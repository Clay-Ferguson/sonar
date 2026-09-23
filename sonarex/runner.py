"""Running a search and streaming its hits back as they are found.

A `QProcess` rather than `subprocess` + a thread: QProcess delivers its output
through Qt's own event loop, so hits arrive on the GUI thread already and the
list can be appended to directly, with no locking and no queue.

ugrep is invoked with `-l`, so its stdout is one absolute path per line and
the volume stays low even for a large search — which is what makes streaming
straightforward here. find, for a name search, prints the same shape, so
everything after the spawn is shared. The command lines themselves come from
`search`; this module only runs them, and tells a real failure in their
stderr from the per-file notes both programs print and carry on after.
"""

from __future__ import annotations

import os
import re

from PyQt6.QtCore import QObject, QProcess, pyqtSignal

from .search import build_argv, build_name_argv
from .spec import SearchSpec

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
        self._names = False  # whether the current search runs find, not ugrep
        self._stdout_tail = b""  # an incomplete last line, held for the next read
        self._stderr = b""
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

    def start(self, spec: SearchSpec) -> None:
        """Abandon any running search and start the one `spec` describes.

        `spec.names` picks the program: find for a name search, ugrep
        otherwise. Both print one absolute path per line, so everything after
        the spawn is shared.
        """
        self.stop()

        self._names = spec.names
        self._stdout_tail = b""
        self._stderr = b""

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

        argv = build_name_argv(spec) if spec.names else build_argv(spec)
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
        chunk = self._process.readAllStandardOutput().data()
        # A read can land mid-line, so only whole lines are emitted and the
        # remainder waits for the next chunk. splitlines() is deliberately not
        # used here: it would also split on characters that are legal in a
        # filename (\v, \f, \x85 and friends), inventing paths that don't exist.
        #
        # Split as bytes and decoded a whole line at a time: a read can also
        # land mid-*character*, and decoding each chunk would turn both halves
        # into U+FFFD. `fsdecode` (surrogateescape) rather than "replace",
        # because a name that is not UTF-8 is still a real file — the lossless
        # decode is what `open()` and every argv encode back to its bytes.
        lines = (self._stdout_tail + chunk).split(b"\n")
        self._stdout_tail = lines.pop()
        for line in lines:
            self._take_line(os.fsdecode(line))

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
        # Kept as bytes and decoded once at the end, so a message split across
        # two reads is not torn mid-character.
        self._stderr += self._process.readAllStandardError().data()

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
        if self._names:
            message = "Could not run find. Is it installed?\n\n  sudo apt install findutils"
        else:
            message = "Could not run ugrep. Is it installed?\n\n  sudo apt install ugrep"
        self.finished.emit(-1, message)

    def _on_finished(self, exit_code: int, status: QProcess.ExitStatus) -> None:
        # ugrep does not newline-terminate under every combination of flags, so
        # a final partial line is a real result rather than debris.
        if self._stdout_tail:
            self._take_line(os.fsdecode(self._stdout_tail))
            self._stdout_tail = b""
        self._process = None
        stderr = self._stderr.decode("utf-8", "replace")
        if status is QProcess.ExitStatus.CrashExit:
            self.finished.emit(-1, stderr or "ugrep exited abnormally.")
            return
        self.finished.emit(exit_code, stderr)
