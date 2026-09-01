#!/usr/bin/env bash
# Run the test suite. Takes the same arguments pytest does:
#
#   ./tests/run.sh                       everything
#   ./tests/run.sh tests/test_nested.py  one file
#   ./tests/run.sh -k archive -v         by name, verbosely
#
# pytest and pytest-qt are pulled in by `uv run --with` rather than declared in
# pyproject.toml, for the same reason the app has no install step: nothing has
# to be set up before this works, and the app's own dependencies stay the two
# it actually ships with.
#
# QT_QPA_PLATFORM=offscreen is what lets the window tests run without a
# display. Note that a QMessageBox still blocks for a click under it, which is
# why conftest's `dialogs` fixture intercepts them all.
set -euo pipefail
cd "$(dirname "$0")/.."
QT_QPA_PLATFORM=offscreen exec uv run --with pytest --with pytest-qt pytest "${@:-tests}"
