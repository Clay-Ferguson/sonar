"""What Sonar does with the file the user picked: show it, or open it.

`read_for_preview` answers what the read-only pane should display. Every
answer is a string — a file that can't be read produces a notice describing
why, never an exception, since it runs inside a selection-changed callback
where a traceback would take the window down.

`open_in_editor` hands the file to a real editor, for when reading it here
isn't enough. Which editor is a config key (`open.command`), read at the
moment of the click, so changing it in the settings dialog takes effect on
the next Open rather than the next run. PDFs bypass that key entirely and go
to the desktop's default application instead.

`open_folder` is the same handoff aimed one level up — the folder the file
sits in, given to the desktop's file manager.

All three take a `Hit` rather than a path, because with Search Archives on a
result can name a file inside a zip, which no editor and no `open()` can
reach. Those go through `archive.extract` — to the pane directly for a
preview, and to a temporary copy for Open. `open_folder` needs neither: the
folder it wants is the one holding the archive.
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import tempfile

from . import archive
from .archive import Hit, member_name
from .config import open_command

# Where the selected file goes in a configured command, if the user says.
# Without it the path is appended, which is what almost every editor wants;
# with it, the path can sit in the middle — `gnome-terminal -- vim %s`.
PATH_PLACEHOLDER = "%s"

# Beyond this, the file is described rather than shown. The pane holds plain
# text, and loading tens of megabytes into it stalls the GUI thread laying
# out a document nobody is going to read top to bottom anyway.
MAX_PREVIEW_BYTES = 2 * 1024 * 1024

# The same ceiling for a member extracted for Open. Higher, because an editor
# can handle a file the preview pane cannot — but not unbounded, since the
# extraction is buffered in memory before it is written to the temp copy.
MAX_ARCHIVE_OPEN_BYTES = 64 * 1024 * 1024

# The one extension the app treats specially, named once: the preview pane
# renders these itself (see `pdfview.py`) and Open sends them to the system
# rather than to the configured editor. Two behaviors, one answer to "is this
# a PDF".
PDF_SUFFIX = ".pdf"

# File types the configured editor is the wrong tool for, and the command
# they go to instead. `xdg-open` is the freedesktop way to ask "open this
# with whatever is registered for it", so the file lands in the same viewer
# double-clicking it in a file manager would use. It is deliberately not a
# config key: the point of it is that the *system* decides, and a second
# configurable command would only give the user another one to get wrong.
#
# `open_folder` uses the same command for the same reason: what is registered
# for a directory is the desktop's file manager.
SYSTEM_OPEN_EXTENSIONS = {PDF_SUFFIX}
SYSTEM_OPEN_COMMAND = "xdg-open"


def is_pdf(path: str) -> bool:
    """Whether `path` is a PDF, by extension.

    By name rather than by sniffing the file's header: the caller is deciding
    which pane to show before anything has been opened, and a PDF that does
    not parse is reported by the viewer that tried, which says more than a
    silent fall back to "binary file" would.
    """
    return os.path.splitext(path)[1].lower() == PDF_SUFFIX


# How much of the file is examined for the binary check. A NUL in the first
# few KiB is what separates text from everything else in practice, and it is
# the same heuristic grep-family tools use.
SNIFF_BYTES = 8192


def _human_size(size: int) -> str:
    value = float(size)
    for unit in ("bytes", "KiB", "MiB", "GiB"):
        if value < 1024 or unit == "GiB":
            precision = 0 if unit == "bytes" else 1
            return f"{value:.{precision}f} {unit}"
        value /= 1024
    return f"{size} bytes"  # unreachable; keeps the return type honest


def _too_large(size: str, where: str) -> str:
    return (
        f"File is too large to preview "
        f"({size}; the limit is {_human_size(MAX_PREVIEW_BYTES)}).\n\n{where}"
    )


def _read_compressed(hit: Hit, depth: int) -> tuple[str, bool]:
    """`read_for_preview` for a file ugrep had to decompress to search.

    Two shapes reach here: a named member of an archive, and a plain
    compressed file like `notes.txt.gz`, which has no member but is no more
    readable with `open()` than the first is. Both come back through
    `archive.extract`, and the checks after that are the same ones and in the
    same order as the ordinary path — binary, then size, then decode — just
    against bytes already in hand rather than against a file on disk.
    """
    where = f"{hit.member}\n\ninside {hit.path}" if hit.member else hit.path

    # PDFs are the one binary worth naming. One inside an archive is a real
    # search hit — ugrep's pdftotext filter reaches into archives too — so it
    # is worth saying why it cannot be shown rather than calling it binary and
    # leaving the user to guess. `PdfPane` cannot help: it loads a path.
    if is_pdf(hit.member or hit.path):
        return (
            f"PDFs inside archives cannot be previewed.\n\n{where}\n\n"
            "Open the archive to read it.",
            True,
        )

    data = archive.extract(hit, MAX_PREVIEW_BYTES, depth)
    if data is None:
        return (
            f"Cannot read this file out of the archive:\n\n{where}\n\n"
            "It may be encrypted, corrupt, or in a format ugrep cannot "
            "decompress.",
            True,
        )
    if b"\x00" in data[:SNIFF_BYTES]:
        return ("Binary file — cannot preview.", True)
    if len(data) > MAX_PREVIEW_BYTES:
        # `extract` stops one byte past the cap, so the true size is unknown
        # here in a way it is not for a file on disk — hence "more than".
        return (_too_large(f"more than {_human_size(MAX_PREVIEW_BYTES)}", where), True)
    return (data.decode("utf-8", "replace"), False)


def read_for_preview(hit: Hit, depth: int = 0) -> tuple[str, bool]:
    """The text to show for `hit`, and whether it is a notice rather than content.

    The caller uses the flag only to style the pane; both cases are just text.

    Binary files are named as such rather than shown. PDFs used to be the
    galling case of that — ugrep searches inside them, so one turns up in the
    results and then had nothing to show — and they no longer reach here at
    all: `pdfview.PdfPane` renders them, and this is only their fallback for
    when it cannot.

    `depth` is the archive nesting the *search* ran with — 0 for a search that
    had archives off — rather than whatever the settings say now, so a result
    found before the checkbox was cleared still previews the way it was found,
    and a member three levels down is re-opened at the depth that reached it.
    Under a non-zero one, a member and a plain compressed file both divert to
    `_read_compressed`; everything else reads straight off the disk as always.
    """
    path = hit.path
    if depth and (hit.member or archive.is_compressed(path)):
        return _read_compressed(hit, depth)

    try:
        size = os.path.getsize(path)
    except OSError as exc:
        return (f"Cannot read this file:\n\n{path}\n\n{exc}", True)

    if size == 0:
        return ("(empty file)", True)

    try:
        with open(path, "rb") as handle:
            head = handle.read(SNIFF_BYTES)
            if b"\x00" in head:
                return (
                    f"Binary file — cannot preview.",
                    True,
                )
            if size > MAX_PREVIEW_BYTES:
                return (_too_large(_human_size(size), path), True)
            # Small enough and not binary: re-read from the top rather than
            # concatenating `head`, so the decode sees one whole byte string
            # and a multi-byte character straddling the sniff boundary can't
            # be mangled.
            handle.seek(0)
            data = handle.read()
    except OSError as exc:
        return (f"Cannot read this file:\n\n{path}\n\n{exc}", True)

    # "replace" rather than "strict": a file with one bad byte is still worth
    # reading, and a search hit has already proved there is text in there.
    return (data.decode("utf-8", "replace"), False)


# Where extracted copies go, created on the first Open of an archive member
# and removed when the window closes. One directory for the session, with a
# numbered sub-directory per file inside it: two members can share a basename,
# and the basename has to be kept — it is what tells the editor which language
# it is looking at.
_temp_root: str | None = None
_temp_count = 0


def _temp_copy(hit: Hit, depth: int) -> tuple[str | None, str | None]:
    """Extract `hit` to a file on disk. Returns (path, error); one is None.

    The copy is made read-only, which is the closest this can come to being
    honest: nothing written to it goes back into the archive, and an editor
    that says "read-only" in its title bar says so before the user has typed
    anything rather than after.
    """
    global _temp_root, _temp_count

    name = member_name(hit.member, depth)
    data = archive.extract(hit, MAX_ARCHIVE_OPEN_BYTES, depth)
    if data is None:
        return (
            None,
            f"Cannot read '{name}' out of the archive:\n\n"
            f"{hit.path}\n\nIt may be encrypted, corrupt, or in a format ugrep "
            "cannot decompress.",
        )
    # `is_pdf` first, and by name rather than by sniffing, for the same reason
    # the preview checks it before extracting at all: ugrep's extraction is
    # line-based, so a PDF comes back mangled whether or not it happens to
    # hold a NUL byte — and one whose streams are uncompressed holds none.
    # The NUL sniff catches everything else.
    if is_pdf(name) or b"\x00" in data[:SNIFF_BYTES]:
        # What comes back is text or it is nothing worth writing: handing an
        # editor a mangled PDF would be worse than saying no.
        return (
            None,
            f"'{name}' is not a text file, and Sonar "
            "can only extract text out of an archive.\n\nOpen the archive "
            "itself to get at it.",
        )

    try:
        if _temp_root is None:
            _temp_root = tempfile.mkdtemp(prefix="sonar-")
        _temp_count += 1
        folder = os.path.join(_temp_root, str(_temp_count))
        os.mkdir(folder)
        # The name at the bottom of the chain, not the chain: a temp file
        # called `L2.tar.gz:L3.zip:inner.txt` tells the editor it is looking at
        # a tarball, and the extension is the whole point of keeping the name.
        path = os.path.join(folder, name)
        with open(path, "wb") as handle:
            handle.write(data)
        os.chmod(path, 0o444)
    except OSError as exc:
        return (None, f"Could not write a temporary copy to open:\n\n{exc}")
    return (path, None)


def cleanup_temp_files() -> None:
    """Remove every extracted copy. Called when the window closes."""
    global _temp_root
    if _temp_root is None:
        return
    shutil.rmtree(_temp_root, ignore_errors=True)
    _temp_root = None


def _child_env() -> dict[str, str]:
    """Our environment, minus Sonar's own virtualenv.

    start.sh runs the app through `uv run`, which puts .venv/bin on PATH and
    sets VIRTUAL_ENV. Left in place those are inherited by the editor, so
    VS Code would offer Sonar's interpreter as the Python environment for
    whatever project it opens. The editor should see the environment a
    terminal would give it, not ours.
    """
    env = os.environ.copy()
    venv = env.pop("VIRTUAL_ENV", None)
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    if venv:
        bin_dir = os.path.normpath(os.path.join(venv, "bin"))
        kept = [
            p
            for p in env.get("PATH", "").split(os.pathsep)
            if p and os.path.normpath(p) != bin_dir
        ]
        env["PATH"] = os.pathsep.join(kept)
    return env


def build_open_argv(command: str, path: str) -> list[str]:
    """`command` as an argv list with `path` in it.

    Split the way a shell would split it — quotes and escapes honored — but
    nothing is handed to a shell, so an editor whose path has a space in it
    works while a pipe or a redirection in the command does not. That is the
    same trade `search.py` makes with ugrep's `--filter`.

    The path is substituted for `%s` wherever it appears, in whole tokens or
    inside one (`--file=%s`), and appended as the last argument when it does
    not appear at all — which is the case for every ordinary editor.

    Raises ValueError on a command shlex cannot split, e.g. one with an
    unbalanced quote; the caller turns that into a message.
    """
    parts = shlex.split(command)
    if not parts:
        raise ValueError("the command is empty")
    if any(PATH_PLACEHOLDER in part for part in parts):
        return [part.replace(PATH_PLACEHOLDER, path) for part in parts]
    return parts + [path]


def _start_detached(argv: list[str], subject: str, hint: str) -> str | None:
    """Run `argv`, detached from Sonar. An error message, or None.

    Shared by both buttons in the control bar, since "hand this to another
    program and forget about it" is the whole of what each of them does once
    it has decided what to hand over. `subject` is what was being opened, for
    the message; `hint` is where the caller says what to do about it.

    The program is checked on PATH first, so a missing one is reported as the
    missing program it is instead of a bare OSError from the spawn.

    Spawned with `start_new_session=True` and its streams discarded, so the
    editor or the file manager is not a child that dies with Sonar and cannot
    stall the GUI by filling a pipe nobody reads.
    """
    program = argv[0]
    if not os.path.isabs(program):
        resolved = shutil.which(program)
        if resolved is None:
            return f"Cannot open {subject}: '{program}' is not on PATH.{hint}"
        argv[0] = resolved
    elif not os.path.exists(program):
        return f"Cannot open {subject}: {program} is not installed.{hint}"

    try:
        subprocess.Popen(
            argv,
            env=_child_env(),
            start_new_session=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError as exc:
        return f"Could not open {subject}:\n{exc}"
    return None


def open_in_editor(hit: Hit, depth: int = 0) -> str | None:
    """Open `hit` with the configured command. An error message, or None.

    A hit inside an archive is extracted to a read-only temporary copy first
    and that copy is what opens — see `_temp_copy`. Everything below is then
    the same either way, since by that point it is a path like any other.

    PDFs are the exception: the configured command is a text editor, and a
    text editor shows a PDF as the binary it is. Those go to `xdg-open`
    instead, which hands the file to whatever the desktop has registered for
    it — the same thing double-clicking it in a file manager would do. The
    rest of this function is unchanged either way, since the difference is
    only which command runs.

    An error is returned rather than raised so the caller can show it: failing
    to open a file is worth saying, but not worth an exception out of a button
    handler. Every way this can go wrong — a command that will not parse, a
    program that is not installed, a spawn that fails — comes back as a
    string naming the command. For the configured command that message also
    says where to fix it, since it is something the user typed; for the
    system opener there is nothing to fix in the dialog, so it says where the
    file was being sent instead.

    Which program is decided here; starting it is `_start_detached`'s, and so
    is every way that can fail.
    """
    path = hit.path
    if not os.path.exists(path):
        return f"Cannot open — the file no longer exists:\n{path}"

    if hit.member:
        # No editor can open a name inside a zip, so it is extracted to a
        # read-only copy and that is what gets opened. The copy is a copy:
        # edits to it never reach the archive, which the button's tooltip says
        # and the file's permissions repeat.
        path, error = _temp_copy(hit, depth)
        if error:
            return error

    if os.path.splitext(path)[1].lower() in SYSTEM_OPEN_EXTENSIONS:
        command = SYSTEM_OPEN_COMMAND
        hint = (
            f"\n\nThis file type is opened with the system default "
            f"application, through '{SYSTEM_OPEN_COMMAND}'."
        )
    else:
        command = open_command()
        hint = "\n\nChange the Open command under Options ▸ Settings."

    try:
        argv = build_open_argv(command, path)
    except ValueError as exc:
        return (
            f"The Open command cannot be run as written:\n\n    {command}\n\n"
            f"{exc}{hint}"
        )

    return _start_detached(argv, f"'{os.path.basename(path)}'", hint)


def containing_folder(hit: Hit) -> str:
    """The folder to show for `hit`.

    For a hit inside an archive that is the folder holding the *archive*, not
    the temporary copy `open_in_editor` would have extracted: the copy lives
    under /tmp and a window onto that directory tells the user nothing, while
    the archive is the thing that is actually there to be found.

    Absolute, because a relative result would be read against the file
    manager's own working directory rather than Sonar's.
    """
    return os.path.dirname(os.path.abspath(hit.path))


def open_folder(hit: Hit) -> str | None:
    """Show the folder holding `hit` in the file manager. An error, or None.

    The companion to `open_in_editor`: the same gesture aimed at the folder
    instead of the file. There is no configured command for this one — a
    directory goes to `SYSTEM_OPEN_COMMAND`, which is what puts it in front of
    whatever file manager the desktop has registered (Nautilus, Dolphin, and
    so on) rather than in front of a second thing the user has to configure.

    An error is returned rather than raised for the same reason it is in
    `open_in_editor`: this runs in a button handler, where a traceback would
    take the window down.
    """
    folder = containing_folder(hit)
    if not os.path.isdir(folder):
        return f"Cannot open — the folder no longer exists:\n{folder}"
    hint = (
        f"\n\nFolders are opened with the system's file manager, "
        f"through '{SYSTEM_OPEN_COMMAND}'."
    )
    return _start_detached([SYSTEM_OPEN_COMMAND, folder], f"'{folder}'", hint)
