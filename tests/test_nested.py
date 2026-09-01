"""Archives inside archives: what `--zmax` reaches, and how it is labelled.

The fixture is a zip holding a tarball holding a zip holding a text file, so
reaching the bottom takes three expansion stages. ugrep reports that as one
`%z` with the levels colon-joined, and the window turns it into a chain of
arrows.
"""

from __future__ import annotations

import os

import pytest

from helpers import highlighted, labels, nav, select
from sonarex import viewer
from sonarex.archive import Hit
from sonarex.viewer import read_for_preview
from sonarex.window import HIT_ROLE

# What ugrep calls the file at the bottom, and what the window shows instead.
CHAIN = "L2.tar.gz:L3.zip:inner.txt"
DEEP_ROW = "L1.zip → L2.tar.gz → L3.zip → inner.txt"
TOP_ROW = "L1.zip → top.txt"
DEEP_TEXT = "level three needle here\nsecond needle line\n"


def test_depth_one_does_not_reach_the_nested_file(conf, nested_tree, search):
    """--zmax=1 treats an archive inside an archive as a binary file. The
    tarball's compressed bytes do not contain the word, so it is simply not a
    hit — only the file at the top level is."""
    conf(archives=True, depth=1)
    assert labels(search(nested_tree, "needle")) == [TOP_ROW]


def test_depth_three_reaches_it(conf, nested_tree, search):
    conf(archives=True, depth=3)
    assert sorted(labels(search(nested_tree, "needle"))) == sorted([DEEP_ROW, TOP_ROW])


def test_the_row_shows_the_chain_but_keeps_the_raw_member(conf, nested_tree, search):
    """The arrows are a display detail. Everything functional — extraction,
    spans, the %z filter — matches the colon-joined string ugrep gave us."""
    conf(archives=True, depth=3)
    window = search(nested_tree, "needle")
    item = select(window, DEEP_ROW)
    assert item.data(HIT_ROLE) == Hit(f"{nested_tree}/L1.zip", CHAIN)
    assert item.toolTip() == f"{nested_tree}/L1.zip\n  L2.tar.gz\n    L3.zip\n      inner.txt"


def test_a_nested_member_previews_and_steps(conf, nested_tree, search):
    conf(archives=True, depth=3)
    window = search(nested_tree, "needle")
    select(window, DEEP_ROW)
    assert window.preview.toPlainText() == DEEP_TEXT
    assert highlighted(window) == ["needle", "needle"]
    assert nav(window) == (True, "1 of 2")

    window._step_match(1)
    assert window.match_label.text() == "2 of 2"


def test_the_top_level_sibling_still_works(conf, nested_tree, search):
    conf(archives=True, depth=3)
    window = search(nested_tree, "needle")
    select(window, TOP_ROW)
    assert window.preview.toPlainText() == "plain needle at level one\n"
    assert highlighted(window) == ["needle"]


def test_open_extracts_from_the_bottom_of_the_chain(conf, nested_tree, search):
    """The temp copy is named for the innermost file, not the whole chain: a
    file called `L2.tar.gz:L3.zip:inner.txt` would tell the editor it is
    looking at a tarball."""
    conf(archives=True, depth=3)
    window = search(nested_tree, "needle")
    item = select(window, DEEP_ROW)

    assert viewer.open_in_editor(item.data(HIT_ROLE), window._search_depth) is None
    copies = [
        os.path.join(root, name)
        for root, _dirs, names in os.walk(viewer._temp_root)
        for name in names
    ]
    assert len(copies) == 1
    assert os.path.basename(copies[0]) == "inner.txt"
    assert open(copies[0], "rb").read() == DEEP_TEXT.encode()


@pytest.mark.parametrize(
    "depth, is_notice", [(1, True), (3, False)], ids=["wrong-depth", "right-depth"]
)
def test_the_preview_needs_the_depth_the_search_used(nested_tree, depth, is_notice):
    """This is why `_search_depth` is pinned at the start of a search rather
    than read fresh at preview time: at the wrong --zmax the member is simply
    not there, and a file plainly on screen comes back unreadable."""
    assert read_for_preview(Hit(f"{nested_tree}/L1.zip", CHAIN), depth)[1] is is_notice


# -- the colon that is not a level -----------------------------------------


def test_a_colon_in_a_name_is_not_a_level_at_depth_one(conf, colon_tree, search):
    """A colon is legal in a filename and is also what ugrep puts between
    levels. Below depth 2 there is no chain it could be part of, so a member
    honestly called this stays one name — and stays reachable, which it would
    not be if the glob were built from the half after the colon."""
    conf(archives=True, depth=1)
    window = search(colon_tree, "needle")
    assert labels(window) == ["odd.zip → notes:draft.txt"]

    select(window, "odd.zip → notes:draft.txt")
    assert window.preview.toPlainText() == "colon needle here\n"
    assert highlighted(window) == ["needle"]
