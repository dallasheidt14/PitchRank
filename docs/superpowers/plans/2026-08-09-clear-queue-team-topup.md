# Clear Queue Team Top-Up Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `--limit N` on the "Help Clear Queue" action mean "scrape N teams" — drain the `scrape_requests` queue first, then fill the remainder from the teams table — instead of exiting with "Queue is empty" when the queue is short.

**Architecture:** One new pure helper in `scripts/drain_queue.py` calls the existing `get_teams_to_scrape_limited` RPC for the shortfall and de-duplicates against the already-claimed batch. It is wired in immediately after the existing junk filter, so the shortfall is computed from teams that will actually be scraped. Top-up teams carry no `scrape_requests` row, so they flow through the unchanged scrape → import → finalize path without touching queue bookkeeping.

**Tech Stack:** Python 3.11, Supabase (PostgREST via `supabase-py`), pytest, `unittest.mock`, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-08-09-clear-queue-team-topup-design.md`

## Global Constraints

- Worktree: `C:\PitchRank-clearqueue-topup`, branch `feat/clear-queue-team-topup` (already created off `origin/main`). All paths below are relative to that worktree.
- `ruff` config: `line-length = 120`, `target-version = "py311"`, lint rules `["E", "F", "W", "I"]`. Run `ruff check` before every commit.
- Batch every PostgREST `.in_()` query to ≤100 IDs (CLAUDE.md Common Pitfalls #7). No new `.in_()` calls are introduced by this plan.
- Team IDs are UUIDs (strings in Python), never integers.
- Never commit to `main`. Never `git stash`.
- Tests must not hit the network or a real Supabase instance — stub with `unittest.mock.Mock`.
- `tests/conftest.py` has an autouse fixture that resets the module-level GotSport WAF breaker; importing `scripts.drain_queue` pulls in `src.scrapers.gotsport`, which is fine and already handled.

---

### Task 1: `_fetch_topup_teams` helper

The pure function that turns a shortfall into a list of scrapeable team dicts. All the risky logic lives here — RPC parameters, over-fetch padding, overlap removal, truncation, and graceful degradation when the RPC is missing.

**Files:**
- Modify: `scripts/drain_queue.py:29` (add `Set` to the `typing` import)
- Modify: `scripts/drain_queue.py:39` (add `call_rpc_with_fallback` to the existing `src.etl.bulk_ops` import)
- Modify: `scripts/drain_queue.py` (new function after `_fetch_team_metadata`, which ends at line 189)
- Test: `tests/unit/test_drain_queue_topup.py` (create)

**Interfaces:**
- Consumes: `call_rpc_with_fallback(supabase, fn_name, params, *, fallback, limit=200000, log_msg)` from `src/etl/bulk_ops.py:32`. It calls `supabase.rpc(fn_name, params).limit(limit).execute().data`, returns `fallback()` only on SQLSTATE `42883`, and re-raises every other `APIError`.
- Produces: `_fetch_topup_teams(supabase, provider_id: str, shortfall: int, exclude_ids: Set[str]) -> List[Dict]`. Returned dicts have exactly these seven keys: `team_id_master`, `team_name`, `provider_id`, `provider_team_id`, `age_group`, `birth_year`, `last_scraped_at` — the shape `_scrape_team_concurrent` reads.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_drain_queue_topup.py`:

