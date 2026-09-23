"""What the user typed, read the ways ugrep's own parser cannot be asked to.

The content search hands the query to ugrep untouched — `-%` is ugrep's
Boolean query language, and it is the only parser that matters there. Two
other consumers need to understand it themselves, and this is them: a name
search, which runs find and so needs the query as `-iname` patterns, and the
PDF pane, whose search takes one literal string. `MODE_CONTENT` and
`MODE_NAMES` are the two things a query can be matched against.

Pure string work: no processes, no Qt, nothing from the rest of the package.
"""

from __future__ import annotations

import shlex

# What the query is matched against: the text inside files, or the names of
# files and folders. The strings are also the dropdown's labels, so there is
# one spelling of each and nothing to map between.
MODE_CONTENT = "Content"
MODE_NAMES = "Filenames"

# The characters that make a word of a name query a glob of its own rather
# than a fragment to be found anywhere in the name.
NAME_GLOB_CHARACTERS = set("*?[")


def name_terms(query: str) -> list[str]:
    """A name query as `find -iname` patterns, one per word, all required.

      report            -> *report*          (anywhere in the name)
      report 2024       -> *report*, *2024*  (both, in either order)
      "my report"       -> *my report*       (a quoted phrase is one word)
      *.pdf             -> *.pdf             (a glob, on the whole name)

    Not ugrep's query language: find has no regexes, OR or NOT, and a name
    search that half-understood them would be worse than one that plainly
    does words and globs. An unbalanced quote falls back to splitting on
    whitespace, so `it's` is still searched for rather than refused.
    """
    try:
        words = shlex.split(query)
    except ValueError:
        words = query.split()
    return [
        word if set(word) & NAME_GLOB_CHARACTERS else f"*{word}*"
        for word in words
        if word
    ]


# What a Boolean query's operators look like, and the characters that make an
# unquoted term a regex rather than a word. Both are needed by
# `literal_query_term()` below and nowhere else.
QUERY_OPERATORS = {"AND", "OR", "NOT"}
REGEX_METACHARACTERS = set(".^$*+?()[]{}|\\")


def literal_query_term(query: str) -> str | None:
    """One plain string out of a Boolean query, or None if it has none.

    For the PDF pane, whose search (Qt's, hence pdfium's) takes a single
    literal string and knows nothing about regexes, AND/OR or negation. This
    picks the first term of `query` that survives translation:

      "hello world" foo  -> hello world   (a quoted phrase is already literal)
      cat dog            -> cat           (the first of an AND, not both)
      -secret cat        -> cat           (a negated term matches nothing here)
      NOT secret cat     -> cat           (and so does one negated by keyword)
      col(o|ou)r         -> None          (a regex, not a word)

    Terms are dropped rather than approximated, and None is an ordinary
    answer: the caller renders the PDF with no highlighting at all, the same
    as a file ugrep found nothing in. Approximating would be worse — a regex
    searched literally would mark text the search never matched.

    Only the *first* survivor: the search model highlights one string, so a
    two-term AND marks one of the two. That is the known limit of this.
    """
    try:
        # posix=False so the quotes stay on the token: whether a term was
        # quoted is exactly what decides if it is literal, and posix mode
        # strips that evidence away.
        parts = shlex.split(query, posix=False)
    except ValueError:
        # An unbalanced quote. ugrep may still have made sense of it; this
        # cannot, and "no highlighting" is the honest answer.
        return None

    negated = False
    for part in parts:
        # Parentheses group terms in Boolean mode, so a leading or trailing
        # one belongs to the query rather than to the term.
        token = part.strip("()")
        if not token:
            continue
        if token in QUERY_OPERATORS:
            # NOT is the keyword spelling of a leading '-': it negates the
            # term after it, which must be skipped just the same.
            negated = token == "NOT"
            continue
        if negated or token[0] in "-!":  # what the file must *not* contain
            negated = False
            continue
        quoted = len(token) >= 2 and token[0] == token[-1] and token[0] in "\"'"
        term = token[1:-1] if quoted else token
        if not term:
            continue
        if not quoted and set(term) & REGEX_METACHARACTERS:
            continue
        return term
    return None
