# Distinction Cleanup — Phase 0 Characterization Harness — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce a committed before-picture of team-name `distinction` quality and a frozen merge-gate baseline, changing no production logic, so Phase 1 scope can be chosen from real numbers.

**Architecture:** Two read-only diagnostic scripts, modernized in place. (A) `dryrun_team_distinction.py` runs the *canonical* `resolve_distinction` over all teams and reports coverage, identity-key collisions, and problem-bucket counts. (B) `validate_normalizer.py` replays every historical merge through the *production* dedup gate (`_team_distinction.should_skip_pair`) and reports how often it would now block a real merge. New logic lives in small pure helpers that are unit-tested; DB/printing glue is verified by running.

**Tech Stack:** Python 3.11, Supabase Python client, pytest. No DB writes. No frontend changes.

**Spec:** `docs/superpowers/specs/2026-05-28-team-name-distinction-cleanup-design.md`

**Branch:** `feat/distinction-cleanup` (already created).

---

## File Structure

- **Modify** `scripts/dryrun_team_distinction.py` — drop the drifted local `resolve_distinction`; import the canonical one; add a pure `classify_distinction_problems()` helper; add a "PROBLEM BUCKETS" report section.
- **Modify** `scripts/validate_normalizer.py` — fix env loading; move client creation into `main()`; replace the old `team_name_normalizer` logic with a pure `replay_merge_verdict()` helper built on `_team_distinction.should_skip_pair`; report false-skip rate.
- **Create** `tests/unit/test_distinction_phase0.py` — unit tests for both pure helpers.
- **Create** `docs/superpowers/reports/2026-05-28-distinction-quality.txt` and `docs/superpowers/reports/2026-05-28-merge-verdict-baseline.txt` — captured run output (committed).

---

## Task 1: Pure helper — `classify_distinction_problems`

Classifies a resolved distinction string into zero or more problem buckets. Pure function, no DB. Buckets: `unknown`, `league_token`, `club_acronym`, `multi_token`, `single_char`.

**Files:**
- Modify: `scripts/dryrun_team_distinction.py` (add helper near the top, after the existing constant blocks ~line 53)
- Test: `tests/unit/test_distinction_phase0.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_distinction_phase0.py`:

```python
import sys
from pathlib import Path

# scripts/ holds dryrun_team_distinction.py and validate_normalizer.py
_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(_SCRIPTS))

from dryrun_team_distinction import classify_distinction_problems  # noqa: E402


def test_none_distinction_has_no_problems():
    assert classify_distinction_problems(None, "Solar SC") == set()


def test_clean_color_distinction_has_no_problems():
    assert classify_distinction_problems("white", "Solar SC") == set()


def test_unknown_token_flagged():
    assert "unknown" in classify_distinction_problems("unknown", None)


def test_league_token_flagged():
    # "nl" is league-redundant; "mls" too. ad/hd are NOT flagged (Modular11 sacred).
    assert "league_token" in classify_distinction_problems("martinez|north|nl", "DKSC")
    assert "league_token" not in classify_distinction_problems("hd", "LA Bulls")
    assert "league_token" not in classify_distinction_problems("ad", "Breakers FC")


def test_club_acronym_flagged():
    # "cosc" == initials of California Odyssey Soccer Club
    assert "club_acronym" in classify_distinction_problems("cosc", "California Odyssey Soccer Club")
    # a real color is not an acronym
    assert "club_acronym" not in classify_distinction_problems("blue", "San Diego Surf Soccer Club")


def test_multi_token_flagged():
    assert "multi_token" in classify_distinction_problems("blue|alcaraz", "San Diego Surf")
    assert "multi_token" not in classify_distinction_problems("blue", "San Diego Surf")


def test_single_char_flagged():
    assert "single_char" in classify_distinction_problems("a", "Some Club")
    assert "single_char" not in classify_distinction_problems("white", "Some Club")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /c/PitchRank && python -m pytest tests/unit/test_distinction_phase0.py -q`
Expected: FAIL with `ImportError: cannot import name 'classify_distinction_problems'`

- [ ] **Step 3: Add the helper**

