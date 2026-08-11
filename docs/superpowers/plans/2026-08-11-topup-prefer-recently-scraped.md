# Top-up Prefer Recently-Scraped Teams Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the "Help Clear Queue" top-up select teams scraped 14+ days ago, most-recent first, instead of the stalest teams first — raising the share of actively-playing teams in a batch from 5.6% to ~99%.

**Architecture:** Replace the `get_teams_to_scrape_limited` RPC call inside `_fetch_topup_teams` with a direct paged PostgREST query against `teams`, ordered `last_scraped_at DESC`. The two eligibility rules PostgREST cannot express (placeholder teams, lowercase `age_group`) are handled by extracting the existing inline Python filter into a shared `_is_scrapeable_team` helper used by both team sources.

**Tech Stack:** Python 3.11, `supabase-py` / PostgREST, pytest, `unittest.mock`.

**Spec:** `docs/superpowers/specs/2026-08-11-topup-prefer-recently-scraped-design.md`

## Global Constraints

- Worktree: `C:\PitchRank-clearqueue-topup`, branch `feat/topup-prefer-recently-scraped` (already created off the merged `origin/main`). All paths are relative to that worktree.
- **No database changes.** No migration, no new or altered RPC. `get_teams_to_scrape_limited` must be left exactly as it is, because `scripts/scrape_games.py` also calls it.
- Only two files may change: `scripts/drain_queue.py` and `tests/unit/test_drain_queue_topup.py`.
- `ruff` config: `line-length = 120`, `target-version = "py311"`, lint rules `["E", "F", "W", "I"]`. A pre-commit hook runs `ruff --fix` on `scripts/` files and will reformat and re-stage; re-read files after committing to confirm edits persisted.
- PostgREST returns at most 1,000 rows per request. Page with `.range()`.
- Tests must not hit the network or a real Supabase instance — stub with `unittest.mock.Mock`.
- Team IDs are UUIDs (strings in Python), never integers.
- Never commit to `main`. Never `git stash`.

---

### Task 1: Extract the eligibility filter into a shared helper

The U8/U9 and birth-year checks live inline in `drain_queue()`'s filter loop. Task 2 needs the same rules for top-up rows. Extract them first so there is one implementation rather than two that can drift.

**Files:**
- Modify: `scripts/drain_queue.py` (new helpers after `_is_placeholder_unknown_team`, which ends at line 77; rewire the filter loop at lines 549-576)
- Test: `tests/unit/test_drain_queue_topup.py` (append)

**Interfaces:**
- Consumes: `_is_placeholder_unknown_team(team: Dict) -> bool` at `scripts/drain_queue.py:69`.
- Produces:
  - `_excluded_birth_years(today: Optional[date] = None) -> List[int]`
  - `_is_scrapeable_team(team: Dict) -> bool`
  - `_EXCLUDED_AGE_GROUPS: Tuple[str, ...]`

**Two intentional behavior changes, both improvements — do not "fix" them back:**

1. The current loop hardcodes `birth_year in [2005, 2006, 2017, 2018, 2019]`. The SQL side computes the same list dynamically as `extract(year from now())` minus `(21, 20, 9, 8, 7)`. Verified 2026-08-11: for 2026 the dynamic list is exactly `[2005, 2006, 2017, 2018, 2019]`, so **this year the behavior is identical**. From 2027 the hardcoded list would be wrong while the SQL rolls over. The helper computes it dynamically.
2. The current loop reads `team.get("age_group", "").upper()`, which raises `AttributeError` when the key exists with a `None` value (the default only applies to a *missing* key). The helper uses `(team.get("age_group") or "")`, which handles both.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_drain_queue_topup.py`:

```python
def test_excluded_birth_years_is_dynamic():
    """Mirrors the SQL side's extract(year from now()) minus (21,20,9,8,7)."""
    import datetime as _dt

    from scripts.drain_queue import _excluded_birth_years

    assert _excluded_birth_years(_dt.date(2026, 8, 11)) == [2005, 2006, 2017, 2018, 2019]
    assert _excluded_birth_years(_dt.date(2027, 1, 1)) == [2006, 2007, 2018, 2019, 2020]
    # Defaults to today rather than a frozen list.
    assert _excluded_birth_years() == _excluded_birth_years(_dt.date.today())


