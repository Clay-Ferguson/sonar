# Notes to AI Agents

## What this is

Sonar is a PyQt6 desktop app: a two-pane content-search window over
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

One of the three dependencies, `windowchrome`, is a **sibling checkout** rather
than a package from PyPI — `[tool.uv.sources]` points at `../windowchrome`,
editable. It has to actually be there or `uv run` fails with an unresolved path
dependency. See the chrome entry under "Things that will bite you".

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
  three accessors instead — `search_globs()` for the ugrep argv,
  `search_depth()` for `-z`/`--zmax`, `open_command()` for the editor — all
  read at the moment of use so a saved change needs no restart and no
  notification. `search_depth()` folds two keys into one number, returning 0
  when archive searching is off, because 0 is the whole of what "off" means to
  every caller; the keys stay separate on disk so clearing the checkbox does
  not discard the depth. `get_bool()`/`get_int()` are the readers behind it.
  `convert_excluded_pattern()` turns find-style `*/name/*` into ugrep's
  `!name/`. Loading is forgiving by design (see below).
- `sonarex/archive.py` — everything that knows what an archive member *is*.
  `Hit(path, member)` is what the app carries instead of a path string, with
  `member` empty for an ordinary file; `parse_result_line()` turns one line of
  ugrep's `%f%s%z%~` output back into one; `member_glob()` builds the `-g` that
  reaches a member; `extract()` runs ugrep over an empty pattern to get the
  member's text back out. It imports nothing from the package — same rule as
  `style.py`, and for the same reason: `search`, `viewer` and `window` all need
  it and must not need each other. `ARCHIVE_EXTENSIONS` is *not* what turns the
  feature on (the setting is); it only answers whether a result with no member
  is still a compressed file, which is the plain `notes.txt.gz` case.
- `sonarex/search.py` — `SearchRunner`, a `QProcess` wrapper that streams
  ugrep's hits back as `matchFound(path)` signals. `build_argv()` owns the
  command line. Beside it, `build_match_argv()`/`match_spans()` are the
  second, much smaller ugrep call: one named file, `-o -u`, and a `--format`
  that reports where the query matched inside it. That one is synchronous —
  ~16ms at the preview's size cap, so it does not need a `QProcess` — and it
  answers `{}` rather than raising on any failure. Both grow a `depth`:
  non-zero puts `-z` and `--zmax` on the argv and a `%z` on the format, and is
  the whole of what archive searching costs the search side. `literal_query_term()`
  also lives here, because it is about the query language rather than about
  PDFs: it reduces a Boolean query to one plain string for Qt's PDF search,
  which knows no regexes, no AND/OR and no negation.
- `sonarex/pdfview.py` — `PdfPane`, the *other* preview: a `QPdfView` that
  renders a PDF instead of describing it as a binary file. `QtPdf` ships in
  the PyQt6 wheel with its own pdfium, so this costs no dependency; the import
  is still guarded, and `PDF_AVAILABLE` false means a PDF falls back to the
  binary notice rather than the app failing. `show_file()` loads and returns a
  message on failure; `count()`/`go_to()` are what Prev/Next drive. The
  matches are marked by `QPdfView` itself, in colors of its own.
- `sonarex/highlight.py` — `MatchHighlighter`, the `QSyntaxHighlighter` that
  paints those spans onto the preview, one of them in a hotter color as the
  current match. It knows nothing about the query; it only colors the ranges
  `match_spans()` hands it, and `set_current()` says which one is parked on.
