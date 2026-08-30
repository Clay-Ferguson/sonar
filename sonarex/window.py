"""The window: a query row, a folder row, and a split results/preview pane.

Results stream in as ugrep finds them, which is why the list is appended to
rather than filled in one go — and why it is re-sorted once, at the end, when
the full set is finally known (see `_on_search_finished`).
"""

from __future__ import annotations

import os

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QColor, QFont, QFontDatabase, QPalette
from PyQt6.QtWidgets import (
    QApplication,
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
from .help import help_icon, show_help
from .search import EXIT_MATCHED, EXIT_NO_MATCH, SearchRunner
from .viewer import read_for_preview

# The absolute path of the file a row stands for. The row's *text* is only the
# part below the searched folder, so it is not a usable path on its own —
# everything that opens or stats a file must read this role instead.
PATH_ROLE = Qt.ItemDataRole.UserRole

# Results/preview split, as a ratio of the window width. The preview needs the
# room; the list only has to show a path.
SPLIT_LIST = 2
SPLIT_PREVIEW = 3


# How far the window surface is lightened away from the panes sitting on it,
# as a QColor.lighter() percentage. Enough to read as a separate surface,
# not so much that the window starts competing with its own contents.
WINDOW_LIGHTEN = 140

# Below this much separation in lightness, two surfaces read as one.
MIN_SEPARATION = 6

# Header button colors. Search is a muted, desaturated green that reads as the
# primary action without turning into a traffic light; Help is a neutral gray
# so it sits beside it as secondary. Light text works on both, so these are
# defined outright rather than derived from the palette the way the window
# surface is.
SEARCH_BUTTON_BG = "#4a6f45"
HELP_BUTTON_BG = "#5a5a5a"
BUTTON_FG = "#f0f2ef"
SEARCH_BUTTON_PADDING = "8px 24px"

# The icon inside a square header button, as a fraction of the button. A
# QPushButton draws icons at 16px by default whatever its own size, which in a
# button this tall leaves the glyph marooned in the middle and unreadable.
ICON_BUTTON_RATIO = 0.68


def action_button_style(background: str, padding: str = "0px") -> str:
    """Qt stylesheet for a header button of the given background color.

    Styling a button at all opts it out of the native style's rendering —
    including its hover and pressed feedback — so those states have to be
    restated here or the button would look inert to click. Both are derived
    from `background`, so each button's color stays a single value.

    The border is explicit for the same reason: with a stylesheet applied,
    Fusion no longer draws its own frame, and without one the button reads as
    a flat colored rectangle rather than a control.

    `padding` defaults to none, for a button whose size is set explicitly (the
    square icon buttons); padding on top of a fixed size would only squeeze
    the content.
    """
    base = QColor(background)
    return f"""
        QPushButton {{
            background-color: {background};
            color: {BUTTON_FG};
            border: 1px solid {base.darker(125).name()};
            border-radius: 4px;
            padding: {padding};
            font-weight: bold;
        }}
        QPushButton:hover {{ background-color: {base.lighter(115).name()}; }}
        QPushButton:pressed {{ background-color: {base.darker(115).name()}; }}
    """


def tune_palette(app: QApplication) -> None:
    """Lighten the window surface so the list and preview stand out on it.

    Some themes hand Qt the same color for `Window` (the surface behind the
    layout) and `Base` (the background of the list, the preview and the text
    fields). Yaru-dark through the Fusion style is one: both arrive as
    #2a2a2a, so the panes have no edge at all and the whole window reads as
    one flat slab.

    Lightening `Window` — rather than darkening the panes — keeps the panes
    at exactly the color the theme intended for content, and the surround
    becomes the thing that moved.

    Deliberately conditional. In a light theme `Window` is already a gray
    below a white `Base`, and lightening it there would push it *toward*
    white and flatten the very contrast this is meant to create. So the
    change is applied only when it actually increases the separation between
    the two, which also makes it a no-op on a theme that already spaces them
    properly, and on a pure-black palette where `lighter()` cannot move at
    all.
    """
    palette = app.palette()
    window = palette.color(QPalette.ColorRole.Window)
    base = palette.color(QPalette.ColorRole.Base)

    before = abs(window.lightness() - base.lightness())
    if before >= MIN_SEPARATION:
        return  # the theme already distinguishes them; leave it alone

    lightened = window.lighter(WINDOW_LIGHTEN)
    if abs(lightened.lightness() - base.lightness()) <= before:
        return  # lightening would not help (light theme, or a black surface)

    palette.setColor(QPalette.ColorRole.Window, lightened)
    # Buttons keep the theme's own color: against a lightened surround they
    # now read as raised components, which is the point of the change.
    app.setPalette(palette)


def mono_font() -> QFont:
    """The system's fixed-width font at the app's point size.

    Both panes use it: the preview because most of what turns up there is
    source or config, where alignment carries meaning, and the results list
    because a column of paths is far easier to scan when the segments line up
    between rows.

    Taken from QFontDatabase rather than named outright, so this follows
    whatever the desktop is configured to use for monospace. The style hint is
    still set as a fallback, for the case where that lookup hands back
    something proportional.
    """
    font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
    font.setPointSize(UI_POINT_SIZE)
    font.setStyleHint(QFont.StyleHint.Monospace)
    return font


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
        self.query_edit.setPlaceholderText(
            'Search for…   (space = all terms, OR = any, "quoted" = exact phrase, - = exclude)'
        )
        self.query_edit.returnPressed.connect(self.start_search)
        self.search_button = QPushButton("Search")
        self.search_button.setStyleSheet(
            action_button_style(SEARCH_BUTTON_BG, SEARCH_BUTTON_PADDING)
        )
        self.search_button.clicked.connect(self.start_search)
        # So Enter anywhere in the window runs the search rather than
        # activating whichever button happens to have focus.
        self.search_button.setAutoDefault(False)

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
        self.help_button.setFixedSize(row_height, row_height)
        # Scaled to the button rather than left at QPushButton's 16px default.
        glyph = int(row_height * ICON_BUTTON_RATIO)
        self.help_button.setIconSize(QSize(glyph, glyph))

        query_row = QHBoxLayout()
        query_row.addWidget(search_label)
        query_row.addWidget(self.query_edit, 1)
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
        # Pinned here, for the whole life of these results: the same value
        # ugrep is given, so every path it prints is genuinely underneath it
        # and `_display_path` can rely on the prefix matching.
        self._search_root = folder
        self.status.setText(f"Searching {folder}…")
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
        # The root is named here because the rows no longer carry it, and the
        # folder row above is not proof of it — that field stays editable once
        # a search has finished.
        self.status.setText(
            f"{self._match_count} file{'' if self._match_count == 1 else 's'}"
            f" in {self._search_root} — newest first"
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