def test_is_scrapeable_team_accepts_a_normal_team():
    from scripts.drain_queue import _is_scrapeable_team

    assert _is_scrapeable_team(
        {"team_name": "Real Team", "provider_team_id": "123", "age_group": "u12", "birth_year": 2014}
    )


def test_is_scrapeable_team_rejects_placeholder():
    from scripts.drain_queue import _is_scrapeable_team

    assert not _is_scrapeable_team(
        {"team_name": "unknown_123", "provider_team_id": "123", "age_group": "u12", "birth_year": 2014}
    )


def test_is_scrapeable_team_rejects_u8_and_u9_any_case():
    """age_group is stored lowercase but the SQL compares upper(trim(...))."""
    from scripts.drain_queue import _is_scrapeable_team

    for ag in ("u8", "U8", " u-9 ", "U-8", "u9"):
        assert not _is_scrapeable_team(
            {"team_name": "T", "provider_team_id": "1", "age_group": ag, "birth_year": 2014}
        ), ag


def test_is_scrapeable_team_rejects_out_of_range_birth_year():
    import datetime as _dt

    from scripts.drain_queue import _excluded_birth_years, _is_scrapeable_team

    for by in _excluded_birth_years(_dt.date.today()):
        assert not _is_scrapeable_team(
            {"team_name": "T", "provider_team_id": "1", "age_group": "u12", "birth_year": by}
        ), by


def test_is_scrapeable_team_tolerates_null_age_and_birth_year():
    """A None age_group must not raise — .get(k, "") only defaults a MISSING key."""
    from scripts.drain_queue import _is_scrapeable_team

    assert _is_scrapeable_team(
        {"team_name": "T", "provider_team_id": "1", "age_group": None, "birth_year": None}
    )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd C:/PitchRank-clearqueue-topup && python -m pytest tests/unit/test_drain_queue_topup.py -q`
Expected: collection error — `ImportError: cannot import name '_excluded_birth_years' from 'scripts.drain_queue'`

- [ ] **Step 3: Add `date` to the datetime import**

`scripts/drain_queue.py:29` currently reads `from datetime import datetime`. This task needs `date`:

```python
from datetime import date, datetime
```

Do **not** add `timedelta` here. Task 2 needs it, but importing it now leaves it unused until then and this task's `ruff` check would fail on F401.

- [ ] **Step 4: Add the helpers**

Insert immediately after `_is_placeholder_unknown_team` (ends at line 77), before the next section banner:

```python
_EXCLUDED_AGE_GROUPS = ("U8", "U-8", "U9", "U-9")


def _excluded_birth_years(today: Optional[date] = None) -> List[int]:
    """Birth years outside PitchRank's U10-U19 range for the current season.

    Mirrors the list the SQL side computes as ``extract(year from now())``
    minus (21, 20, 9, 8, 7): the U20/U21 old end and the U7/U8/U9 young end.
    Computed rather than hardcoded so it rolls over on Jan 1 like the SQL does.
    """
    yr = (today or date.today()).year
    return [yr - 21, yr - 20, yr - 9, yr - 8, yr - 7]


def _is_scrapeable_team(team: Dict) -> bool:
    """True when a team passes PitchRank's scrape-eligibility rules.

    Both team sources run through this — claimed queue rows and teams-table
    top-ups — so the two cannot diverge. The placeholder rule compares two
    columns and ``age_group`` is stored lowercase but compared uppercase, so
    neither is expressible as a PostgREST filter and both must be applied here.
    """
    if _is_placeholder_unknown_team(team):
        return False
    if (team.get("age_group") or "").upper().strip() in _EXCLUDED_AGE_GROUPS:
        return False
    if team.get("birth_year") in _excluded_birth_years():
        return False
    return True
