# Data & Pandas Safety

## pandas fillna(None) will crash
`fillna(None)` raises TypeError in modern pandas. Use `where(col.notna(), None)` or conditional assignment instead. Also: columns initialized with `None` stay as `object` dtype even after filling with numeric values — set the dtype explicitly.

## `str.isdigit()` is Unicode-aware and unbounded
A shape check like `s.startswith("u") and s[1:].isdigit()` accepts `u٣٢`, `u１２`, `u²` and a
5,000-digit string, because `isdigit()` is true for every Unicode digit class and nothing
caps the length. Any value that reaches a database write or a PostgREST filter needs an
explicit ASCII-bounded pattern (`re.match(r"^u[0-9]{1,2}$", s)`), not a character-class test.

## `re.IGNORECASE` folds Unicode look-alikes
Without `re.ASCII`, `(?i)boys` matches `Boyſ` and `(?i)girls` matches `Gİrls`, so a
`.lower()` lookup into a word table keyed on ASCII raises `KeyError` on text that a scraped
label or a pasted roster can carry. Scope the flag to the word itself (`\b(?a:(boys|girls))\b`):
a whole-pattern `re.ASCII` also makes `\b` ASCII-only, and `Menü` then reads as `Men`. And
NFC-normalise pasted text before splitting it into words: a decomposed accent (common from
macOS and PDFs) splits `México` into two words.

## Batch sizing
Don't over-correct batch sizes after a single timeout or failure. Balance reliability with runtime. Dropping from 1000 to 100 rows per batch turns a 5-minute job into a 50-minute one. Investigate the actual failure before shrinking batches.
