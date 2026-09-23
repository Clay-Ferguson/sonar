"""The command lines Sonar runs ugrep and find with, and the one it reads.

Every argv the app spawns for a search is built here from a `SearchSpec`:
`build_argv` for a content search (ugrep), `build_name_argv` for a name search
(find), and `build_match_argv` for the per-file ugrep run the preview makes to
find out where to paint. `match_spans` is that last run, done synchronously
and parsed; the two searches are run by `runner.SearchRunner`, which streams
their output.

The flags here are ugrep facts verified against 7.5.0, each explained where
it goes on; AGENTS.md lists the ones that are easy to "fix" into a bug.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess

from .archive import RESULT_FORMAT, SEPARATOR, Hit, member_glob
from .query import name_terms
from .spec import SearchSpec

# Exit statuses, confirmed against ugrep 7.5.0. The distinction that matters is
# 1 vs 2: "nothing matched" is an ordinary outcome to report in the status
# line, while anything above it is a real error whose stderr must be shown.
EXIT_MATCHED = 0
EXIT_NO_MATCH = 1

# ugrep runs a --filter command directly rather than through a shell, so this
# string cannot contain redirections or pipes. '%' is where ugrep substitutes
# the filename; '-' makes pdftotext write to stdout; '-q' silences the
# warnings that would otherwise be read as file content.
PDF_FILTER = "--filter=pdf:pdftotext -q % -"


def ugrep_available() -> bool:
    """Whether ugrep is on PATH. Checked at startup — nothing works without it."""
    return shutil.which("ugrep") is not None


def build_argv(spec: SearchSpec) -> list[str]:
    """The full ugrep command line for `spec`'s query under its root.

    Flags, all carried over from the search this app replaces:

      --line-buffered  flush per line, so hits stream instead of arriving in
                       one block when the pipe buffer fills
      -r               recurse
      -i               case-insensitive
      -l               list matching file paths only, no matching lines
      -%               Boolean query mode: "quoted phrases" are literal, a
                       space (or AND) requires all terms, OR matches any,
                       NOT/- excludes, and unquoted terms are regexes
      --files          apply the Boolean query at whole-file scope, so
                       `cat dog` matches a file with the terms on different
                       lines rather than requiring them on one

    `--` separates the flags from the query so a query beginning with '-' is
    searched for rather than parsed as an option, and the root is passed
    absolute so every path ugrep prints is absolute too.

    With Search Archives on, four more flags go on: `-z` to look inside
    archives, `--zmax` for how many levels of them, and a `--separator` plus
    `--format` so a hit inside one arrives as its two halves rather than as
    ugrep's ambiguous `archive.zip{member}`. With it off the argv is
    byte-for-byte what it has always been — the whole feature stays off the
    ordinary code path.

    With Find near matches set, one more flag goes on: `--fuzzy`, which allows
    that many characters of difference between the pattern and what it matches.
    It applies to the whole matcher rather than to one kind of term, so quoted
    phrases, unquoted regexes and negated terms alike become approximate. A 0
    puts nothing on the argv at all — `--fuzzy=0` is an error to ugrep, not an
    "off" — so an unset setting leaves this command line untouched too.

    `--stats` is what makes the status bar able to say how many files were
    *searched* rather than only how many matched, which nothing else on the
    argv reports. It costs a short block of prose on stdout after the last
    hit, and `SearchRunner` is what tells that block from a result (see
    `STATS_FILES`); it goes last so the flags before it keep their positions.
    """
    argv = ["ugrep", "--line-buffered", "-r", "-i", "-l", "-%", "--files"]
    if shutil.which("pdftotext"):
        argv.append(PDF_FILTER)
    if spec.depth:
        argv.extend(
            ["-z", f"--zmax={spec.depth}", f"--separator={SEPARATOR}", RESULT_FORMAT]
        )
    if spec.fuzzy:
        argv.append(f"--fuzzy={spec.fuzzy}")
    argv.extend(spec.globs)
    argv.append("--stats")
    argv.extend(["--", spec.query, spec.root])
    return argv


def build_name_argv(spec: SearchSpec) -> list[str]:
    """The `find` command line listing names that match `spec`'s query.

    ugrep cannot do this: it lists only files whose *content* matched, so it
    never reports a directory, and it skips an empty file even when asked to
    match the empty pattern (verified with -Y and --iglob, 7.5.0).

      find FOLDER -mindepth 1 ( EXCLUDED… ) -prune -o -iname T1 -iname T2 -print

    `-mindepth 1` keeps the folder itself off the list, and comes first because
    find warns about it anywhere else. It also stops the folder being pruned
    when its own name happens to match an exclusion — tests are not applied
    above the minimum depth. Juxtaposed tests are an AND, and bind tighter than
    the `-o`, so the prune clause and the name tests need no extra grouping.

    The root is absolute, as it is for ugrep, so every line printed starts with
    '/' and `SearchRunner._take_line` needs no change to tell a hit apart.

    `stdbuf -oL` because find writes to a pipe through a fully buffered stdout:
    without it a slow walk delivers its hits in 4 KiB bursts rather than as
    they are found, which is what `--line-buffered` does for ugrep.
    """
    argv = ["find", spec.root, "-mindepth", "1", *spec.prune]
    for term in name_terms(spec.query):
        argv.extend(["-iname", term])
    argv.append("-print")
    if shutil.which("stdbuf"):
        argv = ["stdbuf", "-oL", *argv]
    return argv


# Line, column and the matched text, one match per output line. `%k` is a
# *character* column, not a byte one, which is what makes it usable against a
# QTextDocument directly; `%j` is JSON-quoted, so a match containing a newline
# still cannot spill onto a second output line and invent a match.
MATCH_FORMAT = "--format=%n %k %j%~"

# The same, with the member name in front, for a search that has -z on. Every
# line has to say which file inside the archive it came from: the -g that
# reaches a member is a widened basename, so it can match more than one.
ARCHIVE_MATCH_FORMAT = "--format=%z%s%n %k %j%~"

# Seconds. This call is synchronous, on the GUI thread, so it needs a ceiling:
# the measured worst case at the preview's 2 MiB cap is ~16ms, and anything
# approaching this number means something is wrong rather than slow. Reaching it
# costs the highlight, not the preview.
MATCH_TIMEOUT = 10


def build_match_argv(spec: SearchSpec, hit: Hit) -> list[str]:
    """The ugrep command line that reports where `spec`'s query matches in `hit`.

    The query-shaping flags are exactly `build_argv`'s -i, -% and --files, so
    the terms reported here are the same ones that selected this file in the
    first place: --files evaluates the Boolean over the whole file, so every
    satisfied term is reported wherever it occurs, and NOT/- terms — which
    excluded the file rather than matching in it — are not reported at all.

    `-o -u` reports every match rather than one per line.

    `--tabs=1` because `%k` is not a plain character count by default: ugrep
    expands a tab to the next multiple of 8 first, so `\tneedle` reports column
    9 rather than 2 (verified, 7.5.0) and every match after a tab is painted
    that many characters too far right. At 1 a tab is one column, which is what
    it is in the document the spans are applied to.

    Deliberately *not* carried over from `build_argv`: -r and -l (this is one
    named file and the offsets are the whole point), --line-buffered (the
    output is read in one go), and `spec.globs`. The globs are the one that
    would bite: -g filters explicitly named file arguments too, so passing them
    here returns nothing for the very file the search just found.

    A non-zero `spec.depth` puts `-z` back on and grows the format a `%z`, so the
    lines can be attributed to a member. It has to be the same `--zmax` the
    search ran with: a member three levels down is not reachable at one, and
    the spans would come back empty for a file that is plainly on screen.

    The `-g` here is the exception to the paragraph above and is safe for the
    same reason it was unsafe there: under -z a glob is matched against the
    names *inside* the archive, not against the archive named on the command
    line. Line and column mean exactly what they did before — verified, `-z` on
    an ordinary file leaves the spans identical and merely prefixes an empty
    `%z`.

    `spec.fuzzy` is pinned the same way and for the same reason, with a quieter
    failure: at 0 an approximate hit is simply not found again, so a file the
    search plainly put on screen previews with nothing marked. ugrep reports
    the approximate span itself — `%k` is still the character column and `%j`
    still the text actually matched, `"clor"` rather than `"color"` — so
    nothing below this has to know that the match was inexact.
    """
    argv = ["ugrep", "-i", "-%", "--files", "-o", "-u", "--tabs=1"]
    if spec.depth:
        argv.extend(
            [
                "-z",
                f"--zmax={spec.depth}",
                "--no-messages",
                f"--separator={SEPARATOR}",
                ARCHIVE_MATCH_FORMAT,
            ]
        )
        if hit.member:
            argv.extend(["-g", member_glob(hit.member, spec.depth)])
    else:
        argv.append(MATCH_FORMAT)
    if spec.fuzzy:
        argv.append(f"--fuzzy={spec.fuzzy}")
    argv.extend(["--", spec.query, hit.path])
    return argv


def _match_length(field: str) -> int:
    """The character length of a `%j` field — a JSON-quoted match.

    The fast path avoids `json.loads` for the overwhelmingly common match with
    nothing to escape, which is what keeps parsing a file full of hits cheap:
    at ~88k matches that is the difference between roughly 20ms and 85ms.
    """
    if "\\" in field:
        return len(json.loads(field))
    return len(field) - 2


def match_spans(spec: SearchSpec, hit: Hit) -> dict[int, list[tuple[int, int]]]:
    """Where `spec`'s query matches in `hit`: 0-based line -> [(column, length)].

    Columns are 1-based characters, as ugrep reports them; the line numbers are
    shifted to 0-based here because their only consumer indexes text blocks.

    Never raises and never reports a problem. A missing ugrep, a timeout, a
    file that changed since the search, or exit 1 (nothing matched) all come
    back as {}: the preview is worth showing unhighlighted, and a dialog over
    a merely undecorated pane would be worse than the missing color.

    The output is read as bytes and decoded here, not with `text=True`: that
    decodes strictly, and `%j` passes a non-UTF-8 byte through raw — a
    Latin-1 `café` raised UnicodeDecodeError out of the selection handler,
    which PyQt answers by aborting the process. `surrogateescape` rather than
    "replace" so the member prefix below compares equal to `hit.member`, which
    `SearchRunner` decoded the same way; either counts one character per bad
    byte, which is what the preview's own "replace" decode puts in the pane.
    """
    try:
        completed = subprocess.run(
            build_match_argv(spec, hit),
            capture_output=True,
            timeout=MATCH_TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError):
        return {}

    if completed.returncode != EXIT_MATCHED:
        return {}
    stdout = os.fsdecode(completed.stdout)

    spans: dict[int, list[tuple[int, int]]] = {}
    # Under -z every line is prefixed with the member it came from. Matching
    # the expected member exactly, rather than splitting on the separator, is
    # what keeps two members of one basename apart — and is correct even for a
    # member name containing a tab, since the name is known in advance.
    prefix = hit.member + SEPARATOR if spec.depth else ""
    # Split on "\n" rather than splitlines() for the same reason
    # `SearchRunner._read_stdout` does: a matched string can contain \v, \f or
    # \x85, and %j escapes none of them, so splitlines() would tear one match
    # into two unparseable halves.
    for line in stdout.split("\n"):
        if not line or not line.startswith(prefix):
            continue
        line = line[len(prefix) :]
        try:
            number, column, matched = line.split(" ", 2)
            spans.setdefault(int(number) - 1, []).append(
                (int(column), _match_length(matched))
            )
        except ValueError:
            continue
    return spans