- `sonarex/window.py` — `MainWindow`: a `QMainWindow` holding the menu bar,
  the two rows, the splitter, the status label, and the end-of-search sort. It
  is a `QMainWindow` rather than a plain `QWidget` only so `menuBar()` exists —
  everything else lives on a central widget; `_build_menus()` is the whole menu
  bar, one Options menu with Settings and Help on it, labels only (these
  were square icon buttons in the query row until they became menu items). Also the Prev/Next walk: `_adopt_matches()`
  flattens the spans into reading order on `self._matches`, and
  `_go_to_match()` is the single place that moves `self._match_index`, marks
  the highlighter, scrolls, and refreshes the counter. The preview is a
  `QStackedWidget` of two panes — the text one and `PdfPane` — and
  `_pdf_showing` says which is up; `_match_total()` and the one branch in
  `_go_to_match()` are all Prev/Next needs to work over either. `HIT_ROLE`
  carries a whole `Hit` rather than a path — one role, because the two halves
  are never meaningful apart and `_sort_by_mtime()` rebuilds every row from it.
  `_search_depth` is pinned in `start_search()` beside `_search_root` and
  `_search_query`, so changing the setting mid-session cannot turn rows already
  on screen into files nothing can read — a member found three levels down is
  only reachable again at the depth that found it. It also decides the label:
  `member_levels()` is what turns one member into
  `L1.zip → L2.tar.gz → inner.txt`. Open's tooltip is the one
  control that changes with the selection (`OPEN_TIP`/`OPEN_TIP_ARCHIVED`):
  a member opens a *copy*, which is worth saying before the click rather than
  after someone has edited one and found the archive unchanged.
- `sonarex/style.py` — the shared look: `action_button()` and the
  `action_button_style()` under it, `menu_style()`, the wider scroll bars,
  `tune_palette()`, `mono_font()`. It exists so a dialog can
  match the window's controls without importing `window`, which opens the
  dialogs and would make that a cycle. It imports nothing from the package
  except `UI_POINT_SIZE`; keep it that way. **Every button in the app is made
  by `action_button()`** — never `QPushButton(...)` at a call site: the
  factory is what carries the color, the padding and `setAutoDefault(False)`,
  and a button built by hand comes out wearing the desktop theme instead
  (which is exactly what the help dialog's `QDialogButtonBox` Close did until
  it was replaced by a plain button). The colors are named for the *role* —
  `PRIMARY_BUTTON_BG` for the main action of a window or dialog (Search,
  Save), `SECONDARY_BUTTON_BG` for anything beside it (Cancel, Close, the
  folder-row `…`), `NAV_BUTTON_BG` for Prev/Next, `selection_button_bg()` for
  Open — so a new button picks a role rather than a hex value.
  `SONAREX_THEME` also lives here: the app's override of `windowchrome`'s
  neutral title bar default (`#1369da`), and the one thing the library needs
  from this app. `splitter_style()` derives its color from
  `windowchrome.body_window_color()` — see the entry below.
- `sonarex/settings.py` — the Options ▸ Settings dialog: one text area per pattern
  list (one pattern per line), a checkbox for Search Archives, a dropdown for
  how deep it goes, and a line edit for the Open command. A future setting is
  one more `_add_patterns()`/`_add_line()`/`_add_check()`/`_add_combo()` call
  plus a field on
  `Settings`; the dialog sizes to its contents, so nothing else has to change.
- `sonarex/viewer.py` — `read_for_preview()`: size cap, binary sniff, decode.
  Always returns a string, never raises. It takes a `Hit` and the setting the
  *search* ran with; a member or a compressed file diverts to
  `_read_compressed()`, which does the same three checks in the same order
  against `archive.extract()`'s bytes instead of against a file on disk. Also `open_in_editor()`, which runs
  `open.command` from the config — `build_open_argv()` is the split-and-place
  rule, and every failure comes back as a message naming the command, since
  the command is now something the user typed. Extensions in
  `SYSTEM_OPEN_EXTENSIONS` (`.pdf`) skip the config key and go to
  `SYSTEM_OPEN_COMMAND` (`xdg-open`) instead, so they land in whatever the
  desktop has registered for them; only the command and the error hint differ,
  the spawn is the same. `is_pdf()` is the one answer to "is this a PDF",
  shared by that and by the window's choice of preview pane. A member has no
  path any editor can open, so `_temp_copy()` extracts it to a read-only file
  under a per-session `tempfile.mkdtemp()` and Open runs against that;
  `cleanup_temp_files()` is what `closeEvent` calls to remove them.

## Things that will bite you

