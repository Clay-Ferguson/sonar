"""The Filenames search mode: `find` over names instead of ugrep over contents.

Driven for real, like the rest of the suite — a genuine find over a genuine
tree — because the cases worth pinning are exactly the ones where the two
programs see the same files differently: folders, empty files, and a word that
is in a file's text but not in its name.
"""

from __future__ import annotations

import os

from helpers import current_spec, highlighted, labels, nav, select, status
from sonarex.archive import Hit
from sonarex.patterns import build_prune_args
from sonarex.preview import OPEN_TIP_FOLDER
from sonarex.query import MODE_CONTENT, MODE_NAMES, name_terms
from sonarex.reader import FOLDER_NOTICE
from sonarex.search import build_name_argv
from sonarex.window import HIT_ROLE, STATUS_FAILED, MainWindow

from conftest import NOOP_OPENER, needs_permissions

# What a name search for `report` finds in `name_tree` with node_modules
# excluded: the folder, the empty file, and the mixed-case name — and not
# `unrelated.txt`, whose only `report` is inside it.
REPORT_NAMES = ["My Report.md", "ReportDir", "empty-report.txt"]


# -- the pieces --------------------------------------------------------------


def test_the_mode_starts_on_content(qtbot, tmp_path):
    window = MainWindow(str(tmp_path))
    qtbot.addWidget(window)
    combo = window.mode_combo
    assert [combo.itemText(i) for i in range(combo.count())] == [MODE_CONTENT, MODE_NAMES]
    assert combo.currentText() == MODE_CONTENT


def test_name_terms():
    assert name_terms("report") == ["*report*"]
    assert name_terms("report 2024") == ["*report*", "*2024*"]
    assert name_terms('"my report"') == ["*my report*"]
    assert name_terms("*.pdf") == ["*.pdf"]
    assert name_terms("draft?.txt") == ["draft?.txt"]
    # An unbalanced quote is still searched for, split on whitespace.
    assert name_terms("it's here") == ["*it's*", "*here*"]
    assert name_terms('""') == []


def test_exclusions_become_a_prune_clause():
    assert build_prune_args([]) == []
    assert build_prune_args(["*/node_modules/*", "*/a/b/*", "docs/*.tmp", "*.log"]) == [
        "(",
        "-path", "*/node_modules",
        "-o", "-path", "*/a/b",
        "-o", "-path", "docs/*.tmp",
        "-o", "-name", "*.log",
        ")", "-prune", "-o",
    ]


def test_name_argv(conf):
    conf(archives=True, fuzzy=2, excluded=["*/.git/*"], included=["*.py"])
    argv = build_name_argv(current_spec("report md", names=True))
    if argv[0] == "stdbuf":
        argv = argv[2:]
    # No archive flag, no fuzziness and no inclusion glob: none of them mean
    # anything to a name.
    assert argv == [
        "find", "/f", "-mindepth", "1",
        "(", "-path", "*/.git", ")", "-prune", "-o",
        "-iname", "*report*", "-iname", "*md*",
        "-print",
    ]


# -- searching ---------------------------------------------------------------


def test_a_name_search_lists_folders_and_empty_files(conf, name_tree, search):
    conf(archives=False, excluded=["*/node_modules/*"])
    window = search(name_tree, "report", MODE_NAMES)
    assert sorted(labels(window)) == REPORT_NAMES
    assert window.results.item(0).data(HIT_ROLE).member == ""
    assert status(window).startswith("3 items found in ")


def test_content_mode_still_searches_contents(conf, name_tree, search):
    """The same query, the other mode: the text, not the names."""
    conf(archives=False, excluded=["*/node_modules/*"])
    window = search(name_tree, "report", MODE_CONTENT)
    assert sorted(labels(window)) == ["My Report.md", "unrelated.txt"]


def test_every_word_has_to_be_in_the_name(conf, name_tree, search):
    conf(archives=False)
    assert labels(search(name_tree, "md report", MODE_NAMES)) == ["My Report.md"]


