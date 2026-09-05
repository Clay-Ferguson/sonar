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

*Searches are case-insensitive, and a query matches a file when its terms appear anywhere in that file — not necessarily on the same line.*

*With **Find near matches** turned on in **Options ▸ Settings**, every term above — quoted, unquoted or negated — also matches words spelled a little differently. The first letter still has to be right. See [Finding near matches](USER_GUIDE.md#finding-near-matches).*

---

For everything else Sonar does, see the [User Guide](USER_GUIDE.md) — it is open under **Options ▸ User Guide** as well.
