---
type: plan
status: done
---

# Plan: Hygiene Pipeline — Recognize `14U` and Canonicalize Ages at Comparison Time

## Context

On 2026-04-22 the owner had to manually merge two team duplicates that the weekly data-hygiene pipeline missed:

1. `EBU 14U Premier 1` ↔ `EBU 2012 Premier 1`
2. `14U 2012 Rush Union WI Select` ↔ `Rush Union WI 2012 Select`

**Root cause (confirmed empirically).** The age-token parsers (`scripts/team_name_normalizer.py:parse_age_gender` and the sibling `AGE_PATTERN` regexes in `scripts/find_fuzzy_duplicate_teams.py`, `src/utils/team_name_utils.py`, `src/models/game_matcher.py`, and `scripts/find_queue_matches.py`) only recognize U-prefixed age groups (`U14`, `U-14`, `BU14`) or digit+gender (`14B`, `B14`, `2014B`). None recognize the digit-then-U form (`14U`), even though `scripts/scrape_playmetrics_league.py:185` already has a precedent regex that handles both orderings. Two consequences:

- In `find_fuzzy_duplicate_teams.py:extract_distinctions`, `14u` falls through to Pass 4 (line 361-372) and lands in `squad_words` as if it were a mascot. `_should_skip_pair` (line 427) then rejects the pair because squad_words differ.
- Even when `14u` IS recognized as age, the `age_tokens` set in `_should_skip_pair` compares raw tokens: `{'2012'}` vs `{'u14'}` is a false mismatch, because the matcher never canonicalizes age tokens to a shared cohort key before set-comparison.

**Resolution strategy.** Two changes, both narrow:

1. **Parsers learn `14U`.** Add a new branch to `parse_age_gender` and extend every parallel `AGE_PATTERN` / Pass-3 classifier in the hygiene and game-matcher paths. `14U` is recognized as an age-group token (returns `U14`) rather than leaking into `squad_words` or coach-name detection.
2. **Matchers canonicalize age tokens at comparison time only.** Add a single shared helper `_canonicalize_age_token` in `src/utils/team_name_utils.py` (not per-file duplicates) and import it from `scripts/find_fuzzy_duplicate_teams.py` and `scripts/find_queue_matches.py`. The helper converts every raw age token (`2012`, `U14`, `14U`, `14UB`, `'12`, `'10/11`, bare `14`) to a canonical cohort key like `"u14"` using `src.utils.team_utils.CURRENT_YEAR`. Applied inside `extract_distinctions` before age_tokens land in the comparison set, and inside the queue matcher's `extract_age_group`. `_should_skip_pair` then compares canonical-form sets on both sides.

**Crucially: stored `team_name` is NOT rewritten.** The pre-review direction (rewrite every team_name to U-form in Step 3) was rejected because it contradicts `docs/TEAM_MERGE_RULES.md:145-157` ("preserve the original system: birth year stays birth year, U-group stays U##"), contradicts the pipeline comment at `.github/workflows/data-hygiene-weekly.yml:39` ("14B→2014"), and breaks Step 4 — `fix_team_age_groups.py:extract_birth_year` (lines 48-90) REQUIRES a 4-digit birth year in `team_name` to derive `age_group`. A U-form rewrite would cause Step 4 to return `None` for every rewritten team, silently breaking the age_group column. It would also force a permanent Aug-1 mass rewrite every season. Matcher-side canonicalization avoids all of that.

**Scope: in-pipeline consumers only.** The matchers directly used by the weekly hygiene pipeline and its queue step are in scope: `scripts/find_fuzzy_duplicate_teams.py` (Step 5), `scripts/find_queue_matches.py` (Step 6, also provides the `normalize_team_name` + `extract_team_variant` helpers imported by Step 5), plus their `src/utils/team_name_utils.py` and `src/models/game_matcher.py` cousins. MATCHING_CONFIG routing, ranking, and DB schemas remain untouched.

**Design decisions:**
- Canonical cohort key is built from `src.utils.team_utils.CURRENT_YEAR` (auto-rolls Aug 1; currently `CURRENT_YEAR == 2025`). Both U-form and birth-year tokens are converted into the key via `calculate_age_group_from_birth_year` (for birth years) or the U-age itself (for U-forms).
- `parse_age_gender("14U")` returns `("U14", None)` (U-form, matching the semantic meaning of the token). Existing `14B → ("2014", "Male")` stays unchanged — the docs' "preserve the original system" principle is honored.
- Season-year inconsistency between `src/utils/team_utils.CURRENT_YEAR` (Aug-1 rollover) and `find_queue_matches.py:507 _current_season_year` (calendar year) is a pre-existing footgun. This plan consolidates on `CURRENT_YEAR` inside the matcher canonicalization helper but does NOT remove or modify the local `_current_season_year` elsewhere — that's a separate cleanup.