def test_a_glob_word_matches_the_whole_name(conf, name_tree, search):
    conf(archives=False)
    assert labels(search(name_tree, "*.MD", MODE_NAMES)) == ["My Report.md"]


def test_exclusions_apply_and_inclusions_do_not(conf, name_tree, search):
    conf(archives=False, excluded=[], included=["*.py"])
    assert sorted(labels(search(name_tree, "report", MODE_NAMES))) == sorted(
        REPORT_NAMES + [os.path.join("node_modules", "report.js")]
    )


def test_a_root_named_like_an_exclusion_is_still_searched(conf, tmp_path, search):
    root = tmp_path / "node_modules"
    root.mkdir()
    (root / "report.txt").write_bytes(b"")
    conf(archives=False, excluded=["*/node_modules/*"])
    assert labels(search(str(root), "report", MODE_NAMES)) == ["report.txt"]


def test_no_matches(conf, name_tree, search):
    conf(archives=False)
    window = search(name_tree, "zzzz", MODE_NAMES)
    assert labels(window) == []
    assert status(window).startswith("No matches in ")


@needs_permissions
def test_an_unreadable_folder_is_not_an_error(conf, guarded_tree, search, dialogs):
    """find exits 1 for a folder it may not open; that is not a failure."""
    conf(archives=False)
    window = search(guarded_tree, "found", MODE_NAMES)
    assert labels(window) == ["found.txt"]
    assert dialogs == []
    assert status(window) != STATUS_FAILED


def test_a_slash_in_a_name_query_is_refused(conf, name_tree, qtbot, dialogs):
    conf(archives=False)
    window = MainWindow(name_tree)
    qtbot.addWidget(window)
    window.mode_combo.setCurrentText(MODE_NAMES)
    window.query_edit.setText("ReportDir/sub")
    window.start_search()
    assert len(dialogs) == 1 and "'/'" in dialogs[0][1]
    assert not window._runner.is_running()
    assert labels(window) == []


# -- the rows ----------------------------------------------------------------


def test_a_folder_row_previews_a_notice_and_opens_in_the_file_manager(
    conf, name_tree, search, spawned
):
    conf(archives=False, excluded=["*/node_modules/*"])
    window = search(name_tree, "report", MODE_NAMES)
    select(window, "ReportDir")

    assert window.panel.text.toPlainText() == FOLDER_NOTICE
    assert nav(window) == (False, "")
    assert window.panel.open_button.isEnabled()
    assert window.panel.open_button.toolTip() == OPEN_TIP_FOLDER

    window.panel.open_button.click()
    assert spawned == [[NOOP_OPENER, os.path.join(name_tree, "ReportDir")]]


def test_a_file_row_previews_with_nothing_highlighted(conf, name_tree, search):
    """The query matched the name; the `report` in the text is not a match."""
    conf(archives=False, excluded=["*/node_modules/*"])
    window = search(name_tree, "report", MODE_NAMES)
    select(window, "My Report.md")

    assert window.panel.text.toPlainText() == "a report inside\n"
    assert highlighted(window) == []
    assert nav(window) == (False, "")


def test_the_mode_is_pinned_with_the_results(conf, name_tree, search):
    """Switching the dropdown after a search changes nothing on screen.

    Both directions: rows from a name search stay unhighlighted, and rows
    from a content search keep their highlights.
    """
    conf(archives=False, excluded=["*/node_modules/*"])

    names = search(name_tree, "report", MODE_NAMES)
    names.mode_combo.setCurrentText(MODE_CONTENT)
    select(names, "My Report.md")
    assert highlighted(names) == []

    content = search(name_tree, "report", MODE_CONTENT)
    content.mode_combo.setCurrentText(MODE_NAMES)
    select(content, "My Report.md")
    assert highlighted(content) == ["report"]
    assert content.results.currentItem().data(HIT_ROLE) == Hit(
        os.path.join(name_tree, "My Report.md"), ""
    )
