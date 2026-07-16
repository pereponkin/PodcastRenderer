$ErrorActionPreference = "Stop"
if ($PSVersionTable.PSVersion.Major -ge 7) {
    $PSNativeCommandUseErrorActionPreference = $true
}

Set-Location -LiteralPath $PSScriptRoot

$appName = "PodcastRenderer"
$ffmpeg = Join-Path $PSScriptRoot "vendor\windows\ffmpeg.exe"
$ffprobe = Join-Path $PSScriptRoot "vendor\windows\ffprobe.exe"
$ffmpegHash = Join-Path $PSScriptRoot "vendor\windows\ffmpeg.sha256"
$ffprobeHash = Join-Path $PSScriptRoot "vendor\windows\ffprobe.sha256"
$icon = Join-Path $PSScriptRoot "assets\Podcast Renderer.ico"
$notices = Join-Path $PSScriptRoot "THIRD_PARTY_NOTICES.md"
$buildRequirements = Join-Path $PSScriptRoot "requirements-build.txt"

function Assert-FileHash {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$HashFile
    )

    if (-not (Test-Path -LiteralPath $HashFile)) {
        throw "Missing SHA-256 file: $HashFile"
    }
    $expected = (Get-Content -LiteralPath $HashFile -Raw).Trim().ToUpperInvariant()
    if ($expected -notmatch '^[0-9A-F]{64}$') {
        throw "Invalid SHA-256 value in $HashFile"
    }
    $actual = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToUpperInvariant()
    if ($actual -ne $expected) {
        throw "SHA-256 mismatch for $Path`nExpected: $expected`nActual:   $actual"
    }
}

if (-not (Test-Path -LiteralPath $ffmpeg)) {
    throw "Missing $ffmpeg"
}
if (-not (Test-Path -LiteralPath $ffprobe)) {
    throw "Missing $ffprobe"
}
if (-not (Test-Path -LiteralPath $icon)) {
    throw "Missing $icon"
}
if (-not (Test-Path -LiteralPath $notices)) {
    throw "Missing $notices"
}
if (-not (Test-Path -LiteralPath $buildRequirements)) {
    throw "Missing $buildRequirements"
}

Assert-FileHash -Path $ffmpeg -HashFile $ffmpegHash
Assert-FileHash -Path $ffprobe -HashFile $ffprobeHash

$nativeErrors = $PSNativeCommandUseErrorActionPreference
$PSNativeCommandUseErrorActionPreference = $false
python -m pip install --disable-pip-version-check --requirement $buildRequirements
if ($LASTEXITCODE -ne 0) {
    throw "Failed to install pinned build requirements"
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
    --add-data "$notices;." `
    main.py
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller build failed"
}

Copy-Item -LiteralPath $notices -Destination "dist\THIRD_PARTY_NOTICES.md" -Force
Compress-Archive `
    -LiteralPath "dist\$appName.exe", "dist\THIRD_PARTY_NOTICES.md" `
    -DestinationPath "dist\$appName-windows.zip" `
    -Force

Remove-Item -Recurse -Force "build" -ErrorAction SilentlyContinue
Remove-Item -Force "$appName.spec" -ErrorAction SilentlyContinue

Write-Host ""
Write-Host "Done."
Write-Host "EXE:"
Write-Host "  dist\$appName.exe"
Write-Host "Notices:"
Write-Host "  dist\THIRD_PARTY_NOTICES.md"
Write-Host "Zip to send:"
Write-Host "  dist\$appName-windows.zip"
