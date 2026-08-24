---
status: done
---

# Plan: Team Name Normalization — Structured Identity (Hygiene Initiative)

## Context

`teams.team_name` is a freeform string doing two jobs (display + matching) and reliably doing neither. Step 1 of `data-hygiene-weekly.yml` already canonicalizes age tokens and strips gender words, but the structure of the resulting string still varies wildly across teams. Dry-run analysis surfaced three independent hygiene gaps that all collapse the same canonical team identity (Club + Age + League + Distinction): no persisted distinction facet (89.5% of teams have a distinguisher today, just unstored); ~316 age-group misclassifications driven by club names with embedded numbers like `Union 10 FC`; and ~1,510 u13+ teams missing `league` because `backfill_team_leagues.py` either never ran exhaustively or has detection gaps (notably no Pre-* exclusion).

Fixing all three together — in execution order **B → C → A** — gives the ranking engine a clean cohort key without rework. The distinction column reads `age_group` and `league`; both must be correct first. The spec at `docs/superpowers/specs/2026-05-01-team-name-normalization-design.md` is the source of truth for scope, schema, and out-of-scope boundaries.

## Pattern Survey

### Analogous Features

- `C:/PitchRank/supabase/migrations/20260402000000_add_league_column.sql:1-7` — Most directly analogous additive `ALTER TABLE teams ADD COLUMN IF NOT EXISTS <col> TEXT;` with single-column index and `COMMENT ON COLUMN`. The new `distinction` column is structurally identical to `league`.
- `C:/PitchRank/supabase/migrations/20251208000001_add_team_deprecation.sql:1-46` — Heavier additive-column template: `ADD COLUMN IF NOT EXISTS … DEFAULT …`, multiple partial indexes, `COMMENT ON COLUMN`, and a `DO $$ … information_schema.columns RAISE EXCEPTION` verification block.
- `C:/PitchRank/supabase/migrations/20260424000000_add_priority_score_to_review_queue.sql:1-15` — Recent minimal additive migration: `ADD COLUMN IF NOT EXISTS … DOUBLE PRECISION;`, `COMMENT ON COLUMN`, single `CREATE INDEX IF NOT EXISTS`. Closest in size/shape to a `teams.distinction TEXT` migration.
- `C:/PitchRank/scripts/backfill_team_leagues.py:1-209` — End-to-end analog for workstream A's backfill: paginated `paginated_fetch("teams", …)`, regex classification, `Rich` summary table, `--dry-run` flag, batched `update().eq("team_id_master", tid)` writes with retry + client refresh every 2000 rows. Same script also owns workstream C.
- `C:/PitchRank/scripts/scan_teams_nl_national_league_u13_u19.py:118-146` and `C:/PitchRank/scripts/assign_ecnl_rl_from_name_u13_u19.py:165` — Surgical name-pattern → `teams.league` updaters. Same retry-with-`create_client` pattern as `backfill_team_leagues.py`.
- `C:/PitchRank/scripts/backfill_missing_club_names.py:350,393` and `C:/PitchRank/scripts/backfill_missing_state_codes.py:361,403` — Single-column-update Supabase REST backfills with `--dry-run`, `--limit`, `--workers`, paginated fetch, per-row update. Closest existing analogs for a per-row-distinction backfill that does NOT use psycopg2.
- `C:/PitchRank/scripts/normalize_team_names.py:216-315` — Direct-Postgres path (`run_with_psycopg2`): `psycopg2.connect(DATABASE_URL)`, single `cursor`, per-row `UPDATE teams SET … WHERE id = %s`, single `conn.commit()` at end. The existing pure-psycopg2 backfill template; Step 1 of the hygiene workflow.
- `C:/PitchRank/scripts/restore_rankings_from_history.py:115-220` — Bulk `psycopg2 + execute_values(…, page_size=1000)` with `ON CONFLICT … DO UPDATE`. The chunked-1000 idiom called out in `gotcha_supabase_bulk_updates.md`.
- `C:/PitchRank/.github/workflows/data-hygiene-weekly.yml:99-202` — All four hygiene steps (Step 1 normalize, Step 2 fix age, Step 3 fuzzy, Step 4 queue) share a copy-paste template: `id: stepN`, `if: ${{ !contains(format(',{0},', github.event.inputs.skip_steps || ''), ',N,') }}`, `DRY_RUN_FLAG=""` shell branch, `python scripts/<x>.py $FLAG 2>&1 | tee logs/stepN_<name>.log`, `grep -oP '…' logs/… || echo "0"`, `echo "<key>=$VAL" >> $GITHUB_OUTPUT`. The summary block at lines 215-241 reads `${{ steps.stepN.outputs.<key> || 'skipped' }}`.
- `C:/PitchRank/src/models/playmetrics_matcher.py:417-509`, `C:/PitchRank/src/models/sincsports_matcher.py:659-740`, `C:/PitchRank/src/models/tgs_matcher.py:586-665`, `C:/PitchRank/src/models/modular11_matcher.py:1258-1375`, `C:/PitchRank/src/models/affinity_wa_matcher.py:339-392` — Five parallel `_create_new_<provider>_team()` methods. Each builds a flat `team_data = { team_id_master, team_name, club_name, age_group, gender, [state_code,] provider_id, provider_team_id, [created_at] }` dict and calls `self.db.table("teams").insert(team_data).execute()`. This is the only insertion site for new `teams` rows in the import pipeline.
- `C:/PitchRank/src/models/game_matcher.py:1420-1483` — `_create_alias()` is the base-class method for writing `team_alias_map`; called by every subclass after autocreate (`playmetrics_matcher.py:355`, `affinity_wa_matcher.py:315`, `sincsports_matcher.py:607`, `tgs_matcher.py:554`).
- `C:/PitchRank/src/etl/enhanced_pipeline.py:208-267` — Orchestration site: `_ensure_initialized()` switches on `self.provider_code.lower()` to instantiate the right matcher. No team_data is built here; matchers own the write path.
- `C:/PitchRank/scripts/team_name_normalizer.py:98-217` — `parse_age_gender(token)` is a pure pattern-cascade function; the `\d{2}` bare-digit branch (lines 196-203) is what swallows club-token numbers like `10` in "Union 10 FC". `normalize_team_name(team_name, club_name)` (lines 122-213) is the per-token loop that calls it.
- `C:/PitchRank/src/utils/team_name_utils.py:671-818` — `extract_distinctions(name)` returns the dict workstream A's `resolve_distinction()` will compose from. `should_skip_pair(name_a, name_b)` (lines 821-852) shows the canonical "every distinction must match" comparison.

