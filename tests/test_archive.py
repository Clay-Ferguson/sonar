"""`sonarex.archive` on its own: parsing, globbing, and extraction.

No window and no Qt here — these are the pure functions plus the one ugrep
call that reads a member back out. Extraction is checked against `unzip -p`
rather than against a literal, so the assertion is "byte for byte what the
archive holds" rather than "what I typed into the fixture twice".
"""

from __future__ import annotations

import shutil
import subprocess
import zipfile

import pytest

from sonarex.archive import (
    Hit,
    extract,
    is_compressed,
    member_glob,
    member_levels,
    member_name,
    parse_result_line,
)
from sonarex.viewer import MAX_PREVIEW_BYTES

from conftest import MEMBERS, TRUNCATED_SURVIVOR, needs_zip


@pytest.mark.parametrize(
    "line, expected",
    [
        # No separator at all: what ugrep prints with archives off, so the
        # same parser has to serve both kinds of search.
        ("/a/b.txt", Hit("/a/b.txt", "")),
        # Trailing separator, empty %z: an ordinary file, archives on.
        ("/a/b.txt\t", Hit("/a/b.txt", "")),
        ("/a/d.zip{doc/one.txt}\tdoc/one.txt", Hit("/a/d.zip", "doc/one.txt")),
        # A tab is legal in a filename, in either half. The split is verified
        # against the braces rather than guessed, so both of these survive.
        ("/a/we\tird.txt\t", Hit("/a/we\tird.txt", "")),
        ("/a/d.zip{x\ty}\tx\ty", Hit("/a/d.zip", "x\ty")),
        # So is a brace.
        ("/a/od{d}.txt\t", Hit("/a/od{d}.txt", "")),
        # Nesting is one %z with the levels colon-joined, not nested braces.
        (
            "/a/L1.zip{L2.tar.gz:L3.zip:inner.txt}\tL2.tar.gz:L3.zip:inner.txt",
            Hit("/a/L1.zip", "L2.tar.gz:L3.zip:inner.txt"),
        ),
    ],
)
def test_parse_result_line(line, expected):
    assert parse_result_line(line) == expected


@pytest.mark.parametrize(
    "member, depth, expected",
    [
        ("doc/one.txt", 1, "one.txt"),
        ("L2.tar.gz:L3.zip:inner.txt", 3, "inner.txt"),
        # A colon in a name is not a level boundary below depth 2, which is
        # what keeps a member honestly called this reachable at all.
        ("notes:draft.txt", 1, "notes:draft.txt"),
    ],
)
def test_member_name(member, depth, expected):
    assert member_name(member, depth) == expected


def test_member_levels_splits_only_above_depth_one():
    chain = "L2.tar.gz:L3.zip:inner.txt"
    assert member_levels(chain, 3) == ["L2.tar.gz", "L3.zip", "inner.txt"]
    assert member_levels(chain, 1) == [chain]
    assert member_levels("notes:draft.txt", 1) == ["notes:draft.txt"]


def test_member_glob_neuters_metacharacters():
    # '?' matches exactly one character, so the substitution is
    # length-preserving and can only widen; the caller filters by exact %z.
    assert member_glob("doc/a[1].txt", 1) == "a?1?.txt"
    assert member_glob("doc/one.txt", 1) == "one.txt"
    assert member_glob("L2.tar.gz:L3.zip:inner.txt", 3) == "inner.txt"


@pytest.mark.parametrize(
    "path, expected",
    [
        ("/x/notes.txt.gz", True),
        ("/x/bundle.tar.gz", True),
        ("/x/notes.txt", False),
        # .Z is a distinct format from .z, so this one is case-sensitive.
        ("/x/old.Z", True),
    ],
)
def test_is_compressed(path, expected):
    assert is_compressed(path) is expected


# -- extraction ------------------------------------------------------------


def unzipped(tree, member):
    """What `unzip -p` says the member holds, as the reference answer."""
    # unzip treats its member argument as a glob, so a name with a bracket in
    # it has to be escaped or it silently matches nothing.
    pattern = member.replace("[", "\\[").replace("]", "\\]")
    return subprocess.run(
        ["unzip", "-p", f"{tree}/docs.zip", pattern], capture_output=True
    ).stdout


@pytest.mark.skipif(shutil.which("unzip") is None, reason="unzip is the reference")
@pytest.mark.parametrize(
    "member", [name for name in MEMBERS if name != "doc/nonl.txt"]
)
def test_extract_matches_unzip_byte_for_byte(tree, member):
    assert extract(Hit(f"{tree}/docs.zip", member), MAX_PREVIEW_BYTES) == unzipped(
        tree, member
    )


