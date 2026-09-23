"""The settings dialog: what it shows, and what Save writes.

`SettingsDialog` constructs without the main window and `_save()` can be
called directly, so none of this needs a click. `conf` has already pointed
`config.CONFIG_PATH` at a temp file, which is what keeps a test off the real
~/.config.
"""

from __future__ import annotations

import pytest
from PyQt6.QtWidgets import QLabel

from helpers import current_spec
from sonarex import config
from sonarex.archive import MAX_DEPTH
from sonarex.config import MAX_FUZZY
from sonarex.settings import DEPTH_LABELS, FUZZY_LABELS, SettingsDialog


def test_the_dialog_shows_what_is_on_disk(conf, qtbot):
    conf(archives=True, depth=2, included=["*.md"], excluded=["*/build/*"], fuzzy=2)
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)

    assert dialog.included_edit.toPlainText() == "*.md"
    assert dialog.excluded_edit.toPlainText() == "*/build/*"
    assert dialog.archives_check.isChecked() is True
    assert dialog.depth_combo.currentIndex() == 1  # 0-based: "2 — also ..."
    # This one reads from a base of 0, so the index *is* the value.
    assert dialog.fuzzy_combo.currentIndex() == 2
    assert dialog.open_edit.text() == "/bin/true"


def test_saving_writes_every_field(conf, qtbot):
    conf(archives=False, depth=1)
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)

    dialog.archives_check.setChecked(True)
    dialog.depth_combo.setCurrentIndex(2)
    dialog.fuzzy_combo.setCurrentIndex(1)
    dialog.included_edit.setPlainText("*.py\n*.md")
    dialog.open_edit.setText("/usr/bin/vim")
    dialog._save()

    settings, error = config.load_settings()
    assert error is None
    assert settings.archives is True
    assert settings.archive_depth == 3
    assert settings.included == ["*.py", "*.md"]
    assert settings.fuzzy == 1
    assert settings.open_command == "/usr/bin/vim"


def test_the_depth_follows_the_checkbox(conf, qtbot):
    """Dim rather than hidden, so the dialog does not change height under the
    pointer as the box is clicked."""
    conf(archives=False, depth=2)
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    assert dialog.depth_combo.isEnabled() is False

    dialog.archives_check.setChecked(True)
    assert dialog.depth_combo.isEnabled() is True
    dialog.archives_check.setChecked(False)
    assert dialog.depth_combo.isEnabled() is False


def test_the_depth_survives_being_turned_off(conf, qtbot):
    """Unchecking the box must not discard the depth that was picked, or
    turning it back on would silently reset to 1."""
    conf(archives=True, depth=3)
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    dialog.archives_check.setChecked(False)
    dialog._save()

    assert config.load_settings()[0].archive_depth == 3
    assert current_spec().depth == 0


def test_the_dropdown_offers_exactly_max_depth_choices(conf, qtbot):
    conf()
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    assert dialog.depth_combo.count() == MAX_DEPTH
    assert dialog.depth_combo.itemText(0) == DEPTH_LABELS[0]


def test_the_fuzzy_dropdown_starts_at_off(conf, qtbot):
    """`_add_combo` is 1-based for the depth and 0-based here, so the first
    entry has to stand for 0 rather than for 1 — otherwise "Off" saves as
    "Close" and every search silently becomes approximate."""
    conf(fuzzy=0)
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    assert dialog.fuzzy_combo.count() == MAX_FUZZY + 1
    assert dialog.fuzzy_combo.itemText(0) == FUZZY_LABELS[0]
    assert dialog.fuzzy_combo.currentIndex() == 0

    dialog._save()
    assert config.load_settings()[0].fuzzy == 0
    assert current_spec().fuzzy == 0


def test_a_broken_config_warns_before_it_can_be_overwritten(conf, qtbot):
    """The fields start empty in that case, and Save replaces the file rather
    than editing it — so the dialog says so at the top."""
    conf()
    open(config.CONFIG_PATH, "w").write("search: [unclosed\n")
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)

    captions = [label.text() for label in dialog.findChildren(QLabel)]
    assert any("could not be read" in text for text in captions)


