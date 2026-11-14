$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$launcher = Join-Path $root 'Open-POS.cmd'
$icon = Join-Path $root 'static\sqi-pos.ico'
$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    throw 'Run Install-POS.cmd on the main laptop before creating shortcuts.'
}
if (-not (Test-Path -LiteralPath $icon -PathType Leaf)) {
    throw 'The SQI shortcut icon is missing from the static folder.'
}
$desktop = [Environment]::GetFolderPath('Desktop')
$startup = [Environment]::GetFolderPath('Startup')
if (-not $desktop -or -not $startup) { throw 'Windows Desktop or Startup folder was not found.' }
$shell = New-Object -ComObject WScript.Shell

foreach ($shortcutPath in @(
    (Join-Path $desktop 'Start SQI POS.lnk'),
    (Join-Path $root 'Start SQI POS.lnk'),
    (Join-Path $root 'Open SQI POS.lnk')
)) {
    $open = $shell.CreateShortcut($shortcutPath)
    $open.TargetPath = $launcher
    $open.WorkingDirectory = $root
    $open.Description = 'Start the HTTPS POS server for both laptops and open the POS app window'
    $open.IconLocation = "$icon,0"
    $open.Save()
}

$auto = $shell.CreateShortcut((Join-Path $startup 'SQI POS Server.lnk'))
$auto.TargetPath = (Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe')
$auto.Arguments = '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + (Join-Path $PSScriptRoot 'Open-POS.ps1') + '" -ServerOnly'
$auto.WorkingDirectory = $root
$auto.WindowStyle = 7
$auto.Description = 'Start the SQI POS server when this Windows user signs in'
$auto.IconLocation = "$icon,0"
$auto.Save()

Write-Output 'Created branded POS icons on the desktop and in this folder, plus the Windows sign-in startup shortcut.'
