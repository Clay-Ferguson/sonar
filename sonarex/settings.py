"""The settings dialog: the search patterns, and the Open button's command.

One pattern per line in each of two text areas, which is the shape the lists
already have in the config file and the shape they need for ugrep. There is
no add/remove/reorder machinery because a text area already does all three,
and it is the only editor for this that can be used without the mouse.

The layout is a stack of labelled sections in a QVBoxLayout, sized to its
contents: the next setting is one more `_add_patterns`, `_add_line` or
`_add_check` call and the dialog grows to fit it, with no geometry to revisit.

Saving writes the file and nothing else. Both readers go back to the config
at the moment they need it — `build_argv` calls `search_globs` per search,
`open_in_editor` calls `open_command` per click — so a saved change applies
next time without a restart and without anything to notify.
"""

from __future__ import annotations

from html import escape

from PyQt6.QtGui import QFontMetrics
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from . import APP_NAME
from .archive import MAX_DEPTH
from .config import (
    CONFIG_PATH,
    MAX_FUZZY,
    Settings,
    load_settings,
    parse_pattern_lines,
    pattern_lines,
    save_settings,
)
from .style import (
    PRIMARY_BUTTON_BG,
    SECONDARY_BUTTON_BG,
    action_button,
    action_button_size,
    apply_scrollbars,
    enlarge_checkbox,
    mono_font,
)

# How many lines of patterns each text area shows before it has to scroll.
VISIBLE_LINES = 7

# Vertical gaps: between one labelled section and the next, and between a
# label and the field it belongs to. The second is smaller on purpose — it is
# what makes the pair read as one thing.
SECTION_SPACING = 14
LABEL_SPACING = 4

# What each --zmax value is called in the dropdown. A bare "1 / 2 / 3" says
# nothing about what is being counted, and this is a setting most people will
# look at exactly once; the number stays in front so the config file's
# `archive_depth: 2` is still recognisable as the same thing.
DEPTH_LABELS = [
    "1 — archives only",
    "2 — also archives inside archives",
    "3 — three levels deep",
]

# What each --fuzzy value is called. Named rather than numbered first, unlike
# the depth: the number counts something a user has no feel for — "2" says
# nothing about how much wider a search gets — so the adjective leads and the
# count explains it. The first entry is 0, which is why this dropdown is read
# from a base of 0 rather than 1.
FUZZY_LABELS = [
    "Off — exact matches only",
    "Close — 1 character different",
    "Looser — 2 characters different",
    "Loosest — 3 characters different",
]

# Wide enough for a long exclusion path without wrapping it — these are read
# as whole patterns, and a pattern broken across two lines is hard to check.
MIN_WIDTH = 600


