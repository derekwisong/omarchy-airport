#!/usr/bin/env bash
# Copy this plugin into the Omarchy user plugin directory and enable it.
# Saving files there hot-reloads the shell, so re-running this applies edits.
set -euo pipefail
cd "$(dirname "$0")"

ID=$(python3 -c "import json;print(json.load(open('manifest.json'))['id'])")
DEST="$HOME/.config/omarchy/plugins/$ID"

mkdir -p "$DEST"
cp -r manifest.json Model.js Panel.qml scripts "$DEST/"
rm -rf "$DEST/scripts/__pycache__"

omarchy plugin validate "$DEST"
echo "installed $ID -> $DEST"

if ! omarchy plugin list | grep -q "^$ID .*enabled"; then
  omarchy plugin enable "$ID"
fi

if ! python3 scripts/apt.py cache status >/dev/null 2>&1; then
  echo "building the airport data cache (~8s, ~40MB)..."
  python3 scripts/apt.py cache update
fi

echo
echo "Open the panel with:"
echo "  omarchy-shell shell toggle $ID"
echo
echo "No bar item and no keybinding are installed. See README for how to add"
echo "an Omarchy menu entry or bind a key yourself."