```

- [ ] **Step 5: Rewire the filter loop to use the helper**

Replace the loop body at `scripts/drain_queue.py:555-576` (from `for team in teams:` through `filtered_teams.append(team)`) with:

```python
        for team in teams:
            if _is_scrapeable_team(team):
                filtered_teams.append(team)
                continue
            if _is_placeholder_unknown_team(team):
                logger.debug(f"Skipping placeholder unknown team: {team.get('team_name', 'Unknown')}")
                placeholder_unknown_count += 1
            else:
                logger.debug(f"Skipping out-of-range team: {team.get('team_name', 'Unknown')}")
                skipped_count += 1
```

The two counters and their console messages are unchanged, so the run output keeps the same shape.

- [ ] **Step 6: Run tests and lint**

Run: `cd C:/PitchRank-clearqueue-topup && python -m pytest tests/unit/test_drain_queue_topup.py -q && python -m ruff check scripts/drain_queue.py tests/unit/test_drain_queue_topup.py`
Expected: 22 passed, `All checks passed!`

- [ ] **Step 7: Commit**

```bash
cd C:/PitchRank-clearqueue-topup
git add scripts/drain_queue.py tests/unit/test_drain_queue_topup.py
git commit -m "refactor(drain-queue): extract _is_scrapeable_team from the filter loop

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016Af8mR2feo3iCzSKjm4bsA"
```

---

### Task 2: Query teams directly, most-recently-scraped first

**Files:**
- Modify: `scripts/drain_queue.py:199-262` (replace `_fetch_topup_teams` entirely)
- Modify: `scripts/drain_queue.py:39` (drop the now-unused `call_rpc_with_fallback` import)
- Test: `tests/unit/test_drain_queue_topup.py` (rewrite the RPC-era tests)

**Interfaces:**
- Consumes: `_is_scrapeable_team(team: Dict) -> bool` and `_excluded_birth_years(today=None) -> List[int]` from Task 1.
- Produces: `_fetch_topup_teams(supabase, provider_id: str, shortfall: int, exclude_ids: Set[str]) -> List[Dict]` — signature unchanged, so the call site at `drain_queue.py:~560` needs no edit. Returned dicts carry exactly the seven keys in `_TEAM_KEYS`.

**Query shape, verified live against production 2026-08-11** (1,000 rows returned, ordering confirmed descending, all seven keys present, 99.2% of the result active within 90 days):

```
teams
  where provider_id = <gotsport>
    and last_scraped_at < now() - 14 days
    and (birth_year is null or birth_year not in (<dynamic list>))
  order by last_scraped_at desc
```

- [ ] **Step 1: Rewrite the tests**

In `tests/unit/test_drain_queue_topup.py`, **delete exactly these two tests** — they assert RPC mechanics that have no analogue in a table query:

- `test_requests_shortfall_padded_by_exclusion_count` (asserts `p_limit`; the over-fetch padding is replaced by paging)
- `test_missing_rpc_degrades_to_queue_only` (SQLSTATE 42883 means "function does not exist"; `teams` always exists)

**Rename** `test_other_api_errors_propagate` to `test_postgrest_errors_propagate` and replace its body with the version given below.

**Keep every other test unchanged.** Six of them (`test_no_rpc_call_when_batch_is_already_full`, `test_drops_overlap_with_claimed_batch_and_truncates_to_shortfall`, `test_preserves_rpc_order`, `test_returns_fewer_than_shortfall_when_supply_is_short`, `test_skips_rows_with_no_team_id_master`, `test_returns_only_the_keys_the_scrape_path_reads`) assert behavior that still holds — dedup, truncation, order preservation, key projection, short supply, null-id skipping — and they all call `_supabase_returning`. **Do not delete that helper.** Redefine it as a single-page adapter over the new paging mock so those six keep passing untouched.

Two of the kept tests need one-line edits because they name RPC concepts:

- `test_no_rpc_call_when_batch_is_already_full`: its body asserts `supabase.rpc.assert_not_called()`. Against a table query the meaningful assertion is `supabase.table.assert_not_called()`. Change that one line; keep the test name.
- `test_preserves_rpc_order`: rename to `test_preserves_source_order`. Body unchanged.

Then add the paging mock and the new tests:

```python
def _supabase_paging(pages):
    """Mock the .table().select()...range().execute() chain, one entry per page.

    Each call to .range() returns the next page. `pages` is a list of row lists.
    Records the builder calls so tests can assert on the query that was built.
    """
    supabase = Mock()
    builder = Mock()
    calls = {"eq": [], "lt": [], "or_": [], "order": [], "range": []}

    def _record(name):
        def inner(*args, **kwargs):
            calls[name].append((args, kwargs))
            return builder
        return inner

    supabase.table.return_value.select.return_value = builder
    builder.eq.side_effect = _record("eq")
    builder.lt.side_effect = _record("lt")
    builder.or_.side_effect = _record("or_")
    builder.order.side_effect = _record("order")

    seq = list(pages)

    def _range(*args, **kwargs):
        calls["range"].append((args, kwargs))
        result = Mock()
        result.execute.return_value = Mock(data=seq.pop(0) if seq else [])
        return result

    builder.range.side_effect = _range
    supabase._calls = calls
    return supabase


