"""Painting the search hits onto the preview document.

A `QSyntaxHighlighter` rather than `QPlainTextEdit.setExtraSelections()`, which
is the more obvious tool for "highlight these ranges". The difference is when
the work happens: extra selections are all built up front, while a highlighter
formats a block only when that block is laid out. Measured on a file at the
preview's 2 MiB cap — 44k lines, 88k matches — that is ~80ms against ~1.15s,
and scrolling stays flat. It is why nothing here caps the number of matches.

The spans come from ugrep itself (`search.match_spans`), so this module never
looks at the query and never matches anything; it only paints where it is told.
"""

from __future__ import annotations

from PyQt6.QtGui import QColor, QSyntaxHighlighter, QTextCharFormat, QTextDocument

from .style import MATCH_BG, MATCH_FG


class MatchHighlighter(QSyntaxHighlighter):
    """Highlights the match spans it is given on the document it is attached to."""

    def __init__(self, document: QTextDocument) -> None:
        super().__init__(document)
        self._spans: dict[int, list[tuple[int, int]]] = {}
        # Built once rather than per block: highlightBlock runs for every line
        # of the document, and a QTextCharFormat per line is pure waste.
        self._format = QTextCharFormat()
        self._format.setBackground(QColor(MATCH_BG))
        self._format.setForeground(QColor(MATCH_FG))

    def set_spans(self, spans: dict[int, list[tuple[int, int]]]) -> None:
        """Adopt `spans` — 0-based line -> [(1-based column, length)].

        Deliberately does *not* rehighlight. The caller sets the spans and then
        replaces the document's text, and that replacement already triggers a
        pass over every block; rehighlighting here would make it two passes over
        a document that can be 44k lines long.
        """
        self._spans = spans

    def highlightBlock(self, text: str) -> None:
        """Paint one line. Called by Qt, once per block, as blocks are laid out."""
        for column, length in self._spans.get(self.currentBlock().blockNumber(), ()):
            # setFormat clips to the block, so a match that ugrep reports as
            # spanning lines — only reachable through a multi-line regex term —
            # colors its first line instead of bleeding into the next one.
            self.setFormat(column - 1, length, self._format)
