"""The right-hand pane: the file on show, and the bar of controls under it.

A `PreviewPanel` owns everything about *showing* one result: the read-only
text pane and its `MatchHighlighter`, the rendered PDF pane that stands in for
it on a PDF, the stack that swaps them, and the control bar — Open, the folder
button, Prev/Next with their counter, and Word Wrap. It also owns the walk
through the current file's matches, which reads from whichever pane is up.

The window decides *which* result to show and hands it over with the search
that found it (`show_hit`), or empties the pane (`clear`). It does not reach
into the panes, and nothing here knows about the results list or the runner.
Open and the folder button only live here: what they open is the window's
business, so it connects their `clicked` itself.
"""

from __future__ import annotations

import os

from PyQt6.QtGui import QTextCursor
from PyQt6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QStackedWidget,
    QStyle,
    QVBoxLayout,
    QWidget,
)
from windowchrome import apply_checkboxes, apply_scrollbars

from .archive import Hit
from .highlight import MatchHighlighter
from .pdfview import PDF_AVAILABLE, PdfPane
from .query import literal_query_term
from .reader import is_pdf, read_for_preview
from .search import match_spans
from .spec import SearchSpec
from .style import (
    CONTROL_BAR_PADDING,
    NAV_BUTTON_BG,
    NAV_GROUP_SPACING,
    PANE_GAP,
    SECONDARY_BUTTON_BG,
    action_button,
    icon_button,
    mono_font,
    selection_button_bg,
)

# The Open button's tooltip, which changes with the selection: a hit inside an
# archive opens a copy, and that is worth saying before the click rather than
# after the user has edited one and found the archive unchanged.
OPEN_TIP = "Open this file in the editor"
OPEN_TIP_ARCHIVED = (
    "Open a read-only copy extracted from the archive.\n"
    "Edits to it do not go back into the archive."
)
# A folder row, which only a name search produces: Open goes to the file
# manager rather than the editor, and that is worth saying before the click.
OPEN_TIP_FOLDER = "Show this folder in the file manager"

# The folder button's, which changes with the selection for the same reason
# Open's does: for a hit inside an archive the folder that opens is the one
# holding the archive, and that is worth saying before the click.
FOLDER_TIP = "Show this file's folder in the file manager"
FOLDER_TIP_ARCHIVED = "Show the folder holding the archive in the file manager"