def _supabase_returning(rows):
    """Single-page adapter so the pre-existing tests keep working unchanged.

    They were written against the RPC's one-shot result; a single page of the
    same rows is the exact equivalent under the paged table query.
    """
    return _supabase_paging([rows if rows is not None else None])


def test_query_uses_14_day_cutoff_provider_and_descending_order():
    import datetime as _dt

    from scripts.drain_queue import _fetch_topup_teams

    supabase = _supabase_paging([[_team_row("t-0")]])
    _fetch_topup_teams(supabase, "prov-1", 1, set())

    c = supabase._calls
    assert c["eq"][0][0] == ("provider_id", "prov-1")
    col, cutoff = c["lt"][0][0]
    assert col == "last_scraped_at"
    delta = _dt.datetime.now() - _dt.datetime.fromisoformat(cutoff)
    assert 13.9 < delta.days + delta.seconds / 86400 < 14.1
    assert c["order"][0][0] == ("last_scraped_at",)
    assert c["order"][0][1] == {"desc": True}


def test_query_excludes_birth_years_dynamically():
    from scripts.drain_queue import _excluded_birth_years, _fetch_topup_teams

    supabase = _supabase_paging([[_team_row("t-0")]])
    _fetch_topup_teams(supabase, "prov-1", 1, set())

    clause = supabase._calls["or_"][0][0][0]
    assert clause.startswith("birth_year.is.null,birth_year.not.in.(")
    for yr in _excluded_birth_years():
        assert str(yr) in clause


def test_pages_until_shortfall_is_satisfied():
    """~40% of fetched rows fail the filter, so one page is often not enough."""
    from scripts.drain_queue import _fetch_topup_teams

    junk = [{**_team_row(f"j-{i}"), "team_name": f"unknown_pt-j-{i}"} for i in range(1000)]
    good = [_team_row(f"g-{i}") for i in range(1000)]
    supabase = _supabase_paging([junk, good])

    result = _fetch_topup_teams(supabase, "prov-1", 5, set())

    assert [t["team_id_master"] for t in result] == [f"g-{i}" for i in range(5)]
    assert len(supabase._calls["range"]) == 2


def test_stops_paging_on_a_short_page():
    """A page smaller than the page size means the source is exhausted."""
    from scripts.drain_queue import _fetch_topup_teams

    supabase = _supabase_paging([[_team_row("t-0")], [_team_row("t-1")]])
    result = _fetch_topup_teams(supabase, "prov-1", 50, set())

    assert [t["team_id_master"] for t in result] == ["t-0"]
    assert len(supabase._calls["range"]) == 1


def test_paging_offsets_advance_by_page_size():
    from scripts.drain_queue import _fetch_topup_teams

    junk = [{**_team_row(f"j-{i}"), "team_name": f"unknown_pt-j-{i}"} for i in range(1000)]
    supabase = _supabase_paging([junk, [_team_row("g-0")]])
    _fetch_topup_teams(supabase, "prov-1", 1, set())

    assert [c[0] for c in supabase._calls["range"]] == [(0, 999), (1000, 1999)]


