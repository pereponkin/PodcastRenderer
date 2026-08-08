[CmdletBinding()]
param(
    [string]$IsccPath = ""
)

$ErrorActionPreference = "Stop"
if ($PSVersionTable.PSVersion.Major -ge 7) {
    $PSNativeCommandUseErrorActionPreference = $true
}

Set-Location -LiteralPath $PSScriptRoot

& (Join-Path $PSScriptRoot "build_windows.ps1")

if (-not $IsccPath) {
    $command = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    if ($command) {
        $IsccPath = $command.Source
    }
}
if (-not $IsccPath) {
    $candidates = @(
        "C:\Program Files\Inno Setup 7\ISCC.exe",
        "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 7\ISCC.exe"),
        (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe")
    )
    $IsccPath = $candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
}
if (-not $IsccPath -or -not (Test-Path -LiteralPath $IsccPath)) {
    throw "Inno Setup compiler was not found. Install Inno Setup 6 or 7, or pass -IsccPath."
}

$versionLine = Select-String -LiteralPath "main.py" -Pattern '^APP_VERSION = "([0-9]+\.[0-9]+\.[0-9]+)"$'
if (-not $versionLine) {
    throw "Could not read APP_VERSION from main.py"
}
$appVersion = $versionLine.Matches[0].Groups[1].Value

& $IsccPath "/DAppVersion=$appVersion" "installer\PodcastRenderer.iss"
if ($LASTEXITCODE -ne 0) {
    throw "Inno Setup build failed"
}

$installer = Join-Path $PSScriptRoot "dist\PodcastRenderer-Setup.exe"
if (-not (Test-Path -LiteralPath $installer)) {
    throw "Installer was not created: $installer"
}

Write-Host ""
Write-Host "Installer:"
Write-Host "  dist\PodcastRenderer-Setup.exe"