```python
"""Tests for the teams-table top-up that fills out short queue batches."""
import os
import sys
from unittest.mock import Mock

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from postgrest.exceptions import APIError

from scripts.drain_queue import _fetch_topup_teams

TEAM_KEYS = {
    "team_id_master",
    "team_name",
    "provider_id",
    "provider_team_id",
    "age_group",
    "birth_year",
    "last_scraped_at",
}


def _team_row(team_id):
    """A row shaped like SETOF public.teams, with extra columns the helper drops."""
    return {
        "team_id_master": team_id,
        "team_name": f"Team {team_id}",
        "provider_id": "prov-1",
        "provider_team_id": f"pt-{team_id}",
        "age_group": "u12",
        "birth_year": 2014,
        "last_scraped_at": None,
        "state_code": "CA",  # extra column that must not leak through
    }


def _supabase_returning(rows):
    """Mock matching call_rpc_with_fallback's supabase.rpc(...).limit(...).execute().data chain."""
    supabase = Mock()
    supabase.rpc.return_value.limit.return_value.execute.return_value.data = rows
    return supabase


def test_no_rpc_call_when_batch_is_already_full():
    supabase = _supabase_returning([])
    assert _fetch_topup_teams(supabase, "prov-1", 0, {"t-1"}) == []
    assert _fetch_topup_teams(supabase, "prov-1", -5, {"t-1"}) == []
    supabase.rpc.assert_not_called()


def test_requests_shortfall_padded_by_exclusion_count():
    """920 claimed, 300 survive filtering, limit 4000 -> shortfall 3700, p_limit 4000."""
    supabase = _supabase_returning([])
    _fetch_topup_teams(supabase, "prov-1", 3700, {f"t-{i}" for i in range(300)})

    fn_name, params = supabase.rpc.call_args.args
    assert fn_name == "get_teams_to_scrape_limited"
    assert params["p_limit"] == 4000
    assert params["p_provider_id"] == "prov-1"
    assert params["p_include_recent"] is False
    assert params["p_null_only"] is False
    assert params["p_shard_index"] == 0
    assert params["p_shard_count"] == 1


def test_drops_overlap_with_claimed_batch_and_truncates_to_shortfall():
    supabase = _supabase_returning([_team_row(f"t-{i}") for i in range(5)])
    result = _fetch_topup_teams(supabase, "prov-1", 2, {"t-0", "t-1"})
    assert [t["team_id_master"] for t in result] == ["t-2", "t-3"]


def test_preserves_rpc_order():
    """The RPC orders last_scraped_at ASC NULLS FIRST; the helper must not reorder."""
    supabase = _supabase_returning([_team_row("t-9"), _team_row("t-4"), _team_row("t-7")])
    result = _fetch_topup_teams(supabase, "prov-1", 3, set())
    assert [t["team_id_master"] for t in result] == ["t-9", "t-4", "t-7"]


def test_returns_fewer_than_shortfall_when_supply_is_short():
    supabase = _supabase_returning([_team_row("t-0")])
    assert len(_fetch_topup_teams(supabase, "prov-1", 10, set())) == 1


def test_skips_rows_with_no_team_id_master():
    rows = [_team_row("t-0"), {**_team_row("t-1"), "team_id_master": None}, _team_row("t-2")]
    supabase = _supabase_returning(rows)
    result = _fetch_topup_teams(supabase, "prov-1", 5, set())
    assert [t["team_id_master"] for t in result] == ["t-0", "t-2"]


def test_returns_only_the_keys_the_scrape_path_reads():
    supabase = _supabase_returning([_team_row("t-0")])
    (team,) = _fetch_topup_teams(supabase, "prov-1", 1, set())
    assert set(team) == TEAM_KEYS


def test_missing_rpc_degrades_to_queue_only():
    """Rolling deploy where the migration has not landed must not crash a drain."""
    supabase = Mock()
    supabase.rpc.return_value.limit.return_value.execute.side_effect = APIError(
        {"code": "42883", "message": "function does not exist", "hint": "", "details": ""}
    )
    assert _fetch_topup_teams(supabase, "prov-1", 100, set()) == []


def test_other_api_errors_propagate():
    """Only 42883 is survivable; a real DB fault must not be silently swallowed."""
    supabase = Mock()
    supabase.rpc.return_value.limit.return_value.execute.side_effect = APIError(
        {"code": "42P01", "message": "relation does not exist", "hint": "", "details": ""}
    )
    try:
        _fetch_topup_teams(supabase, "prov-1", 100, set())
    except APIError:
        return
    raise AssertionError("expected APIError to propagate")


def test_none_data_is_treated_as_empty():
    """PostgREST can return data=None; the helper must not raise on it."""
    assert _fetch_topup_teams(_supabase_returning(None), "prov-1", 5, set()) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd C:/PitchRank-clearqueue-topup && python -m pytest tests/unit/test_drain_queue_topup.py -v`
