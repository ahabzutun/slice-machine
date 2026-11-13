#!/bin/bash
# Copy the shared look (theme, widgets, stage, draw) from Kontrolleur, so both apps stay identical.
#   scripts/sync-look.sh [path to Kontrolleur's package folder]
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
SRC="${1:-}"
if [ -z "$SRC" ]; then
  for c in "$HOME/projects/eurorack/dualsense-eurorack-midi/kontrolleur/kontrolleur" \
           "$HOME/projects/eurorack/kontrolleur/kontrolleur" \
           "$HOME/dualsense-eurorack-midi/kontrolleur/kontrolleur"; do
    [ -f "$c/theme.py" ] && SRC="$c" && break
  done
fi
[ -n "$SRC" ] && [ -f "$SRC/theme.py" ] || { echo "Kontrolleur not found. Pass its package folder (the one with theme.py)."; exit 1; }
for f in theme.py widgets.py stage.py draw.py; do
  if cmp -s "$SRC/$f" "$HERE/slicemachine/$f"; then echo "  $f  same"; else cp "$SRC/$f" "$HERE/slicemachine/$f"; echo "  $f  updated"; fi
done
