"""`SearchSpec`: one read of the config per search, pinned for its results.

The argv builders are covered where their flags are (`test_window`,
`test_names`, `test_fuzzy`); this is what the spec itself promises — which
settings each kind of search carries, and that building one is the only
time a search looks at the config.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from sonarex import config
from sonarex.config import Settings
from sonarex.spec import SearchSpec, search_problems
from sonarex.window import MainWindow

SETTINGS = Settings(
    included=["*.md"],
    excluded=["*/build/*"],
    archives=True,
    archive_depth=2,
    open_command="true",
    fuzzy=1,
)


def test_a_content_search_carries_depth_fuzz_and_globs():
    spec = SearchSpec.from_settings(SETTINGS, "q", "/f")
    assert (spec.names, spec.depth, spec.fuzzy) == (False, 2, 1)
    assert spec.globs == ("-g", "!build/", "-g", "*.md")
    assert spec.prune == ()


def test_a_name_search_carries_only_the_prune_clause():
    """None of the content settings mean anything to a name, and they must
    not shape how its rows are read back either."""
    spec = SearchSpec.from_settings(SETTINGS, "q", "/f", names=True)
    assert (spec.names, spec.depth, spec.fuzzy, spec.globs) == (True, 0, 0, ())
    assert spec.prune == ("(", "-path", "*/build", ")", "-prune", "-o")


def test_archives_off_is_depth_zero_whatever_the_depth():
    spec = SearchSpec.from_settings(SETTINGS._replace(archives=False), "q", "/f")
    assert spec.depth == 0


def test_switched_off_lists_are_not_applied():
    off = SETTINGS._replace(use_included=False, use_excluded=False)
    assert SearchSpec.from_settings(off, "q", "/f").globs == ()
    assert SearchSpec.from_settings(off, "q", "/f", names=True).prune == ()


def test_problems_only_count_the_lists_a_search_applies():
    bad = SETTINGS._replace(included=["docs/*.md"], excluded=["docs/*.tmp"])
    assert len(search_problems(bad)) == 2
    assert len(search_problems(bad, names=True)) == 1
    assert search_problems(bad._replace(use_included=False, use_excluded=False)) == []


def test_a_spec_cannot_be_changed_once_pinned():
    spec = SearchSpec("q", "/f")
    with pytest.raises(FrozenInstanceError):
        spec.depth = 3  # type: ignore[misc]


def test_one_search_reads_the_config_once(conf, tree, qtbot, monkeypatch):
    """The pattern check and the search itself share a single read — the
    window used to parse the file six times per Search press, and the
    values it pinned came from different reads than the argv it ran."""
    conf(archives=True, fuzzy=1)
    reads = []
    real = config.read_config
    monkeypatch.setattr(config, "read_config", lambda: reads.append(1) or real())

    window = MainWindow(tree)
    qtbot.addWidget(window)
    window.query_edit.setText("needle")
    with qtbot.waitSignal(window._runner.finished, timeout=10000):
        window.start_search()
    assert len(reads) == 1
    assert (window._search.depth, window._search.fuzzy) == (1, 1)