### Reusable Utilities

- `C:/PitchRank/src/utils/team_name_utils.py:671` — `extract_distinctions(name) -> Dict` returns `colors`, `directions`, `programs`, `team_number`, `location_codes`, `squad_words`, `coach_name`. Source for `resolve_distinction()`.
- `C:/PitchRank/src/utils/team_name_utils.py:30-409` — Shared frozensets `TEAM_COLORS`, `DIRECTION_CANONICAL`, `PROGRAM_WORDS`, `LOCATION_CODES`, `NOISE_WORDS`, `US_STATES`. Used directly by the length-2/3 token recovery filter.
- `C:/PitchRank/src/utils/team_name_utils.py:993-1006` — `has_ecnl_rl`, `has_ecnl_only`, `has_protected_division` league-marker helpers. Workstream C's Pre-* exclusion can grow alongside these.
- `C:/PitchRank/scripts/backfill_team_leagues.py:106-122` — `paginated_fetch(table, select, filters)` reusable in `backfill_team_distinction.py`.
- `C:/PitchRank/scripts/team_name_normalizer.py:88-95` — `normalize_gender(text)` token→`Male/Female` helper.
- `C:/PitchRank/scripts/dryrun_team_distinction.py` and `C:/PitchRank/scripts/dryrun_investigate_c_and_d.py` — Already-validated reference implementations of the resolution priority + club-token-strip + length-2/3 recovery + age-misclass detector + missing-league detector. The production code in this plan should mirror their logic exactly.

### Convention Anchors

- **Migration filename + layout**: `supabase/migrations/<YYYYMMDDHHMMSS>_<verb>_<noun>.sql`. Recent additive column migrations use `ADD COLUMN IF NOT EXISTS`, `COMMENT ON COLUMN`, `CREATE INDEX IF NOT EXISTS idx_<table>_<col>`. Closest precedent for `teams.distinction TEXT NULL` is `20260402000000_add_league_column.sql`.
- **Backfill script idiom — Supabase REST**: `scripts/backfill_*.py` follow a fixed shape: load `.env.local` then `.env` via `python-dotenv`, accept `SUPABASE_SERVICE_ROLE_KEY or SUPABASE_KEY`, paginated fetch in 1000-row batches, classify in memory, `--dry-run` exits before writes, batch updates of 50 rows with 3-attempt retry that re-creates the client on failure and refreshes every 2000 writes (`backfill_team_leagues.py:184-203`). Rich console output with a summary `Table`. Per `gotcha_supabase_bulk_updates.md`, anything writing >10K rows must use psycopg2; smaller backfills stick with Supabase REST.
- **Backfill script idiom — psycopg2 chunked**: `with psycopg2.connect(database_url) as conn: with conn.cursor() as cur:`, `from psycopg2.extras import execute_values`, `execute_values(cur, "INSERT … ON CONFLICT … DO UPDATE", rows, page_size=1000)`, single `commit` at exit. See `restore_rankings_from_history.py:115-220`.
- **Hygiene workflow step shape** (`.github/workflows/data-hygiene-weekly.yml`): `id: step<N>`, gating expression `if: ${{ !contains(format(',{0},', github.event.inputs.skip_steps || ''), ',<N>,') }}`, optional `DRY_RUN_FLAG=""` set from `github.event.inputs.dry_run`, run line `python scripts/<x>.py $FLAGS 2>&1 | tee logs/step<N>_<slug>.log`, output extraction via `grep -oP '<pattern>' logs/… || echo "0"` then `echo "<key>=$VAL" >> $GITHUB_OUTPUT`. Logs upload from `logs/step*.log`; summary table reads `${{ steps.step<N>.outputs.<key> || 'skipped' }}`. Pipeline-order header comment + "Why this order" block (yml:34-50) updated whenever steps change.
- **Provider-matcher autocreate write path**: Every provider has `_create_new_<provider>_team()` building an inline `team_data` dict and calling `self.db.table("teams").insert(team_data).execute()`. Each subclass `_match_team()` calls `super()._match_team()` first, then on `not matched` autocreates and immediately invokes inherited `self._create_alias(...)`. Race: pre-insert `select … .single()` and `23505 / "duplicate key"` exception fallback. The `enhanced_pipeline._ensure_initialized` orchestration does NOT touch team_data — provider knowledge stays in matchers.
- **Team-name parsing seam**: `scripts/team_name_normalizer.py` owns the per-token state machine for hygiene Step 1; `src/utils/team_name_utils.py` owns the structured-decomposition path used by import-time matching. `parse_age_gender` is the natural injection point for a club-token-skip filter — currently has no awareness of `club_name`, but `normalize_team_name` already passes `club_name` and tokenizes against it. A wrapper `resolve_distinction(name, club_name)` lives most naturally in `src/utils/team_name_utils.py` next to `extract_distinctions` / `should_skip_pair`.
- **League regex location**: `LEAGUE_PATTERNS` lives only in `scripts/backfill_team_leagues.py:47-82` as a module-level `list[tuple[str, re.Pattern]]` checked in priority order. Pre-* exclusion is already implemented as three explicit `re.search` checks in `detect_league_from_name` (`backfill_team_leagues.py:91-103`) before the `LEAGUE_PATTERNS` loop. Convention: add new exclusions as additional explicit `if re.search(…): return None` lines, not as negative lookaheads.
- **Test runner convention**: `scripts/team_name_normalizer.py:472-569` and `src/utils/team_name_utils.py:1014-1095` both put inline `if __name__ == "__main__":` test cases that print `✅`/`❌` and exit non-zero on failure.
- **Migrations don't auto-apply** (per `gotcha_supabase_migrations_and_db_access.md`): from this Windows env, port 5432 + pooler 6543 are blocked. Migration files must be applied via Supabase Dashboard SQL editor or CLI from another env. Plan must surface this so the implementer doesn't expect `supabase db push` to "just work" locally.

### Proposed Alignment

