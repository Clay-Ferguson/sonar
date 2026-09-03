# Sonar — Query Syntax

## Query Syntax

- Unquoted terms are `regular expressions`
- `"quoted phrases"` match literally (not as regex)
- Space or `AND` requires all terms
- `OR` matches any term
- `NOT` (or `-term`) excludes
- Parenthetical groupings of `AND` / `OR` / `NOT` are allowed

## Regex Match Tips

- Whole word ABC: `\bABC\b`
- From 0 up to 10 characters: `.{0,10}`
- Any string of chars: `.*`

*Searches are case-insensitive, and a query matches a file when its terms
appear anywhere in that file — not necessarily on the same line.*

---

For everything else Sonar does, see the [User Guide](USER_GUIDE.md) — it is
open under **Options ▸ Help ▸ User Guide** as well.
