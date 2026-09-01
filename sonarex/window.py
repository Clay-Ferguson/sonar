"""The window: a query row, a folder row, and a split results/preview pane.

Results stream in as ugrep finds them, which is why the list is appended to
rather than filled in one go — and why it is re-sorted once, at the end, when
the full set is finally known (see `_on_search_finished`).
"""

from __future__ import annotations

import os

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QTextCursor
from PyQt6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from . import APP_NAME
from .help import help_icon, show_help
from .highlight import MatchHighlighter
from .search import EXIT_MATCHED, EXIT_NO_MATCH, SearchRunner, match_spans
from .settings import settings_icon, show_settings
from .style import (
    CONTROL_BAR_PADDING,
    PANE_GAP,
    SPLITTER_HANDLE_WIDTH,
    HELP_BUTTON_BG,
    ICON_BUTTON_RATIO,
    NAV_BUTTON_BG,
    SEARCH_BUTTON_BG,
    SEARCH_BUTTON_PADDING,
    action_button_style,
    apply_scrollbars,
    enlarge_checkbox,
    mono_font,
    selection_button_bg,
    splitter_style,
)
from .viewer import open_in_editor, read_for_preview

# The absolute path of the file a row stands for. The row's *text* is only the
# part below the searched folder, so it is not a usable path on its own —
# everything that opens or stats a file must read this role instead.
PATH_ROLE = Qt.ItemDataRole.UserRole

# Results/preview split, as a ratio of the window width. The preview needs the
# room; the list only has to show a path.
SPLIT_LIST = 2
SPLIT_PREVIEW = 3


