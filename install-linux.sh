#!/bin/bash
# Slice Machine on Linux (Fedora, Debian/Ubuntu, Raspberry Pi OS …)
#   ./install-linux.sh            install for this user: venv, launcher, menu entry
#   ./install-linux.sh --remove   take it out again (keeps your settings)
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
DATA="${XDG_DATA_HOME:-$HOME/.local/share}"
VENV="$DATA/slicemachine/venv"
BIN="$HOME/.local/bin/slicemachine"
DESKTOP="$DATA/applications/slicemachine.desktop"
ICON="$DATA/icons/hicolor/256x256/apps/slicemachine.png"

if [ "${1:-}" = "--remove" ]; then
  rm -rf "$VENV" "$BIN" "$DESKTOP" "$ICON"
  echo "Removed. Settings stay in ~/.config/SliceMachine/."
  exit 0
fi

PY="$(command -v python3 || true)"
[ -n "$PY" ] || { echo "python3 is missing (Fedora: sudo dnf install python3)"; exit 1; }
"$PY" - <<'PYEOF' || { echo "Python 3.9 or newer is needed."; exit 1; }
import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)
PYEOF

echo "→ Python environment in $VENV …"
mkdir -p "$(dirname "$VENV")"
[ -x "$VENV/bin/python" ] || "$PY" -m venv "$VENV"
"$VENV/bin/python" -m pip install --quiet --upgrade pip
"$VENV/bin/python" -m pip uninstall --quiet -y PySide6 PySide6_Addons 2>/dev/null || true
"$VENV/bin/python" -m pip install --quiet -r "$HERE/requirements-app.txt" \
  || { echo "pip could not install the requirements (librosa, PySide6-Essentials …)."; exit 1; }

echo "→ Launcher $BIN"
mkdir -p "$(dirname "$BIN")"
cat > "$BIN" <<LAUNCH
#!/bin/sh
exec "$VENV/bin/python" "$HERE/slicemachine.py" "\$@"
LAUNCH
chmod +x "$BIN"

echo "→ Menu entry"
mkdir -p "$(dirname "$DESKTOP")" "$(dirname "$ICON")"
cp "$HERE/slicemachine/icon.png" "$ICON"
cat > "$DESKTOP" <<DESK
[Desktop Entry]
Type=Application
Name=Slice Machine
GenericName=Sample chain slicer
Comment=Sample chains and slices for the ER-301, the Percussa SSP (GRID) and the NerdSEQ
Exec=$BIN
Icon=slicemachine
Terminal=false
Categories=AudioVideo;Audio;Music;
StartupWMClass=slicemachine
DESK
command -v update-desktop-database >/dev/null && update-desktop-database "$DATA/applications" >/dev/null 2>&1 || true
command -v gtk-update-icon-cache >/dev/null && gtk-update-icon-cache -q "$DATA/icons/hicolor" >/dev/null 2>&1 || true

command -v pw-play >/dev/null || command -v paplay >/dev/null || command -v aplay >/dev/null \
  || echo "note: no audio player found for listening to slices (Fedora: sudo dnf install pipewire-utils)"
case ":$PATH:" in *":$HOME/.local/bin:"*) ;; *) echo "note: add ~/.local/bin to your PATH to start it with 'slicemachine'";; esac
echo "Done. Start Slice Machine from the app menu or with: slicemachine"
