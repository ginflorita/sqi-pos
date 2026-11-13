param([switch]$ServerOnly)

$ErrorActionPreference = 'Stop'
try {
$root = Split-Path $PSScriptRoot -Parent
$python = Join-Path $root '.venv\Scripts\python.exe'
$runFile = Join-Path $root 'run.py'
$healthCheck = Join-Path $PSScriptRoot 'check_pos.py'
. (Join-Path $PSScriptRoot 'Pos-App-Window.ps1')
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

function Get-PosBuildStatus([bool]$secure) {
    if ($secure) { & $python $healthCheck --cert $cert --check-build 2>$null }
    else { & $python $healthCheck --check-build 2>$null }
    return $LASTEXITCODE
}

function Stop-OutdatedPos([bool]$secure) {
    if (-not (Test-Pos $secure)) { throw 'The server on port 8765 could not be identified as SQI POS. Ask the main laptop owner to check it.' }
    $owners = @(netstat -ano -p tcp | ForEach-Object {
        if ($_ -match '^\s*TCP\s+\S+:8765\s+\S+\s+LISTENING\s+(\d+)\s*$') { [int]$Matches[1] }
    } | Sort-Object -Unique)
    if ($owners.Count -ne 1) { throw 'Could not identify the older SQI POS server on port 8765. Close its black server window, then click Start SQI POS.' }
    $ownerProcess = Get-Process -Id $owners[0] -ErrorAction Stop
    if ($ownerProcess.ProcessName -notin @('python', 'pythonw')) {
        throw 'Another program owns port 8765. Ask the main laptop owner to check it.'
    }
    Write-Output 'Applying the SQI POS update. Please wait...'
    Stop-Process -Id $owners[0] -Force -ErrorAction Stop
    for ($attempt = 0; $attempt -lt 20; $attempt++) {
        if (-not (Test-Port)) { return }
        Start-Sleep -Milliseconds 500
    }
    throw 'The old SQI POS server did not release port 8765. Close its black server window, then click Start SQI POS.'
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
$serverHealthy = Test-Pos $lan
if ($serverHealthy) {
    $buildStatus = Get-PosBuildStatus $lan
    if ($buildStatus -eq 0) { $url = if ($lan) { $httpsUrl } else { $httpUrl } }
    elseif ($buildStatus -eq 2) { Stop-OutdatedPos $lan }
    else { throw 'SQI POS answered, but its version could not be checked. Close its black server window, then click Start SQI POS.' }
}

# A former single-laptop HTTP server can still occupy the port after HTTPS is enabled.
if (-not $url -and $lan -and (Test-Port) -and (Test-Pos $false)) {
    Stop-OutdatedPos $false
}

if (-not $url -and (Test-Port)) {
    if (-not $ServerOnly) { Write-Output 'The POS server is starting or busy. Waiting for it to respond...' }
    for ($attempt = 0; $attempt -lt 6; $attempt++) {
        Start-Sleep -Seconds 1
        if (Test-Pos $lan) {
            $buildStatus = Get-PosBuildStatus $lan
            if ($buildStatus -eq 0) { $url = if ($lan) { $httpsUrl } else { $httpUrl } }
            elseif ($buildStatus -eq 2) { Stop-OutdatedPos $lan }
            else { throw 'SQI POS answered, but its version could not be checked. Close its black server window, then click Start SQI POS.' }
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
    Start-PosAppWindow $url
}
Write-Output "SQI POS is ready: $url"
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
}