In `scripts/dryrun_team_distinction.py`, after the `_PROGRAM_DISTINCTIONS` block (~line 52), add:

```python
# League-equivalent tokens that are redundant with the `league` column.
# Deliberately EXCLUDES "ad"/"hd" — those are load-bearing for Modular11
# (MLS NEXT) display and must never be flagged. See the cleanup design spec.
_LEAGUE_TOKENS = {
    "ecnl", "ecnl-rl", "ecrl", "rl", "ga", "npl", "dpl", "dplo",
    "scdsl", "nal", "mlsnext", "mls-next", "next", "ea", "ea2",
    "pre-ecnl", "mls", "nl",
}


def _club_acronym(club_name):
    """First-letter acronym of a club name's significant tokens (>=3 words).

    'California Odyssey Soccer Club' -> 'cosc'. Returns '' when the club has
    fewer than 3 significant tokens (acronyms shorter than that are too
    collision-prone to flag).
    """
    toks = _club_tokens(club_name)  # already lowercased, noise-stripped
    # Preserve original order from the club string for a stable acronym.
    if not club_name:
        return ""
    import re as _re
    ordered = [
        t.strip("()[]'*.,")
        for t in _re.split(r"[\s\-_./]+", club_name.lower())
        if t.strip("()[]'*.,") in toks
    ]
    if len(ordered) < 3:
        return ""
    return "".join(t[0] for t in ordered)


def classify_distinction_problems(distinction, club_name):
    """Return the set of problem buckets a resolved distinction falls into.

    Buckets: 'unknown', 'league_token', 'club_acronym', 'multi_token',
    'single_char'. Empty set means the distinction looks clean. Pure function.
    """
    problems = set()
    if not distinction:
        return problems
    tokens = [t for t in distinction.split("|") if t]
    if len(tokens) >= 2:
        problems.add("multi_token")
    acronym = _club_acronym(club_name)
    for t in tokens:
        tl = t.lower()
        if tl == "unknown":
            problems.add("unknown")
        if tl in _LEAGUE_TOKENS:
            problems.add("league_token")
        if len(tl) == 1:
            problems.add("single_char")
        if acronym and tl == acronym:
            problems.add("club_acronym")
    return problems
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /c/PitchRank && python -m pytest tests/unit/test_distinction_phase0.py -q`
Expected: PASS (7 passed)

- [ ] **Step 5: Commit**

```bash
cd /c/PitchRank
git add scripts/dryrun_team_distinction.py tests/unit/test_distinction_phase0.py
git commit -m "feat(distinction): add classify_distinction_problems diagnostic helper"
```

---

## Task 2: Point the dry-run at the canonical resolver + emit problem buckets

Remove the drifted local `resolve_distinction` so the report reflects production logic, and add a PROBLEM BUCKETS section to the report.

**Files:**
- Modify: `scripts/dryrun_team_distinction.py` (import swap ~line 32; delete local `resolve_distinction` ~lines 74-170; extend `main()` ~line 247 onward)

- [ ] **Step 1: Swap to the canonical resolver**

Change the import block (~line 32) from:

```python
from src.utils.team_name_utils import extract_distinctions  # noqa: E402
```

to:

```python
from src.utils.team_name_utils import extract_distinctions, resolve_distinction  # noqa: E402
```

Then **delete** the entire local `def resolve_distinction(...)` (the block spanning from `def resolve_distinction(name: str, club_name: Optional[str] = None)` through its `return "|".join(out)` ~lines 74-170). Leave `_CLUB_NOISE`, `_LEAGUE_EQUIVS`, `_PROGRAM_DISTINCTIONS`, and `_club_tokens` in place (still used).

- [ ] **Step 2: Pass state_code to the canonical resolver**

In `main()`, change the per-team resolve call (~line 213) from:

```python
        dist = resolve_distinction(name, club)
```

to:

```python
        dist = resolve_distinction(name, club, t.get("state_code"))
```

- [ ] **Step 3: Accumulate problem buckets during the team loop**

In `main()`, immediately after `t["_distinction"] = dist` (~line 247), add:

