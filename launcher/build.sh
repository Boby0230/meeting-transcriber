#!/bin/sh
# Builds "Meeting Transcriber.app" in the project folder from the AppleScript
# source. Double-click that app to start the server and open the browser.
set -e
cd "$(dirname "$0")/.."
APP="Meeting Transcriber.app"
TMP="$(mktemp -d)"
rm -rf "$APP"
osacompile -o "$APP" "launcher/Meeting Transcriber.applescript"

# Custom icon. Needs Pillow; if it's missing the app still works, it just
# keeps the generic AppleScript icon.
if .venv/bin/python launcher/make_icon.py "$TMP/icon.iconset" 2>/dev/null; then
  iconutil -c icns "$TMP/icon.iconset" -o "$APP/Contents/Resources/applet.icns"
  # Use applet.icns instead of the default script icon baked into Assets.car.
  rm -f "$APP/Contents/Resources/Assets.car"
  /usr/libexec/PlistBuddy -c "Delete :CFBundleIconName" "$APP/Contents/Info.plist" 2>/dev/null || true
else
  echo "⚠️  Skipped custom icon (Pillow not installed: .venv/bin/pip install Pillow)"
fi
rm -rf "$TMP"

xattr -cr "$APP"  # codesign refuses files with Finder metadata
# Re-sign after modifying the bundle. Best-effort: the app still runs if this
# fails, so do not abort a build that has already assembled successfully.
codesign --force --deep --sign - "$APP" 2>/dev/null || echo "⚠️  codesign skipped"
touch "$APP"
echo "Built $APP"
