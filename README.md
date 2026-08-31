# SonarEx

![Python](https://img.shields.io/badge/python-3.11+-blue.svg)
![Platform](https://img.shields.io/badge/platform-linux-lightgrey.svg)
![License](https://img.shields.io/badge/license-MIT-green.svg)

A desktop search utility: type a query, get every file under a folder whose
*contents* match, and read them without leaving the window.

[ugrep](https://github.com/Genivia/ugrep) does the searching, so queries are
Google-style Boolean expressions and a whole source tree is scanned in
seconds. SonarEx is the window around it — results stream in as they are
found, and clicking one shows the file.

## Running

```bash
./start.sh                      # search the current directory
./start.sh /path/to/folder      # start on a particular folder
```

The folder is the only argument, and it just prefills the **Folder** row —
nothing is searched until you type a query and press Enter. Without an
argument, SonarEx starts on the current working directory. Either way the
folder row stays editable, with a **…** button for picking one.

`start.sh` runs the app through [uv](https://docs.astral.sh/uv/), which creates
and refreshes the virtualenv from `pyproject.toml` on every run — there is no
install step and nothing to activate.

`./install.sh` adds a desktop entry and its icon so SonarEx shows up in your
application launcher; `./uninstall.sh` removes both.

## The window

```
┌──────────────────────────────────────────────┐
│ [ search query…                  ] [Search]  │
│ Folder: [ /mnt/projects            ] [  …  ] │
├────────────────────┬─────────────────────────┤
│ matching files     │ the selected file       │
│ (newest first)     │ (read-only)             │
├────────────────────┴─────────────────────────┤
│ 11 files — newest first                      │
└──────────────────────────────────────────────┘
```

Results appear as ugrep finds them, then settle into newest-modified-first
order once the search finishes — ugrep walks the tree in directory order, so
the useful ordering can only be applied once everything is in.

Select a file with the mouse or the arrow keys to read it on the right. The
pane is read-only and wraps long lines; it is not an editor. Binary files
(PDFs included) are named rather than shown, and very large files are
described instead of loaded.

**Open** hands the selected file to a real editor — VS Code by default, or
whatever command you set in the settings dialog.

## Query syntax

Queries run in ugrep's Boolean mode (`-%`) at whole-file scope (`--files`),
so a query matches a file when the terms are somewhere in it, not necessarily
on the same line.

| Query | Matches files containing |
|---|---|
| `needle` | `needle` (as a regex) |
| `cat dog` | both `cat` and `dog`, anywhere in the file |
| `cat OR dog` | either one |
| `"exact phrase"` | that phrase literally, regex characters and all |
| `cat -dog` | `cat` but not `dog` |
| `cat NOT dog` | the same thing |

Searches are case-insensitive.

## Configuration

`~/.config/sonarex/sonarex-config.yaml`, created with sensible defaults the
first time SonarEx runs:

```yaml
search:
  included: []          # empty = search everything (the default)
  excluded:
    - "*/node_modules/*"
    - "*/.git/*"

open:
  command: "/usr/bin/code"
```

`excluded` skips the directories nobody means to search. `included` is a
whitelist — leave it empty unless you want to search *only* certain file
types, since any entry hides everything else. `open.command` is what the Open
button runs; the file is added as the last argument.

Edit all three from the gear button in the top row — one pattern per line in
each list — or open the file directly. Either way the change applies the next
time it is used, with no restart. See [docs/CONFIG.md](docs/CONFIG.md) for the
full reference.

## Requirements

```bash
sudo apt install ugrep
```

`ugrep` is required — SonarEx says so and exits if it is missing. `uv` is
required to launch (see [uv's install page](https://docs.astral.sh/uv/)); it
pulls in PyQt6 and PyYAML on first run.

Optional: `poppler-utils` (for `pdftotext`). With it installed, ugrep searches
the *text inside* PDFs, so they turn up in results — though the preview pane
still reports them as binary rather than displaying them.

## History

SonarEx began as a Nautilus context-menu extension that drove `zenity` and
`gnome-terminal`. It is now a standalone application: a Nautilus extension
runs inside the Nautilus process, which is GTK, and PyQt6 cannot live there.
Going PyQt6 meant dropping the file-manager integration and, with it, several
hundred lines of shell that existed only to work around zenity.

## License

MIT — see [LICENSE.md](LICENSE.md).
