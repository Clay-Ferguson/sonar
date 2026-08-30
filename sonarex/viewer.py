"""What SonarEx does with the file the user picked: show it, or open it.

`read_for_preview` answers what the read-only pane should display. Every
answer is a string — a file that can't be read produces a notice describing
why, never an exception, since it runs inside a selection-changed callback
where a traceback would take the window down.

`open_in_editor` hands the file to a real editor, for when reading it here
isn't enough.
"""

from __future__ import annotations

import os
import shutil
import subprocess

# The editor the Open button launches. Carried over unchanged from the
# Nautilus version, which spawned exactly this. Slated to become a config
# key — when it does, this becomes the default rather than the only value,
# which is why callers go through `open_in_editor` rather than reading it.
EDITOR_COMMAND = "/usr/bin/code"

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


def open_in_editor(path: str) -> str | None:
    """Open `path` in the editor. Returns an error message, or None on success.

    An error is returned rather than raised so the caller can put it in the
    status line: failing to open a file is worth saying, but not worth an
    exception out of a button handler.

    The editor is checked on PATH first, so a missing one is reported as the
    missing program it is instead of a bare OSError from the spawn.

    Spawned with `start_new_session=True` and its streams discarded, so the
    editor is not a child that dies with SonarEx and cannot stall the GUI by
    filling a pipe nobody reads.
    """
    if not os.path.exists(path):
        return f"Cannot open — the file no longer exists:\n{path}"

    program = EDITOR_COMMAND
    if not os.path.isabs(program):
        resolved = shutil.which(program)
        if resolved is None:
            return f"Cannot open '{os.path.basename(path)}': '{program}' is not on PATH."
        program = resolved
    elif not os.path.exists(program):
        return (
            f"Cannot open '{os.path.basename(path)}': {program} is not installed.\n"
            "Install VS Code, or point EDITOR_COMMAND at another editor."
        )

    try:
        subprocess.Popen(
            [program, path],
            env=_child_env(),
            start_new_session=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError as exc:
        return f"Could not open '{os.path.basename(path)}':\n{exc}"
    return None
