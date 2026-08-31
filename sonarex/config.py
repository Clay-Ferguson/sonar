"""The config file, and the glob translation it feeds.

One YAML file at `CONFIG_PATH` holds two lists of glob patterns —
`search.included` and `search.excluded` — which scope every search. The
settings dialog (`settings.py`) edits exactly those two lists, and
`save_patterns()` is the whole of what it needs to write them back.

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

# The exclusions written on first run: the directories nobody means to search.
# `included` ships empty — an inclusion list is a whitelist, so any entry at
# all silently hides every other file type, which is the wrong default for a
# general-purpose search tool.
DEFAULT_EXCLUDED = [
    "*/node_modules/*",
    "*/.git/*",
    "*/.venv/*",
    "*/__pycache__/*",
    "*/venv/*",
    "*/.svn/*",
    "*/.hg/*",
    "*/build/*",
    "*/dist/*",
    "*/.next/*",
    "*/.nuxt/*",
]

# The comment block at the top of the file, and the ones introducing each
# list. They are written out by `render_config` rather than living only in a
# first-run template, because the settings dialog rewrites the whole file —
# a template would mean the explanations survived exactly until the first
# save and then vanished.
FILE_COMMENT = """\
# SonarEx configuration.
#
# Both lists are glob patterns, and both are optional. SonarEx rewrites this
# file when you press Save in the settings dialog, which reformats it: your
# own comments and blank lines here will not survive that.
"""

INCLUDED_COMMENT = """\
  # Files to search. An EMPTY list means "search everything", which is the
  # default. Adding any entry turns this into a whitelist: only files matching
  # one of these patterns are searched, and everything else is ignored.
  # Examples: ["*.md", "*.txt", "*.py"]
"""

EXCLUDED_COMMENT = """\
  # Directories and files to skip. Written in find's -path style; SonarEx
  # translates them into ugrep's glob syntax.
"""


def _quote(value: str) -> str:
    """`value` as a YAML double-quoted scalar.

    Everything here is a glob, and globs are made of the characters YAML
    reserves — `*`, `!`, `#`, a leading `-`. Quoting unconditionally means
    none of them has to be reasoned about; the two escapes a double-quoted
    scalar needs are the backslash and the quote itself.
    """
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _render_list(name: str, comment: str, patterns: list[str]) -> str:
    """One commented `name:` key holding `patterns`, indented under `search:`.

    An empty list is written inline as `[]` rather than as a key with nothing
    under it: a bare `included:` parses as None, which is legal YAML but reads
    like something went missing.
    """
    if not patterns:
        return f"{comment}  {name}: []\n"
    items = "".join(f"    - {_quote(p)}\n" for p in patterns)
    return f"{comment}  {name}:\n{items}"


def _indent_yaml(mapping: dict, indent: str) -> str:
    """`mapping` dumped as YAML, every line shifted right by `indent`.

    Used to carry through keys this module does not know about, so a setting
    added to the file by a later version (or by hand) is not silently dropped
    the first time someone presses Save.
    """
    if not mapping or not YAML_AVAILABLE:
        return ""
    dumped = yaml.safe_dump(
        mapping, sort_keys=False, default_flow_style=False, allow_unicode=True
    )
    return "".join(f"{indent}{line}\n" for line in dumped.splitlines())


def render_config(
    included: list[str], excluded: list[str], config: dict | None = None
) -> str:
    """The full text of a config file holding these two pattern lists.

    `config` is the file's previously parsed contents, if any: every key it
    holds other than `search.included` and `search.excluded` is written back
    out underneath, so rewriting the file preserves settings this function
    was never taught about.
    """
    config = config if isinstance(config, dict) else {}
    search = config.get("search")
    search = search if isinstance(search, dict) else {}

    extra_search = {k: v for k, v in search.items() if k not in ("included", "excluded")}
    extra_top = {k: v for k, v in config.items() if k != "search"}

    return (
        FILE_COMMENT
        + "\nsearch:\n"
        + _render_list("included", INCLUDED_COMMENT, included)
        + "\n"
        + _render_list("excluded", EXCLUDED_COMMENT, excluded)
        + _indent_yaml(extra_search, "  ")
        + _indent_yaml(extra_top, "")
    )


DEFAULT_CONFIG = render_config([], DEFAULT_EXCLUDED)


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


def read_config() -> tuple[dict, str | None]:
    """The parsed config, plus a message if it could not be read.

    The message exists for the settings dialog, which is the one caller that
    must not treat "unreadable" as "empty": pressing Save there rewrites the
    file, so someone whose YAML has a typo needs to be told that what they are
    looking at is not what is on disk before they overwrite it. A missing file
    is not a problem and reports none.

    Every failure still yields a usable `{}`, so a search never depends on
    this succeeding.
    """
    if not YAML_AVAILABLE:
        return {}, "PyYAML is not available, so the config file was not read."
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as handle:
            loaded = yaml.safe_load(handle)
    except FileNotFoundError:
        return {}, None
    except (OSError, yaml.YAMLError) as exc:
        print(f"SonarEx: error loading {CONFIG_PATH}: {exc}")
        return {}, str(exc)
    # safe_load returns None for an empty file, and could return a scalar or a
    # list for a file that parses but isn't a mapping.
    if loaded is None:
        return {}, None
    if not isinstance(loaded, dict):
        return {}, "The config file does not contain a YAML mapping."
    return loaded, None


def load_config() -> dict:
    """The parsed config, or `{}` if it can't be read for any reason."""
    return read_config()[0]


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


# -- writing ----------------------------------------------------------------


def parse_pattern_lines(text: str) -> list[str]:
    """A text area's contents as a pattern list: one pattern per line.

    Blank lines are dropped and surrounding whitespace is stripped, so the
    trailing newline every text area ends up with does not become an empty
    pattern — which ugrep would take as a glob matching nothing at all.
    """
    return [stripped for stripped in (line.strip() for line in text.splitlines()) if stripped]


def pattern_lines(patterns: list[str]) -> str:
    """The inverse: a pattern list as text for a text area."""
    return "\n".join(patterns)


def load_patterns() -> tuple[list[str], list[str], str | None]:
    """`(included, excluded, error)` for the settings dialog to display."""
    config, error = read_config()
    return get_patterns(config, "included"), get_patterns(config, "excluded"), error


def save_patterns(included: list[str], excluded: list[str]) -> str | None:
    """Write the two lists to `CONFIG_PATH`; return an error message or None.

    The file is rewritten in full rather than patched, so keys this module
    does not know about are carried across by `render_config` reading them
    back off the parsed file first. A config that would not parse contributes
    nothing to carry across — which is why the dialog warns before it gets
    this far.

    Written to a temporary file in the same directory and renamed over the
    original: `os.replace` is atomic within a filesystem, so a failure
    part-way through leaves the previous config intact instead of a truncated
    one that a later search would silently read as "no patterns".
    """
    config, _error = read_config()
    text = render_config(included, excluded, config)

    temporary = f"{CONFIG_PATH}.tmp"
    try:
        os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
        with open(temporary, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(temporary, CONFIG_PATH)
    except OSError as exc:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        return f"Could not write {CONFIG_PATH}:\n\n{exc}"
    return None
