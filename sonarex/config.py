"""The config file: what it holds, how it is read, and how it is written.

One YAML file at `CONFIG_PATH` holds everything the settings dialog edits:
the two lists of glob patterns that scope every search (`search.included` and
`search.excluded`, with a switch each), archive searching and its depth,
near-match searching, and the command the Open button runs (`open.command`).
`Settings` is that file as a record; `load_settings()` and `save_settings()`
are the whole of the interface.

Every key is described once, in `KEYS`: which `Settings` field it fills,
where it sits in the file, what kind of value it holds, and the comment
written above it. Loading, rendering and "which keys does this version know"
are all driven from that table, so adding a setting is a `Settings` field, a
`KEYS` row and a widget in the dialog — nothing to keep in step by hand.

The rest of the app reads the file at the moment of use: a search calls
`load_settings()` once and folds the result into a `spec.SearchSpec`, and the
Open button calls `open_command()` per click. A saved change therefore applies
without a restart. What the patterns *mean* to ugrep and find is `patterns`'s
business, not this module's.

Loading is deliberately forgiving: a missing file, unreadable file, malformed
YAML, or a key holding the wrong type all fall back to the defaults, so a
broken config means an unfiltered search rather than an app that won't run.
The one thing a search must never do is fail because of a comment someone
mistyped in a config file.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from dataclasses import dataclass, fields

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
DEFAULT_EXCLUDED = (
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
)

# Whether each pattern list is applied at all. On, so a list someone wrote
# does what it says; the switches exist so a list can be set aside for one
# search without deleting it and pasting it back afterwards. They are
# independent: each governs its own list and nothing else.
DEFAULT_USE_INCLUDED = True
DEFAULT_USE_EXCLUDED = True

# Whether to search inside archives. Off, because turning it on changes what
# an ordinary search returns rather than merely adding to it: every compressed
# file becomes searchable text, and a `copyright` search over /usr/share/doc
# goes from 2285 hits to 3548, nearly all of them gzipped documentation. That
# is a fine thing to ask for and a surprising thing to be given.
DEFAULT_ARCHIVES = False

# How many levels of archive to open when archive searching is on: ugrep's
# --zmax. 1 is ugrep's own default and means "look inside an archive, but treat
# an archive found inside that one as a binary file". Raising it is what finds
# `L1.zip{L2.tar.gz:L3.zip:inner.txt}`, and costs a decompression pass per
# level, which is why it is a choice rather than simply set high.
DEFAULT_ARCHIVE_DEPTH = 1

# How many characters a match may differ by — ugrep's --fuzzy. 0 is off, and
# off is the whole of what 0 means to every caller: the flag never goes on the
# argv at all, since ugrep rejects `--fuzzy=0` outright the way it rejects
# `--zmax=0`. Off by default because approximate matching returns files that do
# not contain what was typed, which is a fine thing to ask for and a confusing
# thing to be given.
DEFAULT_FUZZY = 0

# The ceiling offered for --fuzzy. ugrep allows far more, but the noise grows
# faster than the usefulness: measured over /usr/share/doc, `copyright` returns
# 2285 files exactly, 2426 at 3 — and 4826 at 4, where `color` starts matching
# `cat`. Three is where it stops being a search.
MAX_FUZZY = 3

# The ceiling offered for --zmax. ugrep itself allows 1..99, but every level
# costs and three is already past what an ordinary tree holds; the dialog
# offers exactly this many.
MAX_DEPTH = 3

# The command the Open button runs when nothing else is configured. Carried
# over from the Nautilus version, which spawned exactly this.
DEFAULT_OPEN_COMMAND = "/usr/bin/code"



@dataclass(frozen=True)
class Settings:
    """The config file as a record — one field per thing the dialog edits.

    Frozen, and the pattern lists are tuples (a list passed in is converted),
    so a `Settings` can be shared — a search pins one — without anyone being
    able to change it underneath the others.

    Each field's default is what a *missing* key means, which for the two
    pattern lists is "none". The file written on first run is `DEFAULTS`,
    which differs in exactly one way: it ships `DEFAULT_EXCLUDED`.
    """

    included: tuple[str, ...] = ()
    excluded: tuple[str, ...] = ()
    archives: bool = DEFAULT_ARCHIVES
    archive_depth: int = DEFAULT_ARCHIVE_DEPTH
    open_command: str = DEFAULT_OPEN_COMMAND
    fuzzy: int = DEFAULT_FUZZY
    use_included: bool = DEFAULT_USE_INCLUDED
    use_excluded: bool = DEFAULT_USE_EXCLUDED

    def __post_init__(self) -> None:
        # object.__setattr__ because the dataclass is frozen; this is the one
        # moment it may be written, and only to normalize the type.
        object.__setattr__(self, "included", tuple(self.included))
        object.__setattr__(self, "excluded", tuple(self.excluded))

    # -- what a search applies ---------------------------------------------
    #
    # The one place the `use_*` switches and the archives checkbox are read
    # for searching, so the content search and the name search cannot
    # disagree about what is in force.

    @property
    def active_included(self) -> tuple[str, ...]:
        """The include list as a search applies it: `()` when switched off.

        A list switched off is exactly an empty one to every caller; the
        patterns stay in the file only so the dialog can give them back.
        """
        return self.included if self.use_included else ()

    @property
    def active_excluded(self) -> tuple[str, ...]:
        """The skip list as a search applies it: `()` when switched off."""
        return self.excluded if self.use_excluded else ()

    @property
    def depth(self) -> int:
        """How many archive levels a search should open: 0 when it should not.

        One number carries both settings, because everything downstream wants
        exactly that: `-z` and `--zmax` go on together, and 0 is the whole of
        what "archive searching is off" means to a caller. The two keys stay
        separate in the file so that clearing the checkbox does not throw
        away the depth the user picked.
        """
        return self.archive_depth if self.archives else 0


DEFAULTS = Settings(excluded=DEFAULT_EXCLUDED)


# The comment block at the top of the file, and the ones introducing each
# list. They are written out by `render_config` rather than living only in a
# first-run template, because the settings dialog rewrites the whole file —
# a template would mean the explanations survived exactly until the first
# save and then vanished.
FILE_COMMENT = """\
# Sonar configuration.
#
# Sonar rewrites this file when you press Save in the settings dialog, which
# reformats it: your own comments and blank lines here will not survive that.
"""

OPEN_COMMENT = """\
  # The command the Open button runs. It is split the way a shell would split
  # it, but no shell is involved, so pipes and redirection do not work. The
  # selected file is appended as the last argument — or substituted wherever
  # %s appears, if it appears at all.
  # Examples: "/usr/bin/code", "gedit", "xdg-open", "gnome-terminal -- vim %s"
