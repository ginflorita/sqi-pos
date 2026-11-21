param([string]$Address, [string]$ShortcutDirectory = [Environment]::GetFolderPath('Desktop'))

$ErrorActionPreference = 'Stop'
$scriptPath = $MyInvocation.MyCommand.Path
if (-not $scriptPath) {
    throw 'Run Create-Cashier-Shortcut.cmd from the extracted SQI POS folder.'
}
$scriptDirectory = [System.IO.Path]::GetDirectoryName($scriptPath)
$root = [System.IO.Path]::GetDirectoryName($scriptDirectory)
if (-not $Address) {
    $Address = Read-Host 'Enter the main laptop IP address or hostname (for example 192.168.1.115)'
}
$address = $address.Trim()
if ($address -notmatch '^[a-zA-Z0-9.-]+$' -or $address -eq 'localhost' -or $address -eq '127.0.0.1') {
    throw 'Enter the main laptop network address, without https:// or a port number.'
}
$url = "https://${address}:8765/"
$icon = Join-Path $root 'static\sqi-pos.ico'
if (-not (Test-Path -LiteralPath $icon -PathType Leaf)) {
    throw "The SQI shortcut icon is missing at $icon. Copy static\sqi-pos.ico from the main POS folder, or extract the complete cashier shortcut setup kit."
}
. (Join-Path $scriptDirectory 'Pos-App-Window.ps1')
$browser = Get-PosAppBrowser
if (-not $ShortcutDirectory -or -not (Test-Path -LiteralPath $ShortcutDirectory -PathType Container)) {
    throw 'The shortcut folder was not found.'
}
$shortcut = Join-Path $ShortcutDirectory 'SQI POS Cashier.lnk'
$shell = New-Object -ComObject WScript.Shell
$open = $shell.CreateShortcut($shortcut)
$open.TargetPath = $browser
$open.Arguments = "--app=$url --new-window"
$open.WorkingDirectory = Split-Path $browser -Parent
$open.Description = 'Open SQI POS in a dedicated app window on the second laptop'
$open.IconLocation = "$icon,0"
$open.Save()
Write-Output "Created $shortcut"
Write-Output "Double-click it to open $url without browser tabs or an address bar."
Write-Output 'The POS server and database stay on the main laptop.'