## Pattern Survey

### Analogous Features

- `C:\PitchRank\scripts\scrape_playmetrics_league.py:185` — `_TEAM_U_AGE_RE = re.compile(r"\b(?:[Uu]-?(\d{1,2})|(\d{1,2})[Uu])\b")` handles BOTH `U14` and `14U` orderings. Lines 188-213 (`derive_team_age_group`) show the canonical consumption pattern: resolve birth-year first, then fall back to U-age token, then remap `u18→u19`. **This is the precedent for the new parser branches.**
- `C:\PitchRank\scripts\team_name_normalizer.py:98-201` — `parse_age_gender` has 8 sequential `re.match(r"^...$", token)` branches returning `(normalized_age_str, gender_or_None)`. Branches order longest-specific to shortest-generic, delegate gender via `normalize_gender(char)`, and fall through to `return (None, None)`. Line 123 handles `U14/U-14/BU14` via `^[Uu]-?(\d{1,2})([BbGgMmFf]?)$`. No branch handles `<digits>U`.
- `C:\PitchRank\scripts\find_fuzzy_duplicate_teams.py:238` — `AGE_PATTERN = re.compile(r"\b(20\d{2})\b|'(\d{2})(?:/(\d{2}))?|\b[Uu]-?(\d{1,2})\b")`. Used in `extract_distinctions` at `finditer` line 325 (collects raw tokens) and `search` line 329 (partitions secondary numbers). Pass 3 classifier at line 347 (`re.fullmatch(r"u-?\d{1,2}", tok)`) also doesn't match `14u`; when a token is neither classified nor matched by any Pass 3 alternate, Pass 4 (lines 361-372) dumps it into `squad_words`.
- `C:\PitchRank\src\utils\team_name_utils.py:418` — Verbatim duplicate of the `AGE_PATTERN` above. Used by the game-matcher family (`src/models/game_matcher.py`, `playmetrics_matcher.py`, `tgs_matcher.py`, `sincsports_matcher.py`). `_VARIANT_AGE_PATTERNS` list at lines 410-415 is the split-point regex list used by name-decomposition callers. Line 631-641 contains a Pass-3-style inline classifier with the same blind spot as `find_fuzzy_duplicate_teams.py:347`.
- `C:\PitchRank\src\models\game_matcher.py:255-260` — `_AGE_PATTERNS` list (NOT compiled `AGE_PATTERN`) — four split-point regexes, used at line 300 and 378 for coach-name / variant detection. Same blind spot: no `\d{1,2}[Uu]` alternate, so `FC Example 14U Riedell` skips coach detection silently.
- `C:\PitchRank\scripts\find_queue_matches.py:63-83` — `normalize_team_name(name)` does its own lowercase + age-format rewrites: `(b|g)(\d{2,4}) → \2`, `(\d{2,4})(b|g) → \1`, `u\s*(\d+) → u\1`. No `\d{1,2}u` rewrite — `14U` passes through as-is, preventing fuzzy matches at the queue stage (Step 6). Line 518 `extract_age_group` has its own `\bu(\d+)\b` that also misses `14U`.

### Reusable Utilities

- `C:\PitchRank\src\utils\team_utils.py:20` — `CURRENT_YEAR = _soccer_season_year()` auto-rolls every Aug 1. **Single source of truth for the season year.** Verified: `CURRENT_YEAR == 2025` today (2026-04-22, still in the 2025-26 soccer season).
- `C:\PitchRank\src\utils\team_utils.py:58-81` — `calculate_age_group_from_birth_year(birth_year, current_year=CURRENT_YEAR) -> Optional[str]` — formula `age = current_year - birth_year + 1`, returns `f"U{age}"` when `7 <= age <= 19`. Empirical: `2012→U14, 2011→U15, 2013→U13`. **Reuse this to convert birth-year tokens to canonical cohort keys.**
- `C:\PitchRank\scripts\fix_team_age_groups.py:32,42` — `calculate_age_group(birth_year)` imports `from src.utils.team_utils import CURRENT_YEAR`. Convention proof for the `scripts/ → src.utils/` import pattern. Uses `sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))` at line 21 (NOT the `scripts/` insert used by `normalize_team_names.py:27`).
- `C:\PitchRank\scripts\team_name_normalizer.py:88-96` — `normalize_gender(text)` — gender-char → `"Male"`/`"Female"`. Reuse for the new `parse_age_gender` branch's `[BbGgMmFf]?` capture.

### Convention Anchors

