#!/bin/bash
# Install the Sonar desktop entry.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

read -rp "Path to the Sonar program directory [$SCRIPT_DIR]: " PROGRAM_DIR
PROGRAM_DIR="${PROGRAM_DIR:-$SCRIPT_DIR}"
PROGRAM_DIR="${PROGRAM_DIR/#\~/$HOME}"
PROGRAM_DIR="$(cd "$PROGRAM_DIR" && pwd)"  # normalize; fails if it doesn't exist

mkdir -p ~/.local/share/applications
DESKTOP_TARGET="$HOME/.local/share/applications/sonarex.desktop"
ICON_ROOT="$HOME/.local/share/icons/hicolor"

# Icon=sonarex in the .desktop file is a theme name, not a path, so the PNGs
# have to land in the hicolor theme for it to resolve. They are checked in at
# every size rather than converted here: install.sh stays free of Pillow and
# ImageMagick. Regenerate them with icons/make-icons.py if the artwork changes.
for ICON in "$SCRIPT_DIR"/icons/hicolor/*/apps/sonarex.png; do
  SIZE_DIR="$(basename "$(dirname "$(dirname "$ICON")")")"
  mkdir -p "$ICON_ROOT/$SIZE_DIR/apps"
  cp "$ICON" "$ICON_ROOT/$SIZE_DIR/apps/sonarex.png"
done
# Refreshes the theme cache where one exists; harmless (and absent) otherwise.
gtk-update-icon-cache -f -t "$ICON_ROOT" 2>/dev/null || true

# No folder argument is baked into Exec=: launched from the application grid,
# Sonar opens on the current working directory and the folder row is editable
# anyway. A folder is only worth passing when something else (a file manager,
# a script) already knows which one you mean.
sed \
  -e "s|^Exec=.*|Exec=\"$PROGRAM_DIR/start.sh\"|" \
  "$SCRIPT_DIR/sonarex.desktop" > "$DESKTOP_TARGET"
update-desktop-database ~/.local/share/applications/ 2>/dev/null

echo "Sonar desktop entry installed."
echo "  Program: $PROGRAM_DIR"
echo "  Icon:    $ICON_ROOT/*/apps/sonarex.png"

if ! command -v ugrep >/dev/null 2>&1; then
  echo
  echo "Note: ugrep is not installed, and Sonar cannot search without it."
  echo "  sudo apt install ugrep"
fi