def test_drops_excluded_ids_and_filtered_rows():
    from scripts.drain_queue import _fetch_topup_teams

    rows = [
        _team_row("t-0"),
        {**_team_row("t-1"), "team_name": "unknown_pt-t-1"},  # placeholder
        {**_team_row("t-2"), "age_group": "u9"},              # out of range
        _team_row("t-3"),
    ]
    supabase = _supabase_paging([rows])
    result = _fetch_topup_teams(supabase, "prov-1", 10, {"t-0"})

    assert [t["team_id_master"] for t in result] == ["t-3"]


def test_postgrest_errors_propagate():
    """Swallowing this would silently return a short batch with no explanation.
    The caller's claim-release guard depends on the exception escaping."""
    from postgrest.exceptions import APIError

    from scripts.drain_queue import _fetch_topup_teams

    supabase = _supabase_paging([[]])
    supabase.table.return_value.select.return_value.eq.side_effect = APIError(
        {"code": "42P01", "message": "boom", "hint": "", "details": ""}
    )
    try:
        _fetch_topup_teams(supabase, "prov-1", 5, set())
    except APIError:
        return
    raise AssertionError("expected APIError to propagate")
```

Also update `_team_row` so its `provider_team_id` matches the placeholder convention the tests rely on:

```python
def _team_row(team_id):
    """A row shaped like a public.teams select, with an extra column to drop."""
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd C:/PitchRank-clearqueue-topup && python -m pytest tests/unit/test_drain_queue_topup.py -q`
Expected: FAIL — the new tests exercise a table query while `_fetch_topup_teams` still calls `supabase.rpc`, so the recorded `eq`/`lt`/`order` call lists are empty and the assertions fail with `IndexError`.

- [ ] **Step 3: Replace `_fetch_topup_teams`**

Replace the whole function at `scripts/drain_queue.py:199-262` with:

```python
_TOPUP_STALE_DAYS = 14
_TOPUP_PAGE_SIZE = 1000
_TEAM_KEYS = (
    "team_id_master",
    "team_name",
    "provider_id",
    "provider_team_id",
    "age_group",
    "birth_year",
    "last_scraped_at",
)


def _fetch_topup_teams(
    supabase,
    provider_id: str,
    shortfall: int,
    exclude_ids: Set[str],
) -> List[Dict]:
    """Pull recently-scraped eligible teams to fill out a short queue batch.

    Ordered ``last_scraped_at`` DESC, skipping anything scraped in the last
    14 days. How recently we scraped a team is a strong proxy for whether it
    is still playing: measured 2026-08-11, teams last scraped 14-75 days ago
    were 80-93% active within 90 days, while teams last scraped 75+ days ago
    were 0-6% active. Actively-playing teams are continuously re-enqueued by
    the daily pipeline so they always carry a recent ``last_scraped_at``; a
    team sinks to the bottom of an ascending sort precisely because nothing
    has had reason to touch it. Ascending order is anti-correlated with
    activity, which is why this reads the column descending.

    Queries ``teams`` directly rather than through
    ``get_teams_to_scrape_limited``: that RPC is shared with scrape_games.py
    and orders ascending, so reversing it there would mean altering a function
    another script depends on.

    Pages until ``shortfall`` teams survive ``_is_scrapeable_team`` — roughly
    40% of fetched rows do not — or the source is exhausted, in which case it
    returns fewer. Never-scraped teams are excluded, since ``last_scraped_at
    < cutoff`` is NULL for them; they carry no activity signal, and
    enqueue_safety_net already routes them through the queue.
    """
    if shortfall <= 0:
        return []

    cutoff = (datetime.now() - timedelta(days=_TOPUP_STALE_DAYS)).isoformat()
    excluded_years = ",".join(str(y) for y in _excluded_birth_years())

    topup: List[Dict] = []
    offset = 0
    while len(topup) < shortfall:
        page = (
            supabase.table("teams")
            .select(",".join(_TEAM_KEYS))
            .eq("provider_id", provider_id)
            .lt("last_scraped_at", cutoff)
            .or_(f"birth_year.is.null,birth_year.not.in.({excluded_years})")
            .order("last_scraped_at", desc=True)
            .range(offset, offset + _TOPUP_PAGE_SIZE - 1)
            .execute()
            .data
        ) or []

        if not page:
            break

        for row in page:
            team_id_master = row.get("team_id_master")
            if not team_id_master or team_id_master in exclude_ids:
                continue
            if not _is_scrapeable_team(row):
                continue
            topup.append({k: row.get(k) for k in _TEAM_KEYS})
            if len(topup) >= shortfall:
                break

        if len(page) < _TOPUP_PAGE_SIZE:
            break
        offset += _TOPUP_PAGE_SIZE

    return topup
