#!/bin/bash
#
# SonarEx search results dialog.
#
# Shows the file paths produced by search_static.sh in a scrollable zenity
# list. Selecting one or more rows opens them (VS Code for text-like files,
# xdg-open for PDFs and other binary formats) and then redisplays the list, so
# the user can work through the results without searching again. Closing the
# window ends the loop.
#
# Launched detached by search_static.sh, so it has no terminal of its own: its
# output goes to the status file, which it owns along with the results file and
# removes on the way out.
#
# Usage: search_results_dialog.sh <results-file> <search-root> <vscode-path> <query> <status-file>
#
set -u

# The first thing the script does, so search_static.sh can tell "the dialog is
# up" from "the dialog died on launch" before it lets the terminal close.
printf 'dialog started (pid %s)\n' "$$" >&2

RESULTS_FILE="$1"
SEARCH_ROOT="$2"
VSCODE_PATH="$3"
QUERY="$4"
STATUS_FILE="$5"

# zenity's list widget bogs down well before this, and the rows are passed as
# command line arguments, so cap what we hand it.
MAX_ROWS=2000

trap 'rm -f "$RESULTS_FILE" "$STATUS_FILE"' EXIT

# zenity renders --text as Pango markup, so any &, < or > in the query or path
# has to be escaped or the dialog text comes out mangled. sed is used rather
# than ${var//&/&amp;} because bash 5.2+ reads an unquoted & in a substitution
# replacement as "the text that matched".
escape_markup() {
    printf '%s' "$1" | sed -e 's/&/\&amp;/g' -e 's/</\&lt;/g' -e 's/>/\&gt;/g'
}

# Text-like files go to VS Code; formats it cannot render usefully (PDFs turn
# up here because SonarEx searches their text) go to the desktop's default app.
open_path() {
    local path="$1"
    local ext="${path##*.}"

    case "${ext,,}" in
        pdf|ps|epub|djvu|\
        png|jpg|jpeg|gif|bmp|tif|tiff|webp|ico|heic|\
        mp3|wav|flac|ogg|m4a|mp4|mkv|avi|mov|webm|\
        odt|ods|odp|doc|docx|xls|xlsx|ppt|pptx|rtf|\
        zip|tar|gz|bz2|xz|7z|rar|jar|deb|rpm)
            xdg-open "$path" >/dev/null 2>&1 &
            ;;
        *)
            "$VSCODE_PATH" "$path" >/dev/null 2>&1 &
            ;;
    esac
}

# Last resort when zenity cannot show the list: hand the user the plain list of
# paths in VS Code, which is better than the search silently evaporating. The
# results file is deleted on exit, so copy it somewhere durable first.
fall_back_to_editor() {
    local keep="/tmp/sonarex-search-$(date +%Y-%m-%d--%H-%M-%S).txt"

    if cp "$RESULTS_FILE" "$keep" 2>/dev/null; then
        "$VSCODE_PATH" "$keep" >/dev/null 2>&1 &
    fi
}

# zenity's option set changed between versions (4.0 was a GTK4 rewrite), and an
# unknown option makes zenity exit immediately without ever showing a window.
# Ask this zenity what it supports and build the command line from that, so the
# dialog degrades to a plainer list instead of failing outright.
ZENITY_HELP=$(zenity --help-all 2>/dev/null)

zenity_supports() {
    case "$ZENITY_HELP" in
        *"$1"*) return 0 ;;
        *) return 1 ;;
    esac
}

declare -a ROWS=()
while IFS= read -r path; do
    [ -n "$path" ] || continue
    # Show paths relative to the searched folder—full paths are too wide to
    # scan—and rebuild the full path when the user picks a row. The quoting
    # inside ${path#...} keeps glob characters in the folder name literal.
    ROWS+=("${path#"$SEARCH_ROOT"/}")
done < "$RESULTS_FILE"

TOTAL=${#ROWS[@]}

if [ "$TOTAL" -eq 0 ]; then
    zenity --info --title="SonarEx Search Results" --text="No files matched."
    exit 0
fi

NOTE=""
if [ "$TOTAL" -gt "$MAX_ROWS" ]; then
    ROWS=("${ROWS[@]:0:$MAX_ROWS}")
    NOTE=" (showing the first $MAX_ROWS)"
fi

HEADING="<b>$TOTAL match(es)</b> for: $(escape_markup "$QUERY")$NOTE"
HEADING="$HEADING"$'\n'"Folder: $(escape_markup "$SEARCH_ROOT")"

declare -a ZENITY_ARGS=(--list --title="SonarEx Search Results" --column="File")

zenity_supports '--text=' && ZENITY_ARGS+=(--text="$HEADING")
# --multiple lets several files be opened at once; the newline separator is
# unambiguous because a path can contain anything except a newline.
zenity_supports '--multiple' && ZENITY_ARGS+=(--multiple)
zenity_supports '--separator=' && ZENITY_ARGS+=(--separator=$'\n')
zenity_supports '--ok-label=' && ZENITY_ARGS+=(--ok-label="Open")
zenity_supports '--cancel-label=' && ZENITY_ARGS+=(--cancel-label="Close")
zenity_supports '--width=' && ZENITY_ARGS+=(--width=900)
zenity_supports '--height=' && ZENITY_ARGS+=(--height=600)

FIRST_PASS=1

while true; do
    STARTED_AT=$(date +%s%N)

    SELECTION=$(zenity "${ZENITY_ARGS[@]}" -- "${ROWS[@]}")
    STATUS=$?

    ELAPSED_MS=$(( ($(date +%s%N) - STARTED_AT) / 1000000 ))

    # Closing the window (nonzero) or pressing Open with nothing selected ends
    # the session. Looping on an empty selection instead would spin the CPU if
    # zenity ever returned success without displaying anything.
    if [ "$STATUS" -ne 0 ] || [ -z "$SELECTION" ]; then
        # A dialog the user closed was on screen for a while; one that quits in
        # a fraction of a second never appeared, and that is worth recovering
        # from rather than exiting with nothing to show for the search.
        if [ "$FIRST_PASS" -eq 1 ] && [ "$ELAPSED_MS" -lt 700 ]; then
            fall_back_to_editor
        fi
        break
    fi

    FIRST_PASS=0

    while IFS= read -r relative; do
        [ -n "$relative" ] || continue
        open_path "$SEARCH_ROOT/$relative"
    done <<< "$SELECTION"
done
