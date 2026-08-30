"""The config file, and the glob translation it feeds.

One YAML file at `CONFIG_PATH` holds two lists of glob patterns —
`search.included` and `search.excluded` — which scope every search. There is
no UI for editing it yet; a configuration dialog is planned, and everything
here is written so that dialog only has to write the same two lists back.

Loading is deliberately forgiving: a missing file, unreadable file, malformed
YAML, or a key holding the wrong type all degrade to "no patterns", so a
broken config means an unfiltered search rather than an app that won't run.
The one thing a search must never do is fail because of a comment someone
mistyped in a config file.
"""

from __future__ import annotations

import os

# PyYAML is a declared dependency, so this import normally succeeds. It is
# still guarded because the failure mode matters: running the module without
# the virtualenv (say, a bare `python3 -m sonarex`) should degrade to an
# unfiltered search rather than raising ImportError out of a GUI callback.
try:
    import yaml

    YAML_AVAILABLE = True
except ImportError:  # pragma: no cover - depends on how the app was started
    YAML_AVAILABLE = False


CONFIG_PATH = os.path.expanduser("~/.config/sonarex/sonarex-config.yaml")

# Written verbatim on first run. `included` ships empty — an inclusion list is
# a whitelist, so any entry at all silently hides every other file type, which
# is the wrong default for a general-purpose search tool. `excluded` carries
# the directories nobody means to search.
DEFAULT_CONFIG = """\
# SonarEx configuration.
#
# Both lists are glob patterns, and both are optional.

search:
  # Files to search. An EMPTY list means "search everything", which is the
  # default. Adding any entry turns this into a whitelist: only files matching
  # one of these patterns are searched, and everything else is ignored.
  # Examples: ["*.md", "*.txt", "*.py"]
  included: []

  # Directories and files to skip. Written in find's -path style; SonarEx
  # translates them into ugrep's glob syntax.
  excluded:
    - "*/node_modules/*"
    - "*/.git/*"
    - "*/.venv/*"
    - "*/__pycache__/*"
    - "*/venv/*"
    - "*/.svn/*"
    - "*/.hg/*"
    - "*/build/*"
    - "*/dist/*"
    - "*/.next/*"
    - "*/.nuxt/*"
"""


def ensure_config() -> None:
    """Create `CONFIG_PATH` with `DEFAULT_CONFIG` if it isn't there yet.

    Failures are swallowed on purpose: not being able to write the config is
    not a reason to refuse to search, and `load_config` treats the missing
    file as "no patterns" anyway.
    """
    if os.path.exists(CONFIG_PATH):
        return
    try:
        os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
        with open(CONFIG_PATH, "w", encoding="utf-8") as handle:
            handle.write(DEFAULT_CONFIG)
    except OSError as exc:
        print(f"SonarEx: could not create {CONFIG_PATH}: {exc}")


def load_config() -> dict:
    """The parsed config, or `{}` if it can't be read for any reason."""
    if not YAML_AVAILABLE:
        return {}
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as handle:
            loaded = yaml.safe_load(handle)
    except FileNotFoundError:
        return {}
    except (OSError, yaml.YAMLError) as exc:
        print(f"SonarEx: error loading {CONFIG_PATH}: {exc}")
        return {}
    # safe_load returns None for an empty file, and could return a scalar or a
    # list for a file that parses but isn't a mapping.
    return loaded if isinstance(loaded, dict) else {}


def get_patterns(config: dict, kind: str) -> list[str]:
    """The `search.<kind>` list from `config`; `[]` if absent or malformed.

    `kind` is "included" or "excluded". Anything that isn't a list of strings
    is discarded rather than half-used — a pattern list holding a stray
    mapping would otherwise reach ugrep's argv as something unprintable.
    """
    search = config.get("search")
    if not isinstance(search, dict):
        return []
    patterns = search.get(kind)
    if not isinstance(patterns, list):
        return []
    return [p for p in patterns if isinstance(p, str) and p]


def convert_excluded_pattern(pattern: str) -> str:
    """A find-style exclusion pattern as a ugrep `-g` glob.

    The config spells exclusions the way `find -path` does, typically
    `*/node_modules/*`. ugrep's `-g` globs are gitignore-style instead, where a
    trailing '/' matches directories by basename anywhere in the tree and '**'
    is what crosses path separators.

        */node_modules/*   ->  !node_modules/
        */a/b/*            ->  !**/a/b/**
        *.log              ->  !*.log
    """
    if pattern.startswith("*/") and pattern.endswith("/*"):
        middle = pattern[2:-2]
        if "/" not in middle:
            # Basename form: excludes a directory of this name at any depth.
            return f"!{middle}/"
        # A nested path only means anything as a full-pathname glob.
        return f"!**/{middle}/**"
    return f"!{pattern}"


def build_glob_args(excluded: list[str], included: list[str]) -> list[str]:
    """Config patterns as a flat argv list of repeated ugrep `-g` arguments.

    e.g. `['-g', '!node_modules/', '-g', '*.md']`. Returned as argv rather
    than a shell string because nothing in SonarEx builds a shell command line
    any more — ugrep is spawned directly.
    """
    args: list[str] = []
    for pattern in excluded:
        args.extend(["-g", convert_excluded_pattern(pattern)])
    for pattern in included:
        args.extend(["-g", pattern])
    return args


def search_globs() -> list[str]:
    """The `-g` argv for the current config — the one call the GUI needs."""
    config = load_config()
    return build_glob_args(
        get_patterns(config, "excluded"),
        get_patterns(config, "included"),
    )
