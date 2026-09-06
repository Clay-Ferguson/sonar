"""The window: a query row, a folder row, and a split results/preview pane.

Results stream in as ugrep finds them, which is why the list is appended to
rather than filled in one go — and why it is re-sorted once, at the end, when
the full set is finally known (see `_on_search_finished`).
"""

from __future__ import annotations

import os

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction, QTextCursor
from PyQt6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QStyle,
    QVBoxLayout,
    QWidget,
)
from windowchrome import apply_scrollbars, close_markdown_windows

from . import APP_NAME
from .archive import Hit, member_levels, parse_result_line
from .config import search_depth, search_fuzzy
from .help import show_query_syntax, show_user_guide
from .highlight import MatchHighlighter
from .pdfview import PDF_AVAILABLE, PdfPane
from .search import (
    EXIT_MATCHED,
    EXIT_NO_MATCH,
    SearchRunner,
    literal_query_term,
    match_spans,
    search_error,
)
from .settings import show_settings
from .style import (
    CONTROL_BAR_PADDING,
    NAV_BUTTON_BG,
    NAV_GROUP_SPACING,
    PANE_GAP,
    PRIMARY_BUTTON_BG,
    SECONDARY_BUTTON_BG,
    SPLITTER_HANDLE_WIDTH,
    action_button,
    enlarge_checkbox,
    icon_button,
    menu_style,
    mono_font,
    results_list_style,
    selection_button_bg,
    splitter_style,
)
from .viewer import (
    cleanup_temp_files,
    is_pdf,
    open_folder,
    open_in_editor,
    read_for_preview,
)

# The `Hit` a row stands for: an absolute path, plus a name inside it when the
# result came out of an archive. The row's *text* is only the part below the
# searched folder, so it is not a usable path on its own — everything that
# opens, stats or previews a file must read this role instead.
#
# One role rather than a path role and a member role beside it: they are never
# meaningful apart, and two roles would have to be kept in step everywhere a
# row is built, which `_sort_by_mtime` does all over again from scratch.
HIT_ROLE = Qt.ItemDataRole.UserRole

# The Open button's tooltip, which changes with the selection: a hit inside an
# archive opens a copy, and that is worth saying before the click rather than
# after the user has edited one and found the archive unchanged.
# What separates an archive from what was found inside it, in a row's label.
# Spaced, because the names on either side of it are paths full of punctuation
# already and an unspaced arrow disappears into them.
ARROW = " → "

OPEN_TIP = "Open this file in the editor"
OPEN_TIP_ARCHIVED = (
    "Open a read-only copy extracted from the archive.\n"
    "Edits to it do not go back into the archive."
)

# The folder button's, which changes with the selection for the same reason
# Open's does: for a hit inside an archive the folder that opens is the one
# holding the archive, and that is worth saying before the click.
FOLDER_TIP = "Show this file's folder in the file manager"
FOLDER_TIP_ARCHIVED = "Show the folder holding the archive in the file manager"

# Results/preview split, as a ratio of the window width. The preview needs the
# room; the list only has to show a path.
SPLIT_LIST = 2
SPLIT_PREVIEW = 3


