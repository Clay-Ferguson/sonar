# Sonar — User Guide

Sonar is a desktop search window for the *contents* of files. You type a
query, point it at a folder, and it lists every file underneath that folder
whose text matches — then shows you the file, with the matches highlighted,
without leaving the window.

The searching itself is done by [ugrep](https://github.com/Genivia/ugrep), so
queries are Google-style Boolean expressions and a large source tree is
scanned in seconds.

This guide covers everything the window does. For the configuration file in
detail, see [CONFIG.md](CONFIG.md).

---

## Contents

- [Before you start](#before-you-start)
- [Starting Sonar](#starting-sonar)
- [The window at a glance](#the-window-at-a-glance)
- [Running a search](#running-a-search)
- [Query syntax](#query-syntax)
- [The results list](#the-results-list)
- [The preview pane](#the-preview-pane)
- [Stepping through matches](#stepping-through-matches)
- [PDFs](#pdfs)
- [Opening a file in your editor](#opening-a-file-in-your-editor)
- [Searching inside archives](#searching-inside-archives)
- [The Options menu](#the-options-menu)
- [The Settings dialog](#the-settings-dialog)
- [The Help windows](#the-help-windows)
- [Keyboard and mouse](#keyboard-and-mouse)
- [Messages you may see](#messages-you-may-see)
- [Troubleshooting](#troubleshooting)
- [Where Sonar keeps things](#where-sonar-keeps-things)

---

## Before you start

Sonar runs on Linux and needs two things installed:

| Requirement | Why | Install |
|---|---|---|
| **ugrep** | does all the searching; Sonar refuses to start without it | `sudo apt install ugrep` |
| **uv** | builds the Python environment when you launch | [docs.astral.sh/uv](https://docs.astral.sh/uv/) |

`uv` pulls in PyQt6 and PyYAML by itself the first time you run — there is
nothing else to install and nothing to activate.

One optional extra:

- **poppler-utils** (`sudo apt install poppler-utils`), which provides
  `pdftotext`. With it installed, searches read the *text inside* PDF files,
  so PDFs turn up in your results like any other document. Without it, PDFs
  are simply never matched.

If ugrep is missing, Sonar shows a dialog saying so and exits rather than
starting a window that cannot search.

---

## Starting Sonar

From the project directory:

```bash
./start.sh                      # start on the current directory
./start.sh /path/to/folder      # start on a particular folder
```

The folder is the **only** argument, and all it does is prefill the **Folder**
row. Nothing is searched automatically — a search always needs a query, and
the query only ever comes from the window. If you pass a path to a *file*,
Sonar starts on the folder containing it. If you pass a path that does not
exist, Sonar warns you and starts on the current directory instead.

### Adding Sonar to your application launcher

```bash
./install.sh
```

This asks where Sonar lives (press Enter to accept the directory it is run
from), then installs a desktop entry and the application icons into your home
directory. Sonar then appears in your application grid, dock and alt-tab like
any other app. Launched that way it opens on your current working directory,
with the folder row editable as always.

```bash
./uninstall.sh
```

removes the desktop entry and the icons again. Your configuration file is left
alone.

---

## The window at a glance

```
┌─────────────────────────────────────────────────────────────┐
│ Options                                            ← menu bar│
├─────────────────────────────────────────────────────────────┤
│ Search:  [ query…                              ] [ Search ]  │
│ Folder:  [ /home/you/projects                  ] [   …    ]  │
├──────────────────────────┬──────────────────────────────────┤
│ matching files           │ the selected file,               │
│ (newest modified first)  │ read-only, matches highlighted   │
│                          │                                  │
│                          │                                  │
│                          ├──────────────────────────────────┤
│                          │ [Open][Prev][Next] 3 of 12  ☑ Wrap│
└──────────────────────────┴──────────────────────────────────┘
```

- **Menu bar** — **File**, holding **Exit**, and **Options**, holding
  **Settings** and a **Help** submenu.
- **Search row** — the query field and the **Search** button.
- **Folder row** — the folder to search, and a **…** button that opens a
  folder chooser.
- **Results list** (left) — one row per matching file, newest first.
- **Preview pane** (right) — the selected file, read-only.
- **Control bar** (under the preview) — **Open**, **Prev**, **Next**, the
  match counter, and the **Word Wrap** checkbox.
- **Title bar** — this is where Sonar reports on the search. There is no
  status bar at the bottom of the window; the title says `Sonar — Searching…
  42 files` while a search runs and `Sonar — 137 files in /home/you/projects`
  when it finishes.

The divider between the two panes is draggable — grab it and give whichever
side you are reading more room.

---

## Running a search

1. **Set the folder.** Type a path into the **Folder** row (`~` works), or
   press **…** to pick one in a file dialog. The search covers that folder and
   everything under it, recursively.
2. **Type a query** in the **Search** row. See
   [Query syntax](#query-syntax) below.
3. **Press Enter** — from either field — or click **Search**.

Results appear in the left pane **as they are found**, so a long search is
useful before it finishes. The title bar counts them up as they arrive.

When the search finishes, the list re-sorts itself so the **most recently
modified files come first**. That reordering can only happen at the end: files
are found in directory order, and the newest one may turn up last. If a file
was deleted while the search was running, its row is dropped at this point.

The folder row stays editable after a search, which is why the finished title
names the folder the results actually came from.

Pressing **Search** again while a search is running abandons the first one
cleanly and starts over — the two result sets never mix.

Some notes on scope:

- Searches are **case-insensitive**, always.
- A query matches a file when its terms appear **anywhere in that file**, not
  necessarily on the same line.
- Which files are searched at all is governed by the **include** and
  **exclude** patterns in [Settings](#the-settings-dialog). By default nothing
  is included-only and the usual noise directories (`node_modules`, `.git`,
  `.venv`, `build`, `dist` …) are skipped.
- Changes to settings apply to the **next** search. There is no need to
  restart Sonar.

---

## Query syntax

Queries are Boolean expressions over regular expressions.

| Query | Matches files containing |
|---|---|
| `needle` | `needle`, treated as a regular expression |
| `cat dog` | both `cat` and `dog`, anywhere in the file |
| `cat AND dog` | the same thing — a space *is* AND |
| `cat OR dog` | either one |
| `"exact phrase"` | that phrase literally, regex characters and all |
| `cat -dog` | `cat` but not `dog` |
| `cat NOT dog` | the same thing |
| `(cat OR dog) fish` | `fish`, plus at least one of `cat` and `dog` |

Useful regex fragments:

| Fragment | Meaning |
|---|---|
| `\bABC\b` | `ABC` as a whole word |
| `.*` | any run of characters |
| `.{0,10}` | up to ten characters |
| `^TODO` | at the start of a line |

A query starting with `-` (say `-l`) is safe to type — it is passed as a
query, never mistaken for an option.

If ugrep rejects a query — an unbalanced parenthesis, a broken regex — Sonar
shows the message it gave in a dialog, and the results list stays as it was.

The same reference is available inside the app under
**Options ▸ Help ▸ Query Syntax**.

---

## The results list

Each row is one matching file. The row shows the path **relative to the folder
you searched**, since repeating the folder on every row costs width and says
nothing:

```
sonarex/window.py
docs/CONFIG.md
tests/test_queries.py
```

Hover a row to see the **full absolute path** in a tooltip.

A file found inside an archive is labelled with an arrow, and its tooltip
lists the archive and each level below it, one per line:

```
docs.zip → manual/intro.txt
```

Click a row — or walk the list with the **↑/↓ arrow keys** — to show that file
in the preview pane. Arrow-key navigation previews each file as you pass it,
so you can skim a result set from the keyboard.

The list is ordered newest-modified-first once the search completes. Files
found inside the same archive share that archive's timestamp, so they stay
grouped together and in the order they were found.

---

## The preview pane

The right-hand pane shows the selected file. It is **read-only** — Sonar is a
search tool, not an editor. Use [**Open**](#opening-a-file-in-your-editor) when
you want to change something.

Every place your query matched is **highlighted in amber**, and the match you
are currently parked on is highlighted in a hotter color so you can tell it
from the rest. The pane scrolls straight to the first match when a file opens,
rather than leaving you at the top of a long file to hunt for it.

**Word Wrap** (bottom right) is on by default and wraps long lines to the pane
width. Turn it off for code or data where the column layout matters; you then
get a horizontal scroll bar. It is a per-look preference and is not saved
between sessions.

Some files are described rather than shown. In each case the pane holds
Sonar's own words, and nothing is highlighted:

| Notice | Means |
|---|---|
| `Binary file — cannot preview.` | the file is not text |
| `File is too large to preview (…; the limit is 2.0 MiB).` | over the preview cap |
| `(empty file)` | the file has no content |
| `Cannot read this file: …` | permissions, a vanished file, a bad path |

The 2 MiB cap applies to the *preview*, not to the search — a large file is
still searched and still listed, you just cannot read it in the pane.

---

## Stepping through matches

Under the preview:

- **Prev** / **Next** move to the previous or next match **in the file on
  screen**. They step between individual matches, not lines, so a line
  carrying three matches is three stops. Both **wrap around** at the ends of
  the file.
- The **counter** beside them reads `3 of 12` — which match you are on, and
  how many that file has. It is blank, and both buttons are dim, when there is
  nothing to step through: a notice, a file with no visible matches, or no
  selection at all.

Selecting a different file restarts the count at match 1 of that file. Prev
and Next stay within one file — they do not roll over into the next result.

---

## PDFs

If `pdftotext` is installed, PDFs are searched like any other document. When
you select one, Sonar **renders the page** in the preview pane instead of
calling it a binary file. The document opens fit-to-width and scrolls
normally.

**Prev** and **Next** work on a PDF too, jumping to and marking each hit. Two
things behave differently there:

- **The match count climbs for a second or two after a PDF opens.** Pages are
  searched lazily, so `1 of 16` legitimately becomes `1 of 44` while you
  watch. Prev/Next keep working throughout.
- **Only one plain term is searched inside a PDF.** The PDF viewer can search
  for a literal string only — no regexes, no AND/OR, no negation. Sonar picks
  the first term of your query that translates and marks that. If nothing in
  the query translates (`col(o|ou)r`, or a query made only of negations), the
  PDF still renders, with Prev/Next dim.
- The match colors in a PDF are the viewer's own — a pale wash, and a stronger
  color for the current hit — not Sonar's amber. They cannot be changed.

**Word Wrap** is dimmed while a PDF is showing; a rendered page has no line
wrapping to turn off.

A PDF that is corrupt, or that vanished since the search, falls back to the
text pane with a message explaining why. A PDF *inside* an archive is found
and listed, but is shown as a binary notice rather than rendered.

---

## Opening a file in your editor

**Open** (bottom left of the control bar) hands the selected file to a real
editor. It is dim until you select something.

By default that is VS Code (`/usr/bin/code`). You can point it at any editor
from **Options ▸ Settings** — see [the Open command](#the-open-command) below.

Two exceptions:

- **PDFs** are opened with `xdg-open` instead, so they land in whatever PDF
  viewer your desktop is set up to use — not in a text editor.
- **A file inside an archive** has no path an editor can open, so Sonar
  extracts it to a **read-only temporary copy** and opens that. Open's tooltip
  says so before you click. Edits to that copy do **not** go back into the
  archive. The copies are deleted when you close Sonar.

The editor is started independently of Sonar, so it stays open after you close
the search window. If the command cannot be found or fails to start, Sonar
tells you in a dialog naming the command, so you know what to fix.

Sonar refuses to Open a non-text file out of an archive rather than handing
your editor a mangled copy.

---

## Searching inside archives

Turn on **Search inside archives** in **Options ▸ Settings**, and searches also
look inside compressed files: `.zip`, `.tar`, `.tar.gz`, `.tgz`, `.7z`,
`.cpio`, `.gz`, `.bz2`, `.xz`, `.zst`, `.lz4` and the rest of the formats
ugrep can decompress.

A match inside one is listed with an arrow and previews like any other file,
with the same highlighting and the same Prev/Next:

```
docs.zip → manual/intro.txt
```

### How deep to look inside them

The dropdown under the checkbox, **1 to 3**, controls archives nested inside
other archives:

| Setting | Behavior |
|---|---|
| `1 — archives only` | an archive found *inside* an archive is left alone |
| `2 — also archives inside archives` | one level of nesting is opened |
| `3 — three levels deep` | two levels of nesting are opened |

A row names every level it went through:

```
bundle.tar.gz → vendor.zip → src/parser.py
```

Each level is another decompression pass over everything the level above it
produced, so leave this at 1 unless you actually keep archives inside
archives.

The depth is fixed for the results on screen. If you change the setting and
your current results were found at a different depth, the rows already listed
still preview and open correctly — the new depth takes effect from the next
search.

### Things worth knowing

Three of these surprise people, and all three are ugrep's behavior rather than
choices Sonar made:

- **The include patterns apply to the files *inside* an archive too.** A
  whitelist of `*.md` finds the `.md` files inside a zip and nothing else in
  it.
- **Do not add `*.zip` to the include patterns to "enable" archives.** The
  checkbox is what enables them; an include pattern of `*.zip` would instead
  restrict results to files *named* `*.zip` inside archives, which is the
  opposite of what you want.
- **Archives with an unusual extension are only opened if you name that
  extension.** `.jar`, `.docx` and `.epub` are all really zips that ugrep does
  not recognise as archives. To reach inside one, add its extension to the
  include patterns alongside a pattern for the files you want out of it.

And two more:

- **Password-protected and corrupt archives are skipped silently.** They
  produce no rows and no dialog, and they do not stop the rest of the search.
  There is currently no log of what was skipped.
- **Non-text files inside an archive** — a PDF, an image — are found and
  listed, but the preview names them rather than showing them, and **Open**
  declines.

### Why it is off by default

Turning it on **changes what an ordinary search returns**, rather than merely
adding to it: every compressed file on the system becomes searchable text. On
a machine with gzipped documentation, a common word can go from a couple of
thousand hits to several thousand, most of them inside `.gz` files you were
not thinking about.

---

## The Options menu

The second menu in the menu bar — **File** holds only **Exit**. Options has
a dialog and a submenu on it:

| Item | What it opens |
|---|---|
| **Settings** | the settings dialog described below |
| **Help ▸ Query Syntax** | a short reference for the query syntax |
| **Help ▸ User Guide** | this document, in a window of its own |

Neither one affects a search in progress. A saved setting applies from the
next search, or the next press of Open.

---

## The Settings dialog

**Options ▸ Settings.** Five settings, saved to a YAML file you can also edit
by hand (see [CONFIG.md](CONFIG.md)). **Save** writes them and closes;
**Cancel** discards. Enter in the dialog saves.

### Include only these files (empty = search everything)

A **whitelist**, one glob pattern per line. Empty — the default — means every
file is searched.

The moment you add an entry, only files matching one of these patterns are
searched and everything else is silently ignored. This is the one setting that
can quietly hide results you expected to see, so leave it empty unless you
specifically want to search a narrow set of file types:

```
*.md
*.txt
*.py
```

Patterns match the filename, so `*.md` means "any Markdown file at any depth".

### Skip these files and folders

Directories and files to leave out, one pattern per line, written in
`find`-style:

| Pattern | Meaning |
|---|---|
| `*/node_modules/*` | skip any directory named `node_modules`, at any depth |
| `*/src/generated/*` | skip that particular nested path |
| `*.log` | skip files by name |

Sonar ships with a generous list — `node_modules`, `.git`, `.venv`,
`__pycache__`, `venv`, `.svn`, `.hg`, `build`, `dist`, `.next`, `.nuxt`.
Keeping it generous is usually the difference between a search that returns in
a second and one that grinds through a hundred thousand irrelevant files.

### Search inside archives

The checkbox described in [Searching inside
archives](#searching-inside-archives). Off by default.

### How deep to look inside them

The 1-to-3 dropdown, also described above. It is dimmed while the checkbox is
off, but it keeps its value — turning archive searching off and back on does
not lose the depth you picked.

### The Open command

The command the **Open** button runs, defaulting to `/usr/bin/code`. The
selected file is added as the **last argument**:

| You set | Sonar runs |
|---|---|
| `/usr/bin/code` | `/usr/bin/code /path/to/hit.txt` |
| `gedit` | `gedit /path/to/hit.txt` |
| `code -n` | `code -n /path/to/hit.txt` |
| `xdg-open` | opens it in whatever your desktop associates with the type |

Put `%s` anywhere in the command and the file goes **there** instead of at the
end — for editors that want the filename in the middle:

```
gnome-terminal -- vim %s
```

The command is split the way a shell would split it, so quotes work and a
program path containing a space can be quoted. It is **not run through a
shell**, though: pipes, redirection and `&&` do nothing useful. If you need
them, point this at a script.

A bare program name is looked up on your `PATH`; an absolute path is used as
given. Clearing the field resets it to the default rather than breaking Open.

### If the config file is broken

If Sonar could not read your configuration file, the dialog says so at the top
and its fields start **empty**. That warning matters: saving from that state
**replaces** the file rather than editing it. Fix the YAML by hand first if
you want to keep what is in it.

---

## The Help windows

**Options ▸ Help** has two items, and both open the same kind of window: a
document, rendered from a markdown file that ships with Sonar in `docs/`.

| Item | Shows |
|---|---|
| **Query Syntax** | a compact reference for the query language — the Boolean operators, quoting, and a few regex fragments |
| **User Guide** | this document — so if you are reading this inside Sonar, that is how you got here |

The windows are **modeless**: they stay open beside the main window and you
can search while one is up. Asking for the same document again raises the
window already showing it rather than opening a second copy of it.

Links work. A **Contents** entry jumps to that section, a link to another
document — the User Guide's pointers to `CONFIG.md`, say — opens it in the
same window, and the **Back** button returns you to where you were, at the
place on the page you left. A link out to the web opens in your browser.

The text is selectable, so a regex fragment can be copied straight out of a
window and into the query field.

---

## Keyboard and mouse

| Action | How |
|---|---|
| Run the search | **Enter** in the query field or the folder field, or click **Search** |
| Move between fields and buttons | **Tab** |
| Walk the results, previewing each | **↑ / ↓** in the results list |
| See a result's full path | hover the row |
| Open the Options menu | **Alt+O** |
| Settings / Help from the open menu | **S** / **H** (Help then opens a submenu) |
| Resize the panes | drag the divider between them |
| Save the settings dialog | **Enter** |
| Close a dialog | **Esc** |

Prev and Next currently have no keyboard shortcut — use the buttons.

---

## Messages you may see

**In the title bar:**

| Title | Meaning |
|---|---|
| `Sonar` | idle — no search has run yet |
| `Sonar — Searching…` | a search has just started |
| `Sonar — Searching… 42 files` | still running; 42 hits so far |
| `Sonar — No matches` | the search finished and found nothing |
| `Sonar — 137 files in /path` | finished, sorted, and this is where they came from |

**In dialogs:**

| Message | Meaning |
|---|---|
| `Sonar searches with ugrep, which is not installed.` | install ugrep; Sonar exits |
| `No such folder: … Starting in … instead.` | the folder passed on the command line does not exist |
| `Not a folder: …` | the Folder row does not name a directory |
| a ugrep error message | your query was rejected — usually a broken regex |
| `Could not run '…'` | the Open command could not be started |
| `… could not be read` (in Settings) | your config file has a YAML error |

---

## Troubleshooting

**A file I know contains the text did not turn up.**
Check the **include** patterns first — a non-empty whitelist hides everything
that does not match it. Then check **exclude**: the file may be under a
skipped directory. Remember too that a query with two terms requires *both*,
and that `-term` and `NOT term` exclude.

**My search returns far more than it used to.**
**Search inside archives** is probably on. It makes every compressed file on
the system searchable text.

**Nothing inside my `.jar` / `.docx` / `.epub` is found.**
Those are zips with extensions ugrep does not recognise as archives. Add the
extension to the include patterns, alongside a pattern for the files you want
out of it.

**PDFs never match.**
Install `poppler-utils`, which provides the `pdftotext` that ugrep uses to read
them.

**A PDF renders but Prev/Next are dim.**
Your query has no plain literal term to search for inside it — a regex, or
nothing but negations. The document still renders; only the in-page marking is
unavailable.

**The preview says "Binary file" for something I am sure is text.**
It probably contains a NUL byte. Use **Open** to look at it in your editor.

**The preview says the file is too large.**
The preview cap is 2 MiB. The file was still searched and listed; open it in
your editor to read it.

**Edits I made to a file from an archive did not stick.**
They cannot — Open extracts a **read-only copy** for archive members, and the
copy is deleted when Sonar closes. Extract the archive yourself if you need to
edit its contents.

**Results seem to be in no particular order.**
They are in the order they were found until the search *finishes*, at which
point they re-sort newest-first. Wait for the title bar to stop counting.

**My settings changes did nothing.**
They apply the next time the setting is used — the next **Search** press, or
the next **Open** click. Nothing needs restarting.

**A search is slow.**
Add the heavy directories to the exclude list, and check whether **Search
inside archives** is on with a depth above 1.

---

## Where Sonar keeps things

| Path | What |
|---|---|
| `~/.config/sonarex/sonarex-config.yaml` | your settings; created with defaults on first run |
| `~/.local/share/applications/sonarex.desktop` | the launcher entry, if you ran `install.sh` |
| `~/.local/share/icons/hicolor/*/apps/sonarex.png` | the application icons, likewise |
| a temporary directory | read-only copies of archive members you opened, removed when Sonar closes |

Sonar writes nothing else, and never modifies the files it searches.
