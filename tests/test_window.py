"""The window, driven for real: what a search lists and what a row previews.

These run a genuine ugrep over a genuine tree of archives, so they are closer
to integration tests than unit tests. That is deliberate — nearly every bug
this feature had lived in what ugrep actually does, not in what a mock of it
would have been told to do.
"""

from __future__ import annotations

import os

import pytest

from helpers import highlighted, labels, nav, select
from sonarex import viewer
from sonarex.archive import Hit
from sonarex.search import build_argv
from sonarex.viewer import read_for_preview
from sonarex.window import HIT_ROLE, OPEN_TIP, OPEN_TIP_ARCHIVED

from conftest import (
    MEMBERS,
    TRUNCATED_SURVIVOR,
    needs_pdftotext,
    needs_permissions,
    needs_zip,
)

# What a search of the fixture tree finds with archives on: every member of
# both containers, the two files that are not in one, and the single member
# that survived truncating the third. The encrypted archive contributes
# nothing at all, which is the point of it.
ARCHIVED_ROWS = sorted(
    ["loose.txt", "notes.txt.gz", f"truncated.zip → {TRUNCATED_SURVIVOR}"]
    + [
        f"{container} → {member}"
        for container in ("docs.zip", "bundle.tar.gz")
        for member in MEMBERS
    ]
)


# -- the setting off -------------------------------------------------------


def test_argv_is_unchanged_when_archives_are_off(conf):
    """The regression guard for every existing user: with the setting off, the
    command line is byte-for-byte the one this app always built."""
    conf(archives=False)
    assert build_argv("q", "/f") == [
        "ugrep", "--line-buffered", "-r", "-i", "-l", "-%", "--files",
        "--filter=pdf:pdftotext -q % -", "--", "q", "/f",
    ]


def test_argv_carries_the_flags_when_on(conf):
    conf(archives=True, depth=2)
    assert build_argv("q", "/f")[8:12] == [
        "-z", "--zmax=2", "--separator=\t", "--format=%f%s%z%~",
    ]


def test_a_zip_is_one_opaque_row_when_off(conf, tree, search):
    """The fixture's entries are *stored*, so ugrep matches its raw bytes even
    without -z. That has always happened; what matters is that it is one
    binary row rather than seven member rows."""
    conf(archives=False)
    window = search(tree, "needle")
    # truncated.zip is a prefix of docs.zip, so its stored bytes match too.
    assert sorted(labels(window)) == ["docs.zip", "loose.txt", "truncated.zip"]

    select(window, "docs.zip")
    assert window.preview.toPlainText() == "Binary file — cannot preview."
    assert highlighted(window) == []
    assert nav(window) == (False, "")


# -- the setting on --------------------------------------------------------


def test_members_are_listed(conf, tree, search):
    conf(archives=True)
    assert sorted(labels(search(tree, "needle"))) == ARCHIVED_ROWS


@needs_zip
def test_unreadable_archives_are_skipped_in_silence(conf, tree, search):
    """ugrep writes `cannot decompress` to stderr and leaves the exit code at
    0, so an encrypted or corrupt archive never reaches the error dialog."""
    conf(archives=True)
    window = search(tree, "needle")
    assert not any("locked" in row for row in labels(window))
    # The title is a result count, which is what says no dialog was raised.
    assert "files in" in window.windowTitle()


def test_a_row_carries_its_hit_and_a_two_line_tooltip(conf, tree, search):
    conf(archives=True)
    window = search(tree, "needle")
    item = select(window, "docs.zip → doc/one.txt")
    assert item.data(HIT_ROLE) == Hit(f"{tree}/docs.zip", "doc/one.txt")
    assert item.toolTip() == f"{tree}/docs.zip\n  doc/one.txt"