- **Parse_age_gender branch style**: `re.match(r"^...$", token)` full-token anchors, optional gender via `[BbGgMmFf]?`, `normalize_gender(char)` delegation, `return (normalized_age_str, gender_or_None)`. `[Ss]?` trailing tolerated for `14Bs`-style tokens. New `<digits>U[gender]?` branch must mirror this shape and place immediately before the `^(\d{2})([BbGgMmFf])[Ss]?$` branch at line 139 (close cousins, keep adjacent).
- **docs/TEAM_MERGE_RULES.md:145-157** (normative): "Preserve the original system — birth-year formats → 4-digit year; age-group formats → U##." The new `14U → U14` recognizer respects this (14U is an age-group format). Existing `14B → 2014` stays unchanged.
- **Test harness**: Zero pytest coverage for `parse_age_gender`, `extract_distinctions`, `AGE_PATTERN`, or `_AGE_PATTERNS` across the repo. Convention for this subsystem is an inline `__main__` block in `scripts/team_name_normalizer.py` using printed `✅`/`❌` rows against `(input, expected)` tuples. `scripts/validate_normalizer.py` is DB-backed, not a unit harness. Matcher modules (`find_fuzzy_duplicate_teams.py`, `team_name_utils.py`, `game_matcher.py`, `find_queue_matches.py`) have no inline test blocks today.
- **Commit shape (prior art)**: one focused commit per normalizer feature — `3f0744305` (age normalizer rewrite), `fcd18a0d8` (prioritize birth year), `ac0178916` (consolidate AGE_PATTERN into src/utils/team_name_utils.py). Extend `__main__` tests inline; update `docs/TEAM_MERGE_RULES.md` in the same commit when behavior changes.
- **Pipeline order (`.github/workflows/data-hygiene-weekly.yml:34-48`)**: Step 3 normalize runs before Step 4 fix_team_age_groups and Step 5 fuzzy merge. Step 3's comment promises "14B→2014, 15M→2015" (birth-year form). Step 4 depends on that.

### Proposed Alignment

- Mirror `scripts/scrape_playmetrics_league.py:185` for the new `<digits>U` recognizer shape.
- Mirror existing `parse_age_gender` branch style for the new branch.
- Canonicalization lives in the MATCHERS, not in `normalize_team_names.py`. Stored `team_name` retains its original form.
- Extend every parallel `AGE_PATTERN` / `_AGE_PATTERNS` / Pass-3 classifier in the hygiene and game-matcher paths so `14U` is recognized as age and doesn't leak into `squad_words` or coach-name detection.
- One shared `_canonicalize_age_token(tok) -> str | None` helper lives in `src/utils/team_name_utils.py` (the lower-level module already imported by game-matcher siblings). Takes a raw age token and returns a canonical cohort key like `"u14"` (or `None` when out of range / unrecognized). Both `scripts/find_fuzzy_duplicate_teams.py` and `scripts/find_queue_matches.py` import it via `from src.utils.team_name_utils import _canonicalize_age_token`. This rejects the earlier draft's per-file duplication plan: `_canonicalize_age_token` is imperative logic (U18→U19 remap, slash-form rule, cutoff thresholds) that drifts silently when duplicated — unlike the `AGE_PATTERN` constant which is pure data and can reasonably be per-module. A cross-file equivalence test in Step 6 catches any future regression.
- Tests: extend `scripts/team_name_normalizer.py` `__main__` block with `14U`/`14UB`/`14UG`/`14uM` rows. Add new inline `__main__` blocks at the tail of `scripts/find_fuzzy_duplicate_teams.py` (asserts `_canonicalize_age_token` + `_should_skip_pair` behavior on the two failure pairs), `src/utils/team_name_utils.py` (asserts AGE_PATTERN and canonicalizer), and a short assertion block appended to `scripts/find_queue_matches.py` under `if "--test" in sys.argv:`.

## Implementation Steps

1. **Add `<digits>U` branch to `parse_age_gender`**
   - Edit `C:/PitchRank/scripts/team_name_normalizer.py`. Insert a new branch between the `BU14`/`GU14` branch (ending at line 136 with `return (f"U{age_num}", gender)`) and the `14B`/`B14` branch starting at line 139.
   - New branch: `re.match(r"^(\d{1,2})[Uu]([BbGgMmFf]?)$", token)`. Extract `age_num = int(group(1))`; `gender = normalize_gender(group(2))` when `group(2)` is non-empty, else `None`.
   - Guard: only return a result when `6 <= age_num <= 19`. Rationale: covers U6-U19 (the full youth-soccer cohort range). `calculate_age_group_from_birth_year` validates `7 <= age <= 19`; this guard loosens to `U6` so existing U6 teams (if any exist) are still recognized as age tokens rather than leaking into squad_words. Upper bound 19 rejects nonsense tokens like `20U` or `25U`.
   - Return `(f"U{age_num}", gender)`. **No birth-year conversion inside the parser** — `14U` is semantically an age-group token (like `U14`), not a birth-year shorthand.
   - Update the docstring block at lines 102-119 to list the new examples: `'14U' → ('U14', None)`, `'14UB' → ('U14', 'Male')`, `'14uG' → ('U14', 'Female')`.

