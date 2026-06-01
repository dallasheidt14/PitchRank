# Distinction Cleanup — Phase 1 (Display / Source Cleanup) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Clean the stored `teams.distinction` value so displayed team names read well — by dropping a club's own initials, stray single letters, and redundant league tokens from the composite — without touching the merge/dedup gate.

**Architecture:** The only logic change is in `resolve_distinction()` (`src/utils/team_name_utils.py`), the function that assembles the stored distinction string. The merge gate (`should_skip_pair`) recomputes from raw names and does NOT read this value, so these changes cannot affect matching/merging. After the logic change we re-run the Phase 0 quality report as a before/after guard, re-backfill the column, and present a sample for sign-off. Re-enabling `composeTeamDisplay` on rankings/search is a SEPARATE follow-up after the user eyeballs cleaned data.

**Tech Stack:** Python 3.11, pytest, Supabase Python client.

**Spec:** `docs/superpowers/specs/2026-05-28-team-name-distinction-cleanup-design.md`
**Phase 0 baseline reports:** `docs/superpowers/reports/2026-05-28-distinction-quality.txt`

**Branch:** `feat/distinction-cleanup` (already created; continue on it).

**Scope guardrails:**
- Modular11 / MLS NEXT stays untouched: `ad`/`hd` are never dropped.
- This plan changes ONLY `resolve_distinction` + its helper + tests + a re-backfill. No frontend changes, no merge-gate (`should_skip_pair`/`extract_distinctions`) changes, no DB schema changes.
- Accepted tradeoff: dropping single-character tokens could in rare cases erase a genuine "Team A/B/C" tag. Task 2's collision check is the safety net — if it collapses real teams, collisions spike and we reconsider.

---

## File Structure

- **Modify** `src/utils/team_name_utils.py` — add `_club_acronym()` helper near `_club_tokens()`; extend `_LEAGUE_DISTINCTION_BLOCKLIST` with `mls`/`nl`; add three drop rules inside `resolve_distinction()`.
- **Create** `tests/unit/test_resolve_distinction_cleanup.py` — unit tests for the three drops + two "must-preserve" cases.
- **No other code files.** Tasks 2–4 run existing scripts (`scripts/dryrun_team_distinction.py`, `scripts/backfill_team_distinction.py`) and produce report artifacts under `docs/superpowers/reports/`.

---

## Task 1: Clean `resolve_distinction` output (TDD)

**Files:**
- Modify: `src/utils/team_name_utils.py`
- Test: `tests/unit/test_resolve_distinction_cleanup.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_resolve_distinction_cleanup.py`:

```python
from src.utils.team_name_utils import resolve_distinction


def test_drops_club_acronym_short():
    # "vsa" = initials of Virginia Soccer Assocation -> not a squad tag
    got = resolve_distinction("VSA 2014 Premier Red", "Virginia Soccer Assocation", "VA")
    assert got == "red|premier"  # vsa dropped; red (color) before premier (program)


def test_drops_club_acronym_long():
    # "cosc" = initials of California Odyssey Soccer Club; ECNL is league, 2013 is age
    got = resolve_distinction("COSC ECNL 2013", "California Odyssey Soccer Club", "CA")
    assert got is None


def test_drops_stray_single_char():
    # "c" left over from "F.C" is not a squad tag
    got = resolve_distinction("MIDWEST GLADIATORS F.C", "MIDWEST GLADIATORS F.C", "TX")
    assert got is None


def test_drops_leftover_league_token():
    got = resolve_distinction("Hoover-Vestavia 2009 MLS NEXT", "Hoover-Vestavia Soccer", "AL")
    assert got is None  # mls + next both dropped as league tokens


def test_preserves_real_squad_tag():
    # color + direction is a legitimate squad distinguisher
    got = resolve_distinction("CCV Stars 2011 East Navy", "Ccv Stars", "AZ")
    assert got == "navy|east"  # 2-word club -> no acronym; nothing stripped


def test_preserves_modular11_ad_hd():
    # HD must survive (Modular11 / MLS NEXT format is sacred)
    got = resolve_distinction("Carolina Core FC U13 HD", "Carolina Core FC Youth", "NC")
    assert got is not None and "hd" in got.split("|")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /c/PitchRank && python -m pytest tests/unit/test_resolve_distinction_cleanup.py -q`
