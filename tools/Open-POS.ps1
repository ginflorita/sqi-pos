param([switch]$ServerOnly)

$ErrorActionPreference = 'Stop'
try {
$root = Split-Path $PSScriptRoot -Parent
$python = Join-Path $root '.venv\Scripts\python.exe'
$runFile = Join-Path $root 'run.py'
$healthCheck = Join-Path $PSScriptRoot 'check_pos.py'
$runtime = Join-Path $root '.runtime'
$cert = Join-Path $root 'certs\pos.crt'
$key = Join-Path $root 'certs\pos.key'
$httpUrl = 'http://localhost:8765'
$httpsUrl = 'https://localhost:8765'
function Test-Pos([bool]$secure) {
    if ($secure) { & $python $healthCheck --cert $cert 2>$null }
    else { & $python $healthCheck 2>$null }
    return $LASTEXITCODE -eq 0
}

function Test-Port {
    foreach ($endpoint in [System.Net.NetworkInformation.IPGlobalProperties]::GetIPGlobalProperties().GetActiveTcpListeners()) {
        if ($endpoint.Port -eq 8765) { return $true }
    }
    return $false
}

if (-not (Test-Path -LiteralPath $python) -or -not (Test-Path -LiteralPath $runFile) -or -not (Test-Path -LiteralPath $healthCheck)) {
    throw 'POS is not installed on this main laptop. Run Install-POS.cmd first.'
}

$hasCert = Test-Path -LiteralPath $cert
$hasKey = Test-Path -LiteralPath $key
if ($hasCert -xor $hasKey) {
    throw 'Only one HTTPS certificate file was found. Both certs\pos.crt and certs\pos.key are required.'
}
$lan = $hasCert -and $hasKey
$url = $null
if ($lan -and (Test-Pos $true)) { $url = $httpsUrl }
elseif (-not $lan -and (Test-Pos $false)) { $url = $httpUrl }

if (-not $url -and (Test-Port)) {
    if (-not $ServerOnly) { Write-Output 'The POS server is starting or busy. Waiting for it to respond...' }
    for ($attempt = 0; $attempt -lt 6; $attempt++) {
        Start-Sleep -Seconds 1
        if (Test-Pos $lan) {
            $url = if ($lan) { $httpsUrl } else { $httpUrl }
            break
        }
    }
    if (-not $url) {
        if ($lan -and (Test-Pos $false)) {
            throw 'An old single-laptop POS server is running. Close its server window or restart the main laptop, then click Start SQI POS again.'
        }
        throw 'Port 8765 is occupied, but SQI POS still did not answer after waiting. Ask the person who set up this laptop to check the running server.'
    }
}

if (-not $url) {
    $url = if ($lan) { $httpsUrl } else { $httpUrl }
    New-Item -ItemType Directory -Path $runtime -Force | Out-Null
    $stdin = Join-Path $runtime 'pos-launcher.stdin.txt'
    if (-not (Test-Path -LiteralPath $stdin)) { New-Item -ItemType File -Path $stdin | Out-Null }
    if (-not $ServerOnly) { Write-Output 'Starting SQI POS. Please wait...' }
    $arguments = '"' + $runFile + '"'
    if ($lan) {
        $arguments += ' --lan --cert "' + $cert + '" --key "' + $key + '"'
    }
    $process = Start-Process -FilePath $python -ArgumentList $arguments -WorkingDirectory $root `
        -WindowStyle Hidden -PassThru `
        -RedirectStandardInput $stdin `
        -RedirectStandardOutput (Join-Path $runtime 'pos-launcher.stdout.log') `
        -RedirectStandardError (Join-Path $runtime 'pos-launcher.stderr.log')
    $ready = $false
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        if (Test-Pos $lan) { $ready = $true; break }
        if ($process.HasExited) { break }
        Start-Sleep -Seconds 1
    }
    if (-not $ready) {
        $log = Join-Path $runtime 'pos-launcher.stderr.log'
        $detail = if (Test-Path -LiteralPath $log) { (Get-Content -LiteralPath $log -Tail 6) -join ' ' } else { '' }
        throw "SQI POS did not start. $detail"
    }
}

if (-not $ServerOnly) {
    Start-Process $url
}
Write-Output "SQI POS is ready: $url"
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
}
