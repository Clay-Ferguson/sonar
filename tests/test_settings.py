"""The settings dialog: what it shows, and what Save writes.

`SettingsDialog` constructs without the main window and `_save()` can be
called directly, so none of this needs a click. `conf` has already pointed
`config.CONFIG_PATH` at a temp file, which is what keeps a test off the real
~/.config.
"""

from __future__ import annotations

from PyQt6.QtWidgets import QLabel

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
    assert config.search_depth() == 0


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
    assert config.search_fuzzy() == 0


def test_a_broken_config_warns_before_it_can_be_overwritten(conf, qtbot):
    """The fields start empty in that case, and Save replaces the file rather
    than editing it — so the dialog says so at the top."""
    conf()
    open(config.CONFIG_PATH, "w").write("search: [unclosed\n")
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)

    captions = [label.text() for label in dialog.findChildren(QLabel)]
    assert any("could not be read" in text for text in captions)
