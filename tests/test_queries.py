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
from sonarex.archive import Hit
from sonarex.search import literal_query_term, match_spans, search_error
from sonarex.window import MainWindow


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


@pytest.mark.parametrize(
    "query, expected",
    [
        # The keyword form of NOT negates the term after it, exactly as the
        # dash does — so that term must be skipped, not picked.
        pytest.param("NOT dog cat", "cat", id="not-first"),
        pytest.param("cat NOT dog", "cat", id="not-second"),
        pytest.param("NOT dog", None, id="not-only"),
        pytest.param('NOT "dog food" cat', "cat", id="not-phrase"),
        pytest.param("cat OR dog", "cat", id="or"),
        pytest.param("(cat OR dog) fish", "cat", id="grouped"),
        pytest.param("'single quoted'", "single quoted", id="single-quotes"),
        pytest.param('"unbalanced', None, id="unbalanced"),
        pytest.param('""', None, id="empty-phrase"),
        pytest.param("AND OR", None, id="only-operators"),
    ],
)
def test_literal_query_term_edge_cases(query, expected):
    assert literal_query_term(query) == expected


# -- more query shapes -----------------------------------------------------


@pytest.mark.parametrize(
    "query, present, absent",
    [
        # The keyword spellings of what the other tests use the short form of.
        pytest.param("needle NOT bracket", "doc/one.txt", "doc/a[1].txt", id="not-keyword"),
        pytest.param("alpha AND second", "doc/one.txt", "doc/sub/one.txt", id="and-keyword"),
        pytest.param("(alpha OR bracket) file", "doc/a[1].txt", "doc/one.txt", id="grouping"),
        # Unquoted terms are regexes.
        pytest.param("^second", "doc/one.txt", "doc/sub/one.txt", id="anchor"),
        pytest.param(r"\bneedle\b deep", "doc/sub/one.txt", "doc/one.txt", id="word-boundary"),
    ],
)
def test_query_shapes_select_the_right_members(conf, tree, search, query, present, absent):
    conf(archives=True)
    rows = labels(search(tree, query))
    assert f"docs.zip → {present}" in rows
    assert f"docs.zip → {absent}" not in rows


def test_a_search_ignores_case_and_so_does_the_highlight(conf, tree, search):
    conf(archives=False)
    window = search(tree, "NEEDLE")
    select(window, "loose.txt")
    assert highlighted(window) == ["needle"]


def test_an_anchored_regex_highlights_only_where_it_matched(conf, tree, search):
    conf(archives=True)
    window = search(tree, "^second")
    select(window, "docs.zip → doc/one.txt")
    assert highlighted(window) == ["second"]


def test_a_blank_query_starts_nothing(conf, tree, qtbot):
    conf(archives=False)
    window = MainWindow(tree)
    qtbot.addWidget(window)
    window.query_edit.setText("   ")
    window.start_search()
    assert not window._runner.is_running()
    assert labels(window) == []


def test_the_query_is_trimmed(conf, tree, search):
    conf(archives=False)
    window = search(tree, "  loose  ")
    assert labels(window) == ["loose.txt"]
    assert window._search_query == "loose"


# -- where the highlight lands ---------------------------------------------


def test_a_tab_is_one_column(tmp_path):
    """ugrep's `%k` expands a tab to the next multiple of 8 by default, which
    puts every match after one in the wrong place — `\tneedle` came back as
    column 9. The highlighter counts characters, so a tab has to count as one.
    """
    path = tmp_path / "tabs.txt"
    path.write_bytes(b"\tneedle\n\t\tneedle\nx\tneedle\n")
    assert match_spans("needle", Hit(str(path))) == {
        0: [(2, 6)],
        1: [(3, 6)],
        2: [(3, 6)],
    }


@pytest.mark.parametrize("archives", [False, True], ids=["plain", "archives"])
def test_a_tab_indented_file_highlights_the_word(conf, tmp_path, search, archives):
    (tmp_path / "code.go").write_bytes(b"func main() {\n\tneedle := 1\n\t\treturn needle\n}\n")
    conf(archives=archives)
    window = search(str(tmp_path), "needle")
    select(window, "code.go")
    assert highlighted(window) == ["needle", "needle"]


def test_two_matches_on_one_line_and_multibyte_text(tmp_path):
    """Columns are characters, and a match's length is its characters too —
    `café` is four long although it is five bytes."""
    path = tmp_path / "m.txt"
    path.write_bytes("café needle café\n".encode())
    assert match_spans("café", Hit(str(path))) == {0: [(1, 4), (13, 4)]}


def test_a_match_that_is_not_utf8_is_located_not_raised(tmp_path):
    """`%j` passes a Latin-1 byte through raw. Decoding that strictly raised
    UnicodeDecodeError out of the selection handler, and PyQt aborted the
    whole app over it. The bad byte counts as one character, as it does in
    the preview's own "replace" decode, so the column after it still lines
    up."""
    path = tmp_path / "latin.txt"
    path.write_bytes(b"caf\xe9 needle\n")
    assert match_spans("caf. needle", Hit(str(path))) == {0: [(1, 4), (6, 6)]}


def test_a_latin1_file_previews_with_its_match_marked(conf, tmp_path, search):
    (tmp_path / "latin.txt").write_bytes(b"caf\xe9 needle\n")
    conf(archives=False)
    window = search(str(tmp_path), "caf.")
    select(window, "latin.txt")
    assert highlighted(window) == ["caf\ufffd"]


def test_crlf_highlights_on_a_loose_file(conf, tmp_path, search):
    """The same CRLF case the archive tests cover, off the -z path."""
    (tmp_path / "dos.txt").write_bytes(b"first needle\r\nsecond needle\r\n")
    conf(archives=False)
    window = search(str(tmp_path), "needle")
    select(window, "dos.txt")
    assert highlighted(window) == ["needle", "needle"]
