param(
    [string]$OutputDirectory = (Join-Path (Split-Path $PSScriptRoot -Parent) 'dist')
)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$pythonVersion = '3.13.16'
$installerName = "python-$pythonVersion-amd64.exe"
$installerUrl = "https://www.python.org/ftp/python/$pythonVersion/$installerName"
$packageName = "SQI-POS-Offline-Windows-x64"
$buildRoot = Join-Path $OutputDirectory '.build'
$packageRoot = Join-Path $buildRoot $packageName
$wheelhouse = Join-Path $packageRoot 'wheelhouse'
$installers = Join-Path $packageRoot 'installers'
$zipPath = Join-Path $OutputDirectory "$packageName.zip"

if (Test-Path $buildRoot) { Remove-Item -LiteralPath $buildRoot -Recurse -Force }
New-Item -ItemType Directory -Path $packageRoot,$wheelhouse,$installers -Force | Out-Null

$runtimeItems = @(
    '.gitattributes', 'Install-POS.cmd', 'OFFLINE-INSTALL.txt', 'README.md',
    'requirements.txt', 'run.py', 'Start-POS.cmd', 'Open-POS.cmd',
    'Setup-Host-Shortcut.cmd', 'Create-Cashier-Shortcut.cmd', 'Start-Print-Helper.cmd',
    'docs', 'pos', 'static', 'templates', 'tools'
)
foreach ($item in $runtimeItems) {
    $source = Join-Path $root $item
    $destination = Join-Path $packageRoot $item
    if (Test-Path $source -PathType Container) {
        Copy-Item -LiteralPath $source -Destination $destination -Recurse
    } else {
        Copy-Item -LiteralPath $source -Destination $destination
    }
}
Get-ChildItem -LiteralPath $packageRoot -Directory -Recurse -Force |
    Where-Object Name -eq '__pycache__' |
    Remove-Item -Recurse -Force

$installerPath = Join-Path $installers $installerName
Invoke-WebRequest -Uri $installerUrl -OutFile $installerPath
$signature = Get-AuthenticodeSignature -LiteralPath $installerPath
if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'Python|Open Source') {
    throw "The downloaded Python installer does not have a valid expected signature: $($signature.Status)"
}

$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) { $python = 'python' }
& $python -m pip download --disable-pip-version-check --only-binary=:all: `
    --platform win_amd64 --python-version 313 --implementation cp --abi cp313 `
    --dest $wheelhouse -r (Join-Path $root 'requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'Could not download the offline Python packages.' }

$hashLines = @()
Get-ChildItem -LiteralPath $installers,$wheelhouse -File | Sort-Object Name | ForEach-Object {
    $relative = $_.FullName.Substring($packageRoot.Length + 1)
    $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $_.FullName).Hash.ToLowerInvariant()
    $hashLines += "$hash  $relative"
}
$hashLines | Set-Content -LiteralPath (Join-Path $packageRoot 'SHA256SUMS.txt') -Encoding utf8

if (Test-Path $zipPath) { Remove-Item -LiteralPath $zipPath -Force }
Compress-Archive -LiteralPath $packageRoot -DestinationPath $zipPath -CompressionLevel Optimal
$zipHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $zipPath).Hash.ToLowerInvariant()
$zipHashPath = "$zipPath.sha256.txt"
"$zipHash  $(Split-Path $zipPath -Leaf)" | Set-Content -LiteralPath $zipHashPath -Encoding ascii
Remove-Item -LiteralPath $buildRoot -Recurse -Force
Write-Output $zipPath
Write-Output $zipHashPath