class PatternEdit(QPlainTextEdit):
    """A text area exactly `VISIBLE_LINES` tall, one pattern per line.

    The height is pinned rather than left to the layout. A QVBoxLayout hands
    surplus height to whatever will take it, and a field a few pixels taller
    than a whole number of lines shows the top of the next one — a sliver of
    clipped text along the bottom edge that reads as a rendering fault. Seven
    whole lines, always; the dialog's own surplus collects above the buttons
    instead.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFont(mono_font())
        # Patterns are single tokens: wrapping one across two lines would make
        # the "one per line" rule the whole field is built on unreadable.
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setTabChangesFocus(True)  # Tab moves on rather than inserting one
        apply_scrollbars(self)
        self.setFixedHeight(self._height_for_lines())

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


class SettingsDialog(QDialog):
    """Edit the search patterns, archive searching and the Open command."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"{APP_NAME} — Settings")
        self.setMinimumWidth(MIN_WIDTH)

        settings, error = load_settings()

        self._layout = QVBoxLayout(self)
        # The layout's own spacing is the tight one, since it is what falls
        # between a label and the field it names; the wider gap between
        # sections is added explicitly, in `_begin_section`.
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

        self.included_edit = self._add_patterns(
            "Include only these files (empty = search everything):",
            settings.included,
        )
        self.excluded_edit = self._add_patterns(
            "Skip these files and folders:", settings.excluded
        )
        self.archives_check = self._add_check(
            "Search inside archives (.zip, .tar.gz, .7z, .gz \u2026)",
            settings.archives,
            # Both halves of this surprise people, and both are ugrep's doing
            # rather than a choice made here: -g globs are matched against the
            # names inside an archive, and an archive is only opened at all if
            # its own extension is one ugrep knows.
            tooltip=(
                "A match inside an archive is listed as \"archive.zip \u2192 name\".\n"
                "The include patterns above then apply to the files inside an"
                " archive too.\n"
                "Archives with an unusual extension (.jar, .docx, .epub are all"
                " zips) are\nonly opened if you add that extension to the include"
                " patterns."
            ),
        )
        self.depth_combo = self._add_combo(
            "How deep to look inside them:",
            DEPTH_LABELS[:MAX_DEPTH],
            settings.archive_depth,
            tooltip=(
                "Each level is another pass over what the one above it found,"
                " so raise this\nonly if you keep archives inside archives."
            ),
        )
        # Dim rather than hidden: the depth is still worth seeing when it is
        # not in use, and it keeps the dialog from changing height under the
        # pointer as the checkbox is clicked.
        self.depth_combo.setEnabled(settings.archives)
        self.archives_check.toggled.connect(self.depth_combo.setEnabled)

        self.fuzzy_combo = self._add_combo(
            "Find near matches:",
            FUZZY_LABELS[: MAX_FUZZY + 1],
            settings.fuzzy,
            # Both of these surprise people and both are ugrep's doing: an
            # approximate match always begins at the pattern's first character,
            # and the setting is a property of the matcher rather than of one
            # kind of term, so a negated term is widened along with everything
            # else and therefore excludes more.
            tooltip=(
                "Also finds words spelled a little differently from what you"
                " typed —\n\"color\" then finds \"colour\" too.\n"
                "The first letter still has to be right: \"xolor\" finds"
                " nothing at any setting.\n"
                "NOT and - terms become approximate as well, so they exclude"
                " more."
            ),
            base=0,
        )

        self.open_edit = self._add_line(
            "Command the Open button runs (the file is added as the last argument):",
            settings.open_command,
            # The caption covers the case everyone has — a program name. The
            # rest is here rather than on a third line of label: it matters
            # only to someone already reaching for a placeholder or a flag.
            tooltip=(
                "Split the way a shell would split it, but run without a shell,"
                " so pipes and redirection do not work.\n"
                "Put %s anywhere in the command to place the file there instead"
                " of at the end — e.g. gnome-terminal -- vim %s"
            ),
        )

        # New settings go here — one more `_add_patterns` / `_add_line` /
        # `_add_check` (or any widget) added before the button row, which stays
        # pinned to the bottom.

        # Every field above is a fixed height, so a dialog dragged taller has
        # surplus to put somewhere: it goes here, between the last setting and
        # the buttons, rather than into a field that would then show a clipped
        # row. At the dialog's natural size this is worth nothing.
        self._layout.addStretch(1)
        self._layout.addSpacing(SECTION_SPACING - LABEL_SPACING)
        self._layout.addLayout(self._button_row())

    # -- construction ------------------------------------------------------

    def _begin_section(self, label: str, tooltip: str = "") -> None:
        """Open a new labelled section: the gap above it, then its caption."""
        if self._layout.count():
            # Everything but the first section is held off from what precedes
            # it, so a label reads as belonging to the field below it rather
            # than to the one above.
            self._layout.addSpacing(SECTION_SPACING - LABEL_SPACING)
        caption = QLabel(label)
        # A long caption wraps rather than widening the dialog past MIN_WIDTH.
        caption.setWordWrap(True)
        # The label carries the field's tooltip too: it is the larger target,
        # and someone hunting for an explanation hovers the text.
        caption.setToolTip(tooltip)
        self._layout.addWidget(caption)

    def _add_patterns(self, label: str, patterns: list[str]) -> PatternEdit:
        """A labelled pattern field, appended to the stack. Returns the field."""
        self._begin_section(label)
        edit = PatternEdit()
        edit.setPlainText(pattern_lines(patterns))
        self._layout.addWidget(edit)
        return edit

    def _add_line(self, label: str, value: str, tooltip: str = "") -> QLineEdit:
        """A labelled single-line field, appended to the stack.

        Height matched to the buttons — and so to the main window's query row,
        which is measured the same way — rather than left at a bare
        QLineEdit's, which is shorter than everything around it.
        """
        self._begin_section(label, tooltip)
        edit = QLineEdit(value)
        edit.setFont(mono_font())
        edit.setToolTip(tooltip)
        edit.setFixedHeight(action_button_size().height())
        self._layout.addWidget(edit)
        return edit

    def _add_check(self, label: str, checked: bool, tooltip: str = "") -> QCheckBox:
        """A checkbox, appended to the stack. Returns the field.

        No caption above it: a checkbox carries its own label, and a second
        line of text naming the same setting would read as two settings. It
        gets the section gap all the same, so it sits apart from the field
        above rather than looking like part of it.
        """
        if self._layout.count():
            self._layout.addSpacing(SECTION_SPACING - LABEL_SPACING)
        check = QCheckBox(label)
        check.setChecked(checked)
        check.setToolTip(tooltip)
        # Matched to the main window's Word Wrap, which is the only other
        # checkbox in the app.
        enlarge_checkbox(check)
        self._layout.addWidget(check)
        return check

    def _add_combo(
        self,
        label: str,
        options: list[str],
        value: int,
        tooltip: str = "",
        base: int = 1,
    ) -> QComboBox:
        """A labelled dropdown over base..base+len(options)-1, appended to the stack.

        The value is the position it stands for, not the text, so the caller
        reads `currentIndex() + base` and never has to parse a label back into
        a number. `base` is what the *first* option means: 1 for a count of
        levels, 0 for a setting whose first entry is "off". Sized to its
        contents and pushed left rather than stretched across the dialog: a
        field as wide as the pattern areas would read as holding something as
        large as they do.
        """
        self._begin_section(label, tooltip)
        combo = QComboBox()
        combo.addItems(options)
        combo.setCurrentIndex(max(0, min(len(options) - 1, value - base)))
        combo.setToolTip(tooltip)
        # Matched to the buttons, like the single-line fields, so the controls
        # in this dialog are all one height.
        combo.setFixedHeight(action_button_size().height())
        combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        row = QHBoxLayout()
        row.addWidget(combo)
        row.addStretch(1)
        self._layout.addLayout(row)
        return combo

    def _button_row(self) -> QHBoxLayout:
        """Save and Cancel, right-aligned, sized like the Search button.

        Both are matched to the header's primary button rather than left to
        size themselves: three buttons of three different widths in one app is
        what makes a dialog look assembled rather than designed.
        """
        save = action_button("Save", PRIMARY_BUTTON_BG, uniform=True)
        save.setDefault(True)  # Enter in the dialog saves
        save.clicked.connect(self._save)

        cancel = action_button("Cancel", SECONDARY_BUTTON_BG, uniform=True)
        cancel.clicked.connect(self.reject)

        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(cancel)
        row.addWidget(save)
        return row

    # -- actions -----------------------------------------------------------

    def _save(self) -> None:
        """Write every field back, and close only if that worked."""
        error = save_settings(
            Settings(
                included=parse_pattern_lines(self.included_edit.toPlainText()),
                excluded=parse_pattern_lines(self.excluded_edit.toPlainText()),
                archives=self.archives_check.isChecked(),
                archive_depth=self.depth_combo.currentIndex() + 1,
                open_command=self.open_edit.text().strip(),
                fuzzy=self.fuzzy_combo.currentIndex(),
            )
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