2. **Add shared `_canonicalize_age_token` helper in `src/utils/team_name_utils.py`**
   - Edit `C:/PitchRank/src/utils/team_name_utils.py`. At top of file, ensure `from src.utils.team_utils import CURRENT_YEAR, calculate_age_group_from_birth_year` is imported (add if missing — `team_utils` is a sibling module, no sys.path dance needed from within `src/utils/`).
   - Define module-level helper. Full spec (implementer must match this exactly — do not loosen):
     ```python
     def _canonicalize_age_token(tok: str) -> str | None:
         """Map any age token to a canonical cohort key like 'u14'.

         Accepts (case-insensitive; caller may pass lowercased and apostrophe-stripped):
           4-digit birth year:  '2012' -> 'u14'
           2-digit shorthand:   '12' when used as birth year -> 'u14' (via 2000+n if n<30 else 1900+n)
           U-age form:          'U14', 'u-14' -> 'u14'
           Digit-then-U form:   '14U', '14u' -> 'u14'
           With gender suffix:  '14ub', 'u14b', '14b', 'b14', 'b2012', '2012b' -> canonical + drop gender
           Slash dual-age:      '10/11' -> 'u15' (take LARGER 2-digit year = younger cohort; see rationale below)

         Returns None for:
           - Out-of-range ages (outside U6-U19 after canonicalization)
           - Unrecognized tokens (do NOT fall back to raw — silent drift masks bugs)

         U18 remap:
           After deriving the numeric age, apply `age = 19 if age == 18 else age`.
           U18 is merged into the U19 cohort everywhere else in PitchRank (see config/settings.py AGE_GROUPS,
           scrape_playmetrics_league.derive_team_age_group).

         Slash-form rationale:
           '10/11' means a dual-age division spanning 2010 and 2011 birth years. Per the PlayMetrics
           age-derivation memory (playmetrics_age_derivation.md), dual-age league labels are "play-up gates,
           not cohort labels" — the team is PRIMARILY the younger cohort with older players permitted up.
           So take the LARGER 2-digit year (younger players' birth year) as the canonical cohort.
           Example in 2025-26: '10/11' -> 2011 -> U15 -> 'u15'. A companion single-year '10 -> 2010 -> U16 -> 'u16',
           so they DO NOT match — slash teams remain distinct from single-cohort teams. Intentional.
         """
     ```
   - Cutoff convention for 2-digit-year shorthand: mirror `parse_age_gender`'s existing `2000 + n if n < 30 else 1900 + n` (line 144 of `team_name_normalizer.py`). Do NOT invent a new cutoff.
   - Unit-test this helper inline in `src/utils/team_name_utils.py`'s `__main__` block (see Step 6).
   - Extend `AGE_PATTERN` at line 418: add alternation `|\b(\d{1,2})[Uu]\b`. Final: `r"\b(20\d{2})\b|'(\d{2})(?:/(\d{2}))?|\b[Uu]-?(\d{1,2})\b|\b(\d{1,2})[Uu]\b"`.
   - Extend `_VARIANT_AGE_PATTERNS` at lines 410-415: append `r"\b\d{1,2}[Uu]\b"` as a new entry. Consumers in `src/models/game_matcher.py:300,378`, `playmetrics_matcher.py`, `tgs_matcher.py`, `sincsports_matcher.py` iterate the list and use `re.search`/`re.findall`, so appending is safe. Verify via the Step 6 assertion that `extract_team_variant("FC Example 14U Riedell") == "riedell"` (coach name detected correctly with the new split point).
   - If there's a Pass-3-style inline classifier elsewhere in this file (spot-check around lines 631-641), add the `|\d{1,2}u` alternation. Note: the existing Pass-3-style branch `(\d{1,4})u?[bgmf]` at `find_fuzzy_duplicate_teams.py:339` (sibling) emits a raw digit string into `age_tokens` — that must be wrapped by the helper too (see Step 3).

