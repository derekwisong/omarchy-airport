#!/usr/bin/env bash
# Copy this plugin into the Omarchy user plugin directory and enable it.
# Saving files there hot-reloads the shell, so re-running this applies edits.
set -euo pipefail
cd "$(dirname "$0")"

ID=$(python3 -c "import json;print(json.load(open('manifest.json'))['id'])")
DEST="$HOME/.config/omarchy/plugins/$ID"

mkdir -p "$DEST"
cp -r manifest.json Model.js *.qml scripts "$DEST/"
rm -rf "$DEST/scripts/__pycache__"

omarchy plugin validate "$DEST"
echo "installed $ID -> $DEST"

# The shell only learns about a brand-new plugin directory when it rescans, and
# `plugin enable` refuses an id it has never heard of. Rescanning first makes a
# first install behave like a reinstall.
omarchy-shell shell rescanPlugins >/dev/null 2>&1 || true

if ! omarchy plugin list | grep -q "^$ID .*enabled"; then
  omarchy plugin enable "$ID"
fi

echo
echo "Open the panel with:"
echo "  omarchy-shell shell toggle $ID"
echo
echo "The airport data cache is built by the panel the first time you open it"
echo "(about 40 MB, a few seconds), and again when the 28-day FAA cycle rolls."
echo "To build it now instead:  python3 scripts/apt.py cache update"
echo
echo "No bar item and no keybinding are installed. See README for how to add"
echo "an Omarchy menu entry or bind a key yourself."
