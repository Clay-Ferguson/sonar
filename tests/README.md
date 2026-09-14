# Testing notes

Run with `./tests/run.sh` (see `AGENTS.md`). These are integration tests: they run a real ugrep over real archives rather than mocking it, because nearly every bug this code has had lived in what ugrep actually does.

**A green run says "this ugrep on this filesystem", not "correct".** Three tests once passed here and failed on another machine — two because that build's exit status for an encrypted archive differs, one because its disk wrote both fixture archives inside a single mtime tick. Where behavior can vary, pin it: the fixture stamps explicit mtimes with `os.utime`, and the exit-status tests call `_on_search_finished` with the status directly.

## Layout

`conftest.py` builds every fixture archive from the standard library into pytest's `tmp_path`, so nothing is checked in. `helpers.py` reads the window back — `labels()`, `highlighted()`, `select()`, `nav()`, `status()`, `searching()`. The `spawned` fixture and `NOOP_OPENER` record what Open or the folder button hands to the system opener. `search(folder, query, mode)` sets the mode dropdown.

Suites: `test_archive` (no Qt), `test_config`, `test_settings`, `test_window`, `test_queries`, `test_nested`, `test_fuzzy`, `test_status`, `test_help`, `test_names`.

## Fixtures worth knowing

- `tree` — the archive tree. Its zip entries are **stored, not deflated**, on purpose: that is what makes it match a raw byte search with `-z` off, which `test_a_zip_is_one_opaque_row_when_off` pins. Deflate it and that test passes for the wrong reason.
- `fuzzy_tree` — four spellings of one word at *stated* edit distances from `color`, so a search returns an exactly known set at every setting. Its zip is deflated and padded on purpose: a small member is stored even when deflate is asked for, and stored bytes would match a raw search with `-z` off.
- `name_tree` — for Filenames mode: a folder, an empty file, a mixed-case name, and a file with the word only in its content (content mode lists it, names mode must not).
- `conf` — writes a config and points `config.CONFIG_PATH` at a temp file, so no test reaches the real `~/.config`. It is read at call time, so rebinding the module attribute is enough.
- `dialogs` — **autouse, and load-bearing.** A `QMessageBox` still blocks for a click under `offscreen`, so one raised by code under test hangs the run instead of failing it. This intercepts them and hands back what would have been shown, which is also how to assert a problem *was* reported.

## Gotchas

- `test_help.py` must **not** hand a help window to `qtbot.addWidget`: those windows set `WA_DeleteOnClose`, and pytest-qt's teardown then fails the *following* test. Its link tests are pure text and run in milliseconds. The rendering itself is windowchrome's and tested in `../windowchrome/tests/`.
- `SettingsDialog()` constructs without the main window; call `_save()` directly instead of clicking.
- `win.grab().save(path)` renders the window to a PNG when you want to see a layout.

## What to cover, by area

**Search and results** (mostly in `test_queries.py`, `test_window.py`): config exclusions, an `included:` whitelist, a query starting with `-`, a folder with spaces, no matches, a bad regex, a binary file, a file over the 2 MiB preview cap, repeated Search presses mid-search.

**Preview highlighting.** Assert on the document, not pixels: walk the blocks, read `block.layout().formats()`, collect runs whose background is `MATCH_BG`. Cover: an AND query with terms on different lines (both highlighted, `--files` scope), `OR` against a file matching one branch, a `NOT`/`-` term (no highlight), a quoted phrase, CRLF, multi-byte characters ahead of the match, a notice (binary/over-cap, no highlight), and a first match thousands of lines down (pane scrolls to it).

**Prev/Next.** The *current* match is painted `MATCH_CURRENT_BG`, not `MATCH_BG` — collect both for "what did ugrep find", only the former for "which one is current". Cover: two hits on one line (two stops), wrapping off either end, switching files restarts the count, a notice or fresh search leaves the buttons dim and the counter blank.

**PDF pane.** Assert on objects: `_pdf_showing`, `_panes.currentWidget()`, `match_label.text()`, and `pdf.verticalScrollBar().value()` moving (the check that catches the non-scrolling `setCurrentSearchResultIndex()`). Spin a `QEventLoop` for about a second after selecting a PDF, since the count climbs lazily. `/usr/share/texmf/doc/fonts/lm/lm-info.pdf` is a 26-page file with ~50 hits for `font`; truncate it for a corrupt one. Cover: a query with no literal term (`col(o|ou)r`, `-font`) renders with nav dim; a corrupt or vanished PDF falls back to the text pane with a message; PDF → text → PDF re-adopts each pane's matches and Word Wrap follows; wrapping; Open on a PDF spawns `xdg-open`.

**Archives.** Cover: the argv with the setting off is byte-for-byte the old one; two same-basename members preview differently; a member named `a[1].txt`; a plain `.gz` previews as text; encrypted and truncated zips produce no rows, no dialog, and don't stop the rest of the tree; `_sort_by_mtime` keeps an archive's members contiguous (stable sort keyed on time alone); a PDF inside a zip is a real hit that shows the notice, stays on the text pane, and is refused by Open; Open on a text member leaves one read-only copy with the right basename, removed by `closeEvent`; Open's tooltip follows the selection.

**Nesting.** Search a directory holding *only* the outermost archive — staging copies are hits too. Cover: depth 1 doesn't reach the nested file, depth 3 does; the row reads `L1.zip → L2.tar.gz → L3.zip → inner.txt` while `HIT_ROLE` holds the raw colon-joined member; the extracted copy is named `inner.txt`; a member called `notes:draft.txt` in a plain zip is one level at depth 1 and previews; `read_for_preview` at the *wrong* depth returns a notice (keeps `_search_depth` pinned).

**Fuzzy.** Assert on the *set* of files, with edit distances pinned in the fixture. Cover: argv at 0 carries no `--fuzzy`; 1 reaches one edit and not two; the first-character rule as a pair on one word (`dolor` never, `colot` at 1); quoted phrases and regexes both widen; the highlight is the approximate text (`colour`, not `color`); fuzzy and archives compose on one argv; `match_spans` at the wrong `fuzzy` returns `{}` (keeps `_search_fuzzy` pinned).

**Status bar.** Drive `_take_line()` directly — the stats block's wording is ugrep's and the edge cases can't come from a fixture tree. Cover: no row is ever a stats line (including a path that looks like one, and anything after the block); the count arrives and is at least the number of files matched; the bar is green while searching and not after; the spinner survives a hit arriving (`_set_busy` idempotence); the window title is `Sonar` regardless.
