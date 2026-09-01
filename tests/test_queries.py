"""Boolean query shapes, checked by what they highlight inside an archive.

`build_argv` passes `-%` and `--files`, so a query is a Boolean expression
evaluated over the whole file. `match_spans` re-runs with the same two flags,
which is what makes the marked words the same terms that selected the file.
These assert on the highlighting rather than on the result list, because that
is where the two runs have to agree.
"""

from __future__ import annotations

import pytest

from helpers import highlighted, labels, select
from sonarex.search import literal_query_term, search_error


def test_and_across_lines_highlights_both_terms(conf, tree, search):
    """--files evaluates at whole-file scope, so terms on different lines both
    match and both get marked. doc/one.txt is "alpha needle here" then
    "second needle line"."""
    conf(archives=True)
    window = search(tree, "alpha line")
    assert "docs.zip → doc/one.txt" in labels(window)

    select(window, "docs.zip → doc/one.txt")
    assert sorted(highlighted(window)) == ["alpha", "line"]


def test_or_marks_only_the_branch_that_matched(conf, tree, search):
    conf(archives=True)
    window = search(tree, "alpha OR zzznope")
    select(window, "docs.zip → doc/one.txt")
    assert highlighted(window) == ["alpha"]


def test_a_negated_term_excludes_and_marks_nothing(conf, tree, search):
    """A NOT term is what the file must *not* contain, so it selected nothing
    to highlight — marking it would colour text the search never matched."""
    conf(archives=True)
    window = search(tree, "needle -bracket")
    assert "docs.zip → doc/a[1].txt" not in labels(window)

    select(window, "docs.zip → doc/one.txt")
    assert highlighted(window) == ["needle", "needle"]


def test_a_quoted_phrase_is_literal(conf, tree, search):
    conf(archives=True)
    window = search(tree, '"second needle"')
    select(window, "docs.zip → doc/one.txt")
    assert highlighted(window) == ["second needle"]


def test_a_query_starting_with_a_dash_is_a_query(conf, tree, search):
    """`--` before the query is load-bearing: without it ugrep parses this as
    an option and the search fails instead of running."""
    conf(archives=True)
    window = search(tree, "-bracket")
    assert any(row.startswith("docs.zip") for row in labels(window))


def test_a_folder_with_spaces(conf, tmp_path, search):
    """The folder reaches ugrep as one argv element, so a space in it is not a
    second argument."""
    folder = tmp_path / "a folder with spaces"
    folder.mkdir()
    (folder / "note.txt").write_bytes(b"spaced needle here\n")

    conf(archives=True)
    window = search(str(folder), "needle")
    assert labels(window) == ["note.txt"]


def test_a_bad_regex_is_reported_not_raised(conf, tree, search, dialogs):
    """ugrep exits above 1 and the window reports it in a dialog, rather than
    raising out of a signal handler.

    `dialogs` is what makes this runnable at all: a real QMessageBox blocks
    for a click under offscreen and would hang the run.
    """
    conf(archives=True)
    window = search(tree, "col(o|ou")
    assert labels(window) == []
    assert len(dialogs) == 1
    assert "col(o|ou" in dialogs[0][1] or "error" in dialogs[0][1].lower()


# -- telling a skipped file from a failed search ---------------------------


@pytest.mark.parametrize(
    "stderr, expected",
    [
        pytest.param(
            "ugrep: cannot decompress /t/locked.zip: zip data is encrypted",
            "",
            id="encrypted-archive",
        ),
        pytest.param(
            "ugrep: cannot decompress /t/bad.zip: corrupt zip archive",
            "",
            id="corrupt-archive",
        ),
        pytest.param(
            "ugrep: warning: cannot open directory /t/sub: Permission denied",
            "",
            id="permission-denied",
        ),
        pytest.param("", "", id="nothing-said"),
        # A bad regex runs on for two more lines carrying no marker at all, so
        # the filter has to work per line and keep what it does not recognise.
        pytest.param(
            "ugrep: error: error at position 13\n(?mi)col(o|ou\n   \\___mismatched ( )",
            "ugrep: error: error at position 13\n(?mi)col(o|ou\n   \\___mismatched ( )",
            id="bad-regex-kept-whole",
        ),
        pytest.param(
            "ugrep: warning: cannot open directory /t/sub: Permission denied\n"
            "ugrep: error: error at position 13",
            "ugrep: error: error at position 13",
            id="a-real-error-beside-a-warning",
        ),
        pytest.param(
            "Could not run ugrep. Is it installed?",
            "Could not run ugrep. Is it installed?",
            id="failed-to-start",
        ),
    ],
)
def test_search_error_keeps_only_real_failures(stderr, expected):
    """ugrep's exit status cannot answer this — it is 2 for both a failed
    search and a file that was merely skipped, and which one an encrypted
    archive counts as differs between builds. The text decides instead."""
    assert search_error(stderr) == expected


# -- the PDF pane's one-string translation ---------------------------------


def test_literal_query_term_translations():
    """Qt's PDF search takes one literal string: no regex, no AND/OR, no
    negation. Terms that cannot survive that are dropped rather than
    approximated, since a regex searched literally would mark text the search
    never matched."""
    assert literal_query_term('"hello world" foo') == "hello world"
    assert literal_query_term("cat dog") == "cat"
    assert literal_query_term("-secret cat") == "cat"
    assert literal_query_term("col(o|ou)r") is None
    assert literal_query_term("-font") is None
