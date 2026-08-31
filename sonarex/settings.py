"""The settings dialog: the include and exclude pattern lists, as text.

One pattern per line in each of two text areas, which is the shape the lists
already have in the config file and the shape they need for ugrep. There is
no add/remove/reorder machinery because a text area already does all three,
and it is the only editor for this that can be used without the mouse.

The layout is a stack of labelled sections in a QVBoxLayout, sized to its
contents: the next setting is a `_add_section` call and the dialog grows to
fit it, with no geometry to revisit.

Saving writes the file and nothing else — `SearchRunner` re-reads the config
on every search (`build_argv` calls `search_globs`), so the next Search picks
the new patterns up on its own.
"""

from __future__ import annotations

from html import escape

from PyQt6.QtCore import QSize
from PyQt6.QtGui import QFontMetrics, QIcon
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from . import APP_NAME
from .config import (
    CONFIG_PATH,
    load_patterns,
    parse_pattern_lines,
    pattern_lines,
    save_patterns,
)
from .style import (
    HELP_BUTTON_BG,
    SEARCH_BUTTON_BG,
    SEARCH_BUTTON_PADDING,
    action_button_style,
    apply_scrollbars,
    match_action_button,
    mono_font,
)

# Icon-theme names to try for the button, best first. Yaru supplies the first
# few; a bare desktop install may supply none, which is what the drawn gear
# fallback in `settings_icon` is for.
ICON_NAMES = (
    "preferences-system",
    "applications-system",
    "preferences-desktop",
    "emblem-system",
    "settings-configure",
    "gtk-preferences",
)

# How many lines of patterns each text area shows before it has to scroll.
VISIBLE_LINES = 7

# Vertical gaps: between one labelled section and the next, and between a
# label and the field it belongs to. The second is smaller on purpose — it is
# what makes the pair read as one thing.
SECTION_SPACING = 14
LABEL_SPACING = 4

# Wide enough for a long exclusion path without wrapping it — these are read
# as whole patterns, and a pattern broken across two lines is hard to check.
MIN_WIDTH = 600


def settings_icon() -> QIcon:
    """A gear icon from the desktop theme, or a null QIcon if it has none.

    Same contract as `help.help_icon`: the caller checks for null and draws a
    character instead, since a button showing a null icon is a blank button.
    """
    for name in ICON_NAMES:
        icon = QIcon.fromTheme(name)
        if not icon.isNull():
            return icon
    return QIcon()


