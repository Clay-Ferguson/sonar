# Sonar

![Python](https://img.shields.io/badge/python-3.11+-blue.svg) ![Platform](https://img.shields.io/badge/platform-linux-lightgrey.svg) ![License](https://img.shields.io/badge/license-MIT-green.svg)

A desktop search utility: type a query, get every file under a folder whose *contents* match — or, with the dropdown set to **Filenames**, every file and folder whose *name* matches — and read them without leaving the window.

[ugrep](https://github.com/Genivia/ugrep) does the searching, so queries are Google-style Boolean expressions and a whole source tree is scanned in seconds. Sonar is the window around it — results stream in as they are found, clicking one shows the file with every match highlighted, and **Open** hands it to your editor.

## Sonar App Window
![](docs/img/application.png)

## Settings Dialog
![](docs/img/settings-dialog.png)

**Highlights**

- Boolean queries — `cat dog`, `cat OR dog`, `"exact phrase"`, `cat -dog` — matched anywhere in a file, case-insensitively
- Every match highlighted in the preview, with Prev/Next and a counter
- PDFs rendered in the window and searched in place
- Optional search *inside* archives (`.zip`, `.tar.gz`, `.7z`, `.gz` …), up to three levels of nesting
- Optional near-match searching, so `color` also finds `colour` — off by default
- Include/exclude glob patterns and a configurable Open command

## Documentation

📖 **[User Guide](docs/USER_GUIDE.md)** — the full walkthrough: every control in the window, the query language, PDFs, archive searching, the settings dialog, keyboard shortcuts and troubleshooting. Start here.

⚙️ **[Configuration reference](docs/CONFIG.md)** — the YAML file behind the settings dialog, key by key.

Both are readable **inside the app** as well, under **Options ▸ Help** — the same files, rendered in a window with working links and a Back button, so the guide is never a browser tab away from the thing it describes.

🛠 **[AGENTS.md](AGENTS.md)** — architecture and implementation notes, for anyone working on the code.

## Requirements

```bash
sudo apt install ugrep
```

`ugrep` is required — Sonar says so and exits if it is missing. The Debian package below depends on it, so `apt` brings it along; installing it by hand is only needed when running from this checkout.

Running from the checkout also needs `uv` (see [uv's install page](https://docs.astral.sh/uv/)); it pulls in PyQt6 and PyYAML on first run. The package needs neither — it uses the distribution's `python3-pyqt6` and `python3-yaml`.

Optional: `poppler-utils`, for `pdftotext`. With it installed, ugrep searches the text inside PDFs, so they turn up in results.

### The `windowchrome` sibling project

Sonar's wide scroll bars, enlarged check boxes and help windows come from **[windowchrome](https://github.com/Clay-Ferguson/windowchrome)**, a small reusable PyQt6 library kept in its own repository so other apps can share the same look and show their own documentation the same way. It is **not on PyPI**: `pyproject.toml` resolves it by path, from a directory sitting *beside* this one.

```bash
cd ..                      # the directory holding sonar/
git clone https://github.com/Clay-Ferguson/windowchrome.git
```

giving:

```
projects/
├── sonar/
└── windowchrome/          <- must be a sibling, and named this
```

If it is missing, `./start.sh` and `./tests/run.sh` fail immediately with an unresolved path dependency rather than with anything subtle. The checkout is used in place — `uv` installs it editable, so there is nothing to build and an edit there is live here on the next run.

## Running

```bash
./start.sh                      # search the current directory
./start.sh /path/to/folder      # start on a particular folder
```

The folder is the only argument, and it just prefills the **Folder** row — nothing is searched until you type a query and press Enter.

`start.sh` runs the app through [uv](https://docs.astral.sh/uv/), which creates and refreshes the virtualenv from `pyproject.toml` on every run — there is no install step and nothing to activate.

## Installing

```bash
./build-deb-install.sh
sudo apt install ./dist/sonarex_0.1.0_all.deb
```

`build-deb-install.sh` builds `dist/sonarex_<version>_all.deb`, which any Debian-based distribution can install if its repositories carry `python3-pyqt6`, `ugrep` and Python 3.11 or newer. It installs:

| Path | What it is |
|---|---|
| `/usr/bin/sonarex` | The launcher. |
| `/usr/lib/sonarex/` | The `sonarex` package, a copy of `windowchrome`, and `docs/`. |
| `/usr/share/applications/sonarex.desktop` | The application-menu entry. |
| `/usr/share/icons/hicolor/*/apps/sonarex.png` | The icon, at every size. |

`docs/` is installed because it is read at runtime, not just for reference: **Options ▸ Help** renders `HELP.md` and `USER_GUIDE.md` straight out of it.

The desktop entry names no folder, because one entry serves every user on the machine: launched from the application grid, Sonar opens on the current working directory and the folder row is editable anyway. Running `sonarex /path/to/folder` from a terminal still prefills it.

PyQt6 and PyYAML aren't bundled. The package depends on the distribution's own `python3-pyqt6` and `python3-yaml`, which `apt` installs along with it, and `uv` isn't needed at all. `ugrep` is a hard dependency — Sonar can't search without it. `poppler-utils` (for searching inside PDFs) and `xdg-utils` (for the default **Open** command) are recommended, not required.

Building needs only `dpkg-deb`, which every Debian system has, and the `windowchrome` sibling checkout described above, whose source is copied into the package. The version comes from `pyproject.toml`. The package's Maintainer field comes from your `git config user.name` and `user.email`; override it with `SONAREX_MAINTAINER="Name <email>"`.

When installing from inside your home folder, `apt` may end with this notice:

```
N: Download is performed unsandboxed as root as file '.../sonarex_0.1.0_all.deb' couldn't be accessed by user '_apt'. - pkgAcquire::Run (13: Permission denied)
```

It's harmless, and the package still installs normally. `apt` usually reads package files as its unprivileged `_apt` user, and Ubuntu home folders are private by default, so `apt` read the file as root instead. To avoid the notice, copy the `.deb` somewhere world-readable first, such as `/tmp`, and install it from there.

Remove the package with `sudo apt remove sonarex`. Your config at `~/.config/sonarex/` is untouched.

The package is the only way to install Sonar. To run it from this checkout instead — while working on it, say — use `./start.sh` directly; there is nothing to install for that.

## Tests

```bash
./tests/run.sh
```

pytest and pytest-qt are fetched by the script itself, so there is nothing to install first. See [AGENTS.md](AGENTS.md#testing) for the layout.

## License

MIT — see [LICENSE.md](LICENSE.md).