Expected: collection error — `ImportError: cannot import name '_fetch_topup_teams' from 'scripts.drain_queue'`

- [ ] **Step 3: Widen the two imports**

In `scripts/drain_queue.py:29`, add `Set`:

```python
from typing import Any, Dict, List, Optional, Set, Tuple
```

In `scripts/drain_queue.py:39`, add `call_rpc_with_fallback`:

```python
from src.etl.bulk_ops import bulk_update_last_scraped_at, call_rpc_with_fallback
```

- [ ] **Step 4: Write the helper**

Insert after `_fetch_team_metadata` (which ends at line 189), before the `_finalize_queue_items` block comment:

```python
def _fetch_topup_teams(
    supabase,
    provider_id: str,
    shortfall: int,
    exclude_ids: Set[str],
) -> List[Dict]:
    """Pull oldest-scraped eligible teams to fill out a short queue batch.

    ``--limit`` is a total scrape target, not a claim count. The queue is
    usually shallower than the requested batch, and the placeholder/age filters
    drop a large share of what it does hold, so without this the operator gets
    a fraction of the batch they asked for.

    ``get_teams_to_scrape_limited`` applies the same eligibility rules in SQL
    (provider, U8/U9, out-of-range birth years, placeholder ``unknown_*``) and
    orders ``last_scraped_at ASC NULLS FIRST``, so these rows need no further
    Python filtering. ``p_include_recent=False`` skips anything scraped in the
    last 7 days, which is what lets consecutive runs walk the backlog instead
    of re-scraping the same teams.

    Over-fetches by ``len(exclude_ids)`` to cover the worst case where every
    claimed queue team is also top-up-eligible and comes back in the result.
    """
    if shortfall <= 0:
        return []

    rows = (
        call_rpc_with_fallback(
            supabase,
            "get_teams_to_scrape_limited",
            {
                "p_provider_id": provider_id,
                "p_limit": shortfall + len(exclude_ids),
                "p_shard_index": 0,
                "p_shard_count": 1,
                "p_include_recent": False,
                "p_null_only": False,
            },
            fallback=lambda: [],
            log_msg="get_teams_to_scrape_limited missing, skipping top-up: %s",
        )
        or []
    )

    topup: List[Dict] = []
    for row in rows:
        team_id_master = row.get("team_id_master")
        if not team_id_master or team_id_master in exclude_ids:
            continue
        topup.append(
            {
                "team_id_master": team_id_master,
                "team_name": row.get("team_name"),
                "provider_id": row.get("provider_id"),
                "provider_team_id": row.get("provider_team_id"),
                "age_group": row.get("age_group"),
                "birth_year": row.get("birth_year"),
                "last_scraped_at": row.get("last_scraped_at"),
            }
        )
        if len(topup) >= shortfall:
            break

    return topup
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd C:/PitchRank-clearqueue-topup && python -m pytest tests/unit/test_drain_queue_topup.py -v`
Expected: 10 passed

- [ ] **Step 6: Lint**

Run: `cd C:/PitchRank-clearqueue-topup && ruff check scripts/drain_queue.py tests/unit/test_drain_queue_topup.py`
Expected: `All checks passed!`

- [ ] **Step 7: Commit**

```bash
cd C:/PitchRank-clearqueue-topup
git add scripts/drain_queue.py tests/unit/test_drain_queue_topup.py
git commit -m "feat(drain-queue): add teams-table top-up helper

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016Af8mR2feo3iCzSKjm4bsA"
```

---

### Task 2: Wire the top-up into `drain_queue()`

Three edits to the orchestrator: stop bailing out on an empty queue, call the helper after the junk filter, and move the dry-run preview below the top-up so it shows what would actually be scraped.

**Files:**
- Modify: `scripts/drain_queue.py:402-406` (empty-queue early return)
- Modify: `scripts/drain_queue.py:438-458` (dry-run block — moved, not edited in place)
- Modify: `scripts/drain_queue.py:488-492` (top-up call site, after the filter loop)
- Test: `tests/unit/test_drain_queue_topup.py` (append)