@pytest.mark.parametrize(
    "member, text, marks",
    [
        ("doc/one.txt", "alpha needle here\nsecond needle line\n", ["needle", "needle"]),
        ("doc/sub/one.txt", "nested needle deep\n", ["needle"]),
        ("doc/a[1].txt", "bracket needle file\n", ["needle"]),
        ("doc/crlf.txt", None, ["needle", "needle"]),
        ("doc/utf8.txt", None, ["needle"]),
        ("doc/blanks.txt", "blank line follows\n\n\nneedle after blanks\n", ["needle"]),
    ],
)
def test_a_member_previews_and_highlights(conf, tree, search, member, text, marks):
    conf(archives=True)
    window = search(tree, "needle")
    select(window, f"docs.zip → {member}")
    if text is not None:
        assert window.preview.toPlainText() == text
    assert highlighted(window) == marks


def test_a_plain_compressed_file_previews_as_text(conf, tree, search):
    """This used to read "Binary file"; it has no member but still needs
    decompressing before there is anything to show."""
    conf(archives=True)
    window = search(tree, "needle")
    select(window, "notes.txt.gz")
    assert window.preview.toPlainText() == "gzipped needle content\nsecond gz needle\n"
    assert highlighted(window) == ["needle", "needle"]


def test_a_tarball_member_previews(conf, tree, search):
    conf(archives=True)
    window = search(tree, "needle")
    select(window, "bundle.tar.gz → doc/one.txt")
    assert window.preview.toPlainText() == MEMBERS["doc/one.txt"].decode()


# -- Prev/Next -------------------------------------------------------------


def test_stepping_through_a_member(conf, tree, search):
    conf(archives=True)
    window = search(tree, "needle")
    select(window, "docs.zip → doc/one.txt")
    assert nav(window) == (True, "1 of 2")

    window._step_match(1)
    assert window.match_label.text() == "2 of 2"
    window._step_match(1)
    assert window.match_label.text() == "1 of 2"  # wraps forward
    window._step_match(-1)
    assert window.match_label.text() == "2 of 2"  # and back

    # Exactly one match is the hot one at any time.
    assert len(highlighted(window, current_only=True)) == 1


def test_switching_rows_restarts_the_count(conf, tree, search):
    conf(archives=True)
    window = search(tree, "needle")
    select(window, "docs.zip → doc/one.txt")
    window._step_match(1)
    select(window, "docs.zip → doc/a[1].txt")
    assert window.match_label.text() == "1 of 1"


def test_a_fresh_search_leaves_the_nav_dim(conf, tree, search):
    conf(archives=True)
    window = search(tree, "zzzznothingzzz")
    assert window.windowTitle().endswith("No matches")
    assert nav(window) == (False, "")


# -- ordering --------------------------------------------------------------


def test_results_are_newest_first_with_members_grouped(conf, tree, search):
    """Sorted by mtime alone, so every member of one archive shares a key and
    `sort`'s stability keeps them in the order ugrep found them.

    The fixture stamps the archives a day apart, which is what makes this
    assertable: written back to back they land in one filesystem tick, become
    one sort key, and interleave — still correct, but nothing a test can pin.
    """
    conf(archives=True)
    rows = labels(search(tree, "needle"))

    # The containers appear in mtime order, newest first, with no other
    # container's rows in between.
    order = []
    for row in rows:
        container = row.split(" → ")[0]
        if container not in order:
            order.append(container)
    assert order == ["docs.zip", "bundle.tar.gz", "notes.txt.gz", "loose.txt",
                     "truncated.zip"]


# -- a search that ran, but complained ------------------------------------


@needs_permissions
def test_a_skipped_file_is_not_an_error_dialog(conf, guarded_tree, search, dialogs):
    """ugrep exits 2 for a directory it could not open, having searched
    everything else. That is a report about one file, not a failed search, and
    it must not reach the user as a modal — which it did, on any build whose
    exit status says 2 for an encrypted archive.
    """
    conf(archives=True)
    window = search(guarded_tree, "needle")

    assert dialogs == []
    assert labels(window) == ["found.txt"]
    assert "1 file in" in window.windowTitle()


