"""Archive members: what one is, how ugrep names it, how to get its text.

Turning on ugrep's `-z` makes a search reach inside `.zip`, `.tar.gz`, `.7z`
and the rest, and a hit stops being a path — it becomes a path *plus* a name
inside it. `Hit` is that pair, and it is what the rest of the app carries
around instead of a string.

The whole of the archive knowledge lives here so `search`, `viewer` and
`window` can share it without importing each other, the same reason `style`
exists. Like `style`, it imports nothing from the package.

Extraction goes back through ugrep rather than through `unzip`/`tar`/`7z` or
Python's `zipfile`: ugrep is already the one hard dependency, it covers every
format it can search (so there is no per-format table to keep in step with its
`-z`), and `--format='%O%~'` over an empty pattern reproduces a member
verbatim — diffed against `unzip -p`, byte for byte, for both a zip member and
a plain `.gz`. The cost is that it is line-based: text only, and see
`extract()` on the newline it can add.
"""

from __future__ import annotations

import os
import subprocess
from typing import NamedTuple


class Hit(NamedTuple):
    """One search result: a file on disk, and optionally a name inside it.

    `member` is "" for an ordinary file, which is the overwhelmingly common
    case and the one every path in the app was before archives existed. The
    two fields are never joined back into one string except for display — a
    path and a name inside an archive are different kinds of thing, and the
    joined form is ambiguous (see `parse_result_line`).
    """

    path: str
    member: str = ""

    @property
    def archived(self) -> bool:
        return bool(self.member)


# What `--separator` is set to and what `%s` emits. A tab because it is the
# one ordinary character that is vanishingly rare in a filename while still
# being visible in a terminal when debugging the argv by hand. It is not
# *impossible* in a filename, which is why both parsers below verify their
# split rather than trusting it.
SEPARATOR = "\t"

# The search's output shape. `%f` is the display name ugrep already builds --
# `archive.zip{member}` -- and `%z` is the member alone, empty for a file that
# is not inside an archive. Emitting both is what makes the split checkable.
RESULT_FORMAT = "--format=%f%s%z%~"

# Extraction: the member name, then the line, for every line of the file.
EXTRACT_FORMAT = "--format=%z%s%O%~"

# What ugrep puts between the levels of a member found inside an archive that
# was itself inside an archive: `L1.zip{L2.tar.gz:L3.zip:inner.txt}`. Only
# reachable above --zmax=1, which is why `member_levels` will not split below
# it — a colon is legal in a filename, and at one level there is no chain for
# it to be confused with.
LEVEL_SEPARATOR = ":"

# The ceiling offered for --zmax. ugrep itself allows 1..99, but every level
# costs and three is already past what an ordinary tree holds; the dialog
# offers exactly this many.
MAX_DEPTH = 3

# Seconds. Extraction is synchronous, on the GUI thread, for the same reason
# `match_spans` is: at the preview's size cap it is a few tens of milliseconds.
# The ceiling is here because a pathological archive should cost a missing
# preview, not a frozen window.
EXTRACT_TIMEOUT = 20

# How much of ugrep's output to take per read. Big enough that the preview's
# 2 MiB cap is a handful of reads, small enough that overshooting the cap on
# the last one costs nothing.
READ_CHUNK = 64 * 1024

# The extensions ugrep decompresses, from `man ugrep` under -z: the archive
# containers, the compressed archives, and the plain compression formats.
#
# This is *not* what turns archive searching on -- the Search Archives setting
# does that. It answers a narrower question: whether a result with no member
# still needs decompressing to be read, which is the plain `notes.txt.gz`
# case, a file that is one compressed stream rather than an archive of many.
ARCHIVE_EXTENSIONS = frozenset(
    {
        ".cpio",
        ".pax",
        ".tar",
        ".zip",
        ".7z",
        ".taz",
        ".tgz",
        ".tpz",
        ".tbz",
        ".tbz2",
        ".tb2",
        ".tz2",
        ".tlz",
        ".txz",
        ".tzst",
        ".gz",
        ".Z",
        ".bz",
        ".bz2",
        ".bzip2",
        ".xz",
        ".lzma",
        ".zst",
        ".zstd",
        ".lz4",
        ".br",
    }
)