> **Line numbers above are for the file as it stands at the start of this task.** Task 1 added ~55 lines near the top, and Step 4 below deletes 21 lines in the middle — so every number shifts as you go. Locate each edit by the quoted surrounding code, not by line number.

**Interfaces:**
- Consumes: `_fetch_topup_teams(supabase, provider_id, shortfall, exclude_ids)` from Task 1; `_finalize_queue_items(supabase, queue_map, log_buffer)` at `scripts/drain_queue.py:192` (unchanged).
- Produces: no new callable surface. `drain_queue()` keeps its existing signature `(limit=2000, concurrency=30, dry_run=False, output_file=None)`.

**Why `_finalize_queue_items` needs no change:** `queue_map` is built only from `claimed` (lines 409-415), before the top-up runs, so top-up teams are never keys in it. `_finalize_queue_items` iterates `queue_map.items()`, so it can only ever update rows that were really claimed. Step 1 below pins that behavior with a test, because a regression here would try to complete a `scrape_requests` row that does not exist.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_drain_queue_topup.py`:

```python
def test_finalize_only_touches_claimed_queue_rows():
    """Top-up teams land in log_buffer but have no scrape_requests row.

    _finalize_queue_items iterates queue_map, which is built from claimed items
    only — so a top-up team must never produce an update.
    """
    from scripts.drain_queue import _finalize_queue_items

    supabase = Mock()
    queue_map = {"t-queue": "req-1"}
    log_buffer = [
        {"team_id_master": "t-queue", "games_found": 3, "status": "success"},
        {"team_id_master": "t-topup", "games_found": 7, "status": "success"},
    ]

    _finalize_queue_items(supabase, queue_map, log_buffer)

    eq_calls = supabase.table.return_value.update.return_value.eq.call_args_list
    assert [c.args for c in eq_calls] == [("id", "req-1")]
    supabase.table.return_value.update.return_value.in_.assert_not_called()
```

- [ ] **Step 2: Run test to verify it passes as-is**

Run: `cd C:/PitchRank-clearqueue-topup && python -m pytest tests/unit/test_drain_queue_topup.py::test_finalize_only_touches_claimed_queue_rows -v`
Expected: PASS

This is a characterization test — it pins behavior that already holds, so it passes before the Task 2 edits. Its value is that it fails if a later change starts feeding top-up teams into `queue_map`. If it fails now, stop: the assumption above is wrong and the top-up would corrupt queue state.

- [ ] **Step 3: Replace the empty-queue early return**

At `scripts/drain_queue.py:402-406`, replace:

```python
    if not claimed:
        console.print("[green]Queue is empty — nothing to drain.[/green]")
        return

    console.print(f"[cyan]Claimed {len(claimed)} items from scrape_requests queue[/cyan]")
```

with:

```python
    if claimed:
        console.print(f"[cyan]Claimed {len(claimed)} items from scrape_requests queue[/cyan]")
    else:
        console.print("[yellow]Queue is empty — filling the batch from the teams table[/yellow]")
```

The code between here and the filter loop is already empty-safe: `queue_map` and `team_id_masters` stay empty, `_fetch_team_metadata(supabase, [])` iterates `range(0, 0, 200)` and returns `{}`, and the `teams` comprehension over `claimed` produces `[]`.

- [ ] **Step 4: Cut the dry-run block out of its current position**

Delete `scripts/drain_queue.py:438-458` entirely — the whole `if dry_run:` block through its `return`. It is re-inserted in Step 6 below the top-up. Do not edit it in place; moving it is the point.

- [ ] **Step 5: Add the top-up call site**

After the filter loop's two count prints (`scripts/drain_queue.py:489-492`, ending with the "Filtered out N out-of-range teams" print) and before the `Scraping games for` banner, insert:

```python
    # --limit is a total scrape target, not a claim count. The queue is usually
    # shallower than the requested batch, and the filters above drop a large
    # share of what it does hold — a 500-item claim on 2026-08-04 left 104
    # teams. Top up from the teams table so the operator gets the batch size
    # they asked for.
    queue_team_count = len(teams)
    shortfall = limit - queue_team_count
    if shortfall > 0:
        topup = _fetch_topup_teams(
            supabase,
            provider_id,
            shortfall,
            {t["team_id_master"] for t in teams if t.get("team_id_master")},
        )
        if topup:
            console.print(
                f"[cyan]Topping up with {len(topup):,} teams from the teams table "
                f"(oldest-scraped first)[/cyan]"
            )
            teams.extend(topup)
        else:
            console.print("[yellow]No eligible teams available to top up the batch[/yellow]")
