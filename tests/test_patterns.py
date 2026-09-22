"""The include and exclude lists, run for real in both search modes.

`test_config.py` pins what the lists translate to — the `-g` globs and the
`find` prune clause — as strings. This file pins what those strings *do*,
against a real ugrep and a real find, because the translation is exactly the
kind of thing that reads right as an argv and means something else to the
program: gitignore-style globs anchor and cross `/` by rules of their own, and
`find -path` matches against the whole path it was handed.

Every file in `pattern_tree` has `needle` in its name and in its text, so the
same query finds the same set in either mode and any difference is the
pattern's doing.
"""

from __future__ import annotations

import os

import pytest

from helpers import highlighted, labels, select
from sonarex import config
from sonarex.search import MODE_CONTENT, MODE_NAMES
from sonarex.window import MainWindow

MODES = pytest.mark.parametrize("mode", [MODE_CONTENT, MODE_NAMES])

# Everything a search of the tree lists with nothing excluded. No folder has
# `needle` in its name, so a name search lists exactly these files too — which
# is what keeps the two modes' sets comparable. Content mode lists all but the
# zip, whose deflated bytes do not hold the word while archives are off.
LOOSE = [
    "needle-a.md",
    "needle-app.log",
    "needle-b.txt",
    "needle-bundle.zip",
    os.path.join("node_modules", "needle-mod.txt"),
    os.path.join("other", "generated", "needle-other.txt"),
    os.path.join("pkg", "node_modules", "needle-deep.txt"),
    os.path.join("src", "generated", "needle-gen.txt"),
]


def rows(search, folder, mode):
    return sorted(labels(search(folder, "needle", mode)))


def without(*gone):
    return sorted(row for row in LOOSE if row not in gone)


# -- exclusions --------------------------------------------------------------


@MODES
def test_nothing_excluded_lists_everything(conf, pattern_tree, search, mode):
    """The baseline the other tests subtract from. The zip is deflated, so
    with archives off a content search cannot see the word inside it; its
    name carries the word, so a name search lists it."""
    conf(archives=False)
    expected = LOOSE if mode == MODE_NAMES else without("needle-bundle.zip")
    assert rows(search, pattern_tree, mode) == expected


@MODES
def test_a_directory_is_skipped_at_any_depth(conf, pattern_tree, search, mode):
    conf(archives=False, excluded=["*/node_modules/*"])
    gone = [
        os.path.join("node_modules", "needle-mod.txt"),
        os.path.join("pkg", "node_modules", "needle-deep.txt"),
    ]
    if mode == MODE_CONTENT:
        gone.append("needle-bundle.zip")
    assert rows(search, pattern_tree, mode) == without(*gone)


@MODES
def test_a_nested_path_skips_that_path_only(conf, pattern_tree, search, mode):
    """`*/src/generated/*` must not take `other/generated` with it: a nested
    pattern is a path, not the basename `generated` anywhere."""
    conf(archives=False, excluded=["*/src/generated/*"])
    gone = [os.path.join("src", "generated", "needle-gen.txt")]
    if mode == MODE_CONTENT:
        gone.append("needle-bundle.zip")
    assert rows(search, pattern_tree, mode) == without(*gone)


@MODES
def test_a_file_is_skipped_by_name(conf, pattern_tree, search, mode):
    conf(archives=False, excluded=["*.log"])
    gone = ["needle-app.log"]
    if mode == MODE_CONTENT:
        gone.append("needle-bundle.zip")
    assert rows(search, pattern_tree, mode) == without(*gone)


@MODES
def test_the_exclusions_switch_off_reaches_the_skipped_folders(
    conf, pattern_tree, search, mode
):
    conf(archives=False, excluded=["*/node_modules/*"], use_excluded=False)
    expected = LOOSE if mode == MODE_NAMES else without("needle-bundle.zip")
    assert rows(search, pattern_tree, mode) == expected


# A known limitation, kept rather than fixed: ugrep applies `!node_modules/` to
# the folder it is handed as well as to the ones below it, so a content search
# *inside* an excluded folder finds nothing. find never tests its root
# (`-mindepth 1`), so the name search does not share it. The obvious fix —
# handing ugrep `folder/.` — stops nested patterns such as `*/src/generated/*`
# matching at all, and the guide tells the user to untick Skip instead.
ROOT_EXCLUDED = pytest.mark.xfail(
    strict=True,
    reason="ugrep applies a directory exclusion to the search root itself",
)


