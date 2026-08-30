"""The window: a query row, a folder row, and a split results/preview pane.

Results stream in as ugrep finds them, which is why the list is appended to
rather than filled in one go — and why it is re-sorted once, at the end, when
the full set is finally known (see `_on_search_finished`).
"""

from __future__ import annotations

import os

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from . import APP_NAME, UI_POINT_SIZE
from .search import EXIT_MATCHED, EXIT_NO_MATCH, SearchRunner
from .viewer import read_for_preview

# The absolute path of the file a row stands for. The row's own text is the
# same path today, but reading it back from a role rather than from the label
# keeps the display free to change (relative paths, an added match count)
# without breaking the preview.
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

        layout = QVBoxLayout(self)

        # --- query row ---------------------------------------------------
        self.query_edit = QLineEdit()
        self.query_edit.setPlaceholderText(
            'Search for…   (space = all terms, OR = any, "quoted" = exact phrase, - = exclude)'
        )
        self.query_edit.returnPressed.connect(self.start_search)
        self.search_button = QPushButton("Search")
        self.search_button.clicked.connect(self.start_search)
        # So Enter anywhere in the window runs the search rather than
        # activating whichever button happens to have focus.
        self.search_button.setAutoDefault(False)

        query_row = QHBoxLayout()
        query_row.addWidget(self.query_edit, 1)
        query_row.addWidget(self.search_button)
        layout.addLayout(query_row)

        # --- folder row --------------------------------------------------
        self.folder_edit = QLineEdit(folder)
        self.folder_edit.returnPressed.connect(self.start_search)
        browse_button = QPushButton("…")
        browse_button.setFixedWidth(36)
        browse_button.setToolTip("Choose the folder to search")
        browse_button.setAutoDefault(False)
        browse_button.clicked.connect(self._browse)

        folder_row = QHBoxLayout()
        folder_row.addWidget(QLabel("Folder:"))
        folder_row.addWidget(self.folder_edit, 1)
        folder_row.addWidget(browse_button)
        layout.addLayout(folder_row)

        # --- results / preview -------------------------------------------
        self.results = QListWidget()
        self.results.currentItemChanged.connect(self._on_selection_changed)

        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        # A fixed-pitch font because most of what turns up here is source or
        # config, where alignment carries meaning.
        preview_font = QFont("Monospace", UI_POINT_SIZE)
        preview_font.setStyleHint(QFont.StyleHint.Monospace)
        self.preview.setFont(preview_font)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.results)
        splitter.addWidget(self.preview)
        splitter.setStretchFactor(0, SPLIT_LIST)
        splitter.setStretchFactor(1, SPLIT_PREVIEW)
        splitter.setSizes([SPLIT_LIST * 100, SPLIT_PREVIEW * 100])
        layout.addWidget(splitter, 1)

        # --- status ------------------------------------------------------
        # There is no terminal behind this app any more, so everything a
        # search has to say — progress, "no matches", ugrep's own errors —
        # has to land somewhere visible.
        self.status = QLabel("")
        self.status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.status)

        self.query_edit.setFocus()

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
            self.status.setText("Type something to search for.")
            self.query_edit.setFocus()
            return

        folder = self._folder()
        if not os.path.isdir(folder):
            self.status.setText(f"Not a folder: {folder}")
            return

        self.results.clear()
        self.preview.clear()
        self._match_count = 0
        self.status.setText(f"Searching {folder}…")
        self._runner.start(query, folder)

    # -- search callbacks --------------------------------------------------

    def _on_match(self, path: str) -> None:
        item = QListWidgetItem(path)
        item.setData(PATH_ROLE, path)
        self.results.addItem(item)
        self._match_count += 1
        # Cheap enough to do per hit, and it is the only sign the search is
        # still making progress on a long run.
        self.status.setText(f"Searching… {self._match_count} files")

    def _on_search_finished(self, exit_code: int, stderr: str) -> None:
        if exit_code == EXIT_NO_MATCH:
            self.status.setText("No matches.")
            return
        if exit_code != EXIT_MATCHED:
            message = stderr.strip() or f"ugrep exited with status {exit_code}."
            # One line: a multi-line ugrep error would resize the status label
            # and push the splitter around.
            self.status.setText(message.replace("\n", "  "))
            self.status.setToolTip(message)
            return

        self.status.setToolTip("")
        self._sort_by_mtime()
        self.status.setText(
            f"{self._match_count} file{'' if self._match_count == 1 else 's'}"
            " — newest first"
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
            item = QListWidgetItem(path)
            item.setData(PATH_ROLE, path)
            self.results.addItem(item)
        self.results.blockSignals(False)

        self._match_count = self.results.count()
        if selected_path:
            for row in range(self.results.count()):
                if self.results.item(row).data(PATH_ROLE) == selected_path:
                    self.results.setCurrentRow(row)
                    break

    # -- preview -----------------------------------------------------------

    def _on_selection_changed(
        self, current: QListWidgetItem | None, _previous: QListWidgetItem | None
    ) -> None:
        """Show the current row's file.

        Wired to the current *item* rather than to clicks, so walking the
        results with the arrow keys previews each file too.
        """
        if current is None:
            self.preview.clear()
            return
        text, _is_notice = read_for_preview(current.data(PATH_ROLE))
        self.preview.setPlainText(text)
        # Long searches leave the preview scrolled wherever the last file was.
        self.preview.moveCursor(self.preview.textCursor().MoveOperation.Start)

    # -- lifecycle ---------------------------------------------------------

    def closeEvent(self, event) -> None:
        # Without this a search still running when the window closes leaves an
        # orphaned ugrep walking the tree.
        self._runner.stop()
        super().closeEvent(event)
