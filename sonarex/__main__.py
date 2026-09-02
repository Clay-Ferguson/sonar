"""Entry point: python -m sonarex [FOLDER]"""

from __future__ import annotations

import argparse
import os
import sys

from PyQt6.QtWidgets import QApplication, QMessageBox

from . import APP_NAME, UI_POINT_SIZE
from .config import ensure_config
from .search import ugrep_available
from .style import WAYLAND_DECORATION, paint_title_bar, tune_palette
from .window import MainWindow


def resolve_folder(argument: str | None) -> tuple[str, str | None]:
    """The folder to search, plus a warning to show about it (or None).

    With no argument, the current working directory — which is what a desktop
    launcher gives us, and a sensible place for the folder row to start.

    A path that turns out to be a *file* resolves to its parent directory.
    That is carried over from the Nautilus version, where the search could be
    invoked on a selected file, and it stays useful for anything scripting
    Sonar.
    """
    if argument is None:
        return os.getcwd(), None

    folder = os.path.abspath(os.path.expanduser(argument))
    if os.path.isdir(folder):
        return folder, None
    if os.path.isfile(folder):
        return os.path.dirname(folder), None
    return (
        os.getcwd(),
        f"No such folder:\n\n{folder}\n\nStarting in {os.getcwd()} instead.",
    )


def main() -> int:
    # nargs="?" rather than a required argument: argparse reports a missing
    # one on stderr and exits before a QApplication exists, which is invisible
    # when Sonar is started from a desktop icon rather than a terminal.
    # Everything that can go wrong is reported in a dialog below instead.
    parser = argparse.ArgumentParser(prog="sonarex", description=__doc__)
    parser.add_argument(
        "folder",
        nargs="?",
        default=None,
        metavar="FOLDER",
        help="folder to search in; defaults to the current directory",
    )
    args = parser.parse_args()

    # Before the QApplication, because the Wayland platform plugin reads this
    # during that constructor and never again. `setdefault` so an explicit
    # value in the environment still wins — this is a default, not a policy.
    # See `style.paint_title_bar()` for what it buys.
    os.environ.setdefault("QT_WAYLAND_DECORATION", WAYLAND_DECORATION)

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    # applicationDisplayName is deliberately NOT set. Every platform backend
    # runs its window titles through QPlatformWindow::formatWindowTitle(),
    # which appends the display name to whatever setWindowTitle() was given —
    # so with it set, the help dialog's "Sonar — Query Syntax" reached the
    # title bar as "Sonar — Query Syntax — Sonar". Each window spells out
    # its own full title instead.
    # Ties the window to sonarex.desktop, so the desktop shows our icon and
    # name in the dock and alt-tab. Without it the Wayland app_id is derived
    # from argv[0] ("python3") and matches no desktop entry at all.
    app.setDesktopFileName("sonarex")

    # Set on the application rather than per widget, so the query and folder
    # rows scale along with the two panes. The panes then override the family
    # (not the size) with a fixed-width one — see style.mono_font.
    font = app.font()
    font.setPointSize(UI_POINT_SIZE)
    app.setFont(font)

    tune_palette(app)
    paint_title_bar(app)

    if not ugrep_available():
        QMessageBox.critical(
            None,
            f"{APP_NAME} — cannot start",
            "Sonar searches with ugrep, which is not installed.\n\n"
            "Install it with:\n\n    sudo apt install ugrep",
        )
        return 1

    ensure_config()

    folder, warning = resolve_folder(args.folder)
    window = MainWindow(folder)
    window.show()
    window.activateWindow()
    window.raise_()

    # After show(), so the warning appears over the window it is talking about
    # rather than on its own against the desktop.
    if warning:
        QMessageBox.warning(window, f"{APP_NAME} — folder not found", warning)

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
