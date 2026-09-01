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
import shlex
import shutil
import subprocess

from PyQt6.QtCore import QObject, QProcess, pyqtSignal

from .archive import RESULT_FORMAT, SEPARATOR, Hit, member_glob
from .config import search_depth, search_globs

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
    """
    argv = ["ugrep", "--line-buffered", "-r", "-i", "-l", "-%", "--files"]
    if shutil.which("pdftotext"):
        argv.append(PDF_FILTER)
    depth = search_depth()
    if depth:
        argv.extend(
            ["-z", f"--zmax={depth}", f"--separator={SEPARATOR}", RESULT_FORMAT]
        )
    argv.extend(search_globs())
    argv.extend(["--", query, folder])
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

    for part in parts:
        # Parentheses group terms in Boolean mode, so a leading or trailing
        # one belongs to the query rather than to the term.
        token = part.strip("()")
        if not token or token in QUERY_OPERATORS:
            continue
        if token[0] in "-!":  # negated: it is what the file must *not* contain
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


def build_match_argv(query: str, hit: Hit, depth: int) -> list[str]:
    """The ugrep command line that reports where `query` matches inside one file.

    The query-shaping flags are exactly `build_argv`'s -i, -% and --files, so
    the terms reported here are the same ones that selected this file in the
    first place: --files evaluates the Boolean over the whole file, so every
    satisfied term is reported wherever it occurs, and NOT/- terms — which
    excluded the file rather than matching in it — are not reported at all.

    `-o -u` reports every match rather than one per line.

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
    """
    argv = ["ugrep", "-i", "-%", "--files", "-o", "-u"]
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
    query: str, hit: Hit, depth: int = 0
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
            build_match_argv(query, hit, depth),
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


class SearchRunner(QObject):
    """One ugrep process at a time, reporting hits as they arrive.

    `matchFound` carries one absolute path; `finished` carries ugrep's exit
    code and whatever it wrote to stderr. A `start()` while a search is still
    running abandons that search first (see `stop`), so pressing Search
    repeatedly can never interleave two result sets in the list.
    """

    matchFound = pyqtSignal(str)
    finished = pyqtSignal(int, str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._process: QProcess | None = None
        self._stdout_tail = ""  # an incomplete last line, held for the next read
        self._stderr = ""

    def is_running(self) -> bool:
        return self._process is not None

    def start(self, query: str, folder: str) -> None:
        """Abandon any running search and start one for `query` under `folder`."""
        self.stop()

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
            if line:
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
        self.finished.emit(
            -1, "Could not run ugrep. Is it installed?\n\n  sudo apt install ugrep"
        )

    def _on_finished(self, exit_code: int, status: QProcess.ExitStatus) -> None:
        # ugrep does not newline-terminate under every combination of flags, so
        # a final partial line is a real result rather than debris.
        if self._stdout_tail:
            self.matchFound.emit(self._stdout_tail)
            self._stdout_tail = ""
        self._process = None
        if status is QProcess.ExitStatus.CrashExit:
            self.finished.emit(-1, self._stderr or "ugrep exited abnormally.")
            return
        self.finished.emit(exit_code, self._stderr)
