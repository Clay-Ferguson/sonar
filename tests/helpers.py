"""Reading the window back: what is listed, what is selected, what is colored.

These assert on the objects rather than on pixels. `highlighted()` is the one
worth understanding — it walks the preview document and collects the text of
every run the highlighter painted, which turns "the right words are marked"
into an ordinary string comparison.
"""

from __future__ import annotations

from sonarex import config
from sonarex.spec import SearchSpec
from sonarex.style import MATCH_BG, MATCH_CURRENT_BG


def current_spec(query: str = "q", root: str = "/f", names: bool = False) -> SearchSpec:
    """The spec a search would pin right now, from whatever `conf` wrote.

    What `MainWindow.start_search` builds, minus the window: one read of the
    config folded into a `SearchSpec`, so a test can check what the settings
    put on an argv without running anything.
    """
    return SearchSpec.from_settings(config.load_settings()[0], query, root, names)


def labels(window) -> list[str]:
    """Every row's text, in the order the list holds them."""
    return [window.results.item(row).text() for row in range(window.results.count())]


def select(window, label):
    """Click the row with this text. Raises if it is not there."""
    for row in range(window.results.count()):
        if window.results.item(row).text() == label:
            window.results.setCurrentRow(row)
            return window.results.item(row)
    raise AssertionError(f"no row {label!r} in {labels(window)}")


def status(window) -> str:
    """What the status bar along the bottom is saying.

    The window title used to carry this and is now only the app's name, so a
    test asking "what did the search report" reads it here.
    """
    return window._status.message.text()


def searching(window) -> bool:
    """Whether the status bar is in its searching state — green, spinner on."""
    return window._status.busy


def highlighted(window, current_only=False) -> list[str]:
    """The highlighted words in the preview, in reading order.

    Both match colors are collected by default. The *current* match is painted
    `MATCH_CURRENT_BG` rather than `MATCH_BG`, so a check that gathers only the
    latter silently drops one and reads as a lost match — pass `current_only`
    to ask the other question, which one Prev/Next is parked on.
    """
    wanted = {MATCH_CURRENT_BG.lower()}
    if not current_only:
        wanted.add(MATCH_BG.lower())

    found = []
    block = window.panel.text.document().begin()
    while block.isValid():
        for run in block.layout().formats():
            if run.format.background().color().name().lower() in wanted:
                found.append(block.text()[run.start : run.start + run.length])
        block = block.next()
    return found


def nav(window) -> tuple[bool, str]:
    """Whether Prev/Next are live, and what the counter reads."""
    return (window.panel.next_button.isEnabled(), window.panel.match_label.text())
