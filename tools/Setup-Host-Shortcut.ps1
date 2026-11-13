$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$launcher = Join-Path $root 'Open-POS.cmd'
$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    throw 'Run Install-POS.cmd on the main laptop before creating shortcuts.'
}
$desktop = [Environment]::GetFolderPath('Desktop')
$startup = [Environment]::GetFolderPath('Startup')
if (-not $desktop -or -not $startup) { throw 'Windows Desktop or Startup folder was not found.' }
$shell = New-Object -ComObject WScript.Shell

$open = $shell.CreateShortcut((Join-Path $desktop 'Start SQI POS.lnk'))
$open.TargetPath = $launcher
$open.WorkingDirectory = $root
$open.Description = 'Start the HTTPS POS server for both laptops and open the POS app window'
$open.Save()

$auto = $shell.CreateShortcut((Join-Path $startup 'SQI POS Server.lnk'))
$auto.TargetPath = (Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe')
$auto.Arguments = '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + (Join-Path $PSScriptRoot 'Open-POS.ps1') + '" -ServerOnly'
$auto.WorkingDirectory = $root
$auto.WindowStyle = 7
$auto.Description = 'Start the SQI POS server when this Windows user signs in'
$auto.Save()

Write-Output 'Created the Start SQI POS desktop icon and Windows sign-in startup shortcut.'
