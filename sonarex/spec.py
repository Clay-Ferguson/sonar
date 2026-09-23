"""One search, pinned: everything a search and its results are read with.

A `SearchSpec` is built once, when Search is pressed, from the query row, the
folder row, the mode dropdown and a single read of the config — and then it is
the only place any of those are read from until the next search. The argv
builders take it, `SearchRunner` takes it, the preview's `match_spans` takes
it, and the window keeps it for as long as its results are on screen.

That is what "pinned at search start" means, and why it matters. The rows on
screen have to keep meaning the search that found them: the query and folder
rows stay editable, and the settings can be changed mid-session, but a member
found three archive levels down is only reachable again at depth 3, and a hit
found with fuzzy matching on only highlights with it on. Reading any of these
back from the config later is the bug this object exists to make impossible.

Pure data and pure functions: nothing here touches the disk or Qt, which is
what lets every argv be tested without a config file.
"""

from __future__ import annotations

from dataclasses import dataclass

from .config import Settings
from .patterns import build_glob_args, build_prune_args, pattern_problems


@dataclass(frozen=True)
class SearchSpec:
    """The inputs of one search.

    `root` is absolute — the same value ugrep or find is given, so every path
    printed is under it. `names` picks a name search (find) over a content
    search (ugrep). `depth` is ugrep's `--zmax`, 0 when archives are off;
    `fuzzy` is `--fuzzy`, 0 when off — 0 is never put on an argv for either,
    since ugrep rejects both as errors. `globs` is the `-g` argv for a content
    search and `prune` the prune clause for a name search, each already
    translated from the config's patterns.

    Everything past `root` defaults to "off", so a spec for a plain search of
    one file — all `match_spans` needs in a test — is `SearchSpec(q, "")`.
    """

    query: str
    root: str
    names: bool = False
    depth: int = 0
    fuzzy: int = 0
    globs: tuple[str, ...] = ()
    prune: tuple[str, ...] = ()

    @classmethod
    def from_settings(
        cls, settings: Settings, query: str, root: str, names: bool = False
    ) -> SearchSpec:
        """The spec for `query` under `root`, with `settings` folded in.

        A name search never looks inside an archive, approximates, or applies
        the include list (a whitelist of file *types* to read would hide every
        folder), so none of those is carried for one — they may not shape how
        its rows are read back either.
        """
        if names:
            return cls(
                query,
                root,
                names=True,
                prune=tuple(build_prune_args(settings.active_excluded)),
            )
        return cls(
            query,
            root,
            depth=settings.depth,
            fuzzy=settings.fuzzy,
            globs=tuple(
                build_glob_args(settings.active_excluded, settings.active_included)
            ),
        )


def search_problems(settings: Settings, names: bool = False) -> list[str]:
    """`pattern_problems` for the lists a search is about to apply.

    Only the lists in force: one switched off is not applied, so it cannot
    spoil anything. A name search applies the exclusions alone.
    """
    included = [] if names else settings.active_included
    return pattern_problems(included, settings.active_excluded)
