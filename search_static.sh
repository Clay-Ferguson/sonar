#!/bin/bash
#
# SonarEx "Search (Static)" helper.
#
# Launched in a terminal by search_static.py. Prompts for a search string, runs
# ugrep to collect the full paths of every matching file, then hands those
# paths to search_results_dialog.sh, which shows them in a scrollable zenity
# list the user can click through. The dialog is launched detached so this
# terminal window closes as soon as the search is done.
#
# Usage: search_static.sh <search-dir> <vscode-path> [extra ugrep args...]
#
set -u

SEARCH_DIR="$1"
VSCODE_PATH="$2"
shift 2
UGREP_ARGS=("$@")

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DIALOG_SCRIPT="$SCRIPT_DIR/search_results_dialog.sh"

pause_and_exit() {
    echo ""
    echo "Press Enter to close..."
    read -r
    exit "${1:-0}"
}

if ! command -v ugrep >/dev/null 2>&1; then
    echo "ERROR: ugrep not found. Please install it:"
    echo "  sudo apt install ugrep"
    pause_and_exit 1
fi

if ! command -v zenity >/dev/null 2>&1; then
    echo "ERROR: zenity not found. Please install it:"
    echo "  sudo apt install zenity"
    pause_and_exit 1
fi

if [ ! -f "$DIALOG_SCRIPT" ]; then
    echo "ERROR: results dialog script not found:"
    echo "  $DIALOG_SCRIPT"
    pause_and_exit 1
fi

echo "SonarEx Search (Static)"
echo "Folder: $SEARCH_DIR"
echo ""
echo 'Query Syntax:'
echo '  * Unquoted terms are regular expressions'
echo '  * "quoted phrases" match literally (not as REGEX)'
echo '  * Space or AND requires all terms'
echo '  * OR matches any term'
echo '  * NOT (or -term) excludes'
echo '  * Parenthetical groupings of AND/OR/NOT are allowed'
echo ""
echo 'REGEX Match Tips:'
echo '  * Whole word ABC: \bABC\b'
echo '  * From 0 up to 10 characters: .{0,10}'
echo '  * Any string of chars: .*'
echo ""
read -r -p "Enter Search: " QUERY

if [ -z "$QUERY" ]; then
    echo "No search string entered."
    pause_and_exit 0
fi

# mktemp keeps concurrent searches from colliding and creates the file with
# owner-only permissions rather than whatever a plain redirect into /tmp gets.
RESULTS_FILE=$(mktemp "/tmp/sonarex-search-$(date +%Y-%m-%d--%H-%M-%S)-XXXXXX.txt") || {
    echo "ERROR: could not create a temporary results file in /tmp."
    pause_and_exit 1
}

echo ""
echo "Searching..."

# -l lists matching file names only; -% is Boolean query mode and --files
# applies the query at whole-file scope. -- ends option processing so a query
# beginning with '-' (Boolean NOT) is still read as the pattern. No --sort here
# on purpose: ugrep sorts within each directory and emits subdirectories after
# the files, so --sort=rchanged does not give a tree-wide newest-first order.
# The sort below does that instead.
ugrep -r -i -l -% --files "${UGREP_ARGS[@]}" -- "$QUERY" "$SEARCH_DIR" > "$RESULTS_FILE"
STATUS=$?

# ugrep exits 0 when it matched, 1 when it did not, and >1 on a real error.
if [ "$STATUS" -gt 1 ]; then
    echo "ugrep failed (exit code $STATUS)."
    rm -f "$RESULTS_FILE"
    pause_and_exit "$STATUS"
fi

COUNT=$(wc -l < "$RESULTS_FILE")

if [ "$COUNT" -eq 0 ]; then
    echo "No files matched: $QUERY"
    rm -f "$RESULTS_FILE"
    pause_and_exit 0
fi

# Reorder the hits newest-first, tree-wide, so the most recently edited files
# land at the top of the results dialog (and survive its row cap). ugrep's own
# --sort only orders within a directory, so the sort has to happen out here on
# the finished list. stat prints each file's mtime as epoch seconds ahead of
# its path; sorting numerically in reverse on that first field and then cutting
# from field 2 onward leaves the paths in the wanted order with any tab inside
# a filename intact. Files that disappeared since the search drop out silently;
# only an empty or failed result falls back to ugrep's original ordering.
if [ "$COUNT" -gt 1 ]; then
    SORTED_FILE=$(mktemp "/tmp/sonarex-search-sorted-XXXXXX.txt" 2>/dev/null)
    if [ -n "$SORTED_FILE" ]; then
        if xargs -d '\n' -r stat --printf '%Y\t%n\n' -- < "$RESULTS_FILE" 2>/dev/null \
            | sort -rn -k1,1 | cut -f2- > "$SORTED_FILE" && [ -s "$SORTED_FILE" ]; then
            mv "$SORTED_FILE" "$RESULTS_FILE"
            COUNT=$(wc -l < "$RESULTS_FILE")
        else
            echo "(could not sort by modification time; showing ugrep's order)"
            rm -f "$SORTED_FILE"
        fi
    fi
fi

echo "$COUNT file(s) matched. Opening results..."

# The dialog has no terminal of its own, so anything it prints—including the
# line it writes on startup, and any error that kills it—lands here.
STATUS_FILE=$(mktemp /tmp/sonarex-search-status-XXXXXX)

# Launch the results dialog in its own session so it outlives this terminal,
# which closes the moment this script exits. The dialog owns the results and
# status files from here on, and deletes both when the user closes the window.
#
# Detaching has to survive the terminal tearing its process group down the
# instant this script exits, so all three of these matter:
#   nohup          - ignore the SIGHUP the terminal sends on the way out
#   setsid --fork  - always fork, so the new session is established by a
#                    process that is not this script's job-control leader
#   the wait below - give the new session time to exist before we exit
if command -v setsid >/dev/null 2>&1; then
    nohup setsid --fork bash "$DIALOG_SCRIPT" \
        "$RESULTS_FILE" "$SEARCH_DIR" "$VSCODE_PATH" "$QUERY" "$STATUS_FILE" \
        </dev/null >>"$STATUS_FILE" 2>&1 &
else
    nohup bash "$DIALOG_SCRIPT" \
        "$RESULTS_FILE" "$SEARCH_DIR" "$VSCODE_PATH" "$QUERY" "$STATUS_FILE" \
        </dev/null >>"$STATUS_FILE" 2>&1 &
fi

disown 2>/dev/null

# Wait for the dialog to report itself started. If that never happens it died
# on launch, and the user would otherwise be left with a terminal that vanished
# and nothing to show for the search.
for _ in 1 2 3 4 5 6 7 8 9 10; do
    grep -q 'dialog started' "$STATUS_FILE" 2>/dev/null && exit 0
    sleep 0.2
done

echo ""
echo "ERROR: the results dialog failed to start."
if [ -s "$STATUS_FILE" ]; then
    echo ""
    cat "$STATUS_FILE"
    echo ""
fi

# The dialog normally owns these files and deletes them on exit; since it never
# ran, hand the results over under a durable name and clean up here.
KEPT="/tmp/sonarex-search-$(date +%Y-%m-%d--%H-%M-%S).txt"
if cp "$RESULTS_FILE" "$KEPT" 2>/dev/null; then
    echo "Your $COUNT result(s) were saved to: $KEPT"
    "$VSCODE_PATH" "$KEPT" >/dev/null 2>&1 &
fi
rm -f "$RESULTS_FILE" "$STATUS_FILE"

pause_and_exit 1
