# Sonar configuration

Sonar reads one file:

```
~/.config/sonarex/sonarex-config.yaml
```

It is created with defaults the first time Sonar runs. It holds the two lists of glob patterns that scope every search, the two archive settings, how closely a word has to match, and the command the Open button runs.

Edit them from **Options ▸ Settings** in the window's menu bar. The file can still be edited by hand; the dialog and the file are two views of the same settings. Saving from the dialog **rewrites the file**, so any comments or blank lines you added by hand are replaced by Sonar's own.

## The file

```yaml
search:
  # Files to search. An EMPTY list means "search everything" (the default).
  included: []

  # Directories and files to skip.
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

  # Look inside .zip, .tar.gz, .7z, .gz and the rest. Off by default.
  archives: false

  # How many levels of archive-inside-archive to open, 1 to 3.
  archive_depth: 1

  # How many characters a word may differ by and still count as a hit.
  # 0 is off — exact matches only.
  fuzzy: 0

open:
  # The command the Open button runs.
  command: "/usr/bin/code"
```

Changes take effect the next time the setting is used — the next search, or the next press of Open. There is no need to restart Sonar.

## `search.included`

A **whitelist**. Empty (the default) means every file is searched.

The moment you add an entry, only files matching one of these patterns are searched and *everything else is silently ignored* — which is the one setting here that can quietly hide results you expected to see. Leave it empty unless you specifically want to search a narrow set of file types.

```yaml
search:
  included:
    - "*.md"
    - "*.txt"
    - "*.py"
```

Patterns are matched against the filename, so `*.md` means "any Markdown file at any depth".

## `search.excluded`

Directories and files to skip. Written in `find -path` style; Sonar translates them into ugrep's glob syntax:

| You write | Sonar passes to ugrep | Meaning |
|---|---|---|
| `*/node_modules/*` | `!node_modules/` | skip any directory named `node_modules`, at any depth |
| `*/src/generated/*` | `!**/src/generated/**` | skip that nested path |
| `*.log` | `!*.log` | skip files by name |

The common case is the first row: `*/NAME/*` excludes a directory called `NAME` wherever it appears in the tree.

Exclusions are worth keeping generous. Skipping `node_modules`, `.git` and build output is usually the difference between a search that returns in a second and one that grinds through a hundred thousand irrelevant files.

## `search.archives`

`true` or `false`, default `false`. The **Search inside archives** checkbox in the settings dialog. With it on, a search also looks inside every format ugrep can decompress — `.zip`, `.tar`, `.tar.gz`, `.tgz`, `.7z`, `.cpio`, `.gz`, `.bz2`, `.xz`, `.zst`, `.lz4`, `.br` and the rest — and a match inside one is listed as `archive.zip → path/inside.txt`.

Two interactions are worth knowing, because both are ugrep's behavior rather than a choice Sonar made:

- **`included` applies to the files inside an archive too.** A whitelist of `["*.md"]` finds the `.md` files in a zip and nothing else in it. Do *not* add `"*.zip"` to `included` to "enable" archives — it does the opposite, and would restrict members to ones named `*.zip`.
- **Only archives ugrep recognises by extension are opened**, once `included` has anything in it at all. `.jar`, `.docx` and `.epub` are all really zips that ugrep does not know, so reaching into one means adding that extension to `included` yourself — alongside a pattern for the files you want out of it.

It is off by default because it changes what an ordinary search returns rather than merely adding to it: every compressed file becomes searchable text, which on a system with gzipped documentation can be most of the results.

Archives that are password-protected or corrupt are skipped without comment. Files inside an archive that are not text — a PDF, an image — are still found and listed, but the preview names them instead of showing them, and **Open** declines rather than handing an editor a mangled copy.

## `search.archive_depth`

`1`, `2` or `3`, default `1`. The **How deep to look inside them** dropdown, which is ugrep's `--zmax`. It only does anything when `search.archives` is on, and it is kept separately from it so that turning archive searching off and back on does not lose the depth you picked.

At `1` an archive found *inside* an archive is treated as a binary file and left alone. Raise it and those are opened too, and the row names every level:

```
bundle.tar.gz → vendor.zip → src/parser.py
```

Each level is another decompression pass over everything the level above it produced, so the cost grows with the setting. Leave it at `1` unless you actually keep archives inside archives.

Out-of-range values are clamped rather than rejected — `archive_depth: 99` means 3 — since a number outside the range says clearly enough what was wanted. ugrep itself allows up to 99; Sonar offers 3 because past that the cost is real and the case is rare.

