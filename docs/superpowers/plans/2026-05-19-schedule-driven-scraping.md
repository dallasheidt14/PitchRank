# Schedule-Driven Scraping Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist future-dated games as NULL-score rows in the `games` table, then route all GotSport scraping through a single priority-ordered queue (`scrape_requests`) drained by the existing `process_missing_games` workflow at a fixed rate (200 teams every 15 minutes).

**Architecture:** Patch `enhanced_pipeline.py` to allow future-dated NULL-score rows past two filter sites. Add `priority` to `scrape_requests` with a unique-on-pending index. Bump `process_missing_games` to 15-min cadence with priority-ordered draining. Add thin enqueue scripts for daily yesterday-game collection, weekly discovery (teams without future games), and weekly safety-net. Neuter `scrape-games.yml`'s scheduled cron, keep its manual dispatch as a ZenRows bulk-operations tool.

**Tech Stack:** Python 3.11, pytest + asyncio, Supabase (PostgreSQL), GotSportScraper, GitHub Actions

**Reference spec:** `docs/superpowers/specs/2026-05-19-schedule-driven-scraping-design.md`

---

## File Structure

**Modified:**
- `src/etl/enhanced_pipeline.py` — patch two filter sites + add helpers (Phase 1)
- `tests/test_enhanced_pipeline.py` — future-date tests (Phase 1)
- `scripts/process_missing_games.py` — add per-run cap + priority ordering (Phase 3)
- `.github/workflows/process-missing-games.yml` — bump cadence to 15min, add cap input (Phase 3)
- `.github/workflows/scrape-games.yml` — remove `schedule:` block (Phase 7)
- Whichever code path inserts user-clicked "process missing" requests — add `priority=1` (Phase 3)

**Created:**
- `supabase/migrations/<TS>_add_priority_to_scrape_requests.sql` — schema change (Phase 3)
- `scripts/enqueue_yesterday_games.py` — daily enqueue script (Phase 4)
- `tests/unit/test_enqueue_yesterday_games.py` (Phase 4)
- `.github/workflows/enqueue-yesterday-games.yml` (Phase 4)
- `scripts/enqueue_discovery_teams.py` — weekly enqueue script (Phase 5)
- `tests/unit/test_enqueue_discovery_teams.py` (Phase 5)
- `.github/workflows/enqueue-discovery.yml` (Phase 5)
- `scripts/enqueue_safety_net.py` — weekly enqueue script (Phase 6)
- `.github/workflows/enqueue-safety-net.yml` (Phase 6)
- `tests/integration/test_scheduled_to_played_dedup.py` — game_uid symmetry guard (Phase 1)

**Audited (read-only unless audit finds a problem):**
- `src/rankings/calculator.py`, `src/rankings/data_adapter.py` — NULL-score guard
- `rankings_view`, `rankings_full` — view filter check
- `games.result` derivation site

---

## Phase 1: Pipeline Patch

The critical change. Done TDD-style.

### Task 1.1: Add `_is_future_game` helper

**Files:**
- Modify: `src/etl/enhanced_pipeline.py` (add method near line 1039)
- Test: `tests/test_enhanced_pipeline.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_enhanced_pipeline.py`:

```python
from datetime import date, timedelta

class TestFutureDateHelper:
    """Tests for the _is_future_game helper used by the scheduled-game carveout."""

    @pytest.fixture
    def mock_supabase(self):
        supabase = Mock()
        provider_result = Mock()
        provider_result.data = {'id': 'test-provider-uuid'}
        supabase.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = provider_result
        return supabase

    def _make_pipeline(self, mock_supabase):
        return EnhancedETLPipeline(mock_supabase, 'gotsport', dry_run=True)

    def test_future_date_returns_true(self, mock_supabase):
        pipeline = self._make_pipeline(mock_supabase)
        future = (date.today() + timedelta(days=7)).isoformat()
        assert pipeline._is_future_game({"game_date": future}) is True

    def test_today_returns_false(self, mock_supabase):
        pipeline = self._make_pipeline(mock_supabase)
        today = date.today().isoformat()
        assert pipeline._is_future_game({"game_date": today}) is False

    def test_past_date_returns_false(self, mock_supabase):
        pipeline = self._make_pipeline(mock_supabase)
        past = (date.today() - timedelta(days=7)).isoformat()
        assert pipeline._is_future_game({"game_date": past}) is False

    def test_missing_game_date_returns_false(self, mock_supabase):
        pipeline = self._make_pipeline(mock_supabase)
        assert pipeline._is_future_game({}) is False

    def test_unparseable_date_returns_false(self, mock_supabase):
        pipeline = self._make_pipeline(mock_supabase)
        assert pipeline._is_future_game({"game_date": "not-a-date"}) is False
```

- [ ] **Step 2: Run and verify it fails**

```bash
cd C:/PitchRank && python -m pytest tests/test_enhanced_pipeline.py::TestFutureDateHelper -v
```

Expected: FAIL with `AttributeError: 'EnhancedETLPipeline' object has no attribute '_is_future_game'`.

- [ ] **Step 3: Add the helper**

In `src/etl/enhanced_pipeline.py`, immediately after `_is_empty_score` (around line 1039), add:

```python
def _is_future_game(self, game: Dict) -> bool:
    """
    Return True if game_date is strictly in the future (game_date > today).

    Used by the scheduled-game carveout in score-validation filters: future-dated
    rows with NULL scores are *scheduled*, not data quality issues, and must be
    persisted so the daily enqueue can trigger off them.
    """
    game_date_raw = game.get("game_date", "")
    if not game_date_raw:
        return False
    try:
        game_date_obj = parse_game_date(game_date_raw)
    except (ValueError, TypeError):
        return False
    return game_date_obj > date.today()
```

Check the imports at the top of the file. If `date` isn't imported from `datetime`, add it.

- [ ] **Step 4: Run the test**

