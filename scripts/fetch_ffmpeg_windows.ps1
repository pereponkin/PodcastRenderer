[CmdletBinding()]
param(
    [string]$Destination = (Join-Path $PSScriptRoot "..\vendor\windows")
)

$ErrorActionPreference = "Stop"
if ($PSVersionTable.PSVersion.Major -ge 7) {
    $PSNativeCommandUseErrorActionPreference = $true
}

$baseUrl = "https://github.com/shaka-project/static-ffmpeg-binaries/releases/download/n8.1.2-1"
$binaries = @(
    @{
        Name = "ffmpeg.exe"
        HashName = "ffmpeg.sha256"
        Url = "$baseUrl/ffmpeg-win-x64.exe"
        Sha256 = "4044B3924C977AD31229D504C5D5B8685F9553124FBAFF6E9C99048B42830341"
    },
    @{
        Name = "ffprobe.exe"
        HashName = "ffprobe.sha256"
        Url = "$baseUrl/ffprobe-win-x64.exe"
        Sha256 = "FC37CA23D31EE08BB8F7E108EDF3822F6EF3EFC1A8D306BBE0B779190230710B"
    }
)

New-Item -ItemType Directory -Path $Destination -Force | Out-Null

foreach ($binary in $binaries) {
    $target = Join-Path $Destination $binary.Name
    $download = "$target.download"
    Remove-Item -LiteralPath $download -Force -ErrorAction SilentlyContinue

    Write-Host "Downloading $($binary.Name)..."
    Invoke-WebRequest -UseBasicParsing -Uri $binary.Url -OutFile $download
    $actual = (Get-FileHash -LiteralPath $download -Algorithm SHA256).Hash.ToUpperInvariant()
    if ($actual -ne $binary.Sha256) {
        Remove-Item -LiteralPath $download -Force
        throw "SHA-256 mismatch for $($binary.Name)`nExpected: $($binary.Sha256)`nActual:   $actual"
    }

    Move-Item -LiteralPath $download -Destination $target -Force
    $hashFile = Join-Path $Destination $binary.HashName
    Set-Content -LiteralPath $hashFile -Value $binary.Sha256 -Encoding ascii -NoNewline
}

$ffmpeg = Join-Path $Destination "ffmpeg.exe"
$ffprobe = Join-Path $Destination "ffprobe.exe"
$encoders = (& $ffmpeg -hide_banner -encoders 2>&1 | Out-String)
if ($LASTEXITCODE -ne 0 -or $encoders -notmatch '\blibx264\b') {
    throw "Downloaded FFmpeg does not provide the required libx264 encoder"
}
& $ffprobe -hide_banner -version | Select-Object -First 1
if ($LASTEXITCODE -ne 0) {
    throw "Downloaded ffprobe could not be started"
}

Write-Host "Verified FFmpeg binaries in $Destination"
