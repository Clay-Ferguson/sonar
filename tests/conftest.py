"""Shared fixtures: the archive tree every test searches, and a private config.

The tree is built here rather than checked in, because half of what it has to
contain cannot survive a git checkout intact — a deliberately truncated zip, a
file whose last line has no newline, a name with a glob metacharacter in it —
and the rest is only interesting for the bytes it holds, which are three lines
long. Building it takes about a tenth of a second and it is made once per
session.

Everything is generated with the standard library except the encrypted zip,
which needs the `zip` command (`zipfile` can read encryption but not write it)
and skips the tests that want it when that is missing.
"""

from __future__ import annotations

import gzip
import io
import os
import shutil
import subprocess
import sys
import tarfile
import zipfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6.QtWidgets import QMessageBox  # noqa: E402

from sonarex import config, viewer  # noqa: E402
from sonarex.window import MainWindow  # noqa: E402

# The word every fixture file contains and every search looks for.
NEEDLE = "needle"

# The staged files that go into both docs.zip and bundle.tar.gz, each one there
# for a case that has bitten this code: two members sharing a basename in
# different directories, a glob metacharacter in a name, CRLF, a missing final
# newline, a multi-byte character ahead of the match, and blank lines in the
# middle of the text.
MEMBERS = {
    "doc/one.txt": b"alpha needle here\nsecond needle line\n",
    "doc/sub/one.txt": b"nested needle deep\n",
    "doc/a[1].txt": b"bracket needle file\n",
    "doc/crlf.txt": b"crlf needle line\r\nsecond crlf needle\r\n",
    "doc/nonl.txt": b"no trailing newline needle",
    "doc/utf8.txt": "ééé needle after multibyte\n".encode(),
    "doc/blanks.txt": b"blank line follows\n\n\nneedle after blanks\n",
}


# How much of docs.zip `truncated.zip` keeps, and the one member that survives
# it. Both are pinned here rather than discovered in a test, because a corrupt
# archive yielding *something* is the surprising half of this behavior and the
# tests on either side of it should agree about what.
TRUNCATION = 120
TRUNCATED_SURVIVOR = "doc/one.txt"

# The newest mtime in the fixture tree; each later file is stamped a day older.
# An arbitrary fixed point, so the ordering a test asserts does not depend on
# how fast the machine wrote the files. 2020-01-01 UTC.
BASE_MTIME = 1577836800


def _minimal_pdf(text: str) -> bytes:
    """A one-page PDF holding `text`, as an uncompressed stream.

    Generated rather than copied off the system: a real PDF from
    /usr/share/doc is there on this machine and not on the next one, and the
    only thing these tests need from one is that `pdftotext` finds a word in
    it, which twenty lines of PDF syntax deliver exactly.
    """
    stream = f"BT /F1 24 Tf 72 700 Td ({text}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    start = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        start,
    )
    return bytes(out)


def _write_zip(path, members, compress=zipfile.ZIP_STORED):
    """A zip of `members`, stored rather than deflated by default.

    Stored on purpose: it is what makes `docs.zip` match a raw byte search with
    -z *off*, which is the behavior the "archives off" test pins down. Deflate
    it and that test starts passing for the wrong reason.
    """
    with zipfile.ZipFile(path, "w", compress) as archive:
        for name, data in members.items():
            archive.writestr(name, data)