def test_the_include_checkbox_dims_the_field(conf, qtbot):
    """Dimmed, not cleared: the patterns have to be there when it is ticked
    again."""
    conf(included=["*.md"], use_included=True)
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    assert dialog.included_check.isChecked() is True
    assert dialog.included_edit.isEnabled() is True

    dialog.included_check.setChecked(False)
    assert dialog.included_edit.isEnabled() is False
    assert dialog.included_edit.toPlainText() == "*.md"
    dialog.included_check.setChecked(True)
    assert dialog.included_edit.isEnabled() is True


def test_unticking_include_keeps_the_patterns_but_not_the_whitelist(conf, qtbot):
    conf(included=["*.md", "*.py"], excluded=["*/build/*"])
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    dialog.included_check.setChecked(False)
    dialog._save()

    settings = config.load_settings()[0]
    assert settings.use_included is False
    assert settings.included == ["*.md", "*.py"]
    assert list(current_spec().globs) == ["-g", "!build/"]

    reopened = SettingsDialog()
    qtbot.addWidget(reopened)
    assert reopened.included_check.isChecked() is False
    assert reopened.included_edit.isEnabled() is False
    assert reopened.included_edit.toPlainText() == "*.md\n*.py"


def test_the_skip_checkbox_dims_the_field_and_keeps_the_patterns(conf, qtbot):
    conf(included=["*.md"], excluded=["*/build/*"])
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    assert dialog.excluded_check.isChecked() is True
    assert dialog.excluded_edit.isEnabled() is True

    dialog.excluded_check.setChecked(False)
    assert dialog.excluded_edit.isEnabled() is False
    # Independent of the include box, which stays as it was.
    assert dialog.included_edit.isEnabled() is True
    dialog._save()

    settings = config.load_settings()[0]
    assert settings.use_excluded is False
    assert settings.use_included is True
    assert settings.excluded == ["*/build/*"]
    assert list(current_spec().globs) == ["-g", "*.md"]

    reopened = SettingsDialog()
    qtbot.addWidget(reopened)
    assert reopened.excluded_check.isChecked() is False
    assert reopened.excluded_edit.isEnabled() is False
    assert reopened.excluded_edit.toPlainText() == "*/build/*"


@pytest.mark.parametrize(
    "field, text, named",
    [
        pytest.param("included_edit", "*.md\ndocs/*.txt", "docs/*.txt", id="include"),
        pytest.param("excluded_edit", "*/build/*\ndocs/*.tmp", "docs/*.tmp", id="skip"),
    ],
)
def test_a_pattern_that_cannot_work_is_not_saved(conf, qtbot, dialogs, field, text, named):
    """The dialog stays open with the edits in it, and the file is untouched."""
    conf(included=["*.py"], excluded=["*/build/*"])
    before = open(config.CONFIG_PATH).read()
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    getattr(dialog, field).setPlainText(text)
    dialog._save()

    assert len(dialogs) == 1 and f'"{named}"' in dialogs[0][1]
    assert open(config.CONFIG_PATH).read() == before
    assert dialog.result() != dialog.DialogCode.Accepted


def test_it_is_refused_even_with_the_box_unticked(conf, qtbot, dialogs):
    """Saved either way, it would stop every search the moment the box was
    ticked again."""
    conf()
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    dialog.included_check.setChecked(False)
    dialog.included_edit.setPlainText("docs/*.md")
    dialog._save()
    assert len(dialogs) == 1


def test_a_skip_pattern_under_any_folder_saves(conf, qtbot, dialogs):
    conf()
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    dialog.excluded_edit.setPlainText("*/build/*\n*/docs/*.tmp")
    dialog._save()
    assert dialogs == []
    assert config.load_settings()[0].excluded == ["*/build/*", "*/docs/*.tmp"]
