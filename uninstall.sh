#!/bin/bash
# Remove the SonarEx desktop entry.
set -euo pipefail

DESKTOP_TARGET="$HOME/.local/share/applications/sonarex.desktop"

if [ -f "$DESKTOP_TARGET" ]; then
  rm -f "$DESKTOP_TARGET"
  update-desktop-database ~/.local/share/applications/ 2>/dev/null
  echo "SonarEx desktop entry removed."
else
  echo "No SonarEx desktop entry found at $DESKTOP_TARGET"
fi

echo "(Your config at ~/.config/sonarex/sonarex-config.yaml was left alone.)"
