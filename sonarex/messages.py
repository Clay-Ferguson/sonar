"""Message boxes in Sonar's own window frame.

Drop-in replacements for `QMessageBox.critical()`, `warning()`,
`information()` and `question()`, with the same arguments and results. The
static ones build and run their box in a single call, leaving nothing to hand
to `windowchrome.apply_frame()` — so they would show the system's title bar
beside a framed main window. These build the box, frame it, and run it.

A message box built by hand calls `apply_frame()` itself before `exec()`.
The test suite's `dialogs` fixture catches every box at `QMessageBox.exec()`,
so it catches these too.
"""

from __future__ import annotations

from PyQt6.QtWidgets import QMessageBox, QWidget
from windowchrome import apply_frame

Button = QMessageBox.StandardButton


def _show(
    icon: QMessageBox.Icon,
    parent: QWidget | None,
    title: str,
    text: str,
    buttons: Button,
    default: Button,
) -> Button:
    box = QMessageBox(icon, title, text, buttons, parent)
    box.setDefaultButton(default)
    apply_frame(box)
    return Button(box.exec())


def critical(
    parent: QWidget | None,
    title: str,
    text: str,
    buttons: Button = Button.Ok,
    default: Button = Button.NoButton,
) -> Button:
    return _show(QMessageBox.Icon.Critical, parent, title, text, buttons, default)


def warning(
    parent: QWidget | None,
    title: str,
    text: str,
    buttons: Button = Button.Ok,
    default: Button = Button.NoButton,
) -> Button:
    return _show(QMessageBox.Icon.Warning, parent, title, text, buttons, default)


def information(
    parent: QWidget | None,
    title: str,
    text: str,
    buttons: Button = Button.Ok,
    default: Button = Button.NoButton,
) -> Button:
    return _show(QMessageBox.Icon.Information, parent, title, text, buttons, default)


def question(
    parent: QWidget | None,
    title: str,
    text: str,
    buttons: Button = Button.Yes | Button.No,
    default: Button = Button.NoButton,
) -> Button:
    return _show(QMessageBox.Icon.Question, parent, title, text, buttons, default)