@needs_permissions
def test_a_fruitless_search_that_complained_says_no_matches(
    conf, guarded_tree, search, dialogs
):
    """Same exit 2, no results. "No matches" is decided by the count rather
    than by EXIT_NO_MATCH, precisely so this does not become an error."""
    conf(archives=True)
    window = search(guarded_tree, "zzzznothingzzz")

    assert dialogs == []
    assert window.windowTitle().endswith("No matches")
    assert nav(window) == (False, "")


@needs_zip
def test_an_encrypted_archive_never_raises_a_dialog(conf, tree, search, dialogs):
    """Pinned by feeding the window the status rather than by trusting ugrep.

    Whether an encrypted archive sets the exit status to 2 or leaves it at 0 is
    a property of the *build*: 7.5.0 here leaves it at 0, and the build this
    bug was reported from returns 2 for the same tree. Injecting the status
    covers both, so this cannot pass on one machine and fail on the next —
    which is exactly how it got missed.
    """
    conf(archives=True)
    window = search(tree, "needle")
    found = len(labels(window))
    dialogs.clear()

    window._on_search_finished(
        2, "ugrep: cannot decompress /t/locked.zip: zip data is encrypted\n"
    )
    assert dialogs == []
    assert f"{found} files in" in window.windowTitle()


def test_an_unreadable_archive_and_no_matches_says_no_matches(conf, tree, search, dialogs):
    """The same injected status with an empty list. "No matches" comes from the
    count, not from EXIT_NO_MATCH, so a status of 2 does not turn a fruitless
    search into an error."""
    conf(archives=True)
    window = search(tree, "zzzznothingzzz")
    dialogs.clear()

    window._on_search_finished(
        2, "ugrep: cannot decompress /t/locked.zip: zip data is encrypted\n"
    )
    assert dialogs == []
    assert window.windowTitle().endswith("No matches")


def test_an_unexplained_failure_is_still_reported(conf, tree, search, dialogs):
    """Only silence a bad status when ugrep said why and every reason was a
    file it skipped. Nothing said at all is still a failure."""
    conf(archives=True)
    window = search(tree, "needle")
    dialogs.clear()

    window._on_search_finished(2, "")
    assert len(dialogs) == 1
    assert "status 2" in dialogs[0][1]


@needs_permissions
def test_a_real_error_still_reaches_the_user(conf, guarded_tree, search, dialogs):
    """The filter keeps what it does not recognise, so a bad regex is still
    reported even when a skipped-file warning is on stderr beside it."""
    conf(archives=True)
    window = search(guarded_tree, "col(o|ou")

    assert len(dialogs) == 1
    assert "error" in dialogs[0][1]
    assert window.windowTitle() == "Sonar"


# -- Open ------------------------------------------------------------------


def test_open_extracts_a_read_only_copy(conf, tree, search):
    conf(archives=True)
    window = search(tree, "needle")
    item = select(window, "docs.zip → doc/one.txt")

    assert viewer.open_in_editor(item.data(HIT_ROLE), window._search_depth) is None

    copies = [
        os.path.join(root, name)
        for root, _dirs, names in os.walk(viewer._temp_root)
        for name in names
    ]
    assert len(copies) == 1
    # The basename is kept: it is what tells the editor which language it is
    # looking at.
    assert os.path.basename(copies[0]) == "one.txt"
    assert open(copies[0], "rb").read() == MEMBERS["doc/one.txt"]
    assert oct(os.stat(copies[0]).st_mode & 0o777) == "0o444"


def test_closing_removes_the_copies(conf, tree, search):
    conf(archives=True)
    window = search(tree, "needle")
    item = select(window, "docs.zip → doc/one.txt")
    viewer.open_in_editor(item.data(HIT_ROLE), window._search_depth)
    assert viewer._temp_root is not None

    window.close()
    assert viewer._temp_root is None


