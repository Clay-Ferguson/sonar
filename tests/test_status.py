"""The status bar along the bottom, and the `--stats` count it reports.

Two things are being pinned here. One is that ugrep's `--stats` block — which
arrives on *stdout*, after the last hit — is read for its file count and never
listed as a result; get that wrong and every search grows half a dozen rows of
English prose at the end of it. The other is that the bar says what happened
and the title bar does not: the title is the app's name in every state, which
is a thing that has been moved twice and should stay put.
"""

from __future__ import annotations

from helpers import labels, searching, status
from sonarex.search import STATS_FILES, SearchRunner
from sonarex.style import STATUS_BAR_MARGINS
from sonarex.window import SPINNER_FRAMES, STATUS_READY


# -- telling the stats block from a result ---------------------------------


def test_the_stats_block_is_not_listed_as_results(conf, tree, search):
    """Every row is a path. Nothing from the block ugrep prints after them —
    the "Searched n files" line or the prose under it — reaches the list."""
    conf(archives=False)
    window = search(tree, "needle")
    assert labels(window)
    assert not any(row.startswith("Searched ") for row in labels(window))
    assert not any("--directories" in row for row in labels(window))


def test_the_searched_count_arrives(conf, tree, search):
    """`--stats` is the only thing that reports it, and it is at least the
    number of files that matched."""
    conf(archives=False)
    window = search(tree, "needle")
    searched = window._runner.files_searched()
    assert searched >= len(labels(window)) > 0


def test_a_path_that_looks_like_the_stats_line_is_still_a_row(qtbot):
    """The discriminator is one-way on purpose: a line beginning with '/' is a
    hit, whatever it says. The folder is passed absolute, so every path ugrep
    prints is too — including a file someone called `Searched 3 files`."""
    runner = SearchRunner()
    seen = []
    runner.matchFound.connect(seen.append)

    runner._take_line("/tmp/Searched 3 files in 1 directory")
    runner._take_line("Searched 12 files in 1 directory in 0.1 seconds")
    runner._take_line("  --directories=recurse")

    assert seen == ["/tmp/Searched 3 files in 1 directory"]
    assert runner.files_searched() == 12


def test_nothing_after_the_stats_line_is_a_result(qtbot):
    """The rest of the block is prose, and ugrep prints it last, so the flag
    the count sets stays set for the remainder of the run."""
    runner = SearchRunner()
    seen = []
    runner.matchFound.connect(seen.append)

    runner._take_line("Searched 1 file in 1 directory in 0.1 seconds")
    runner._take_line("/tmp/after.txt")

    assert seen == []


def test_a_thousands_separator_is_read_as_a_number():
    """ugrep prints plain digits here, but the pattern accepts the grouped
    form too — a count that came back as a string would put "1,234" through
    a `:,` format and read `1,2,3,4`."""
    found = STATS_FILES.match("Searched 1,234 files in 2 directories")
    assert found and int(found.group(1).replace(",", "")) == 1234


# -- what the bar says ------------------------------------------------------


def test_the_bar_is_ready_before_the_first_search(qtbot, conf):
    from sonarex.window import MainWindow

    conf(archives=False)
    window = MainWindow("/tmp")
    qtbot.addWidget(window)
    assert status(window) == STATUS_READY
    assert not searching(window)


def test_the_bar_has_room_around_its_text(qtbot, conf):
    """The room is contents margins, not a stylesheet `padding`: a QStatusBar
    ignores padding outright — measured, 22px tall with it and without it — and
    the margins have to survive the stylesheet swap `_set_busy` does on every
    search, which is the way this could quietly come undone."""
    from sonarex.window import MainWindow

    conf(archives=False)
    window = MainWindow("/tmp")
    qtbot.addWidget(window)
    bare = window.statusBar().contentsMargins()
    assert (bare.top(), bare.bottom()) == (STATUS_BAR_MARGINS[1], STATUS_BAR_MARGINS[3])

    window._set_status("Searching…", busy=True)
    window._set_status("done")
    after = window.statusBar().contentsMargins()
    assert (after.left(), after.top()) == (STATUS_BAR_MARGINS[0], STATUS_BAR_MARGINS[1])


def test_a_finished_search_reports_both_counts(conf, tree, search):
    conf(archives=False)
    window = search(tree, "needle")
    text = status(window)
    assert f"{len(labels(window))} files found" in text
    assert f"{window._runner.files_searched():,} files searched" in text
    assert tree in text


def test_a_fruitless_search_still_says_how_many_were_searched(conf, tree, search):
    conf(archives=False)
    window = search(tree, "zzzznothingzzz")
    assert status(window).startswith("No matches")
    assert "files searched" in status(window)


def test_the_bar_is_green_while_searching_and_not_after(qtbot, conf, tree):
    """`_busy` is the flag behind both the green and the spinner, and it has
    to be *off* once ugrep has exited — a bar left green says a search that
    finished is still running."""
    from sonarex.window import MainWindow

    conf(archives=False)
    window = MainWindow(tree)
    qtbot.addWidget(window)
    window.query_edit.setText("needle")
    with qtbot.waitSignal(window._runner.finished, timeout=30000):
        window.start_search()
        assert searching(window)
        assert "Searching" in status(window)
    assert not searching(window)


def test_the_spinner_turns_and_stops(qtbot, conf, tree):
    """It is the only sign a search that has found nothing yet is alive, so a
    frozen one is the failure worth catching. `_set_busy` is idempotent for
    exactly this reason: `_on_match` re-enters the busy state on every hit,
    and restarting the timer there would park it on its first glyph."""
    from sonarex.window import MainWindow

    conf(archives=False)
    window = MainWindow(tree)
    qtbot.addWidget(window)
    window._set_status("Searching…", busy=True)
    assert window._status_spinner.text() == SPINNER_FRAMES[0]

    # A hit arriving must not reset it.
    window._search_root = tree
    window._on_match(f"{tree}/loose.txt")
    window._tick_spinner()
    assert window._status_spinner.text() == SPINNER_FRAMES[1]

    window._set_status("done")
    assert window._status_spinner.text() == ""
    assert not window._spinner_timer.isActive()


def test_the_title_bar_is_only_the_app_name(conf, tree, search):
    """It carried the search's numbers once. It does not any more, in any
    state — that is the whole reason the status bar came back."""
    conf(archives=False)
    for query in ("needle", "zzzznothingzzz"):
        window = search(tree, query)
        assert window.windowTitle() == "Sonar"