"""

INCLUDED_COMMENT = """\
  # Both lists are glob patterns, and both are optional.
  #
  # Files to search. An EMPTY list means "search everything", which is the
  # default. Adding any entry turns this into a whitelist: only files matching
  # one of these patterns are searched, and everything else is ignored.
  # Patterns match a file's NAME at any depth, so they cannot contain "/".
  # Examples: ["*.md", "*.txt", "*.py"]
"""

USE_INCLUDED_COMMENT = """\
  # Whether the "included" list above is applied. false searches every file,
  # as if the list were empty, but keeps the list for next time.
"""

USE_EXCLUDED_COMMENT = """\
  # Whether the "excluded" list below is applied. false skips nothing, as if
  # the list were empty, but keeps the list for next time.
"""

EXCLUDED_COMMENT = """\
  # Directories and files to skip. Written in find's -path style; Sonar
  # translates them into ugrep's glob syntax. A pattern containing "/" must
  # start with "*/" ("*/build/*", "*/docs/*.tmp"); one without "/" matches a
  # file or folder name at any depth ("*.log").
"""

ARCHIVES_COMMENT = """\
  # Search inside .zip, .tar, .tar.gz, .7z, .gz and the other formats ugrep
  # can decompress. A match inside one is listed as "archive.zip -> name".
  #
  # Note that "included" above then applies to the files INSIDE an archive as
  # well, so a whitelist of ["*.md"] finds the .md files in a zip and nothing
  # else in it. Archives whose extension ugrep does not know (.jar, .docx,
  # .epub are all really zips) are only opened if you add that extension to
  # "included" yourself.
"""

ARCHIVE_DEPTH_COMMENT = """\
  # How many levels deep to look, when the above is on. 1 opens an archive;
  # 2 also opens an archive found inside one, and so on. Each level costs
  # another pass, so raise it only if you keep archives inside archives.
