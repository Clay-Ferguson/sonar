# Notes to AI Agents

## What this is

Sonar is a PyQt6 desktop app: a two-pane content-search window over [ugrep](https://github.com/Genivia/ugrep). A query field and folder row across the top; below, a splitter with matching paths on the left and a read-only preview on the right. A **Content / Filenames** dropdown switches a search to matching file and folder *names*, which runs GNU `find` instead of ugrep (ugrep cannot list names — it only reports files whose content matched, never directories or empty files).

It **used to be a Nautilus extension**. That is gone deliberately: PyQt6 cannot live inside Nautilus's GTK process. Any file-manager integration must be a separate process launched with a folder argument — never an import into Nautilus — and none of the old zenity/detach/status-file bash should come back.

The modules are heavily commented, and the comments record *why* (usually with measurements against real ugrep/Qt behavior). Read the comments at a site before "simplifying" it.

## Running

```bash
./start.sh [FOLDER]
```

`start.sh` runs through `uv`; `pyproject.toml` sets `package = false`, so there is no install step and edits are live. `windowchrome` is a **sibling checkout** (`[tool.uv.sources]` → `../windowchrome`, editable) — it must exist or `uv run` fails.

The folder is the only CLI argument, is optional (`nargs="?"` → the current directory), and only prefills the folder row; no search ever runs automatically. Startup failures are `QMessageBox`es, not argparse/stderr errors, because the app is launched from a desktop icon — which is also why the argument must stay optional.

Installed from the `.deb` it is `sonarex` instead, running `/usr/lib/sonarex` under `python3 -I`, so neither `PYTHONPATH` nor pip user installs can shadow the distribution's PyQt6. See `packaging/build-deb.sh`.

## Layout

Top level: `sonarex/` (the app), `docs/` (runtime help content, shipped), `tests/`, `packaging/` (`build-deb.sh`, the `.desktop` template, and `icons/` with their source art and `make-icons.py`), `start.sh` and `lint.sh`. Tool settings live in `ruff.toml`, `pyrightconfig.json` and `pytest.ini`, so `pyproject.toml` stays the runtime dependency list. The package:

- `__main__.py` — entry point: argparse, `QApplication`, ugrep check, folder resolution.
- `config.py` — YAML config (`Settings`, a frozen dataclass; `load_settings`/`save_settings`), read **at the moment of use** (once per search, and `open_command()` per Open click), so saved changes need no restart. Every key is one row of `KEYS` (field, section, name, kind, comment), which drives loading, rendering and the known-key set. `Settings.active_included`/`active_excluded`/`depth` are the one place the `use_*` switches and the archives checkbox are read for searching.
- `patterns.py` — what the config's glob patterns mean to ugrep (`build_glob_args`) and find (`build_prune_args`), `pattern_problems()`, and the dialog's one-pattern-per-line text form. Pure; imports nothing from the package.
- `spec.py` — `SearchSpec`, the frozen record of one search (query, root, mode, depth, fuzzy, translated globs/prune clause), built by `SearchSpec.from_settings()` from a single `load_settings()`; `search_problems()` checks the lists a search will apply. Pure: no disk, no Qt.
- `archive.py` — `Hit(path, member)` (member empty for ordinary files), result-line parsing, member globs, extraction via ugrep. Imports nothing from the package.
- `query.py` — `MODE_CONTENT`/`MODE_NAMES`, and the two places the app reads a query itself: `name_terms()` (find `-iname` patterns) and `literal_query_term()` (one string for PDF search). Pure.
- `search.py` — the argv builders, each taking a `SearchSpec`: content search (`build_argv`), name search (`build_name_argv`), per-file match spans (`build_match_argv`, run synchronously by `match_spans`). Also ugrep's exit codes and `ugrep_available()`. No Qt.
- `runner.py` — `SearchRunner` (`QProcess` streaming hits from either argv), the `--stats` split, and `search_error()`/`name_search_error()`, which tell a real failure from per-file notes.
- `window.py` — `MainWindow`: menus, the query and folder rows, the results list, running a search and reading its results back, the end-of-search mtime sort, and what Open / the folder button do with the selected row.
- `preview.py` — `PreviewPanel`, the right-hand pane: text pane + `MatchHighlighter`, `PdfPane`, the control bar (Open, folder, Prev/Next, counter, Word Wrap) and the walk through the current file's matches. The window only calls `show_hit(hit, search)`, `clear()` and `shutdown()`.
- `statusbar.py` — `SearchStatusBar`: message, text spinner and the green searching state (`set_status(message, busy)`).
- `reader.py` — `read_for_preview()` (always returns a string, never raises), `is_pdf()`, the preview size cap.
- `launch.py` — `open_hit()` (editor, or `xdg-open` for PDFs and folders), `open_folder()`, the child environment, and `TempCopies`, the read-only copies Open extracts from archives. The window owns one `TempCopies`.
- `highlight.py` — `MatchHighlighter`, paints the spans it is given; knows nothing about the query.
- `pdfview.py` — `PdfPane` (`QPdfView`); `PDF_AVAILABLE` false falls back to the binary notice.
- `settings.py` — Options ▸ Settings dialog. Adding a setting = one `_add_*()` call + a field on `Settings` + a row in `config.KEYS` (an import-time assert catches a field with no row).
- `help.py` — opens `docs/HELP.md` and `docs/USER_GUIDE.md` via `windowchrome.show_markdown()`. Help text is markdown, not Python.
- `style.py` — shared look. Imports nothing from the package except `UI_POINT_SIZE` (it exists so dialogs needn't import `window`).

## Rules

- **Every button is made by `style.action_button()`** (or `icon_button()`), never `QPushButton(...)` directly — a hand-built button wears the desktop theme (`tests/test_rules.py` guards it). Pick a color by role (`PRIMARY_BUTTON_BG`, `SECONDARY_BUTTON_BG`, `NAV_BUTTON_BG`, `selection_button_bg()`), not a hex value.
- **Shared widget looks live in `windowchrome`** (scroll bars, check boxes, markdown help windows). Change them there, and read `../windowchrome/README.md` first.
- **Do not style the title bar or window frame**, and keep the window title just the app name (search numbers belong in the status bar; `test_the_title_bar_is_only_the_app_name` guards it). Title-bar coloring was removed as too fragile.
- **Do not restyle the rendered help documents** (link colors, code backgrounds, injected anchors). Modifying the document once stopped Qt's layout part way, rendering sections as blank space. `tests/test_help.py::test_the_whole_document_is_laid_out` is the only guard and must run against the real `docs/` — don't delete it.
- **`docs/` is runtime content.** Renaming a heading changes its slug and breaks links (including the guide's Contents). Run `tests/test_help.py` before and after editing docs. Don't add non-help markdown under `docs/`; the link test globs it.
- **The `.deb` is built by `packaging/build-deb.sh`** (with the desktop template and icons beside it in `packaging/`). It copies the whole `sonarex/`, `windowchrome/` and `docs/` trees under `/usr/lib/sonarex/`, then smoke-tests the stage before packing: every intra-package import resolves to a staged file, every relative doc link resolves, and the modules import under `python3 -I` (only the Qt-free ones when the system python3 has no PyQt6). A failure there means a package that would have installed cleanly and failed on first use. `docs/` must stay beside the package, because `help.DOCS_DIR` resolves it that way. The Debian package and the Python package are both `sonarex`, but the program and its repository are "Sonar".
- **No shells.** ugrep, find, `--filter` and the user's Open command all run as argv lists (`shlex` for the Open command). Never `shell=True` — the command comes from a text field (`tests/test_rules.py` guards it).
- **Config loading must never raise.** Bad or missing config degrades to "no patterns". Saving rewrites the whole file (comments included) via temp file + `os.replace`.
- **Anything a preview or Open needs is pinned at search start** in the window's one `self._search: SearchSpec`, not re-read from config or the rows. `start_search` reads the config exactly once (`test_one_search_reads_the_config_once`). A member found at depth 3 is unreachable at depth 1; the wrong fuzziness silently highlights nothing. Tests at the wrong depth/fuzziness exist to stop this being "simplified".
- **Only the widget modules import Qt** (`window`, `preview`, `statusbar`, `runner`, `highlight`, `pdfview`, `settings`, `help`, `style`). `archive`, `config`, `patterns`, `spec`, `query`, `search`, `reader` and `launch` are plain Python; `test_the_non_widget_modules_never_import_qt` guards it.
- **Empty the preview only through `PreviewPanel.clear()`** (selection → None, `start_search`, a selected row dropped by the sort) — it is what resets Prev/Next along with the text.
- **`closeEvent` must call `panel.shutdown()`** (it clears `PdfPane`; else SIGSEGV on exit), `self._copies.cleanup()` and `close_markdown_windows()`.
- Do not commit to git, or offer to. Only the human developer commits.

## ugrep / find behavior that shapes the code

Each of these is verified and explained at its site; listed here because they are easy to "fix" into a bug.

- **Exit codes don't decide success.** ugrep: 0 match, 1 no match, 2 error *or* skipped file (build-dependent for encrypted archives). `find` exits 1 for any unreadable directory. Failure is decided from stderr (`search_error()` / `name_search_error()`), and "No matches" from the match count.
- **`--stats` goes to stdout after the last hit.** `SearchRunner._take_line()` separates it (lines starting `/` are hits; the stats block is sticky). Keep `--stats` last on the argv.
- **`--` before the query is load-bearing**; the folder is passed absolute so every printed path is absolute.
- **`-g` filters explicitly named files too**, so `build_match_argv()` omits the config globs.
- **A `/` in a pattern fails silently**, so `patterns.pattern_problems()` refuses it (checked on Save and before every search). Any `/` in an include pattern empties the *whole* search; an exclude pattern with `/` must start with `*/`, which `convert_excluded_pattern` turns into `**/` (ugrep's `*` never crosses `/`).
- **With `-z`, inclusion `-g` globs filter archive *members*, not which archives open** — so archive extensions never go in `included:`. A glob containing `/` never matches inside an archive; `member_glob()` uses the basename and callers filter by exact `%z`.
- **`--zmax=0` and `--fuzzy=0` are errors, not "off".** 0 means off in this app, so builders omit the flag (or floor depth at 1 for extraction). With archives and fuzzy off the argv must be byte-for-byte the plain one.
- **Fuzzy's first character always matches exactly**, and fuzzy widens negated terms too. Don't work around either.
- **Highlight spans are line + character column (`%n`/`%k`/`%j`), not byte offsets** — Qt strips CRLF and text is decoded. `%k` expands tabs to 8 columns unless `--tabs=1` is on the argv. Set spans *before* `setPlainText`; use `QSyntaxHighlighter`, not `setExtraSelections` (14× slower).
- **Result ordering is done in Python** at completion (`_sort_by_mtime`); ugrep's sort is per-directory only.
- **`_read_stdout` splits on `"\n"`, not `splitlines()`** (`\v`, `\f`, `\x85` are legal in filenames).
- **`SearchRunner.stop()` disconnects before killing**, so a superseded search can't deliver late results.
- **`find` quirks:** prune with `-path '*/name'` (not `*/name/*`), `-mindepth 1` protects the root, `stdbuf -oL` avoids pipe buffering, and a query containing `/` is refused up front.
- **Qt PDF:** search is one literal string; the match count arrives lazily (`countChanged`); `setCurrentSearchResultIndex()` doesn't scroll (jump separately); match colors are compiled in and can't be changed.

## Testing

```bash
./tests/run.sh                       # everything, ~1s
./tests/run.sh tests/test_nested.py  # one file
./tests/run.sh -k archive -v         # by name
```

`run.sh` sets `QT_QPA_PLATFORM=offscreen` and pulls in pytest/pytest-qt with `uv run --with` — keep test tooling out of `pyproject.toml`. Tests are integration tests against real ugrep and real archives, deliberately; run them before any change to `search.py`, `runner.py`, `archive.py`, `reader.py` or `launch.py`. A green run means *this* ugrep on *this* filesystem — pin varying behavior (mtimes, exit statuses) rather than observing it.

Before writing tests, read `tests/README.md` (fixtures, the autouse `dialogs` fixture that stops `QMessageBox` hanging the run, and what is worth covering per feature). Also run `../windowchrome/tests/` when touching help rendering.

Static checks: `./lint.sh` — ruff (`ruff.toml`: pyflakes, pycodestyle, bugbear, import order at 100 columns), pyright in basic mode over `sonarex/` (`pyrightconfig.json`; `reportOptionalMemberAccess` is off because PyQt6's stubs mark nearly every getter Optional), and `bash -n` on every script. Keep it clean; there is no formatter — the code's own style stands.


