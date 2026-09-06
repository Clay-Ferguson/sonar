"""The two help windows, and where their content lives.

There is no help *text* here any more. Both documents are markdown files
under `docs/`, rendered by `windowchrome.show_markdown()` — so changing what
the help says means editing markdown, not Python, and the same two files
serve as the repository's documentation and as the app's.

Kept out of `window.py` so neither file has to know much about the other: it
imports only `style`, which sits below everything, so `window` -> `help`
never becomes a cycle.
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtWidgets import QWidget
from windowchrome import MarkdownDialog, apply_scrollbars, show_markdown

from . import APP_NAME
from .style import action_button

# `docs/` sits beside the package, not inside it. That is safe rather than
# lucky: `pyproject.toml` sets `package = false` and `start.sh` runs the app
# out of the tree with `uv run --directory`, so there is no wheel this could
# be missing from and nothing for `importlib.resources` to improve on.
DOCS_DIR = Path(__file__).resolve().parent.parent / "docs"


def _open(name: str, title: str, parent: QWidget | None) -> MarkdownDialog:
    """Show one of the documents, styled like the rest of the app."""
    dialog = show_markdown(
        DOCS_DIR / name,
        parent,
        title=f"{APP_NAME} — {title}",
        # Every button in this app comes from `action_button`, and this is the
        # one place that factory is handed *out* — the dialog lives in
        # windowchrome, which has no opinion about button color, and a plain
        # QPushButton would come out wearing the desktop theme.
        button_factory=lambda text: action_button(text, uniform=True),
    )
    # The wider scroll bars the rest of the app uses. `.view` is public for
    # exactly this: styling the button factory cannot reach.
    apply_scrollbars(dialog.view)
    return dialog


def show_query_syntax(parent: QWidget | None = None) -> None:
    """The short reference for what can go in the query field."""
    _open("HELP.md", "Query Syntax", parent)


def show_user_guide(parent: QWidget | None = None) -> None:
    """The whole user guide, the same one that ships in `docs/`."""
    _open("USER_GUIDE.md", "User Guide", parent)