3. **Wire the helper into `scripts/find_fuzzy_duplicate_teams.py`**
   - Edit `C:/PitchRank/scripts/find_fuzzy_duplicate_teams.py`. Add the exact three-line sys.path idiom at the top (mirror `scripts/fix_team_age_groups.py:21`):
     ```python
     import os, sys
     sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
     ```
     Then `from src.utils.team_name_utils import _canonicalize_age_token`.
   - Extend `AGE_PATTERN` at line 238: same alternation change as Step 2. Final regex identical to the `team_name_utils.py` copy.
   - Extend Pass 3 classifier at line 347: change `re.fullmatch(r"u-?\d{1,2}", tok)` to `re.fullmatch(r"u-?\d{1,2}|\d{1,2}u", tok)`. Also add a same-line guard: the new alternate should only classify when `_canonicalize_age_token(tok)` returns a non-None — this ensures `20u` (out-of-range) is still leaked to `squad_words` rather than silently classified as an unknown age. In practice: wrap the classification block with `if _canonicalize_age_token(tok) is not None:`.
   - Inside `extract_distinctions`:
     - **Critical: the extended `AGE_PATTERN` changes the result of `AGE_PATTERN.search(name)` at line 329** (now `14U` matches where previously only later tokens like `2012` did). This moves the partition point for `secondary_nums`. Accept this behavior change — it's more correct, `14U` IS an age token — and verify via Step 6 regression assertion that `secondary_nums` for the Rush Union pair (`"14U 2012 Rush Union WI Select"`) collects `["2012"]` and not `["14", "2012"]`. The pair-level outcome is unchanged because both teams now canonicalize to `("u14",)` in the age_tokens set regardless of secondary_nums ordering.
     - Replace the age_tokens collection (line 325):
       ```python
       age_tokens = []
       for m in AGE_PATTERN.finditer(name):
           canonical = _canonicalize_age_token(m.group(0).lower().strip("'"))
           if canonical is not None:
               age_tokens.append(canonical)
       ```
       **Do NOT fall back to the raw token when canonicalization returns None.** Raw+canonical mixing in `tuple(sorted(age_tokens))` at line 387 produces non-deterministic lexicographic ordering that breaks the comparison at line 431.
     - Also wrap Pass 3's `age_tokens.append(age_num)` at line 343 with the helper: `canonical = _canonicalize_age_token(f"u{age_num}" if age_num else ""); if canonical: age_tokens.append(canonical)`. This ensures the raw digit string `"14"` emitted by `14ub`-token matches gets canonicalized to `"u14"`.
   - Do NOT modify `_should_skip_pair` logic at line 431 (`if da["age_tokens"] != db["age_tokens"]: return True`). After the above, both sides compare canonical-key sequences.

4. **Extend `_AGE_PATTERNS` at `src/models/game_matcher.py:255`**
   - Edit `C:/PitchRank/src/models/game_matcher.py`. Append `r"\b\d{1,2}[Uu]\b"` to `_AGE_PATTERNS` (lines 255-260).
   - Consumers at line 300 and 378 iterate the list and use `re.search` for split-point detection — appending is safe. Spot-verify no consumer relies on list length or index.

4. **Extend `_AGE_PATTERNS` at `src/models/game_matcher.py:255`**
   - Edit `C:/PitchRank/src/models/game_matcher.py`. Append `r"\b\d{1,2}[Uu]\b"` to `_AGE_PATTERNS` (line 255-260).
   - Consumers at line 300 and 378 iterate the list and use `re.search` for split-point detection — adding an entry is safe. Spot-verify no consumer relies on list length or index.

5. **Wire the helper into `scripts/find_queue_matches.py` (Step 6 of the pipeline)**
   - Edit `C:/PitchRank/scripts/find_queue_matches.py`. Add sys.path idiom and `from src.utils.team_name_utils import _canonicalize_age_token` (same shape as Step 3).
   - `normalize_team_name` at lines 63-83: after the existing `re.sub(r"\bu\s*(\d+)\b", r"u\1", n)` at line 78, add `n = re.sub(r"\b(\d{1,2})u\b", r"u\1", n)` to rewrite `14u → u14`. Ordering rationale: the existing sub at line 78 matches `u<optional-ws><digits>` so it cannot consume `14u` (no leading `u`); the new sub targets untransformed `14u` and must run AFTER line 78's lowercase-and-collapse pass. String-level rewrites inside `normalize_team_name` are returned as a TRANSIENT comparison string, not persisted — consistent with the "canonicalize at comparison time" principle (the function's output is a comparison key, not a stored field).
   - `extract_age_group` at lines 518-540: `extract_age_group` is called with a raw `name` (line 520 applies `.lower()` locally; not the `normalize_team_name`-processed string), so it needs its own `14U` recognition. Add a fallback branch after the existing U-prefix branch at line 524:
     ```python
     # Priority: digit-then-U form (e.g. "14U") — canonicalize via shared helper
     m = re.search(r"\b(\d{1,2})[Uu]\b", name_lower)
     if m and (canonical := _canonicalize_age_token(m.group(0))):
         return canonical  # 'u14', 'u15', etc. (already in the expected return form)
     ```
     Verify that `normalize_filter_age_group` output shape matches the helper's output shape (`u14` vs `U14`) — adjust case if needed.
   - Leave `_current_season_year` at lines 507-515 untouched (pre-existing footgun, separate cleanup — flagged in Known Limitations).

