"""Handing a result to another program: the editor, or the file manager.

`open_hit` is the Open button. It hands the file to a real editor, for when
reading it in the pane isn't enough. Which editor is a config key
(`open.command`), read at the moment of the click, so changing it in the
settings dialog takes effect on the next Open rather than the next run. PDFs
bypass that key and go to the desktop's default application instead, and a
folder row from a name search goes to the file manager.

`open_folder` is the same handoff aimed one level up — the folder the file
sits in, given to the desktop's file manager.

A hit inside an archive cannot be handed to an editor at all, so Open first
extracts it to a read-only temporary copy. `TempCopies` owns those copies for
a session; the window keeps one and empties it when it closes. `open_folder`
needs none: the folder it wants is the one holding the archive.

Everything here returns an error message rather than raising, because it runs
in a button handler, and every spawn is an argv list — never a shell, since
the command comes from a text field.
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
from .reader import PDF_SUFFIX, SNIFF_BYTES, is_pdf

# Where the selected file goes in a configured command, if the user says.
# Without it the path is appended, which is what almost every editor wants;
# with it, the path can sit in the middle — `gnome-terminal -- vim %s`.
PATH_PLACEHOLDER = "%s"

# The same ceiling for a member extracted for Open. Higher, because an editor
# can handle a file the preview pane cannot — but not unbounded, since the
# extraction is buffered in memory before it is written to the temp copy.
MAX_ARCHIVE_OPEN_BYTES = 64 * 1024 * 1024

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

class TempCopies:
    """Read-only copies of archive members, extracted for Open.

    One directory per session, created on the first Open of a member and
    removed by `cleanup` when the window closes, with a numbered
    sub-directory per file inside it: two members can share a basename, and
    the basename has to be kept — it is what tells the editor which language
    it is looking at.

    An object the window owns rather than module state, so a test (or a
    second window) gets its own set and cannot see another's.
    """

    def __init__(self) -> None:
        # None until the first copy is made; `cleanup` puts it back.
        self.root: str | None = None
        self._count = 0

    def extract(self, hit: Hit, depth: int) -> tuple[str | None, str | None]:
        """Extract `hit` to a file on disk. Returns (path, error); one is None.

        The copy is made read-only, which is the closest this can come to
        being honest: nothing written to it goes back into the archive, and an
        editor that says "read-only" in its title bar says so before the user
        has typed anything rather than after.
        """
        name = member_name(hit.member, depth)
        data = archive.extract(hit, MAX_ARCHIVE_OPEN_BYTES, depth)
        if data is None:
            return (
                None,
                f"Cannot read '{name}' out of the archive:\n\n"
                f"{hit.path}\n\nIt may be encrypted, corrupt, or in a format ugrep "
                "cannot decompress.",
            )
        # `is_pdf` first, and by name rather than by sniffing, for the same
        # reason the preview checks it before extracting at all: ugrep's
        # extraction is line-based, so a PDF comes back mangled whether or not
        # it happens to hold a NUL byte — and one whose streams are
        # uncompressed holds none. The NUL sniff catches everything else.
        if is_pdf(name) or b"\x00" in data[:SNIFF_BYTES]:
            # What comes back is text or it is nothing worth writing: handing
            # an editor a mangled PDF would be worse than saying no.
            return (
                None,
                f"'{name}' is not a text file, and Sonar "
                "can only extract text out of an archive.\n\nOpen the archive "
                "itself to get at it.",
            )

        try:
            if self.root is None:
                self.root = tempfile.mkdtemp(prefix="sonar-")
            self._count += 1
            folder = os.path.join(self.root, str(self._count))
            os.mkdir(folder)
            # The name at the bottom of the chain, not the chain: a temp file
            # called `L2.tar.gz:L3.zip:inner.txt` tells the editor it is
            # looking at a tarball, and the extension is the whole point of
            # keeping the name.
            path = os.path.join(folder, name)
            with open(path, "wb") as handle:
                handle.write(data)
            os.chmod(path, 0o444)
        except OSError as exc:
            return (None, f"Could not write a temporary copy to open:\n\n{exc}")
        return (path, None)

    def cleanup(self) -> None:
        """Remove every extracted copy. Called when the window closes."""
        if self.root is None:
            return
        shutil.rmtree(self.root, ignore_errors=True)
        self.root = None

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


def open_hit(hit: Hit, depth: int, copies: TempCopies) -> str | None:
    """Open `hit` with the configured command. An error message, or None.

    A hit inside an archive is extracted to a read-only temporary copy in
    `copies` first, and that copy is what opens — see `TempCopies.extract`. Everything below is then
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

    # A folder, from a name search: no editor is the right tool, and the file
    # manager the folder button would open is.
    if not hit.member and os.path.isdir(path):
        return _show_directory(path)

    if hit.member:
        # No editor can open a name inside a zip, so it is extracted to a
        # read-only copy and that is what gets opened. The copy is a copy:
        # edits to it never reach the archive, which the button's tooltip says
        # and the file's permissions repeat.
        copy, error = copies.extract(hit, depth)
        if copy is None:
            return error
        path = copy

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
    the temporary copy `open_hit` would have extracted: the copy lives
    under /tmp and a window onto that directory tells the user nothing, while
    the archive is the thing that is actually there to be found.

    Absolute, because a relative result would be read against the file
    manager's own working directory rather than Sonar's.
    """
    return os.path.dirname(os.path.abspath(hit.path))


def open_folder(hit: Hit) -> str | None:
    """Show the folder holding `hit` in the file manager. An error, or None.

    The companion to `open_hit`: the same gesture aimed at the folder
    instead of the file. There is no configured command for this one — a
    directory goes to `SYSTEM_OPEN_COMMAND`, which is what puts it in front of
    whatever file manager the desktop has registered (Nautilus, Dolphin, and
    so on) rather than in front of a second thing the user has to configure.

    An error is returned rather than raised for the same reason it is in
    `open_hit`: this runs in a button handler, where a traceback would
    take the window down.
    """
    folder = containing_folder(hit)
    if not os.path.isdir(folder):
        return f"Cannot open — the folder no longer exists:\n{folder}"
    return _show_directory(folder)


def _show_directory(folder: str) -> str | None:
    """Hand `folder` to the desktop's file manager. An error, or None.

    Shared by the folder button and by Open on a folder row, so both reach the
    same program: `SYSTEM_OPEN_COMMAND`, whatever the desktop has registered
    for a directory — never a file manager named here.
    """
    hint = (
        f"\n\nFolders are opened with the system's file manager, "
        f"through '{SYSTEM_OPEN_COMMAND}'."
    )
    return _start_detached([SYSTEM_OPEN_COMMAND, folder], f"'{folder}'", hint)