```python
        for bucket in classify_distinction_problems(dist, club):
            problem_buckets[bucket] += 1
            if len(problem_samples[bucket]) < 10 and not t.get("is_deprecated"):
                problem_samples[bucket].append((club, name, dist))
```

And initialize the accumulators just before the `for t in teams:` loop (~line 209), alongside the existing counters:

```python
    problem_buckets = collections.Counter()
    problem_samples = collections.defaultdict(list)
```

- [ ] **Step 4: Print the PROBLEM BUCKETS section**

In `main()`, after the existing "RESOLVED SAMPLES" block (~line 297), add:

```python
    print("\n=== PROBLEM BUCKETS (resolved distinctions only) ===")
    print(f"  {'bucket':16} {'count':>8}  {'% of resolved':>14}")
    for bucket, n in problem_buckets.most_common():
        pct = (100 * n / resolved) if resolved else 0.0
        print(f"  {bucket:16} {n:>8,}  {pct:>13.1f}%")
    for bucket, _ in problem_buckets.most_common():
        print(f"\n--- sample: {bucket} ---")
        for club, name, dist in problem_samples[bucket][:10]:
            print(f"  club={club!r:30.30} name={name!r:45.45} dist={dist!r}")
```

- [ ] **Step 5: Smoke-run the script (read-only)**

Run: `cd /c/PitchRank && SUPABASE_KEY=$(grep -m1 '^SUPABASE_SERVICE_ROLE_KEY=' .env.local | cut -d= -f2-) python scripts/dryrun_team_distinction.py | tail -40`
Expected: prints COVERAGE, SOURCE WINNER, UNIQUENESS CHECK, and the new PROBLEM BUCKETS section with non-zero counts; no errors; no DB writes.

> Note: the script reads `SUPABASE_SERVICE_ROLE_KEY`/`SUPABASE_SERVICE_KEY`. If `.env.local` only defines the service-role key, the inline `SUPABASE_KEY=...` shim above is harmless; the script already prefers the service keys.

- [ ] **Step 6: Commit**

```bash
cd /c/PitchRank
git add scripts/dryrun_team_distinction.py
git commit -m "feat(distinction): dry-run uses canonical resolver + problem-bucket report"
```

---

## Task 3: Pure helper — `replay_merge_verdict`

Maps a historical merge (deprecated + canonical team rows) to the production gate's verdict. Pure function, no DB.

**Files:**
- Modify: `scripts/validate_normalizer.py` (add helper + imports)
- Test: `tests/unit/test_distinction_phase0.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_distinction_phase0.py`:

```python
from validate_normalizer import replay_merge_verdict  # noqa: E402


def test_replay_no_data_when_missing_team():
    assert replay_merge_verdict(None, {"team_name": "x", "club_name": "x"}) == "no_data"
    assert replay_merge_verdict({"team_name": "x", "club_name": "x"}, None) == "no_data"


def test_replay_no_data_when_missing_name():
    dep = {"team_name": "", "club_name": "Phoenix FC"}
    can = {"team_name": "Phoenix FC 2012 Red", "club_name": "Phoenix FC"}
    assert replay_merge_verdict(dep, can) == "no_data"


def test_replay_allowed_for_identical_names():
    dep = {"team_name": "Phoenix FC 2012 Red", "club_name": "Phoenix FC"}
    can = {"team_name": "Phoenix FC 2012 Red", "club_name": "Phoenix FC"}
    assert replay_merge_verdict(dep, can) == "allowed"


def test_replay_false_skip_for_different_squads():
    # The gate (correctly) skips different-color squads; replaying a *merge*
    # of them is therefore a 'false_skip' from the replay's point of view —
    # this verifies the True -> 'false_skip' mapping.
    dep = {"team_name": "Phoenix FC 2012 Red", "club_name": "Phoenix FC"}
    can = {"team_name": "Phoenix FC 2012 Blue", "club_name": "Phoenix FC"}
    assert replay_merge_verdict(dep, can) == "false_skip"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /c/PitchRank && python -m pytest tests/unit/test_distinction_phase0.py -q`
Expected: FAIL with `ImportError: cannot import name 'replay_merge_verdict'`

- [ ] **Step 3: Add the helper (and the gate import) to `validate_normalizer.py`**