@pytest.fixture(scope="session")
def tree(tmp_path_factory):
    """A directory of archives to search. Built once for the whole session."""
    root = tmp_path_factory.mktemp("tree")

    _write_zip(root / "docs.zip", MEMBERS)

    # The same members as a tarball, so every case is exercised against a
    # second container format and not only against zip.
    with tarfile.open(root / "bundle.tar.gz", "w:gz") as archive:
        for name, data in MEMBERS.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))

    # A plain compressed file: no member, but no more readable with open()
    # than one, and the case that used to show as "Binary file".
    (root / "notes.txt.gz").write_bytes(
        gzip.compress(b"gzipped needle content\nsecond gz needle\n")
    )
    (root / "loose.txt").write_bytes(b"loose needle on disk\n")

    # Corrupt: the first 120 bytes of a real zip. ugrep reports it on stderr
    # and carries on, which is what the "no dialog" test checks. It is not
    # empty, though — 120 bytes is enough to hold the first stored member
    # whole, so that one member is still readable. See TRUNCATED_SURVIVOR.
    (root / "truncated.zip").write_bytes((root / "docs.zip").read_bytes()[:TRUNCATION])

    if shutil.which("zip"):
        staging = root / ".staging"
        staging.mkdir()
        (staging / "sec.txt").write_bytes(b"secret needle\n")
        subprocess.run(
            ["zip", "-q", "-P", "hunter2", str(root / "locked.zip"), "sec.txt"],
            cwd=staging,
            check=True,
        )
        shutil.rmtree(staging)

    # Distinct, decreasing mtimes. Without this the two containers are written
    # within the same filesystem timestamp tick on a fast disk, which makes
    # them one sort key and interleaves their members — the results are still
    # correct, but "an archive's members stay together" stops being a thing a
    # test can assert. Spaced a day apart so the order is unambiguous, newest
    # first: docs.zip, bundle.tar.gz, then the rest.
    for age, name in enumerate(
        ["docs.zip", "bundle.tar.gz", "notes.txt.gz", "loose.txt",
         "truncated.zip", "locked.zip"]
    ):
        target = root / name
        if target.exists():
            stamp = BASE_MTIME - age * 86400
            os.utime(target, (stamp, stamp))

    return str(root)


@pytest.fixture(scope="session")
def nested_tree(tmp_path_factory):
    """One archive inside another inside a third, for the --zmax tests.

    The directory holds *only* the outermost archive. The intermediate ones
    are built in a staging directory and removed, because a search finds them
    too and a result list with every staging copy in it is unreadable.
    """
    root = tmp_path_factory.mktemp("nested")
    staging = tmp_path_factory.mktemp("nested-staging")

    _write_zip(staging / "L3.zip", {"inner.txt": b"level three needle here\nsecond needle line\n"})
    with tarfile.open(staging / "L2.tar.gz", "w:gz") as archive:
        archive.add(staging / "L3.zip", arcname="L3.zip")
    with zipfile.ZipFile(root / "L1.zip", "w") as archive:
        archive.write(staging / "L2.tar.gz", arcname="L2.tar.gz")
        archive.writestr("top.txt", b"plain needle at level one\n")

    return str(root)


@pytest.fixture
def guarded_tree(tmp_path):
    """A tree with a matching file and a directory nothing may open.

    This is how a search is made to exit 2 *without* anything actually being
    wrong, deterministically and on any machine. The encrypted archive does it
    too on some ugrep builds and not on others, which is precisely the
    inconsistency that made the app raise a dialog on one machine and not the
    next; permissions do it everywhere.
    """
    (tmp_path / "found.txt").write_bytes(b"needle here\n")
    blocked = tmp_path / "blocked"
    blocked.mkdir()
    (blocked / "secret.txt").write_bytes(b"needle\n")
    blocked.chmod(0o000)
    yield str(tmp_path)
    blocked.chmod(0o755)  # or the temp directory cannot be cleaned up


@pytest.fixture(scope="session")
def colon_tree(tmp_path_factory):
    """A zip holding a member with a colon in its name.

    A colon is what ugrep puts *between* nesting levels, so a file honestly
    called this is the case that tells `member_levels` apart from a chain.
    """
    root = tmp_path_factory.mktemp("colon")
    _write_zip(root / "odd.zip", {"notes:draft.txt": b"colon needle here\n"})
    return str(root)


# Enough filler around the zipped member to make deflate actually smaller than
# the input. It matters: a small member is *stored* even when deflate is asked
# for, and stored bytes match a raw byte search with -z off — which would put
# the archive into the plain-file result sets these tests pin exactly. It
# contains no "c", so it cannot itself be an approximate hit for "color".
FUZZY_PADDING = "padding line so this file will deflate\n" * 40