- **ugrep's exit codes are 0 / 1 / 2**, and `1` means *no match*, not failure.
  Treating anything non-zero as an error reports an empty search as broken.
  Verified against ugrep 7.5.0. `2` is not simply "failure" either — see the
  entry on it below; it is also what a skipped file produces.
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
- **Styling `QMenuBar::item` / `QMenu::item` costs you the hover.** As with
  the buttons, a stylesheet on a sub-control opts it out of the native style's
  rendering, so `menu_style()` restates `:selected` — in `palette()` terms, so
  the menus still follow the theme — or a menu highlights nothing under the
  pointer. Padding only, no font size: the menus grow as targets without
  the rest of the header moving. Note that the items carry no icons — if one
  is ever added back, styling `::item` also takes the icon column out of Qt's
  hands and it will need a `QMenu::icon { left: … }` to sit clear of the
  label.

- **The window chrome lives in `windowchrome`, not here — read
  `../windowchrome/README.md` before touching any of it.** The colored title
  bar — and with it the thin frame the decoration draws down the sides and along
  the bottom — is a sibling library (`[tool.uv.sources]` in `pyproject.toml`
  points at `../windowchrome`, editable, so an edit there is live here with no
  reinstall; the checkout has to *be* a sibling or `uv run` fails outright).
  Its README carries the whole of what was measured: that the bar is colorable
  only on Wayland and only by repurposing three application palette roles; that
  `libadwaita.so` links no `QPalette` symbol at all while `bradient` does,
  which is what `QT_WAYLAND_DECORATION` is choosing between; that the
  decoration's `QMargins{3, 30, 3, 3}` are compiled-in constants, so neither
  the bar's height nor the frame's 3px is adjustable; and that a stylesheet
  severs a widget's palette inheritance, which is why an application event
  filter hands the body colors back (measured: 22 widgets leaked without it, 0
  with).

  What this app owes it, and what will break if it is forgotten:
  `windowchrome.configure(SONAREX_THEME)` **before** `QApplication` and
  `windowchrome.install(app)` **after** `tune_palette(app)` — both in
  `__main__`, and both order-sensitive; and `body_window_color()` /
  `body_text_color()` rather than `QApplication.palette()` anywhere a body
  color is derived. `splitter_style()` is the only reader of `Window` in this
  app — it once read the title bar blue and lightened it, painting the handle a
  brighter blue than the bar — while `scrollbar_style()` uses `Base` and
  `selection_button_bg()` uses `Highlight`, neither of which the title bar
  touches. That is the whole integration: three calls, and nothing about any
  window's layout changes.

  The library briefly also painted a thicker border just inside every window
  (`bordered_body()`, `WINDOW_BORDER_WIDTH`, a `QMenuBar` margin to inset the
  menu bar within it). It was removed: the decoration's own 3px frame, which
  takes the title bar's color for free, is what the design wants. Do not
  reintroduce it — `window.py`, `settings.py` and `help.py` are back to plain
  layouts and `menu_style()` is back to padding only.

- **With `-z`, an inclusion `-g` glob filters what is *inside* an archive, not
  which archives are opened.** `-g '*.zip'` alone returns nothing; `-g '*.tex'`
  alone finds the `.tex` inside a zip. So archive patterns must never go in
  `included:` — that was the obvious design and it is exactly backwards, and it
  is why Search Archives is a checkbox instead. The corollary is the one thing
  the checkbox's tooltip has to say: an `included:` whitelist silently applies
  to members too.

- **An archive is only opened at all if ugrep knows its extension**, once any
  inclusion glob is in play. `-g '*.MF'` finds nothing in `apport.jar`;
  `-g '*.MF' -g '*.jar'` finds the manifest. `.jar`, `.docx` and `.epub` are all
  zips ugrep does not recognise, so reaching into one means naming its
  extension in `included:`. `ARCHIVE_EXTENSIONS` in `archive.py` is that list,
  copied from `man ugrep`.

