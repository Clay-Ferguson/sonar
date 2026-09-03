# Sonar

![Python](https://img.shields.io/badge/python-3.11+-blue.svg)
![Platform](https://img.shields.io/badge/platform-linux-lightgrey.svg)
![License](https://img.shields.io/badge/license-MIT-green.svg)

A desktop search utility: type a query, get every file under a folder whose
*contents* match, and read them without leaving the window.

[ugrep](https://github.com/Genivia/ugrep) does the searching, so queries are
Google-style Boolean expressions and a whole source tree is scanned in
seconds. Sonar is the window around it — results stream in as they are found,
clicking one shows the file with every match highlighted, and **Open** hands it
to your editor.

## Sonar App Window
![](docs/img/application.png)

## Settings Dialog
![](docs/img/settings-dialog.png)

**Highlights**

- Boolean queries — `cat dog`, `cat OR dog`, `"exact phrase"`, `cat -dog` —
  matched anywhere in a file, case-insensitively
- Every match highlighted in the preview, with Prev/Next and a counter
- PDFs rendered in the window and searched in place
- Optional search *inside* archives (`.zip`, `.tar.gz`, `.7z`, `.gz` …), up to
  three levels of nesting
- Include/exclude glob patterns and a configurable Open command

## Documentation

📖 **[User Guide](docs/USER_GUIDE.md)** — the full walkthrough: every control
in the window, the query language, PDFs, archive searching, the settings
dialog, keyboard shortcuts and troubleshooting. Start here.

⚙️ **[Configuration reference](docs/CONFIG.md)** — the YAML file behind the
settings dialog, key by key.

Both are readable **inside the app** as well, under **Options ▸ Help** — the
same files, rendered in a window with working links and a Back button, so the
guide is never a browser tab away from the thing it describes.

🛠 **[AGENTS.md](AGENTS.md)** — architecture and implementation notes, for
anyone working on the code.

## Requirements

```bash
sudo apt install ugrep
```

`ugrep` is required — Sonar says so and exits if it is missing. `uv` is
required to launch (see [uv's install page](https://docs.astral.sh/uv/)); it
pulls in PyQt6 and PyYAML on first run.

Optional: `poppler-utils`, for `pdftotext`. With it installed, ugrep searches
the text inside PDFs, so they turn up in results.

### The `windowchrome` sibling project

Sonar's colored title bar and window border come from
**[windowchrome](https://github.com/Clay-Ferguson/windowchrome)**, a small
reusable PyQt6 library kept in its own repository so other apps can wear the
same chrome — and, since the help windows were added, so they can show their
own documentation the same way. It is **not on PyPI**: `pyproject.toml`
resolves it by path, from a directory sitting *beside* this one.

```bash
cd ..                      # the directory holding sonarex/
git clone https://github.com/Clay-Ferguson/windowchrome.git
```

giving:

```
projects/
├── sonarex/
└── windowchrome/          <- must be a sibling, and named this
```

If it is missing, `./start.sh` and `./tests/run.sh` fail immediately with an
unresolved path dependency rather than with anything subtle. The checkout is
used in place — `uv` installs it editable, so there is nothing to build and an
edit there is live here on the next run.

## Running

```bash
./start.sh                      # search the current directory
./start.sh /path/to/folder      # start on a particular folder
```

The folder is the only argument, and it just prefills the **Folder** row —
nothing is searched until you type a query and press Enter.

`start.sh` runs the app through [uv](https://docs.astral.sh/uv/), which creates
and refreshes the virtualenv from `pyproject.toml` on every run — there is no
install step and nothing to activate.

`./install.sh` adds a desktop entry and its icon so Sonar shows up in your
application launcher; `./uninstall.sh` removes both.

## Tests

```bash
./tests/run.sh
```

pytest and pytest-qt are fetched by the script itself, so there is nothing to
install first. See [AGENTS.md](AGENTS.md#testing) for the layout.

## License

MIT — see [LICENSE.md](LICENSE.md).