```

- [ ] **Step 6: Re-insert the dry-run block below the top-up**

Immediately after the block from Step 5, insert:

```python
    if dry_run:
        topup_count = len(teams) - queue_team_count
        console.print(f"\n[yellow][DRY RUN] Would scrape {len(teams)} teams:[/yellow]")
        console.print(
            f"[dim]  {queue_team_count} from the queue, {topup_count} topped up from the teams table[/dim]"
        )
        for t in teams[:20]:
            console.print(f"  {t['provider_team_id']} — {t['team_name']}")
        if len(teams) > 20:
            console.print(f"  ... and {len(teams) - 20} more")
        # Release claimed items back to pending. Top-up teams have no queue row.
        ids = list(queue_map.values())
        for i in range(0, len(ids), 100):
            batch = ids[i : i + 100]
            try:
                (
                    supabase.table("scrape_requests")
                    .update({"status": "pending", "processed_at": None})
                    .in_("id", batch)
                    .execute()
                )
            except Exception:
                pass
        console.print("[yellow]Released claimed items back to pending[/yellow]")
        return
```

Everything the dry-run path now runs ahead of itself — the filter loop and one `get_teams_to_scrape_limited` call — is read-only against Supabase, so `--dry-run` still writes nothing except releasing claimed rows back to `pending`.

- [ ] **Step 7: Run the full unit test file and lint**

Run: `cd C:/PitchRank-clearqueue-topup && python -m pytest tests/unit/test_drain_queue_topup.py -v && ruff check scripts/drain_queue.py`
Expected: 11 passed, `All checks passed!`

- [ ] **Step 8: Verify the module still imports and the flow reads correctly**

Run: `cd C:/PitchRank-clearqueue-topup && python -c "import scripts.drain_queue as d; print(d._fetch_topup_teams.__name__)"`
Expected: `_fetch_topup_teams`

Then read `scripts/drain_queue.py` from the claim call to the `Scraping games for` banner and confirm the order is: claim → queue_map → metadata → build teams → filter → top-up → dry-run → banner.

- [ ] **Step 9: Commit**

```bash
cd C:/PitchRank-clearqueue-topup
git add scripts/drain_queue.py tests/unit/test_drain_queue_topup.py
git commit -m "feat(drain-queue): top up short batches from the teams table

--limit now means total teams to scrape. Drops the empty-queue early
return and moves the dry-run preview below the top-up so it shows what
would actually be scraped.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016Af8mR2feo3iCzSKjm4bsA"
```

---

### Task 3: Workflow input docs and ZenRows concurrency default

Config-only change to the dispatch form. Reviewable independently of the Python: an operator could accept the top-up behavior and reject the concurrency bump, or vice versa.

**Files:**
- Modify: `.github/workflows/clear-queue.yml:2-7` (run-name wording)
- Modify: `.github/workflows/clear-queue.yml:12-16` (`queue_limit` description)
- Modify: `.github/workflows/clear-queue.yml:67-72` (ZenRows concurrency default)

**Interfaces:**
- Consumes: nothing from Tasks 1-2 at the YAML level; the built command string is unchanged in shape (`python scripts/drain_queue.py --limit <int> --concurrency <int>`).
- Produces: no new inputs. The four existing `workflow_dispatch` inputs keep their names and types.

- [ ] **Step 1: Update the run-name**

`--limit` now counts teams, not queue items. Replace `.github/workflows/clear-queue.yml:2-7`:

```yaml
run-name: >-
  Clear Queue · ${{
    format('{0} items', inputs.queue_limit || '2000')
  }}${{
    inputs.use_zenrows == true && ' · ZenRows' || ''
  }}