6. **Add inline `__main__` tests**
   - `C:/PitchRank/scripts/team_name_normalizer.py`: append to the existing `age_tests2` block (around line 473-484) new rows for age-only assertions: `("14U", "U14")`, `("14u", "U14")`, `("15U", "U15")`, `("10U", "U10")`, `("19U", "U19")`. Then append to `match_tests` (line 513+) gender-bearing assertions using the `(input, expected_tuple)` style: `parse_age_gender("14UB") == ("U14", "Male")`, `parse_age_gender("14UG") == ("U14", "Female")`, `parse_age_gender("14UM") == ("U14", "Male")`, `parse_age_gender("14UF") == ("U14", "Female")`. Negative rows: `parse_age_gender("20U") == (None, None)` (out of range guard), `parse_age_gender("14UZ") == (None, None)` (invalid gender char).
   - `C:/PitchRank/src/utils/team_name_utils.py`: new `if __name__ == "__main__":` block. Primary location for `_canonicalize_age_token` assertions (the helper lives here):
     - Single-cohort canonicalization in 2025-26 season (CURRENT_YEAR=2025): `_canonicalize_age_token("2012") == "u14"`, `("'12")`, `("U14")`, `("u-14")`, `("14U")`, `("14u")`, `("14ub")`, `("u14b")`, `("b2012")`, `("2012b")`, `("12b")`, `("b12")` all → `"u14"`.
     - Bare digit: `_canonicalize_age_token("14") == "u14"` (Pass 3 emits bare digits; helper must handle them).
     - U18 remap: `_canonicalize_age_token("U18") == "u19"` and `_canonicalize_age_token("2007") == "u19"` — both must equal each other.
     - Slash form: `_canonicalize_age_token("10/11") == "u15"` (take larger 2-digit year = 2011 = u15 in 2025-26 season). Companion assertion: `_canonicalize_age_token("10") == "u16"` (different result — intentional, slash teams stay distinct from single-cohort teams).
     - Out of range: `_canonicalize_age_token("20U") is None`, `_canonicalize_age_token("5U") is None`, `_canonicalize_age_token("2003") is None` (adult birth year).
     - Unrecognized: `_canonicalize_age_token("random") is None`, `_canonicalize_age_token("") is None`.
     - `AGE_PATTERN.search("Phoenix FC 14U Black").group(0) == "14U"`. Regression: `AGE_PATTERN.search("Phoenix FC U14 Black").group(0) == "U14"`.
     - `extract_team_variant("FC Example 14U Riedell") == "riedell"` (coach name detected correctly; verifies `_VARIANT_AGE_PATTERNS` extension works at the consumer level, not just regex level).
   - `C:/PitchRank/scripts/find_fuzzy_duplicate_teams.py`: add a new `if __name__ == "__main__":` guard at the tail (no block exists today). Assertions:
     - **Cross-file equivalence (drift detection):** `from src.utils.team_name_utils import _canonicalize_age_token as utils_canon`; assert `_canonicalize_age_token("14U") == utils_canon("14U")` and four other fixture tokens. Since the helper is now imported (not duplicated), this is a trivial identity assert — but keep it so a future refactor that re-introduces duplication fails loudly.
     - **Pass-4 leak regression (isolates the Pass-3 classifier fix from the canonicalization fix):** `assert "14u" not in extract_distinctions("EBU 14U Premier 1", "EBU")["squad_words"]` (before the fix, `14u` leaked to squad_words; after, Pass 3 classifies it).
     - **Canonicalization regression:** `extract_distinctions("EBU 2012 Premier 1", "EBU")["age_tokens"] == extract_distinctions("EBU 14U Premier 1", "EBU")["age_tokens"]` (both `("u14",)`).
     - **secondary_nums partition regression:** `extract_distinctions("14U 2012 Rush Union WI Select", "Rush Union WI")["secondary_nums"] == ("2012",)` (NOT `("14", "2012")` — the extended AGE_PATTERN now partitions at `14U`, consuming `14` into the age match).
     - **Full-pair match:** `_should_skip_pair("EBU 14U Premier 1", "EBU 2012 Premier 1", club_name="EBU") == False`.
     - **Full-pair match:** `_should_skip_pair("14U 2012 Rush Union WI Select", "Rush Union WI 2012 Select", club_name="Rush Union WI") == False`.
     - **Same-club different-squad regression:** `_should_skip_pair("Phoenix FC 2012 Red", "Phoenix FC 2012 Blue", club_name="Phoenix FC") == True` (still different colors).
     - **Cross-cohort regression:** `_should_skip_pair("Phoenix 2012 Red", "Phoenix 2013 Red", club_name="Phoenix") == True` (canonical keys `u14` vs `u13`).
     - **U18/U19 merge regression:** `_should_skip_pair("Phoenix U18 Red", "Phoenix 2007 Red", club_name="Phoenix") == False` (both canonicalize to `u19`).
     - **Slash-distinct regression:** `_should_skip_pair("Phoenix '10/11 Red", "Phoenix '10 Red", club_name="Phoenix") == True` (slash team → u15, single → u16).
   - `C:/PitchRank/scripts/find_queue_matches.py`: refactor the existing `if __name__ == "__main__":` block to branch on `"--test" in sys.argv` so the test block doesn't block CLI use. Assertions:
     - `normalize_team_name("Team 14U Blue") == "team u14 blue"`.
     - `normalize_team_name("Team U14 Blue") == "team u14 blue"` (regression — existing behavior preserved).
     - `extract_age_group("FC Example 14U", {}) == extract_age_group("FC Example U14", {})` — both return the same cohort key.
     - `extract_age_group("FC Example 2012", {}) == extract_age_group("FC Example 14U", {})` — birth-year and 14U resolve to same cohort.