```bash
cd C:/PitchRank && python -m pytest tests/test_enhanced_pipeline.py::TestFutureDateHelper -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
cd C:/PitchRank && git add src/etl/enhanced_pipeline.py tests/test_enhanced_pipeline.py
git commit -m "$(cat <<'EOF'
feat(pipeline): add _is_future_game helper for scheduled-game carveout

Helper distinguishes future-dated scheduled games from past-dated data
quality issues. Used by upcoming patches to both score-validation filter
sites in enhanced_pipeline.py.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 1.2: Patch filter site 1 (`_validate_and_dedup`)

**Files:**
- Modify: `src/etl/enhanced_pipeline.py:1063-1072`
- Test: `tests/test_enhanced_pipeline.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_enhanced_pipeline.py`:

```python
class TestValidateAndDedupFutureCarveout:
    @pytest.fixture
    def mock_supabase(self):
        supabase = Mock()
        provider_result = Mock()
        provider_result.data = {'id': 'test-provider-uuid'}
        supabase.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = provider_result
        return supabase

    @pytest.mark.asyncio
    async def test_future_scoreless_game_passes_filter(self, mock_supabase):
        pipeline = EnhancedETLPipeline(mock_supabase, 'gotsport', dry_run=True)
        future_date = (date.today() + timedelta(days=14)).isoformat()
        games = [{
            "game_uid": "future-001",
            "team_id": "team-a",
            "opponent_id": "team-b",
            "game_date": future_date,
            "goals_for": None,
            "goals_against": None,
            "provider": "gotsport",
            "home_away": "H",
        }]
        valid, invalid, stats = await pipeline._validate_and_dedup(games, run_validation=False)
        assert stats["skipped_empty_scores"] == 0
        assert len(valid) == 1

    @pytest.mark.asyncio
    async def test_past_scoreless_game_still_skipped(self, mock_supabase):
        pipeline = EnhancedETLPipeline(mock_supabase, 'gotsport', dry_run=True)
        past_date = (date.today() - timedelta(days=7)).isoformat()
        games = [{
            "game_uid": "past-001",
            "team_id": "team-a",
            "opponent_id": "team-b",
            "game_date": past_date,
            "goals_for": None,
            "goals_against": None,
            "provider": "gotsport",
            "home_away": "H",
        }]
        valid, invalid, stats = await pipeline._validate_and_dedup(games, run_validation=False)
        assert stats["skipped_empty_scores"] == 1
        assert len(valid) == 0
```

- [ ] **Step 2: Run and verify it fails**

```bash
cd C:/PitchRank && python -m pytest tests/test_enhanced_pipeline.py::TestValidateAndDedupFutureCarveout -v
```

Expected: `test_future_scoreless_game_passes_filter` FAILS. `test_past_scoreless_game_still_skipped` passes.

- [ ] **Step 3: Patch the filter site**

In `src/etl/enhanced_pipeline.py` at line 1063-1072, replace:

```python
for game in games:
    # Skip games with no scores
    if self._is_empty_score(game.get("goals_for")) and self._is_empty_score(game.get("goals_against")):
        skipped_empty_scores += 1
        if skipped_empty_scores <= 5:
            logger.debug(
                f"Skipping game with no scores: {game.get('team_id')} vs "
                f"{game.get('opponent_id')} on {game.get('game_date')}"
            )
        continue
```

with:

```python
for game in games:
    # Scoreless games: allow future-dated rows through (scheduled games — daily
    # enqueue uses them as scrape triggers). Skip past/today scoreless rows.
    if self._is_empty_score(game.get("goals_for")) and self._is_empty_score(game.get("goals_against")):
        if self._is_future_game(game):
            pass  # Scheduled game — fall through to dedup/insert with NULL scores
        else:
            skipped_empty_scores += 1
            if skipped_empty_scores <= 5:
                logger.debug(
                    f"Skipping game with no scores: {game.get('team_id')} vs "
                    f"{game.get('opponent_id')} on {game.get('game_date')}"
                )
            continue
```

- [ ] **Step 4: Run the test**

```bash
cd C:/PitchRank && python -m pytest tests/test_enhanced_pipeline.py::TestValidateAndDedupFutureCarveout -v
```

Expected: 2 passed.

- [ ] **Step 5: Run the full file**

```bash
cd C:/PitchRank && python -m pytest tests/test_enhanced_pipeline.py -v
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
cd C:/PitchRank && git add src/etl/enhanced_pipeline.py tests/test_enhanced_pipeline.py
git commit -m "$(cat <<'EOF'
feat(pipeline): allow future-dated scoreless games past _validate_and_dedup

Scheduled games arrive with NULL scores. The pre-dedup gate previously
discarded them as data quality issues; now it lets future-dated rows
through so they persist to games table with NULL scores. Past-dated
scoreless rows continue to be skipped.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 1.3: Patch filter site 2 (`_has_valid_scores`)

**Files:**
- Modify: `src/etl/enhanced_pipeline.py` (add helper after `_has_valid_scores`; patch call site at line ~889)
- Test: `tests/test_enhanced_pipeline.py`

- [ ] **Step 1: Write the failing test**

Append:

```python
class TestHasValidScoresFutureCarveout:
    @pytest.fixture
    def mock_supabase(self):
        supabase = Mock()
        provider_result = Mock()
        provider_result.data = {'id': 'test-provider-uuid'}
        supabase.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = provider_result
        return supabase

    def test_has_valid_scores_rejects_past_null(self, mock_supabase):
        pipeline = EnhancedETLPipeline(mock_supabase, 'gotsport', dry_run=True)
        past_game = {
            "game_uid": "past-null-001",
            "game_date": (date.today() - timedelta(days=7)).isoformat(),
            "home_score": None,
            "away_score": None,
        }
        assert pipeline._has_valid_scores(past_game) is False

    def test_should_accept_for_insert_keeps_future_null(self, mock_supabase):
        pipeline = EnhancedETLPipeline(mock_supabase, 'gotsport', dry_run=True)
        future_game = {
            "game_uid": "future-null-001",
            "game_date": (date.today() + timedelta(days=7)).isoformat(),
            "home_score": None,
            "away_score": None,
        }
        assert pipeline._should_accept_for_insert(future_game) is True

    def test_should_accept_for_insert_rejects_past_null(self, mock_supabase):
        pipeline = EnhancedETLPipeline(mock_supabase, 'gotsport', dry_run=True)
        past_game = {
            "game_uid": "past-null-002",
            "game_date": (date.today() - timedelta(days=7)).isoformat(),
            "home_score": None,
            "away_score": None,
        }
        assert pipeline._should_accept_for_insert(past_game) is False

    def test_should_accept_for_insert_keeps_played_game(self, mock_supabase):
        pipeline = EnhancedETLPipeline(mock_supabase, 'gotsport', dry_run=True)
        played = {
            "game_uid": "played-001",
            "game_date": (date.today() - timedelta(days=2)).isoformat(),
            "home_score": 2,
            "away_score": 1,
        }
        assert pipeline._should_accept_for_insert(played) is True
```

- [ ] **Step 2: Run and verify it fails**

```bash
cd C:/PitchRank && python -m pytest tests/test_enhanced_pipeline.py::TestHasValidScoresFutureCarveout -v
```

Expected: 3 of 4 fail with `AttributeError: ... has no attribute '_should_accept_for_insert'`.

- [ ] **Step 3: Add helper and patch call site**

Add immediately after `_has_valid_scores` in `src/etl/enhanced_pipeline.py`:

```python
def _should_accept_for_insert(self, game: Dict) -> bool:
    """
    Return True if a transformed game record should be inserted.

    Accepts:
      - Games with valid scores
      - Future-dated games with NULL scores (scheduled — score arrives later)

    Rejects:
      - Past or today-dated games with NULL/invalid scores
    """
    if self._has_valid_scores(game):
        return True
    return self._is_future_game(game)
```