Replace the stale import line `from team_name_normalizer import parse_team_name, teams_match` with:

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # scripts/ for _team_distinction
from _team_distinction import should_skip_pair  # production masters-dedup gate
```

Then add the helper at module level (after the imports):

```python
def replay_merge_verdict(dep, can):
    """Replay one historical merge through the production dedup gate.

    dep/can are team rows (dicts) with 'team_name' and 'club_name', or None.
    Returns:
      'no_data'    — a row is missing or has a blank team_name
      'allowed'    — gate would NOT skip the pair (a real merge stays reachable)
      'false_skip' — gate WOULD skip the pair (it would block this real merge)

    Uses require_age_token_match=True to mirror find_fuzzy_duplicate_teams.py
    (the path that produces masters merges).
    """
    if not dep or not can:
        return "no_data"
    dep_name = (dep.get("team_name") or "").strip()
    can_name = (can.get("team_name") or "").strip()
    if not dep_name or not can_name:
        return "no_data"
    club = (can.get("club_name") or dep.get("club_name") or "")
    skipped = should_skip_pair(dep_name, can_name, club_name=club, require_age_token_match=True)
    return "false_skip" if skipped else "allowed"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /c/PitchRank && python -m pytest tests/unit/test_distinction_phase0.py -q`
Expected: PASS (11 passed)

- [ ] **Step 5: Commit**

```bash
cd /c/PitchRank
git add scripts/validate_normalizer.py tests/unit/test_distinction_phase0.py
git commit -m "feat(distinction): add replay_merge_verdict gate-baseline helper"
```

---

## Task 4: Rewire `validate_normalizer.main()` onto the gate

Fix env loading, make the module import-safe, and rewrite the per-merge loop + summary to use `replay_merge_verdict`.

**Files:**
- Modify: `scripts/validate_normalizer.py` (env block ~lines 16-17; `main()` loop ~lines 95-179)

- [ ] **Step 1: Fix env loading + remove module-level client**

Replace lines 16-17:

```python
load_dotenv("/Users/pitchrankio-dev/Projects/PitchRank/.env")
supabase = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))
```

with:

```python
load_dotenv("C:/PitchRank/.env.local")
load_dotenv("C:/PitchRank/.env")
```

Then, at the top of `main()` (before `print("Fetching merge history...")`), add:

```python
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_SERVICE_KEY") or os.getenv("SUPABASE_KEY")
    if not (url and key):
        print("Missing Supabase creds (need SUPABASE_URL + a service key)")
        return
    supabase = create_client(url, key)
```

- [ ] **Step 2: Rewrite the per-merge loop**

Replace the loop body and result tracking (~lines 84-135) so it uses the helper. The new `main()` body from `# Track results` to the end of the loop becomes:

```python
    verdicts = Counter()
    false_skips = []

    print("\nReplaying merges through the production dedup gate...")
    for i, merge in enumerate(all_merges):
        if i % 500 == 0:
            print(f"  Processing {i}/{len(all_merges)}...")
        dep = teams_cache.get(merge["deprecated_team_id"])
        can = teams_cache.get(merge["canonical_team_id"])
        verdict = replay_merge_verdict(dep, can)
        verdicts[verdict] += 1
        if verdict == "false_skip" and len(false_skips) < 40:
            false_skips.append((dep, can))
```

- [ ] **Step 3: Rewrite the summary**

Replace the summary section (~lines 137-179) with:

```python
    total = len(all_merges)
    allowed = verdicts["allowed"]
    false_skip = verdicts["false_skip"]
    no_data = verdicts["no_data"]

    print("\n" + "=" * 60)
    print("MERGE-VERDICT BASELINE (production gate: should_skip_pair)")
    print("=" * 60)
    print(f"\nHistorical merges replayed: {total:,}")
    evaluable = total - no_data
    print(f"  ✅ allowed (gate keeps merge reachable): {allowed:,}"
          f"  ({100*allowed/evaluable:.2f}% of evaluable)" if evaluable else "  (no evaluable rows)")
    print(f"  ❌ false_skip (gate would BLOCK this merge): {false_skip:,}"
          f"  ({100*false_skip/evaluable:.2f}% of evaluable)" if evaluable else "")
    print(f"  ⚠️  no_data (missing team rows): {no_data:,}")

    print("\n" + "-" * 60)
    print(f"SAMPLE FALSE-SKIPS (first {len(false_skips)})")
    print("-" * 60)
    for dep, can in false_skips:
        print(f"\n  deprecated: {dep.get('team_name')!r}  (club={dep.get('club_name')!r})")
        print(f"  canonical : {can.get('team_name')!r}  (club={can.get('club_name')!r})")
```

