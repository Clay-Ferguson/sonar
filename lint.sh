#!/usr/bin/env bash
# Static checks, the companion to tests/run.sh:
#
#   ./lint.sh
#
# ruff (pyflakes, pycodestyle, bugbear and import order; see ruff.toml),
# pyright over the app package (see pyrightconfig.json), and a syntax check of
# every shell script. Like the tests, the tools are fetched by uv on demand
# rather than declared in pyproject.toml, so nothing has to be installed first.
set -euo pipefail
cd "$(dirname "$0")"

uvx ruff check .
uv run --with pyright pyright
bash -n start.sh lint.sh tests/run.sh packaging/build-deb.sh
echo "lint: all clean"