"""

FUZZY_COMMENT = """\
  # Find near matches: how many characters a word may differ by and still
  # count as a hit. 0 is off — only exact matches. 1 finds "colour" for
  # "color"; 3 is as loose as this goes, and gets noisy.
  #
  # The FIRST letter always has to be right: "xolor" finds nothing at any
  # setting. NOT / - terms become approximate too, so they exclude more.
"""



# -- the key table ----------------------------------------------------------

# What a key holds, which decides how it is read and how it is written.
PATTERNS = "patterns"  # a list of non-empty strings
BOOL = "bool"  # a real YAML boolean
INT = "int"  # an integer, clamped to [low, high]
STRING = "string"  # a non-blank string


@dataclass(frozen=True)
class Key:
    """One key of the file, and the `Settings` field it fills.

    `comment` is written above it on every save. `low` and `high` bound an
    `INT` and mean nothing for the other kinds.
    """

    field: str
    section: str
    name: str
    kind: str
    comment: str
    low: int = 0
    high: int = 0


# Every key this version knows, in the order they are written. The order is
# part of the file's readability — `use_excluded`'s comment says "below", and
# the depth follows the checkbox it qualifies — so it is fixed here rather than
# derived from `Settings`.
KEYS = (
    Key("included", "search", "included", PATTERNS, INCLUDED_COMMENT),
    Key("use_included", "search", "use_included", BOOL, USE_INCLUDED_COMMENT),
    Key("use_excluded", "search", "use_excluded", BOOL, USE_EXCLUDED_COMMENT),
    Key("excluded", "search", "excluded", PATTERNS, EXCLUDED_COMMENT),
    Key("archives", "search", "archives", BOOL, ARCHIVES_COMMENT),
    Key(
        "archive_depth", "search", "archive_depth", INT, ARCHIVE_DEPTH_COMMENT,
        low=1, high=MAX_DEPTH,
    ),
    Key("fuzzy", "search", "fuzzy", INT, FUZZY_COMMENT, low=0, high=MAX_FUZZY),
    Key("open_command", "open", "command", STRING, OPEN_COMMENT),
)

# The file's top-level sections, in the order they are written.
SECTIONS = ("search", "open")

# Every `Settings` field has exactly one key. Checked at import, so a field
# added without a row fails the first test run rather than silently never
# being saved.
assert sorted(key.field for key in KEYS) == sorted(f.name for f in fields(Settings))


# -- writing ----------------------------------------------------------------


def _quote(value: str) -> str:
    """`value` as a YAML double-quoted scalar.

    Everything here is a glob, and globs are made of the characters YAML
    reserves — `*`, `!`, `#`, a leading `-`. Quoting unconditionally means
    none of them has to be reasoned about; the two escapes a double-quoted
    scalar needs are the backslash and the quote itself.
    """
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _render_list(name: str, comment: str, patterns: Sequence[str]) -> str:
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


def _section(mapping: dict | None) -> dict:
    """One top-level section of the parsed file, or `{}` if it isn't a mapping."""
    return mapping if isinstance(mapping, dict) else {}


def _render_key(key: Key, value) -> str:
    """One commented key, indented under its section."""
    if key.kind == PATTERNS:
        return _render_list(key.name, key.comment, value)
    if key.kind == BOOL:
        text = "true" if value else "false"
    elif key.kind == INT:
        text = str(value)
    else:
        text = _quote(value)
    return f"{key.comment}  {key.name}: {text}\n"


def render_config(settings: Settings, config: dict | None = None) -> str:
    """The full text of a config file holding `settings`.

    `config` is the file's previously parsed contents, if any: every key it
    holds that `KEYS` does not cover is written back out after the known ones
    of its section, so rewriting the file preserves settings this version was
    never taught about.
    """
    config = _section(config)
    text = FILE_COMMENT
    for section in SECTIONS:
        keys = [key for key in KEYS if key.section == section]
        known = {key.name for key in keys}
        text += f"\n{section}:\n"
        text += "\n".join(_render_key(key, getattr(settings, key.field)) for key in keys)
        extra = {
            k: v for k, v in _section(config.get(section)).items() if k not in known
        }
        text += _indent_yaml(extra, "  ")
    extra_top = {k: v for k, v in config.items() if k not in SECTIONS}
    return text + _indent_yaml(extra_top, "")


DEFAULT_CONFIG = render_config(DEFAULTS)


