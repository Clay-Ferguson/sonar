"""The status bar: what a search is doing, and whether it is still doing it.

A message on the left, and in front of it a text spinner that turns while a
search runs; the bar goes green for the same span. The window says what to
show (`set_status`) and whether a search is running; everything about how
that looks — the colors, the spinner's glyphs and its timer — is here.
"""

from __future__ import annotations

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QLabel, QStatusBar, QWidget

from .style import STATUS_BAR_MARGINS, mono_font, status_style

# The status bar's activity indicator, and how fast it turns. Text rather than
# an animated image: Qt ships no spinner widget and no animated icon in the
# standard pixmaps, and a QMovie would mean carrying a GIF as an asset for one
# character's worth of motion. These four glyphs in the monospace font the
# results list already uses read as one rotating bar and take a fixed width,
# so nothing beside them shifts as it turns.
#
# 120ms is fast enough to look continuous and slow enough that a search
# finishing in one frame does not flash. The timer is the only thing that says
# a search over a large tree yielding nothing yet is still running.
SPINNER_FRAMES = "|/-\\"
SPINNER_INTERVAL_MS = 120

# What the bar says before the first search of a session. Something rather
# than nothing: an empty strip along the bottom of the window reads as a
# rendering fault, and "Ready" also shows where a search will report itself.
STATUS_READY = "Ready"


class SearchStatusBar(QStatusBar):
    """The window's status bar, with a spinner and a searching state."""

    def __init__(self, parent: QWidget | None = None) -> None:
        """The line along the bottom: an activity indicator and a message.

        A real `QStatusBar` rather than one more row in the central layout,
        because the menu items already carry `setStatusTip` text and this is
        the widget Qt shows it in — hovering Options ▸ Settings says what it
        does, for free, the moment the bar exists. The size grip is off: the
        window is resizable from any edge already, and the grip reads as a
        second thing in a bar that has one.

        The spinner and the message are two labels rather than one so the
        message cannot shift sideways as the spinner turns, and the spinner's
        width is pinned for the same reason — the glyphs are monospaced, but
        an empty spinner between searches would otherwise collapse to nothing
        and drag the message left with it.
        """
        super().__init__(parent)
        # Where the spinner is in its cycle, and whether it is turning at all.
        # The flag is what makes `_set_busy` idempotent — see the note there.
        self._spinner_frame = 0
        self._busy = False

        self.spinner = QLabel()
        self.spinner.setFont(mono_font())
        self.spinner.setFixedWidth(self.spinner.fontMetrics().horizontalAdvance("M"))
        self.message = QLabel(STATUS_READY)

        self.setSizeGripEnabled(False)
        # Contents margins rather than a stylesheet `padding`, which a
        # QStatusBar ignores outright — see STATUS_BAR_MARGINS. Set once here:
        # they survive the stylesheet `_set_busy` swaps on every search.
        self.setContentsMargins(*STATUS_BAR_MARGINS)
        self.addWidget(self.spinner)
        self.addWidget(self.message, 1)
        # Directly, not through `_set_busy`: the flag already says idle, so
        # that call is the no-op the guard is there to make it.
        self.setStyleSheet(status_style(False))

        # Started and stopped by `_set_busy`, never left running: it is a
        # repaint of two labels every 120ms, which is nothing next to a search
        # and is still not worth doing while the window sits idle.
        self._spinner_timer = QTimer(self)
        self._spinner_timer.setInterval(SPINNER_INTERVAL_MS)
        self._spinner_timer.timeout.connect(self._tick)

    def _set_busy(self, busy: bool) -> None:
        """Turn the searching look on or off: the green, and the spinner.

        The color is the half of this that can be read without reading, which
        is the point of it — a glance at the bottom of the window says whether
        the thing is still working. The spinner is the half that says it is
        still working *now*, which the color alone cannot: a search over a
        large tree that has found nothing yet leaves every other part of the
        window exactly as it was before Search was pressed.
        """
        # Idempotent, and it has to be: the window sets the status on every
        # hit, and re-entering the busy state would restart the timer and reset
        # the frame each time — the spinner would sit frozen on its first glyph
        # for exactly the search that is streaming results fastest.
        if busy == self._busy:
            return
        self._busy = busy
        self.setStyleSheet(status_style(busy))
        if busy:
            self._spinner_frame = 0
            self.spinner.setText(SPINNER_FRAMES[0])
            self._spinner_timer.start()
        else:
            self._spinner_timer.stop()
            self.spinner.clear()

    def _tick(self) -> None:
        self._spinner_frame = (self._spinner_frame + 1) % len(SPINNER_FRAMES)
        self.spinner.setText(SPINNER_FRAMES[self._spinner_frame])

    def set_status(self, message: str, busy: bool = False) -> None:
        """Put `message` in the status bar, in one of its two states.

        This is where a search says how it is going — the title bar is the
        app's name and nothing else. A search's numbers belong at the bottom
        of the window beside the results they describe, not in a strip the
        window manager may truncate, ellipsize or refuse to widen.
        """
        self.message.setText(message)
        self._set_busy(busy)

    @property
    def busy(self) -> bool:
        """Whether the bar is in its searching state — green, spinner on."""
        return self._busy

    def stop(self) -> None:
        """Stop the spinner for good; called as the window closes, so it does
        not go on repainting two labels while they are torn down."""
        self._spinner_timer.stop()
