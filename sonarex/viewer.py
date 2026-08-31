"""What SonarEx does with the file the user picked: show it, or open it.

`read_for_preview` answers what the read-only pane should display. Every
answer is a string — a file that can't be read produces a notice describing
why, never an exception, since it runs inside a selection-changed callback
where a traceback would take the window down.

`open_in_editor` hands the file to a real editor, for when reading it here
isn't enough. Which editor is a config key (`open.command`), read at the
moment of the click, so changing it in the settings dialog takes effect on
the next Open rather than the next run.
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess

from .config import open_command

# Where the selected file goes in a configured command, if the user says.
# Without it the path is appended, which is what almost every editor wants;
# with it, the path can sit in the middle — `gnome-terminal -- vim %s`.
PATH_PLACEHOLDER = "%s"

# Beyond this, the file is described rather than shown. The pane holds plain
# text, and loading tens of megabytes into it stalls the GUI thread laying
# out a document nobody is going to read top to bottom anyway.
MAX_PREVIEW_BYTES = 2 * 1024 * 1024

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


def read_for_preview(path: str) -> tuple[str, bool]:
    """The text to show for `path`, and whether it is a notice rather than content.

    The caller uses the flag only to style the pane; both cases are just text.

    Binary files — PDFs among them — are named as such rather than shown.
    SonarEx searches inside PDFs (ugrep extracts their text through a filter),
    so a PDF legitimately appears in the results list; it just has nothing
    useful to display here.
    """
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
                    f"Binary file — cannot preview.\n\n{path}\n\n{_human_size(size)}",
                    True,
                )
            if size > MAX_PREVIEW_BYTES:
                return (
                    f"File is too large to preview "
                    f"({_human_size(size)}; the limit is {_human_size(MAX_PREVIEW_BYTES)}).\n\n"
                    f"{path}",
                    True,
                )
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


def _child_env() -> dict[str, str]:
    """Our environment, minus SonarEx's own virtualenv.

    start.sh runs the app through `uv run`, which puts .venv/bin on PATH and
    sets VIRTUAL_ENV. Left in place those are inherited by the editor, so
    VS Code would offer SonarEx's interpreter as the Python environment for
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


def open_in_editor(path: str) -> str | None:
    """Open `path` with the configured command. An error message, or None.

    An error is returned rather than raised so the caller can show it: failing
    to open a file is worth saying, but not worth an exception out of a button
    handler. Every way this can go wrong — a command that will not parse, a
    program that is not installed, a spawn that fails — comes back as a
    string naming the command, since the command is now something the user
    typed and can go back and fix.

    The program is checked on PATH first, so a missing one is reported as the
    missing program it is instead of a bare OSError from the spawn.

    Spawned with `start_new_session=True` and its streams discarded, so the
    editor is not a child that dies with SonarEx and cannot stall the GUI by
    filling a pipe nobody reads.
    """
    if not os.path.exists(path):
        return f"Cannot open — the file no longer exists:\n{path}"

    command = open_command()
    try:
        argv = build_open_argv(command, path)
    except ValueError as exc:
        return (
            f"The Open command cannot be run as written:\n\n    {command}\n\n"
            f"{exc}\n\nFix it with the gear button."
        )

    program = argv[0]
    if not os.path.isabs(program):
        resolved = shutil.which(program)
        if resolved is None:
            return (
                f"Cannot open '{os.path.basename(path)}': "
                f"'{program}' is not on PATH.\n\n"
                "Change the Open command with the gear button."
            )
        argv[0] = resolved
    elif not os.path.exists(program):
        return (
            f"Cannot open '{os.path.basename(path)}': {program} is not installed.\n\n"
            "Change the Open command with the gear button."
        )

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
        return f"Could not open '{os.path.basename(path)}':\n{exc}"
    return None