@needs_zip
def test_open_declines_an_unreadable_member(tree):
    error = viewer.open_in_editor(Hit(f"{tree}/locked.zip", "sec.txt"), 1)
    assert error.startswith("Cannot read 'sec.txt' out of the archive")


def test_the_open_tooltip_follows_the_selection(conf, tree, search):
    conf(archives=True)
    window = search(tree, "needle")
    select(window, "docs.zip → doc/one.txt")
    assert window.open_button.toolTip() == OPEN_TIP_ARCHIVED
    select(window, "loose.txt")
    assert window.open_button.toolTip() == OPEN_TIP


# -- notices ---------------------------------------------------------------


@needs_zip
def test_an_encrypted_member_is_a_notice(tree):
    text, is_notice = read_for_preview(Hit(f"{tree}/locked.zip", "sec.txt"), 1)
    assert is_notice
    assert text.startswith("Cannot read this file out of the archive")


def test_an_over_cap_member_is_a_notice(tmp_path):
    import zipfile

    archive = tmp_path / "big.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("big.txt", "needle padding line\n" * 200_000)

    text, is_notice = read_for_preview(Hit(str(archive), "big.txt"), 1)
    assert is_notice
    assert text.startswith("File is too large to preview")


# -- PDFs ------------------------------------------------------------------


@needs_pdftotext
def test_a_pdf_inside_an_archive_is_found_but_not_rendered(conf, pdf_tree, search):
    """ugrep's pdftotext filter reaches into archives, so this is a real hit —
    but `PdfPane` loads a path and there is no path to a name inside a zip."""
    conf(archives=True)
    window = search(pdf_tree, "needle")
    assert "withpdf.zip → doc.pdf" in labels(window)

    select(window, "withpdf.zip → doc.pdf")
    assert window.preview.toPlainText().startswith("PDFs inside archives cannot be previewed.")
    assert window._pdf_showing is False
    assert window._panes.currentWidget() is window.preview
    assert nav(window) == (False, "")


@needs_pdftotext
def test_open_declines_a_pdf_member(pdf_tree):
    """Declined by extension, not by sniffing for a NUL byte.

    This fixture's PDF has an uncompressed text stream and contains no NUL at
    all, so the binary sniff alone lets it through and the editor gets a
    mangled copy. The preview never had this problem because it checks
    `is_pdf` before it extracts anything.
    """
    error = viewer.open_in_editor(Hit(f"{pdf_tree}/withpdf.zip", "doc.pdf"), 1)
    assert error.startswith("'doc.pdf' is not a text file")


def test_open_declines_a_binary_member(tmp_path):
    """And the NUL sniff still catches everything that is not a PDF."""
    import zipfile

    archive = tmp_path / "bin.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("blob.dat", b"needle\x00\x01\x02 binary payload")

    error = viewer.open_in_editor(Hit(str(archive), "blob.dat"), 1)
    assert error.startswith("'blob.dat' is not a text file")


@needs_pdftotext
def test_a_loose_pdf_still_uses_the_pdf_pane(conf, pdf_tree, search, qtbot):
    conf(archives=True)
    window = search(pdf_tree, "needle")
    select(window, "loose.pdf")
    assert window._pdf_showing is True
    assert window._panes.currentWidget() is window._pdf
    # The search model fills in lazily, so the count climbs after the load.
    qtbot.waitUntil(lambda: window._pdf.count() > 0, timeout=5000)


# -- repeated searches -----------------------------------------------------


def test_repeated_searches_do_not_interleave(conf, tree, search, qtbot):
    """`SearchRunner.stop()` disconnects before killing, so a superseded
    process cannot deliver a late result into the search that replaced it."""
    conf(archives=True)
    window = search(tree, "needle")
    for _ in range(4):
        window.start_search()
    with qtbot.waitSignal(window._runner.finished, timeout=30000):
        window.start_search()

    rows = labels(window)
    assert len(rows) == len(set(rows))
    assert sorted(rows) == ARCHIVED_ROWS
