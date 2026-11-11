"""Every window Sonar opens wears windowchrome's title bar and border.

What the frame itself does — dragging, resizing, the buttons, the colors — is
windowchrome's to test (its `tests/test_frame.py`), and dragging and resizing
can only be tried by hand anyway. What is Sonar's is that each window *gets*
one, and that the main window's layout lands below it.
"""

from __future__ import annotations

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QMessageBox
from windowchrome import WindowFrame, close_markdown_windows

from sonarex import help as help_windows
from sonarex import messages
from sonarex.settings import SettingsDialog
from sonarex.window import MainWindow


def frame_of(window) -> WindowFrame | None:
    return window.findChild(WindowFrame, options=Qt.FindChildOption.FindDirectChildrenOnly)


def caption_buttons(frame: WindowFrame) -> list[str]:
    bar = frame.title_bar
    return [
        name
        for name in ("minimize_button", "maximize_button", "close_button")
        if hasattr(bar, name)
    ]


def test_the_main_window_is_framed_with_all_three_buttons(qtbot, tmp_path):
    window = MainWindow(str(tmp_path))
    qtbot.addWidget(window)
    frame = frame_of(window)
    assert frame is not None
    assert caption_buttons(frame) == ["minimize_button", "maximize_button", "close_button"]


def test_the_title_bar_does_not_take_room_from_the_content(qtbot, tmp_path):
    """The title bar is inside the window now, so the size asked for grows by
    its height and the panes keep what they had."""
    window = MainWindow(str(tmp_path))
    qtbot.addWidget(window)
    assert window.height() == 700 + frame_of(window).title_bar.height()


def test_the_menu_bar_is_below_the_title_bar(qtbot, tmp_path):
    window = MainWindow(str(tmp_path))
    qtbot.addWidget(window)
    window.show()
    qtbot.waitExposed(window)
    title_bar = frame_of(window).title_bar
    assert window.menuBar().geometry().top() >= title_bar.geometry().bottom()


def test_the_settings_dialog_is_framed_with_a_close_button_only(conf, qtbot):
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    frame = frame_of(dialog)
    assert frame is not None
    assert caption_buttons(frame) == ["close_button"]


@pytest.mark.parametrize("name", ["HELP.md", "USER_GUIDE.md"])
def test_a_help_window_is_framed_once_however_often_it_is_opened(qtbot, name):
    try:
        first = help_windows._open(name, "Test", None)
        again = help_windows._open(name, "Test", None)
        assert again is first
        assert len(first.findChildren(WindowFrame)) == 1
        assert caption_buttons(frame_of(first)) == ["close_button"]
    finally:
        close_markdown_windows()


@pytest.mark.parametrize(
    "show", [messages.critical, messages.warning, messages.information, messages.question]
)
def test_a_message_box_is_framed_before_it_runs(qtbot, monkeypatch, show):
    seen = []

    def capture(box, *args, **kwargs):
        seen.append((box.windowTitle(), box.text(), frame_of(box) is not None))
        return QMessageBox.StandardButton.Ok.value

    monkeypatch.setattr(QMessageBox, "exec", capture)
    assert show(None, "Title", "Text") == QMessageBox.StandardButton.Ok
    assert seen == [("Title", "Text", True)]
