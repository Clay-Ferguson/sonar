#!/bin/bash
# Install the SonarEx desktop entry.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

read -rp "Path to the SonarEx program directory [$SCRIPT_DIR]: " PROGRAM_DIR
PROGRAM_DIR="${PROGRAM_DIR:-$SCRIPT_DIR}"
PROGRAM_DIR="${PROGRAM_DIR/#\~/$HOME}"
PROGRAM_DIR="$(cd "$PROGRAM_DIR" && pwd)"  # normalize; fails if it doesn't exist

mkdir -p ~/.local/share/applications
DESKTOP_TARGET="$HOME/.local/share/applications/sonarex.desktop"

# No folder argument is baked into Exec=: launched from the application grid,
# SonarEx opens on the current working directory and the folder row is editable
# anyway. A folder is only worth passing when something else (a file manager,
# a script) already knows which one you mean.
sed \
  -e "s|^Exec=.*|Exec=\"$PROGRAM_DIR/start.sh\"|" \
  "$SCRIPT_DIR/sonarex.desktop" > "$DESKTOP_TARGET"
update-desktop-database ~/.local/share/applications/ 2>/dev/null

echo "SonarEx desktop entry installed."
echo "  Program: $PROGRAM_DIR"

if ! command -v ugrep >/dev/null 2>&1; then
  echo
  echo "Note: ugrep is not installed, and SonarEx cannot search without it."
  echo "  sudo apt install ugrep"
fi
