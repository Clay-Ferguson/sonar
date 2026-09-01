# Notes to AI Agents

## What this is

SonarEx is a PyQt6 desktop app: a two-pane content-search window over
[ugrep](https://github.com/Genivia/ugrep). A query field and a folder row sit
across the top; below them a splitter holds the matching file paths on the
left and a read-only view of the selected file on the right.

It **used to be a Nautilus extension** driving `zenity` and `gnome-terminal`.
That is gone, deliberately and entirely: a Nautilus extension runs inside the
Nautilus process, which already has a GTK main loop, so PyQt6 cannot live
there. If you are tempted to re-add file-manager integration, it has to be a
separate process launched with a folder argument — never an import into
Nautilus. Roughly 330 lines of defensive bash (a `nohup setsid --fork` detach
dance, a status-file handshake, runtime zenity-flag probing, a 2000-row argv
cap) died with that change; none of it should come back.

## Running

```bash
./start.sh [FOLDER]
```

`start.sh` runs the app through `uv`, which rebuilds the virtualenv from
`pyproject.toml` on every run — there is no install step. `pyproject.toml`
sets `package = false`: the code runs straight out of the tree, so there is
nothing to reinstall after an edit.

The folder is the **only** command-line argument, and it only prefills the
folder row. No search ever runs automatically — a search needs a query, and
the query only ever comes from the window.

## Architecture

- `sonarex/__main__.py` — entry point: argparse, `QApplication`, the ugrep
  check, folder resolution. The `folder` argument is `nargs="?"` rather than
  required because argparse reports a missing argument on stderr and exits
  before a `QApplication` exists, which is invisible when launched from a
  desktop icon; every startup failure is a `QMessageBox` instead.
- `sonarex/config.py` — the YAML config plus the glob translation it feeds.
  `Settings` is the file as a record and `load_settings()`/`save_settings()`
  are the dialog's whole interface to it; the rest of the app goes through the
  two accessors instead, `search_globs()` for the ugrep argv and
  `open_command()` for the editor, both read at the moment of use so a saved
  change needs no restart and no notification. `convert_excluded_pattern()`
  turns find-style `*/name/*` into ugrep's `!name/`. Loading is forgiving by
  design (see below).
- `sonarex/search.py` — `SearchRunner`, a `QProcess` wrapper that streams
  ugrep's hits back as `matchFound(path)` signals. `build_argv()` owns the
  command line. Beside it, `build_match_argv()`/`match_spans()` are the
  second, much smaller ugrep call: one named file, `-o -u`, and a `--format`
  that reports where the query matched inside it. That one is synchronous —
  ~16ms at the preview's size cap, so it does not need a `QProcess` — and it
  answers `{}` rather than raising on any failure.
- `sonarex/highlight.py` — `MatchHighlighter`, the `QSyntaxHighlighter` that
  paints those spans onto the preview, one of them in a hotter color as the
  current match. It knows nothing about the query; it only colors the ranges
  `match_spans()` hands it, and `set_current()` says which one is parked on.
- `sonarex/window.py` — `MainWindow`: the two rows, the splitter, the status
  label, and the end-of-search sort. Also the Prev/Next walk: `_adopt_matches()`
  flattens the spans into reading order on `self._matches`, and
  `_go_to_match()` is the single place that moves `self._match_index`, marks
  the highlighter, scrolls, and refreshes the counter.
- `sonarex/style.py` — the shared look: `action_button_style()`, the wider
  scroll bars, `tune_palette()`, `mono_font()`. It exists so a dialog can
  match the window's controls without importing `window`, which opens the
  dialogs and would make that a cycle. It imports nothing from the package
  except `UI_POINT_SIZE`; keep it that way.
- `sonarex/settings.py` — the gear button's dialog: one text area per pattern
  list (one pattern per line) and a line edit for the Open command. A future
  setting is one more `_add_patterns()`/`_add_line()` call plus a field on
  `Settings`; the dialog sizes to its contents, so nothing else has to change.
- `sonarex/viewer.py` — `read_for_preview()`: size cap, binary sniff, decode.
  Always returns a string, never raises. Also `open_in_editor()`, which runs
  `open.command` from the config — `build_open_argv()` is the split-and-place
  rule, and every failure comes back as a message naming the command, since
  the command is now something the user typed. Extensions in
  `SYSTEM_OPEN_EXTENSIONS` (`.pdf`) skip the config key and go to
  `SYSTEM_OPEN_COMMAND` (`xdg-open`) instead, so they land in whatever the
  desktop has registered for them; only the command and the error hint differ,
  the spawn is the same.

## Things that will bite you

- **ugrep's exit codes are 0 / 1 / 2**, and `1` means *no match*, not failure.
  Treating anything non-zero as an error reports an empty search as broken.
  Verified against ugrep 7.5.0.
- **Result ordering is done in Python, not by ugrep.** ugrep's
  `--sort=rchanged` sorts only *within* each directory and emits
  subdirectories after files, so it never produces a tree-wide newest-first
  list. `MainWindow._sort_by_mtime()` re-sorts once, on completion — it cannot
  happen during streaming, because the newest file may be the last one found.
  Files that vanished mid-search are dropped; any other failure leaves
  ugrep's ordering intact. Cost is ~0.9s at 43k rows, which is a single hitch
  at the end of a large search.
- **`--` before the query is load-bearing.** Without it a query starting with
  `-` (`-l`, say) is parsed as an option. The folder is passed absolute so
  every path ugrep prints is absolute.
- **`-g` filters explicitly named file arguments too**, not just what recursion
  turns up. This is why `build_match_argv()` omits `search_globs()`: with the
  globs in place, ugrep returns nothing for the very file the search just
  found, and the preview highlights nothing. Verified — adding `-g '!*.txt'`
  to a re-run on a named `.txt` file exits 1.
- **The highlight spans are line + column, deliberately, not byte offsets.**
  `%b`/`%d` are available and both break here: Qt strips the `\r` from CRLF on
  `setPlainText`, so byte offsets drift by one per preceding line, and
  `read_for_preview` decodes UTF-8, so bytes need a character walk anyway.
  ugrep's `%k` is already a *character* column (`ééé hello` reports 5, not 8),
  and `%n` maps straight onto a text block. `%j` gives the match JSON-quoted,
  so a match can never spill onto a second output line.
- **Set the spans before `setPlainText`, not after.** Replacing the document's
  text is itself what makes Qt run the highlighter over it, so spans set first
  ride along with that pass; set afterwards they need an explicit
  `rehighlight()`, which is a second full pass over what can be 44k lines.
- **Highlighting is a `QSyntaxHighlighter`, not `setExtraSelections()`.** The
  latter is the more obvious tool and is ~14x slower here, because it builds
  every range up front rather than formatting blocks as they are laid out:
  measured at the 2 MiB cap with 88k matches, 1.15s against ~80ms. That is the
  only reason nothing caps the number of matches.
- **`MATCH_BG` and `MATCH_FG` have to be set together.** The amber is pinned
  rather than derived from the palette, so the text on it cannot be left to
  inherit the theme's foreground — on a dark theme that is near-white and
  disappears against the highlight. `MATCH_CURRENT_BG` shares that same
  foreground, which is the constraint on changing it: it has to stay light
  enough to read near-black text on.
- **`set_current()` repaints two lines, not the document.** Prev/Next changes
  which match is hot, and the obvious `rehighlight()` is a pass over every
  block on every click — a visible stall on a long file. Only the line losing
  the mark and the line gaining it need it, which is why the current match is
  tracked as a (line, column) pair: the line is what has to be found again.
  Measured at 0.1ms per click on a file with 100k matches.
- **The nav state has to be reset wherever the preview is cleared.** There are
  two such places — a selection going to None, and `start_search` — and both
  route through `_adopt_matches({})`. Leaving them out leaves Prev and Next
  live over a document whose matches are gone.
- **The Open command runs without a shell either**, for the same reason the
  ugrep filter does: `subprocess.Popen` gets an argv list, split by `shlex`.
  Quotes and spaces in a program path work; pipes, redirection and `&&` do
  not. Do not "fix" that with `shell=True` — the command reaches this code
  from a text field, and a shell would make a stray `;` in it executable.

- **`--filter` runs without a shell.** ugrep executes a filter command
  directly, so `PDF_FILTER` can contain no pipes or redirection — hence
  `pdftotext -q % -` rather than a shell one-liner. The PDF path is written
  against documented behavior and has **not** been exercised; treat it as
  unverified.
- **Saving the config rewrites the whole file.** `render_config()` re-emits
  the comments along with the two lists, precisely because a first-run
  template would mean the explanations survived until the first Save and then
  vanished. Keys the module does not know about are read back off the parsed
  file and re-dumped underneath, so a setting added later is not dropped by an
  older Save — but a file that will not parse contributes nothing to carry
  across, which is why the dialog warns before it gets that far. A new setting
  needs its key added to the "known" sets in `render_config`, or it will be
  written twice: once by name and once as an unknown extra. The write
  goes to a temp file and `os.replace`s over the original: a failure part-way
  must not leave a truncated config, which the loader would read as "no
  patterns" and silently search everything.

- **`PatternEdit`'s height is pinned, and the slack goes above the buttons.**
  Two things conspire otherwise: a QPlainTextEdit's `sizeHint()` is a fixed
  256x192 with no relation to its font, and a QVBoxLayout hands any surplus
  height to whatever will take it. A field a few pixels off a whole number of
  lines shows the top of the next one, which reads as clipped text. So the
  height is computed from the font (`lineSpacing() * lines`, plus the frame
  and the document margin counted **once** — the document runs on underneath
  the bottom margin) and fixed, and the dialog's `addStretch(1)` before the
  button row absorbs whatever a resize adds.

- **Config loading must never raise.** A missing file, bad YAML, or a key of
  the wrong type all degrade to "no patterns" so a typo means an unfiltered
  search rather than an app that won't search. Keep that property.
- **`SearchRunner.stop()` disconnects before killing.** A superseded process
  must not deliver a late `finished` into the search that replaced it; this
  is what keeps rapid Search presses from interleaving two result sets.
- **`_read_stdout` splits on `"\n"`, not `splitlines()`.** `splitlines()` also
  breaks on `\v`, `\f` and `\x85`, all legal in a filename, which would invent
  paths that don't exist.
- **`pkill -f "python -m sonarex"` matches its own shell.** It will kill your
  own session. Use `pkill -f "[p]ython -m sonarex"`.

## The icon

`sonar-icon.jpeg` is the source artwork: a 1024x1024 render of a rounded-square
icon on a dark backdrop. The installable PNGs under `icons/hicolor/` are
generated from it by `icons/make-icons.py`, which crops away the backdrop and
masks the corners to transparent so the icon is not a dark tile on a light
panel. Two constants in that script (`CROP`, `RADIUS`) were measured off the
current render and are wrong for any other artwork.

The PNGs are **checked in** rather than converted at install time, which is the
only reason `install.sh` needs neither Pillow nor ImageMagick. Regenerate them
by hand when the artwork changes:

```bash
uv run --with pillow icons/make-icons.py
```

`Icon=sonarex` in `sonarex.desktop` is a theme name, not a path, so the PNGs
have to be copied into `~/.local/share/icons/hicolor/` for it to resolve — an
absolute path there would work too, but only at one size.

## Testing

There is no test suite in the repo. Drive the real window from a script
instead — `MainWindow` is directly constructible, and `QEventLoop` + the
`SearchRunner.finished` signal is enough to await a search:

```bash
QT_QPA_PLATFORM=offscreen PYTHONPATH=/mnt/projects/sonarex uv run python yourtest.py
```

`QT_QPA_PLATFORM=offscreen` runs headless; `win.grab().save(path)` renders the
window to a PNG when you want to see the layout. Note that a `QMessageBox`
still blocks for a click under `offscreen`, so the startup-error paths can't
be driven that way — assert on `ugrep_available()` instead.

Syntax checks:

```bash
python3 -m py_compile sonarex/*.py
bash -n start.sh install.sh uninstall.sh
```

Worth covering when you change search or results handling: exclusions from
the config, an `included:` whitelist, a query starting with `-`, a folder with
spaces in its name, no matches, a bad regex, a binary file, a file over the
2 MiB preview cap, and repeated Search presses mid-search.

For the preview highlighting, assert on the document rather than on pixels:
walk the blocks, read `block.layout().formats()`, and collect the runs whose
background is `MATCH_BG`. That gives the highlighted text back as strings, so a
check reads as "these exact words are colored". Worth covering: an AND query
whose terms are on different lines (both must be highlighted, `--files` scope),
an `OR` query against a file matching only one branch, a `NOT`/`-` term (which
must contribute *no* highlight), a quoted phrase, a CRLF file, a file with
multi-byte characters ahead of the match, a notice (binary or over-cap, which
must highlight nothing), and a file whose first match is thousands of lines
down — the pane should scroll to it rather than sit at the top.

For Prev/Next, note that the *current* match is painted `MATCH_CURRENT_BG`
rather than `MATCH_BG`, so a check that collects only the latter will miss it
and read as a lost match. Collect both when asking "what did ugrep find", and
only `MATCH_CURRENT_BG` when asking "which one is it parked on". Worth
covering: a line carrying two hits (two stops, not one), wrapping off either
end, that switching files restarts the count, and that a notice or a fresh
search leaves the buttons dim and the counter blank.

The settings dialog is drivable the same way — `SettingsDialog()` constructs
without the main window, and `_save()` can be called directly instead of
clicking. Point `config.CONFIG_PATH` at a temp file first: it is read at call
time, so rebinding the module attribute is enough, and nothing in a test then
touches the real `~/.config`.

## Not built yet

- Further settings. The dialog is built to grow — another `_add_patterns()` or
  `_add_line()` call and it re-sizes itself — and `render_config()` carries
  unknown keys through, so an option can be added on either side first.
- Keyboard shortcuts for Prev/Next. The buttons are the only way to step; F3
  and Shift+F3 would be a `QShortcut` each onto `_step_match`, which already
  takes the direction as its argument.
- Stepping between *files* from the preview. Prev/Next stop at the ends of the
  current file and wrap rather than rolling into the next result.
- Single-instance / tabbed behavior.

## Working in this repo

* Do not commit changes to the 'git' repository, or offer to. Only the Human
  developer will do commits.