```

- [ ] **Step 4: Drop the unused import**

`scripts/drain_queue.py:39` currently reads:

```python
from src.etl.bulk_ops import bulk_update_last_scraped_at, call_rpc_with_fallback
```

`call_rpc_with_fallback` is now unused and `ruff` will fail on F401. Change it to:

```python
from src.etl.bulk_ops import bulk_update_last_scraped_at
```

- [ ] **Step 5: Run tests and lint**

Run: `cd C:/PitchRank-clearqueue-topup && python -m pytest tests/unit/test_drain_queue_topup.py -q && python -m ruff check scripts/drain_queue.py tests/unit/test_drain_queue_topup.py`
Expected: 25 passed, `All checks passed!`

- [ ] **Step 6: Correct the two stale docstrings this change invalidates**

Both name the RPC and both state the old ordering.

In the module docstring near `scripts/drain_queue.py:5-7`, replace:

```
Claims pending items from the scrape_requests queue and scrapes those. When
the queue yields fewer teams than --limit, tops the batch up from the teams
table via get_teams_to_scrape_limited (oldest-scraped first).
```

with:

```
Claims pending items from the scrape_requests queue and scrapes those. When
the queue yields fewer teams than --limit, tops the batch up by querying the
teams table directly for the most-recently-scraped eligible teams, skipping
anything scraped in the last 14 days.
```

In the `drain_queue()` docstring near `scripts/drain_queue.py:482-486`, replace:

```
    Clone of scrape_games() with one change: teams come from the
    scrape_requests queue first, then from the teams table RPC
    (get_teams_to_scrape_limited) to top up the batch when the queue
    falls short of --limit.
```

with:

```
    Clone of scrape_games() with one change: teams come from the
    scrape_requests queue first, then from a direct teams-table query
    (most-recently-scraped first) to top up the batch when the queue
    falls short of --limit.
```

- [ ] **Step 7: Run the whole file once more, then commit**

```bash
cd C:/PitchRank-clearqueue-topup
python -m pytest tests/unit/test_drain_queue_topup.py -q
python -m ruff check scripts/drain_queue.py tests/unit/test_drain_queue_topup.py
git add scripts/drain_queue.py tests/unit/test_drain_queue_topup.py
git commit -m "feat(drain-queue): top up with recently-scraped teams, not the stalest

Queries teams directly, ordered last_scraped_at DESC past a 14-day gate.
Measured 5.6% -> 99.2% of picks active within 90 days.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016Af8mR2feo3iCzSKjm4bsA"
```

---

### Task 3: Verify against production with a dry-run

The ordering and the activity lift are properties of real data; a stubbed test cannot show either. `--dry-run` claims rows, previews the batch, and releases the rows — the only write it performs.

**Files:**
- Modify: none.

**Interfaces:**
- Consumes: the completed Task 1 and Task 2 implementation.
- Produces: nothing. Verification only.

- [ ] **Step 1: Record the baseline queue state**

The worktree already has a tracked `.env.local` with working credentials — do not copy, move, delete, or commit it.

```bash
cd C:/PitchRank-clearqueue-topup && python -c "
import os
from dotenv import load_dotenv
load_dotenv('.env.local'); load_dotenv('.env')
from supabase import create_client
sb = create_client(os.getenv('SUPABASE_URL'), os.getenv('SUPABASE_SERVICE_ROLE_KEY') or os.getenv('SUPABASE_SERVICE_KEY'))
for s in ['pending','processing']:
    print(s, sb.table('scrape_requests').select('id', count='exact').eq('status', s).limit(1).execute().count)