class PatternEdit(QPlainTextEdit):
    """A text area exactly `VISIBLE_LINES` tall, one pattern per line.

    The height is reported through `sizeHint` rather than pinned with
    `setFixedHeight`, so the dialog opens at seven lines but the fields still
    take the extra room when someone drags it larger — a fixed height would
    leave a resized dialog with a band of dead space instead.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFont(mono_font())
        # Patterns are single tokens: wrapping one across two lines would make
        # the "one per line" rule the whole field is built on unreadable.
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setTabChangesFocus(True)  # Tab moves on rather than inserting one
        apply_scrollbars(self)
        self.setMinimumHeight(self._height_for_lines())

    def _height_for_lines(self) -> int:
        """The pixel height that shows `VISIBLE_LINES` lines and no more.

        Measured from the font actually set on the widget: a QPlainTextEdit
        lays each block out at exactly `lineSpacing()`, so the text itself is
        that times the line count, and the chrome around it is the frame plus
        the document's own margin.

        The margin is counted once, not at both ends. It is only leading
        space — the document keeps running underneath the bottom one — so
        allowing for it twice leaves room for the top few pixels of an eighth
        line, which reads as a clipped row rather than a full field.
        """
        metrics = QFontMetrics(self.font())
        margin = int(self.document().documentMargin())
        return metrics.lineSpacing() * VISIBLE_LINES + margin + 2 * self.frameWidth()

    def sizeHint(self) -> QSize:
        # Width from the base class, height ours: QAbstractScrollArea's own
        # hint is a fixed 256x192 that has nothing to do with the font, and
        # taking the larger of the two would open the field at nine lines on
        # this font and some other number on the next one.
        return QSize(super().sizeHint().width(), self._height_for_lines())


class SettingsDialog(QDialog):
    """Edit `search.included` and `search.excluded`, then save or discard."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"{APP_NAME} — Settings")
        self.setMinimumWidth(MIN_WIDTH)

        included, excluded, error = load_patterns()

        self._layout = QVBoxLayout(self)
        # The layout's own spacing is the tight one, since it is what falls
        # between a label and the field it names; the wider gap between
        # sections is added explicitly, in `_add_section`.
        self._layout.setSpacing(LABEL_SPACING)

        if error:
            # Shown before anything else, because Save from here rewrites the
            # file: someone with a typo in their YAML is looking at empty
            # fields that do not reflect what is on disk, and needs to know
            # that saving replaces it rather than edits it.
            # Escaped: the label is rich text, and a YAML parser error is
            # full of the file's own punctuation — PyYAML's "expected ',' but
            # got '<stream end>'" would otherwise lose the part in angle
            # brackets to the HTML parser.
            warning = QLabel(
                f"<b>{escape(CONFIG_PATH)} could not be read</b><br>"
                f"{escape(error)}<br>"
                "The fields below start empty; saving replaces the file."
            )
            warning.setWordWrap(True)
            self._layout.addWidget(warning)

        self.included_edit = self._add_section(
            "Include only these files (empty = search everything):", included
        )
        self.excluded_edit = self._add_section(
            "Skip these files and folders:", excluded
        )

        # New settings go here — one more `_add_section` (or any widget) added
        # before the button row, which stays pinned to the bottom.

        self._layout.addSpacing(SECTION_SPACING - LABEL_SPACING)
        self._layout.addLayout(self._button_row())

    # -- construction ------------------------------------------------------

    def _add_section(self, label: str, patterns: list[str]) -> PatternEdit:
        """A labelled pattern field, appended to the stack. Returns the field."""
        if self._layout.count():
            # Everything but the first section is held off from what precedes
            # it, so a label reads as belonging to the field below it rather
            # than to the one above.
            self._layout.addSpacing(SECTION_SPACING - LABEL_SPACING)
        self._layout.addWidget(QLabel(label))
        edit = PatternEdit()
        edit.setPlainText(pattern_lines(patterns))
        # Stretch 1: at the dialog's own size the field sits at its seven-line
        # hint, and only a deliberate resize by the user gives it more.
        self._layout.addWidget(edit, 1)
        return edit

    def _button_row(self) -> QHBoxLayout:
        """Save and Cancel, right-aligned, sized like the Search button.

        Both are matched to the header's primary button rather than left to
        size themselves: three buttons of three different widths in one app is
        what makes a dialog look assembled rather than designed.
        """
        save = self._action_button("Save", SEARCH_BUTTON_BG)
        save.setDefault(True)  # Enter in the dialog saves
        save.clicked.connect(self._save)

        cancel = self._action_button("Cancel", HELP_BUTTON_BG)
        cancel.clicked.connect(self.reject)

        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(cancel)
        row.addWidget(save)
        return row

    @staticmethod
    def _action_button(text: str, background: str) -> QPushButton:
        button = QPushButton(text)
        button.setStyleSheet(action_button_style(background, SEARCH_BUTTON_PADDING))
        match_action_button(button)
        return button

    # -- actions -----------------------------------------------------------

    def _save(self) -> None:
        """Write both lists back, and close only if that worked."""
        error = save_patterns(
            parse_pattern_lines(self.included_edit.toPlainText()),
            parse_pattern_lines(self.excluded_edit.toPlainText()),
        )
        if error:
            # Left open rather than closed on failure: the edits are still in
            # the fields, so the user can fix the cause and press Save again
            # instead of retyping them.
            QMessageBox.warning(self, f"{APP_NAME} — Settings", error)
            return
        self.accept()


def show_settings(parent: QWidget | None = None) -> bool:
    """Open the settings dialog modally. True if it was saved."""
    return SettingsDialog(parent).exec() == QDialog.DialogCode.Accepted
