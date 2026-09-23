"""`PreviewPanel` and `SearchStatusBar` on their own, without a window.

Most preview behavior is covered through the window, where it is used
(`test_window`, `test_queries`, `test_nested`); this pins the panel's own
contract — `show_hit` with a spec, and `clear` as the one way to empty it —
and the one place the window hands it a row that has gone.
"""

from __future__ import annotations

import os

from helpers import highlighted, labels, select
from sonarex.archive import Hit
from sonarex.preview import OPEN_TIP, OPEN_TIP_ARCHIVED, PreviewPanel
from sonarex.spec import SearchSpec
from sonarex.statusbar import SPINNER_FRAMES, STATUS_READY, SearchStatusBar
from sonarex.window import HIT_ROLE


class _Panel:
    """Lets `helpers.highlighted` read a bare panel as it reads a window."""

    def __init__(self, panel):
        self.panel = panel


def test_show_hit_marks_what_the_spec_matched(qtbot, tmp_path):
    path = tmp_path / "a.txt"
    path.write_text("one needle\ntwo needle\n")
    panel = PreviewPanel()
    qtbot.addWidget(panel)

    panel.show_hit(Hit(str(path)), SearchSpec("needle", str(tmp_path)))
    assert panel.text.toPlainText() == "one needle\ntwo needle\n"
    assert highlighted(_Panel(panel)) == ["needle", "needle"]
    assert panel.match_label.text() == "1 of 2"
    assert panel.open_button.isEnabled() and panel.next_button.isEnabled()

    panel.step_match(1)
    assert panel.match_label.text() == "2 of 2"
    panel.step_match(1)
    assert panel.match_label.text() == "1 of 2"  # wraps


def test_a_name_search_spec_marks_nothing(qtbot, tmp_path):
    """After a name search the query described the name, not the text."""
    path = tmp_path / "needle.txt"
    path.write_text("needle\n")
    panel = PreviewPanel()
    qtbot.addWidget(panel)
    panel.show_hit(Hit(str(path)), SearchSpec("needle", str(tmp_path), names=True))
    assert panel.text.toPlainText() == "needle\n"
    assert highlighted(_Panel(panel)) == []
    assert not panel.next_button.isEnabled()


def test_clear_resets_everything_show_hit_set(qtbot, tmp_path):
    path = tmp_path / "a.txt"
    path.write_text("needle\n")
    panel = PreviewPanel()
    qtbot.addWidget(panel)
    panel.show_hit(Hit(str(path), "inner.txt"), SearchSpec("needle", str(tmp_path)))
    assert panel.open_button.toolTip() == OPEN_TIP_ARCHIVED

    panel.clear()
    assert panel.text.toPlainText() == ""
    assert not panel.open_button.isEnabled() and not panel.folder_button.isEnabled()
    assert not panel.next_button.isEnabled() and panel.match_label.text() == ""
    assert panel.open_button.toolTip() == OPEN_TIP
    assert not panel.pdf_showing


def test_a_selected_row_dropped_by_the_sort_empties_the_panel(conf, tmp_path, search):
    """The end-of-search sort drops rows whose file has vanished. If that was
    the selected one, the panel used to keep showing it with Open dimmed; it
    is emptied instead, like any other loss of the selection."""
    for name in ("keep.txt", "gone.txt"):
        (tmp_path / name).write_text("needle\n")
    conf(archives=False)
    window = search(str(tmp_path), "needle")
    select(window, "gone.txt")
    assert window.panel.text.toPlainText() == "needle\n"

    os.remove(tmp_path / "gone.txt")
    window._sort_by_mtime()
    assert labels(window) == ["keep.txt"]
    assert window.results.currentItem() is None
    assert window.panel.text.toPlainText() == ""
    assert not window.panel.open_button.isEnabled()


def test_a_selected_row_kept_by_the_sort_stays_selected(conf, tmp_path, search):
    for name in ("a.txt", "b.txt"):
        (tmp_path / name).write_text("needle\n")
    conf(archives=False)
    window = search(str(tmp_path), "needle")
    item = select(window, "b.txt")
    hit = item.data(HIT_ROLE)

    window._sort_by_mtime()
    assert window.results.currentItem().data(HIT_ROLE) == hit
    assert window.panel.open_button.isEnabled()
    assert highlighted(window) == ["needle"]


def test_the_status_bar_on_its_own(qtbot):
    bar = SearchStatusBar()
    qtbot.addWidget(bar)
    assert bar.message.text() == STATUS_READY and not bar.busy

    bar.set_status("Searching…", busy=True)
    assert bar.busy and bar.spinner.text() == SPINNER_FRAMES[0]
    bar._tick()
    assert bar.spinner.text() == SPINNER_FRAMES[1]

    bar.stop()
    assert not bar._spinner_timer.isActive()
    bar.set_status("done")
    assert not bar.busy and bar.spinner.text() == ""
