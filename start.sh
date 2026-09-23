#!/usr/bin/env bash
# Sonar launcher.
#
# uv builds/refreshes the virtualenv from pyproject.toml on every run, so there
# is no install step. Usage: ./start.sh [/folder/to/search]
set -euo pipefail

HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

if ! command -v uv >/dev/null 2>&1; then
  echo "Error: uv is required but was not found in PATH." >&2
  echo "Install it from https://docs.astral.sh/uv/ or via: curl -LsSf https://astral.sh/uv/install.sh | sh" >&2
  exit 1
fi

# An activated virtualenv — VS Code's integrated terminal activates .venv on
# its own — makes uv warn that VIRTUAL_ENV "does not match the project
# environment" before ignoring it. The project environment is always the one
# wanted here, so drop the variable rather than read past the warning.
unset VIRTUAL_ENV

exec uv run --directory "${HERE}" python -m sonarex "$@"