## `search.fuzzy`

`0`, `1`, `2` or `3`, default `0`. The **Find near matches** dropdown, which is ugrep's `--fuzzy`. `0` means exact matching and is off in the fullest sense: the flag is not passed at all, and the command line is the one Sonar has always built.

Above `0` it is how many characters a word may differ by and still be found — one edit finds `colour` for `color`, two also finds `collour`. Unlike the archive settings this is a single key rather than a switch plus a number, because "off" is the first position of the same dropdown and there is no cleared checkbox whose value would need remembering.

Three things about it are ugrep's behavior rather than choices Sonar made, and all three surprise people:

- **The first letter always has to be right.** An approximate match has to begin at the pattern's first character, so `xolor` finds nothing at any setting even though it is one character from `color`. This is also why a short query stays useful: `if` at `3` still does not match `of`.
- **It applies to the whole query, not to one kind of term.** Quoted phrases, unquoted regexes and Boolean terms all become approximate together. A regex is widened *on top of itself* — `col(o|ou)r` at `1` also reaches `collour`.
- **`NOT` and `-` terms become approximate too**, so a negated term excludes more than it did. That is consistent, and it is worth knowing before wondering where a file went.

The cost is real but modest at these settings. Over `/usr/share/doc`, `copyright` returns 2285 files exactly, 2286 at `1`, 2294 at `2` and 2426 at `3`. The ceiling is `3` because `4` returns 4826 — at four errors `color` matches `cat`, and the results stop being an answer. Out-of-range values are clamped rather than rejected, as `archive_depth` is.

One asymmetry to expect: a **PDF** can be found by an approximate search, because ugrep reads it through `pdftotext`, but the PDF viewer's own search takes one literal string and has no approximate mode. Such a PDF opens and renders with **Prev** and **Next** dimmed and nothing marked — the same state a query with no plain word in it already produces.

## `open.command`

The command the **Open** button runs on the selected file. It defaults to `/usr/bin/code` (VS Code), which is what Sonar used before this was configurable.

The command is split the way a shell would split it — so quotes work, and an editor whose path contains a space can be quoted — but it is **not run through a shell**. Pipes, redirection, `&&` and environment assignments do nothing useful; if you need them, point this at a script.

The selected file is added as the **last argument**:

| `open.command` | Sonar runs |
|---|---|
| `/usr/bin/code` | `/usr/bin/code /path/to/hit.txt` |
| `gedit` | `/usr/bin/gedit /path/to/hit.txt` |
| `code -n` | `/usr/bin/code -n /path/to/hit.txt` |
| `xdg-open` | opens it in whatever the desktop associates with the type |

Unless you write `%s`, in which case the file goes there instead — for a command that takes the filename in the middle:

```yaml
open:
  command: "gnome-terminal -- vim %s"
```

A bare program name is looked up on `PATH`; an absolute path is used as given. Either way, a command that cannot be found is reported in a dialog naming the program, rather than failing silently.

The editor is started in its own session with its streams discarded, so it outlives Sonar and cannot block the window. Sonar's own virtualenv is stripped from the environment it inherits — otherwise VS Code would offer Sonar's Python interpreter to whatever project it opens.

## When the config is missing or broken

Every failure degrades to "no patterns", never to an error:

- **File missing** — recreated with the defaults above on the next run.
- **Malformed YAML** — reported on stdout, and the search runs unfiltered. The settings dialog says so at the top of the window when you open it, since its fields start empty in that case and saving would replace the file rather than edit it.
- **A key holding the wrong type** (say `included: "*.md"` instead of a list) — that key is ignored; the others still apply.
- **An empty or non-string `open.command`** — the default editor is used, so clearing the field in the dialog resets it rather than breaking Open.
- **A non-boolean `search.archives`** (`"yes"`, `1`) — read as `false`, so a typo means archives are not searched rather than a broken search.
- **A non-integer `search.archive_depth`** (`"2"`, `true`) — the default of 1 is used. `true` counts as a mistake here even though Python calls a bool an int; out-of-range numbers are clamped instead.
- **Non-string entries** in a list — dropped individually.

A search never fails because of a typo in this file. If results look wrong, check the file for a mistake rather than assuming the search broke.

## What is *not* configurable

Case-insensitivity, Boolean query mode, whole-file matching, and the PDF filter are fixed. They are the behavior described in the [User Guide](USER_GUIDE.md#query-syntax) and are not read from this file.
