#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PROJECT_ROOT="$(cd "$ROOT_DIR/.." && pwd)"
APP_NAME="Ferryman.app"
APP_PATH="$ROOT_DIR/src-tauri/target/release/bundle/macos/$APP_NAME"
DMG_DIR="$ROOT_DIR/src-tauri/target/release/bundle/dmg"
VERSION="0.1.0"
ARCH="$(uname -m)"
DMG_NAME="Ferryman_${VERSION}_${ARCH}.dmg"
DMG_PATH="$DMG_DIR/$DMG_NAME"
VOLUME_NAME="Ferryman"
DIST_DIR="$PROJECT_ROOT/dist"

if [[ ! -d "$APP_PATH" ]]; then
  echo "App bundle not found at $APP_PATH" >&2
  exit 1
fi

# Tauri's unsigned app bundle can contain an ad-hoc executable signature that
# does not seal bundled resources. Re-sign locally so macOS accepts the copied
# app bundle from the DMG during install smoke tests.
codesign --force --deep --sign - "$APP_PATH"
codesign --verify --deep --strict --verbose=2 "$APP_PATH"

mkdir -p "$DMG_DIR"
TMP_DIR="$(mktemp -d /tmp/ferryman-dmg.XXXXXX)"
cleanup() {
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT

cp -R "$APP_PATH" "$TMP_DIR/$APP_NAME"
ln -s /Applications "$TMP_DIR/Applications"
rm -f "$DMG_PATH"

hdiutil create \
  -volname "$VOLUME_NAME" \
  -srcfolder "$TMP_DIR" \
  -ov \
  -format UDZO \
  "$DMG_PATH"

mkdir -p "$DIST_DIR"
rm -rf "$DIST_DIR/$APP_NAME"
cp -R "$APP_PATH" "$DIST_DIR/$APP_NAME"
cp -f "$DMG_PATH" "$DIST_DIR/$DMG_NAME"

echo "Created DMG at $DMG_PATH"
echo "Synced app bundle to $DIST_DIR/$APP_NAME"
echo "Synced DMG to $DIST_DIR/$DMG_NAME"