@pytest.mark.parametrize(
    "mode", [pytest.param(MODE_CONTENT, marks=ROOT_EXCLUDED), MODE_NAMES]
)
def test_a_root_named_like_an_exclusion_is_still_searched(
    conf, pattern_tree, search, mode
):
    """Opening Sonar *in* a `node_modules` folder means that folder is what
    should be searched; the exclusion is for folders met on the way down."""
    root = os.path.join(pattern_tree, "pkg", "node_modules")
    conf(archives=False, excluded=["*/node_modules/*"])
    assert rows(search, root, mode) == ["needle-deep.txt"]


def test_unticking_skip_searches_inside_an_excluded_root(conf, pattern_tree, search):
    """What the guide tells the user to do about it, and that it works."""
    root = os.path.join(pattern_tree, "pkg", "node_modules")
    conf(archives=False, excluded=["*/node_modules/*"], use_excluded=False)
    assert rows(search, root, MODE_CONTENT) == ["needle-deep.txt"]


@ROOT_EXCLUDED
def test_a_root_below_a_skipped_folder_is_searched_too(conf, tmp_path, search):
    """And a nested `node_modules` under that root is still skipped."""
    root = tmp_path / "node_modules"
    (root / "inner" / "node_modules").mkdir(parents=True)
    (root / "top.txt").write_bytes(b"needle\n")
    (root / "inner" / "mid.txt").write_bytes(b"needle\n")
    (root / "inner" / "node_modules" / "deep.txt").write_bytes(b"needle\n")
    conf(archives=False, excluded=["*/node_modules/*"])
    window = search(str(root), "needle")
    assert sorted(labels(window)) == [os.path.join("inner", "mid.txt"), "top.txt"]


# -- the whitelist -----------------------------------------------------------


def test_a_whitelist_narrows_a_content_search(conf, pattern_tree, search):
    conf(archives=False, included=["*.md"])
    assert rows(search, pattern_tree, MODE_CONTENT) == ["needle-a.md"]


def test_the_whitelist_switch_off_widens_it_again(conf, pattern_tree, search):
    conf(archives=False, included=["*.md"], use_included=False)
    assert rows(search, pattern_tree, MODE_CONTENT) == without("needle-bundle.zip")


def test_a_whitelist_filters_archive_members_not_archives(conf, pattern_tree, search):
    """With -z, `included:` applies to the names *inside* an archive: the zip
    is still opened although `*.zip` is not on the list, and only its
    Markdown member is listed. The config file's comment says so; this is
    what holds it to that."""
    conf(archives=True, included=["*.md"])
    assert rows(search, pattern_tree, MODE_CONTENT) == [
        "needle-a.md",
        "needle-bundle.zip → x.md",
    ]


def test_highlights_survive_a_whitelist(conf, pattern_tree, search):
    """The highlight run is its own ugrep over one named file, and must not
    carry the config's globs — `-g` filters a file named on the command line
    too. Inside an archive its `-g` is the member's basename instead, which
    the whitelist has already let through."""
    conf(archives=True, included=["*.md"])
    window = search(pattern_tree, "needle")
    select(window, "needle-a.md")
    assert highlighted(window) == ["needle"]
    select(window, "needle-bundle.zip → x.md")
    assert highlighted(window) == ["needle"]


# -- the pattern helpers -----------------------------------------------------


@pytest.mark.parametrize(
    "pattern, expected",
    [
        ("*/node_modules/*", "!node_modules/"),
        ("*/src/generated/*", "!**/src/generated/**"),
        # ugrep's `*` never crosses a '/', so `!*/docs/*.tmp` would skip
        # nothing; `**/` is what matches at any depth.
        ("*/docs/*.tmp", "!**/docs/*.tmp"),
        ("*.log", "!*.log"),
    ],
)
def test_convert_excluded_pattern(pattern, expected):
    assert config.convert_excluded_pattern(pattern) == expected


def test_parse_pattern_lines():
    """Blank lines and surrounding space never become a pattern: an empty
    glob is one ugrep takes as matching nothing at all."""
    assert config.parse_pattern_lines("  *.md \n\n*.py\r\n\t\n") == ["*.md", "*.py"]
    assert config.parse_pattern_lines("") == []
    assert config.pattern_lines(["*.md", "*.py"]) == "*.md\n*.py"