- Workstream A migration mirrors `20260402000000_add_league_column.sql` (`ADD COLUMN IF NOT EXISTS … TEXT;` + `COMMENT ON COLUMN` + composite index on `(club_name, age_group, league, gender, distinction)`).
- `resolve_distinction(name, club_name)` lives in `src/utils/team_name_utils.py` next to `extract_distinctions`. Logic mirrors `scripts/dryrun_team_distinction.py:resolve_distinction` exactly — no new behavior, just promote the already-validated dry-run logic.
- `scripts/backfill_team_distinction.py` built from the `backfill_team_leagues.py` template (paginated_fetch + retry-with-client-refresh). Stays under 10K-row threshold per row touched; Supabase REST, not psycopg2.
- Step 1b in `data-hygiene-weekly.yml` follows the verbatim shell template (skip_steps gating, `DRY_RUN_FLAG`, `tee logs/step1b_…`, `GITHUB_OUTPUT`, summary row). The new backfill script must explicitly emit `Updated: N` and `Would update: N` lines so the existing grep template `(Would update|Updated): \K\d+` works (the parent template's `✓ Updated 1,234 / 5,678` comma-formatted line in `backfill_team_leagues.py:200` does NOT match this grep — pin the format in the new script).
- Populate `distinction` at each `_create_new_<provider>_team()` site by computing `resolve_distinction(<input>, club_name)` and adding it to `team_data`. The `<input>` is per-matcher (asymmetric — see Step 12 for the exact variable per file). Orchestration layer (`src/etl/enhanced_pipeline.py`) untouched.
- **Spec divergence**: the spec's Files table for Workstream A lists `src/models/game_matcher.py` and `src/etl/enhanced_pipeline.py` as EDIT sites. The plan deliberately supersedes that — `game_matcher.py` only writes `team_alias_map` (not `teams` rows; insert paths live in the per-provider `_create_new_*_team()` methods), and `enhanced_pipeline._ensure_initialized` only dispatches matchers without building `team_data`. Neither file is edited in this initiative.
- Workstream B has TWO parser patch sites (the reviewer caught this): `fix_team_age_groups.py:extract_birth_year` is the function the sweep actually consults — patching only `parse_age_gender` in `team_name_normalizer.py` would not change a single age-group decision in the sweep. Both are patched, with `extract_birth_year` doing the real work for the 316-row sweep and `parse_age_gender` preventing future pollution from Step 1 of the weekly hygiene workflow.
- Workstream C: `backfill_team_leagues.py:94-98` already early-returns for `Pre[\s\-]*ECNL`, `Pre[\s\-]*MLS`, and `PRE[\s\-]*ACADEMY`. The actual gaps are only `Pre-NPL` and `Pre-NL`. Plan's Step 5 reflects this. Per `architecture_age_pattern_drift.md`, AGE_PATTERN regex variants exist in 4 files (`fuzzy`, `team_name_utils`, `game_matcher`, `find_queue_matches`); patching only one in this initiative is intentional but worth noting for future work.

## Implementation Steps

### Workstream B — Age-group misclassification fix

**Decision-site discovery (load-bearing context for the implementer):** The 316-row sweep is driven by `scripts/fix_team_age_groups.py:extract_birth_year` (`fix_team_age_groups.py:52-98`), NOT by `scripts/team_name_normalizer.py:parse_age_gender`. The two functions live in different scripts and run at different stages of the weekly pipeline. Patching only `parse_age_gender` would prevent FUTURE Step-1 pollution but would not change a single age-group decision when the Step-2 sweep runs over already-stored teams. Both functions need parallel patches: `extract_birth_year` does the real work for the 316-row sweep; `parse_age_gender` prevents future pollution.

Additionally: when `extract_birth_year` reads a team_name that Step 1 of the weekly workflow has already polluted (e.g., DB stores `"Union 2010 FC 2008"` because the original `"Union 10 FC 2008 Boys"` was rewritten by `parse_age_gender` years ago), the cleanest path is to read `team_name_original` when present and fall back to `team_name` only when null. `team_name_original` is the raw provider name preserved by `normalize_team_names.py:280-289`.

**Empirical baseline (verified 2026-05-01 against the 316 candidates):** 72% of misclassified rows have `team_name_original IS NULL` — these teams have never been touched by Step 1, so `team_name` IS the unpolluted raw provider form. The remaining 28% have non-NULL `team_name_original` that examination shows IS the raw provider name (`B2019`, `B2006`, `(19B)`, `HYSA B2006 BLUE-PR`, etc., not the normalized form). The fallback strategy `team_name_original or team_name` therefore reads unpolluted text in both cases. A pre-sweep verification step (Step 5 below) re-runs this sample query before the live sweep to confirm the property still holds.

**Critical edge case in club_skip_tokens construction:** For `club_name="Union 10 FC"`, the literal token set is `{"union", "10", "fc"}` — but the polluted `team_name` contains `2010`, NOT `10`. Skipping the matched 4-digit year against the literal set fails: `"2010" in {"union", "10", "fc"}` is False. The set must be **expanded**: for any 2-digit numeric club token in the 06-18 range, also add the 4-digit form `f"20{n:02d}"` (e.g., `"10"` → also adds `"2010"`). The expanded set `{"union", "10", "2010", "fc"}` then correctly catches the polluted year.

1. **Patch `extract_birth_year` to skip club-token numbers and prefer `team_name_original`**
   - Edit `scripts/fix_team_age_groups.py:52-98`. Change the function signature from `extract_birth_year(team_name: str) -> int` to `extract_birth_year(team_name: str, club_name: str | None = None, team_name_original: str | None = None) -> int | None`.
   - When `team_name_original` is provided and non-empty, use it as the parsing source; fall back to `team_name`. This ensures pollution-affected rows are reparsed from the raw provider name.
   - Compute `club_skip_tokens` from `club_name` using the lowercased-token logic from `scripts/dryrun_team_distinction.py:_club_tokens` (split on `[\s\-_./]+`, lowercase, drop the `_CLUB_NOISE` set: `fc`, `sc`, `sa`, `ac`, `cf`, `cd`, `fcs`, `ysa`, `soccer`, `club`, `futbol`, `football`, `youth`, `academy`, `the`, `of`, `and`, `association`).
   - **Expand the set** before the regex skip: for every numeric token `n_str` in the set where `n_str.isdigit()` and `len(n_str) == 2` and `6 <= int(n_str) <= 18`, also add the 4-digit form to the set:
     ```python
     expanded = set(club_skip_tokens)
     for tok in club_skip_tokens:
         if tok.isdigit() and len(tok) == 2 and 6 <= int(tok) <= 18:
             expanded.add(f"20{tok}")
     club_skip_tokens = expanded
     ```
     This makes `Union 10 FC` produce `{"union", "10", "2010", "fc"}` so a polluted `2010` is correctly skipped.
   - In the regex matching loop, after each successful 4-digit match, check `if str(year) in club_skip_tokens: continue` (or skip the match) before validating the 2005–2018 range and returning. Apply this check to all three regex paths (two-year, short-year, single-year). For the two-year and short-year paths, also check both year halves before computing `min(...)` — if both years are in `club_skip_tokens`, fall through; if only one is, use the other.
   - Update the mismatch loop call site (`fix_team_age_groups.py:166`): pass `team["team_name"]`, `team.get("club_name")`, and `team.get("team_name_original")` into the helper. Add `club_name` and `team_name_original` to the `select(...)` projection (`fix_team_age_groups.py:134`).
   - Self-test: add an `if __name__ == "__main__":` block to `fix_team_age_groups.py` with these cases:
     - `extract_birth_year("Union 10 FC 2008", "Union 10 FC", None)` → `2008` (raw, "10" skipped via 2-digit token)
     - `extract_birth_year("Union 2010 FC 2008", "Union 10 FC", "Union 10 FC 2008 Boys")` → `2008` (uses original)
     - `extract_birth_year("Union 2010 FC 2008", "Union 10 FC", None)` → `2008` (no original, but expanded set has `"2010"`)
     - `extract_birth_year("Phoenix FC 2014", "Phoenix FC", None)` → `2014` (no club number leakage)
     - `extract_birth_year("Phoenix FC 2010 Black", "Phoenix FC", None)` → `2010` (no club number leakage; 2010 is real birth year here)

2. **Patch `parse_age_gender` (forward-only fix to prevent future pollution from Step 1)**
   - Edit `scripts/team_name_normalizer.py:98-217`. Add `club_skip_tokens: set[str] | None = None` kwarg (default `None` preserves existing call-sites).
   - Inside the function, guard the bare-2-digit branch at `team_name_normalizer.py:196-203` (`Pattern: ## alone`): when `club_skip_tokens` is provided and `token` is in it, return `(None, None)` instead of converting to a birth year.
   - Do NOT touch the other 7 branches (`U-##`, `BU##`, `##U`, `##B/G/M/F`, `B/G/M/F##`, `####B/G/M/F`, `B/G/M/F####`, `####`). Only the bare-2-digit form is what swallows `Union 10 FC`-style numbers.
   - Add `season_year_max: int | None = None` kwarg. **Default behavior**: when `season_year_max` is `None`, derive it at runtime from `from src.utils.team_utils import CURRENT_YEAR` and use `season_year_max = CURRENT_YEAR - 7` (so the cutoff tracks the season; in 2025-26 → 2018, dropping 2020+ as season labels but preserving u7 = 2019-born). In the `Pattern: ####` branch (`team_name_normalizer.py:189-192`) and 4-digit-with-gender branches, when the resulting year exceeds `season_year_max + 1`, return `(None, None)`. This filters season labels like `Spring 2025`, `2020 (founding year)`, etc.
   - **Drift note**: per memory `architecture_age_pattern_drift.md`, AGE_PATTERN-equivalent regex variants exist in 4 files (`src/utils/team_name_utils.py`, `scripts/find_fuzzy_duplicate_teams.py`, `src/models/game_matcher.py`, `scripts/find_queue_matches.py`). This initiative patches only `team_name_normalizer.py` and `fix_team_age_groups.py` — the others retain their current behavior. Track as a follow-up if drift causes new misclassifications post-launch.

3. **Wire club-token computation into `normalize_team_name`**
   - Edit `scripts/team_name_normalizer.py:122-213`. Build `club_skip_tokens` once before the per-token loop using the lowercased-token logic from `scripts/dryrun_team_distinction.py:_club_tokens`. The set used here only needs the literal 2-digit form (no 4-digit expansion) because `parse_age_gender`'s `\d{2}` bare branch is what we're protecting against — it sees `"10"` as the input token, not `"2010"`. Do NOT add the expansion in this path.
   - Pass `club_skip_tokens=...` to every `parse_age_gender(...)` call inside the loop. Do NOT pass `season_year_max` — let it default to the runtime-derived value.
   - Verify: `normalize_team_name("Union 10 FC 2008 Boys", "Union 10 FC")` returns `"Union 10 FC 2008"` (not `"Union 2010 FC 2008"`).

4. **Extend self-tests in both `team_name_normalizer.py` and `fix_team_age_groups.py`**
   - Edit `scripts/team_name_normalizer.py:472-569`. Add a new test section "CLUB-TOKEN SKIP" with at least 6 cases covering `Union 10 FC` (2008→u19, 2009→u17, 2010→u16, 2011→u15, 2012→u14), plus a season-year case (`Phoenix FC Spring 2025` → `2025` not parsed as birth year, but `Phoenix FC 2019` → `2019` IS parsed since 2019 is u7).
   - Match the `✅`/`❌` print + exit-non-zero-on-failure convention already present.
   - Add an analogous `if __name__ == "__main__":` test block to `scripts/fix_team_age_groups.py` (no test block exists today) with the three `extract_birth_year` cases enumerated in Step 1.

5. **Pre-sweep verification + targeted age-group sweep over 316 candidates**
   - **Pre-sweep verification (run before the live sweep — exercises the patched code path, not just data):** Sample 50 random IDs from `logs/age_misclass_candidates.csv` and for each:
     - Query `team_name`, `team_name_original`, `club_name`, `age_group` from the DB.
     - Call the patched `extract_birth_year(team_name, club_name, team_name_original)` and capture the returned year.
     - Compute `expected_age = calculate_age_group(returned_year)` (with the U18→U19 remap from the existing helper).
     - For each of the 50 rows, classify the outcome:
       - **(a) Patch correctly produces a year that resolves to a different age_group than stored** — the candidate is now correctly identified as misclassified. Count toward "patch will fix this row" bucket.
       - **(b) Patch returns None** — the polluted name had no extractable birth year, or `team_name_original` is also unhelpful. Count toward "patch will not fix this row" bucket.
       - **(c) Patch returns the SAME age as stored** — the candidate was a dry-run false positive (e.g., season-year match like `LC Select 2019` where 2019 is not a birth year); the stored age_group is actually correct. Count toward "false positive" bucket.
     - Halt thresholds:
       - If "patch will fix" bucket < 30 of 50 (60% expected fix rate), halt: patch effectiveness is below projection — re-examine the regex skip logic before live write.
       - If "false positive" bucket > 15 of 50 (30%), halt: the dry-run produced too much noise — re-tune `dryrun_investigate_c_and_d.py:infer_birth_years` before treating the CSV as authoritative.
       - If "patch returns None" bucket > 15 of 50 (30%), halt: many rows can't be parsed by the patched helper at all — the live sweep would silently leave them misclassified.
   - Edit `scripts/fix_team_age_groups.py` to accept a new `--ids-from-csv <path>` flag. When set, parse the CSV (header includes `id`), restrict the team list to those IDs after the existing `paginated_fetch`. Match the `--dry-run` and DB-connection patterns already in the file.
   - Run dry: `python scripts/fix_team_age_groups.py --ids-from-csv logs/age_misclass_candidates.csv --dry-run`.
   - Run live after Steps 1-4 land and all halt thresholds pass: same command without `--dry-run`. Expected: ~270+ of 316 teams move to correct cohort (residual ~50 or fewer are genuinely ambiguous cases).

### Workstream C — League backfill gap (u13+)

6. **Add Pre-NPL and Pre-NL exclusions to `detect_league_from_name`**
   - Edit `scripts/backfill_team_leagues.py:91-103`. The existing cluster already handles `Pre-ECNL` (line 94: `\bPre[\s\-]*ECNL\b`), `Pre-MLS-NEXT` (line 96: `\bPre[\s\-]*MLS\b` matches Pre-MLS, Pre-MLS-NEXT, Pre-MLSNext), and `Pre-Academy` (line 98). Do NOT re-add those — they are already present.
   - Add only the missing two:
     ```python
     if re.search(r"\bPre[\s\-]*NPL\b", team_name, re.IGNORECASE):
         return None
     if re.search(r"\bPre[\s\-]*NL\b(?!\w)", team_name, re.IGNORECASE):
         return None
     ```
   - Negative lookahead on `Pre-NL` prevents matching inside longer tokens like `Pre-NLSA`.
   - Do NOT add a new enum value; Pre-* tiers stay `league = NULL` per spec.

7. **Broaden `LEAGUE_PATTERNS` for missed cases — dry-run is a starting point, not authoritative**
   - **Critical asymmetry to understand before editing**: production has intentional negative-lookahead exclusions the dry-run lacks. `backfill_team_leagues.py:67` has `\bGA\b(?!\s*(?:Green|Gray|Grey|United|SC|FC\b))` — excludes club initialisms like "GA United"/"GA SC"/"GA FC". `backfill_team_leagues.py:72` has `\bNL\b(?!\s*(?:Premier|Next))` — excludes "NL Premier"/"NL Next". The dry-run at `dryrun_investigate_c_and_d.py:LEAGUE_MARKERS` uses bare `\bGA\b` and `\bNL\b(?!\w)` and will flag legitimate non-league clubs as "missing GA/NL". Following the dry-run literally would have you add patterns that corrupt the league column on those clubs.
   - **Workflow**: enumerate the diff between dry-run matches in `logs/missing_league_candidates.csv` and what production already catches. For each pattern variant the dry-run flags that production does NOT, manually classify:
     - **(a) Real production miss** (e.g., a new ECNL_RL phrasing the production regex doesn't cover) → add to `LEAGUE_PATTERNS` in priority-correct order (most-specific first: ECNL_RL before ECNL, MLS_NEXT_AD/HD before generic).
     - **(b) Dry-run false positive** (e.g., "GA United" matched by bare `\bGA\b` but production correctly excludes via the lookahead) → do NOT add. Preserve the existing GA/NL negative-lookahead exclusions.
     - **(c) Pre-* tier** (`Pre-NPL`, `Pre-NL`, etc.) → already handled by Step 6's early-return cluster.
   - **Validation criterion** (revised): "every CSV row matched by dry-run AND not excluded by production's existing GA/NL/Pre-* negative lookaheads should now match production's `detect_league_from_name`." Do NOT use the unconditional dry-run-vs-production parity criterion — that would corrupt legitimate club data.
   - Edit `scripts/backfill_team_leagues.py:47-82` only for category (a) findings.

8. **Add `--age-groups` filter to `backfill_team_leagues.py` and re-run over u13+**
   - **The flag does not currently exist** — `backfill_team_leagues.py:125-128` only accepts `--dry-run`. Add it:
     ```python
     parser.add_argument(
         "--age-groups",
         type=str,
         default=None,
         help="Comma-separated age groups to filter (e.g., u13,u14,u15,u16,u17,u18,u19). "
              "Default: all age groups.",
     )
     ```
   - Thread the filter through fetch. The `paginated_fetch` helper at `backfill_team_leagues.py:106-122` already accepts a `filters: dict` param but only does `eq` filtering, not `in_`. Two options:
     - **(a) Preferred**: post-filter in memory after the existing `paginated_fetch("teams", ...)` call at line 134. Add `team["age_group"]` to the select projection and skip teams whose `age_group` is not in the parsed `--age-groups` set. Minimal change; no helper refactor.
     - (b) If memory pressure is a concern: extend `paginated_fetch` to accept an `in_filters: dict[str, list]` param and apply `q.in_(col, vals)` inside the loop. More invasive; defer unless (a) hits limits.
   - Choose option (a). Update the `select` projection to include `age_group`, parse `args.age_groups.split(",")` into a `set`, and skip non-matching rows in the classification loop at line 150.
   - Dry-run first: `python scripts/backfill_team_leagues.py --age-groups u13,u14,u15,u16,u17,u18,u19 --dry-run`. Expected output: ~1,200–1,300 teams flagged for update (after Pre-* exclusion).
   - Then live run. Confirm via re-running `scripts/dryrun_investigate_c_and_d.py` that the `(d) MISSING LEAGUE` count drops from 1,510 → < 200 (Pre-* false-positive remainder only).

### Workstream A — Distinction column

9. **Create the migration**
   - Write `supabase/migrations/<YYYYMMDDHHMMSS>_add_teams_distinction.sql` matching the shape of `supabase/migrations/20260402000000_add_league_column.sql`.
   - Body:
     ```sql
     ALTER TABLE teams ADD COLUMN IF NOT EXISTS distinction text NULL;
     COMMENT ON COLUMN teams.distinction IS
       'Composite squad distinguisher within (club, age, league, gender). '
       'Lowercase tokens joined with "|", ordered by category priority. '
       'NULL when team_name has no distinguisher (single squad in cohort).';
     CREATE INDEX IF NOT EXISTS idx_teams_distinction
       ON teams (club_name, age_group, league, gender, distinction);
     ```
   - **Apply manually** via Supabase Dashboard SQL editor or CLI from a network-connected env. Per `gotcha_supabase_migrations_and_db_access.md`, this Windows env cannot push migrations directly.

10. **Add `resolve_distinction` helper**
    - Edit `src/utils/team_name_utils.py`. Add `resolve_distinction(name: str, club_name: Optional[str] = None) -> Optional[str]` immediately after `extract_distinctions` (around line 818).
    - Signature, priority, and filter logic must match `scripts/dryrun_team_distinction.py:resolve_distinction` exactly. Specifically:
      - Compose ordered, deduped, lowercase tokens from: `coach_name`, `team_number`, sorted `colors`, sorted `directions`, sorted `squad_words` minus club-tokens, `programs` filtered to the allowlist (`_PROGRAM_DISTINCTIONS` set: `premier`, `select`, `elite`, `classic`, `competitive`, `comp`, `recreational`, `development`, `showcase`, `challenge`, `division`, `reserve`, `copa`, `tal`, `stxcl`, `fdl`, `sccl`), then length-2/3 alpha-token recovery filtered against `LOCATION_CODES`, `US_STATES`, `NOISE_WORDS`, `TEAM_COLORS`, `DIRECTION_CANONICAL`, `PROGRAM_WORDS`, `_LEAGUE_DISTINCTION_BLOCKLIST`, club-tokens, `{the,and,for}`.
      - Return `"|".join(...)` or `None` when empty.
    - Define `_CLUB_NOISE`, `_LEAGUE_DISTINCTION_BLOCKLIST`, `_PROGRAM_DISTINCTIONS` as module-level frozensets in the same file. Mirror the values in `scripts/dryrun_team_distinction.py`. **Note**: the dry-run prototype names this set `_LEAGUE_EQUIVS`, but it includes `scdsl` (not in the canonical league enum) and `pre-ecnl` (out of scope per spec). The production constant is renamed `_LEAGUE_DISTINCTION_BLOCKLIST` to make its purpose explicit (filter out league-adjacent words from the squad-word distinction extraction; not a source of truth for the league enum).
    - Add `_club_tokens(club_name) -> set` private helper next to `resolve_distinction` (matching the dry-run script's helper).
    - Extend the inline `__main__` self-test block (`src/utils/team_name_utils.py:1014-1095`) with at least 8 `resolve_distinction` cases drawn from the validated dry-run samples (`Almaden FC Mercury 2013 Gold` → `gold|mercury`, `LFA Red Star Tango 2013` → `red|star|tango`, `Cleveland Force 2016 Yellow East` → `east|yellow`, `Cheshire SA → Cheshire 2009 DPL` → `None`, `2014 Man City` → `man|city`, `CHALLENGE UNITED ECNL RL 2009` (with `club_name="Challenge SC"`) → `united`, `LC Select 2019` → `select`, `Hoosier FC 2008 Elite Wolves II` → `ii|wolves|elite`).

11. **Build `scripts/backfill_team_distinction.py`**
    - Mirror `scripts/backfill_team_leagues.py` end-to-end: same env loading (`load_dotenv("...env.local")` then `.env`), same `SUPABASE_SERVICE_ROLE_KEY or SUPABASE_KEY` lookup, same `paginated_fetch` (or import that helper), same `--dry-run` flag, same Rich summary `Table`, same retry-with-`create_client` refresh every 2000 rows, same batch-of-50 update pattern.
    - **Add CLI flags** that do NOT exist on the parent template: `--state`, `--age-group`, `--gender`, `--limit`. Wiring rules:
      - `--state` and `--age-group`: fast-path into the SELECT via `.eq("state_code", ...)` / `.eq("age_group", ...)` chained on the existing `paginated_fetch` query (Supabase REST supports `.eq()` chaining without refactoring the helper). Avoids fetching ~150K rows when the caller only wants ~5K.
      - `--gender`: same fast-path via `.eq("gender", ...)`.
      - `--limit`: **input cap semantics** — cap the post-fetch row count *before* classification. Document this in `--help` text: "Process at most N teams from the filtered set; useful for smoke runs." Do NOT use output-cap semantics (process until N writes succeed); that complicates retry logic and isn't needed.
      - When ANY filter is active (`--state`, `--age-group`, `--gender`, `--limit`), the script MUST print `⚠️ Filtered run — coverage threshold not applicable` to stderr at start. The 85% threshold below applies ONLY to unfiltered weekly runs.
    - **Per-row source preference**: include `team_name_original` in the `select(...)` projection. Per row, compute `parsing_source = team_name_original or team_name` and call `resolve_distinction(parsing_source, club_name)`. This mirrors Workstream B Step 1's source-preference rule — distinction backfill should read the raw provider name when available so polluted rows produce the same distinction as their unpolluted counterparts. Skip rows where the resulting value equals the current `distinction` (idempotent re-runs).
    - **Pin the print format for the Step 12 grep contract** — `backfill_team_leagues.py:200` prints `✓ Updated 1,234 / 5,678` (no colon, comma thousands), which does NOT match the workflow grep `(Would update|Updated): \K\d+`. The new script MUST emit **EXACTLY ONE** matching summary line at end of run, verbatim:
      ```python
      if args.dry_run:
          summary_line = f"Would update: {len(updates)}"
      else:
          summary_line = f"Updated: {written}"
      print(summary_line)
      ```
    - **Single-emission enforcement (script-side, not workflow-side)**: add a self-test to the script's `if __name__ == "__main__":` block that runs the script with `--dry-run --limit 5` as a subprocess (`subprocess.run([sys.executable, __file__, "--dry-run", "--limit", "5"], capture_output=True, text=True)`), then asserts `len(re.findall(r'(Would update|Updated):\s*\d+', result.stdout)) == 1`. The test fails CI if a future editor adds a stray progress print matching the pattern. This is the single enforcement mechanism — no docstring banners, no workflow-side `tail -1` workaround. Step 12's grep stays as-is and assumes the script honors the contract.
    - Progress prints, sample transformations, and Rich-console output must use other phrasings (e.g., `Wrote N`, `Progress: N/M`, `Resolved N distinctions`). Document this constraint in the script's module docstring as a load-bearing invariant.
    - Dry-run output: print `(state, league, age_group, gender, club_name, team_count, distinction_resolved, distinction_null)` summary table; sample 15 random transformations using non-matching phrasing.
    - Verification: target ≥85% non-null coverage post-backfill (dry-run measured 89.5%) — **applies only to unfiltered runs**.

12. **Add Step 1b to `data-hygiene-weekly.yml`**
    - Edit `.github/workflows/data-hygiene-weekly.yml`. Add a new step between current Step 1 and Step 2.
    - **Preserve from current file**: every other step (1, 2, 3, 4), the `env:` block (`SUPABASE_URL`, `SUPABASE_KEY` aliases, `DATABASE_URL`, `PYTHONUNBUFFERED`), the `on: schedule + workflow_dispatch` trigger, the `jobs.data-hygiene-pipeline` shell + setup steps (checkout, setup-python, pip install, verify-secrets, mkdir logs), the artifact upload step, and the entire pipeline-summary step. Do not rewrite any of these.
    - New step shape (matching the verbatim template at `data-hygiene-weekly.yml:99-115`):
      ```yaml
      - name: 'Step 1b: Backfill Team Distinction'
        id: step1b
        if: ${{ !contains(format(',{0},', github.event.inputs.skip_steps || ''), ',1b,') }}
        run: |
          DRY_RUN_FLAG=""
          if [ "${{ github.event.inputs.dry_run }}" == "true" ]; then DRY_RUN_FLAG="--dry-run"; fi
          python scripts/backfill_team_distinction.py $DRY_RUN_FLAG 2>&1 | tee logs/step1b_distinction.log
          UPDATED=$(grep -oP '(Would update|Updated): \K\d+' logs/step1b_distinction.log | tail -1 || echo "0")
          echo "distinction_updated=$UPDATED" >> $GITHUB_OUTPUT
      ```
    - **Note the `| tail -1`** — defense-in-depth against `grep -oP` returning multiple matches if the new script accidentally prints `Updated: N` more than once (Step 11's single-emission invariant should prevent this, but `tail -1` makes the workflow robust to invariant violations). The grep contract still depends on Step 11 emitting at least one `Updated: N` / `Would update: N` line verbatim.
    - Add a new row to the summary markdown-table at `data-hygiene-weekly.yml:215-242` (the `Pipeline Summary` step). The summary is a shell `echo "..." >> $GITHUB_STEP_SUMMARY` cascade — NOT a declarative YAML primitive. Insert a new `echo` line between the existing `echo "| 1 | Normalize Team Names | ..."` (line 227) and `echo "| 2 | Fix Age Year | ..."` (line 228):
      ```bash
      echo "| 1b | Backfill Distinction | ${{ steps.step1b.outputs.distinction_updated || 'skipped' }} updated |" >> $GITHUB_STEP_SUMMARY
      ```
      Note that `0 updated` (legitimate idempotent run) and `skipped` (step gated off via `skip_steps=1b`) render differently — verify-by-log when distinguishing.
    - Update the pipeline-order header comment block at `data-hygiene-weekly.yml:34-50` to list "1b. backfill_team_distinction.py — populate distinction column" between Step 1 and Step 2, and update the "Why this order" line to note that distinction reads age_group (Step 2 retrofits stale ages but distinction is post-Step-1 because age_group changes are rare).

13. **Wire `distinction` into `_create_new_<provider>_team()` for all 5 matchers**
    - The 5 matchers are NOT symmetric on their team-name input. Use the per-file mapping below — do not assume `clean_team_name` exists in every file:

      | File | Variable origin line | `team_data` dict line range | Variable to pass to `resolve_distinction` | Why |
      |---|---|---|---|---|
      | `src/models/playmetrics_matcher.py` | n/a (no `clean_team_name`) | 484-495 | `team_name` (raw arg) | No `clean_team_name` exists; the dict inserts raw `team_name`. PlayMetrics relies on upstream cleaning. |
      | `src/models/sincsports_matcher.py` | 716 (`clean_team_name = team_name; if club_name and team_name.lower().startswith(...)`) | 724-734 | `clean_team_name` | Built at 716-722 by stripping the club-name prefix. Use it. |
      | `src/models/tgs_matcher.py` | 644 (`clean_team_name = team_name; if club_name and team_name.startswith(...)`) | 654-663 | `clean_team_name` | Same club-prefix-strip pattern as SincSports. Use it. |
      | `src/models/affinity_wa_matcher.py` | 373 (`clean_team_name = team_name; if club_name and team_name.startswith(...)`) | 381-390 | `clean_team_name` | Same club-prefix-strip pattern. Use it. |
      | `src/models/modular11_matcher.py` | 1339 (`clean_team_name = self._build_team_name_with_division(team_name, division)`) | 1342-1351 | `team_name` (raw arg) — NOT `clean_team_name` | `_build_team_name_with_division` (defined at `modular11_matcher.py:1115-1131`) returns `f"{clean_team_name} {division_normalized}"` for HD/AD divisions — appends a space-separated `HD` or `AD` token. The division belongs in `league`, not `distinction`. Pass the pre-suffix raw `team_name`. |

    - "Variable origin line" cites where the per-file input variable is constructed; "`team_data` dict line range" cites the exact insert payload where the new `"distinction": dist,` key must be added. Verify both line numbers fresh before editing — line drift is possible.
    - In each `_create_new_<provider>_team()`, immediately before the `team_data = { ... }` dict assignment, compute `dist = resolve_distinction(<input_per_table>, club_name)`. Import `resolve_distinction` from `src.utils.team_name_utils` at the top of each matcher file.
    - Add `"distinction": dist,` to the `team_data` dict.
    - Do NOT modify the duplicate-detection `select(...).single()` pre-check or the `23505` exception fallback. Distinction is purely additive on the insert payload.
    - Do NOT touch `src/etl/enhanced_pipeline.py:208-267` or `src/models/game_matcher.py`. The orchestration layer stays unchanged; provider knowledge stays in matchers. (The spec's Files table lists both — the plan deliberately supersedes that. See "Spec divergence" note in Proposed Alignment.)

## Verification

### Workstream B
- Run inline self-tests: `python scripts/team_name_normalizer.py` exits 0 with the new CLUB-TOKEN SKIP cases passing. `python scripts/fix_team_age_groups.py --self-test` (or equivalent — implementer may invoke the new `__main__` test block however it's added) exits 0 with the three `extract_birth_year` cases passing.
- After live sweep over the 316 CSV rows, re-run `python scripts/dryrun_investigate_c_and_d.py`. The `(c) AGE-GROUP MISCLASSIFICATION` count should drop from 316 → **< 50 residual** (matches spec threshold; residual = ambiguous cases like genuine season-year founding-year overlap).
- Spot-check the 5 `Union 10 FC` teams: each should now have a distinct `age_group` corresponding to its actual birth year (2008→u19, 2009→u17, 2010→u16, 2011→u15, 2012→u14).

### Workstream C
- After `backfill_team_leagues.py` re-runs, re-run `python scripts/dryrun_investigate_c_and_d.py`. The `(d) MISSING LEAGUE` count should drop from 1,510 → < 200 (Pre-* false-positive remainder only).
- Spot-check top-leak clubs from `logs/missing_league_candidates.csv`: `Solar SC` (23 expected → 0), `FC Dallas` (49 → 0), `Pateadores Soccer Club` (10 → 0).
- Verify Pre-* still NULL: `SELECT count(*) FROM teams WHERE team_name ILIKE '%pre%ecnl%' AND league IS NULL` should be ≥ 200 (Pre-ECNL teams are intentionally NULL, not backfilled to ECNL). Also confirm `Pre-NPL` and `Pre-NL` exclusions fire: `SELECT count(*) FROM teams WHERE team_name ILIKE '%pre%npl%' AND league IS NULL` and the equivalent `pre%nl%` query should both return non-zero.

### Workstream A
- Migration applied: `SELECT column_name FROM information_schema.columns WHERE table_name='teams' AND column_name='distinction'` returns one row.
- Index present: `SELECT indexname FROM pg_indexes WHERE tablename='teams' AND indexname='idx_teams_distinction'` returns one row.
- Run inline self-tests: `python -m src.utils.team_name_utils` exits 0 with the 8 new `resolve_distinction` cases passing.
- After backfill: `SELECT count(*) FILTER (WHERE distinction IS NOT NULL)::float / count(*) FROM teams` ≥ 0.85 (dry-run measured 0.895).
- After backfill: re-run `python scripts/dryrun_team_distinction.py`. Live-team collision rate should drop from current ~3.0% to near zero (the dry-run computes from team_name; production reads from the column).
- After hygiene step ships and runs live: inspect `logs/step1b_distinction.log` directly for `Updated: N` (live-write) or `Would update: N` (dry-run) lines. Do NOT rely on the workflow summary cell — `0 updated` (legitimate idempotent re-run) and a never-fired-step `'skipped'` fallback look similar but mean different things. The log line is the single source of truth.
- After matcher write-paths ship: trigger one provider scrape via `python scripts/scrape_*.py --dry-run` (or the equivalent) and confirm the inserted row's `distinction` column is populated for any new team that has a distinguisher. Verify per-matcher input mapping correctness: a Modular11 team like `Foo SC 2014 HD` should yield `distinction` without `hd` in it (division stays in `league` column); a SincSports team where `clean_team_name` strips the club prefix should still emit a non-null `distinction` for clubs like `Almaden FC` whose squad uses a color/word distinguisher.

### Cross-cutting
- Re-run the original distinction dry-run end-to-end: `python scripts/dryrun_team_distinction.py`. Coverage should match or exceed 89.5%; collision count should match or improve on 2,263 keys / 4,647 teams.
- Spot-check 5 cohorts where you know the team list (e.g., AZ u14 ECNL_RL Female): every squad has the correct composite distinction stored.

## Context Files

- `C:/PitchRank/docs/superpowers/specs/2026-05-01-team-name-normalization-design.md` — Source of truth for scope, schema, out-of-scope boundaries, and validation thresholds.
- `C:/PitchRank/scripts/dryrun_team_distinction.py` — Reference implementation of `resolve_distinction` (priority + club-strip + length-2/3 recovery). Production `resolve_distinction` in `team_name_utils.py` must mirror this exactly.
- `C:/PitchRank/scripts/dryrun_investigate_c_and_d.py` — Reference implementation of the age-misclass and missing-league detectors. Workstream B/C verification re-runs this.
- `C:/PitchRank/src/utils/team_name_utils.py` — Hosts `extract_distinctions`, `should_skip_pair`, all the shared frozensets, and the natural home for `resolve_distinction`.
- `C:/PitchRank/scripts/team_name_normalizer.py` — Workstream B parser patch site (`parse_age_gender`, `normalize_team_name`).
- `C:/PitchRank/scripts/backfill_team_leagues.py` — Workstream C edit site + Workstream A backfill template.
- `C:/PitchRank/.github/workflows/data-hygiene-weekly.yml` — Workstream A new-step site; preserve all other steps and infrastructure verbatim.
- `C:/PitchRank/src/models/playmetrics_matcher.py`, `sincsports_matcher.py`, `tgs_matcher.py`, `modular11_matcher.py`, `affinity_wa_matcher.py` — Workstream A inline edits in each `_create_new_<provider>_team()`.
- `C:/PitchRank/supabase/migrations/20260402000000_add_league_column.sql` — Migration template to mirror for the new `distinction` column.
- `C:/PitchRank/scripts/normalize_team_names.py` — Existing Step-1 hygiene script that runs immediately before the new Step 1b.
