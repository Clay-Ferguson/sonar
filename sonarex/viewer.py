"""Reading a file for the preview pane.

The pane is read-only plain text, so this only has to answer one question:
what should be shown for this path? Every answer is a string — a file that
can't be read produces a notice describing why, never an exception, since
this runs inside a selection-changed callback where a traceback would take
the window down.
"""

from __future__ import annotations

import os

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