@pytest.fixture(scope="session")
def fuzzy_tree(tmp_path_factory):
    """Four spellings of one word, at known edit distances from "color".

    The distances are the whole point, so they are spelled out rather than
    left to be counted: `colour` is one edit away (an inserted u), `collour`
    is two (an inserted l as well). A search for `color` therefore returns a
    different, exactly known set at every setting, which is what lets these
    tests assert on the set rather than on "more rows than before".

    `exact.txt` holding `color` is also what makes the first-character rule
    testable: `dolor` is one edit from it too, and must still never match.
    """
    root = tmp_path_factory.mktemp("fuzzy")
    (root / "exact.txt").write_bytes(b"the color of the sky\n")
    (root / "near.txt").write_bytes(b"the colour of the sea\n")
    (root / "far.txt").write_bytes(b"a collour of paint\n")
    _write_zip(
        root / "shades.zip",
        {"inner/tint.txt": (FUZZY_PADDING + "a colour swatch inside\n").encode()},
        compress=zipfile.ZIP_DEFLATED,
    )
    return str(root)


@pytest.fixture(scope="session")
def pdf_tree(tmp_path_factory):
    """A PDF loose on disk and the same PDF inside a zip.

    ugrep's pdftotext filter reaches into archives, so the zipped one is a
    real search hit that the preview then has to decline to render.
    """
    root = tmp_path_factory.mktemp("pdfs")
    pdf = _minimal_pdf("needle inside a pdf")
    (root / "loose.pdf").write_bytes(pdf)
    _write_zip(root / "withpdf.zip", {"doc.pdf": pdf})
    return str(root)


@pytest.fixture
def conf(tmp_path):
    """A config file of this test's own, with archives on at `depth`.

    `config.CONFIG_PATH` is read at call time rather than cached, so rebinding
    the module attribute is the whole of what it takes to keep every test off
    the real ~/.config. Returns a function so a test can re-save mid-run.
    """
    original = config.CONFIG_PATH
    config.CONFIG_PATH = str(tmp_path / "sonarex-config.yaml")

    def write(
        archives=True,
        depth=1,
        included=(),
        excluded=(),
        open_command="/bin/true",
        fuzzy=0,
    ):
        config.save_settings(
            config.Settings(
                list(included), list(excluded), archives, depth, open_command, fuzzy
            )
        )
        return config.CONFIG_PATH

    write()
    yield write
    config.CONFIG_PATH = original


@pytest.fixture(autouse=True)
def dialogs(monkeypatch):
    """Catch every QMessageBox instead of showing it, and report what was said.

    Autouse and not optional: under QT_QPA_PLATFORM=offscreen a QMessageBox
    still blocks waiting for a click that can never come, so one raised by a
    path under test hangs the whole run rather than failing it. Anything that
    would have been shown lands in this list, which is also the only way to
    assert that a problem *was* reported.
    """
    shown = []

    def capture(_parent, title, message, *args, **kwargs):
        shown.append((title, message))
        return QMessageBox.StandardButton.Ok

    monkeypatch.setattr(QMessageBox, "warning", staticmethod(capture))
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(capture))
    monkeypatch.setattr(QMessageBox, "information", staticmethod(capture))
    return shown


@pytest.fixture(autouse=True)
def _clean_temp_copies():
    """Remove any extracted copy an Open left behind.

    `viewer` keeps the session's temp directory in a module global, so without
    this a test that opens an archive member leaks it into the next one — and
    the count-the-copies assertions would see the wrong number.
    """
    yield
    viewer.cleanup_temp_files()


@pytest.fixture
def search(qtbot):
    """Open a window on `folder`, run `query`, and wait for ugrep to finish.

    `qtbot.waitSignal` is what replaces the hand-rolled QEventLoop this suite
    used to spin: it blocks until `finished` arrives or the timeout expires,
    and fails the test rather than hanging. `addWidget` hands the window to
    pytest-qt to close when the test ends.
    """

    def run(folder, query):
        window = MainWindow(folder)
        qtbot.addWidget(window)
        window.query_edit.setText(query)
        window.folder_edit.setText(folder)
        with qtbot.waitSignal(window._runner.finished, timeout=30000):
            window.start_search()
        return window

    return run


needs_permissions = pytest.mark.skipif(
    os.geteuid() == 0, reason="root reads an unreadable directory anyway"
)
needs_zip = pytest.mark.skipif(
    shutil.which("zip") is None, reason="the `zip` command is needed to build an encrypted archive"
)
needs_pdftotext = pytest.mark.skipif(
    shutil.which("pdftotext") is None, reason="pdftotext is needed to search inside a PDF"
)