def ensure_config() -> None:
    """Create `CONFIG_PATH` with `DEFAULT_CONFIG` if it isn't there yet.

    Failures are swallowed on purpose: not being able to write the config is
    not a reason to refuse to search, and `load_settings` treats the missing
    file as "no patterns" anyway.
    """
    if os.path.exists(CONFIG_PATH):
        return
    try:
        os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
        with open(CONFIG_PATH, "w", encoding="utf-8") as handle:
            handle.write(DEFAULT_CONFIG)
    except OSError as exc:
        print(f"Sonar: could not create {CONFIG_PATH}: {exc}")


# -- reading ----------------------------------------------------------------


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
        print(f"Sonar: error loading {CONFIG_PATH}: {exc}")
        return {}, str(exc)
    # safe_load returns None for an empty file, and could return a scalar or a
    # list for a file that parses but isn't a mapping.
    if loaded is None:
        return {}, None
    if not isinstance(loaded, dict):
        return {}, "The config file does not contain a YAML mapping."
    return loaded, None


def get_patterns(config: dict, section: str, key: str) -> tuple[str, ...]:
    """`<section>.<key>` from `config` as a pattern list; `()` if absent or
    malformed.

    Anything that isn't a list of strings
    is discarded rather than half-used — a pattern list holding a stray
    mapping would otherwise reach ugrep's argv as something unprintable.
    """
    values = config.get(section)
    if not isinstance(values, dict):
        return ()
    patterns = values.get(key)
    if not isinstance(patterns, list):
        return ()
    return tuple(p for p in patterns if isinstance(p, str) and p)


def get_string(config: dict, section: str, key: str, default: str) -> str:
    """`<section>.<key>` from `config` as a non-empty string, else `default`.

    Blank counts as absent on purpose: clearing the Open command in the dialog
    should give back the built-in editor, not a button that tries to run "".
    """
    values = config.get(section)
    if not isinstance(values, dict):
        return default
    value = values.get(key)
    if not isinstance(value, str) or not value.strip():
        return default
    return value.strip()


def get_bool(config: dict, section: str, key: str, default: bool) -> bool:
    """`<section>.<key>` from `config` as a bool, else `default`.

    Only a real YAML boolean counts. A string "true" is a typo rather than a
    value, and guessing at it would mean a setting that looks set and is not —
    worse than falling back to the default, which at least matches the
    checkbox the dialog will show.
    """
    values = config.get(section)
    if not isinstance(values, dict):
        return default
    value = values.get(key)
    return value if isinstance(value, bool) else default


def get_int(
    config: dict, section: str, key: str, default: int, low: int, high: int
) -> int:
    """`<section>.<key>` from `config` as an int clamped to [low, high].

    Clamped rather than rejected, since a number out of range says clearly
    enough what was wanted. `bool` is excluded explicitly: it is a subclass of
    `int` in Python, so a stray `archive_depth: true` would otherwise be read
    as the number 1 rather than as the mistake it is.
    """
    values = config.get(section)
    if not isinstance(values, dict):
        return default
    value = values.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        return default
    return max(low, min(high, value))


def _read_key(config: dict, key: Key, default):
    """`key`'s value from the parsed `config`, or `default` if it is unusable."""
    if key.kind == PATTERNS:
        return get_patterns(config, key.section, key.name)
    if key.kind == BOOL:
        return get_bool(config, key.section, key.name, default)
    if key.kind == INT:
        return get_int(config, key.section, key.name, default, key.low, key.high)
    return get_string(config, key.section, key.name, default)


# What each field falls back to when its key is missing or unusable.
_FALLBACK = Settings()


def load_settings() -> tuple[Settings, str | None]:
    """The file as a `Settings`, plus a message if it could not be read.

    Every field falls back to its default independently, so one malformed key
    costs only that key — the dialog still opens on the rest of the file.
    """
    config, error = read_config()
    values = {
        key.field: _read_key(config, key, getattr(_FALLBACK, key.field))
        for key in KEYS
    }
    return Settings(**values), error


def open_command() -> str:
    """The Open button's command line — the one call the viewer needs.

    Read per click rather than cached, for the same reason the settings are
    read per search: a change saved in the dialog has to apply to the next use
    without restarting the app.
    """
    return load_settings()[0].open_command


def save_settings(settings: Settings) -> str | None:
    """Write `settings` to `CONFIG_PATH`; return an error message or None.

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
    text = render_config(settings, config)

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