Then in the filter loop around line 885-901, change:

```python
for g in game_records:
    if self._has_valid_scores(g):
```

to:

```python
for g in game_records:
    if self._should_accept_for_insert(g):
```

- [ ] **Step 4: Run tests**

```bash
cd C:/PitchRank && python -m pytest tests/test_enhanced_pipeline.py -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
cd C:/PitchRank && git add src/etl/enhanced_pipeline.py tests/test_enhanced_pipeline.py
git commit -m "$(cat <<'EOF'
feat(pipeline): accept future-dated NULL-score games at insert filter

Adds _should_accept_for_insert wrapper around _has_valid_scores so
future-dated scheduled games pass the post-match insert gate while past
data-quality issues continue to be rejected. _has_valid_scores itself is
unchanged.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 1.4: Integration test — scheduled→played dedup

**Files:**
- Create: `tests/integration/test_scheduled_to_played_dedup.py`

- [ ] **Step 1: Write the test**

```python
"""
Integration guard: game_uid is symmetric on (team_a, team_b, game_date) and
independent of scores. This is the precondition for scheduled rows UPDATING
to played rows in dedup.
"""
from datetime import date, timedelta
from unittest.mock import Mock
import pytest

from src.etl.enhanced_pipeline import EnhancedETLPipeline


@pytest.fixture
def mock_supabase():
    supabase = Mock()
    provider_result = Mock()
    provider_result.data = {'id': 'test-provider-uuid'}
    supabase.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = provider_result
    supabase.table.return_value.select.return_value.in_.return_value.execute.return_value.data = []
    return supabase


@pytest.mark.asyncio
async def test_game_uid_identical_for_scheduled_and_played(mock_supabase):
    pipeline = EnhancedETLPipeline(mock_supabase, 'gotsport', dry_run=True)
    game_date = (date.today() + timedelta(days=3)).isoformat()

    scheduled = {
        "team_id": "team-a",
        "opponent_id": "team-b",
        "game_date": game_date,
        "goals_for": None,
        "goals_against": None,
        "home_away": "H",
        "provider": "gotsport",
    }
    played = {
        "team_id": "team-a",
        "opponent_id": "team-b",
        "game_date": game_date,
        "goals_for": 2,
        "goals_against": 1,
        "home_away": "H",
        "provider": "gotsport",
    }

    valid_sched, _, _ = await pipeline._validate_and_dedup([scheduled], run_validation=False)
    valid_played, _, _ = await pipeline._validate_and_dedup([played], run_validation=False)

    assert len(valid_sched) == 1
    assert len(valid_played) == 1
    assert valid_sched[0].get("game_uid") is not None
    assert valid_sched[0].get("game_uid") == valid_played[0].get("game_uid")
```

- [ ] **Step 2: Run**

```bash
cd C:/PitchRank && python -m pytest tests/integration/test_scheduled_to_played_dedup.py -v
```

Expected: PASS. If it fails, STOP — the dedup model is broken and Phase 1 cannot ship safely. Investigate `game_uid` generation in `enhanced_validators.py` or wherever it's set.

- [ ] **Step 3: Commit**

```bash
cd C:/PitchRank && git add tests/integration/test_scheduled_to_played_dedup.py
git commit -m "$(cat <<'EOF'
test(pipeline): prove game_uid symmetry across scheduled→played transition

Asserts that the same calendar game produces an identical game_uid whether
scraped before kickoff (NULL scores) or after (real scores). Precondition
for the UPDATE-on-uid-collision dedup path.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 1.5: Consumer audit — rankings NULL-score guard

**Files:**
- Read only first: `src/rankings/calculator.py`, `src/rankings/data_adapter.py`
- Potential modify: ranking input loader (if audit finds a gap)

- [ ] **Step 1: Locate the ranking input loader**

```bash
cd C:/PitchRank && grep -rn "home_score\|away_score\|goals_for\|goals_against" src/rankings/data_adapter.py | head -20
```

Identify the function/query that loads games for ranking. Look for an existing `WHERE home_score IS NOT NULL` (or equivalent filter via view).

- [ ] **Step 2: Verify or add the guard**

**If the existing query already filters NULL scores** (e.g., reads from `rankings_view` which has `WHERE result IS NOT NULL`): note the file and line in your handoff. No code change.

**If no filter exists:** add one. Either:
- Add `IS NOT NULL` predicate to the query
- Add an assertion at the loader entrypoint that raises if any input row has NULL scores

Whichever applies, write the test that proves it:

```python
# tests/unit/test_ranking_null_score_guard.py
import pytest


def test_ranking_loader_excludes_null_score_games():
    """
    The ranking input loader must NOT return NULL-score rows.
    Replace the import + assertion below with the actual loader function once located.
    """
    # from src.rankings.data_adapter import <actual_loader_name>
    # rows = <actual_loader_name>(supabase_or_db)
    # assert all(r.get("home_score") is not None and r.get("away_score") is not None for r in rows)
    pytest.skip("Replace with concrete assertion against the located loader")
```

If the existing query already filters: convert the skip into a query-shape assertion (test that the generated SQL contains `IS NOT NULL`).

- [ ] **Step 3: Commit only if changes were made**

