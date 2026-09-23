"""`TempCopies` on its own, and the package's layering.

Open's behavior end to end is covered in `test_window` and `test_nested`;
this pins what moved out of module globals into an object.
"""

from __future__ import annotations

import os
import subprocess
import sys
import zipfile

from sonarex.archive import Hit
from sonarex.launch import TempCopies


def _zip(path, members):
    with zipfile.ZipFile(path, "w") as handle:
        for name, data in members.items():
            handle.writestr(name, data)
    return str(path)


def test_two_members_with_one_basename_get_separate_copies(tmp_path, copies):
    archive = _zip(tmp_path / "a.zip", {"x/notes.txt": b"one\n", "y/notes.txt": b"two\n"})
    first, error = copies.extract(Hit(archive, "x/notes.txt"), 1)
    assert error is None
    second, error = copies.extract(Hit(archive, "y/notes.txt"), 1)
    assert error is None
    assert first != second
    assert os.path.basename(first) == os.path.basename(second) == "notes.txt"
    assert open(first, "rb").read() == b"one\n"
    assert open(second, "rb").read() == b"two\n"


def test_each_set_is_its_own_and_cleanup_is_idempotent(tmp_path):
    """No shared module state: one window's cleanup cannot remove another's
    copies, and cleaning an empty or already-clean set is harmless."""
    archive = _zip(tmp_path / "a.zip", {"notes.txt": b"text\n"})
    mine, theirs = TempCopies(), TempCopies()
    path, _ = mine.extract(Hit(archive, "notes.txt"), 1)
    theirs.extract(Hit(archive, "notes.txt"), 1)
    assert mine.root != theirs.root

    theirs.cleanup()
    assert os.path.exists(path) and theirs.root is None
    mine.cleanup()
    mine.cleanup()
    assert not os.path.exists(path) and mine.root is None


def test_the_non_widget_modules_never_import_qt():
    """Everything below the widgets is plain Python, which is what lets it be
    tested — and reasoned about — without an application. A Qt import creeping
    into one of these is a layering mistake, so it fails here first."""
    modules = "archive config patterns spec query search reader launch".split()
    code = (
        "import sys\n"
        + "".join(f"import sonarex.{name}\n" for name in modules)
        + "print(sorted(m for m in sys.modules if m.startswith('PyQt6')))"
    )
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    done = subprocess.run(
        [sys.executable, "-c", code], cwd=root, capture_output=True, text=True, check=True
    )
    assert done.stdout.strip() == "[]"