```

with:

```yaml
run-name: >-
  Clear Queue · ${{
    format('{0} teams', inputs.queue_limit || '2000')
  }}${{
    inputs.use_zenrows == true && ' · ZenRows' || ''
  }}
```

- [ ] **Step 2: Rewrite the `queue_limit` description**

Replace the `description:` line at `.github/workflows/clear-queue.yml:13`:

```yaml
        description: 'Number of queue items to claim and process (default 2000). Safe to dispatch multiple runs — each claims its own batch via FOR UPDATE SKIP LOCKED.'
```

with:

```yaml
        description: 'Total teams to scrape (default 2000). Drains the scrape_requests queue first, then tops up from the teams table (oldest-scraped first, skipping anything scraped in the last 7 days). Queue claims use FOR UPDATE SKIP LOCKED so parallel dispatches split the queue safely — the top-up does NOT, so run one at a time when the queue is short.'
```

- [ ] **Step 3: Raise the ZenRows concurrency default**

Replace `.github/workflows/clear-queue.yml:67-72`:

```bash
          # Concurrency: 8 with ZenRows (shared 50-slot ceiling), 30 without
          if [[ "${USE_ZENROWS:-false}" == "true" ]]; then
            CONCURRENCY=8
          else
            CONCURRENCY=30
          fi
```

with:

```bash
          # Concurrency: 20 with ZenRows, 30 without.
          #
          # ZenRows: 20, not the 8 used by scrape-games.yml. That 8 exists
          # because scrape-games runs 5 shards through one ZenRows API key
          # (5 x 8 = 40, under the Startup-tier 50-slot parallel ceiling).
          # This workflow is a single runner, so one run at 20 is 40% of the
          # cap.
          #
          # Sizing: run 27104427792 (2026-06-07) scraped 4984 teams in 45m06s
          # at concurrency 10 — 1.84 teams/sec. Now that --limit is a total
          # scrape target, a 20,000-team batch is reachable, and at that rate
          # it needs ~181 min of scraping alone — past the 180-min
          # timeout-minutes below. A killed run never reaches auto-import, so
          # every game it scraped is lost to Supabase. 20 roughly halves the
          # scrape to ~75 min.
          if [[ "${USE_ZENROWS:-false}" == "true" ]]; then
            CONCURRENCY=20
          else
            CONCURRENCY=30
          fi