# The characters that mean something to ugrep's globs. `member_glob` neuters
# them rather than escaping them; see there for why.
GLOB_METACHARACTERS = "*?[]!^\\"


def is_compressed(path: str) -> bool:
    """Whether `path`'s extension is one ugrep would decompress.

    Case-insensitive except for `.Z`, which is a distinct format from `.z`;
    matching it case-insensitively would be wrong rather than merely generous.
    """
    extension = os.path.splitext(path)[1]
    return extension in ARCHIVE_EXTENSIONS or extension.lower() in ARCHIVE_EXTENSIONS


def parse_result_line(line: str) -> Hit:
    """One line of `RESULT_FORMAT` output as a `Hit`.

    The line is `%f` + SEPARATOR + `%z`, and `%f` is `%z` wrapped in braces and
    appended to the path. That redundancy is the point: both halves can legally
    contain a tab, so the split cannot simply be `rsplit`. Every separator
    position is tried and the one that verifies wins —

        docs.zip{doc/one.txt}<TAB>doc/one.txt   ->  Hit("docs.zip", "doc/one.txt")
        loose.txt<TAB>                          ->  Hit("loose.txt", "")

    A line with no separator at all is a plain path: that is what ugrep prints
    when archive searching is off and the format is not in the argv, so the
    same parser serves both kinds of search.
    """
    index = line.find(SEPARATOR)
    while index != -1:
        display, member = line[:index], line[index + len(SEPARATOR) :]
        if not member:
            # The separator is the last character: `%z` was empty, so this is
            # an ordinary file and everything before it is its path.
            return Hit(display)
        wrapped = "{" + member + "}"
        if display.endswith(wrapped):
            return Hit(display[: -len(wrapped)], member)
        index = line.find(SEPARATOR, index + 1)
    return Hit(line)


def member_levels(member: str, depth: int) -> list[str]:
    """`member` split into one name per archive level, outermost first.

        ("doc/one.txt", 1)                    -> ["doc/one.txt"]
        ("L2.tar.gz:L3.zip:inner.txt", 3)     -> ["L2.tar.gz", "L3.zip", "inner.txt"]

    Only split above depth 1, because a colon is a legal character in a
    filename and at one level there is no chain it could be part of: a member
    honestly called `notes:draft.txt` stays one name for everyone who has not
    turned nesting on, which is the default. Above that the ambiguity is real
    and unresolvable — ugrep reports the joined string and nothing else — so a
    colon in a name is shown as though it were a level. It costs a wrong label
    and nothing more: every other use of a member matches the exact `%z`
    string, never these pieces.
    """
    if depth <= 1:
        return [member]
    return member.split(LEVEL_SEPARATOR)


def member_name(member: str, depth: int) -> str:
    """The name of the file at the bottom of `member`'s chain of archives.

        ("doc/one.txt", 1)                 -> "one.txt"
        ("L2.tar.gz:L3.zip:doc/in.txt", 3) -> "in.txt"

    Depth-aware for the reason `member_levels` is, and this is where it
    matters most: taking the part after the last colon unconditionally would
    turn a member honestly called `notes:draft.txt` into `draft.txt`, and a
    glob built from that reaches nothing at all — verified, ugrep exits 1 for
    the very member `-g 'notes:draft.txt'` finds.
    """
    return os.path.basename(member_levels(member, depth)[-1])


def member_glob(member: str, depth: int) -> str:
    """A ugrep `-g` glob that reaches `member` inside its archive.

    The innermost basename only. A glob containing '/' is matched against
    filesystem pathnames and never against a path inside an archive: verified,
    `-g 'doc-src/Makefile'` returns nothing for the very member that `-g
    'Makefile'` finds. Nesting works the same way — the glob has to name the
    file at the bottom of the chain, so `-g 'inner.txt'` reaches
    `L1.zip{L2.tar.gz:L3.zip:inner.txt}` and `-g` on the whole chain matches
    nothing at all.

    Glob metacharacters in the name are replaced by '?' rather than escaped.
    '?' matches exactly one character, so the substitution is length-preserving
    and can only ever *widen* the glob — a name ugrep would otherwise refuse to
    match is still reached, and `a[1].txt` cannot be read as a character class.
    Widening is free here because every caller filters the output by the exact
    `%z` anyway, which is also what keeps two members sharing a basename apart.
    """
    name = member_name(member, depth)
    return "".join("?" if ch in GLOB_METACHARACTERS else ch for ch in name)


