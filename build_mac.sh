#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

APP_NAME="PodcastRenderer"
VENV=".venv-build"
VENDOR_DIR="vendor/macos"
NOTICES="THIRD_PARTY_NOTICES.md"
PACKAGE_DIR="dist/${APP_NAME}-macOS"

need() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "Missing $1. Install it and run this script again."
    exit 1
  }
}

find_binary() {
  local name="$1"
  if [[ -x "$VENDOR_DIR/$name" ]]; then
    printf '%s\n' "$VENDOR_DIR/$name"
    return
  fi
  command -v "$name" || true
}

need python3

if [[ ! -f "$NOTICES" ]]; then
  echo "Missing $NOTICES"
  exit 1
fi

FFMPEG="$(find_binary ffmpeg)"
FFPROBE="$(find_binary ffprobe)"

if [[ -z "$FFMPEG" || -z "$FFPROBE" ]]; then
  cat <<'MSG'
Missing ffmpeg/ffprobe.

Best option for a self-contained app:
  1. Put macOS ffmpeg and ffprobe binaries here:
       vendor/macos/ffmpeg
       vendor/macos/ffprobe
  2. Make them executable:
       chmod +x vendor/macos/ffmpeg vendor/macos/ffprobe
  3. Run this script again.

Fallback for build-only machines:
  brew install ffmpeg

Note: Homebrew ffmpeg may depend on Homebrew dylibs. For an app you send to
another Mac, static/self-contained ffmpeg binaries in vendor/macos are safer.
MSG
  exit 1
fi

if [[ "$FFMPEG" != "$VENDOR_DIR/ffmpeg" || "$FFPROBE" != "$VENDOR_DIR/ffprobe" ]]; then
  cat <<MSG
Using ffmpeg/ffprobe from PATH:
  $FFMPEG
  $FFPROBE

Warning: if these are Homebrew binaries, the app may require Homebrew libraries
on the target Mac. For a safer app, place self-contained binaries in:
  $VENDOR_DIR/ffmpeg
  $VENDOR_DIR/ffprobe

MSG
fi

python3 -m venv "$VENV"
"$VENV/bin/python" -m pip install --upgrade pip pyinstaller

rm -rf build dist "${APP_NAME}.spec"

"$VENV/bin/python" -m PyInstaller \
  --noconfirm \
  --windowed \
  --name "$APP_NAME" \
  --add-binary "$FFMPEG:bin" \
  --add-binary "$FFPROBE:bin" \
  --add-data "$NOTICES:." \
  main.py

if command -v codesign >/dev/null 2>&1; then
  codesign --force --deep --sign - "dist/${APP_NAME}.app" || true
fi

cp "$NOTICES" "dist/$NOTICES"
rm -rf "$PACKAGE_DIR"
mkdir -p "$PACKAGE_DIR"
cp -R "dist/${APP_NAME}.app" "$PACKAGE_DIR/"
cp "$NOTICES" "$PACKAGE_DIR/$NOTICES"
ditto -c -k --sequesterRsrc --keepParent "$PACKAGE_DIR" "dist/${APP_NAME}-macOS.zip"

cat <<MSG
Done.

App:
  dist/${APP_NAME}.app

Zip to send:
  dist/${APP_NAME}-macOS.zip

Third-party notices:
  dist/${NOTICES}
MSG