Expected: FAILs — `test_drops_club_acronym_short` returns `red|premier|vsa`, `test_drops_club_acronym_long` returns `cosc`, `test_drops_stray_single_char` returns `c`, `test_drops_leftover_league_token` returns `mls`. (`test_preserves_*` may already pass.)

> If the import line fails (`ModuleNotFoundError: src`), add at the top of the test file:
> `import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))` — but try without it first; the repo's pyproject usually puts the root on the path.

- [ ] **Step 3: Add the `_club_acronym` helper**

In `src/utils/team_name_utils.py`, immediately AFTER the existing `def _club_tokens(club_name)` function, add:

```python
def _club_acronym(club_name: Optional[str]) -> str:
    """First-letter acronym of a club's words (>=3 words), else ''.

    'California Odyssey Soccer Club' -> 'cosc'. Used to drop a club's own
    initials from its distinction — those identify the club, not the squad,
    so they are noise in the composite. Includes noise words (soccer/club) so
    the acronym matches how clubs actually abbreviate themselves. Returns ''
    for <3-word clubs (short acronyms collide too easily to drop safely).
    """
    if not club_name:
        return ""
    words = [
        w.strip("()[]'*.,")
        for w in re.split(r"[\s\-_./]+", club_name.lower())
        if w.strip("()[]'*.,")
    ]
    if len(words) < 3:
        return ""
    return "".join(w[0] for w in words)
```

- [ ] **Step 4: Extend the league-token blocklist**

In `src/utils/team_name_utils.py`, find the `_LEAGUE_DISTINCTION_BLOCKLIST = frozenset({ ... })` definition and add `"mls"` and `"nl"` to the set (these leak through the length-2/3 recovery today). The resulting set must still NOT contain `"ad"` or `"hd"`. Example resulting definition:

```python
_LEAGUE_DISTINCTION_BLOCKLIST = frozenset({
    "ecnl", "ecnl-rl", "ecrl", "rl", "ga", "npl", "dpl", "dplo",
    "scdsl", "nal", "mlsnext", "mls-next", "next", "ea", "ea2",
    "pre-ecnl", "aspire", "mls", "nl",
})
```

(Only `"mls"` and `"nl"` are added; keep every pre-existing member. This set is used ONLY inside `resolve_distinction`, so this does not affect the merge gate.)

- [ ] **Step 5: Add the three drop rules inside `resolve_distinction`**

In `resolve_distinction()`, AFTER the block that computes `club_toks` (and adds state-name tokens to it) and BEFORE the `squad_words = sorted(...)` line, add:

```python
    club_acronym = _club_acronym(club_name)
```

Then change the squad-words loop from:

```python
    squad_words = sorted(d.get("squad_words") or [])
    for sw in squad_words:
        sw_l = sw.lower()
        if sw_l in club_toks:
            continue  # club or state leakage — drop
        parts.append(sw_l)
```

to:

```python
    squad_words = sorted(d.get("squad_words") or [])
    for sw in squad_words:
        sw_l = sw.lower()
        if sw_l in club_toks:
            continue  # club or state leakage — drop
        if len(sw_l) == 1:
            continue  # stray single letter (e.g. "C" from "F.C") — not a squad tag
        if club_acronym and sw_l == club_acronym:
            continue  # club's own initials — identifies the club, not the squad
        parts.append(sw_l)
```

Then, in the length-2/3 recovery loop, add an acronym guard. Change:

```python
        if tok in club_toks:
            continue
```

(inside that recovery `for tok in raw_toks:` loop) to:

```python
        if tok in club_toks:
            continue
        if club_acronym and tok == club_acronym:
            continue  # club's own initials — drop
```

(The `mls`/`nl` league tokens are already handled in this loop because it skips any token in `_LEAGUE_DISTINCTION_BLOCKLIST`, which now includes them.)

- [ ] **Step 6: Run the new tests to verify they pass**

Run: `cd /c/PitchRank && python -m pytest tests/unit/test_resolve_distinction_cleanup.py -q`
Expected: 6 passed.

- [ ] **Step 7: Run the existing distinction tests for regressions**