- [ ] **Step 4: Run the unit tests again (regression guard)**

Run: `cd /c/PitchRank && python -m pytest tests/unit/test_distinction_phase0.py -q`
Expected: PASS (11 passed) — confirms the rewire didn't break the importable helper.

- [ ] **Step 5: Smoke-run the script (read-only)**

Run: `cd /c/PitchRank && python scripts/validate_normalizer.py | tail -50`
Expected: prints "MERGE-VERDICT BASELINE", a false_skip count + percent, and sample false-skips; no errors; no DB writes.

- [ ] **Step 6: Commit**

```bash
cd /c/PitchRank
git add scripts/validate_normalizer.py
git commit -m "feat(distinction): rewire validate_normalizer onto production dedup gate"
```

---

## Task 5: Capture and commit the Phase 0 reports

**Files:**
- Create: `docs/superpowers/reports/2026-05-28-distinction-quality.txt`
- Create: `docs/superpowers/reports/2026-05-28-merge-verdict-baseline.txt`

- [ ] **Step 1: Capture both reports to files**

```bash
cd /c/PitchRank
mkdir -p docs/superpowers/reports
python scripts/dryrun_team_distinction.py > docs/superpowers/reports/2026-05-28-distinction-quality.txt 2>&1
python scripts/validate_normalizer.py   > docs/superpowers/reports/2026-05-28-merge-verdict-baseline.txt 2>&1
```

- [ ] **Step 2: Sanity-check the captured files**

Run: `cd /c/PitchRank && tail -25 docs/superpowers/reports/2026-05-28-distinction-quality.txt && echo "=====" && tail -20 docs/superpowers/reports/2026-05-28-merge-verdict-baseline.txt`
Expected: distinction report ends with PROBLEM BUCKETS counts; baseline report ends with false-skip rate + samples.

- [ ] **Step 3: Commit the reports**

```bash
cd /c/PitchRank
git add docs/superpowers/reports/2026-05-28-distinction-quality.txt docs/superpowers/reports/2026-05-28-merge-verdict-baseline.txt
git commit -m "docs(distinction): capture Phase 0 characterization reports"
```

- [ ] **Step 4: Hand back for review**

Stop here. Present the two reports' headline numbers (coverage, collision rate, problem-bucket counts, false-skip rate) and ask the user to decide Phase 1 scope: composer-only (`resolve_distinction`) vs. root parser (`extract_distinctions`).

---

## Self-Review

**Spec coverage:** Phase 0 deliverables in the spec — (A) distinction quality report via modernized `dryrun_team_distinction.py` ✅ Tasks 1-2; (B) merge-verdict baseline via rewired `validate_normalizer.py` ✅ Tasks 3-4; committed report ✅ Task 5; "no logic changes / no DB writes / no display changes" ✅ (both scripts read-only; production `resolve_distinction`/`extract_distinctions`/`should_skip_pair` untouched). Modular11 carve-out honored (`ad`/`hd` excluded from `_LEAGUE_TOKENS`) ✅.

**Placeholder scan:** No TBD/TODO; every code step shows complete code; run commands have expected output. ✅

**Type/name consistency:** `classify_distinction_problems(distinction, club_name)`, `_club_acronym(club_name)`, `_LEAGUE_TOKENS`, `replay_merge_verdict(dep, can)` used identically across tasks and tests. `should_skip_pair(..., require_age_token_match=True)` matches the signature in `scripts/_team_distinction.py`. `resolve_distinction(name, club, state_code)` matches `src/utils/team_name_utils.py`. ✅
