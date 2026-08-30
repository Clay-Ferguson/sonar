# SonarEx (Nautilus Search Extension)

![Python](https://img.shields.io/badge/python-3.x-blue.svg)
![Platform](https://img.shields.io/badge/platform-linux-lightgrey.svg)
![License](https://img.shields.io/badge/license-MIT-green.svg)

A standalone extension for the Nautilus file manager that adds fast, recursive content search to the right-click context menu. SonarEx adds two menu items — **Search (Interactive)** and **Search (Static)** — to folders and to the empty-space background menu, so you can search the contents of every file under any folder without leaving the file manager.

Both modes are powered by [ugrep](https://github.com/Genivia/ugrep), support Google-style Boolean queries, honor include/exclude glob patterns from your config file, and can search inside PDFs. The interactive mode gives you a live terminal UI that refines results as you type; the static mode asks once and hands you a clickable list of matching files.

## 🔍 Search (Interactive) (Menu Item)
**Available:** On folders and empty space (searches current directory)

Recursively searches file contents within a folder using [ugrep](https://github.com/Genivia/ugrep)'s interactive terminal UI (`ugrep -Q`), launched in a new terminal window scoped to the folder you right-clicked. You type your search pattern directly in the TUI and see matching results update live as you type — no dialogs, no waiting for a search to finish before you can refine it.

- **Live incremental search:** Results appear and refine as you type each character
- **Case-insensitive by default:** SonarEx starts the TUI with `-i`
- **PDF content search:** When `pdftotext` is installed, PDF text content is searched too (via ugrep's `--filter` option)
- **Configurable exclusions:** Directories like `node_modules`, `.git`, and build folders are skipped automatically via the `search.included` and `search.excluded` glob patterns in your SonarEx config file
  - See [CONFIG.md](docs/CONFIG.md) for details on customizing search exclusions

See [UGREP Tips](#ugrep-tips) below for how to drive the TUI once it's open.

### Search Query Syntax

The search launches in **Boolean query mode** (ugrep's `-%` option), which supports Google-style search expressions typed directly in the TUI:

| What you want | What to type | Notes |
|---|---|---|
| Exact phrase | `"My Exact String"` | Quotes match the exact phrase, in order, treated literally (special characters like `(`, `*`, `.` lose their regex meaning inside quotes) |
| All words, any order (AND) | `cat dog` or `"my cat" AND "my dog"` | A space between terms means AND — every term must appear somewhere in the file (not necessarily on the same line) |
| Any of the terms (OR) | `"my cat" OR "my dog"` | Also `"my cat"\|"my dog"`; matches files containing either phrase |
| Excluding a term (NOT) | `"my" NOT "dog"` | Also `"my" -"dog"`; matches files containing "my" but not containing "dog" anywhere |
| Wildcard (match anything between) | `my.*cat` | Unquoted terms are regular expressions, so the "match anything" wildcard is `.*` (not a bare `*`); this example matches "my fluffy white cat" |
| Combinations | `("error" OR "warning") NOT "test"` | Parentheses group sub-expressions |

**Are quotes needed?** Only when it matters: a single word needs no quotes. For multiple words, `My Exact String` unquoted means *all three words anywhere in the file, in any order* (space = AND), while `"My Exact String"` quoted means *that exact phrase*. When in doubt, quote — quotes also protect special characters (e.g. searching for `file(1)` works quoted, but unquoted it's interpreted as a regex).

**Note:** Boolean queries match at *whole-file* scope (ugrep's `--files` option, which SonarEx enables) — `"cat" AND "dog"` matches a file with "cat" on one line and "dog" on another. All of this syntax is covered in depth by `ugrep --help bool` or the [ugrep manual](https://ugrep.com/).

## 🔍 Search (Static) (Menu Item)
**Available:** On folders and empty space (searches current directory)

A one-shot version of the search above, for when you want a plain list of *which files* matched, in a window you can keep open and click through.

A terminal opens and prompts you for a search string. Press Enter and SonarEx runs the same ugrep search (same Boolean query syntax, same config exclusions, same PDF support), then the terminal closes itself and the matching files appear in a scrollable dialog.

- **The dialog stays open:** Open a file, look at it, come back — the list is still there. It closes when you press **Close** or close the window
- **Open several at once:** Ctrl-click or Shift-click to select multiple rows, then press **Open**
- **Opens the right app:** Text-like files open in VS Code; PDFs, images, and other binary formats open in whatever application your desktop uses for them (via `xdg-open`), since VS Code can't display them
- **Newest first:** Results are listed in reverse chronological order of modification time, so the files you edited most recently are at the top
- **Readable paths:** Rows show the path relative to the folder you searched, with the full root shown above the list
- **Same query syntax and exclusions:** See [Search Query Syntax](#search-query-syntax) above, and the `search.included` / `search.excluded` patterns in your config file

Very large result sets are capped at 2000 files (the 2000 most recently modified), which the dialog tells you about — narrow the query if you hit that.

**If the results window can't be shown** — an unusable zenity build, no display — SonarEx falls back to opening the list of matching paths in VS Code and, when the dialog fails to start at all, keeps the search terminal open with the reason. A search never ends in silence.

## UGREP Tips

These all apply to the TUI that opens when you click **Search (Interactive)** — they're keystrokes you press inside that window, not things you type on a command line.

### Show only filenames (hide the matching lines)

Press **`Alt-l`**. That's the one worth memorizing.

By default the TUI lists every matching *line* along with the file it came from. `Alt-l` toggles ugrep's `-l` option, which collapses the display down to a plain list of matching filenames — one per file, no line content. Press `Alt-l` again to switch back to the full line view.

This is especially useful with SonarEx's Boolean search: because SonarEx runs in whole-file mode, a query like `"cat" AND "dog"` matches a file with "cat" in one place and "dog" in another, so the filename list is often the answer you actually want.

### Toggling other options

The general rule: **`Alt` + an option letter toggles that ugrep option on and off.** Press it once to enable, again to disable. (If your terminal eats `Alt` key combos, press `Ctrl-O` and then the letter instead.)

| Key | Toggles | Effect |
|---|---|---|
| `Alt-l` | `-l` | Filenames only, no line content |
| `Alt-c` | `-c` | Show a count of matches per file |
| `Alt-n` | `-n` | Show/hide line numbers |
| `Alt-i` | `-i` | Case sensitivity (SonarEx starts with case-*insensitive*, so this makes it case-sensitive) |
| `Alt-w` | `-w` | Match whole words only |
| `Alt-v` | `-v` | Invert the match — show what *doesn't* match |
| `Alt-.` | `-.` | Include hidden dotfiles, which are skipped by default |
| `Alt-]` | — | Increase the lines of context shown around each match |
| `Alt-g` | `-g` | Edit the active file/directory globs for this session; `Esc` returns to the search prompt |

The prompt at the left edge tells you what mode you're in: `Q>` is the normal Boolean query prompt, and it changes to `F>`, `G>`, `P>`, or `Z>` when you switch to fixed-string, basic-regex, Perl, or fuzzy matching.

### Moving around the results

| Key | Does |
|---|---|
| `Up` / `Down` | Scroll the result list one line |
| `PgUp` / `PgDn` | Scroll a full page |
| `Tab` | Descend into the directory of the file at the top of the screen (narrows the search to it) |
| `Shift-Tab` | Go back up one directory level |
| `Ctrl-^` | Jump all the way back to the folder you started in |
| `Ctrl-S` | Jump to the next file in the results |
| `Ctrl-W` | Jump back to the previous file |

Note that your typing always goes into the search pattern, so navigation is done with these control and arrow keys rather than plain letters.

### Looking at a file

- **`Ctrl-T`** (or `F5`) splits the screen and previews the file at the top of the results in the bottom pane — the fastest way to check whether a hit is the one you want without leaving the search.
- **`Ctrl-Y`** (or `F2`) opens the file at the top of the screen in your `$PAGER` or `$EDITOR`. Filenames have to be visible in the output for this to work.

### Getting out

- **`Esc`** (or `Ctrl-C`) backs out one step, and exits the TUI from the top level. The terminal window closes on its own.
- **`Enter`** switches into selection mode, where `Enter` / `Del` mark individual result lines and `A` selects all of them. **`Ctrl-Q`** then exits and prints just the selected lines to the terminal — handy for copying a set of paths out. Without selecting anything, ugrep exits silently and prints nothing.

### Built-in help

Press **`F1`** (or `Ctrl-Z`) at any time for ugrep's own help screen, which lists every option and lets you toggle them from there. It's the authoritative reference if you need something not covered above.

**Note:** Both Search menu items require ugrep (installed by `setup.sh`, or manually):
```bash
sudo apt install ugrep
```

To additionally search inside PDF files, install poppler-utils:
```bash
sudo apt install poppler-utils
```

## Configuration

SonarEx reads `~/.config/sonarex/sonarex-config.yaml`, which is created with sensible defaults by `setup.sh`. It defines which files searches look at:

```yaml
search:
  included:
    - "*.md"
    - "*.txt"
    - "*.pdf"
  excluded:
    - "*/node_modules/*"
    - "*/.git/*"
    - "*/build/*"
```

The **⚙️ Open SonarEx Configs** menu item opens this file in VS Code from anywhere in Nautilus. See [CONFIG.md](docs/CONFIG.md) for the full reference, and [example-config/sonarex-config.yaml](example-config/sonarex-config.yaml) for a complete sample.

**TIP:** Run `nautilus -q` after editing the config to make changes take effect.

## Installation

1. Run the setup script:
   ```bash
   ./setup.sh
   ```

2. Restart Nautilus:
   ```bash
   nautilus -q
   ```

3. Open a new Nautilus window, right-click a folder, and start searching!

## Requirements

- Nautilus file manager
- Python 3 with Nautilus bindings (automatically installed by setup script)
- gnome-terminal (both search modes run in a terminal window)
- ugrep (the search engine behind both menu items - install with `sudo apt install ugrep`)
- zenity (for the Search (Static) results dialog)
- Visual Studio Code (for opening matched text files and the config file)
- poppler-utils (optional, for PDF search support - install with `sudo apt install poppler-utils`)

All of these except VS Code are installed for you by `setup.sh`:

```bash
sudo apt install python3-nautilus python3-yaml zenity ugrep poppler-utils
```

## License

MIT — see [LICENSE.md](LICENSE.md).
