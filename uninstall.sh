#!/bin/bash
# Remove the SonarEx desktop entry.
set -euo pipefail

DESKTOP_TARGET="$HOME/.local/share/applications/sonarex.desktop"
ICON_ROOT="$HOME/.local/share/icons/hicolor"

if [ -f "$DESKTOP_TARGET" ]; then
  rm -f "$DESKTOP_TARGET"
  update-desktop-database ~/.local/share/applications/ 2>/dev/null
  echo "SonarEx desktop entry removed."
else
  echo "No SonarEx desktop entry found at $DESKTOP_TARGET"
fi

# Only our own file is removed from each size directory; the directories are
# shared with every other application's icons, so they are left in place.
rm -f "$ICON_ROOT"/*/apps/sonarex.png
gtk-update-icon-cache -f -t "$ICON_ROOT" 2>/dev/null || true

echo "(Your config at ~/.config/sonarex/sonarex-config.yaml was left alone.)"
