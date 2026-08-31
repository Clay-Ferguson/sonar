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
  `convert_excluded_pattern()` turns find-style `*/name/*` into ugrep's
  `!name/`; `search_globs()` is the one call the GUI needs. Loading is
  forgiving by design (see below).
- `sonarex/search.py` — `SearchRunner`, a `QProcess` wrapper that streams
  ugrep's hits back as `matchFound(path)` signals. `build_argv()` owns the
  command line.
- `sonarex/window.py` — `MainWindow`: the two rows, the splitter, the status
  label, and the end-of-search sort.
- `sonarex/style.py` — the shared look: `action_button_style()`, the wider
  scroll bars, `tune_palette()`, `mono_font()`. It exists so a dialog can
  match the window's controls without importing `window`, which opens the
  dialogs and would make that a cycle. It imports nothing from the package
  except `UI_POINT_SIZE`; keep it that way.
- `sonarex/settings.py` — the gear button's dialog: one text area per pattern
  list, one pattern per line. `_add_section()` is where a future setting goes;
  the dialog sizes to its contents, so nothing else has to change.
- `sonarex/viewer.py` — `read_for_preview()`: size cap, binary sniff, decode.
  Always returns a string, never raises.

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
  across, which is why the dialog warns before it gets that far. The write
  goes to a temp file and `os.replace`s over the original: a failure part-way
  must not leave a truncated config, which the loader would read as "no
  patterns" and silently search everything.

- **A QPlainTextEdit's `sizeHint()` is a fixed 256x192**, unrelated to its
  font — so `PatternEdit` overrides it outright rather than taking the larger
  of the two, or the field opens at whatever line count that pixel height
  happens to be. Its height counts the document margin *once*: the document
  runs on underneath the bottom margin, so allowing for it at both ends leaves
  room for the top few pixels of an eighth line.

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

The settings dialog is drivable the same way — `SettingsDialog()` constructs
without the main window, and `_save()` can be called directly instead of
clicking. Point `config.CONFIG_PATH` at a temp file first: it is read at call
time, so rebinding the module attribute is enough, and nothing in a test then
touches the real `~/.config`.

## Not built yet

- Any setting beyond the two pattern lists. The dialog is built to grow —
  another `_add_section()` call and it re-sizes itself — and `render_config()`
  carries unknown keys through, so an option can be added on either side
  first.
- Single-instance / tabbed behavior.

## Working in this repo

* Do not commit changes to the 'git' repository, or offer to. Only the Human
  developer will do commits.