- **A glob containing `/` never matches a path inside an archive.** Verified:
  `-g 'doc-src/Makefile'` returns nothing for the member that `-g 'Makefile'`
  finds. `member_glob()` therefore takes the basename only — which means it can
  reach a second member of the same name, and why everything that uses it
  filters the output by the exact `%z` afterwards rather than trusting the
  glob. It also replaces glob metacharacters with `?` rather than escaping
  them: `?` is one character wide, so the substitution can only widen, and a
  member called `a[1].txt` is not read as a character class.

- **A nested member is one `%z`, colon-joined, not nested braces.** At
  `--zmax=3` ugrep prints `L1.zip{L2.tar.gz:L3.zip:inner.txt}` — one brace pair,
  the levels separated by ':'. So `parse_result_line` needed no change at all;
  only the *label* did. A colon is legal in a filename, which is why
  `member_levels()` refuses to split below depth 2: at one level there is no
  chain a colon could be part of, so `notes:draft.txt` stays one name for
  everyone who has not turned nesting on. Above that the ambiguity is real and
  unresolvable, and it costs a wrong label only — every other use of a member
  matches the exact `%z` string, never the split pieces.

- **A `-g` at depth must name the file at the *bottom* of the chain.**
  `-g 'inner.txt'` reaches `L1.zip{L2.tar.gz:L3.zip:inner.txt}`; `-g` on the
  whole colon chain matches nothing. That is what `member_name()` is for, and
  it takes the depth for the reason above — splitting on the last colon
  unconditionally turns a member honestly called `notes:draft.txt` into
  `draft.txt`, whose glob then reaches nothing. Verified both ways.

- **`--zmax=0` is not "off", it is an error.** ugrep rejects it outright
  (`invalid argument --zmax=0`, exit 2), and since `extract()` reports every
  failure as None, a 0 arriving there would surface as "this file cannot be
  read" rather than as the bug it is. 0 is a real value in this app — it is how
  `search_depth()` says archives are off — so `build_extract_argv` floors it
  at 1.

- **The depth has to be pinned with the search, not read at preview time.** A
  member found at three levels is not reachable at one: the same `--zmax` has
  to go to `match_spans` and `extract` as went to the search, or a file plainly
  on screen comes back unreadable and unhighlighted. This is the same reason
  `_search_root` and `_search_query` are pinned, with a sharper failure.

- **`%f` already contains the braces; `%z` is the member alone.** A result line
  is `archive.zip{member}` + separator + `member`, and the redundancy is the
  point — both halves can legally contain a tab, so `parse_result_line()` tries
  each separator position and takes the one where `%f` ends with `{%z}`. The
  format only goes on the argv when archives are on, so an ordinary search
  emits bare paths exactly as it always has.

- **ugrep's exit 2 does not mean the search failed, and 0/1 do not mean it
  went cleanly.** ugrep uses 2 both for a real failure and for a file it
  skipped and carried on from — and *which of those an encrypted archive
  counts as depends on the build*. Measured: 7.5.0 here exits 0 for a tree
  holding a `zip -P` archive; another machine's build exits 2 for the same
  tree. A directory without read permission exits 2 everywhere.

  So the status cannot decide, and taking it at face value shipped a modal
  error dialog on every search that so much as passed a password-protected zip
  — on some machines only, which is why it survived a full test run here.
  `search.search_error()` reads the stderr instead and keeps only the lines
  that are not per-file notes (`warning:`, `cannot decompress`); empty means
  the search ran. It matches **per line and keeps what it does not recognise**,
  because a bad regex's message runs on for two more lines carrying no marker.

  For the same reason `_on_search_finished` decides "No matches" from
  `_match_count` rather than from `EXIT_NO_MATCH`: a fruitless search over a
  tree with one unreadable file in it exits 2, not 1.

- **ugrep is the extractor, and it is line-based.** `--format='%O%~'` over an
  empty pattern reproduces a member byte for byte — diffed against `unzip -p`
  for a zip member, a `.tar.gz` member and a plain `.gz` — with one exception:
  `%O` is the line without its terminator and `%~` puts one back, so a file
  whose last line has no newline gains one. It cannot carry binary at all,
  which is why a PDF or an image inside an archive gets a notice and why Open
  refuses one rather than handing an editor a mangled copy.

