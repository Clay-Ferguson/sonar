"""Running ugrep and streaming its hits back as they are found.

A `QProcess` rather than `subprocess` + a thread: QProcess delivers its output
through Qt's own event loop, so hits arrive on the GUI thread already and the
list can be appended to directly, with no locking and no queue.

ugrep is invoked with `-l`, so its stdout is one absolute path per line and
the volume stays low even for a large search — which is what makes streaming
straightforward here.
"""

from __future__ import annotations

import json
import re
import shlex
import shutil
import subprocess

from PyQt6.QtCore import QObject, QProcess, pyqtSignal

from .archive import RESULT_FORMAT, SEPARATOR, Hit, member_glob
from .config import search_depth, search_fuzzy, search_globs, search_prune_args

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


# What ugrep prints when it skipped one file and carried on: an encrypted or
# corrupt archive, a directory it may not open, a file it may not read. These
# are reports *about* a file, not failures of the search.
#
# They have to be told apart from a real error by their text, because the exit
# status does not distinguish them and is not even consistent between builds:
# for a tree holding an encrypted zip, ugrep 7.5.0 here exits 0 while another
# machine's build exits 2 for the same tree. A genuine failure says
# "ugrep: error:" or "invalid argument" instead, and a bad regex's message runs
# on for two more lines that carry no marker at all — which is why this matches
# per line and keeps everything it does not recognise.
SKIPPED_FILE_NOTICES = ("warning:", "cannot decompress")


def _without_notices(stderr: str, notices: tuple[str, ...]) -> str:
    """`stderr` with every line carrying one of `notices` dropped."""
    kept = [
        line
        for line in stderr.splitlines()
        if line.strip() and not any(note in line for note in notices)
    ]
    return "\n".join(kept)


def search_error(stderr: str) -> str:
    """What in `stderr` is a real failure, with the skipped-file notes removed.

    Empty means ugrep only complained about files it went on without, which is
    the ordinary outcome of searching a tree containing a password-protected
    archive and must not reach the user as an error.
    """
    return _without_notices(stderr, SKIPPED_FILE_NOTICES)


# The name search's equivalent: what GNU find prints for a directory it may not
# open, and for an entry that vanished between being listed and being tested.
# find exits 1 for either and carries on, so like ugrep's 2 the status alone
# cannot say whether anything actually went wrong.
SKIPPED_PATH_NOTICES = ("Permission denied", "No such file or directory")


def name_search_error(stderr: str) -> str:
    """What in find's `stderr` is a real failure, per-path notes removed."""
    return _without_notices(stderr, SKIPPED_PATH_NOTICES)


def ugrep_available() -> bool:
    """Whether ugrep is on PATH. Checked at startup — nothing works without it."""
    return shutil.which("ugrep") is not None


