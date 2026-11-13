function Get-PosAppBrowser {
    $preferred = (Get-ItemProperty 'HKCU:\Software\Microsoft\Windows\Shell\Associations\UrlAssociations\https\UserChoice' -ErrorAction SilentlyContinue).ProgId
    $browsers = if ($preferred -like 'MSEdgeHTM*') {
        @('Microsoft\Edge\Application\msedge.exe', 'Google\Chrome\Application\chrome.exe')
    } else {
        @('Google\Chrome\Application\chrome.exe', 'Microsoft\Edge\Application\msedge.exe')
    }
    $locations = @(
        $env:ProgramFiles,
        ${env:ProgramFiles(x86)},
        $env:LOCALAPPDATA
    ) | Where-Object { $_ }
    foreach ($name in $browsers) {
        foreach ($location in $locations) {
            $candidate = Join-Path $location $name
            if (Test-Path -LiteralPath $candidate -PathType Leaf) { return $candidate }
        }
    }
    foreach ($name in $browsers) {
        $command = Get-Command (Split-Path $name -Leaf) -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($command) { return $command.Source }
    }
    throw 'Chrome or Microsoft Edge is required for the SQI POS app window. Install one of them and try again.'
}

function Start-PosAppWindow([string]$Url) {
    if ($Url -notin @('http://localhost:8765', 'https://localhost:8765')) {
        throw 'The POS app address is invalid.'
    }
    $browser = Get-PosAppBrowser
    Start-Process -FilePath $browser -ArgumentList "--app=$Url", '--new-window'
}