- **The extraction cap is applied to the stripped text, not to ugrep's
  output.** Every line comes back with the member name and a separator in
  front of it, so a file of short lines is several times its own size on the
  wire; capping the raw read would cut a 2 MiB member at a few hundred KiB.

- **`-z` changes what an ordinary search returns, it does not merely add to
  it.** Every compressed file becomes searchable text: `copyright` over
  `/usr/share/doc` goes from 2,285 hits to 3,548, nearly all gzipped docs. That
  is the reason the setting defaults off. Note too that a zip whose entries are
  *stored* rather than deflated already matches without `-z` — as one opaque
  binary row, since ugrep is scanning its raw bytes.

- **`PdfPane` has to be cleared before the window is destroyed.** A
  `QPdfSearchModel` searches pages lazily on its own, so closing while one is
  still working leaves pdfium walking a document Qt is tearing down: measured,
  the process exits **139 (SIGSEGV)** rather than 0, which from a terminal is
  "Segmentation fault" printed after a session that went fine. `closeEvent`
  calls `self._pdf.clear()` for this, and it predates the archive work — it
  reproduces on 7b8c7cf. It is also why the test suite segfaulted until the
  clear went in, since pytest keeps the process alive across tests.

- **"Is this text?" cannot be answered by the NUL sniff alone.** A PDF with
  uncompressed streams contains no NUL byte at all, so
  `viewer._temp_copy` let one through and Open handed an editor a mangled
  copy. It checks `is_pdf(name)` first now, by *name*, the way
  `_read_compressed` always did before extracting. The preview never had the
  bug because it asked that question in the right order.

- **The Open command runs without a shell either**, for the same reason the
  ugrep filter does: `subprocess.Popen` gets an argv list, split by `shlex`.
  Quotes and spaces in a program path work; pipes, redirection and `&&` do
  not. Do not "fix" that with `shell=True` — the command reaches this code
  from a text field, and a shell would make a stray `;` in it executable.

- **`--filter` runs without a shell.** ugrep executes a filter command
  directly, so `PDF_FILTER` can contain no pipes or redirection — hence
  `pdftotext -q % -` rather than a shell one-liner. Exercised: a search for
  `font` over a folder of PDFs returns them, so the filter path works with
  pdftotext 25.x.

- **`QPdfView.setCurrentSearchResultIndex()` does not scroll.** It marks the
  result and nothing else — measured, the scroll bar stays at 0 for a hit
  thirteen pages down. Scrolling is a separate
  `pageNavigator().jump(link.page(), link.location())`, which is why
  `PdfPane.go_to()` does both, jump first.

- **`QPdfView`'s match colors cannot be changed** — a pale blue wash, and
  opaque cyan for the current hit. They are compiled in, not taken from the
  palette (confirmed: re-rendering with Highlight set to red moves not one
  pixel). Painting the marks in this app's own yellow was tried and reverted:
  it means withholding the search model from the view and reimplementing its
  private page layout, since there is no page-to-viewport mapping in the
  public API — a lot of fragile geometry for a color.

- **A `QPdfSearchModel`'s count arrives over time.** Pages are searched
  lazily: on a 26-page file the count climbed 1 → 16 → 26 → 44 across about a
  second. So the counter is driven by `countChanged` (`_on_pdf_count_changed`)
  rather than read once at load, "1 of n" legitimately has n grow while the
  user watches, and any index has to be re-checked against the count of the
  moment — an early Next can outrun the search.

- **Qt's PDF search is one literal string.** No regex, no AND/OR, no
  negation, which is most of what an ugrep query can be. `literal_query_term()`
  drops what it cannot translate rather than approximating it — a regex
  searched literally would mark text the search never matched — and returning
  None is ordinary: the PDF renders with Prev/Next dim, exactly like a file
  with no matches.
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

There is a pytest suite under `tests/`. Run it with:

```bash
./tests/run.sh                       # everything, ~1s
./tests/run.sh tests/test_nested.py  # one file
./tests/run.sh -k archive -v         # by name
```

`run.sh` is a two-line wrapper: it sets `QT_QPA_PLATFORM=offscreen` and pulls
pytest and pytest-qt in with `uv run --with`, so **nothing is declared in
`pyproject.toml` and there is no install step** — the same bargain `start.sh`
makes for the app itself. Keep it that way; the app ships two dependencies and
the test tooling should not become a third.

Layout: `conftest.py` builds every fixture archive from the standard library
into pytest's `tmp_path`, so nothing is checked in and nothing is left in
`/tmp` by hand. `helpers.py` reads the window back — `labels()`,
`highlighted()`, `select()`, `nav()`. The suites are split by what they drive:
`test_archive` (no Qt at all), `test_config`, `test_settings`,
`test_window`, `test_queries`, `test_nested`.

These are integration tests, deliberately: they run a real ugrep over real
archives rather than mocking it, because nearly every bug this code has had
lived in what ugrep actually does. That is also why they are worth running
before *any* change to `search.py`, `archive.py` or `viewer.py`.

The flip side, learned the hard way: **a green run says this ugrep on this
filesystem, not "correct"**. Three tests passed here and failed on another
machine — two because that build's exit status for an encrypted archive
differs, one because its disk wrote both fixture archives inside a single
mtime tick. Where behavior can vary like that, pin it rather than observe it:
the fixture stamps explicit mtimes with `os.utime`, and the exit-status tests
call `_on_search_finished` with the status directly instead of hoping the
local ugrep produces it.

Three fixtures carry the load and are worth knowing before adding a test:

- `tree` — the archive tree. Its zip entries are **stored, not deflated**, on
  purpose: that is what makes it match a raw byte search with `-z` off, which
  is what `test_a_zip_is_one_opaque_row_when_off` pins. Deflate it and that
  test starts passing for the wrong reason.
- `conf` — a callable that writes a config and points `config.CONFIG_PATH` at
  a temp file, so no test can reach the real `~/.config`.
- `dialogs` — **autouse**, and load-bearing. A `QMessageBox` still blocks for
  a click under `offscreen`, so one raised by code under test hangs the whole
  run instead of failing it. This intercepts them all and hands back what
  would have been shown, which is also the only way to assert that a problem
  *was* reported.

`win.grab().save(path)` still renders the window to a PNG when you want to see
a layout rather than assert on it.

Syntax checks:

```bash
python3 -m py_compile sonarex/*.py
bash -n start.sh install.sh uninstall.sh
```

Worth covering when you change search or results handling, most of it already
in `test_queries.py` and `test_window.py`: exclusions from the config, an
`included:` whitelist, a query starting with `-`, a folder with spaces in its
name, no matches, a bad regex, a binary file, a file over the 2 MiB preview
cap, and repeated Search presses mid-search.

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

For the PDF pane, assert on the objects rather than on pixels: `_pdf_showing`
and `_panes.currentWidget()` say which pane is up, `match_label.text()` is the
counter, and `pdf.verticalScrollBar().value()` moving is what proves a jump
actually happened — that last one is the check that catches
`setCurrentSearchResultIndex()`'s non-scrolling from being "simplified" back
in. Spin a `QEventLoop` for a second or so after selecting a PDF, or the count
is still climbing when the assertion runs. `/usr/share/texmf/doc/fonts/lm/lm-info.pdf`
is a 26-page file with ~50 hits for `font`; truncating it makes a corrupt one.
Worth covering: a query with no literal term (`col(o|ou)r`, `-font`) — renders,
nav dim; a corrupt or vanished PDF — falls back to the text pane with the
message; switching PDF → text → PDF, where each pane must re-adopt its own
matches and Word Wrap must follow; wrapping off both ends; and Open on a PDF,
which still spawns `xdg-open`.

