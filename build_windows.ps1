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
$sourceOffer = Join-Path $PSScriptRoot "FFMPEG_SOURCE_OFFER.md"
$licenses = Join-Path $PSScriptRoot "licenses"
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
if (-not (Test-Path -LiteralPath $sourceOffer)) {
    throw "Missing $sourceOffer"
}
if (-not (Test-Path -LiteralPath $licenses -PathType Container)) {
    throw "Missing $licenses"
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

$versionLine = Select-String -LiteralPath "main.py" -Pattern '^APP_VERSION = "([0-9]+\.[0-9]+\.[0-9]+)"$'
if (-not $versionLine) {
    throw "Could not read APP_VERSION from main.py"
}
$appVersion = $versionLine.Matches[0].Groups[1].Value
$versionParts = @($appVersion.Split('.') | ForEach-Object { [int]$_ }) + @(0)
$versionTuple = ($versionParts[0..3] -join ", ")
$versionFile = Join-Path $PSScriptRoot "build\windows-version-info.txt"
New-Item -ItemType Directory -Path (Split-Path -Parent $versionFile) -Force | Out-Null
@"
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=($versionTuple),
    prodvers=($versionTuple),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable(
        '040904B0',
        [StringStruct('CompanyName', 'pereponkin'),
         StringStruct('FileDescription', 'Podcast Renderer'),
         StringStruct('FileVersion', '$appVersion'),
         StringStruct('InternalName', 'PodcastRenderer'),
         StringStruct('OriginalFilename', 'PodcastRenderer.exe'),
         StringStruct('ProductName', 'Podcast Renderer'),
         StringStruct('ProductVersion', '$appVersion')]
      )
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"@ | Set-Content -LiteralPath $versionFile -Encoding utf8

python -m PyInstaller `
    --noconfirm `
    --onefile `
    --windowed `
    --name $appName `
    --icon "$icon" `
    --version-file "$versionFile" `
    --add-binary "$ffmpeg;bin" `
    --add-binary "$ffprobe;bin" `
    --add-data "$icon;assets" `
    --add-data "$notices;." `
    --add-data "$sourceOffer;." `
    --add-data "$licenses;licenses" `
    main.py
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller build failed"
}

$portableDir = Join-Path $PSScriptRoot "dist\PodcastRenderer-Windows-Portable"
New-Item -ItemType Directory -Path $portableDir -Force | Out-Null
Copy-Item -LiteralPath "dist\$appName.exe" -Destination $portableDir -Force
Copy-Item -LiteralPath $notices -Destination $portableDir -Force
Copy-Item -LiteralPath $sourceOffer -Destination $portableDir -Force
Copy-Item -LiteralPath $licenses -Destination $portableDir -Recurse -Force
Compress-Archive -Path "$portableDir\*" -DestinationPath "dist\PodcastRenderer-Windows-Portable.zip" -Force
Remove-Item -LiteralPath $portableDir -Recurse -Force

Remove-Item -Recurse -Force "build" -ErrorAction SilentlyContinue
Remove-Item -Force "$appName.spec" -ErrorAction SilentlyContinue

Write-Host ""
Write-Host "Done."
Write-Host "EXE:"
Write-Host "  dist\$appName.exe"
Write-Host "Notices:"
Write-Host "  included in the portable archive"
Write-Host "Portable archive:"
Write-Host "  dist\PodcastRenderer-Windows-Portable.zip"