def build_argv(query: str, folder: str) -> list[str]:
    """The full ugrep command line for `query` under `folder`.

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
    searched for rather than parsed as an option, and `folder` is passed
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
    depth = search_depth()
    if depth:
        argv.extend(
            ["-z", f"--zmax={depth}", f"--separator={SEPARATOR}", RESULT_FORMAT]
        )
    fuzzy = search_fuzzy()
    if fuzzy:
        argv.append(f"--fuzzy={fuzzy}")
    argv.extend(search_globs())
    argv.append("--stats")
    argv.extend(["--", query, folder])
    return argv


# What the query is matched against: the text inside files, or the names of
# files and folders. The strings are also the dropdown's labels, so there is
# one spelling of each and nothing to map between.
MODE_CONTENT = "Content"
MODE_NAMES = "Filenames"

# The characters that make a word of a name query a glob of its own rather
# than a fragment to be found anywhere in the name.
NAME_GLOB_CHARACTERS = set("*?[")


def name_terms(query: str) -> list[str]:
    """A name query as `find -iname` patterns, one per word, all required.

      report            -> *report*          (anywhere in the name)
      report 2024       -> *report*, *2024*  (both, in either order)
      "my report"       -> *my report*       (a quoted phrase is one word)
      *.pdf             -> *.pdf             (a glob, on the whole name)

    Not ugrep's query language: find has no regexes, OR or NOT, and a name
    search that half-understood them would be worse than one that plainly
    does words and globs. An unbalanced quote falls back to splitting on
    whitespace, so `it's` is still searched for rather than refused.
    """
    try:
        words = shlex.split(query)
    except ValueError:
        words = query.split()
    return [
        word if set(word) & NAME_GLOB_CHARACTERS else f"*{word}*"
        for word in words
        if word
    ]


def build_name_argv(query: str, folder: str) -> list[str]:
    """The `find` command line that lists names matching `query` under `folder`.

    ugrep cannot do this: it lists only files whose *content* matched, so it
    never reports a directory, and it skips an empty file even when asked to
    match the empty pattern (verified with -Y and --iglob, 7.5.0).

      find FOLDER -mindepth 1 ( EXCLUDED… ) -prune -o -iname T1 -iname T2 -print

    `-mindepth 1` keeps the folder itself off the list, and comes first because
    find warns about it anywhere else. It also stops the folder being pruned
    when its own name happens to match an exclusion — tests are not applied
    above the minimum depth. Juxtaposed tests are an AND, and bind tighter than
    the `-o`, so the prune clause and the name tests need no extra grouping.

    `folder` is absolute, as it is for ugrep, so every line printed starts with
    '/' and `SearchRunner._take_line` needs no change to tell a hit apart.

    `stdbuf -oL` because find writes to a pipe through a fully buffered stdout:
    without it a slow walk delivers its hits in 4 KiB bursts rather than as
    they are found, which is what `--line-buffered` does for ugrep.
    """
    argv = ["find", folder, "-mindepth", "1", *search_prune_args()]
    for term in name_terms(query):
        argv.extend(["-iname", term])
    argv.append("-print")
    if shutil.which("stdbuf"):
        argv = ["stdbuf", "-oL", *argv]
    return argv


# What a Boolean query's operators look like, and the characters that make an
# unquoted term a regex rather than a word. Both are needed by
# `literal_query_term()` below and nowhere else.
QUERY_OPERATORS = {"AND", "OR", "NOT"}
REGEX_METACHARACTERS = set(".^$*+?()[]{}|\\")


def literal_query_term(query: str) -> str | None:
    """One plain string out of a Boolean query, or None if it has none.

    For the PDF pane, whose search (Qt's, hence pdfium's) takes a single
    literal string and knows nothing about regexes, AND/OR or negation. This
    picks the first term of `query` that survives translation:

      "hello world" foo  -> hello world   (a quoted phrase is already literal)
      cat dog            -> cat           (the first of an AND, not both)
      -secret cat        -> cat           (a negated term matches nothing here)
      NOT secret cat     -> cat           (and so does one negated by keyword)
      col(o|ou)r         -> None          (a regex, not a word)

    Terms are dropped rather than approximated, and None is an ordinary
    answer: the caller renders the PDF with no highlighting at all, the same
    as a file ugrep found nothing in. Approximating would be worse — a regex
    searched literally would mark text the search never matched.

    Only the *first* survivor: the search model highlights one string, so a
    two-term AND marks one of the two. That is the known limit of this.
    """
    try:
        # posix=False so the quotes stay on the token: whether a term was
        # quoted is exactly what decides if it is literal, and posix mode
        # strips that evidence away.
        parts = shlex.split(query, posix=False)
    except ValueError:
        # An unbalanced quote. ugrep may still have made sense of it; this
        # cannot, and "no highlighting" is the honest answer.
        return None

    negated = False
    for part in parts:
        # Parentheses group terms in Boolean mode, so a leading or trailing
        # one belongs to the query rather than to the term.
        token = part.strip("()")
        if not token:
            continue
        if token in QUERY_OPERATORS:
            # NOT is the keyword spelling of a leading '-': it negates the
            # term after it, which must be skipped just the same.
            negated = token == "NOT"
            continue
        if negated or token[0] in "-!":  # what the file must *not* contain
            negated = False
            continue
        quoted = len(token) >= 2 and token[0] == token[-1] and token[0] in "\"'"
        term = token[1:-1] if quoted else token
        if not term:
            continue
        if not quoted and set(term) & REGEX_METACHARACTERS:
            continue
        return term
    return None


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


def build_match_argv(query: str, hit: Hit, depth: int, fuzzy: int = 0) -> list[str]:
    """The ugrep command line that reports where `query` matches inside one file.

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
    output is read in one go), and `search_globs()`. The globs are the one that
    would bite: -g filters explicitly named file arguments too, so passing them
    here returns nothing for the very file the search just found.

    A non-zero `depth` puts `-z` back on and grows the format a `%z`, so the
    lines can be attributed to a member. It has to be the same `--zmax` the
    search ran with: a member three levels down is not reachable at one, and
    the spans would come back empty for a file that is plainly on screen.

    The `-g` here is the exception to the paragraph above and is safe for the
    same reason it was unsafe there: under -z a glob is matched against the
    names *inside* the archive, not against the archive named on the command
    line. Line and column mean exactly what they did before — verified, `-z` on
    an ordinary file leaves the spans identical and merely prefixes an empty
    `%z`.

    `fuzzy` is pinned the same way and for the same reason, with a quieter
    failure: at 0 an approximate hit is simply not found again, so a file the
    search plainly put on screen previews with nothing marked. ugrep reports
    the approximate span itself — `%k` is still the character column and `%j`
    still the text actually matched, `"clor"` rather than `"color"` — so
    nothing below this has to know that the match was inexact.
    """
    argv = ["ugrep", "-i", "-%", "--files", "-o", "-u", "--tabs=1"]
    if depth:
        argv.extend(
            [
                "-z",
                f"--zmax={depth}",
                "--no-messages",
                f"--separator={SEPARATOR}",
                ARCHIVE_MATCH_FORMAT,
            ]
        )
        if hit.member:
            argv.extend(["-g", member_glob(hit.member, depth)])
    else:
        argv.append(MATCH_FORMAT)
    if fuzzy:
        argv.append(f"--fuzzy={fuzzy}")
    argv.extend(["--", query, hit.path])
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


def match_spans(
    query: str, hit: Hit, depth: int = 0, fuzzy: int = 0
) -> dict[int, list[tuple[int, int]]]:
    """Where `query` matches in `hit`: 0-based line -> [(column, length)].

    Columns are 1-based characters, as ugrep reports them; the line numbers are
    shifted to 0-based here because their only consumer indexes text blocks.

    Never raises and never reports a problem. A missing ugrep, a timeout, a
    file that changed since the search, or exit 1 (nothing matched) all come
    back as {}: the preview is worth showing unhighlighted, and a dialog over
    a merely undecorated pane would be worse than the missing color.
    """
    try:
        completed = subprocess.run(
            build_match_argv(query, hit, depth, fuzzy),
            capture_output=True,
            text=True,
            timeout=MATCH_TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError):
        return {}

    if completed.returncode != EXIT_MATCHED:
        return {}

    spans: dict[int, list[tuple[int, int]]] = {}
    # Under -z every line is prefixed with the member it came from. Matching
    # the expected member exactly, rather than splitting on the separator, is
    # what keeps two members of one basename apart — and is correct even for a
    # member name containing a tab, since the name is known in advance.
    prefix = hit.member + SEPARATOR if depth else ""
    # Split on "\n" rather than splitlines() for the same reason `_read_stdout`
    # does: a matched string can contain \v, \f or \x85, and %j escapes none of
    # them, so splitlines() would tear one match into two unparseable halves.
    for line in completed.stdout.split("\n"):
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


# The one line of `--stats` output this app wants: "Searched 1234 files in 56
# directories in 0.1 seconds ...". Anchored, and only ever tried against a line
# that does not begin with '/', because the folder is passed absolute and so
# every path ugrep prints is too — a file honestly called "Searched 3 files"
# still arrives with its directory in front of it.
STATS_FILES = re.compile(r"^Searched ([\d,]+) files?\b")


class SearchRunner(QObject):
    """One ugrep process at a time, reporting hits as they arrive.

    `matchFound` carries one absolute path; `finished` carries ugrep's exit
    code and whatever it wrote to stderr. A `start()` while a search is still
    running abandons that search first (see `stop`), so pressing Search
    repeatedly can never interleave two result sets in the list.

    `files_searched()` is the other half of what the status bar reports, and
    is a plain accessor rather than a third signal or a wider `finished`: it
    arrives exactly once, at the end, so there is nothing to be notified of
    that `finished` does not already say.
    """

    matchFound = pyqtSignal(str)
    finished = pyqtSignal(int, str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._process: QProcess | None = None
        self._mode = MODE_CONTENT  # which program the current search runs
        self._stdout_tail = ""  # an incomplete last line, held for the next read
        self._stderr = ""
        self._files_searched = 0
        # Everything ugrep prints after its "Searched n files" line is the rest
        # of the --stats block: the selections and constraints it applied, in
        # prose. None of it is a result, and this is what stops it being added
        # to the list as one.
        self._in_stats = False

    def files_searched(self) -> int:
        """How many files the last search actually looked at, 0 if unknown.

        0 is what a search that failed to start, or was superseded, or ran
        before `--stats` produced anything, honestly reports — the caller
        leaves the number out of the status line rather than claiming zero.
        """
        return self._files_searched

    def is_running(self) -> bool:
        return self._process is not None

    def start(self, query: str, folder: str, mode: str = MODE_CONTENT) -> None:
        """Abandon any running search and start one for `query` under `folder`.

        `mode` picks the program: ugrep for `MODE_CONTENT`, find for
        `MODE_NAMES`. Both print one absolute path per line, so everything
        after the spawn is shared.
        """
        self.stop()

        self._mode = mode
        self._stdout_tail = ""
        self._stderr = ""

        process = QProcess(self)
        # Separate channels: stderr is an error report to show the user, and
        # merging it into stdout would put its text into the results list.
        process.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
        process.readyReadStandardOutput.connect(self._read_stdout)
        process.readyReadStandardError.connect(self._read_stderr)
        process.finished.connect(self._on_finished)
        process.errorOccurred.connect(self._on_error)
        self._process = process
        self._files_searched = 0
        self._in_stats = False

        if mode == MODE_NAMES:
            argv = build_name_argv(query, folder)
        else:
            argv = build_argv(query, folder)
        process.start(argv[0], argv[1:])

    def stop(self) -> None:
        """Kill the running search, if any, without emitting `finished`.

        The signals are disconnected before the kill so the dying process
        cannot deliver a late `finished` (or a last read) into a search that
        has already been superseded. Killed rather than terminated: ugrep has
        no cleanup worth waiting for, and this has to be synchronous enough
        that the next search starts against an empty list.
        """
        process, self._process = self._process, None
        if process is None:
            return
        try:
            process.readyReadStandardOutput.disconnect()
            process.readyReadStandardError.disconnect()
            process.finished.disconnect()
            process.errorOccurred.disconnect()
        except TypeError:
            # Already disconnected; nothing to undo.
            pass
        if process.state() != QProcess.ProcessState.NotRunning:
            process.kill()
            process.waitForFinished(1000)
        process.deleteLater()

    def _read_stdout(self) -> None:
        if self._process is None:
            return
        chunk = bytes(self._process.readAllStandardOutput()).decode("utf-8", "replace")
        # A read can land mid-line, so only whole lines are emitted and the
        # remainder waits for the next chunk. splitlines() is deliberately not
        # used here: it would also split on characters that are legal in a
        # filename (\v, \f, \x85 and friends), inventing paths that don't exist.
        text = self._stdout_tail + chunk
        lines = text.split("\n")
        self._stdout_tail = lines.pop()
        for line in lines:
            self._take_line(line)

    def _take_line(self, line: str) -> None:
        """One whole line of ugrep's stdout: a hit, the file count, or debris.

        `--stats` writes its block to stdout, after the last hit, so this is
        where a result is told from a sentence about the search. The test is
        deliberately one-way and sticky: a line beginning with '/' is a hit
        (every path ugrep prints is absolute, because the folder it was given
        was), and the first line that both fails that and matches
        `STATS_FILES` puts this into the stats block for the rest of the run.
        Nothing after it can be a result — ugrep prints the block last —
        which is what keeps its prose out of the results list.
        """
        if not line:
            return
        if not self._in_stats and not line.startswith("/"):
            found = STATS_FILES.match(line)
            if found:
                self._in_stats = True
                self._files_searched = int(found.group(1).replace(",", ""))
                return
        if self._in_stats:
            return
        self.matchFound.emit(line)

    def _read_stderr(self) -> None:
        if self._process is None:
            return
        self._stderr += bytes(self._process.readAllStandardError()).decode("utf-8", "replace")

    def _on_error(self, error: QProcess.ProcessError) -> None:
        """A failure to run ugrep at all, as opposed to a failure inside it.

        Only `FailedToStart` is reported: every other ProcessError (Crashed,
        and the timeout/read/write errors) either arrives alongside a normal
        `finished` or belongs to the synchronous API this class never uses,
        so reporting them here would double up on `_on_finished`.
        """
        if error is not QProcess.ProcessError.FailedToStart:
            return
        self._process = None
        if self._mode == MODE_NAMES:
            message = "Could not run find. Is it installed?\n\n  sudo apt install findutils"
        else:
            message = "Could not run ugrep. Is it installed?\n\n  sudo apt install ugrep"
        self.finished.emit(-1, message)

    def _on_finished(self, exit_code: int, status: QProcess.ExitStatus) -> None:
        # ugrep does not newline-terminate under every combination of flags, so
        # a final partial line is a real result rather than debris.
        if self._stdout_tail:
            self._take_line(self._stdout_tail)
            self._stdout_tail = ""
        self._process = None
        if status is QProcess.ExitStatus.CrashExit:
            self.finished.emit(-1, self._stderr or "ugrep exited abnormally.")
            return
        self.finished.emit(exit_code, self._stderr)
