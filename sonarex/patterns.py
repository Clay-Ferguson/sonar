"""The config's glob patterns, and what ugrep and find make of them.

The settings keep two lists: files to search (`included`) and files and
folders to skip (`excluded`), spelled the way `find -path` spells them. A
content search hands them to ugrep as `-g` globs, which are gitignore-style
instead; a name search hands the exclusions to find as a prune clause. This
module is that translation, the check that refuses a pattern neither program
would honor, and the text-area form the settings dialog edits them in.

Pure string work — no disk, no Qt, nothing from the rest of the package — so
the config, the dialog and `spec` can all use it without depending on each
other.
"""

from __future__ import annotations

from collections.abc import Sequence

# -- ugrep ------------------------------------------------------------------


def convert_excluded_pattern(pattern: str) -> str:
    """A find-style exclusion pattern as a ugrep `-g` glob.

    The config spells exclusions the way `find -path` does, typically
    `*/node_modules/*`. ugrep's `-g` globs are gitignore-style instead, where a
    trailing '/' matches directories by basename anywhere in the tree and '**'
    is what crosses path separators.

        */node_modules/*   ->  !node_modules/
        */a/b/*            ->  !**/a/b/**
        */docs/*.tmp       ->  !**/docs/*.tmp
        *.log              ->  !*.log

    A leading `*/` has to become `**/` whatever follows it: ugrep's `*` never
    crosses a '/', so `!*/docs/*.tmp` matches nothing at all (verified), while
    find's `-path */docs/*.tmp` skips those files — the two modes disagreed.
    Any other pattern with a '/' is refused by `pattern_problems` before it
    gets here.
    """
    if pattern.startswith("*/") and pattern.endswith("/*"):
        middle = pattern[2:-2]
        if "/" not in middle:
            # Basename form: excludes a directory of this name at any depth.
            return f"!{middle}/"
        # A nested path only means anything as a full-pathname glob.
        return f"!**/{middle}/**"
    if pattern.startswith("*/"):
        return f"!**/{pattern[2:]}"
    return f"!{pattern}"


def build_glob_args(excluded: Sequence[str], included: Sequence[str]) -> list[str]:
    """Config patterns as a flat argv list of repeated ugrep `-g` arguments.

    e.g. `['-g', '!node_modules/', '-g', '*.md']`. Returned as argv rather
    than a shell string because nothing in Sonar builds a shell command line
    any more — ugrep is spawned directly.
    """
    args: list[str] = []
    for pattern in excluded:
        args.extend(["-g", convert_excluded_pattern(pattern)])
    for pattern in included:
        args.extend(["-g", pattern])
    return args


# -- find -------------------------------------------------------------------


def convert_excluded_to_find(pattern: str) -> list[str]:
    """A find-style exclusion pattern as one `find` test, for a name search.

    The config's spelling is already `find -path`'s, but the usual form
    `*/node_modules/*` matches what is *inside* the directory rather than the
    directory itself — pruned that way, find still opens it and tests every
    entry. Dropping the trailing `/*` prunes the directory as it is reached,
    and it is the directory's own row that should not be listed either.

        */node_modules/*   ->  -path */node_modules
        */a/b/*            ->  -path */a/b
        */docs/*.tmp       ->  -path */docs/*.tmp
        *.log              ->  -name *.log

    A pattern with a '/' is matched against the whole absolute path find
    prints, so it has to begin with `*/` to match anything — which is why
    `pattern_problems` refuses one that does not.
    """
    if pattern.startswith("*/") and pattern.endswith("/*"):
        return ["-path", pattern[:-2]]
    if "/" in pattern:
        return ["-path", pattern]
    return ["-name", pattern]


def build_prune_args(excluded: Sequence[str]) -> list[str]:
    """Exclusions as a `find` prune clause: `( T1 -o T2 … ) -prune -o`.

    Empty when nothing is excluded, so the caller can put it straight in front
    of the name tests. `included` has no counterpart here on purpose: it is a
    whitelist of file *types* to read, and applied to names it would hide
    every folder in the tree.
    """
    tests: list[str] = []
    for pattern in excluded:
        if tests:
            tests.append("-o")
        tests.extend(convert_excluded_to_find(pattern))
    if not tests:
        return []
    return ["(", *tests, ")", "-prune", "-o"]


# -- checking ---------------------------------------------------------------


def pattern_problems(included: Sequence[str], excluded: Sequence[str]) -> list[str]:
    """One message per pattern that cannot do what it says; `[]` if none.

    Both lists fail *silently* on a bad '/', which is why this exists rather
    than leaving ugrep to complain — it never does (all verified, 7.5.0):

      included  Any '/' at all. The folder is passed absolute, so `docs/*.md`
                matches no path ever printed — and ugrep then lists nothing,
                even for the other patterns beside it: one such line empties
                every search. `**/gen/*` narrows the whole list to that folder
                instead. Neither is needed: a pattern matches the file's name
                at any depth, so `*.md` already means `**/*.md`.
      excluded  A '/' without a leading `*/`. `docs/*.tmp` is matched against
                the absolute path too, so it skips nothing, in either mode.

    Checked by the settings dialog before it saves and, through
    `spec.search_problems`, by the window before it searches, since the file
    can be edited by hand.
    """
    problems = [
        f"Include pattern \"{p}\" contains '/'. Include patterns match a "
        "file's name at any depth, so use just the name part, e.g. \"*.md\"."
        for p in included
        if "/" in p
    ]
    problems += [
        f"Skip pattern \"{p}\" contains '/' but does not start with \"*/\". "
        "It would skip nothing; write it as \"*/" + p.lstrip("/") + "\"."
        for p in excluded
        if "/" in p and not p.startswith("*/")
    ]
    return problems


# -- the settings dialog's text areas --------------------------------------


def parse_pattern_lines(text: str) -> list[str]:
    """A text area's contents as a pattern list: one pattern per line.

    Blank lines are dropped and surrounding whitespace is stripped, so the
    trailing newline every text area ends up with does not become an empty
    pattern — which ugrep would take as a glob matching nothing at all.
    """
    return [stripped for stripped in (line.strip() for line in text.splitlines()) if stripped]


def pattern_lines(patterns: Sequence[str]) -> str:
    """The inverse: a pattern list as text for a text area."""
    return "\n".join(patterns)
