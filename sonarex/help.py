"""The query-syntax help dialog.

Rendered with Qt's own rich-text support — a subset of HTML built into
QtGui, not a web engine or any other extra dependency. That is enough for
headings, bullets and inline monospace, which is all this needs.

Kept out of `window.py` so neither file has to know much about the other:
it imports only `style`, which sits below everything, so `window` -> `help`
never becomes a cycle.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from .style import action_button

# Wide enough that no bullet wraps at the default font size — the list reads
# as one item per line, which is most of what makes it scannable.
MIN_WIDTH = 520


def _mono(text: str) -> str:
    """`text` as inline monospace.

    The font family is named in a style attribute rather than left to a bare
    <code> tag: Qt's rich text honors the tag, but spelling out the family
    keeps the fragments looking the same whatever the surrounding style does
    with it.
    """
    return f'<span style="font-family:monospace; font-weight:bold">{text}</span>'


def _section(title: str, items: list[str]) -> str:
    bullets = "".join(f"<li style='margin-bottom:4px'>{item}</li>" for item in items)
    return (
        f"<p style='margin-top:14px; margin-bottom:2px'><b>{title}</b></p>"
        f"<ul style='margin-top:0'>{bullets}</ul>"
    )


HELP_HTML = (
    _section(
        "Query Syntax",
        [
            f"Unquoted terms are {_mono('regular expressions')}",
            f"{_mono('&quot;quoted phrases&quot;')} match literally (not as regex)",
            f"Space or {_mono('AND')} requires all terms",
            f"{_mono('OR')} matches any term",
            f"{_mono('NOT')} (or {_mono('-term')}) excludes",
            f"Parenthetical groupings of {_mono('AND')}/{_mono('OR')}/{_mono('NOT')}"
            " are allowed",
        ],
    )
    + _section(
        "Regex Match Tips",
        [
            f"Whole word ABC: {_mono(r'\bABC\b')}",
            f"From 0 up to 10 characters: {_mono('.{0,10}')}",
            f"Any string of chars: {_mono('.*')}",
        ],
    )
    + "<p style='margin-top:14px'><i>Searches are case-insensitive, and a query"
    " matches a file when its terms appear anywhere in that file — not"
    " necessarily on the same line.</i></p>"
)


class HelpDialog(QDialog):
    """A short, static reference for what can go in the query field."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Sonar — Query Syntax")
        self.setMinimumWidth(MIN_WIDTH)

        body = QLabel(HELP_HTML)
        body.setTextFormat(Qt.TextFormat.RichText)
        body.setWordWrap(True)
        # Selectable so the regex fragments can be copied straight out of the
        # dialog into the query field, which is the main thing anyone would
        # want to do with them.
        body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        body.setAlignment(Qt.AlignmentFlag.AlignTop)

        # A plain button rather than a QDialogButtonBox: the box supplies its
        # own Close, styled by the native theme, which is exactly the button
        # that would not match the rest of the app.
        close = action_button("Close", uniform=True)
        close.clicked.connect(self.reject)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(close)

        layout = QVBoxLayout(self)
        layout.addWidget(body)
        layout.addStretch(1)
        layout.addLayout(buttons)


def show_help(parent: QWidget | None = None) -> None:
    """Open the help dialog, modally, and return once it is dismissed."""
    HelpDialog(parent).exec()
