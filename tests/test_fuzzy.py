"""Find near matches: what --fuzzy widens, and what it deliberately does not.

`fuzzy_tree` holds one word at four known edit distances, so every assertion
here is on the exact set of files a setting returns rather than on "more than
before". These run a real ugrep, like the rest of the suite, because the whole
feature is one flag and everything interesting about it is ugrep's behavior.
"""

from __future__ import annotations

from helpers import highlighted, labels, select
from sonarex.archive import Hit
from sonarex.search import match_spans


def test_off_is_exact(conf, fuzzy_tree, search):
    conf(archives=False, fuzzy=0)
    assert labels(search(fuzzy_tree, "color")) == ["exact.txt"]


def test_one_character_reaches_one_edit_away(conf, fuzzy_tree, search):
    """`colour` is an inserted u; `collour` is that plus an inserted l, so it
    is two away and must stay out at this setting."""
    conf(archives=False, fuzzy=1)
    assert sorted(labels(search(fuzzy_tree, "color"))) == ["exact.txt", "near.txt"]


def test_two_characters_reach_two_edits_away(conf, fuzzy_tree, search):
    conf(archives=False, fuzzy=2)
    assert sorted(labels(search(fuzzy_tree, "color"))) == [
        "exact.txt",
        "far.txt",
        "near.txt",
    ]


# -- the first character ---------------------------------------------------


def test_a_wrong_first_letter_is_never_forgiven(conf, fuzzy_tree, search):
    """ugrep: "The first character of an approximate match always matches a
    character at the beginning of the pattern."

    `dolor` is exactly one edit from the `color` in exact.txt, so without that
    rule this would match at every setting. It matches at none — which is also
    why a two-letter query does not return the whole disk, and why raising the
    ceiling is not the danger it looks like.
    """
    for level in (1, 2, 3):
        conf(archives=False, fuzzy=level)
        assert labels(search(fuzzy_tree, "dolor")) == []


def test_a_wrong_last_letter_is(conf, fuzzy_tree, search):
    """The other half of the pair: same word, same one edit, different end."""
    conf(archives=False, fuzzy=1)
    assert "exact.txt" in labels(search(fuzzy_tree, "colot"))


# -- what the flag applies to ----------------------------------------------


def test_a_quoted_phrase_goes_fuzzy_too(conf, fuzzy_tree, search):
    """--fuzzy is a property of the matcher, not of one kind of term, so a
    quoted literal is approximate as well: "color of" reaches "colour of"."""
    conf(archives=False, fuzzy=1)
    window = search(fuzzy_tree, '"color of"')
    assert sorted(labels(window)) == ["exact.txt", "near.txt"]

    select(window, "near.txt")
    assert highlighted(window) == ["colour of"]


def test_a_regex_goes_fuzzy_on_top_of_itself(conf, fuzzy_tree, search):
    """The edits are applied over the regex rather than instead of it:
    `col(o|ou)r` already reaches `colour` on its own, and one edit further
    reaches `collour` as well."""
    conf(archives=False, fuzzy=0)
    assert sorted(labels(search(fuzzy_tree, "col(o|ou)r"))) == [
        "exact.txt",
        "near.txt",
    ]

    conf(archives=False, fuzzy=1)
    assert sorted(labels(search(fuzzy_tree, "col(o|ou)r"))) == [
        "exact.txt",
        "far.txt",
        "near.txt",
    ]


def test_fuzzy_and_archives_compose(conf, fuzzy_tree, search):
    """Both are flags on the same argv, and neither cancels the other."""
    conf(archives=True, depth=1, fuzzy=1)
    assert "shades.zip → inner/tint.txt" in labels(search(fuzzy_tree, "color"))


# -- the preview -----------------------------------------------------------


def test_the_approximate_text_is_what_gets_highlighted(conf, fuzzy_tree, search):
    """ugrep reports where it actually matched — `%j` is "colour", not the
    "color" that was typed — so the highlighter needs to know nothing about
    any of this and marks the real span."""
    conf(archives=False, fuzzy=1)
    window = search(fuzzy_tree, "color")

    select(window, "near.txt")
    assert highlighted(window) == ["colour"]

    select(window, "exact.txt")
    assert highlighted(window) == ["color"]


def test_the_preview_needs_the_setting_the_search_ran_with(conf, fuzzy_tree):
    """The guard on pinning `_search_fuzzy` alongside `_search_depth`.

    Re-running at 0 finds nothing in a file the search plainly listed, so a
    preview that read the setting fresh instead of the pinned one would mark
    nothing the moment someone changed it mid-session.
    """
    conf(archives=False, fuzzy=1)
    hit = Hit(f"{fuzzy_tree}/near.txt", "")

    assert match_spans("color", hit, 0, 1) == {0: [(5, 6)]}
    assert match_spans("color", hit, 0, 0) == {}