Run: `cd /c/PitchRank && python -m pytest tests/unit/test_distinction_phase0.py -q && python -m src.utils.team_name_utils`
Expected: `test_distinction_phase0.py` 11 passed; the `team_name_utils` inline `__main__` self-tests print and exit 0 (no `❌`). If any inline `resolve_distinction` case now fails because its expected value included a dropped token (club-acronym/single-char/`mls`/`nl`), update that expected value in the inline `distinction_cases` list to the new correct output and note it in the commit.

- [ ] **Step 8: Commit**

```bash
cd /c/PitchRank
git add src/utils/team_name_utils.py tests/unit/test_resolve_distinction_cleanup.py
git commit -m "feat(distinction): drop club-acronym/single-char/league tokens from resolve_distinction"
```

---

## Task 2: Verify against the Phase 0 quality report (before/after guard)

No code change — this confirms the cleanup did what we expect AND did not collapse real teams. The dry-run script is read-only.

**Files:**
- Create: `docs/superpowers/reports/2026-05-29-distinction-quality-after.txt`

- [ ] **Step 1: Re-run the quality report with the new logic**

Run:
```bash
cd /c/PitchRank && python scripts/dryrun_team_distinction.py > docs/superpowers/reports/2026-05-29-distinction-quality-after.txt 2>&1
```
Expected: completes with no error (truststore handles SSL); file ends with a PROBLEM BUCKETS section.

- [ ] **Step 2: Compare buckets and collisions to the Phase 0 baseline**

Run:
```bash
cd /c/PitchRank && echo "--- BEFORE (Phase 0) ---" && grep -A8 "PROBLEM BUCKETS" docs/superpowers/reports/2026-05-28-distinction-quality.txt | head -8 && grep -E "Collision keys|Collision team count|resolved :" docs/superpowers/reports/2026-05-28-distinction-quality.txt && echo "--- AFTER ---" && grep -A8 "PROBLEM BUCKETS" docs/superpowers/reports/2026-05-29-distinction-quality-after.txt | head -8 && grep -E "Collision keys|Collision team count|resolved :" docs/superpowers/reports/2026-05-29-distinction-quality-after.txt
```
Expected:
- `club_acronym`, `single_char`, and `league_token` buckets drop to ~0 (a few residuals are acceptable).
- `multi_token` count drops (composites shrank as junk tokens were removed).
- **Collision keys / collision team count do NOT increase materially** (a small change is fine; a large jump means single-char/acronym drops collapsed distinguishable teams — STOP and report, do not proceed to backfill).

- [ ] **Step 3: Record the comparison**

Append a short summary to the AFTER report file (so the artifact is self-describing):
```bash
cd /c/PitchRank && { echo ""; echo "=== BEFORE/AFTER vs 2026-05-28 baseline ==="; echo "(buckets club_acronym/single_char/league_token expected ~0; collisions expected ~stable)"; } >> docs/superpowers/reports/2026-05-29-distinction-quality-after.txt
```

- [ ] **Step 4: Commit the after-report**

```bash
cd /c/PitchRank
git add docs/superpowers/reports/2026-05-29-distinction-quality-after.txt
git commit -m "docs(distinction): capture post-cleanup quality report (before/after guard)"
```

> GATE: If Step 2 showed a material collision increase, STOP and report to the controller/user before Task 3. Otherwise proceed.

---

## Task 3: Re-backfill `teams.distinction` with the cleaned logic

`scripts/backfill_team_distinction.py` reads `resolve_distinction` (now updated) and writes only rows whose value changed (idempotent — safe to re-run/resume).

- [ ] **Step 1: Dry-run the backfill and eyeball the change count + samples**

Run:
```bash
cd /c/PitchRank && python scripts/backfill_team_distinction.py --dry-run 2>&1 | tail -40
```
Expected: prints a "Distinction Backfill Summary" table and a single `Would update: <N>` line. `N` should be in the low tens of thousands (≈ the club_acronym + single_char + league_token + affected multi_token teams), NOT ~150K. Sample resolutions should show junk tokens removed (e.g. `'VSA 2014 Premier Red' -> 'red|premier'`).

- [ ] **Step 2: Run the live backfill in the background**

The Supabase REST API can drop connections past ~10K updates; the script retries and refreshes the client every 2000 rows, and is idempotent, so a partial run can simply be re-run to resume.

