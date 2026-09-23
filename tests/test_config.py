"""The config file: what survives a save, and what a broken one degrades to.

The property being defended throughout is that loading never raises. A missing
file, bad YAML, or a key of the wrong type all have to come back as the
defaults, because the alternative is an app that will not search because of a
typo in a comment.
"""

from __future__ import annotations

import pytest

from helpers import current_spec

from sonarex import config


def test_saving_round_trips(conf):
    conf(archives=True, depth=2, included=["*.md"], excluded=["*/build/*"], fuzzy=2)
    settings, error = config.load_settings()
    assert error is None
    assert settings == config.Settings(
        ["*.md"], ["*/build/*"], True, 2, "/bin/true", 2
    )


def test_saving_rewrites_the_comments(conf):
    """`render_config` re-emits them, because Save rewrites the whole file and
    a first-run template would mean they vanished at the first save."""
    conf()
    text = open(config.CONFIG_PATH).read()
    assert "# Search inside .zip" in text
    assert "# How many levels deep to look" in text
    assert "# Find near matches" in text


def test_unknown_keys_are_carried_through(conf):
    """A setting added by a later version must not be dropped by an older Save."""
    conf()
    open(config.CONFIG_PATH, "w").write(
        "search:\n  included: []\n  excluded: []\n  archives: true\n"
        "  archive_depth: 2\n  somethingelse: 42\n"
        "open:\n  command: \"/bin/true\"\n"
    )
    settings, error = config.load_settings()
    assert error is None
    config.save_settings(settings)

    text = open(config.CONFIG_PATH).read()
    assert "somethingelse: 42" in text
    # Each known key written exactly once. A key missing from render_config's
    # "known" sets gets written twice: once by name, once as an unknown extra.
    assert text.count("archives:") == 1
    assert text.count("archive_depth:") == 1
    assert text.count("fuzzy:") == 1
    assert text.count("use_included:") == 1
    assert text.count("use_excluded:") == 1


def test_use_included_off_drops_only_the_whitelist(conf):
    """The switch sets the inclusions aside; the exclusions stay, and the
    patterns themselves survive in the file."""
    conf(included=["*.md"], excluded=["*/build/*"], use_included=True)
    assert list(current_spec().globs) == ["-g", "!build/", "-g", "*.md"]

    conf(included=["*.md"], excluded=["*/build/*"], use_included=False)
    assert list(current_spec().globs) == ["-g", "!build/"]
    assert config.load_settings()[0].included == ["*.md"]


def test_use_excluded_off_drops_only_the_exclusions(conf):
    """The mirror image, and it reaches the name search's prune clause too, so
    the two modes cannot disagree about whether the list is in force."""
    conf(included=["*.md"], excluded=["*/build/*"], use_excluded=True)
    assert list(current_spec(names=True).prune) == ["(", "-path", "*/build", ")", "-prune", "-o"]

    conf(included=["*.md"], excluded=["*/build/*"], use_excluded=False)
    assert list(current_spec().globs) == ["-g", "*.md"]
    assert list(current_spec(names=True).prune) == []
    assert config.load_settings()[0].excluded == ["*/build/*"]


def test_both_switches_off_is_an_unfiltered_search(conf):
    conf(included=["*.md"], excluded=["*/build/*"], use_included=False, use_excluded=False)
    assert list(current_spec().globs) == []


@pytest.mark.parametrize(
    "body",
    [
        pytest.param('search:\n  included: ["*.md"]\n', id="absent"),
        pytest.param('search:\n  included: ["*.md"]\n  use_included: "no"\n', id="string"),
    ],
)
def test_use_included_defaults_on(conf, body):
    """A file written before the key existed must keep applying its whitelist,
    and a typo must not silently widen the search."""
    conf()
    open(config.CONFIG_PATH, "w").write(body)
    assert config.load_settings()[0].use_included is True
    assert list(current_spec().globs) == ["-g", "*.md"]


def test_the_spec_folds_the_two_depth_keys(conf):
    conf(archives=True, depth=2)
    assert current_spec().depth == 2


def test_depth_is_kept_when_archives_are_off(conf):
    """Clearing the checkbox must not discard the depth that was picked."""
    conf(archives=False, depth=3)
    assert current_spec().depth == 0
    assert config.load_settings()[0].archive_depth == 3


@pytest.mark.parametrize(
    "body, expected",
    [
        pytest.param("search:\n  archives: true\n  archive_depth: 99\n", 3, id="clamped-high"),
        pytest.param("search:\n  archives: true\n  archive_depth: 0\n", 1, id="clamped-low"),
        # bool is a subclass of int in Python, so this one has to be excluded
        # explicitly or `true` would read as the number 1.
        pytest.param("search:\n  archives: true\n  archive_depth: true\n", 1, id="bool-depth"),
        pytest.param('search:\n  archives: true\n  archive_depth: "2"\n', 1, id="string-depth"),
        pytest.param('search:\n  archives: "yes"\n', 0, id="string-archives"),
        pytest.param("search: [this is not a mapping\n", 0, id="broken-yaml"),
        pytest.param("", 0, id="empty-file"),
    ],
)
def test_bad_values_degrade_to_a_default(conf, body, expected):
    conf()
    open(config.CONFIG_PATH, "w").write(body)
    assert current_spec().depth == expected


def test_the_spec_reads_the_one_fuzzy_key(conf):
    """One key, not the pair the depth folds: "off" is a position in the same
    dropdown, so there is no checkbox whose value has to be remembered."""
    conf(fuzzy=2)
    assert current_spec().fuzzy == 2


@pytest.mark.parametrize(
    "body, expected",
    [
        pytest.param("search:\n  fuzzy: 99\n", config.MAX_FUZZY, id="clamped-high"),
        pytest.param("search:\n  fuzzy: -1\n", 0, id="clamped-low"),
        # As with archive_depth: bool subclasses int, so `true` must not read
        # as the number 1 and silently turn approximate matching on.
        pytest.param("search:\n  fuzzy: true\n", 0, id="bool-fuzzy"),
        pytest.param('search:\n  fuzzy: "2"\n', 0, id="string-fuzzy"),
        pytest.param("", 0, id="empty-file"),
    ],
)
def test_bad_fuzzy_values_degrade_to_off(conf, body, expected):
    conf()
    open(config.CONFIG_PATH, "w").write(body)
    assert current_spec().fuzzy == expected


def test_a_missing_file_is_not_an_error(conf, tmp_path):
    config.CONFIG_PATH = str(tmp_path / "does-not-exist.yaml")
    settings, error = config.load_settings()
    assert error is None  # absent is ordinary; unreadable is what gets reported
    assert current_spec().depth == 0
    assert current_spec().fuzzy == 0


def test_broken_yaml_is_reported_to_the_dialog(conf):
    """The dialog warns before offering to Save over a file it could not read."""
    conf()
    open(config.CONFIG_PATH, "w").write("search: [unclosed\n")
    _settings, error = config.load_settings()
    assert error is not None


@pytest.mark.parametrize(
    "body",
    [
        pytest.param('search:\n  excluded: ["*/build/*"]\n', id="absent"),
        pytest.param('search:\n  excluded: ["*/build/*"]\n  use_excluded: 0\n', id="int"),
    ],
)
def test_use_excluded_defaults_on(conf, body):
    """As with `use_included`: an old file keeps skipping what it skipped, and
    a typo must not start searching node_modules."""
    conf()
    open(config.CONFIG_PATH, "w").write(body)
    assert config.load_settings()[0].use_excluded is True
    assert list(current_spec().globs) == ["-g", "!build/"]