For archives, build the tree rather than hunting for one: a `.zip` and a
`.tar.gz` over the same staging directory, a plain `.gz`, a loose `.txt`, a
`zip -P` encrypted one and a `head -c 120` truncation of the zip. The staged
files are what the interesting cases are made of — two members sharing a
basename in different directories, one called `a[1].txt`, a CRLF file, a file
with no trailing newline, one with multi-byte characters ahead of the match,
and one with blank lines in the middle. Then assert against the document the
same way as for any other preview.

Worth covering: that the argv with the setting off is byte-for-byte the old one
(the regression guard for every existing user); the two same-basename members
previewing differently; the metacharacter name; a plain `.gz` previewing as
text rather than "Binary file"; that the encrypted and truncated zips produce
no rows, no dialog, and do not stop the rest of the tree from landing; that
`_sort_by_mtime` leaves an archive's members contiguous (they share the
archive's mtime, and the sort is stable only because it keys on the time
alone); a PDF inside a zip, which is a *real* hit — the `pdftotext` filter
reaches into archives — and must show the notice, stay on the text pane, and
be refused by Open; that Open on a text member leaves one read-only copy with
the right basename which `closeEvent` then removes; and that Open's tooltip
follows the selection between its two texts.

For nesting, build one archive inside another inside a third and search a
directory holding *only* the outermost — the staging copies are hits too, and
they make the result set unreadable. Worth covering: that depth 1 does not
reach the nested file and depth 3 does; that the row reads
`L1.zip → L2.tar.gz → L3.zip → inner.txt` while `HIT_ROLE` still holds the raw
colon-joined member; that the extracted copy is named `inner.txt` and not the
whole chain; that a member called `notes:draft.txt` in a plain zip is one level
at depth 1 and still previews; and that `read_for_preview` at the *wrong* depth
returns a notice, which is the check that keeps `_search_depth` from being
"simplified" into a fresh `search_depth()` call.

The settings dialog is drivable the same way — `SettingsDialog()` constructs
without the main window, and `_save()` can be called directly instead of
clicking. Point `config.CONFIG_PATH` at a temp file first: it is read at call
time, so rebinding the module attribute is enough, and nothing in a test then
touches the real `~/.config`.

## Not built yet

- **A log for files that were skipped.** An encrypted or corrupt archive is
  dropped in silence — deliberately, since a dialog per bad zip would be worse
  — but that means there is no way to find out it happened. ugrep already says
  why on stderr and `SearchRunner` already collects it; nothing writes it
  anywhere. There is no logging in the app at all yet, which is the first half
  of this job.
- PDFs, images and other binaries inside archives. They are found and listed,
  and the preview and Open both say why they cannot be shown. Doing better
  means a real extractor — `unzip -p`, `tar -xOf`, `7z e -so` — instead of
  ugrep, since ugrep's output is lines; a temp file would then also let
  `PdfPane` render an archived PDF.
- More than three levels of nesting. `--zmax` accepts 1..99; the dialog offers
  1..3 (`archive.MAX_DEPTH`) because each level is another decompression pass
  and three is already past what an ordinary tree holds. Raising the ceiling is
  one constant and one more entry in `settings.DEPTH_LABELS`.
- Further settings. The dialog is built to grow — another `_add_patterns()` or
  `_add_line()` call and it re-sizes itself — and `render_config()` carries
  unknown keys through, so an option can be added on either side first.
- Keyboard shortcuts for Prev/Next. The buttons are the only way to step; F3
  and Shift+F3 would be a `QShortcut` each onto `_step_match`, which already
  takes the direction as its argument.
- Stepping between *files* from the preview. Prev/Next stop at the ends of the
  current file and wrap rather than rolling into the next result.
- Highlighting more than one term in a PDF. `literal_query_term()` returns the
  first translatable term and the search model takes one string, so `cat dog`
  marks the `cat`s. Every term would mean a model per term and a counter that
  sums across them.
- Zoom and page controls for the PDF pane. It opens fit-to-width and scrolls;
  `QPdfPageSelector` and `setZoomFactor()` are there when they are wanted.
- Single-instance / tabbed behavior.

## Working in this repo

* Do not commit changes to the 'git' repository, or offer to. Only the Human
  developer will do commits.
