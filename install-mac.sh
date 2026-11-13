#!/bin/bash
# Slice Machine on macOS: Python environment + ~/Applications/Slice Machine.app
#   ./install-mac.sh            install (again) — also after a git pull
#   ./install-mac.sh --remove   take it out again (keeps your settings)
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
SUPPORT="$HOME/Library/Application Support/SliceMachine"
VENV="$SUPPORT/venv"
APP="$HOME/Applications/Slice Machine.app"

if [ "${1:-}" = "--remove" ]; then
  rm -rf "$VENV" "$APP"
  echo "Removed. Settings stay in ~/Library/Preferences/com.slicemachine.SliceMachine.plist."
  exit 0
fi

PY=""
for c in /opt/homebrew/bin/python3 /usr/local/bin/python3 python3; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)'; then PY="$(command -v "$c")"; break; fi
done
[ -n "$PY" ] || { echo "Python 3.9 or newer is needed (brew install python)."; exit 1; }

echo "→ Python environment ($PY) in $VENV …"
mkdir -p "$SUPPORT"
[ -x "$VENV/bin/python" ] || "$PY" -m venv "$VENV"
"$VENV/bin/python" -m pip install --quiet --upgrade pip
# only Qt core / GUI / widgets: drop the full PySide6 if an older install pulled it in
"$VENV/bin/python" -m pip uninstall --quiet -y PySide6 PySide6_Addons 2>/dev/null || true
"$VENV/bin/python" -m pip install --quiet -r "$HERE/requirements-app.txt"

echo "→ $APP"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cat > "$APP/Contents/MacOS/SliceMachine" <<LAUNCH
#!/bin/sh
exec "$VENV/bin/python" "$HERE/slicemachine.py" "\$@"
LAUNCH
chmod +x "$APP/Contents/MacOS/SliceMachine"
[ -f "$HERE/scripts/AppIcon.icns" ] && cp "$HERE/scripts/AppIcon.icns" "$APP/Contents/Resources/AppIcon.icns"
cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>Slice Machine</string>
  <key>CFBundleDisplayName</key><string>Slice Machine</string>
  <key>CFBundleIdentifier</key><string>net.ahab.slicemachine</string>
  <key>CFBundleExecutable</key><string>SliceMachine</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>LSMinimumSystemVersion</key><string>11.0</string>
  <key>NSHighResolutionCapable</key><true/>
</dict></plist>
PLIST
codesign --force --deep --sign - "$APP" >/dev/null 2>&1 || true
echo "Done: $APP"
