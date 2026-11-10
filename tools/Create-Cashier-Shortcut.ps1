param([string]$Address)

$ErrorActionPreference = 'Stop'
if (-not $Address) {
    $Address = Read-Host 'Enter the main laptop IP address or hostname (for example 192.168.1.115)'
}
$address = $address.Trim()
if ($address -notmatch '^[a-zA-Z0-9.-]+$' -or $address -eq 'localhost' -or $address -eq '127.0.0.1') {
    throw 'Enter the main laptop network address, without https:// or a port number.'
}
$url = "https://${address}:8765/"
$root = Split-Path $PSScriptRoot -Parent
$shortcut = Join-Path $root 'SQI-POS-Second-Laptop.url'
@('[InternetShortcut]', "URL=$url") | Set-Content -LiteralPath $shortcut -Encoding Ascii
Write-Output "Created $shortcut"
Write-Output 'Copy this file to the second laptop Desktop after installing the trusted certificate there.'
Write-Output "The icon opens $url in the usual browser. It does not install another POS database."