@pytest.mark.skipif(shutil.which("unzip") is None, reason="unzip is the reference")
def test_extract_adds_a_missing_final_newline(tree):
    """The one documented departure from byte-for-byte.

    `%O` is the line without its terminator and `%~` puts one back, so a file
    whose last line has no newline gains one. Pinned here so the exception
    stays a known one rather than a surprise.
    """
    member = "doc/nonl.txt"
    assert extract(Hit(f"{tree}/docs.zip", member), MAX_PREVIEW_BYTES) == unzipped(
        tree, member
    ) + b"\n"


def test_extract_from_a_tarball(tree):
    assert extract(Hit(f"{tree}/bundle.tar.gz", "doc/one.txt"), MAX_PREVIEW_BYTES) == (
        MEMBERS["doc/one.txt"]
    )


def test_extract_a_plain_compressed_file(tree):
    """No member at all: one compressed stream rather than an archive."""
    assert extract(Hit(f"{tree}/notes.txt.gz", ""), MAX_PREVIEW_BYTES) == (
        b"gzipped needle content\nsecond gz needle\n"
    )


def test_extract_keeps_same_named_members_apart(tree):
    """The -g is a widened basename, so the exact %z is what separates these."""
    assert extract(Hit(f"{tree}/docs.zip", "doc/one.txt"), MAX_PREVIEW_BYTES) == (
        MEMBERS["doc/one.txt"]
    )
    assert extract(Hit(f"{tree}/docs.zip", "doc/sub/one.txt"), MAX_PREVIEW_BYTES) == (
        MEMBERS["doc/sub/one.txt"]
    )


@pytest.mark.parametrize(
    "member",
    [
        pytest.param("x.txt", id="missing-archive"),
        pytest.param("doc/nothere.txt", id="missing-member"),
    ],
)
def test_extract_reports_a_missing_thing_as_none(tree, member):
    """Never raises and never reports: every failure is None."""
    archive = "nope.zip" if member == "x.txt" else "docs.zip"
    assert extract(Hit(f"{tree}/{archive}", member), MAX_PREVIEW_BYTES) is None


@needs_zip
def test_extract_reports_an_encrypted_archive_as_none(tree):
    """A preview is the wrong place to learn that a zip has a password on it."""
    assert extract(Hit(f"{tree}/locked.zip", "sec.txt"), MAX_PREVIEW_BYTES) is None


def test_extract_recovers_what_survived_a_truncation(tree):
    """A corrupt archive is not all-or-nothing.

    `truncated.zip` is the first 120 bytes of a real one, which is enough to
    hold the first stored member whole. ugrep reads that back and complains
    about the rest on stderr, so extraction returns real content rather than
    None — worth pinning, because "corrupt means None" is the obvious
    assumption and it is wrong.
    """
    assert extract(
        Hit(f"{tree}/truncated.zip", TRUNCATED_SURVIVOR), MAX_PREVIEW_BYTES
    ) == MEMBERS[TRUNCATED_SURVIVOR]
    # A member past the cut is genuinely gone.
    assert extract(Hit(f"{tree}/truncated.zip", "doc/blanks.txt"), MAX_PREVIEW_BYTES) is None


def test_extract_caps_on_the_stripped_text(tmp_path):
    """The cap counts the file's bytes, not ugrep's prefixed output.

    Every line comes back with the member name in front of it, so a file of
    short lines is several times its own size on the wire; capping the raw
    read would cut it at a fraction of the limit.
    """
    archive = tmp_path / "big.zip"
    line = b"short\n"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("verylongmembername.txt", line * 5000)

    got = extract(Hit(str(archive), "verylongmembername.txt"), 1000)
    # One past the cap, so the caller can tell "exactly the cap" from "over".
    assert len(got) == 1001
    assert got == (line * 5000)[:1001]


def test_extract_floors_the_depth_at_one(tree):
    """ugrep rejects --zmax=0 outright, and `extract` reports every failure as
    None — so a 0 arriving here would look like an unreadable file rather than
    the bug it is. 0 is a real value elsewhere: it is how the app says off."""
    assert extract(Hit(f"{tree}/docs.zip", "doc/one.txt"), MAX_PREVIEW_BYTES, 0) == (
        MEMBERS["doc/one.txt"]
    )
