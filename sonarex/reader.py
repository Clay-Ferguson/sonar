"""Reading a result for the preview pane: its text, or why there is none.

`read_for_preview` answers what the read-only pane should display. Every
answer is a string — a file that can't be read produces a notice describing
why, never an exception, since it runs inside a selection-changed callback
where a traceback would take the window down.

It takes a `Hit` rather than a path, because with Search Archives on a result
can name a file inside a zip, which no `open()` can reach; those are read back
out through `archive.extract`. A name search can also list a *folder*, which
the preview names rather than reads.
"""

from __future__ import annotations

import os

from . import archive
from .archive import Hit

# Beyond this, the file is described rather than shown. The pane holds plain
# text, and loading tens of megabytes into it stalls the GUI thread laying
# out a document nobody is going to read top to bottom anyway.
MAX_PREVIEW_BYTES = 2 * 1024 * 1024

# The one extension the app treats specially, named once: the preview pane
# renders these itself (see `pdfview.py`) and Open sends them to the system
# rather than to the configured editor. Two behaviors, one answer to "is this
# a PDF".
PDF_SUFFIX = ".pdf"

# What the preview pane says for a folder row, which only a name search yields.
# There is nothing to read, so it says what Open will do instead.
FOLDER_NOTICE = "Folder — press Open to show it in the file manager."


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
    # Only a name search lists folders. Without this one falls through to
    # open(), which fails with IsADirectoryError and reads as a broken file.
    if not hit.member and os.path.isdir(path):
        return (FOLDER_NOTICE, True)
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
                return ("Binary file — cannot preview.", True)
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
