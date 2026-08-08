#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

DESTINATION="${1:-vendor/macos}"
BASE_URL="https://github.com/shaka-project/static-ffmpeg-binaries/releases/download/n8.1.2-1"

case "$(uname -m)" in
  arm64)
    FFMPEG_ASSET="ffmpeg-osx-arm64"
    FFPROBE_ASSET="ffprobe-osx-arm64"
    FFMPEG_SHA256="e7b9fcd97f95f333512d6e8b8ac24d9dbc08f189f36047695499bd7b57214b22"
    FFPROBE_SHA256="ded4c698b8ff38d0bc1fd30fcc5e768dc46f58bc15a8dfd61f98615ba49cde5c"
    ;;
  x86_64)
    FFMPEG_ASSET="ffmpeg-osx-x64"
    FFPROBE_ASSET="ffprobe-osx-x64"
    FFMPEG_SHA256="62c87854d851f202fc4a29bdda0fe7b6ebcddd37b863482ce1bdc81151b03fe4"
    FFPROBE_SHA256="d530823f480a3c7eb6334f18a00197d1e9f1070e86172b9aa89c4bf4022bd879"
    ;;
  *)
    echo "Unsupported macOS architecture: $(uname -m)" >&2
    exit 1
    ;;
esac

mkdir -p "$DESTINATION"

download() {
  local asset="$1"
  local target="$2"
  local expected="$3"
  local partial="${target}.download"

  rm -f "$partial"
  echo "Downloading $asset..."
  curl --fail --location --retry 3 --output "$partial" "$BASE_URL/$asset"
  printf '%s  %s\n' "$expected" "$partial" | shasum -a 256 --check
  mv "$partial" "$target"
  chmod +x "$target"
  printf '%s' "$expected" > "${target}.sha256"
}

download "$FFMPEG_ASSET" "$DESTINATION/ffmpeg" "$FFMPEG_SHA256"
download "$FFPROBE_ASSET" "$DESTINATION/ffprobe" "$FFPROBE_SHA256"

ENCODERS="$("$DESTINATION/ffmpeg" -hide_banner -encoders 2>/dev/null)"
if [[ "$ENCODERS" != *libx264* ]]; then
  echo "Downloaded FFmpeg does not provide the required libx264 encoder" >&2
  exit 1
fi
"$DESTINATION/ffprobe" -hide_banner -version | sed -n '1p'

echo "Verified FFmpeg binaries in $DESTINATION"