7. **Update `docs/TEAM_MERGE_RULES.md`**
   - Read the file first. Find the "Age group formats → `U##`" section (around line 153-155) and add `14U`, `14u`, `14UB`, `14uG`, `14UM` to the list of recognized age-group forms.
   - Add a new "Canonicalization at comparison time" subsection explaining that matchers convert all recognized age forms to a canonical cohort key (`u14`) before comparison. Stored `team_name` is NOT rewritten. Reference the `_canonicalize_age_token` helper.

8. **Pre-flight sanity SQL (no writes)**
   - Run against production Supabase as a blast-radius sanity check:
     ```sql
     SELECT
       SUM(CASE WHEN team_name ~ '\b\d{1,2}[Uu]\b' THEN 1 ELSE 0 END) AS digit_u_form,
       SUM(CASE WHEN team_name ~ '\b[Uu]-?\d{1,2}\b' THEN 1 ELSE 0 END) AS u_prefix_form,
       SUM(CASE WHEN team_name ~ '\b20\d{2}\b' THEN 1 ELSE 0 END) AS birth_year_form,
       SUM(CASE WHEN team_name ~ '\b\d{1,2}[Uu]\b' AND team_name ~ '\b20\d{2}\b' THEN 1 ELSE 0 END) AS both_forms_in_one_name,
       COUNT(*) AS total
     FROM teams
     WHERE is_deprecated = false;
     ```
   - Expected: `digit_u_form` > 0 (else the bug report is fabricated). `both_forms_in_one_name` is the exact class of team like `"14U 2012 Rush Union WI Select"` — an upper bound on Case-2-style teams that the fix directly addresses. Paste into the PR description so reviewers see the scale of the fix.

## Known Limitations (document, don't fix)

- `scripts/find_queue_matches.py:_current_season_year` (line 507) uses calendar year; `src.utils.team_utils.CURRENT_YEAR` uses Aug-1 rollover. Around Aug 1 each year they diverge by one, leading to inconsistent cohort classification between the queue matcher and everywhere else. Pre-existing footgun, separate PR.
- `src/utils/team_name_utils.py:AGE_PATTERN` is a verbatim duplicate of `scripts/find_fuzzy_duplicate_teams.py:AGE_PATTERN`. Future work: consolidate into a single shared utility in `src/utils/`. Not in this PR — keeps the diff focused on the bug.
- The duplicate-age-token emission behavior in `scripts/normalize_team_names.py:145-208` (where a second age-parsable token falls through to "keep as-is") is a pre-existing behavior unrelated to this fix. Leaving it alone.

## Verification

- **Unit: parse_age_gender**
  - `cd /c/PitchRank && python scripts/team_name_normalizer.py`
  - Expected: existing `✅` rows pass + every new `14U`/`14UB`/`15U`/negative row prints `✅`.
- **Unit: fuzzy matcher canonicalizer + _should_skip_pair**
  - `cd /c/PitchRank && python scripts/find_fuzzy_duplicate_teams.py` (runs the new `__main__` block)
  - Expected: both failure pairs assert `_should_skip_pair == False`; cross-cohort regression assertion still `True`; same-cohort-different-squad regression still `True`.
- **Unit: src/utils/team_name_utils AGE_PATTERN**
  - `cd /c/PitchRank && python -m src.utils.team_name_utils`
  - Expected: `14U` and `14u` match; all pre-existing patterns still match.
- **Unit: find_queue_matches normalize_team_name + extract_age_group**
  - `cd /c/PitchRank && python scripts/find_queue_matches.py --test`
  - Expected: `14U` normalized to `u14`; `extract_age_group` returns identical result for `14U` and `U14`.
- **Integration: fuzzy matcher on failure pairs (end-to-end)**
  - `cd /c/PitchRank && python -c "
import sys; sys.path.insert(0, 'scripts')
from find_fuzzy_duplicate_teams import extract_distinctions, _should_skip_pair, score_team_pair
pairs = [
    ('EBU 14U Premier 1', 'EBU 2012 Premier 1', 'EBU'),
    ('14U 2012 Rush Union WI Select', 'Rush Union WI 2012 Select', 'Rush Union WI'),
]
for a, b, club in pairs:
    skip = _should_skip_pair(a, b, club)
    score = score_team_pair({'team_name': a, 'club_name': club}, {'team_name': b, 'club_name': club})
    print(f'{a!r:50} vs {b!r:40} skip={skip} score={score}')
"`
  - Expected: both pairs print `skip=False` and `score >= 0.90`.
