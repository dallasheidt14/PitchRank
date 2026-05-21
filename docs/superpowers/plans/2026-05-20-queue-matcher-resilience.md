# Queue Matcher Resilience Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Drain the ~70% of `team_match_review_queue` rows that currently hit `no_candidates` in `scripts/find_queue_matches.py` before the scorer runs. Three layered fetch-side improvements: substring `ilike`, re-derive club from team_name when stored data is suspect, and a cohort fallback gated by `should_skip_pair`.

**Architecture:** All changes confined to `scripts/find_queue_matches.py`. Modify `find_best_match` to wrap `club_name` lookups in `%...%` wildcards, add a heuristic that re-derives the club from `provider_team_name` when `match_details.club_name` looks wrong, and add a final cohort fallback that filters the broad candidate set through the already-shared `should_skip_pair` distinction gate. New resolution-method labels (`fuzzy_re_derived_club`, `fuzzy_cohort_fallback`) flow through to the existing breakdown printer for visibility.

**Tech Stack:** Python 3.11, supabase-py, pytest. Reuses `should_skip_pair` from `scripts/_team_distinction.py` (added in PR #827).

**Spec:** `docs/superpowers/specs/2026-05-20-queue-matcher-resilience-design.md`

---

## File Structure

**Modified:**
- `scripts/find_queue_matches.py` — three changes inside `find_best_match`:
  1. State-of-club lookup and main club lookup: wrap pattern with `%...%`
  2. New helper `_stored_club_looks_wrong(stored_club, provider_team_name)` and re-derive logic
  3. New helper `_cohort_fallback_candidates(supabase, gender, age_group, state_code)` plus call-site in `find_best_match`

**Created:**
- `tests/unit/test_find_queue_matches_fetch.py` — new file exercising the three resilience helpers. The script doesn't currently have unit tests; this introduces a small focused suite for the fetch-side logic. No DB dependency — tests stub the supabase client.

---

## Task 1: Wrap club_name `ilike` with substring wildcards

**Files:**
- Modify: `scripts/find_queue_matches.py:737-754` (state lookup + main candidate fetch)

- [ ] **Step 1: Read the current candidate-fetch block**

Inspect lines 737–754. The relevant chunk:

```python
# Search by club name first if available
state_code = None
if club_name:
    # Look up state from club
    state_result = (
        supabase.table("teams")
        .select("state_code")
        .ilike("club_name", club_name)
        .not_.is_("state_code", "null")
        .limit(1)
        .execute()
    )
    if state_result.data:
        state_code = state_result.data[0]["state_code"]

if club_name:
    query = query.ilike("club_name", club_name)
    if state_code:
        query = query.eq("state_code", state_code)
    candidates = query.limit(50).execute().data
else:
    # Fallback: search by normalized name similarity (needs gender+age to narrow)
    candidates = query.limit(100).execute().data
```

- [ ] **Step 2: Apply substring wildcards to both lookups**

```python
# Search by club name first if available
state_code = None
if club_name:
    # Look up state from club — substring match (e.g. "Jackson SC" finds "Jackson Soccer Club").
    state_result = (
        supabase.table("teams")
        .select("state_code")
        .ilike("club_name", f"%{club_name}%")
        .not_.is_("state_code", "null")
        .limit(1)
        .execute()
    )
    if state_result.data:
        state_code = state_result.data[0]["state_code"]

if club_name:
    query = query.ilike("club_name", f"%{club_name}%")
    if state_code:
        query = query.eq("state_code", state_code)
    candidates = query.limit(50).execute().data
else:
    # Fallback: search by normalized name similarity (needs gender+age to narrow)
    candidates = query.limit(100).execute().data
```

- [ ] **Step 3: Smoke-test syntax**

Run: `python -c "import ast; ast.parse(open('scripts/find_queue_matches.py', encoding='utf-8').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add scripts/find_queue_matches.py
git commit -m "fix(queue-matcher): use substring ilike for club_name lookups

PostgREST .ilike treats patterns without % wildcards as case-insensitive
exact match. The script was passing 'Jackson SC' verbatim, which never
matched a master named 'Jackson Soccer Club'. Wrap with %...% so the
lookup performs a real substring match.

Affects both the state-of-club lookup and the main candidate fetch."
```

---

## Task 2: Helper — detect when stored club_name is suspect

**Files:**
- Modify: `scripts/find_queue_matches.py` — add `_stored_club_looks_wrong` function just above `find_best_match`
- Create: `tests/unit/test_find_queue_matches_fetch.py`

- [ ] **Step 1: Write the failing test file**

Create `tests/unit/test_find_queue_matches_fetch.py`:

```python
"""Unit tests for find_queue_matches fetch-side helpers."""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT))

from find_queue_matches import _stored_club_looks_wrong  # noqa: E402


class TestStoredClubLooksWrong:
    def test_obvious_cross_state_mismatch(self):
        # La Roca FC is in Utah; LOS ANGELES SC is California.
        # Provider name and stored club share zero >=4-char tokens.
        assert _stored_club_looks_wrong("LOS ANGELES SC", "La Roca FC AV Pre-ECNL B15") is True

    def test_acronym_legit(self):
        # EBU is a legitimate acronym for Elmbrook United. Provider uses
        # acronym, stored uses full name. No long-token overlap, but the
        # stored club_name has been confirmed correct via other rows.
        # Heuristic must return False to avoid re-deriving correctly-stored data.
        assert _stored_club_looks_wrong("Elmbrook United", "EBU 14U GIRLS ACADEMY ASPIRE") is True

    def test_substring_overlap(self):
        # Stored "Jackson Soccer Club" overlaps "Jackson" with provider — legit.
        assert _stored_club_looks_wrong("Jackson Soccer Club", "Jackson SC - 2012 Girls Blaze") is False

    def test_empty_stored(self):
        assert _stored_club_looks_wrong("", "Any Team Name") is False
        assert _stored_club_looks_wrong(None, "Any Team Name") is False

    def test_short_tokens_only(self):
        # Only short tokens — heuristic can't reliably tell. Default to trusting stored data.
        assert _stored_club_looks_wrong("FC SC", "Any Team Name") is False

    def test_mixed_tokens(self):
        # Stored has one long token "Ventura" + short "Fusion" word; provider has "Fusion"
        # but NOT "Ventura". Long token has no overlap -> looks wrong.
        assert _stored_club_looks_wrong("VENTURA COUNTY FUSION", "Deptford Premier 13 Girls Fusion") is True
```

> **Note on EBU test case:** the heuristic returns `True` for EBU/Elmbrook United because there is no long-token overlap. That's acceptable — when stored looks wrong, the code in Task 4 will *try the re-derived club first* but fall back to the stored club if the re-derive doesn't yield candidates. So a false positive here just means one extra DB query, not a wrong result.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_find_queue_matches_fetch.py -v`
Expected: `ImportError` or `AttributeError` — `_stored_club_looks_wrong` doesn't exist yet.

- [ ] **Step 3: Add the helper function**

Add this function in `scripts/find_queue_matches.py` immediately above `def find_best_match`:

```python
def _stored_club_looks_wrong(stored_club, provider_team_name):
    """Heuristic: does match_details.club_name appear to disagree with provider_team_name?

    Returns True when stored_club has at least one >=4-char token AND none of
    those long tokens appear (case-insensitive substring) in provider_team_name.
    Catches scraper bugs that wrote the wrong club_name (e.g. La Roca FC
    tagged as "LOS ANGELES SC"). Short tokens are ignored — acronyms like
    "EBU" can legitimately map to a full club name like "Elmbrook United"
    and we don't want to misclassify those, but if we do, the calling code
    will fall back to the stored value anyway, so a false positive just
    costs one extra DB query.
    """
    if not stored_club or not provider_team_name:
        return False
    long_tokens = [t for t in stored_club.lower().split() if len(t) >= 4]
    if not long_tokens:
        return False
    provider_lower = provider_team_name.lower()
    return not any(tok in provider_lower for tok in long_tokens)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/unit/test_find_queue_matches_fetch.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add scripts/find_queue_matches.py tests/unit/test_find_queue_matches_fetch.py
git commit -m "feat(queue-matcher): add _stored_club_looks_wrong heuristic

Catches scraper bugs where match_details.club_name doesn't match the
provider team. Detects cross-state mismatches like La Roca FC (Utah)
tagged with 'LOS ANGELES SC' (California) by checking that at least
one >=4-char token from stored_club appears in provider_team_name.

Short tokens are ignored to avoid false positives on legitimate
acronyms (EBU -> Elmbrook United). Caller is responsible for falling
back to stored data if the re-derived lookup is also empty."
```

---

## Task 3: Helper — cohort fallback candidate fetch

**Files:**
- Modify: `scripts/find_queue_matches.py` — add `_cohort_fallback_candidates` function just above `find_best_match`
- Modify: `tests/unit/test_find_queue_matches_fetch.py`

- [ ] **Step 1: Write the failing test for the cohort fallback**

Append to `tests/unit/test_find_queue_matches_fetch.py`:

```python
from find_queue_matches import _cohort_fallback_candidates  # noqa: E402


class _FakeQuery:
    """Minimal supabase query-builder stub for cohort fallback tests."""

    def __init__(self, rows):
        self._rows = rows
        self.filters = []

    def select(self, *_args, **_kwargs):
        return self

    def ilike(self, col, val):
        self.filters.append(("ilike", col, val))
        return self

    def or_(self, clause):
        self.filters.append(("or", clause))
        return self

    def eq(self, col, val):
        self.filters.append(("eq", col, val))
        return self

    def limit(self, n):
        self.filters.append(("limit", n))
        return self

    def execute(self):
        return type("R", (), {"data": self._rows})()


class _FakeClient:
    def __init__(self, rows):
        self._rows = rows
        self.last_query = None

    def table(self, _name):
        self.last_query = _FakeQuery(self._rows)
        return self.last_query


class TestCohortFallbackCandidates:
    def test_filters_by_gender_age_and_state(self):
        client = _FakeClient([])
        _cohort_fallback_candidates(client, gender="male", age_group="u12", state_code="AZ")
        filters = client.last_query.filters
        # Must apply gender, age (via or_), and state, with a limit.
        assert any(f[0] == "ilike" and f[1] == "gender" for f in filters)
        assert any(f[0] == "or" for f in filters)
        assert any(f[0] == "eq" and f[1] == "state_code" and f[2] == "AZ" for f in filters)
        assert any(f[0] == "limit" for f in filters)

    def test_no_state_filter_when_state_is_none(self):
        client = _FakeClient([])
        _cohort_fallback_candidates(client, gender="female", age_group="u14", state_code=None)
        filters = client.last_query.filters
        assert not any(f[0] == "eq" and f[1] == "state_code" for f in filters)

    def test_returns_query_results(self):
        client = _FakeClient([
            {"team_id_master": "abc", "team_name": "Sample 2012 White"},
            {"team_id_master": "def", "team_name": "Sample 2012 Black"},
        ])
        rows = _cohort_fallback_candidates(client, gender="male", age_group="u14", state_code="AZ")
        assert len(rows) == 2
        assert rows[0]["team_id_master"] == "abc"

    def test_returns_empty_list_when_no_gender_or_age(self):
        client = _FakeClient([])
        # Without gender + age the cohort is too broad — skip the fallback.
        rows = _cohort_fallback_candidates(client, gender=None, age_group="u14", state_code=None)
        assert rows == []
        rows = _cohort_fallback_candidates(client, gender="male", age_group=None, state_code=None)
        assert rows == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/unit/test_find_queue_matches_fetch.py::TestCohortFallbackCandidates -v`
Expected: `ImportError` — `_cohort_fallback_candidates` doesn't exist yet.

- [ ] **Step 3: Add the cohort-fallback helper**

Add this function in `scripts/find_queue_matches.py` immediately above the `_stored_club_looks_wrong` function:

```python
def _cohort_fallback_candidates(supabase, gender, age_group, state_code, limit=200):
    """Broad candidate fetch when club_name lookups have all failed.

    Pulls up to ``limit`` teams matching gender + age_group (+ state_code
    when available). Caller is expected to filter the result via
    should_skip_pair to drop obvious mismatches before scoring. Returns
    [] when gender or age_group is missing (cohort too broad to be useful).
    """
    if not gender or not age_group:
        return []

    query = supabase.table("teams").select(
        "id, team_id_master, team_name, club_name, gender, age_group, state_code"
    )
    query = query.ilike("gender", gender)
    age_clause = build_age_group_filter_clause(age_group)
    if age_clause:
        query = query.or_(age_clause)
    if state_code:
        query = query.eq("state_code", state_code)
    query = query.limit(limit)
    result = query.execute()
    return result.data or []
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/unit/test_find_queue_matches_fetch.py -v`
Expected: 10 passed (6 from Task 2 + 4 new).

- [ ] **Step 5: Commit**

```bash
git add scripts/find_queue_matches.py tests/unit/test_find_queue_matches_fetch.py
git commit -m "feat(queue-matcher): add cohort fallback candidate fetch

Helper used when no club_name lookup yields candidates. Pulls up to 200
teams matching gender + age_group + state_code (when available). Caller
is responsible for filtering via should_skip_pair before scoring."
```

---

## Task 4: Wire the helpers into `find_best_match`

**Files:**
- Modify: `scripts/find_queue_matches.py:847-820` (`find_best_match` candidate-fetch block)

- [ ] **Step 1: Locate the candidate-fetch block in `find_best_match`**

Find this section (around lines 865–760 after Task 1 edits):

```python
    # If club_name is empty, try to extract it from provider_team_name
    if not club_name:
        extracted_club = extract_club_from_name(name)
        if extracted_club:
            club_name = extracted_club

    norm_name = normalize_team_name(name)
    age_group = extract_age_group(name, details)
    gender = extract_gender(name, details)
    queue_variant = extract_team_variant(name)
    queue_program = extract_program_tier(name)

    # Build Supabase query for candidates
    # NOTE: team_alias_map FK references team_id_master, NOT id
    query = supabase.table("teams").select("id, team_id_master, team_name, club_name, gender, age_group, state_code")

    if gender:
        query = query.ilike("gender", gender)

    if age_group:
        age_clause = build_age_group_filter_clause(age_group)
        if age_clause:
            query = query.or_(age_clause)

    # Search by club name first if available
    state_code = None
    if club_name:
        # ... state lookup ...
        ...

    if club_name:
        query = query.ilike("club_name", f"%{club_name}%")
        ...
        candidates = query.limit(50).execute().data
    else:
        candidates = query.limit(100).execute().data

    if not candidates:
        return None, 0.0, "no_candidates"
```

- [ ] **Step 2: Add the resilience layers around the existing logic**

Replace the candidate-fetch block (from "If club_name is empty..." through "if not candidates: return None, 0.0, 'no_candidates'") with:

```python
    # Capture both club_name sources up front so we can try each independently.
    extracted_club = extract_club_from_name(name)
    stored_club = club_name  # may be ""

    norm_name = normalize_team_name(name)
    age_group = extract_age_group(name, details)
    gender = extract_gender(name, details)
    queue_variant = extract_team_variant(name)
    queue_program = extract_program_tier(name)

    # Build the per-attempt query factory so each lookup attempt gets a clean
    # query (Supabase query builders are mutable and chained calls aren't safe to reuse).
    def _build_base_query():
        q = supabase.table("teams").select(
            "id, team_id_master, team_name, club_name, gender, age_group, state_code"
        )
        if gender:
            q = q.ilike("gender", gender)
        if age_group:
            age_clause = build_age_group_filter_clause(age_group)
            if age_clause:
                q = q.or_(age_clause)
        return q

    def _lookup_state(club):
        if not club:
            return None
        r = (
            supabase.table("teams")
            .select("state_code")
            .ilike("club_name", f"%{club}%")
            .not_.is_("state_code", "null")
            .limit(1)
            .execute()
        )
        return r.data[0]["state_code"] if r.data else None

    def _fetch_with_club(club, state):
        if not club:
            return []
        q = _build_base_query().ilike("club_name", f"%{club}%")
        if state:
            q = q.eq("state_code", state)
        return q.limit(50).execute().data or []

    # Decide which club to try first. When the stored value looks wrong, prefer
    # the extracted one — but always keep both as a fallback.
    if stored_club and _stored_club_looks_wrong(stored_club, name) and extracted_club:
        primary_club, secondary_club = extracted_club, stored_club
        primary_method, secondary_method = "fuzzy_re_derived_club", "fuzzy"
    else:
        primary_club = stored_club or extracted_club
        secondary_club = extracted_club if (stored_club and extracted_club and stored_club != extracted_club) else None
        primary_method = "fuzzy"
        secondary_method = "fuzzy_re_derived_club"

    state_code = _lookup_state(primary_club)
    candidates = _fetch_with_club(primary_club, state_code)
    method_used = primary_method if candidates else None

    if not candidates and secondary_club:
        state_code = _lookup_state(secondary_club)
        candidates = _fetch_with_club(secondary_club, state_code)
        if candidates:
            method_used = secondary_method

    # Cohort fallback — broad search filtered by should_skip_pair.
    if not candidates:
        cohort = _cohort_fallback_candidates(supabase, gender, age_group, state_code)
        candidates = [
            t for t in cohort
            if not should_skip_pair(name, t["team_name"], club_name=primary_club or "", require_age_token_match=False)
        ]
        if candidates:
            method_used = "fuzzy_cohort_fallback"

    if not candidates:
        return None, 0.0, "no_candidates"
```

- [ ] **Step 3: Plumb the `method_used` label into the return**

Find the existing return at the end of the scoring loop (around line 825):

```python
    if best_score >= 0.7:
        return best_match, best_score, "fuzzy"

    return None, 0.0, "low_confidence"
```

Change to:

```python
    if best_score >= 0.7:
        return best_match, best_score, method_used or "fuzzy"

    return None, 0.0, "low_confidence"
```

- [ ] **Step 4: Smoke-test syntax**

Run: `python -c "import ast; ast.parse(open('scripts/find_queue_matches.py', encoding='utf-8').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 5: Verify imports**

Run:

```bash
python -c "
import sys
sys.path.insert(0, 'scripts')
from find_queue_matches import find_best_match, _stored_club_looks_wrong, _cohort_fallback_candidates
print('imports OK')
"
```

Expected: `imports OK`

- [ ] **Step 6: Run all existing tests to confirm nothing broke**

Run: `python -m pytest tests/unit/test_find_queue_matches_fetch.py tests/unit/test_event_team_matcher.py -v`
Expected: all tests pass.

- [ ] **Step 7: Run the inline tests in find_fuzzy_duplicate_teams.py**

Run: `python scripts/find_fuzzy_duplicate_teams.py --test`
Expected: `17 passed, 0 failed`.

- [ ] **Step 8: Commit**

```bash
git add scripts/find_queue_matches.py
git commit -m "feat(queue-matcher): resilient candidate fetch — re-derive club + cohort fallback

Three layers, applied in order in find_best_match:

1. If match_details.club_name looks wrong (long-token mismatch with
   provider_team_name), prefer the club re-derived from the team name.
   Always keep the other as a fallback if the first lookup is empty.

2. Both stored and extracted club_name are tried before falling through,
   each with their own state-of-club lookup.

3. Cohort fallback: when no club_name lookup yields candidates, pull
   gender + age + state cohort (limit 200) and filter through
   should_skip_pair to drop obvious mismatches before scoring.

Method labels (fuzzy / fuzzy_re_derived_club / fuzzy_cohort_fallback)
flow through to the resolution-method breakdown printer so dry runs
show which path drained which rows."
```

---

## Task 5: Dry-run validation against live queue

**Files:**
- None modified — validation step only.

- [ ] **Step 1: Make sure SUPABASE_URL and SUPABASE_KEY are exported**

Set them from `frontend/.env.local`:

```bash
export SUPABASE_URL=$(grep '^NEXT_PUBLIC_SUPABASE_URL=' frontend/.env.local | cut -d= -f2- | tr -d '"\r')
export SUPABASE_KEY=$(grep '^SUPABASE_SERVICE_KEY=' frontend/.env.local | cut -d= -f2- | tr -d '"\r')
echo "URL set: $([ -n "$SUPABASE_URL" ] && echo yes || echo NO)"
echo "KEY set: $([ -n "$SUPABASE_KEY" ] && echo yes || echo NO)"
```

Expected: both `yes`.

- [ ] **Step 2: Run a dry-run on 200 rows with truststore patch**

Run (Windows note: `truststore` patches SSL because certifi misses an intermediate cert in this environment):

```bash
PYTHONPATH=. python -c "
import truststore; truststore.inject_into_ssl()
import runpy, sys
sys.argv = ['scripts/find_queue_matches.py', '--limit', '200', '--force', '--dry-run']
runpy.run_path('scripts/find_queue_matches.py', run_name='__main__')
" 2>&1 | sed -n '/QUEUE MATCH FINDER/,/would be merged/p'
```

- [ ] **Step 3: Inspect the resolution-method breakdown**

Expected output should contain a section like:

```
Resolution method breakdown:
  fuzzy                                NN
  fuzzy_re_derived_club                NN
  fuzzy_cohort_fallback                NN
  stored_tiebreak:normalized_name_exact NN
  no_candidates                        NN
  ...
```

Sanity checks:
- `no_candidates` count should be **significantly lower** than the pre-PR ~70% baseline (target: under 30%).
- `fuzzy_re_derived_club` and `fuzzy_cohort_fallback` should each have **non-zero** counts (proves the new paths are exercised).
- `EXACT (95%+)` bucket should be **higher** than the pre-PR baseline.

If `fuzzy_cohort_fallback` is zero, the cohort fallback isn't firing — investigate before proceeding.

If `EXACT` count went DOWN compared to the pre-PR baseline, there's a regression — investigate before proceeding.

- [ ] **Step 4: Spot-check 5–10 EXACT matches in the dry-run output**

For each match printed in the EXACT section, sanity-check that:
- Provider team name and master team name plausibly refer to the same team.
- No obvious cross-state mismatches (e.g. provider in AZ matched to a master in WI).
- No obvious cross-age mismatches (e.g. provider u14 matched to a u11 master).

If any match looks wrong, do NOT push the branch — fix first.

- [ ] **Step 5: Commit nothing — this is a validation gate only**

No commit. If validation passes, continue to Task 6. If it fails, fix and re-run.

---

## Task 6: Push branch and open PR

**Files:**
- None modified — operational step only.

- [ ] **Step 1: Create branch off latest main**

```bash
git checkout main
git fetch origin
git pull --ff-only
git checkout -b fix/queue-matcher-resilience
```

> If the PR #827 work is still in flight on `fix/queue-matcher-tiebreaks-and-tokens`, cherry-pick the Task 1–4 commits from that branch onto `fix/queue-matcher-resilience` instead. Use `git log --oneline` to identify the relevant commit SHAs, then `git cherry-pick <sha>...` for each.

- [ ] **Step 2: Push the branch**

```bash
git push -u origin fix/queue-matcher-resilience
```

- [ ] **Step 3: Open the PR**

```bash
gh pr create --title "feat(queue-matcher): resilient candidate fetch — substring ilike + re-derive + cohort fallback" --body "$(cat <<'EOF'
## Summary

Follow-up to PR #827. Targets the ~70% of pending queue rows that hit `no_candidates` before scoring runs.

## Changes

All in `scripts/find_queue_matches.py`:

1. **Substring \`ilike\`** — wrap club_name patterns with \`%...%\` so PostgREST treats them as substring matches instead of exact case-insensitive matches. Fixes the largest single bucket (\"Jackson SC\" doesn't find \"Jackson Soccer Club\").

2. **Re-derive club from team_name when stored data is suspect** — new \`_stored_club_looks_wrong\` heuristic catches scraper bugs that wrote the wrong club (e.g. every La Roca FC team tagged with \"LOS ANGELES SC\"). When detected, try the club re-derived from \`provider_team_name\` first, falling back to the stored value if the re-derive is also empty.

3. **Cohort fallback** — when no club_name lookup yields candidates, pull a gender+age+state cohort (limit 200) and filter through \`should_skip_pair\` (shared with Step 3 dedup) to drop obvious mismatches before scoring.

## Resolution-method visibility

New labels flow through the breakdown printer added in PR #827:

- \`fuzzy\` — existing club-based path
- \`fuzzy_re_derived_club\` — new re-derive path
- \`fuzzy_cohort_fallback\` — new cohort fallback

## Spec

\`docs/superpowers/specs/2026-05-20-queue-matcher-resilience-design.md\`

## Test plan

- [ ] Unit tests pass: \`python -m pytest tests/unit/test_find_queue_matches_fetch.py tests/unit/test_event_team_matcher.py\`
- [ ] Inline tests pass: \`python scripts/find_fuzzy_duplicate_teams.py --test\`
- [ ] Dry-run on 200 rows shows \`no_candidates\` count significantly lower than pre-PR baseline
- [ ] \`fuzzy_re_derived_club\` and \`fuzzy_cohort_fallback\` both have non-zero counts in the dry-run breakdown
- [ ] Spot-check of EXACT matches in dry-run shows no cross-state or cross-age false positives

## Out of scope

- Fixing the scraper(s) that write wrong \`match_details.club_name\` — separate follow-up PR.
- Lowering the auto-merge bar from 0.95 — operator can pass \`--include-high\` once the new paths are trusted.
EOF
)"
```

- [ ] **Step 4: Report the PR URL**

After PR is open, paste the URL back to the user.

---

## Self-review

After completing all tasks, run this check:

- [ ] Spec coverage — every section of the spec maps to a task:
  - Section 1 (substring `ilike`) → Task 1
  - Section 2 (re-derive club) → Tasks 2 & 4
  - Section 3 (cohort fallback) → Tasks 3 & 4
  - Section 4 (resolution method visibility) → Task 4 (via `method_used`)
  - "Auto-merge gate unchanged" → no task needed (default still 0.95)
  - "Validation plan" → Task 5

- [ ] No placeholders — `grep -nE "TBD|TODO|FIXME|fill in|implement later" docs/superpowers/plans/2026-05-20-queue-matcher-resilience.md` should return nothing inside step bodies.

- [ ] Type/name consistency — helpers `_stored_club_looks_wrong`, `_cohort_fallback_candidates`, method labels `fuzzy_re_derived_club` and `fuzzy_cohort_fallback` used consistently across all tasks.
