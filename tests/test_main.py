"""The entry point: what happens to an exception nothing else caught."""

from __future__ import annotations

import sys

from sonarex.__main__ import _report_unhandled


def test_an_escaped_exception_is_reported_not_fatal(qtbot, dialogs):
    """PyQt6 aborts the process when an exception leaves a slot and no
    excepthook is installed. The hook shows it instead, traceback tail and
    all."""
    try:
        raise ValueError("boom")
    except ValueError:
        _report_unhandled(*sys.exc_info())
    [(title, message)] = dialogs
    assert "internal error" in title
    assert "ValueError: boom" in message
