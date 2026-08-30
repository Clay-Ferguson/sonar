# SonarEx configuration

SonarEx reads one file:

```
~/.config/sonarex/sonarex-config.yaml
```

It is created with defaults the first time SonarEx runs, and it holds exactly
two settings — the glob patterns that scope every search.

There is no settings dialog yet, so edit this file by hand. A configuration
dialog that writes these same two lists is planned.

## The file

```yaml
search:
  # Files to search. An EMPTY list means "search everything" (the default).
  included: []

  # Directories and files to skip.
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
```

Changes take effect on the next search — there is no need to restart SonarEx.

## `search.included`

A **whitelist**. Empty (the default) means every file is searched.

The moment you add an entry, only files matching one of these patterns are
searched and *everything else is silently ignored* — which is the one setting
here that can quietly hide results you expected to see. Leave it empty unless
you specifically want to search a narrow set of file types.

```yaml
search:
  included:
    - "*.md"
    - "*.txt"
    - "*.py"
```

Patterns are matched against the filename, so `*.md` means "any Markdown file
at any depth".

## `search.excluded`

Directories and files to skip. Written in `find -path` style; SonarEx
translates them into ugrep's glob syntax:

| You write | SonarEx passes to ugrep | Meaning |
|---|---|---|
| `*/node_modules/*` | `!node_modules/` | skip any directory named `node_modules`, at any depth |
| `*/src/generated/*` | `!**/src/generated/**` | skip that nested path |
| `*.log` | `!*.log` | skip files by name |

The common case is the first row: `*/NAME/*` excludes a directory called
`NAME` wherever it appears in the tree.

Exclusions are worth keeping generous. Skipping `node_modules`, `.git` and
build output is usually the difference between a search that returns in a
second and one that grinds through a hundred thousand irrelevant files.

## When the config is missing or broken

Every failure degrades to "no patterns", never to an error:

- **File missing** — recreated with the defaults above on the next run.
- **Malformed YAML** — reported on stdout, and the search runs unfiltered.
- **A key holding the wrong type** (say `included: "*.md"` instead of a list)
  — that key is ignored; the other still applies.
- **Non-string entries** in a list — dropped individually.

A search never fails because of a typo in this file. If results look wrong,
check the file for a mistake rather than assuming the search broke.

## What is *not* configurable

Case-insensitivity, Boolean query mode, whole-file matching, and the PDF
filter are fixed. They are the behavior described in the
[README](../README.md#query-syntax) and are not read from this file.