Run (background, since it writes thousands of rows):
```bash
cd /c/PitchRank && python scripts/backfill_team_distinction.py > docs/superpowers/reports/2026-05-29-backfill.log 2>&1
```
(Use the controller's background-run mechanism; do not foreground a multi-minute write.)
Expected on completion: log ends with `Updated: <N>` matching (approximately) the dry-run count.

- [ ] **Step 3: Confirm the backfill landed**

After it completes, re-run the dry-run; it should now report a near-zero delta (the column already matches the new logic):
```bash
cd /c/PitchRank && python scripts/backfill_team_distinction.py --dry-run 2>&1 | grep -E "Would update"
```
Expected: `Would update: 0` (or a tiny residual). If it still shows the original large N, the live run did not complete — re-run Step 2 to resume.

> No commit here — this step changes database rows, not files. The `.log` is committed in Task 4.

---

## Task 4: Verify in-product + present before/after sample (user checkpoint)

`composeTeamDisplay` is STILL live on Compare, TeamSelector, RecentMovers, and infographics, so the cleaned data is already visible there. This task confirms a clean DB-level sample and hands a before/after to the user.

**Files:**
- Create: `docs/superpowers/reports/2026-05-29-distinction-before-after-sample.txt`

- [ ] **Step 1: Pull a before/after sample straight from the DB**

Use the Supabase MCP `execute_sql` (read-only) on project `pfkrhmprwxtghtpinrot` to sample teams that had junk tokens, showing `club_name`, `team_name`, and the new `distinction`:
```sql
SELECT club_name, team_name, league, distinction
FROM teams
WHERE is_deprecated = FALSE
  AND distinction IS NOT NULL
  AND club_name IS NOT NULL
ORDER BY random()
LIMIT 30;
```
Confirm the new `distinction` values are clean (no club initials, no stray single letters, no `mls`/`nl`), and that any `ad`/`hd` (Modular11) values are intact. Save the 30-row result into the sample report file.

- [ ] **Step 2: Commit the sample + backfill log**

```bash
cd /c/PitchRank
git add docs/superpowers/reports/2026-05-29-distinction-before-after-sample.txt docs/superpowers/reports/2026-05-29-backfill.log
git commit -m "docs(distinction): capture post-backfill sample + backfill log"
```

- [ ] **Step 3: Hand back to the user (checkpoint)**

STOP. Present to the user: the bucket before/after numbers (Task 2), the collision delta (the safety check), and the 30-row sample (Task 1). Ask whether the cleaned tags look right. Re-enabling `composeTeamDisplay` on the rankings table + global search (un-reverting PR #743) is the next increment and requires its own plan + visual smoke test — do NOT make frontend changes in this plan.

---

## Self-Review

**Spec coverage (Phase 1 = display/source cleanup, per the chosen scope):**
- "Clean stored distinction for display by dropping club-acronym / single-char / league tokens" → Task 1 (the three drop rules + blocklist extension). ✅
- "Does not touch the merge gate" → only `resolve_distinction` + its private helper + `_LEAGUE_DISTINCTION_BLOCKLIST` (all used solely by `resolve_distinction`) are changed; `should_skip_pair`/`extract_distinctions` untouched. ✅
- "Re-run the quality report as the before/after guard; collisions must not worsen" → Task 2 (with an explicit STOP gate). ✅
- "Re-backfill the stored values" → Task 3 (idempotent, background, resumable). ✅
- "Show a before/after sample before flipping display on; Modular11 untouched" → Task 4 checkpoint; `ad`/`hd` preserved (tested in Task 1 Step 1 and re-checked in Task 4 Step 1). ✅
- Frontend re-enable explicitly deferred to a follow-up plan. ✅

**Placeholder scan:** No TBD/TODO; every code step shows complete code; run commands have expected output. ✅

**Type/name consistency:** `_club_acronym(club_name)` (returns `str`), `club_acronym` local, `_LEAGUE_DISTINCTION_BLOCKLIST`, `resolve_distinction(name, club_name, state_code)` used consistently across tasks and tests. The three drop rules reference `club_toks`/`club_acronym`/`sw_l`/`tok` exactly as named in the existing function. ✅