class MainWindow(QMainWindow):
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
        # Archive nesting, 0 when archives are off. Pinned at the start of a
        # search alongside the root and the query, because it decides how a
        # result is *read* as well as how it was found: changing the setting
        # mid-session must not turn the rows already on screen into files
        # nothing can open, and a member found three levels down can only be
        # re-opened at the depth that reached it.
        self._search_depth = 0
        # How many characters a match may differ by, 0 when off. Pinned for the
        # same reason as the depth and with the same consequence: the preview
        # re-runs ugrep to find out where to paint, and a run without the
        # setting that found the file marks nothing in it.
        self._search_fuzzy = 0
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

        self._build_menus()

        # A QMainWindow so the menu bar is the window's own — Qt places it
        # under the title bar, or hands it to the desktop's global menu where
        # there is one. Everything else lives on a plain central widget, which
        # is what the layout below fills.
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

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
        # Enter anywhere in the window runs the search rather than activating
        # whichever button holds focus — `action_button()` clears autoDefault
        # on every button it makes, which is what leaves that path clear.
        self.search_button = action_button("Search", PRIMARY_BUTTON_BG)
        self.search_button.clicked.connect(self.start_search)

        # The padded Search button sets the height for every control in both
        # rows: a stock QLineEdit is shorter, and mixing the two leaves the
        # fields floating with a gap above and below them. Taken from the
        # button's own size hint rather than hardcoded, so adjusting
        # ACTION_BUTTON_PADDING resizes the whole header together.
        row_height = self.search_button.sizeHint().height()
        self.query_edit.setFixedHeight(row_height)

        query_row = QHBoxLayout()
        query_row.addWidget(search_label)
        query_row.addWidget(self.query_edit, 1)
        query_row.addWidget(self.search_button)
        layout.addLayout(query_row)

        # --- folder row --------------------------------------------------
        self.folder_edit = QLineEdit(folder)
        self.folder_edit.setFixedHeight(row_height)
        self.folder_edit.returnPressed.connect(self.start_search)
        # Square, at the shared row height: with only an ellipsis on it there
        # is no text width to size to, so it would otherwise be a lone stubby
        # control at the end of an otherwise uniform header. The size is fixed,
        # so it takes no padding — padding inside a fixed size only squeezes
        # the label.
        browse_button = action_button("…", SECONDARY_BUTTON_BG, "0px")
        browse_button.setFixedSize(row_height, row_height)
        browse_button.setToolTip("Choose the folder to search")
        browse_button.clicked.connect(self._browse)

        folder_row = QHBoxLayout()
        folder_row.addWidget(folder_label)
        folder_row.addWidget(self.folder_edit, 1)
        folder_row.addWidget(browse_button)
        layout.addLayout(folder_row)

        # --- results / preview -------------------------------------------
        self.results = QListWidget()
        self.results.setFont(mono_font())
        # Rows come out packed tight against each other otherwise: Qt sizes a
        # list row to its text and nothing more, which reads as a block of
        # paths rather than a list of them.
        self.results.setStyleSheet(results_list_style())
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

        # The other preview: a rendered PDF, for the files the text pane can
        # only describe. None when the QtPdf bindings are missing, in which
        # case a PDF falls back to that description — the app still runs.
        self._pdf = PdfPane() if PDF_AVAILABLE else None
        self._panes = QStackedWidget()
        self._panes.addWidget(self.preview)
        if self._pdf is not None:
            self._panes.addWidget(self._pdf)
            # The model searches pages lazily, so the number of matches climbs
            # for about a second after a long PDF opens. The counter has to
            # follow it up rather than freeze on whatever it was at load.
            self._pdf.matchCountChanged.connect(self._on_pdf_count_changed)

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
        self.open_button.clicked.connect(self._open_selected)

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
        self.folder_button.clicked.connect(self._open_selected_folder)

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
        self.prev_button.clicked.connect(lambda: self._step_match(-1))
        self.next_button = self._nav_button(
            QStyle.StandardPixmap.SP_ArrowRight, "Go to the next match"
        )
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

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        # Flush with the splitter edge: the panel is a container, not a frame
        # of its own, and default margins would inset the preview from the
        # results list beside it. The gutter that keeps the contents off the
        # divider is inside the preview and the control bar instead, so it is
        # drawn in their own background rather than the window's.
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.addWidget(self._panes, 1)
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

    # -- menus --------------------------------------------------------------

    def _build_menus(self) -> None:
        """Two menus: File, with Exit on it, and Options, with the two dialogs.

        These were icon buttons in the query row; a menu is where a desktop
        app puts things that open a dialog and are not part of the search
        itself. Labels only — the theme's gear and question mark said nothing
        the words do not, and two items of plain text read as one list.
        """
        bar = self.menuBar()
        # Padding only, so the titles and items are comfortable targets
        # without the menu font growing away from the rest of the window.
        bar.setStyleSheet(menu_style())

        file_menu = bar.addMenu("&File")
        exit_action = QAction("E&xit", self)
        exit_action.setStatusTip("Close Sonar")
        # close(), not QApplication.quit(): closeEvent is what clears the PDF
        # pane and removes the extracted temp copies, and quit() skips it.
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        options = bar.addMenu("&Options")

        settings_action = QAction("&Settings", self)
        settings_action.setStatusTip("Search settings (include / exclude patterns)")
        # Nothing to refresh afterwards: the config is re-read at the start of
        # every search, so a saved change applies from the next Search press.
        settings_action.triggered.connect(lambda: show_settings(self))
        options.addAction(settings_action)

        # Both documents sit on Options directly rather than under a Help
        # submenu: three items is not enough to be worth a second level, and
        # a submenu costs a keystroke and a hover on every visit.
        syntax_action = QAction("&Query Syntax", self)
        syntax_action.setStatusTip("What can go in the query field")
        syntax_action.triggered.connect(lambda: show_query_syntax(self))
        options.addAction(syntax_action)

        guide_action = QAction("&User Guide", self)
        guide_action.setStatusTip("Everything Sonar does")
        guide_action.triggered.connect(lambda: show_user_guide(self))
        options.addAction(guide_action)

    # -- reporting ----------------------------------------------------------

    def _set_title(self, note: str = "") -> None:
        """Put `note` in the title bar, or clear it back to the app name.

        With no status bar, the title is where a search says how it is going.
        It costs no layout space, and it is the one piece of window furniture
        that is always visible — including when Sonar is a background window
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
        self._show_pane(False)
        self.preview.clear()
        self._match_count = 0
        # Pinned here, for the whole life of these results: the same value
        # ugrep is given, so every path it prints is genuinely underneath it
        # and `_display_path` can rely on the prefix matching.
        self._search_root = folder
        self._search_query = query
        self._search_depth = search_depth()
        self._search_fuzzy = search_fuzzy()
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

    def _make_item(self, hit: Hit) -> QListWidgetItem:
        """A row for `hit`: relative label, the whole `Hit` underneath.

        The `Hit` lives in `HIT_ROLE`, and everything that opens, stats or
        previews a file reads it from there — never from the row's text, which
        is now only part of a path and is a display detail besides.

        A hit inside an archive is labelled `archive.zip → name`, with the
        arrow rather than ugrep's own `archive.zip{name}` because the braces
        read as part of a filename at a glance and the arrow does not. Nesting
        just adds arrows — `L1.zip → L2.tar.gz → inner.txt` — since ugrep joins
        those levels with a colon, which reads as no boundary at all. The
        tooltip is the same chain one level per line, indented, which is the
        one place the full archive path and every name below it are visible.
        """
        label = self._display_path(hit.path)
        tooltip = hit.path
        if hit.member:
            levels = member_levels(hit.member, self._search_depth)
            label = ARROW.join([label, *levels])
            tooltip = "\n".join(
                [hit.path] + [f"{'  ' * (n + 1)}{name}" for n, name in enumerate(levels)]
            )
        item = QListWidgetItem(label)
        item.setData(HIT_ROLE, hit)
        # The full path stays reachable, since the row no longer shows it.
        item.setToolTip(tooltip)
        return item

    # -- search callbacks --------------------------------------------------

    def _on_match(self, line: str) -> None:
        self.results.addItem(self._make_item(parse_result_line(line)))
        self._match_count += 1
        # Cheap enough to do per hit, and it is the only sign the search is
        # still making progress on a long run.
        self._set_title(f"Searching… {self._match_count} files")

    def _on_search_finished(self, exit_code: int, stderr: str) -> None:
        """Report a real failure; otherwise settle the list and the title.

        The exit status alone cannot decide this. ugrep uses 2 both for a
        search that failed and for one that merely skipped a file it could not
        open — and which of those an encrypted archive counts as varies by
        build: 7.5.0 on one machine exits 0 for a tree holding one, while
        another exits 2 for the same tree. Taking 2 at face value therefore
        raised a modal dialog on every search that so much as passed a
        password-protected zip, which is exactly what archive searching was
        asked not to do. `search_error` reads the stderr instead and keeps
        only what is not a per-file note.

        The count rather than EXIT_NO_MATCH decides "No matches", for the same
        reason: a fruitless search over a tree with an unreadable file in it
        exits 2, not 1.
        """
        problem = ""
        if exit_code not in (EXIT_MATCHED, EXIT_NO_MATCH):
            problem = search_error(stderr)
            # An unexplained failure is still a failure: only silence a
            # non-zero status when ugrep said why and every reason was a file
            # it skipped.
            if not problem and not stderr.strip():
                problem = f"ugrep exited with status {exit_code}."
        if problem:
            self._set_title()
            self._report_problem(problem)
            return

        if not self._match_count:
            self._set_title("No matches")
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

        The time stat'd for a hit inside an archive is the archive's own, so
        every member of one shares a key. `sort` is stable, which is what
        keeps them in the order ugrep found them and grouped under the archive
        they came from rather than shuffled among each other.
        """
        if self.results.count() < 2:
            return

        selected = self.results.currentItem()
        selected_hit = selected.data(HIT_ROLE) if selected else None

        dated: list[tuple[float, Hit]] = []
        try:
            for row in range(self.results.count()):
                hit = self.results.item(row).data(HIT_ROLE)
                try:
                    dated.append((os.stat(hit.path).st_mtime, hit))
                except OSError:
                    continue  # vanished since the search; drop the row
        except Exception as exc:  # pragma: no cover - defensive
            print(f"Sonar: could not sort results: {exc}")
            return

        # By the time only: sorting on the whole tuple would fall through to
        # comparing hits whenever two share a time, which is now the ordinary
        # case rather than a tie-break, and would scatter an archive's members
        # into alphabetical order.
        dated.sort(key=lambda pair: pair[0], reverse=True)

        # Rebuilding the rows resets the selection, so it is restored below;
        # without that, re-sorting at the end of a search would silently clear
        # a preview the user was already reading.
        self.results.blockSignals(True)
        self.results.clear()
        for _, hit in dated:
            self.results.addItem(self._make_item(hit))
        self.results.blockSignals(False)

        self._match_count = self.results.count()
        # Signals were blocked across the rebuild, so the buttons' state was
        # not refreshed by the clear; put it back in step with the list.
        self._enable_row_actions(False)
        if selected_hit:
            for row in range(self.results.count()):
                if self.results.item(row).data(HIT_ROLE) == selected_hit:
                    self.results.setCurrentRow(row)
                    break

    # -- preview -----------------------------------------------------------

    def _show_pane(self, pdf: bool) -> None:
        """Put either the PDF pane or the text pane in front.

        Leaving the PDF pane also lets go of its document, so a file stays
        open only while it is the one being read.

        Word Wrap goes with the text pane: a rendered page has no line
        wrapping to turn off, and a checkbox that does nothing to what is on
        screen is worse than a dim one.
        """
        if self._pdf is None:
            return
        if self._pdf_showing and not pdf:
            self._pdf.clear()
        self._pdf_showing = pdf
        self._panes.setCurrentWidget(self._pdf if pdf else self.preview)
        self.wrap_check.setEnabled(not pdf)

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

        The `Hit` comes from HIT_ROLE, not the row's text, which is only the
        part below the search root. One naming a file inside an archive is
        extracted to a read-only copy first; `viewer` does that, since it is
        the same decision as which command to run.
        """
        item = self.results.currentItem()
        if item is None:
            return
        error = open_in_editor(item.data(HIT_ROLE), self._search_depth)
        if error:
            self._report_problem(error)

    def _open_selected_folder(self) -> None:
        """Show the selected file's folder in the desktop's file manager.

        No depth argument, unlike Open: nothing is extracted, because the
        folder wanted for a hit inside an archive is the one holding the
        archive itself — see `viewer.containing_folder`.
        """
        item = self.results.currentItem()
        if item is None:
            return
        error = open_folder(item.data(HIT_ROLE))
        if error:
            self._report_problem(error)

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

    def _on_selection_changed(
        self, current: QListWidgetItem | None, _previous: QListWidgetItem | None
    ) -> None:
        """Show the current row's file.

        Wired to the current *item* rather than to clicks, so walking the
        results with the arrow keys previews each file too.
        """
        # Both act on the current row, so they are live exactly when one
        # exists.
        self._enable_row_actions(current is not None)
        if current is None:
            self.open_button.setToolTip(OPEN_TIP)
            self.folder_button.setToolTip(FOLDER_TIP)
            self._show_pane(False)
            self.preview.clear()
            # Clearing the pane has to clear what the pane was about, or Prev
            # and Next stay live over a document that no longer has the matches
            # they would step to.
            self._highlighter.set_spans({})
            self._adopt_matches({})
            return
        hit = current.data(HIT_ROLE)
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
        if self._pdf is not None and not hit.member and is_pdf(hit.path):
            text = self._pdf.show_file(hit.path, literal_query_term(self._search_query))
            if text is None:
                self._show_pane(True)
                self._adopt_pdf_matches()
                return
        self._show_pane(False)
        if text is not None:
            self._highlighter.set_spans({})
            self.preview.setPlainText(text)
            self._adopt_matches({})
            return

        text, is_notice = read_for_preview(hit, self._search_depth)
        # A notice — binary, too large, unreadable — is this app's own words
        # rather than the file, so there is nothing in it ugrep matched and its
        # line numbers mean nothing. Asking ugrep about it would also be asking
        # about a file that by definition cannot be shown.
        spans = (
            {}
            if is_notice or not self._search_query
            else match_spans(
                self._search_query, hit, self._search_depth, self._search_fuzzy
            )
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
        if self._pdf_showing and self._pdf is not None:
            return self._pdf.count()
        return len(self._matches)

    def _step_match(self, delta: int) -> None:
        """Move `delta` matches from the current one, wrapping at either end."""
        total = self._match_total()
        if total:
            self._go_to_match((self._match_index + delta) % total)

    def _go_to_match(self, index: int) -> None:
        """Make match `index` current: mark it, scroll to it, and count it."""
        self._match_index = index
        if self._pdf_showing and self._pdf is not None:
            self._pdf.go_to(index)
            self._update_match_nav()
            return
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
        total = self._match_total()
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
        # And the PDF, for the same reason and a sharper consequence: the
        # search model fills its pages in lazily, so closing the window while
        # one is still being searched leaves pdfium walking a document Qt is
        # already tearing down. Measured: the process exits on SIGSEGV rather
        # than cleanly, which from a terminal is "Segmentation fault" after a
        # session that went fine. Clearing first drops the model and the
        # document while there is still a window to own them.
        if self._pdf is not None:
            self._pdf.clear()
        # And without this, every archive member opened this session is still
        # sitting in /tmp. An editor holding one open keeps its own buffer, so
        # removing it here costs the user nothing.
        cleanup_temp_files()
        # And the help windows, which are modeless and therefore still on
        # screen. They do not hold the application open — a parented dialog
        # has a transient parent, so it is not the last window as far as
        # quitOnLastWindowClosed is concerned — but one of them outliving the
        # window it is about, even for an instant, is wrong on its face.
        close_markdown_windows()
        super().closeEvent(event)