# -- patterns that cannot work -----------------------------------------------
#
# Neither program ever complains about these: a bad include empties every
# search, a bad skip pattern skips nothing. So Sonar refuses them itself.


@MODES
def test_a_file_pattern_under_a_folder_is_skipped(conf, tmp_path, search, mode):
    """`*/docs/*.tmp`: the one shape that used to work in Filenames mode and
    skip nothing in Content mode."""
    root = tmp_path / "tree"
    for name in ["docs/needle.tmp", "deep/docs/needle.tmp", "docs/needle.txt", "needle.tmp"]:
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_bytes(b"needle\n")
    conf(archives=False, excluded=["*/docs/*.tmp"])
    assert rows(search, str(root), mode) == [os.path.join("docs", "needle.txt"), "needle.tmp"]


@pytest.mark.parametrize(
    "included, excluded, bad",
    [
        pytest.param(["*.md", "*.py"], [], [], id="include-ok"),
        pytest.param(["docs/*.md"], [], ["docs/*.md"], id="include-with-slash"),
        # Works on its own, but means only what `*.md` does, and `**/gen/*`
        # beside `*.md` narrows the whole list to one folder. No '/' at all.
        pytest.param(["**/*.md"], [], ["**/*.md"], id="include-with-globstar"),
        pytest.param([], ["*/build/*", "*/docs/*.tmp", "*.log"], [], id="skip-ok"),
        pytest.param([], ["docs/*.tmp"], ["docs/*.tmp"], id="skip-without-leading-star"),
        pytest.param([], ["/abs/docs/*"], ["/abs/docs/*"], id="skip-absolute"),
        pytest.param(["a/b", "*.md"], ["c/d", "*/e/*"], ["a/b", "c/d"], id="one-per-bad-line"),
    ],
)
def test_pattern_problems(included, excluded, bad):
    problems = config.pattern_problems(included, excluded)
    assert len(problems) == len(bad)
    for pattern, message in zip(bad, problems):
        assert f'"{pattern}"' in message


def test_a_skip_problem_suggests_the_fix():
    [message] = config.pattern_problems([], ["docs/*.tmp"])
    assert '"*/docs/*.tmp"' in message


def test_search_problems_only_count_the_lists_in_force(conf):
    conf(included=["docs/*.md"], excluded=["docs/*.tmp"])
    assert len(config.search_pattern_problems()) == 2
    # A name search applies no include list at all.
    assert len(config.search_pattern_problems(names=True)) == 1

    conf(included=["docs/*.md"], excluded=["docs/*.tmp"],
         use_included=False, use_excluded=False)
    assert config.search_pattern_problems() == []


def start(qtbot, folder, mode=MODE_CONTENT):
    window = MainWindow(folder)
    qtbot.addWidget(window)
    window.query_edit.setText("needle")
    window.mode_combo.setCurrentText(mode)
    window.start_search()
    return window


@MODES
def test_a_bad_include_stops_a_content_search_only(conf, pattern_tree, qtbot, dialogs, mode):
    conf(archives=False, included=["docs/*.md"])
    window = start(qtbot, pattern_tree, mode)
    if mode == MODE_CONTENT:
        assert len(dialogs) == 1
        assert '"docs/*.md"' in dialogs[0][1]
        assert "Options ▸ Settings" in dialogs[0][1]
        assert not window._runner.is_running()
    else:
        assert dialogs == []
        assert window._runner.is_running()


@MODES
def test_a_bad_skip_pattern_stops_either_search(conf, pattern_tree, qtbot, dialogs, mode):
    conf(archives=False, excluded=["docs/*.tmp"])
    window = start(qtbot, pattern_tree, mode)
    assert len(dialogs) == 1 and '"docs/*.tmp"' in dialogs[0][1]
    assert not window._runner.is_running()
    assert labels(window) == []


def test_a_bad_pattern_in_a_list_switched_off_does_not(conf, pattern_tree, search, dialogs):
    conf(archives=False, included=["docs/*.md"], use_included=False)
    window = search(pattern_tree, "needle")
    assert dialogs == []
    assert labels(window)