- **Dry-run: fuzzy duplicate scan**
  - `cd /c/PitchRank && python scripts/find_fuzzy_duplicate_teams.py --age-group u14 --gender male --dry-run --min-score 0.90`
  - Expected: script completes without error. New suggested merges may surface (siblings of the EBU / Rush pairs). Spot-check the top 20 for false positives — none should appear because canonicalization only changes how age tokens are compared, not the squad/program/color checks.
- **Regression: weekly workflow dispatch dry-run**
  - Trigger `.github/workflows/data-hygiene-weekly.yml` with `gender=both, dry_run=true`.
  - Step 3 rewrite count MAY increase slightly: Step 1 extends `parse_age_gender` to recognize `14U` tokens, which changes `normalize_team_name`'s behavior for teams with `14U` in their name. Specifically, those teams will now have `14U` recognized as an age token and emitted as `U14` (instead of passed through untransformed). Expected delta: roughly equal to the `digit_u_form` count from Step 8's pre-flight SQL.
  - Pre/post DB sample: before triggering, pick 5 teams from production where `team_name ~ '\b\d{1,2}[Uu]\b'` (via the Step 8 SQL). Record their pre-run `team_name`. After the dry-run, the log's "sample transformations" section should show them rewritten (e.g., `"EBU 14U Premier 1"` → `"EBU U14 Premier 1"`). No team should have its non-age content altered.
  - Step 5 suggested-merge count MAY increase — the fix uncovers previously-missed duplicates. Spot-check the top 20 new suggestions for false positives (teams that should stay separate).
- **Edge cases covered by the `__main__` assertions (see Step 6)**
  - Slash vs single-cohort: `'10/11 → u15` (larger 2-digit year rule) while `'10 → u16` in 2025-26 season. Slash teams stay DISTINCT from single-cohort teams of either year. Intentional — dual-age divisions are primarily the younger cohort per `playmetrics_age_derivation.md`.
  - U18 ↔ U19 merge: both forms and birth year 2007 all canonicalize to `u19` via the helper's remap.
  - Gender mismatch: `14UB` and `14UG` both canonicalize age to `u14`, but `_should_skip_pair` still rejects via the gender field from `parsed_gender`. No regression expected — add this as an explicit assertion in Step 6 if time permits.
  - Out-of-range sanity: `20U` and `5U` return None from the helper, which means they fall to squad_words in `extract_distinctions` (not silently consumed as age). Verified via Step 6 assertion.

## Context Files

- `C:\PitchRank\scripts\team_name_normalizer.py` — `parse_age_gender` (primary parser edit), inline `__main__` tests.
- `C:\PitchRank\src\utils\team_name_utils.py` — PRIMARY home of the new `_canonicalize_age_token` helper. AGE_PATTERN extension (line 418), `_VARIANT_AGE_PATTERNS` extension (lines 410-415), Pass-3 classifier (line 631-641 region), new inline `__main__` tests (most comprehensive coverage).
- `C:\PitchRank\scripts\find_fuzzy_duplicate_teams.py` — imports `_canonicalize_age_token` from `src.utils.team_name_utils`; AGE_PATTERN extension (line 238), Pass 3 extension (line 347), canonicalization wired into `extract_distinctions` (line 325+), new inline `__main__` tests including cross-file equivalence and Pass-4 leak regression.
- `C:\PitchRank\src\models\game_matcher.py` — `_AGE_PATTERNS` list at lines 255-260.
- `C:\PitchRank\scripts\find_queue_matches.py` — `normalize_team_name` (line 63) and `extract_age_group` (line 518).
- `C:\PitchRank\src\utils\team_utils.py` — `CURRENT_YEAR` + `calculate_age_group_from_birth_year` (reuse; do not modify).
- `C:\PitchRank\scripts\fix_team_age_groups.py` — precedent for `scripts/` → `src.utils/` import idiom (line 21, 32). Also the code that REQUIRES birth-year form to survive in team_name — hence our decision NOT to rewrite team_name.
- `C:\PitchRank\scripts\scrape_playmetrics_league.py` — precedent regex for the new `<digits>U` branch (line 185).
- `C:\PitchRank\docs\TEAM_MERGE_RULES.md` — normative spec; preserves "birth-year stays birth-year" principle (line 157). Update to document new `14U` recognition and matcher-side canonicalization.
- `C:\PitchRank\.github\workflows\data-hygiene-weekly.yml` — pipeline order reference; comment at line 39 explains Step 3's output convention.
