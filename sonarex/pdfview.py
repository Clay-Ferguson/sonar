"""The PDF half of the preview pane.

A PDF is a binary file, so the text pane can only ever name it — but Sonar
searches inside PDFs (ugrep extracts their text through `pdftotext`), so they
turn up in the results like anything else, and being told "binary file" about
a hit you just searched for is not an answer. Qt renders them instead:
`QtPdf` ships in the PyQt6 wheel with its own pdfium, so this costs no new
dependency and no install step.

Every use of those bindings is in this module, and the import is guarded, so
an environment without them degrades to the old binary notice rather than
failing to start — the same rule the config loader follows.

The window drives this through three things: `show_file()`, `count()` and
`go_to()`, which is all Prev/Next needs to work over a PDF exactly as it does
over text. The matches themselves are marked by `QPdfView` in its own colors:
they are not configurable, and painting them here instead — which needs a
page-to-viewport mapping Qt does not expose — was more code than the
difference was worth.
"""

from __future__ import annotations

from PyQt6.QtCore import QPointF, pyqtSignal

try:
    from PyQt6.QtPdf import QPdfDocument, QPdfSearchModel
    from PyQt6.QtPdfWidgets import QPdfView

    PDF_AVAILABLE = True
except ImportError:  # pragma: no cover - depends on how PyQt6 was installed
    PDF_AVAILABLE = False

from windowchrome import apply_scrollbars

# The gap between pages in the continuous scroll, in pixels. Qt's default is
# 3, which reads as a seam rather than a page break.
PAGE_SPACING = 12


if PDF_AVAILABLE:

    class PdfPane(QPdfView):
        """A scrolling view of one PDF, with the query's matches marked.

        The document, the view and the search model are made once and reused
        for every file: loading a new path into the same document is what
        `show_file()` does, so nothing here is rebuilt per selection.

        Defined inside the guard because it cannot exist without `QPdfView` to
        derive from; `PDF_AVAILABLE` is what the window checks before asking
        for one.
        """

        # Re-emitted from the search model. The model searches pages lazily,
        # so the count climbs for a second or so after a big document opens
        # (measured: 1 -> 16 -> 26 -> 44 across ~1s on a 26-page file). The
        # window listens so the counter and the buttons follow it up.
        matchCountChanged = pyqtSignal()

        def __init__(self, parent=None) -> None:
            super().__init__(parent)
            self._document = QPdfDocument(self)
            self.setDocument(self._document)
            # Continuous scrolling rather than one page at a time: a match is
            # found by scrolling to it, and SinglePage would make every hit on
            # another page a page-turn first.
            self.setPageMode(QPdfView.PageMode.MultiPage)
            self.setZoomMode(QPdfView.ZoomMode.FitToWidth)
            self.setPageSpacing(PAGE_SPACING)

            self._search = QPdfSearchModel(self)
            self._search.setDocument(self._document)
            self.setSearchModel(self._search)
            self._search.countChanged.connect(self.matchCountChanged)

            # A QAbstractScrollArea like the list and the text preview, so it
            # takes the same wider bars.
            apply_scrollbars(self)

        # -- what the window calls ------------------------------------------

        def show_file(self, path: str, term: str | None) -> str | None:
            """Display `path`, marking `term`. None, or a message on failure.

            An error comes back as a string rather than an exception for the
            same reason `read_for_preview()` never raises: this runs inside a
            selection-changed callback, and the window shows the message in
            the text pane instead of the document.

            The search string is cleared before the load, not after: the hits
            on screen belong to the file being replaced, and a model left
            pointing at them is briefly a model describing the wrong document.
            """
            self._search.setSearchString("")
            self._document.close()

            error = self._document.load(path)
            if error != QPdfDocument.Error.None_:
                self._document.close()
                return f"This PDF cannot be displayed:\n\n{path}\n\n{_reason(error)}"

            # Back to the top for the new file. Without it the view keeps the
            # scroll position of the previous document, which on a shorter one
            # opens somewhere in the middle of nowhere.
            self.pageNavigator().jump(0, QPointF(0, 0))
            if term:
                self._search.setSearchString(term)
            return None

        def clear(self) -> None:
            """Let go of the current document — nothing is selected."""
            self._search.setSearchString("")
            self._document.close()

        def count(self) -> int:
            """How many matches are known *so far* (see `matchCountChanged`)."""
            return self._search.count()

        def go_to(self, index: int) -> None:
            """Scroll to match `index` and make it the current one.

            Two steps, because they are two things:
            `setCurrentSearchResultIndex()` only marks the result — it does
            not move the view (measured: the scroll bar stays put for a hit
            thirteen pages down) — and the jump is what scrolls. The index is
            re-checked against the model because the count is still growing
            while an early click is possible.
            """
            if not 0 <= index < self._search.count():
                return
            link = self._search.resultAtIndex(index)
            if link.isValid():
                self.pageNavigator().jump(link.page(), link.location())
            self.setCurrentSearchResultIndex(index)

    def _reason(error) -> str:
        """A sentence for a `QPdfDocument.Error`.

        Qt's own name for it would be shown otherwise ("Error.IncorrectPassword"),
        which says what happened only if you already know Qt. The password and
        format cases are the two a user can act on, so they say what to do.
        """
        errors = QPdfDocument.Error
        return {
            errors.FileNotFound: "The file could not be opened.",
            errors.InvalidFileFormat: "It is not a valid PDF.",
            errors.IncorrectPassword: (
                "It is password-protected. Use the Open button to view it in "
                "the system's PDF viewer, which can ask for the password."
            ),
            errors.UnsupportedSecurityScheme: (
                "It uses a security scheme this viewer does not support. Use "
                "the Open button to view it in the system's PDF viewer."
            ),
            errors.DataNotYetAvailable: "It could not be read.",
        }.get(error, "It could not be read.")

else:  # pragma: no cover - depends on how PyQt6 was installed

    PdfPane = None  # type: ignore[assignment,misc]