def build_extract_argv(hit: Hit, depth: int) -> list[str]:
    """The ugrep command line that prints `hit`'s content, one line at a time.

    An empty pattern matches every line, so `%O` (the matching line) walks the
    whole file. `-z` is what does the decompressing; the `-g` narrows a
    multi-member archive down to the one wanted, and is left off entirely for a
    plain compressed file, which has no member to name.

    `depth` has to be the same `--zmax` the search ran with, or a member found
    at three levels down is simply not there to extract at one. It is floored
    at 1 because 0 is a real value elsewhere — it is how the rest of the app
    says "archives are off" — but ugrep rejects `--zmax=0` outright, and a
    rejected argv would come back here as an unreadable file rather than as
    the programming mistake it is.
    """
    argv = [
        "ugrep",
        "-z",
        f"--zmax={max(1, depth)}",
        "--no-messages",
        f"--separator={SEPARATOR}",
        EXTRACT_FORMAT,
    ]
    if hit.member:
        argv.extend(["-g", member_glob(hit.member, depth)])
    argv.extend(["-e", "", "--", hit.path])
    return argv


def extract(hit: Hit, limit: int, depth: int = 1) -> bytes | None:
    """`hit`'s content as bytes, or None if it could not be read.

    At most `limit + 1` bytes come back: one past the caller's own cap, so it
    can tell a file of exactly the cap from one over it. The cap is applied
    while reading rather than afterwards, so a multi-gigabyte member is never
    buffered whole — and it is applied to the *stripped* text, because every
    line of ugrep's output carries the member name in front of it and a file of
    short lines would otherwise be cut at a fraction of its size.

    Never raises and never reports. A missing ugrep, an encrypted or corrupt
    archive, a member that vanished — all come back as None, matching
    `match_spans`'s contract, because a preview is the wrong place to learn
    that a zip has a password on it.

    One fidelity note: `%O` is the line without its terminator and `%~` puts one
    back, so a file whose last line has no newline gains one. Everything else is
    byte-exact, CRLF and blank lines included (diffed against `unzip -p`).
    """
    if not os.path.isfile(hit.path):
        return None

    prefix = (hit.member + SEPARATOR).encode("utf-8", "surrogateescape")
    try:
        process = subprocess.Popen(
            build_extract_argv(hit, depth),
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        return None

    text = bytearray()
    tail = b""
    try:
        while len(text) <= limit:
            chunk = process.stdout.read(READ_CHUNK)
            if not chunk:
                break
            # Split on b"\n" and hold the remainder, exactly as
            # `SearchRunner._read_stdout` does and for the same reason: a read
            # lands mid-line, and only whole lines carry a whole prefix.
            lines = (tail + chunk).split(b"\n")
            tail = lines.pop()
            for line in lines:
                # Lines from another member — the glob is a widened basename,
                # so it can reach more than one — are dropped here. This is
                # what keeps two members of the same name apart.
                if line.startswith(prefix):
                    text += line[len(prefix) :] + b"\n"
    except OSError:
        text.clear()
    finally:
        process.stdout.close()
        process.kill()  # the loop usually stops at the cap, mid-file
        try:
            process.wait(timeout=EXTRACT_TIMEOUT)
        except subprocess.TimeoutExpired:  # pragma: no cover - defensive
            pass

    # No output is the only failure signal there is, and it is enough: ugrep
    # exits 1 for an encrypted archive, a corrupt one and a member that is not
    # there alike, and prints nothing in every case. The one thing it does not
    # distinguish — a genuinely empty member — cannot reach here, since a file
    # with no bytes in it never matched the search that produced this row.
    if not text:
        return None
    return bytes(text[: limit + 1])
