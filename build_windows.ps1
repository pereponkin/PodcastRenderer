$ErrorActionPreference = "Stop"
if ($PSVersionTable.PSVersion.Major -ge 7) {
    $PSNativeCommandUseErrorActionPreference = $true
}

Set-Location -LiteralPath $PSScriptRoot

$appName = "PodcastRenderer"
$ffmpeg = Join-Path $PSScriptRoot "vendor\windows\ffmpeg.exe"
$ffprobe = Join-Path $PSScriptRoot "vendor\windows\ffprobe.exe"
$icon = Join-Path $PSScriptRoot "assets\Podcast Renderer.ico"

if (-not (Test-Path -LiteralPath $ffmpeg)) {
    throw "Missing $ffmpeg"
}
if (-not (Test-Path -LiteralPath $ffprobe)) {
    throw "Missing $ffprobe"
}
if (-not (Test-Path -LiteralPath $icon)) {
    throw "Missing $icon"
}

$nativeErrors = $PSNativeCommandUseErrorActionPreference
$PSNativeCommandUseErrorActionPreference = $false
python -m PyInstaller --version *> $null
$hasPyInstaller = ($LASTEXITCODE -eq 0)
if (-not $hasPyInstaller) {
    python -m pip install pyinstaller
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to install PyInstaller"
    }
}
$PSNativeCommandUseErrorActionPreference = $nativeErrors

Remove-Item -Recurse -Force "build", "dist" -ErrorAction SilentlyContinue
Remove-Item -Force "$appName.spec" -ErrorAction SilentlyContinue

python -m PyInstaller `
    --noconfirm `
    --onefile `
    --windowed `
    --name $appName `
    --icon "$icon" `
    --add-binary "$ffmpeg;bin" `
    --add-binary "$ffprobe;bin" `
    --add-data "$icon;assets" `
    main.py
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller build failed"
}

Write-Host ""
Write-Host "Done."
Write-Host "EXE:"
Write-Host "  dist\$appName.exe"