"
```

Write both numbers down. The `processing` count is the leak indicator.

- [ ] **Step 2: Dry-run 200 teams**

```bash
cd C:/PitchRank-clearqueue-topup && python scripts/drain_queue.py --dry-run --limit 200
```

Expected: a `Topping up with N teams` line, `[DRY RUN] Would scrape 200 teams:`, a queue/top-up split summing to 200, and `Released claimed items back to pending`.

- [ ] **Step 3: Confirm nothing leaked**

Re-run the Step 1 query. Both counts must match the baseline. A raised `processing` count means a claim leaked — stop and report rather than retrying.

- [ ] **Step 4: Confirm the ordering actually flipped**

```bash
cd C:/PitchRank-clearqueue-topup && python -c "
import os
from dotenv import load_dotenv
load_dotenv('.env.local'); load_dotenv('.env')
from supabase import create_client
from scripts.drain_queue import _fetch_topup_teams
sb = create_client(os.getenv('SUPABASE_URL'), os.getenv('SUPABASE_SERVICE_ROLE_KEY') or os.getenv('SUPABASE_SERVICE_KEY'))
pid = sb.table('providers').select('id').eq('code','gotsport').single().execute().data['id']
teams = _fetch_topup_teams(sb, pid, 200, set())
ds = [t['last_scraped_at'][:10] for t in teams if t['last_scraped_at']]
print('returned', len(teams), 'newest', ds[0], 'oldest', ds[-1])
print('descending?', all(ds[i] >= ds[i+1] for i in range(len(ds)-1)))
"
```

Expected: 200 teams, descending, newest roughly 14 days ago. If the newest is months old, the ordering did not flip.

- [ ] **Step 5: Measure the activity lift**

```bash
cd C:/PitchRank-clearqueue-topup && python -c "
import os, datetime
from dotenv import load_dotenv
load_dotenv('.env.local'); load_dotenv('.env')
from supabase import create_client
from scripts.drain_queue import _fetch_topup_teams
sb = create_client(os.getenv('SUPABASE_URL'), os.getenv('SUPABASE_SERVICE_ROLE_KEY') or os.getenv('SUPABASE_SERVICE_KEY'))
pid = sb.table('providers').select('id').eq('code','gotsport').single().execute().data['id']
ids = [t['team_id_master'] for t in _fetch_topup_teams(sb, pid, 600, set())]
cut = (datetime.date.today() - datetime.timedelta(days=90)).isoformat()
act = set()
for i in range(0, len(ids), 100):
    b = ids[i:i+100]
    for col in ('home_team_master_id','away_team_master_id'):
        for r in (sb.table('games').select(col).in_(col, b).gte('game_date', cut).limit(5000).execute().data or []):
            if r[col]: act.add(r[col])
print(f'active within 90d: {100*len(act)/len(ids):.1f}%  (baseline before this change: 5.6%)')
"
```

Expected: roughly 99%. Anything under 50% means the ordering or the cutoff is wrong — report it rather than proceeding.

- [ ] **Step 6: Confirm the worktree is clean**

```bash
cd C:/PitchRank-clearqueue-topup && git status --short | grep -v '\.pyc$'
```

Expected: no output. In particular `.env.local` must show no modification, and `data/raw/` must contain no new files (a dry-run writes none).

---

## Post-implementation

Run the full suite (`python -m pytest tests/ -q`) and confirm the failure count matches the known pre-existing baseline of 5 (`test_gotsport_tier_persistence.py` x2, `test_enhanced_pipeline.py` x3) — these fail on `origin/main` too and are unrelated. Then open a PR from `feat/topup-prefer-recently-scraped`.
