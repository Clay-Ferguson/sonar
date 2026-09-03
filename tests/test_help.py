"""The Help menu, and the documents behind it.

The rendering itself is windowchrome's and is tested there. What is Sonar's
own is which documents exist, that the menu reaches them, and — the valuable
one — that every link inside them still resolves, since `docs/` is now
content the running app reads rather than prose that only ever had to be
right on GitHub.
"""

from __future__ import annotations

import re

import pytest
from windowchrome import MarkdownView, heading_slugs
from windowchrome.markdowndialog import _WINDOWS, close_markdown_windows

from sonarex.help import DOCS_DIR
from sonarex.window import MainWindow

# [text](target) — enough for these documents, which have no reference-style
# links and no images.
LINK = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*$", re.MULTILINE)

MENU_DOCUMENTS = [("Query Syntax", "HELP.md"), ("User Guide", "USER_GUIDE.md")]


def documents():
    return sorted(DOCS_DIR.glob("*.md"))


@pytest.fixture(autouse=True)
def _close_help():
    yield
    close_markdown_windows()


def options_menu(window):
    for action in window.menuBar().actions():
        if action.text() == "&Options":
            return action.menu()
    raise AssertionError("no Options menu")


def document_actions(window):
    """The two document items, which sit on Options directly."""
    wanted = {f"&{label}" for label, _ in MENU_DOCUMENTS}
    return [a for a in options_menu(window).actions() if a.text() in wanted]


# -- the documents ----------------------------------------------------------


@pytest.mark.parametrize("_label,name", MENU_DOCUMENTS)
def test_the_menu_documents_exist(_label, name):
    """Guards the `docs/` path `help.py` computes, and any move of it."""
    assert (DOCS_DIR / name).is_file()


def test_every_relative_link_points_at_a_file_that_exists():
    missing = []
    for path in documents():
        for target in LINK.findall(path.read_text()):
            if target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            if not (path.parent / target.split("#")[0]).exists():
                missing.append(f"{path.name} -> {target}")
    assert missing == []


def test_every_fragment_link_points_at_a_heading_that_exists():
    """The one that catches a renamed heading.

    A heading's slug is its anchor, so renaming one silently breaks every
    link into it — including the guide's own Contents list, which is a table
    of contents the app renders and people click. `heading_slugs` is
    imported rather than reimplemented here on purpose: a checker with its
    own copy of the numbering rule is one that will eventually disagree with
    the anchors actually in the document.
    """
    anchors = {
        path.name: set(heading_slugs([m.group(2) for m in HEADING.finditer(path.read_text())]))
        for path in documents()
    }

    broken = []
    for path in documents():
        for target in LINK.findall(path.read_text()):
            if target.startswith(("http://", "https://", "mailto:")):
                continue
            file_part, _, fragment = target.partition("#")
            if not fragment:
                continue
            name = file_part or path.name
            if fragment not in anchors.get(name, set()):
                broken.append(f"{path.name} -> {target}")
    assert broken == []


# -- the menu ---------------------------------------------------------------


def test_both_documents_are_on_the_options_menu(qtbot, tmp_path):
    """Directly on it, not behind a submenu."""
    window = MainWindow(str(tmp_path))
    qtbot.addWidget(window)
    labels = [a.text() for a in options_menu(window).actions()]
    assert labels == ["&Settings", "&Query Syntax", "&User Guide"]
    assert not any(a.menu() for a in options_menu(window).actions())


@pytest.mark.parametrize("label,name", MENU_DOCUMENTS)
def test_each_item_opens_its_document(qtbot, tmp_path, label, name):
    window = MainWindow(str(tmp_path))
    qtbot.addWidget(window)

    action = next(a for a in document_actions(window) if a.text().replace("&", "") == label)
    action.trigger()

    assert len(_WINDOWS) == 1
    dialog = next(iter(_WINDOWS.values()))
    assert dialog.windowTitle() == f"Sonar — {label}"
    assert (DOCS_DIR / name).read_text().splitlines()[0].lstrip("# ") in dialog.view.document().toPlainText()


def test_opening_the_same_document_twice_leaves_one_window(qtbot, tmp_path):
    window = MainWindow(str(tmp_path))
    qtbot.addWidget(window)
    action = document_actions(window)[0]

    action.trigger()
    action.trigger()

    assert len(_WINDOWS) == 1


def test_closing_sonar_closes_the_help_windows(qtbot, tmp_path):
    """A help window outliving the window it is about is wrong on its face."""
    window = MainWindow(str(tmp_path))
    qtbot.addWidget(window)
    for action in document_actions(window):
        action.trigger()
    assert len(_WINDOWS) == 2

    window.close()
    assert _WINDOWS == {}


def test_the_guide_renders_its_images_without_sideways_scrolling(qtbot, tmp_path):
    window = MainWindow(str(tmp_path))
    qtbot.addWidget(window)
    document_actions(window)[1].trigger()

    dialog = next(iter(_WINDOWS.values()))
    assert dialog.view.horizontalScrollBar().maximum() == 0


def paragraph_heights(view):
    """Every non-empty, non-heading paragraph's laid-out height."""
    document = view.document()
    heights = []
    block = document.begin()
    while block.isValid():
        if block.text().strip() and not block.blockFormat().headingLevel():
            heights.append(document.documentLayout().blockBoundingRect(block).height())
        block = block.next()
    return heights


@pytest.mark.parametrize("_label,name", MENU_DOCUMENTS)
def test_the_whole_document_is_laid_out(qtbot, _label, name):
    """Every paragraph has a height — the guard against a blank band.

    windowchrome's view used to restyle the rendered document — a format
    merged per link, per heading and per code block, hundreds of changes.
    Applied to a document Qt is laying out *incrementally*, which is what
    happens whenever the view is already on screen when the content arrives
    (as it is after a click on a link), the layout stops part way through and
    every block past that point keeps a height of zero. On screen that is a
    run of paragraphs rendering as an inch of blank space, the text present
    and selectable but invisible; it hit the User Guide's last three sections,
    and the document reported itself 5338px tall instead of 7480.

    The view no longer modifies the document at all. This test lives here
    rather than in windowchrome because it is *this* document that reproduces
    the failure — a synthetic one of the same length and shape does not.
    """
    view = MarkdownView()
    qtbot.addWidget(view)
    view.set_image_width(780)
    # Shown before loading, deliberately: that is the ordering that broke.
    view.resize(840, 760)
    view.show()
    qtbot.waitExposed(view)

    view.load(DOCS_DIR / name)

    heights = paragraph_heights(view)
    assert heights
    blank = sum(1 for h in heights if h == 0)
    assert blank == 0, f"{blank} of {len(heights)} paragraphs were never laid out"