class MainWindow(QWidget):
    def __init__(self, folder: str) -> None:
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1100, 700)

        self._runner = SearchRunner(self)
        self._runner.matchFound.connect(self._on_match)
        self._runner.finished.connect(self._on_search_finished)
        self._match_count = 0
        # The folder the current results actually came from, captured when the
        # search starts. Deliberately not read back from the folder row: that
        # stays editable while results are on screen, and a row's path must
        # not shift meaning because someone typed in a field afterwards.
        self._search_root = ""
        # Pinned for the same reason and at the same moment as the root: the
        # query row stays editable while results are on screen, and the
        # highlighting in the preview must keep meaning the search that found
        # these files rather than whatever has since been typed over it.
        self._search_query = ""
        # The current file's matches, flattened out of the spans dict and put in
        # reading order, plus where Prev/Next is parked in that list. A flat
        # list rather than the dict because stepping is what it is for: the dict
        # is keyed for painting a line, this is ordered for walking the file.
        self._matches: list[tuple[int, int, int]] = []
        self._match_index = -1

        layout = QVBoxLayout(self)

        # The two rows are separate layouts, so their labels are pinned to a
        # common width here rather than left to size themselves — otherwise
        # "Search:" and "Folder:" render a few pixels apart in a proportional
        # font and the two fields below start at visibly different offsets.
        # Measured rather than hardcoded, so it survives a font or point-size
        # change and a translation that makes either word longer.
        search_label = QLabel("Search:")
        folder_label = QLabel("Folder:")
        label_width = max(search_label.sizeHint().width(), folder_label.sizeHint().width())
        search_label.setFixedWidth(label_width)
        folder_label.setFixedWidth(label_width)

        # --- query row ---------------------------------------------------
        self.query_edit = QLineEdit()
        self.query_edit.returnPressed.connect(self.start_search)
        self.search_button = QPushButton("Search")
        self.search_button.setStyleSheet(
            action_button_style(SEARCH_BUTTON_BG, SEARCH_BUTTON_PADDING)
        )
        self.search_button.clicked.connect(self.start_search)
        # So Enter anywhere in the window runs the search rather than
        # activating whichever button happens to have focus.
        self.search_button.setAutoDefault(False)

        self.settings_button = QPushButton()
        self.settings_button.setStyleSheet(action_button_style(HELP_BUTTON_BG))
        gear = settings_icon()
        if gear.isNull():
            # No icon theme has a gear glyph: draw the character instead,
            # rather than an empty square.
            self.settings_button.setText("⚙")
        else:
            self.settings_button.setIcon(gear)
        self.settings_button.setToolTip("Search settings (include / exclude patterns)")
        self.settings_button.setAutoDefault(False)
        # Nothing to refresh afterwards: the config is re-read at the start of
        # every search, so a saved change applies from the next Search press.
        self.settings_button.clicked.connect(lambda: show_settings(self))

        self.help_button = QPushButton()
        self.help_button.setStyleSheet(action_button_style(HELP_BUTTON_BG))
        icon = help_icon()
        if icon.isNull():
            # No icon theme has a help glyph (a bare desktop install): show the
            # character instead, rather than an empty square.
            self.help_button.setText("?")
        else:
            self.help_button.setIcon(icon)
        self.help_button.setToolTip("Query syntax help")
        self.help_button.setAutoDefault(False)
        self.help_button.clicked.connect(lambda: show_help(self))

        # The padded Search button sets the height for every control in both
        # rows: a stock QLineEdit is shorter, and mixing the two leaves the
        # fields floating with a gap above and below them. Taken from the
        # button's own size hint rather than hardcoded, so adjusting
        # SEARCH_BUTTON_PADDING resizes the whole header together.
        row_height = self.search_button.sizeHint().height()
        self.query_edit.setFixedHeight(row_height)
        # Scaled to the button rather than left at QPushButton's 16px default.
        glyph = int(row_height * ICON_BUTTON_RATIO)
        for button in (self.settings_button, self.help_button):
            button.setFixedSize(row_height, row_height)
            button.setIconSize(QSize(glyph, glyph))

        query_row = QHBoxLayout()
        query_row.addWidget(search_label)
        query_row.addWidget(self.query_edit, 1)
        query_row.addWidget(self.settings_button)
        query_row.addWidget(self.help_button)
        query_row.addWidget(self.search_button)
        layout.addLayout(query_row)

        # --- folder row --------------------------------------------------
        self.folder_edit = QLineEdit(folder)
        self.folder_edit.setFixedHeight(row_height)
        self.folder_edit.returnPressed.connect(self.start_search)
        browse_button = QPushButton("…")
        # Square, at the shared row height: with only an ellipsis on it there
        # is no text width to size to, so it would otherwise be a lone stubby
        # control at the end of an otherwise uniform header.
        browse_button.setFixedSize(row_height, row_height)
        browse_button.setToolTip("Choose the folder to search")
        browse_button.setAutoDefault(False)
        browse_button.clicked.connect(self._browse)

        folder_row = QHBoxLayout()
        folder_row.addWidget(folder_label)
        folder_row.addWidget(self.folder_edit, 1)
        folder_row.addWidget(browse_button)
        layout.addLayout(folder_row)

        # --- results / preview -------------------------------------------
        self.results = QListWidget()
        self.results.setFont(mono_font())
        self.results.currentItemChanged.connect(self._on_selection_changed)

        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.preview.setFont(mono_font())
        # The gutter, taken out of the document rather than the widget. A
        # viewport margin looks like the same thing and is not: that strip is
        # outside the viewport and gets painted in the window color, so it
        # comes out as a gray band beside the divider instead of a gutter.
        # The document's own margin is inside the text area, on its Base
        # background — which is what makes it read as part of the pane. It
        # applies to all four sides; the left is the one being asked for and
        # the rest is breathing room the preview was short of anyway.
        self.preview.document().setDocumentMargin(PANE_GAP)
        # Attached once, to the document, and fed new spans per file. The
        # document survives setPlainText, so this outlives every preview.
        self._highlighter = MatchHighlighter(self.preview.document())

        # --- the preview's own control bar -------------------------------
        # Sits inside the right-hand pane rather than under the whole window,
        # so it reads as belonging to the file being shown above it — and so
        # dragging the splitter moves it with the pane it controls.
        self.open_button = QPushButton("Open")
        self.open_button.setStyleSheet(
            action_button_style(selection_button_bg(), CONTROL_BAR_PADDING)
        )
        self.open_button.setToolTip("Open this file in the editor")
        self.open_button.setAutoDefault(False)
        # Nothing is selected at startup, and "Open" with no file would be a
        # button that silently does nothing.
        self.open_button.setEnabled(False)
        self.open_button.clicked.connect(self._open_selected)

        # Prev/Next step between individual matches rather than between lines:
        # the spans are exact, so a line carrying three hits is three stops.
        # Both wrap around, which is what makes them usable without also
        # having to watch the counter to know when to stop.
        self.prev_button = self._nav_button("Prev", "Go to the previous match")
        self.prev_button.clicked.connect(lambda: self._step_match(-1))
        self.next_button = self._nav_button("Next", "Go to the next match")
        self.next_button.clicked.connect(lambda: self._step_match(1))

        # Says which match of how many, because the highlight alone cannot:
        # every match looks the same until one of them is the current one, and
        # off screen even that is invisible.
        self.match_label = QLabel()
        self.match_label.setToolTip("The current match, and how many this file has")

        self.wrap_check = QCheckBox("Word Wrap")
        enlarge_checkbox(self.wrap_check)
        self.wrap_check.setChecked(True)  # matches the pane's initial mode
        self.wrap_check.toggled.connect(self._set_word_wrap)

        control_bar = QHBoxLayout()
        control_bar.setContentsMargins(PANE_GAP, 0, 0, 0)
        control_bar.addWidget(self.open_button)
        control_bar.addWidget(self.prev_button)
        control_bar.addWidget(self.next_button)
        control_bar.addWidget(self.match_label)
        control_bar.addStretch(1)
        control_bar.addWidget(self.wrap_check)

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        # Flush with the splitter edge: the panel is a container, not a frame
        # of its own, and default margins would inset the preview from the
        # results list beside it. The gutter that keeps the contents off the
        # divider is inside the preview and the control bar instead, so it is
        # drawn in their own background rather than the window's.
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.addWidget(self.preview, 1)
        right_layout.addLayout(control_bar)

        # Both panes get the wider bars; applied per scroll bar so the list
        # and the preview themselves keep native rendering.
        for area in (self.results, self.preview):
            apply_scrollbars(area)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(SPLITTER_HANDLE_WIDTH)
        splitter.setStyleSheet(splitter_style())
        splitter.addWidget(self.results)
        splitter.addWidget(right_panel)
        splitter.setStretchFactor(0, SPLIT_LIST)
        splitter.setStretchFactor(1, SPLIT_PREVIEW)
        splitter.setSizes([SPLIT_LIST * 100, SPLIT_PREVIEW * 100])
        layout.addWidget(splitter, 1)

        self.query_edit.setFocus()

    # -- reporting ----------------------------------------------------------

    def _set_title(self, note: str = "") -> None:
        """Put `note` in the title bar, or clear it back to the app name.

        With no status bar, the title is where a search says how it is going.
        It costs no layout space, and it is the one piece of window furniture
        that is always visible — including when SonarEx is a background window
        someone is glancing at from another app.
        """
        self.setWindowTitle(f"{APP_NAME} — {note}" if note else APP_NAME)

    def _report_problem(self, message: str) -> None:
        """Show something that actually went wrong.

        A dialog rather than a quiet line somewhere: these are rare, they
        follow an explicit action the user just took, and the two that matter
        most — a rejected regex and a missing editor — are long enough that a
        truncated title would hide the part that says what to fix.
        """
        QMessageBox.warning(self, f"{APP_NAME}", message)

    # -- actions -----------------------------------------------------------

    def _browse(self) -> None:
        chosen = QFileDialog.getExistingDirectory(
            self, f"{APP_NAME} — folder to search", self._folder()
        )
        if chosen:
            self.folder_edit.setText(chosen)

    def _folder(self) -> str:
        """The folder row as an absolute path, with '~' expanded."""
        return os.path.abspath(os.path.expanduser(self.folder_edit.text().strip()))

    def start_search(self) -> None:
        query = self.query_edit.text().strip()
        if not query:
            # Nothing to report: an empty query field is its own explanation,
            # so this just puts the cursor where the user needs to type.
            self.query_edit.setFocus()
            return

        folder = self._folder()
        if not os.path.isdir(folder):
            self._report_problem(f"Not a folder:\n\n{folder}")
            return

        self.results.clear()
        self.preview.clear()
        self._match_count = 0
        # Pinned here, for the whole life of these results: the same value
        # ugrep is given, so every path it prints is genuinely underneath it
        # and `_display_path` can rely on the prefix matching.
        self._search_root = folder
        self._search_query = query
        self._set_title("Searching…")
        self._runner.start(query, folder)

    # -- rows ---------------------------------------------------------------

    def _display_path(self, path: str) -> str:
        """`path` as shown in the list: relative to the searched folder.

        Every hit lives under the folder that was searched, so repeating that
        prefix on every row costs width and tells the reader nothing. What
        distinguishes one result from another is the part below it.

        `os.path.relpath` does the work rather than string surgery on the
        prefix: it understands path structure, so it can't sever a name
        mid-segment the way `str.removeprefix` would turn `/tmp/foobar` into
        `bar` when the root is `/tmp/foo`.

        Falls back to the absolute path whenever a relative one would be
        misleading — no root recorded yet, a hit somewhere outside the root
        (which would come out as a chain of `..`), or the ValueError relpath
        raises when two paths share no common base at all.
        """
        if not self._search_root:
            return path
        try:
            relative = os.path.relpath(path, self._search_root)
        except ValueError:
            return path
        if relative.startswith(os.pardir):
            return path
        return relative

    def _make_item(self, path: str) -> QListWidgetItem:
        """A row for `path`: relative label, absolute path underneath.

        The absolute path lives in `PATH_ROLE`, and everything that opens or
        stats a file reads it from there — never from the row's text, which is
        now only part of a path and is a display detail besides.
        """
        item = QListWidgetItem(self._display_path(path))
        item.setData(PATH_ROLE, path)
        # The full path stays reachable, since the row no longer shows it.
        item.setToolTip(path)
        return item

    # -- search callbacks --------------------------------------------------

    def _on_match(self, path: str) -> None:
        self.results.addItem(self._make_item(path))
        self._match_count += 1
        # Cheap enough to do per hit, and it is the only sign the search is
        # still making progress on a long run.
        self._set_title(f"Searching… {self._match_count} files")

    def _on_search_finished(self, exit_code: int, stderr: str) -> None:
        if exit_code == EXIT_NO_MATCH:
            self._set_title("No matches")
            return
        if exit_code != EXIT_MATCHED:
            message = stderr.strip() or f"ugrep exited with status {exit_code}."
            self._set_title()
            self._report_problem(message)
            return

        self._sort_by_mtime()
        # The root is named because the rows no longer carry it, and the folder
        # row above is not proof of it — that field stays editable once a
        # search has finished.
        self._set_title(
            f"{self._match_count} file{'' if self._match_count == 1 else 's'}"
            f" in {self._search_root}"
        )

    def _sort_by_mtime(self) -> None:
        """Re-order the finished list newest-modified-first.

        ugrep emits hits in directory-walk order, and its own --sort=rchanged
        sorts only within each directory, so a tree-wide ordering has to be
        done here — and only once ugrep has exited, since the newest file may
        be the last one found.

        Files deleted since the search are dropped rather than sorted to one
        end: they can no longer be previewed, so a row for one is a dead
        entry. Any other failure leaves ugrep's ordering untouched, which is
        a worse order but never a wrong one.
        """
        if self.results.count() < 2:
            return

        selected = self.results.currentItem()
        selected_path = selected.data(PATH_ROLE) if selected else None

        dated: list[tuple[float, str]] = []
        try:
            for row in range(self.results.count()):
                path = self.results.item(row).data(PATH_ROLE)
                try:
                    dated.append((os.stat(path).st_mtime, path))
                except OSError:
                    continue  # vanished since the search; drop the row
        except Exception as exc:  # pragma: no cover - defensive
            print(f"SonarEx: could not sort results: {exc}")
            return

        dated.sort(key=lambda pair: pair[0], reverse=True)

        # Rebuilding the rows resets the selection, so it is restored below;
        # without that, re-sorting at the end of a search would silently clear
        # a preview the user was already reading.
        self.results.blockSignals(True)
        self.results.clear()
        for _, path in dated:
            self.results.addItem(self._make_item(path))
        self.results.blockSignals(False)

        self._match_count = self.results.count()
        # Signals were blocked across the rebuild, so the button's state was
        # not refreshed by the clear; put it back in step with the list.
        self.open_button.setEnabled(False)
        if selected_path:
            for row in range(self.results.count()):
                if self.results.item(row).data(PATH_ROLE) == selected_path:
                    self.results.setCurrentRow(row)
                    break

    # -- preview -----------------------------------------------------------

    def _set_word_wrap(self, wrap: bool) -> None:
        """Toggle wrapping in the preview pane.

        Deliberately not persisted: it is a per-look preference about the file
        on screen right now, and it starts on because most of what turns up in
        a content search is prose or long lines that would otherwise need
        horizontal scrolling to read at all.
        """
        self.preview.setLineWrapMode(
            QPlainTextEdit.LineWrapMode.WidgetWidth
            if wrap
            else QPlainTextEdit.LineWrapMode.NoWrap
        )

    def _open_selected(self) -> None:
        """Hand the selected file to the editor.

        The path comes from PATH_ROLE, not the row's text, which is only the
        part below the search root.
        """
        item = self.results.currentItem()
        if item is None:
            return
        error = open_in_editor(item.data(PATH_ROLE))
        if error:
            self._report_problem(error)

    def _nav_button(self, text: str, tip: str) -> QPushButton:
        """One of the two match-stepping buttons, styled alike."""
        button = QPushButton(text)
        button.setStyleSheet(action_button_style(NAV_BUTTON_BG, CONTROL_BAR_PADDING))
        button.setToolTip(tip)
        button.setAutoDefault(False)
        # Disabled until a file with matches is on screen, for the same reason
        # Open is: a button that silently does nothing is worse than a dim one.
        button.setEnabled(False)
        return button

    def _on_selection_changed(
        self, current: QListWidgetItem | None, _previous: QListWidgetItem | None
    ) -> None:
        """Show the current row's file.

        Wired to the current *item* rather than to clicks, so walking the
        results with the arrow keys previews each file too.
        """
        # Open acts on the current row, so it is live exactly when one exists.
        self.open_button.setEnabled(current is not None)
        if current is None:
            self.preview.clear()
            # Clearing the pane has to clear what the pane was about, or Prev
            # and Next stay live over a document that no longer has the matches
            # they would step to.
            self._highlighter.set_spans({})
            self._adopt_matches({})
            return
        path = current.data(PATH_ROLE)
        text, is_notice = read_for_preview(path)
        # A notice — binary, too large, unreadable — is this app's own words
        # rather than the file, so there is nothing in it ugrep matched and its
        # line numbers mean nothing. Asking ugrep about it would also be asking
        # about a file that by definition cannot be shown.
        spans = (
            {}
            if is_notice or not self._search_query
            else match_spans(self._search_query, path)
        )
        # Before setPlainText, not after: replacing the text is itself what
        # makes Qt run the highlighter over the document, so spans set first
        # are painted by that pass instead of needing a second one.
        self._highlighter.set_spans(spans)
        self.preview.setPlainText(text)
        self._adopt_matches(spans)

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
            self.preview.moveCursor(self.preview.textCursor().MoveOperation.Start)

    def _step_match(self, delta: int) -> None:
        """Move `delta` matches from the current one, wrapping at either end."""
        if self._matches:
            self._go_to_match((self._match_index + delta) % len(self._matches))

    def _go_to_match(self, index: int) -> None:
        """Make match `index` current: mark it, scroll to it, and count it."""
        self._match_index = index
        line, column, _length = self._matches[index]
        self._highlighter.set_current((line, column))
        block = self.preview.document().findBlockByNumber(line)
        if block.isValid():
            cursor = QTextCursor(block)
            cursor.setPosition(block.position() + column - 1)
            self.preview.setTextCursor(cursor)
            # centerCursor rather than ensureCursorVisible: a match one line
            # from the edge of the viewport is technically visible and still
            # reads as "it did not scroll and I got lucky".
            self.preview.centerCursor()
        self._update_match_nav()

    def _update_match_nav(self) -> None:
        """Sync the two buttons and the counter to the current match."""
        total = len(self._matches)
        self.prev_button.setEnabled(total > 0)
        self.next_button.setEnabled(total > 0)
        # Blank rather than "0 of 0" when there is nothing to step through: the
        # dim buttons already say so, and a zeroed counter beside them reads as
        # a file that lost its matches rather than one that never had any.
        self.match_label.setText(f"{self._match_index + 1} of {total}" if total else "")

    # -- lifecycle ---------------------------------------------------------

    def closeEvent(self, event) -> None:
        # Without this a search still running when the window closes leaves an
        # orphaned ugrep walking the tree.
        self._runner.stop()
        super().closeEvent(event)
