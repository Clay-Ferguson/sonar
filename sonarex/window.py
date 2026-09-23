"""The window: a query row, a folder row, and a split results/preview pane.

Results stream in as ugrep finds them, which is why the list is appended to
rather than filled in one go — and why it is re-sorted once, at the end, when
the full set is finally known (see `_on_search_finished`).
"""

from __future__ import annotations

import os

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)
from windowchrome import apply_scrollbars, close_markdown_windows

from . import APP_NAME
from .archive import Hit, member_levels, parse_result_line
from .config import load_settings
from .help import show_query_syntax, show_user_guide
from .preview import PreviewPanel
from .search import (
    EXIT_MATCHED,
    EXIT_NO_MATCH,
    MODE_CONTENT,
    MODE_NAMES,
    SearchRunner,
    name_search_error,
    name_terms,
    search_error,
)
from .settings import show_settings
from .spec import SearchSpec, search_problems
from .statusbar import SearchStatusBar
from .style import (
    PRIMARY_BUTTON_BG,
    SECONDARY_BUTTON_BG,
    SPLITTER_HANDLE_WIDTH,
    action_button,
    menu_style,
    mono_font,
    results_list_style,
    splitter_style,
)
from .viewer import (
    cleanup_temp_files,
    open_folder,
    open_in_editor,
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

# What separates an archive from what was found inside it, in a row's label.
# Spaced, because the names on either side of it are paths full of punctuation
# already and an unspaced arrow disappears into them.
ARROW = " → "

MODE_TIP = (
    "Content: search the text inside files.\n"
    "Filenames: search the names of files and folders."
)

# Results/preview split, as a ratio of the window width. The preview needs the
# room; the list only has to show a path.
SPLIT_LIST = 2
SPLIT_PREVIEW = 3

# And what it says when a search went wrong. The detail is in the dialog that
# comes with it; this is only what the bar is left showing behind it, in place
# of numbers that no longer mean anything.
STATUS_FAILED = "Search failed"


def printable(text: str) -> str:
    """`text` with any undecodable filename bytes shown as U+FFFD.

    Paths arrive `os.fsdecode`d, so a name that is not UTF-8 carries lone
    surrogates standing for its raw bytes — lossless, which is what lets the
    `Hit` still open the file, but not something to put in front of a reader.
    Only labels go through this; the `Hit` keeps the real path.
    """
    return text.encode("utf-8", "surrogateescape").decode("utf-8", "replace")


class MainWindow(QMainWindow):
    def __init__(self, folder: str) -> None:
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1100, 700)

        self._runner = SearchRunner(self)
        self._runner.matchFound.connect(self._on_match)
        self._runner.finished.connect(self._on_search_finished)
        self._match_count = 0
        # The search the current results came from — query, folder, mode and
        # the settings it ran with — pinned when it starts and read from here,
        # never from the rows or the config, for as long as its results are on
        # screen. See `spec.py` for why. Blank until the first search.
        self._search = SearchSpec("", "")
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

        # What the query is matched against. Either/or, never both, and it
        # starts on Content every launch: it is a choice about this search,
        # not a setting. Changing it runs nothing — the query only runs from
        # Search or Enter, as always.
        self.mode_combo = QComboBox()
        self.mode_combo.addItems([MODE_CONTENT, MODE_NAMES])
        self.mode_combo.setCurrentText(MODE_CONTENT)
        self.mode_combo.setToolTip(MODE_TIP)
        self.mode_combo.setFixedHeight(row_height)
        self.mode_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)

        query_row = QHBoxLayout()
        query_row.addWidget(search_label)
        query_row.addWidget(self.query_edit, 1)
        query_row.addWidget(self.mode_combo)
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

        # The file on show and the controls under it. The two buttons that act
        # on the selected row live in its control bar, but what they open is
        # decided here, from the row and the pinned search.
        self.panel = PreviewPanel()
        self.panel.open_button.clicked.connect(self._open_selected)
        self.panel.folder_button.clicked.connect(self._open_selected_folder)

        # The wider scroll bars; applied per scroll bar so the list itself
        # keeps native rendering. The panel does the same for its own panes.
        apply_scrollbars(self.results)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(SPLITTER_HANDLE_WIDTH)
        splitter.setStyleSheet(splitter_style())
        splitter.addWidget(self.results)
        splitter.addWidget(self.panel)
        splitter.setStretchFactor(0, SPLIT_LIST)
        splitter.setStretchFactor(1, SPLIT_PREVIEW)
        splitter.setSizes([SPLIT_LIST * 100, SPLIT_PREVIEW * 100])
        layout.addWidget(splitter, 1)

        self._status = SearchStatusBar()
        self.setStatusBar(self._status)

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

    # -- the status bar -----------------------------------------------------

    def _searched_note(self) -> str:
        """" — 1,234 files searched" — or nothing, when ugrep did not say.

        The count comes from `--stats`, which ugrep prints after the last hit,
        so it is only ever known once the search has finished. A search that
        failed to start never produces it, and 0 there means "unknown" rather
        than "none": claiming zero files were searched would be a worse answer
        than leaving the clause out.
        """
        searched = self._runner.files_searched()
        return f" — {searched:,} files searched" if searched else ""

    # -- reporting ----------------------------------------------------------

    def _report_problem(self, message: str) -> None:
        """Show something that actually went wrong.

        A dialog rather than a quiet line somewhere: these are rare, they
        follow an explicit action the user just took, and the two that matter
        most — a rejected regex and a missing editor — are long enough that a
        truncated title would hide the part that says what to fix.
        """
        QMessageBox.warning(self, APP_NAME, message)

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

        names = self.mode_combo.currentText() == MODE_NAMES
        if names and "/" in query:
            # find's -iname tests the last path component only, so a slash can
            # never match; it would only warn and list nothing.
            self._report_problem(
                "A file or folder name cannot contain '/'.\n\n"
                "Search for the name alone, and set the folder in the row below."
            )
            return
        if names and not name_terms(query):
            # Nothing but empty quotes: there is no word to look for.
            self.query_edit.setFocus()
            return

        # The config file can be edited by hand, so the dialog's own check on
        # Save is not enough. A bad pattern never makes ugrep or find fail —
        # it silently lists nothing, or skips nothing — so it is refused here,
        # where the user can be told which line to fix. One read of the file
        # serves both this check and the search itself.
        settings, _error = load_settings()
        problems = search_problems(settings, names)
        if problems:
            self._report_problem(
                "The search patterns in the settings need fixing first:\n\n"
                + "\n\n".join(problems)
                + "\n\nChange them under Options ▸ Settings."
            )
            return

        folder = self._folder()
        if not os.path.isdir(folder):
            self._report_problem(f"Not a folder:\n\n{folder}")
            return

        # Clearing the list clears the panel through the selection signal
        # when a row was selected; said outright for when none was.
        self.results.clear()
        self.panel.clear()
        self._match_count = 0
        # Pinned here, for the whole life of these results. The root is the
        # same value ugrep is given, so every path it prints is genuinely
        # underneath it and `_display_path` can rely on the prefix matching.
        self._search = SearchSpec.from_settings(settings, query, folder, names)
        self._status.set_status(f"Searching {folder}…", busy=True)
        self._runner.start(self._search)

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
        if not self._search.root:
            return path
        try:
            relative = os.path.relpath(path, self._search.root)
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
            levels = member_levels(hit.member, self._search.depth)
            label = ARROW.join([label, *levels])
            tooltip = "\n".join(
                [hit.path] + [f"{'  ' * (n + 1)}{name}" for n, name in enumerate(levels)]
            )
        item = QListWidgetItem(printable(label))
        item.setData(HIT_ROLE, hit)
        # The full path stays reachable, since the row no longer shows it.
        item.setToolTip(printable(tooltip))
        return item

    # -- search callbacks --------------------------------------------------

    def _on_match(self, line: str) -> None:
        # find prints bare paths, and a name may legally contain the tab that
        # `parse_result_line` would look for a member after.
        hit = Hit(line, "") if self._search.names else parse_result_line(line)
        self.results.addItem(self._make_item(hit))
        self._match_count += 1
        # Cheap enough to do per hit, and it is what turns the spinner from
        # "still running" into "still finding things".
        self._status.set_status(
            f"Searching {self._search.root}… {self._match_count:,} found",
            busy=True,
        )

    def _on_search_finished(self, exit_code: int, stderr: str) -> None:
        """Report a real failure; otherwise sort the list and report the count.

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
        # find has no "no match" status: 0 is a clean walk and 1 means some
        # path could not be read, which — like ugrep's 2 — is usually nothing.
        if self._search.names:
            failed, program, explain = exit_code != 0, "find", name_search_error
        else:
            failed = exit_code not in (EXIT_MATCHED, EXIT_NO_MATCH)
            program, explain = "ugrep", search_error
        if failed:
            problem = explain(stderr)
            # An unexplained failure is still a failure: only silence a
            # non-zero status when the program said why and every reason was
            # a path it skipped.
            if not problem and not stderr.strip():
                problem = f"{program} exited with status {exit_code}."
        if problem:
            self._status.set_status(STATUS_FAILED)
            self._report_problem(problem)
            return

        if not self._match_count:
            self._status.set_status(
                f"No matches{self._searched_note()} in {self._search.root}"
            )
            return

        self._sort_by_mtime()
        # The root is named because the rows no longer carry it, and the folder
        # row above is not proof of it — that field stays editable once a
        # search has finished. A name search lists folders too, so its rows
        # are counted as items rather than files.
        noun = "item" if self._search.names else "file"
        self._status.set_status(
            f"{self._match_count:,} {noun}"
            f"{'' if self._match_count == 1 else 's'} found"
            f"{self._searched_note()} in {self._search.root}"
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
        # Signals were blocked across the rebuild, so the panel was not told
        # the selection went. Restoring it re-shows that file; if it cannot be
        # restored — nothing was selected, or its file vanished and its row was
        # dropped — the panel is emptied rather than left showing a row that
        # is no longer in the list.
        for row in range(self.results.count() if selected_hit else 0):
            if self.results.item(row).data(HIT_ROLE) == selected_hit:
                self.results.setCurrentRow(row)
                return
        self.panel.clear()

    # -- preview -----------------------------------------------------------

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
        error = open_in_editor(item.data(HIT_ROLE), self._search.depth)
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

    def _on_selection_changed(
        self, current: QListWidgetItem | None, _previous: QListWidgetItem | None
    ) -> None:
        """Show the current row's file, with the search that found it.

        Wired to the current *item* rather than to clicks, so walking the
        results with the arrow keys previews each file too.
        """
        if current is None:
            self.panel.clear()
        else:
            self.panel.show_hit(current.data(HIT_ROLE), self._search)

    # -- lifecycle ---------------------------------------------------------

    def closeEvent(self, event) -> None:
        # Without this a search still running when the window closes leaves an
        # orphaned ugrep walking the tree.
        self._runner.stop()
        # And the spinner, which would otherwise go on repainting two labels
        # while the window is being torn down around them.
        self._status.stop()
        # And the PDF, for a sharper reason: closing on a PDF that is still
        # being searched exits on SIGSEGV. See `PreviewPanel.shutdown`.
        self.panel.shutdown()
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