```bash
cd C:/PitchRank && git add tests/unit/test_ranking_null_score_guard.py src/rankings/
git commit -m "$(cat <<'EOF'
test(rankings): guard against NULL-score games entering Glicko-2 input

Required before scheduled games (NULL-score by definition) start landing
in the games table.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 1.6: Consumer audit — `games.result` derivation

**Files:**
- Read: schema migrations matching the `games` table or `result` column

- [ ] **Step 1: Locate the result-column definition**

```bash
cd C:/PitchRank && grep -rn "result.*GENERATED\|games.*result\|trigger.*games" supabase/migrations/ | head -20
```

Determine: generated column? Trigger? Pipeline-set?

- [ ] **Step 2: Verify NULL-score behavior**

- **Generated/trigger:** test by querying for any existing row with NULL scores. If `result` is non-NULL there, the derivation has a bug.
- **Pipeline-set:** trace the code path. In `process_missing_games.py:223` the default is `game.result or "U"`. Verify this code path doesn't run for scheduled games or that the default is harmless. If a "U" leaks for scheduled rows, the test in Task 1.5 (consumer audit) may catch it.

- [ ] **Step 3: Document or patch**

Either:
- Note in spec/handoff that NULL-score rows produce NULL `result` (no action needed), or
- Patch the derivation site to set NULL for NULL scores and commit.

---

### Task 1.7: Push Phase 1 PR

- [ ] **Step 1: Run the full test suite**

```bash
cd C:/PitchRank && python -m pytest tests/test_enhanced_pipeline.py tests/integration/test_scheduled_to_played_dedup.py tests/unit/test_ranking_null_score_guard.py -v
```

Expected: all pass.

- [ ] **Step 2: Push branch and open PR (Phase 1 only)**

```bash
cd C:/PitchRank && git push -u origin spec/schedule-driven-scraping
```

Open PR via `gh pr create` (user runs this) with title `feat(pipeline): persist future-dated NULL-score games`. Scope = Phase 1 only.

---

## Phase 2: Bootstrap (operational, no code)

After Phase 1 merges and deploys:

### Task 2.1: Manual bootstrap dispatch

- [ ] **Step 1: Verify pipeline patch is live**

```bash
cd C:/PitchRank && git fetch origin main && git log origin/main --oneline | head -10
```

Confirm Phase 1 commits are on main.

- [ ] **Step 2: Dispatch `scrape-games.yml` with bootstrap inputs**

```bash
gh workflow run scrape-games.yml -f null_teams_only=true -f limit_teams=5000
```

Or use the existing chain pattern with the workflow's defaults. Watch the first link's logs:

```bash
gh run watch
```

- [ ] **Step 3: Sanity-check post-run**

```bash
cd C:/PitchRank && python -c "
import truststore; truststore.inject_into_ssl()
import os
from dotenv import load_dotenv
load_dotenv('.env.local'); load_dotenv('.env')
from supabase import create_client
c = create_client(os.environ['SUPABASE_URL'], os.environ['SUPABASE_SERVICE_ROLE_KEY'])
r = c.table('games').select('id', count='exact').is_('home_score', 'null').gt('game_date', 'today').execute()
print(f'Future scheduled rows: {r.count}')
"
```

Expected: non-zero. If zero, Phase 1 patch didn't deploy correctly — investigate before continuing.

- [ ] **Step 4: Iterate**

Dispatch more workflow runs (or chain links) until coverage is good. Track `teams.last_scraped_at` distribution to see progress.

---

## Phase 3: Queue Infrastructure

### Task 3.1: Schema migration

**Files:**
- Create: `supabase/migrations/<TS>_add_priority_to_scrape_requests.sql`

- [ ] **Step 1: Check for duplicate pending rows (pre-flight)**

```bash
cd C:/PitchRank && python -c "
import truststore; truststore.inject_into_ssl()
import os
from dotenv import load_dotenv
load_dotenv('.env.local'); load_dotenv('.env')
from supabase import create_client
c = create_client(os.environ['SUPABASE_URL'], os.environ['SUPABASE_SERVICE_ROLE_KEY'])
r = c.table('scrape_requests').select('team_id_master').eq('status', 'pending').execute()
ids = [row['team_id_master'] for row in r.data if row.get('team_id_master')]
from collections import Counter
dups = {k: v for k, v in Counter(ids).items() if v > 1}
print(f'Duplicate pending team_ids: {len(dups)}')
if dups: print(list(dups.items())[:5])
"
```

If duplicates exist, write a migration step that consolidates them before applying the UNIQUE INDEX (keep oldest pending row, mark others as `superseded` or delete).

- [ ] **Step 2: Generate migration filename**

```bash
cd C:/PitchRank && date -u +%Y%m%d%H%M%S
```

Use the output as the prefix.

- [ ] **Step 3: Write the migration**

`supabase/migrations/<TS>_add_priority_to_scrape_requests.sql`:

```sql
-- Add priority column
ALTER TABLE scrape_requests
  ADD COLUMN IF NOT EXISTS priority smallint NOT NULL DEFAULT 5;

COMMENT ON COLUMN scrape_requests.priority IS
  'Lower number = higher priority. 1=user-clicked, 2=daily yesterday-game, 3=discovery, 4=safety-net, 5=default';

-- Consolidate duplicate pending rows if any (uncomment and adjust if step 1 found dups):
-- DELETE FROM scrape_requests sr1
-- WHERE sr1.status = 'pending'
--   AND EXISTS (
--     SELECT 1 FROM scrape_requests sr2
--     WHERE sr2.status = 'pending'
--       AND sr2.team_id_master = sr1.team_id_master
--       AND sr2.requested_at < sr1.requested_at
--   );

-- Unique pending per team
CREATE UNIQUE INDEX IF NOT EXISTS idx_scrape_requests_pending_team
  ON scrape_requests (team_id_master)
  WHERE status = 'pending';

-- Drain-order index
CREATE INDEX IF NOT EXISTS idx_scrape_requests_priority_pending
  ON scrape_requests (priority ASC, requested_at ASC)
  WHERE status = 'pending';
```

- [ ] **Step 4: Apply migration**

```bash
cd C:/PitchRank && npx supabase db push 2>&1 | tail -20
```

Or apply via Supabase Studio.

- [ ] **Step 5: Verify**

```bash
cd C:/PitchRank && python -c "
import truststore; truststore.inject_into_ssl()
import os
from dotenv import load_dotenv
load_dotenv('.env.local'); load_dotenv('.env')
from supabase import create_client
c = create_client(os.environ['SUPABASE_URL'], os.environ['SUPABASE_SERVICE_ROLE_KEY'])
r = c.table('scrape_requests').select('priority').limit(1).execute()
print(f'priority column present: {r.data}')
"
```

- [ ] **Step 6: Commit**

```bash
cd C:/PitchRank && git add supabase/migrations/
git commit -m "$(cat <<'EOF'
feat(db): add priority + uniqueness indexes to scrape_requests

Priority column enables ordered draining (user clicks first, daily
yesterday-games second, discovery third). Unique-on-pending index lets
upsert semantics keep one pending row per team.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3.2: Update `process_missing_games.py` to use priority ordering + cap

**Files:**
- Modify: `scripts/process_missing_games.py`

- [ ] **Step 1: Read the fetch function**

```bash
cd C:/PitchRank && grep -n "def get_pending_requests\|order\(.requested_at" scripts/process_missing_games.py
```

Locate the query that picks pending requests (currently around line 63-79).

- [ ] **Step 2: Patch the ordering and cap**

In `scripts/process_missing_games.py:63-79`, change:

```python
result = (
    self.supabase.table("scrape_requests")
    .select("*")
    .eq("status", "pending")
    .eq("request_type", "missing_game")
    .order("requested_at")
    .limit(limit)
    .execute()
)
```

to:

```python
result = (
    self.supabase.table("scrape_requests")
    .select("*")
    .eq("status", "pending")
    .order("priority", desc=False)
    .order("requested_at", desc=False)
    .limit(limit)
    .execute()
)
```

Removed: the `.eq("request_type", "missing_game")` filter. Reason: the queue now serves multiple request types (yesterday-game, discovery, safety-net, user-clicked). All get processed the same way — the `request_type` is just metadata for observability.

- [ ] **Step 3: Make `--limit` default to 200**

In the argparse section, change the default from `10` (or whatever it currently is) to `200`. Confirm by reading the `argparse.ArgumentParser` block.

- [ ] **Step 4: Write a quick unit test**

`tests/unit/test_process_missing_games_priority.py`:

