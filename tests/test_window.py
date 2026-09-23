"""The window, driven for real: what a search lists and what a row previews.

These run a genuine ugrep over a genuine tree of archives, so they are closer
to integration tests than unit tests. That is deliberate — nearly every bug
this feature had lived in what ugrep actually does, not in what a mock of it
would have been told to do.
"""

from __future__ import annotations

import io
import os
import tarfile
from dataclasses import replace

import pytest

from helpers import current_spec, highlighted, labels, nav, searching, select, status
from sonarex import search as search_module
from sonarex import viewer
from sonarex.archive import Hit
from sonarex.search import (
    ARCHIVE_MATCH_FORMAT,
    MATCH_FORMAT,
    PDF_FILTER,
    build_argv,
    build_match_argv,
)
from sonarex.preview import FOLDER_TIP, FOLDER_TIP_ARCHIVED, OPEN_TIP, OPEN_TIP_ARCHIVED
from sonarex.viewer import read_for_preview
from sonarex.window import HIT_ROLE, MainWindow

from conftest import (
    MEMBERS,
    NOOP_OPENER,
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
    command line is what this app always built, plus the `--stats` the status
    bar reads its "files searched" count out of. Nothing about the search
    itself changed — the flag adds a block of prose after the last hit, which
    `SearchRunner` drops rather than listing."""
    conf(archives=False)
    assert build_argv(current_spec()) == [
        "ugrep", "--line-buffered", "-r", "-i", "-l", "-%", "--files",
        "--filter=pdf:pdftotext -q % -", "--stats", "--", "q", "/f",
    ]


def test_argv_carries_the_flags_when_on(conf):
    conf(archives=True, depth=2)
    assert build_argv(current_spec())[8:12] == [
        "-z", "--zmax=2", "--separator=\t", "--format=%f%s%z%~",
    ]


def test_argv_carries_fuzzy_when_set(conf):
    conf(archives=False, fuzzy=2)
    assert "--fuzzy=2" in build_argv(current_spec())


def test_argv_has_no_fuzzy_flag_when_off(conf):
    """0 means the flag is absent, not `--fuzzy=0`: ugrep rejects that outright
    (`invalid argument -Z=0`, exit 2), exactly as it rejects `--zmax=0`."""
    conf(archives=False, fuzzy=0)
    assert not any(arg.startswith("--fuzzy") for arg in build_argv(current_spec()))


def test_a_zip_is_one_opaque_row_when_off(conf, tree, search):
    """The fixture's entries are *stored*, so ugrep matches its raw bytes even
    without -z. That has always happened; what matters is that it is one
    binary row rather than seven member rows."""
    conf(archives=False)
    window = search(tree, "needle")
    # truncated.zip is a prefix of docs.zip, so its stored bytes match too.
    assert sorted(labels(window)) == ["docs.zip", "loose.txt", "truncated.zip"]

    select(window, "docs.zip")
    assert window.panel.text.toPlainText() == "Binary file — cannot preview."
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
    # The status bar is a result count, which is what says no dialog was raised.
    assert "files found" in status(window)


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
        assert window.panel.text.toPlainText() == text
    assert highlighted(window) == marks


def test_a_plain_compressed_file_previews_as_text(conf, tree, search):
    """This used to read "Binary file"; it has no member but still needs
    decompressing before there is anything to show."""
    conf(archives=True)
    window = search(tree, "needle")
    select(window, "notes.txt.gz")
    assert window.panel.text.toPlainText() == "gzipped needle content\nsecond gz needle\n"
    assert highlighted(window) == ["needle", "needle"]


def test_a_tarball_member_previews(conf, tree, search):
    conf(archives=True)
    window = search(tree, "needle")
    select(window, "bundle.tar.gz → doc/one.txt")
    assert window.panel.text.toPlainText() == MEMBERS["doc/one.txt"].decode()


# -- more container formats ------------------------------------------------


@pytest.mark.parametrize(
    "name, mode",
    [
        ("bundle.tar.bz2", "w:bz2"),
        ("bundle.tar.xz", "w:xz"),
        ("bundle.tgz", "w:gz"),
        ("bundle.tar", "w"),
    ],
)
def test_other_tarball_formats_are_searched(conf, tmp_path, search, name, mode):
    folder = tmp_path / "formats"
    folder.mkdir()
    with tarfile.open(folder / name, mode) as handle:
        for member in ("doc/one.txt", "doc/sub/one.txt"):
            data = MEMBERS[member]
            info = tarfile.TarInfo(member)
            info.size = len(data)
            handle.addfile(info, io.BytesIO(data))
    conf(archives=True)
    window = search(str(folder), "needle")
    assert sorted(labels(window)) == [f"{name} → doc/one.txt", f"{name} → doc/sub/one.txt"]

    select(window, f"{name} → doc/sub/one.txt")
    assert window.panel.text.toPlainText() == MEMBERS["doc/sub/one.txt"].decode()
    assert highlighted(window) == ["needle"]


# -- Prev/Next -------------------------------------------------------------


def test_stepping_through_a_member(conf, tree, search):
    conf(archives=True)
    window = search(tree, "needle")
    select(window, "docs.zip → doc/one.txt")
    assert nav(window) == (True, "1 of 2")

    window.panel.step_match(1)
    assert window.panel.match_label.text() == "2 of 2"
    window.panel.step_match(1)
    assert window.panel.match_label.text() == "1 of 2"  # wraps forward
    window.panel.step_match(-1)
    assert window.panel.match_label.text() == "2 of 2"  # and back

    # Exactly one match is the hot one at any time.
    assert len(highlighted(window, current_only=True)) == 1


def test_switching_rows_restarts_the_count(conf, tree, search):
    conf(archives=True)
    window = search(tree, "needle")
    select(window, "docs.zip → doc/one.txt")
    window.panel.step_match(1)
    select(window, "docs.zip → doc/a[1].txt")
    assert window.panel.match_label.text() == "1 of 1"


def test_a_fresh_search_leaves_the_nav_dim(conf, tree, search):
    conf(archives=True)
    window = search(tree, "zzzznothingzzz")
    assert status(window).startswith("No matches")
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
    assert "1 file found" in status(window)


@needs_permissions
def test_a_fruitless_search_that_complained_says_no_matches(
    conf, guarded_tree, search, dialogs
):
    """Same exit 2, no results. "No matches" is decided by the count rather
    than by EXIT_NO_MATCH, precisely so this does not become an error."""
    conf(archives=True)
    window = search(guarded_tree, "zzzznothingzzz")

    assert dialogs == []
    assert status(window).startswith("No matches")
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
    assert f"{found} files found" in status(window)


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
    assert status(window).startswith("No matches")


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
    # The title bar is the app's name and stays that way, whatever happens.
    assert window.windowTitle() == "Sonar"
    assert status(window) == "Search failed"
    assert not searching(window)


# -- Open ------------------------------------------------------------------


def test_open_extracts_a_read_only_copy(conf, tree, search):
    conf(archives=True)
    window = search(tree, "needle")
    item = select(window, "docs.zip → doc/one.txt")

    assert viewer.open_in_editor(item.data(HIT_ROLE), window._search.depth) is None

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
    viewer.open_in_editor(item.data(HIT_ROLE), window._search.depth)
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
    assert window.panel.open_button.toolTip() == OPEN_TIP_ARCHIVED
    select(window, "loose.txt")
    assert window.panel.open_button.toolTip() == OPEN_TIP


# -- the folder button -----------------------------------------------------
#
# `spawned` and `NOOP_OPENER` live in conftest.py: Open on a folder row from a
# name search goes to the same opener, and test_names.py records it the same way.


def test_the_folder_button_opens_the_rows_folder(conf, tree, search, spawned):
    conf(archives=False)
    window = search(tree, "needle")
    select(window, "loose.txt")

    window.panel.folder_button.click()

    assert spawned == [[NOOP_OPENER, str(tree)]]


def test_the_folder_button_opens_an_archives_own_folder(conf, tree, search, spawned):
    """The folder for a member is the one holding the archive.

    Not the temp directory an extracted copy goes to — and nothing is
    extracted at all, which is what the untouched `_temp_root` says.
    """
    conf(archives=True)
    window = search(tree, "needle")
    select(window, "docs.zip → doc/one.txt")

    window.panel.folder_button.click()

    assert spawned == [[NOOP_OPENER, str(tree)]]
    assert viewer._temp_root is None


def test_the_folder_button_follows_the_selection(conf, tree, search):
    conf(archives=True)
    window = search(tree, "needle")
    assert not window.panel.folder_button.isEnabled()

    select(window, "docs.zip → doc/one.txt")
    assert window.panel.folder_button.isEnabled()
    assert window.panel.folder_button.toolTip() == FOLDER_TIP_ARCHIVED
    select(window, "loose.txt")
    assert window.panel.folder_button.toolTip() == FOLDER_TIP


def test_the_folder_button_is_a_square_the_height_of_the_row(conf, tree, search):
    conf(archives=False)
    window = search(tree, "needle")

    size = window.panel.folder_button.size()
    assert size.width() == size.height()
    assert size.height() == window.panel.open_button.sizeHint().height()


def test_the_folder_is_reported_when_it_is_gone(tmp_path, spawned):
    folder = tmp_path / "vanished"
    folder.mkdir()
    hit = Hit(str(folder / "file.txt"))
    folder.rmdir()

    error = viewer.open_folder(hit)

    assert error.startswith("Cannot open — the folder no longer exists")
    assert spawned == []


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
    assert window.panel.text.toPlainText().startswith("PDFs inside archives cannot be previewed.")
    assert window.panel.pdf_showing is False
    assert window.panel.panes.currentWidget() is window.panel.text
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
    assert window.panel.pdf_showing is True
    assert window.panel.panes.currentWidget() is window.panel.pdf
    # The search model fills in lazily, so the count climbs after the load.
    qtbot.waitUntil(lambda: window.panel.pdf.count() > 0, timeout=5000)


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


# -- the argv, pinned whole ------------------------------------------------


def test_argv_with_everything_on(conf, monkeypatch):
    """Every optional flag at once, in order: archives, fuzzy, the config's
    globs, then `--stats` directly before the `--` that ends the options."""
    conf(archives=True, depth=2, fuzzy=1, included=["*.md"], excluded=["*/build/*"])
    monkeypatch.setattr(search_module.shutil, "which", lambda _name: None)
    assert build_argv(current_spec()) == [
        "ugrep", "--line-buffered", "-r", "-i", "-l", "-%", "--files",
        "-z", "--zmax=2", "--separator=\t", "--format=%f%s%z%~",
        "--fuzzy=1",
        "-g", "!build/", "-g", "*.md",
        "--stats", "--", "q", "/f",
    ]


def test_argv_carries_the_pdf_filter_only_when_pdftotext_is_there(conf, monkeypatch):
    conf(archives=False)
    monkeypatch.setattr(search_module.shutil, "which", lambda _name: None)
    assert PDF_FILTER not in build_argv(current_spec())
    monkeypatch.setattr(search_module.shutil, "which", lambda name: f"/usr/bin/{name}")
    assert PDF_FILTER in build_argv(current_spec())


def test_match_argv_for_a_plain_file(conf):
    """The config's globs are set and must not appear: `-g` filters a file
    named on the command line too, so they would hide the very file whose
    matches are wanted."""
    conf(archives=True, included=["*.md"], excluded=["*/build/*"])
    spec = current_spec()
    assert spec.globs  # present on the spec, and still kept off this argv
    assert build_match_argv(replace(spec, depth=0), Hit("/f/a.md")) == [
        "ugrep", "-i", "-%", "--files", "-o", "-u", "--tabs=1",
        MATCH_FORMAT, "--", "q", "/f/a.md",
    ]


def test_match_argv_for_a_member(conf):
    conf(archives=True, included=["*.md"], excluded=["*/build/*"])
    spec = replace(current_spec(), depth=2, fuzzy=1)
    assert build_match_argv(spec, Hit("/f/d.zip", "doc/a[1].txt")) == [
        "ugrep", "-i", "-%", "--files", "-o", "-u", "--tabs=1",
        "-z", "--zmax=2", "--no-messages", "--separator=\t", ARCHIVE_MATCH_FORMAT,
        "-g", "a?1?.txt",
        "--fuzzy=1",
        "--", "q", "/f/d.zip",
    ]


# -- what a search pins ----------------------------------------------------


def test_the_preview_uses_the_query_the_search_ran(conf, tree, search):
    """Typing a new query without pressing Search must not re-highlight the
    results of the old one with it."""
    conf(archives=True)
    window = search(tree, "alpha")
    window.query_edit.setText("second")
    select(window, "docs.zip → doc/one.txt")
    assert highlighted(window) == ["alpha"]


def test_the_rows_stay_relative_to_the_folder_searched(conf, tree, search, tmp_path):
    conf(archives=False)
    window = search(tree, "loose")
    window.folder_edit.setText(str(tmp_path))
    item = select(window, "loose.txt")
    assert item.data(HIT_ROLE) == Hit(os.path.join(tree, "loose.txt"))
    assert window.panel.text.toPlainText() == "loose needle on disk\n"


# -- the folder row --------------------------------------------------------


def test_a_folder_that_is_not_there_is_reported(conf, tmp_path, qtbot, dialogs):
    conf(archives=False)
    window = MainWindow(str(tmp_path))
    qtbot.addWidget(window)
    window.query_edit.setText("needle")
    window.folder_edit.setText(str(tmp_path / "missing"))
    window.start_search()
    assert len(dialogs) == 1 and dialogs[0][1].startswith("Not a folder")
    assert not window._runner.is_running()


def test_a_tilde_folder_is_expanded(conf, tree, search, monkeypatch):
    """Every path ugrep prints has to be absolute — it is how a hit is told
    from the stats block — so the folder is expanded before ugrep sees it."""
    conf(archives=False)
    monkeypatch.setenv("HOME", os.path.dirname(tree))
    window = search(os.path.join("~", os.path.basename(tree)), "loose")
    assert labels(window) == ["loose.txt"]
    assert window._search.root == tree


def test_a_relative_folder_is_made_absolute(conf, tree, search, monkeypatch):
    conf(archives=False)
    monkeypatch.chdir(os.path.dirname(tree))
    window = search(os.path.basename(tree), "loose")
    assert labels(window) == ["loose.txt"]
    assert window.results.item(0).data(HIT_ROLE) == Hit(os.path.join(tree, "loose.txt"))


# -- the end-of-search sort ------------------------------------------------


def test_the_sort_drops_a_vanished_file_and_keeps_the_selection(conf, tmp_path, search):
    folder = tmp_path / "three"
    folder.mkdir()
    for age, name in enumerate(["new.txt", "mid.txt", "old.txt"]):
        (folder / name).write_bytes(b"needle\n")
        os.utime(folder / name, (1577836800 - age * 86400,) * 2)
    conf(archives=False)
    window = search(str(folder), "needle")
    assert labels(window) == ["new.txt", "mid.txt", "old.txt"]

    select(window, "old.txt")
    (folder / "mid.txt").unlink()
    window._sort_by_mtime()

    assert labels(window) == ["new.txt", "old.txt"]
    assert window.results.currentItem().text() == "old.txt"


# -- loose files that are not worth showing --------------------------------


@pytest.mark.parametrize(
    "data, starts",
    [
        pytest.param(b"", "(empty file)", id="empty"),
        pytest.param(b"needle\x00\x01\x02", "Binary file", id="binary"),
        pytest.param(b"needle line\n" * 200_000, "File is too large to preview", id="over-cap"),
    ],
)
def test_a_loose_file_notice(tmp_path, data, starts):
    path = tmp_path / "f.txt"
    path.write_bytes(data)
    text, is_notice = read_for_preview(Hit(str(path)))
    assert is_notice
    assert text.startswith(starts)


def test_bad_utf8_is_shown_with_replacements(tmp_path):
    """One undecodable byte is not a reason to refuse the rest of the file."""
    path = tmp_path / "latin.txt"
    path.write_bytes(b"caf\xe9 needle\n")
    assert read_for_preview(Hit(str(path))) == ("caf� needle\n", False)
