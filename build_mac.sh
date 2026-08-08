#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

APP_NAME="PodcastRenderer"
DISPLAY_NAME="Podcast Renderer"
VENDOR_DIR="vendor/macos"
NOTICES="THIRD_PARTY_NOTICES.md"
SOURCE_OFFER="FFMPEG_SOURCE_OFFER.md"
LICENSES="licenses"
INSTALL_GUIDE="installer/MACOS_INSTALL.txt"
BUILD_REQUIREMENTS="requirements-build.txt"
ICON="assets/Podcast Renderer.ico"

need() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "Missing $1. Install it and run this script again." >&2
    exit 1
  }
}

verify_hash() {
  local binary="$1"
  local hash_file="$2"
  if [[ ! -f "$hash_file" ]]; then
    echo "Missing SHA-256 file: $hash_file" >&2
    exit 1
  fi
  local expected
  expected="$(tr -d '[:space:]' < "$hash_file" | tr '[:upper:]' '[:lower:]')"
  if [[ ! "$expected" =~ ^[0-9a-f]{64}$ ]]; then
    echo "Invalid SHA-256 value in $hash_file" >&2
    exit 1
  fi
  printf '%s  %s\n' "$expected" "$binary" | shasum -a 256 --check
}

need python3
need codesign
need hdiutil
need ditto

for required in "$NOTICES" "$SOURCE_OFFER" "$INSTALL_GUIDE" "$BUILD_REQUIREMENTS" "$ICON"; do
  if [[ ! -f "$required" ]]; then
    echo "Missing $required" >&2
    exit 1
  fi
done
if [[ ! -d "$LICENSES" ]]; then
  echo "Missing $LICENSES" >&2
  exit 1
fi
if [[ ! -x "$VENDOR_DIR/ffmpeg" || ! -x "$VENDOR_DIR/ffprobe" ]]; then
  cat >&2 <<'MSG'
Missing self-contained macOS ffmpeg/ffprobe binaries.

Run this first on the target Mac architecture:
  bash scripts/fetch_ffmpeg_macos.sh
MSG
  exit 1
fi

verify_hash "$VENDOR_DIR/ffmpeg" "$VENDOR_DIR/ffmpeg.sha256"
verify_hash "$VENDOR_DIR/ffprobe" "$VENDOR_DIR/ffprobe.sha256"

ENCODERS="$("$VENDOR_DIR/ffmpeg" -hide_banner -encoders 2>/dev/null)"
if [[ "$ENCODERS" != *libx264* ]]; then
  echo "Bundled FFmpeg does not provide the required libx264 encoder" >&2
  exit 1
fi

case "$(uname -m)" in
  arm64)
    ARCH_LABEL="Apple-Silicon"
    EXPECTED_ARCH="arm64"
    ;;
  x86_64)
    ARCH_LABEL="Intel"
    EXPECTED_ARCH="x86_64"
    ;;
  *)
    echo "Unsupported macOS architecture: $(uname -m)" >&2
    exit 1
    ;;
esac

APP_VERSION="$(sed -nE 's/^APP_VERSION = "([0-9]+\.[0-9]+\.[0-9]+)"$/\1/p' main.py)"
if [[ -z "$APP_VERSION" ]]; then
  echo "Could not read APP_VERSION from main.py" >&2
  exit 1
fi

VENV=".venv-build-$(uname -m)"
python3 -m venv "$VENV"
"$VENV/bin/python" -m pip install --disable-pip-version-check --requirement "$BUILD_REQUIREMENTS"

rm -rf build dist "${APP_NAME}.spec"

"$VENV/bin/python" -m PyInstaller \
  --noconfirm \
  --windowed \
  --name "$APP_NAME" \
  --icon "$ICON" \
  --osx-bundle-identifier "io.github.pereponkin.podcastrenderer" \
  --add-binary "$VENDOR_DIR/ffmpeg:bin" \
  --add-binary "$VENDOR_DIR/ffprobe:bin" \
  --add-data "$NOTICES:." \
  --add-data "$SOURCE_OFFER:." \
  --add-data "$LICENSES:licenses" \
  main.py

APP="dist/${APP_NAME}.app"
PLIST="$APP/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Set :CFBundleDisplayName $DISPLAY_NAME" "$PLIST"
/usr/libexec/PlistBuddy -c "Set :CFBundleShortVersionString $APP_VERSION" "$PLIST"
/usr/libexec/PlistBuddy -c "Set :CFBundleVersion $APP_VERSION" "$PLIST"

codesign --force --deep --sign - "$APP"
codesign --verify --deep --strict --verbose=2 "$APP"

file "$APP/Contents/MacOS/$APP_NAME" | grep -q "$EXPECTED_ARCH"
file "$APP/Contents/Frameworks/bin/ffmpeg" | grep -q "$EXPECTED_ARCH"
"$APP/Contents/Frameworks/bin/ffmpeg" -hide_banner -version | sed -n '1p'
"$APP/Contents/Frameworks/bin/ffprobe" -hide_banner -version | sed -n '1p'

PACKAGE_BASENAME="${APP_NAME}-${APP_VERSION}-macOS-${ARCH_LABEL}"
DMG_ROOT="dist/dmg-root"
rm -rf "$DMG_ROOT"
mkdir -p "$DMG_ROOT"
cp -R "$APP" "$DMG_ROOT/"
ln -s /Applications "$DMG_ROOT/Applications"
cp "$INSTALL_GUIDE" "$DMG_ROOT/INSTALL.txt"
cp "$NOTICES" "$SOURCE_OFFER" "$DMG_ROOT/"
cp -R "$LICENSES" "$DMG_ROOT/"

hdiutil create \
  -volname "$DISPLAY_NAME $APP_VERSION" \
  -srcfolder "$DMG_ROOT" \
  -ov \
  -format UDZO \
  "dist/${PACKAGE_BASENAME}.dmg"

ZIP_ROOT="dist/${PACKAGE_BASENAME}"
rm -rf "$ZIP_ROOT"
mkdir -p "$ZIP_ROOT"
cp -R "$APP" "$ZIP_ROOT/"
cp "$INSTALL_GUIDE" "$ZIP_ROOT/INSTALL.txt"
cp "$NOTICES" "$SOURCE_OFFER" "$ZIP_ROOT/"
cp -R "$LICENSES" "$ZIP_ROOT/"
ditto -c -k --sequesterRsrc --keepParent "$ZIP_ROOT" "dist/${PACKAGE_BASENAME}.zip"

rm -rf build "$DMG_ROOT" "$ZIP_ROOT" "${APP_NAME}.spec"

cat <<MSG
Done.

App:
  $APP

Disk image:
  dist/${PACKAGE_BASENAME}.dmg

Zip archive:
  dist/${PACKAGE_BASENAME}.zip
MSG