```python
"""
Verify get_pending_requests orders by priority then requested_at.
"""
from unittest.mock import Mock, MagicMock
import sys, os
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from scripts.process_missing_games import MissingGamesProcessor


def test_get_pending_requests_orders_by_priority_then_requested_at():
    supabase = Mock()
    # Track the order() calls
    q = supabase.table.return_value.select.return_value.eq.return_value
    q.order.return_value = q  # chained .order() returns self
    q.limit.return_value.execute.return_value.data = []

    p = MissingGamesProcessor(supabase, dry_run=True)
    p.get_pending_requests(limit=200)

    # Both order() calls should have been made: priority first, then requested_at
    calls = q.order.call_args_list
    assert len(calls) >= 2
    assert calls[0].args[0] == "priority"
    assert calls[1].args[0] == "requested_at"
```

- [ ] **Step 5: Run**

```bash
cd C:/PitchRank && python -m pytest tests/unit/test_process_missing_games_priority.py -v
```

Expected: pass.

- [ ] **Step 6: Commit**

```bash
cd C:/PitchRank && git add scripts/process_missing_games.py tests/unit/test_process_missing_games_priority.py
git commit -m "$(cat <<'EOF'
feat(queue): order scrape_requests drain by priority then requested_at

Drains highest-priority requests first (lower number = higher priority).
Within the same priority, oldest requests drain first (FIFO). Removes the
request_type='missing_game' filter so all queue sources are processed
uniformly. Default cap raised to 200 per run.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3.3: Bump `process-missing-games.yml` to 15-minute cadence

**Files:**
- Modify: `.github/workflows/process-missing-games.yml`

- [ ] **Step 1: Patch the schedule and limit**

Open `.github/workflows/process-missing-games.yml`. Change:

```yaml
schedule:
  - cron: '0 * * * *'  # hourly
```

to:

```yaml
schedule:
  - cron: '*/15 * * * *'  # every 15 minutes
```

And in the run step, change:

```bash
python scripts/process_missing_games.py --limit 10 || exit 1
```

to:

```bash
python scripts/process_missing_games.py --limit 200 || exit 1
```

Add a `concurrency:` block to prevent overlapping runs (15-min cron + slow runs could stack):

```yaml
concurrency:
  group: process-missing-games
  cancel-in-progress: false
```

- [ ] **Step 2: Commit**

```bash
cd C:/PitchRank && git add .github/workflows/process-missing-games.yml
git commit -m "$(cat <<'EOF'
ci(process-missing-games): 15-min cadence, 200/run cap, no-overlap

Per-run cap = ~0.22 req/sec sustained, well below GotSport WAF limits.
Concurrency block prevents 15-min cron + slow runs from stacking.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3.4: User-click handler — set priority=1

**Files:**
- Modify: wherever user-clicked "process missing games" requests are inserted (audit needed)

- [ ] **Step 1: Find the insert site**

```bash
cd C:/PitchRank && grep -rn "scrape_requests.*insert\|insert.*scrape_requests\|missing_game" frontend/ src/ scripts/ | grep -v "process_missing_games.py" | head -20
```

Likely candidates: `frontend/lib/api.ts`, a frontend handler, or a Supabase RPC.

- [ ] **Step 2: Add priority=1 to the insert payload**

Wherever the insert happens, ensure `priority: 1` is included:

```typescript
// Example for TypeScript:
await supabase.from('scrape_requests').insert({
  team_id_master: teamId,
  request_type: 'missing_game',
  status: 'pending',
  priority: 1,  // <-- ADD THIS
  requested_at: new Date().toISOString(),
});
```

If the insert is via an RPC, update the RPC to default `priority=1` (or pass it explicitly).

- [ ] **Step 3: Commit**

```bash
cd C:/PitchRank && git add <files>
git commit -m "$(cat <<'EOF'
feat(missing-games): user-clicked requests enqueue at priority 1

User-initiated requests jump ahead of auto-enqueued daily/discovery
requests so the UI feels responsive.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase 4: Daily Yesterday-Game Enqueue

### Task 4.1: Write enqueue script

**Files:**
- Create: `scripts/enqueue_yesterday_games.py`
- Create: `tests/unit/test_enqueue_yesterday_games.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_enqueue_yesterday_games.py
"""Tests for the daily yesterday-game enqueue script."""
from datetime import date, timedelta
from unittest.mock import Mock, MagicMock, patch
import pytest

from scripts.enqueue_yesterday_games import find_teams_to_enqueue, enqueue_team


def test_find_teams_to_enqueue_returns_distinct_team_ids():
    supabase = Mock()
    supabase.rpc.return_value.execute.return_value.data = [
        {"team_id_master": "t-1"},
        {"team_id_master": "t-2"},
        {"team_id_master": "t-1"},  # duplicate
    ]
    teams = find_teams_to_enqueue(supabase, gotsport_provider_id="gp")
    team_ids = [t["team_id_master"] for t in teams]
    assert len(team_ids) == len(set(team_ids))


def test_enqueue_team_uses_priority_2():
    supabase = Mock()
    enqueue_team(supabase, team_id_master="t-1")
    # Inspect the insert payload
    upsert_call = supabase.table.return_value.upsert.call_args
    payload = upsert_call.args[0]
    assert payload["priority"] == 2
    assert payload["status"] == "pending"
    assert payload["team_id_master"] == "t-1"
```

- [ ] **Step 2: Write the script**

`scripts/enqueue_yesterday_games.py`:

```python
#!/usr/bin/env python3
"""
Daily enqueue: scan games table for yesterday's NULL-score rows, enqueue each
affected team into scrape_requests at priority 2.

Does NOT scrape. process_missing_games drains the queue.
"""
import argparse
import logging
import os
import sys
from datetime import date, datetime, timedelta

import truststore
truststore.inject_into_ssl()

from dotenv import load_dotenv
load_dotenv(".env.local")
load_dotenv(".env")

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from supabase import create_client

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

GOTSPORT_PROVIDER_CODE = "gotsport"
PRIORITY_YESTERDAY_GAME = 2


def get_gotsport_provider_id(supabase):
    r = supabase.table("providers").select("id").eq("code", GOTSPORT_PROVIDER_CODE).single().execute()
    if not r.data:
        raise RuntimeError(f"Provider '{GOTSPORT_PROVIDER_CODE}' not found")
    return r.data["id"]


def find_teams_to_enqueue(supabase, gotsport_provider_id):
    """
    Return DISTINCT team_id_master values for GotSport teams that had a game
    yesterday with NULL home_score.
    """
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    try:
        r = supabase.rpc("find_yesterday_null_score_teams", {
            "yesterday": yesterday,
            "provider_id": gotsport_provider_id,
        }).execute()
        return r.data or []
    except Exception as e:
        logger.warning(f"RPC unavailable ({e}), using fallback")
        return _fallback_query(supabase, gotsport_provider_id, yesterday)