```

Leave the non-ZenRows `30` alone. It is 3x the per-IP WAF limit documented at `scrape-games.yml:306-320` and should be lowered, but that is a pre-existing bug unrelated to this feature and belongs in its own change.

- [ ] **Step 4: Validate the YAML parses**

Run: `cd C:/PitchRank-clearqueue-topup && python -c "import yaml; d=yaml.safe_load(open('.github/workflows/clear-queue.yml')); print(sorted(d[True]['workflow_dispatch']['inputs']))"`
Expected: `['concurrency', 'queue_limit', 'use_zenrows', 'zenrows_premium_proxy']`

(`d[True]` is not a typo — PyYAML parses the bare `on:` key as boolean `True`.)

- [ ] **Step 5: Verify the built command still has the right shape**

Run:

```bash
cd C:/PitchRank-clearqueue-topup
QUEUE_LIMIT=4000 USE_ZENROWS=true CONCURRENCY_INPUT='' bash -c '
CMD="python scripts/drain_queue.py"
if [[ "$QUEUE_LIMIT" =~ ^[0-9]+$ ]]; then CMD="$CMD --limit $QUEUE_LIMIT"; else CMD="$CMD --limit 2000"; fi
if [[ "${USE_ZENROWS:-false}" == "true" ]]; then CONCURRENCY=20; else CONCURRENCY=30; fi
if [[ "$CONCURRENCY_INPUT" =~ ^[0-9]+$ ]]; then CONCURRENCY="$CONCURRENCY_INPUT"; fi
echo "$CMD --concurrency $CONCURRENCY"'
```

Expected: `python scripts/drain_queue.py --limit 4000 --concurrency 20`

- [ ] **Step 6: Commit**

```bash
cd C:/PitchRank-clearqueue-topup
git add .github/workflows/clear-queue.yml
git commit -m "chore(clear-queue): document limit as a scrape target, raise ZenRows concurrency to 20

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016Af8mR2feo3iCzSKjm4bsA"
```

---

### Task 4: End-to-end dry-run against production

The call site's shortfall arithmetic and the moved dry-run block are not covered by unit tests — driving `drain_queue()` would require stubbing the scraper, the progress bar, the output file, and the auto-import subprocess. A `--dry-run` against the real database exercises all of it for the cost of one command and writes nothing except releasing the rows it claimed.

**Files:**
- Modify: none.

**Interfaces:**
- Consumes: the complete Task 1-3 implementation.
- Produces: nothing. Verification only.

- [ ] **Step 1: Record the pre-run queue depth**

This step replaces spec test case 8 ("Dry-run"), which the spec listed as a unit test. It is verified here instead because driving `drain_queue()` far enough to reach the dry-run block requires stubbing the scraper, the progress bar, the output file handle, and the auto-import subprocess — more mock surface than the behavior is worth.

Run from the main checkout (the worktree has no `.env.local`):

```bash
cd C:/PitchRank && python -c "
import os
from dotenv import load_dotenv
load_dotenv('.env.local'); load_dotenv('.env')
from supabase import create_client
sb = create_client(os.getenv('SUPABASE_URL'), os.getenv('SUPABASE_SERVICE_ROLE_KEY') or os.getenv('SUPABASE_SERVICE_KEY'))
for s in ['pending','processing']:
    print(s, sb.table('scrape_requests').select('id', count='exact').eq('status', s).limit(1).execute().count)
"
```

Write down both numbers.

- [ ] **Step 2: Dry-run with a limit larger than the queue**

Run in the worktree, borrowing the main checkout's credentials:

```bash
cd C:/PitchRank-clearqueue-topup
cp C:/PitchRank/.env.local .env.local
python scripts/drain_queue.py --dry-run --limit 50
```

Expected output contains, in order:
- `Claimed N items from scrape_requests queue` (or `Queue is empty — filling the batch from the teams table`)
- `Topping up with M teams from the teams table (oldest-scraped first)`
- `[DRY RUN] Would scrape 50 teams:` — the total must equal exactly 50
- `  N from the queue, M topped up from the teams table` where `N + M == 50`
- 20 team lines, then `... and 30 more`
- `Released claimed items back to pending`

- [ ] **Step 3: Confirm nothing was left claimed**

Re-run the Step 1 query. Expected: both counts match the pre-run values exactly. A raised `processing` count means the release path failed — stop and investigate before proceeding.

- [ ] **Step 4: Dry-run with a limit smaller than the queue**

```bash
cd C:/PitchRank-clearqueue-topup && python scripts/drain_queue.py --dry-run --limit 5
```

Expected: `Would scrape 5 teams`, with no `Topping up` line (queue alone covers it, so `shortfall <= 0` and the RPC is never called). Re-run the Step 1 query and confirm the counts are unchanged again.

- [ ] **Step 5: Remove the copied env file**

```bash
cd C:/PitchRank-clearqueue-topup && rm -f .env.local
```

`.env.local` is gitignored, but leaving credentials in a scratch worktree is careless. Confirm with `git status --short` that the worktree is clean.

---

## Post-implementation

Run `/finalize` per the project's session-workflow rule, then open a PR from `feat/clear-queue-team-topup`. After the PR merges, clean up:

```bash
cd C:/PitchRank
git worktree remove C:/PitchRank-clearqueue-topup
git branch -D feat/clear-queue-team-topup
```

Deleting the remote branch requires explicit user approval.
