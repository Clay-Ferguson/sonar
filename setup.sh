#!/bin/bash

# Install SonarEx, a Nautilus extension that adds recursive search actions to the
# right-click context menu ("Search (Interactive)" and "Search (Static)").

ACTIONS_DIR="$HOME/.local/share/nautilus-python/extensions"
ACTION_FILE="$ACTIONS_DIR/sonarex_action.py"

echo "Setting up SonarEx - search actions for the Nautilus context menu..."

# Create the directory
mkdir -p "$ACTIONS_DIR"

# Copy the Python extension from the project directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cp "$SCRIPT_DIR/sonarex_action.py" "$ACTION_FILE"
cp "$SCRIPT_DIR/search_ugrep.py" "$ACTIONS_DIR/search_ugrep.py"
cp "$SCRIPT_DIR/search_static.py" "$ACTIONS_DIR/search_static.py"
cp "$SCRIPT_DIR/search_static.sh" "$ACTIONS_DIR/search_static.sh"
cp "$SCRIPT_DIR/search_results_dialog.sh" "$ACTIONS_DIR/search_results_dialog.sh"

# The shell helpers locate each other via $(dirname "${BASH_SOURCE[0]}"), so they
# must live in the same directory and be executable.
chmod +x "$ACTIONS_DIR/search_static.sh" "$ACTIONS_DIR/search_results_dialog.sh"

rm -rf "$ACTIONS_DIR/__pycache__"

# Make sure it's executable
chmod +x "$ACTION_FILE"

# Install dependencies
# ugrep powers both search modes; poppler-utils (pdftotext) is optional and only
# needed to search inside PDF files.
echo "Installing required dependencies..."
sudo apt update && sudo apt install -y python3-nautilus python3-yaml zenity ugrep poppler-utils

# Create config directory and default config file if it doesn't exist
CONFIG_DIR="$HOME/.config/sonarex"
CONFIG_FILE="$CONFIG_DIR/sonarex-config.yaml"

mkdir -p "$CONFIG_DIR"

if [ ! -f "$CONFIG_FILE" ]; then
    echo "Creating default configuration file..."
    cat > "$CONFIG_FILE" << 'EOF'
# SonarEx Nautilus Extension Configuration

search:
  # Patterns to include in searches (glob patterns)
  # If empty or omitted, all files are included (subject to exclusions)
  # Examples: ["*.md", "*.txt", "*.py"]
  included:
    - "*.md"
    - "*.txt"
  
  # Patterns to exclude from searches (glob patterns)
  # These directories/files will be skipped during recursive search
  excluded:
    - "*/node_modules/*"
    - "*/.git/*"
    - "*/.venv/*"
    - "*/__pycache__/*"
    - "*/venv/*"
    - "*/.svn/*"
    - "*/.hg/*"
    - "*/build/*"
    - "*/dist/*"
    - "*/.next/*"
    - "*/.nuxt/*"
EOF
    echo "Default config created at: $CONFIG_FILE"
else
    echo "Config file already exists at: $CONFIG_FILE"
fi

nautilus -q
echo "Setup complete! Right-click on a folder (or empty space) to see the search options."