def _fallback_query(supabase, provider_id, yesterday):
    home = supabase.table("games").select(
        "home_team_master_id, teams!inner(team_id_master, is_deprecated, provider_id)"
    ).eq("game_date", yesterday).is_("home_score", "null").execute()
    away = supabase.table("games").select(
        "away_team_master_id, teams!inner(team_id_master, is_deprecated, provider_id)"
    ).eq("game_date", yesterday).is_("home_score", "null").execute()
    seen = {}
    for row in (home.data or []) + (away.data or []):
        team = row.get("teams")
        if not team or team.get("is_deprecated") or team.get("provider_id") != provider_id:
            continue
        seen[team["team_id_master"]] = {"team_id_master": team["team_id_master"]}
    return list(seen.values())


def enqueue_team(supabase, team_id_master):
    """
    UPSERT a pending scrape_requests row at priority 2.
    If a pending row already exists, keep the lower priority value (more urgent).
    """
    payload = {
        "team_id_master": team_id_master,
        "request_type": "yesterday_game",
        "status": "pending",
        "priority": PRIORITY_YESTERDAY_GAME,
        "requested_at": datetime.now().isoformat(),
    }
    # Use upsert with ON CONFLICT — Supabase Python client supports on_conflict param
    supabase.table("scrape_requests").upsert(payload, on_conflict="team_id_master").execute()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    url = os.environ.get("SUPABASE_URL") or os.environ.get("NEXT_PUBLIC_SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_KEY")
    supabase = create_client(url, key)

    provider_id = get_gotsport_provider_id(supabase)
    teams = find_teams_to_enqueue(supabase, provider_id)
    logger.info(f"Found {len(teams)} teams to enqueue (yesterday games, NULL score)")

    if args.dry_run:
        for t in teams[:20]:
            logger.info(f"  WOULD ENQUEUE: {t['team_id_master']}")
        return

    for t in teams:
        try:
            enqueue_team(supabase, t["team_id_master"])
        except Exception as e:
            logger.warning(f"Failed to enqueue {t['team_id_master']}: {e}")

    logger.info(f"Enqueued {len(teams)} teams at priority {PRIORITY_YESTERDAY_GAME}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Run the test**

```bash
cd C:/PitchRank && python -m pytest tests/unit/test_enqueue_yesterday_games.py -v
```

Expected: pass.

NOTE: the upsert `on_conflict` param needs to match a unique constraint. With our partial unique index `idx_scrape_requests_pending_team`, the Supabase JS/PostgREST UPSERT may not honor partial indexes. If the upsert fails with "no unique constraint matching ON CONFLICT," fall back to manual check-then-insert/update logic, or write a SQL RPC `enqueue_team_request(team_id, priority, request_type)` and call that instead.

- [ ] **Step 4: Test dry-run locally**

```bash
cd C:/PitchRank && python scripts/enqueue_yesterday_games.py --dry-run
```

Expected: logs the count of teams that would be enqueued; lists first 20. If count is zero, verify Phase 1 + Phase 2 actually populated future-scheduled rows that have now aged into yesterday.

- [ ] **Step 5: Commit**

```bash
cd C:/PitchRank && git add scripts/enqueue_yesterday_games.py tests/unit/test_enqueue_yesterday_games.py
git commit -m "$(cat <<'EOF'
feat(scripts): daily enqueue for teams with yesterday's NULL-score games

Scans games table for game_date = yesterday with NULL home_score, enqueues
each affected GotSport team into scrape_requests at priority 2. Does not
scrape; process_missing_games drains the queue.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 4.2: GitHub Actions workflow

**Files:**
- Create: `.github/workflows/enqueue-yesterday-games.yml`

- [ ] **Step 1: Write the workflow**

```yaml
name: Enqueue Yesterday-Game Teams
run-name: Enqueue yesterday teams (${{ inputs.dry_run == true && 'DRY RUN' || 'live' }})

on:
  schedule:
    # 12:00 UTC = 5am Phoenix, 8am Eastern. East-Coast Sunday-night games have
    # had ~12 hours to post scores by then.
    - cron: '0 12 * * *'
  workflow_dispatch:
    inputs:
      dry_run:
        description: 'Dry run: log targets only'
        required: false
        type: boolean
        default: false

jobs:
  enqueue:
    runs-on: ubuntu-latest
    timeout-minutes: 10
    env:
      DRY_RUN_FLAG: ${{ inputs.dry_run == true && '--dry-run' || '' }}
    steps:
      - uses: actions/checkout@v5
      - uses: actions/setup-python@v6
        with:
          python-version: '3.11'
      - name: Install deps
        run: |
          python -m pip install --upgrade pip
          pip install supabase python-dotenv truststore certifi
      - name: Enqueue
        env:
          SUPABASE_URL: ${{ secrets.SUPABASE_URL }}
          SUPABASE_SERVICE_ROLE_KEY: ${{ secrets.SUPABASE_SERVICE_KEY }}
        run: |
          export PYTHONPATH="${PYTHONPATH}:${PWD}"
          python scripts/enqueue_yesterday_games.py $DRY_RUN_FLAG
```

- [ ] **Step 2: Commit**

```bash
cd C:/PitchRank && git add .github/workflows/enqueue-yesterday-games.yml
git commit -m "$(cat <<'EOF'
ci: daily 12pm UTC workflow for yesterday-game enqueue

Triggers enqueue_yesterday_games.py once per day. Drained by the existing
process-missing-games workflow (now at 15-min cadence).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 3: Shadow run**

```bash
gh workflow run enqueue-yesterday-games.yml -f dry_run=true
gh run watch
```

Inspect logs. Should see the count and first 20 candidate teams.

---

## Phase 5: Weekly Discovery Enqueue

### Task 5.1: Write enqueue script

**Files:**
- Create: `scripts/enqueue_discovery_teams.py`
- Create: `tests/unit/test_enqueue_discovery_teams.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_enqueue_discovery_teams.py
from unittest.mock import Mock
import pytest

from scripts.enqueue_discovery_teams import find_teams_to_enqueue, PRIORITY_DISCOVERY


def test_priority_is_3():
    assert PRIORITY_DISCOVERY == 3


def test_find_teams_limits_to_default_1000():
    supabase = Mock()
    supabase.rpc.return_value.execute.return_value.data = [
        {"team_id_master": f"t-{i}"} for i in range(1000)
    ]
    teams = find_teams_to_enqueue(supabase, gotsport_provider_id="gp", limit=1000)
    assert len(teams) == 1000
```

- [ ] **Step 2: Write the script**

`scripts/enqueue_discovery_teams.py`:

```python
#!/usr/bin/env python3
"""
Weekly discovery enqueue: find GotSport teams with no future games on record,
enqueue at priority 3. Slowly chips through teams whose schedules we can't see
(between sessions, newly added clubs, etc.).
"""
import argparse
import logging
import os
import sys
from datetime import datetime

import truststore
truststore.inject_into_ssl()

from dotenv import load_dotenv
load_dotenv(".env.local")
load_dotenv(".env")

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from supabase import create_client

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

GOTSPORT_PROVIDER_CODE = "gotsport"
PRIORITY_DISCOVERY = 3
DEFAULT_LIMIT = 1000


def get_gotsport_provider_id(supabase):
    r = supabase.table("providers").select("id").eq("code", GOTSPORT_PROVIDER_CODE).single().execute()
    return r.data["id"]


def find_teams_to_enqueue(supabase, gotsport_provider_id, limit=DEFAULT_LIMIT):
    """
    Teams with no future-dated games on record, ordered by last_scraped_at ASC NULLS FIRST.
    """
    try:
        r = supabase.rpc("find_discovery_teams", {
            "provider_id": gotsport_provider_id,
            "row_limit": limit,
        }).execute()
        return r.data or []
    except Exception as e:
        logger.warning(f"RPC unavailable ({e}); plan-time TODO: add the RPC migration alongside this script")
        return []


def enqueue_team(supabase, team_id_master):
    payload = {
        "team_id_master": team_id_master,
        "request_type": "discovery",
        "status": "pending",
        "priority": PRIORITY_DISCOVERY,
        "requested_at": datetime.now().isoformat(),
    }
    supabase.table("scrape_requests").upsert(payload, on_conflict="team_id_master").execute()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    url = os.environ.get("SUPABASE_URL") or os.environ.get("NEXT_PUBLIC_SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_KEY")
    supabase = create_client(url, key)

    provider_id = get_gotsport_provider_id(supabase)
    teams = find_teams_to_enqueue(supabase, provider_id, limit=args.limit)
    logger.info(f"Discovery: {len(teams)} GotSport teams without future games")

    if args.dry_run:
        for t in teams[:20]:
            logger.info(f"  WOULD ENQUEUE: {t['team_id_master']}")
        return

    for t in teams:
        try:
            enqueue_team(supabase, t["team_id_master"])
        except Exception as e:
            logger.warning(f"Failed to enqueue {t['team_id_master']}: {e}")

    logger.info(f"Enqueued {len(teams)} teams at priority {PRIORITY_DISCOVERY}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Add the discovery RPC**

Generate a migration filename:

```bash
cd C:/PitchRank && date -u +%Y%m%d%H%M%S
```

Create `supabase/migrations/<TS>_find_discovery_teams.sql`:

```sql
CREATE OR REPLACE FUNCTION find_discovery_teams(
    provider_id uuid,
    row_limit integer DEFAULT 1000
)
RETURNS TABLE(team_id_master uuid)
LANGUAGE sql
STABLE
AS $$
    SELECT t.team_id_master
    FROM teams t
    WHERE t.is_deprecated = false
      AND t.provider_id = find_discovery_teams.provider_id
      AND NOT EXISTS (
          SELECT 1 FROM games g
          WHERE (g.home_team_master_id = t.team_id_master OR g.away_team_master_id = t.team_id_master)
            AND g.game_date > CURRENT_DATE
      )
    ORDER BY t.last_scraped_at ASC NULLS FIRST
    LIMIT find_discovery_teams.row_limit;
$$;

GRANT EXECUTE ON FUNCTION find_discovery_teams(uuid, integer) TO authenticated, service_role;
```

Apply:

```bash
cd C:/PitchRank && npx supabase db push 2>&1 | tail -10
```

- [ ] **Step 4: Tests + dry-run**

```bash
cd C:/PitchRank && python -m pytest tests/unit/test_enqueue_discovery_teams.py -v
python scripts/enqueue_discovery_teams.py --dry-run
```

- [ ] **Step 5: Commit**

```bash
cd C:/PitchRank && git add scripts/enqueue_discovery_teams.py tests/unit/test_enqueue_discovery_teams.py supabase/migrations/
git commit -m "$(cat <<'EOF'
feat(scripts): weekly discovery enqueue for teams without future games

Enqueues 1,000 GotSport teams/week at priority 3, ordered by oldest
last_scraped_at first. Slowly chips through teams whose schedules we
don't have visibility into yet.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 5.2: Discovery workflow

**Files:**
- Create: `.github/workflows/enqueue-discovery.yml`

- [ ] **Step 1: Write the workflow**

```yaml
name: Enqueue Discovery Teams
run-name: Enqueue discovery (${{ inputs.dry_run == true && 'DRY RUN' || 'live' }})

on:
  schedule:
    # Sunday 2:00 PM UTC — runs after weekend games have populated NULL rows but
    # before Monday's yesterday-game enqueue, so discovery teams are queued
    # behind weekend yesterday-games.
    - cron: '0 14 * * 0'
  workflow_dispatch:
    inputs:
      dry_run:
        description: 'Dry run: log targets only'
        required: false
        type: boolean
        default: false
      limit:
        description: 'Max teams to enqueue'
        required: false
        type: string
        default: '1000'

jobs:
  enqueue:
    runs-on: ubuntu-latest
    timeout-minutes: 10
    env:
      DRY_RUN_FLAG: ${{ inputs.dry_run == true && '--dry-run' || '' }}
      LIMIT_FLAG: ${{ inputs.limit != '' && format('--limit {0}', inputs.limit) || '' }}
    steps:
      - uses: actions/checkout@v5
      - uses: actions/setup-python@v6
        with:
          python-version: '3.11'
      - run: pip install supabase python-dotenv truststore certifi
      - name: Enqueue
        env:
          SUPABASE_URL: ${{ secrets.SUPABASE_URL }}
          SUPABASE_SERVICE_ROLE_KEY: ${{ secrets.SUPABASE_SERVICE_KEY }}
        run: |
          export PYTHONPATH="${PYTHONPATH}:${PWD}"
          python scripts/enqueue_discovery_teams.py $DRY_RUN_FLAG $LIMIT_FLAG
```

- [ ] **Step 2: Commit + shadow run**

```bash
cd C:/PitchRank && git add .github/workflows/enqueue-discovery.yml
git commit -m "ci: weekly Sunday 2pm UTC discovery enqueue

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"

gh workflow run enqueue-discovery.yml -f dry_run=true
```

---

## Phase 6: Weekly Safety-Net Enqueue

### Task 6.1: Script + workflow

**Files:**
- Create: `scripts/enqueue_safety_net.py`
- Create: `.github/workflows/enqueue-safety-net.yml`

Structurally identical to Phase 5 discovery, with these differences:
- `PRIORITY_SAFETY_NET = 4`
- Query selects on `last_scraped_at IS NULL OR < NOW() - INTERVAL '90 days'` instead of `NOT EXISTS future games`
- Default `--limit 500`
- Workflow schedule: `cron: '0 16 * * 0'` (Sunday 4pm UTC, after discovery)

- [ ] **Step 1: Write `scripts/enqueue_safety_net.py`**

Copy `enqueue_discovery_teams.py` and modify:
- `PRIORITY = 4`
- Replace `find_discovery_teams` RPC call with `find_stale_teams`
- `request_type = "safety_net"`
- Default `LIMIT = 500`

- [ ] **Step 2: Add `find_stale_teams` RPC**

`supabase/migrations/<TS>_find_stale_teams.sql`:

```sql
CREATE OR REPLACE FUNCTION find_stale_teams(
    provider_id uuid,
    row_limit integer DEFAULT 500
)
RETURNS TABLE(team_id_master uuid)
LANGUAGE sql
STABLE
AS $$
    SELECT t.team_id_master
    FROM teams t
    WHERE t.is_deprecated = false
      AND t.provider_id = find_stale_teams.provider_id
      AND (t.last_scraped_at IS NULL OR t.last_scraped_at < NOW() - INTERVAL '90 days')
    ORDER BY t.last_scraped_at ASC NULLS FIRST
    LIMIT find_stale_teams.row_limit;
$$;

GRANT EXECUTE ON FUNCTION find_stale_teams(uuid, integer) TO authenticated, service_role;
```

- [ ] **Step 3: Write `.github/workflows/enqueue-safety-net.yml`**

Copy `enqueue-discovery.yml` and adjust schedule + script path.

- [ ] **Step 4: Commit**

```bash
cd C:/PitchRank && git add scripts/enqueue_safety_net.py .github/workflows/enqueue-safety-net.yml supabase/migrations/
git commit -m "$(cat <<'EOF'
feat: weekly safety-net enqueue for 90-day stale teams

Catches GotSport teams the daily and discovery enqueues miss (deprecated-
undeprecated, provider relinks, etc.). 500 teams/week at priority 4.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase 7: Deprecate `scrape-games.yml` automation

### Task 7.1: Remove scheduled cron, keep manual dispatch

**Files:**
- Modify: `.github/workflows/scrape-games.yml`

- [ ] **Step 1: Wait for Phases 4-6 to stabilize**

Watch one full week with the new queue handling everything:
- Daily enqueue feeding the queue
- Process-missing-games draining at 200/15min
- Discovery + safety-net adding low-priority teams
- Queue depth stays manageable (no unbounded growth)

If queue grows faster than drains, do NOT proceed — investigate.

- [ ] **Step 2: Remove the `schedule:` block**

In `.github/workflows/scrape-games.yml`, delete the entire `schedule:` block:

```yaml
on:
  schedule:
    - cron: '0 6 * * 1'  # DELETE THIS BLOCK
  workflow_dispatch:
    inputs: ...  # KEEP THIS
```

leaving only:

```yaml
on:
  workflow_dispatch:
    inputs: ...
```

Update the workflow's top-level comment to note this is now manual-only for bulk operations.

- [ ] **Step 3: Commit**

```bash
cd C:/PitchRank && git add .github/workflows/scrape-games.yml
git commit -m "$(cat <<'EOF'
ci(scrape-games): remove scheduled cron, keep manual dispatch

Workflow becomes a manual operator tool for bulk ZenRows scraping
(bootstrap, large one-offs, queue recovery). Scheduled automation is
now handled by the unified scrape_requests queue.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase 8: New-Team Hook

### Task 8.1: Audit existing path

- [ ] **Step 1: Find team-insert sites**

```bash
cd C:/PitchRank && grep -rn "table.*teams.*insert\|insert.*teams\|create_team" scripts/ src/ frontend/lib/ | head -20
```

- [ ] **Step 2: Trace each insert site to verify a scrape is triggered**

For each, follow what happens after the INSERT into `teams`. Does it enqueue a `scrape_requests` row?

- [ ] **Step 3: Document or patch**

If a gap exists, add an INSERT into `scrape_requests` at priority 2 immediately after the team insert succeeds. Match the language/shape of the surrounding code.

Commit if changes made:

```bash
cd C:/PitchRank && git add <files>
git commit -m "$(cat <<'EOF'
feat(teams): enqueue scrape request on new team insert

New teams enter the queue at priority 2 so their schedule is fetched
within hours of being added.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Final Verification

- [ ] **Step 1: Full test suite**

```bash
cd C:/PitchRank && python -m pytest tests/ -v --tb=short 2>&1 | tail -40
```

Expected: all green.

- [ ] **Step 2: End-to-end check**

```bash
cd C:/PitchRank && python -c "
import truststore; truststore.inject_into_ssl()
import os
from dotenv import load_dotenv
load_dotenv('.env.local'); load_dotenv('.env')
from supabase import create_client
from datetime import date, timedelta
c = create_client(os.environ['SUPABASE_URL'], os.environ['SUPABASE_SERVICE_ROLE_KEY'])

# Scheduled rows exist
r = c.table('games').select('id', count='exact').is_('home_score', 'null').gt('game_date', date.today().isoformat()).execute()
print(f'Future scheduled rows: {r.count}')

# Yesterday's NULL rows being filled
y = (date.today() - timedelta(days=1)).isoformat()
r = c.table('games').select('id', count='exact').eq('game_date', y).not_.is_('home_score', 'null').execute()
print(f'Yesterday filled scores: {r.count}')

# Queue health
r = c.table('scrape_requests').select('priority', count='exact').eq('status', 'pending').execute()
print(f'Pending queue depth: {r.count}')
"
```

Health signals:
- Future scheduled rows > 0
- Yesterday filled scores > 0 (and increasing day over day)
- Pending queue depth: usually < 5K outside weekend spikes; spikes Mon/Tue to ~20-40K and drains by Wed-Thu

- [ ] **Step 3: Update spec status**

In `docs/superpowers/specs/2026-05-19-schedule-driven-scraping-design.md`, change `Status: Draft (pending implementation)` → `Status: Deployed`.

---

## Notes for the Implementer

1. **Phase 1 ships alone.** Do not start Phase 2 until Phase 1 is merged and deployed. Bootstrap is wasted budget if the pipeline still discards future games.
2. **`game_uid` symmetry is load-bearing.** Task 1.4's integration test is the canary. If it fails (now or later), the whole design collapses — scheduled rows won't UPDATE to played rows.
3. **Phase 3 is also load-bearing.** Until the priority column exists, none of the enqueue scripts work correctly (no priority field to set). Get migration applied before Phase 4.
4. **Upsert semantics.** The `on_conflict="team_id_master"` UPSERT depends on the partial unique index. If PostgREST doesn't honor partial indexes for ON CONFLICT, fall back to a SQL function `enqueue_team_request(team_id, priority, request_type)` that does the check-then-insert-or-update logic explicitly.
5. **Open questions** in the spec (timezone, `result` column, new-team hook) get resolved during implementation. Update spec inline.
6. **Branch hygiene.** Spec already on `spec/schedule-driven-scraping`. Each phase ships its own PR; branch from latest main, not from the previous phase.