class PreviewPanel(QWidget):
    """The preview and its control bar, as one widget for the splitter."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # The current file's matches, flattened out of the spans dict and put in
        # reading order, plus where Prev/Next is parked in that list. A flat
        # list rather than the dict because stepping is what it is for: the dict
        # is keyed for painting a line, this is ordered for walking the file.
        self._matches: list[tuple[int, int, int]] = []
        self._match_index = -1
        # Which of the two preview widgets is up. The PDF pane keeps its own
        # matches inside Qt's search model, so this is also what says where
        # Prev/Next should be reading its count from.
        self._pdf_showing = False

        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.text.setFont(mono_font())
        # The gutter, taken out of the document rather than the widget. A
        # viewport margin looks like the same thing and is not: that strip is
        # outside the viewport and gets painted in the window color, so it
        # comes out as a gray band beside the divider instead of a gutter.
        # The document's own margin is inside the text area, on its Base
        # background — which is what makes it read as part of the pane. It
        # applies to all four sides; the left is the one being asked for and
        # the rest is breathing room the preview was short of anyway.
        document = self.text.document()
        assert document is not None  # a QPlainTextEdit always has one
        document.setDocumentMargin(PANE_GAP)
        # Attached once, to the document, and fed new spans per file. The
        # document survives setPlainText, so this outlives every preview.
        self._highlighter = MatchHighlighter(document)

        # The other preview: a rendered PDF, for the files the text pane can
        # only describe. None when the QtPdf bindings are missing, in which
        # case a PDF falls back to that description — the app still runs.
        self.pdf = PdfPane() if PDF_AVAILABLE else None
        self.panes = QStackedWidget()
        self.panes.addWidget(self.text)
        if self.pdf is not None:
            self.panes.addWidget(self.pdf)
            # The model searches pages lazily, so the number of matches climbs
            # for about a second after a long PDF opens. The counter has to
            # follow it up rather than freeze on whatever it was at load.
            self.pdf.matchCountChanged.connect(self._on_pdf_count_changed)

        # --- the preview's own control bar -------------------------------
        # Sits inside the right-hand pane rather than under the whole window,
        # so it reads as belonging to the file being shown above it — and so
        # dragging the splitter moves it with the pane it controls.
        self.open_button = action_button(
            "Open", selection_button_bg(), CONTROL_BAR_PADDING
        )
        self.open_button.setToolTip(OPEN_TIP)
        # Nothing is selected at startup, and "Open" with no file would be a
        # button that silently does nothing.
        self.open_button.setEnabled(False)

        # Open aimed one level up, so it sits directly beside Open. An icon
        # rather than a label because "Folder" beside "Open" would read as a
        # second noun in a row of verbs — and because the desktop's own folder
        # is the one glyph every file manager has already taught the user to
        # recognise.
        #
        # The neutral gray rather than Open's selection tint, even though it
        # acts on the same row: the tint is a blue, the themed folder is a
        # blue, and the icon washed out against it. On a button whose whole
        # label is a picture, contrast under the picture outranks the color
        # coding — and secondary gray is a fair reading of it anyway, beside
        # the Open it is a variation on.
        self.folder_button = icon_button(
            QStyle.StandardPixmap.SP_DirIcon,
            SECONDARY_BUTTON_BG,
            CONTROL_BAR_PADDING,
        )
        self.folder_button.setToolTip(FOLDER_TIP)
        self.folder_button.setEnabled(False)

        # Prev/Next step between individual matches rather than between lines:
        # the spans are exact, so a line carrying three hits is three stops.
        # Both wrap around, which is what makes them usable without also
        # having to watch the counter to know when to stop.
        #
        # Arrows rather than the words: the pair is one control, and two
        # arrows pointing away from the counter between them say which way
        # each goes with nothing left to read.
        self.prev_button = self._nav_button(
            QStyle.StandardPixmap.SP_ArrowLeft, "Go to the previous match"
        )
        self.prev_button.clicked.connect(lambda: self.step_match(-1))
        self.next_button = self._nav_button(
            QStyle.StandardPixmap.SP_ArrowRight, "Go to the next match"
        )
        self.next_button.clicked.connect(lambda: self.step_match(1))

        # Says which match of how many, because the highlight alone cannot:
        # every match looks the same until one of them is the current one, and
        # off screen even that is invisible.
        self.match_label = QLabel()
        self.match_label.setToolTip("The current match, and how many this file has")

        self.wrap_check = QCheckBox("Word Wrap")
        apply_checkboxes(self.wrap_check)
        self.wrap_check.setChecked(True)  # matches the pane's initial mode
        self.wrap_check.toggled.connect(self._set_word_wrap)

        # The two arrows and the counter they move are one control, so they
        # travel as one widget: grouped tight, then centered in the bar by the
        # stretches on either side of it. Left-justified with everything else
        # they read as three more buttons in a row of unrelated ones.
        match_nav = QWidget()
        nav_row = QHBoxLayout(match_nav)
        nav_row.setContentsMargins(0, 0, 0, 0)
        nav_row.setSpacing(NAV_GROUP_SPACING)
        nav_row.addWidget(self.prev_button)
        nav_row.addWidget(self.next_button)
        nav_row.addWidget(self.match_label)

        control_bar = QHBoxLayout()
        control_bar.setContentsMargins(PANE_GAP, 0, 0, 0)
        control_bar.addWidget(self.open_button)
        control_bar.addWidget(self.folder_button)
        control_bar.addStretch(1)
        control_bar.addWidget(match_nav)
        control_bar.addStretch(1)
        control_bar.addWidget(self.wrap_check)

        right_layout = QVBoxLayout(self)
        # Flush with the splitter edge: the panel is a container, not a frame
        # of its own, and default margins would inset the preview from the
        # results list beside it. The gutter that keeps the contents off the
        # divider is inside the preview and the control bar instead, so it is
        # drawn in their own background rather than the window's.
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.addWidget(self.panes, 1)
        right_layout.addLayout(control_bar)

        # The wider scroll bars; applied per scroll bar so the pane itself
        # keeps native rendering.
        apply_scrollbars(self.text)

    def _show_pane(self, pdf: bool) -> None:
        """Put either the PDF pane or the text pane in front.

        Leaving the PDF pane also lets go of its document, so a file stays
        open only while it is the one being read.

        Word Wrap goes with the text pane: a rendered page has no line
        wrapping to turn off, and a checkbox that does nothing to what is on
        screen is worse than a dim one.
        """
        if self.pdf is None:
            return
        if self._pdf_showing and not pdf:
            self.pdf.clear()
        self._pdf_showing = pdf
        self.panes.setCurrentWidget(self.pdf if pdf else self.text)
        self.wrap_check.setEnabled(not pdf)

    def _set_word_wrap(self, wrap: bool) -> None:
        """Toggle wrapping in the preview pane.

        Deliberately not persisted: it is a per-look preference about the file
        on screen right now, and it starts on because most of what turns up in
        a content search is prose or long lines that would otherwise need
        horizontal scrolling to read at all.
        """
        self.text.setLineWrapMode(
            QPlainTextEdit.LineWrapMode.WidgetWidth
            if wrap
            else QPlainTextEdit.LineWrapMode.NoWrap
        )

    def _enable_row_actions(self, enabled: bool) -> None:
        """Open and the folder button, which are live or dim together.

        Both act on the current row and neither can do anything without one,
        so they have a single answer between them; kept in one place so a
        third such button cannot be added and then missed at one of the two
        sites that flips them.
        """
        self.open_button.setEnabled(enabled)
        self.folder_button.setEnabled(enabled)

    def _nav_button(self, pixmap: QStyle.StandardPixmap, tip: str) -> QPushButton:
        """One of the two match-stepping buttons, styled alike.

        Square and icon-only, sized off the padding of the text buttons beside
        it so the whole bar stays one height.
        """
        button = icon_button(pixmap, NAV_BUTTON_BG, CONTROL_BAR_PADDING)
        button.setToolTip(tip)
        # Disabled until a file with matches is on screen, for the same reason
        # Open is: a button that silently does nothing is worse than a dim one.
        button.setEnabled(False)
        return button

    # -- what the window calls ----------------------------------------------

    def show_hit(self, hit: Hit, search: SearchSpec) -> None:
        """Show `hit`, marking what `search` matched in it.

        `search` is the window's pinned spec, never a fresh one: its query,
        depth and fuzziness are the ones that found this file, and they are
        the only ones that can read it back and mark it the same way.
        """
        # Both act on the current row, so they are live exactly when one
        # exists.
        self._enable_row_actions(True)
        is_folder = not hit.member and os.path.isdir(hit.path)
        if is_folder:
            self.open_button.setToolTip(OPEN_TIP_FOLDER)
        else:
            self.open_button.setToolTip(OPEN_TIP_ARCHIVED if hit.member else OPEN_TIP)
        self.folder_button.setToolTip(FOLDER_TIP_ARCHIVED if hit.member else FOLDER_TIP)

        # A PDF is rendered rather than described — but only if it renders:
        # a failure comes back as a message, which the text pane then shows
        # in place of the "binary file" notice it would have shown anyway.
        #
        # A PDF *inside* an archive is not one of these: `PdfPane` loads a
        # path, and there is no path to a name inside a zip. It falls through
        # to the text pane, which says so.
        text = None
        if self.pdf is not None and not is_folder and not hit.member and is_pdf(hit.path):
            # After a name search the query is about the name, so nothing in
            # the pages is marked.
            term = None if search.names else literal_query_term(search.query)
            text = self.pdf.show_file(hit.path, term)
            if text is None:
                self._show_pane(True)
                self._adopt_pdf_matches()
                return
        self._show_pane(False)
        if text is not None:
            self._highlighter.set_spans({})
            self.text.setPlainText(text)
            self._adopt_matches({})
            return

        text, is_notice = read_for_preview(hit, search.depth)
        # A notice — binary, too large, unreadable — is this app's own words
        # rather than the file, so there is nothing in it ugrep matched and its
        # line numbers mean nothing. Asking ugrep about it would also be asking
        # about a file that by definition cannot be shown.
        # And after a name search the query matched the name, not the text, so
        # there is nothing in the file to ask ugrep about either.
        spans = (
            {}
            if is_notice or not search.query or search.names
            else match_spans(search, hit)
        )
        # Before setPlainText, not after: replacing the text is itself what
        # makes Qt run the highlighter over the document, so spans set first
        # are painted by that pass instead of needing a second one.
        self._highlighter.set_spans(spans)
        self.text.setPlainText(text)
        self._adopt_matches(spans)

    def clear(self) -> None:
        """Show nothing: no row is selected, or a new search has begun.

        Clearing the pane has to clear what the pane was about, or Prev and
        Next stay live over a document that no longer has the matches they
        would step to — which is why this is the one way to empty it.
        """
        self._enable_row_actions(False)
        self.open_button.setToolTip(OPEN_TIP)
        self.folder_button.setToolTip(FOLDER_TIP)
        self._show_pane(False)
        self.text.clear()
        self._highlighter.set_spans({})
        self._adopt_matches({})

    @property
    def pdf_showing(self) -> bool:
        """Whether the PDF pane, rather than the text pane, is in front."""
        return self._pdf_showing

    def shutdown(self) -> None:
        """Let go of the PDF before the window is torn down around it.

        The search model fills its pages in lazily, so closing the window
        while one is still being searched leaves pdfium walking a document Qt
        is already tearing down. Measured: the process exits on SIGSEGV rather
        than cleanly, which from a terminal is "Segmentation fault" after a
        session that went fine. Clearing first drops the model and the
        document while there is still a window to own them.
        """
        if self.pdf is not None:
            self.pdf.clear()

    # -- stepping through the matches --------------------------------------

    def _adopt_matches(self, spans: dict[int, list[tuple[int, int]]]) -> None:
        """Take on a new file's matches and go to the first one.

        Flattens the spans into reading order — the dict is keyed by line for
        painting, which says nothing about what follows what — and lands on
        match 1. With none, the preview goes to the top instead: long searches
        otherwise leave it scrolled wherever the last file was left.
        """
        self._matches = sorted(
            (line, column, length)
            for line, spots in spans.items()
            for column, length in spots
        )
        self._match_index = -1
        if self._matches:
            self._go_to_match(0)
        else:
            self._highlighter.set_current(None)
            self._update_match_nav()
            self.text.moveCursor(self.text.textCursor().MoveOperation.Start)

    def _adopt_pdf_matches(self) -> None:
        """The PDF pane's equivalent: its matches live in Qt's search model.

        There is no list to flatten — the model is the list, and it is still
        filling in — so this only resets the position and lands on match 1 if
        there is one yet. If there is not, `_on_pdf_count_changed` does it
        when the first one turns up.
        """
        self._matches = []
        self._match_index = -1
        if self._match_total():
            self._go_to_match(0)
        else:
            self._update_match_nav()

    def _on_pdf_count_changed(self) -> None:
        """The PDF's match count grew (or the file changed under it)."""
        if not self._pdf_showing:
            return
        if self._match_index < 0 and self._match_total():
            self._go_to_match(0)
        else:
            self._update_match_nav()

    def _match_total(self) -> int:
        """How many matches the file on screen has, whichever pane shows it."""
        if self._pdf_showing and self.pdf is not None:
            return self.pdf.count()
        return len(self._matches)

    def step_match(self, delta: int) -> None:
        """Move `delta` matches from the current one, wrapping at either end."""
        total = self._match_total()
        if total:
            self._go_to_match((self._match_index + delta) % total)

    def _go_to_match(self, index: int) -> None:
        """Make match `index` current: mark it, scroll to it, and count it."""
        self._match_index = index
        if self._pdf_showing and self.pdf is not None:
            self.pdf.go_to(index)
            self._update_match_nav()
            return
        line, column, _length = self._matches[index]
        self._highlighter.set_current((line, column))
        block = self.text.document().findBlockByNumber(line)
        if block.isValid():
            cursor = QTextCursor(block)
            cursor.setPosition(block.position() + column - 1)
            self.text.setTextCursor(cursor)
            # centerCursor rather than ensureCursorVisible: a match one line
            # from the edge of the viewport is technically visible and still
            # reads as "it did not scroll and I got lucky".
            self.text.centerCursor()
        self._update_match_nav()

    def _update_match_nav(self) -> None:
        """Sync the two buttons and the counter to the current match."""
        total = self._match_total()
        self.prev_button.setEnabled(total > 0)
        self.next_button.setEnabled(total > 0)
        # Blank rather than "0 of 0" when there is nothing to step through: the
        # dim buttons already say so, and a zeroed counter beside them reads as
        # a file that lost its matches rather than one that never had any.
        self.match_label.setText(f"{self._match_index + 1} of {total}" if total else "")
