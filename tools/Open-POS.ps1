param([switch]$ServerOnly)

$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$python = Join-Path $root '.venv\Scripts\python.exe'
$runFile = Join-Path $root 'run.py'
$runtime = Join-Path $root '.runtime'
$cert = Join-Path $root 'certs\pos.crt'
$key = Join-Path $root 'certs\pos.key'
$httpUrl = 'http://localhost:8765'
$httpsUrl = 'https://localhost:8765'
$httpHealth = 'http://127.0.0.1:8765'
$httpsHealth = 'https://127.0.0.1:8765'

function Test-Pos([string]$url) {
    try {
        $response = Invoke-WebRequest -Uri "$url/api/state" -UseBasicParsing -TimeoutSec 2
        return $response.StatusCode -eq 200
    } catch {
        return $false
    }
}

function Test-Port {
    $socket = New-Object System.Net.Sockets.TcpClient
    try {
        $result = $socket.BeginConnect('127.0.0.1', 8765, $null, $null)
        return ($result.AsyncWaitHandle.WaitOne(500) -and $socket.Connected)
    } catch {
        return $false
    } finally {
        $socket.Close()
    }
}

if (-not (Test-Path -LiteralPath $python) -or -not (Test-Path -LiteralPath $runFile)) {
    throw 'POS is not installed on this main laptop. Run Install-POS.cmd first.'
}

$url = $null
if (Test-Pos $httpsHealth) { $url = $httpsUrl }
elseif (Test-Pos $httpHealth) { $url = $httpUrl }

if (-not $url) {
    if (Test-Port) {
        throw 'Port 8765 is already in use, but SQI POS did not respond. Ask the person who set up this laptop to check it.'
    }
    if ((Test-Path -LiteralPath $cert) -xor (Test-Path -LiteralPath $key)) {
        throw 'Only one HTTPS certificate file was found. Both certs\pos.crt and certs\pos.key are required.'
    }
    $lan = (Test-Path -LiteralPath $cert) -and (Test-Path -LiteralPath $key)
    $url = if ($lan) { $httpsUrl } else { $httpUrl }
    New-Item -ItemType Directory -Path $runtime -Force | Out-Null
    $arguments = '"' + $runFile + '"'
    if ($lan) {
        $arguments += ' --lan --cert "' + $cert + '" --key "' + $key + '"'
    }
    $process = Start-Process -FilePath $python -ArgumentList $arguments -WorkingDirectory $root `
        -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $runtime 'pos-launcher.stdout.log') `
        -RedirectStandardError (Join-Path $runtime 'pos-launcher.stderr.log')
    $ready = $false
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        $healthUrl = if ($lan) { $httpsHealth } else { $httpHealth }
        if (Test-Pos $healthUrl) { $ready = $true; break }
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
