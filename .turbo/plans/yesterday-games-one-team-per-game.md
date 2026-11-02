---
status: done
---

# Plan: Queue one team per unscored yesterday game

## As built

Code review changed four details after this plan was written. Where a passage below
disagrees, the code and this section are right:

- **Team rows:** there is no local `load_teams`. `enqueue_helpers.load_team_rows` gained a
  `columns=` parameter, and the job calls it with its own column list. The default stays
  `TEAM_ROW_COLUMNS`, so the other callers and the pin in `test_enqueue_helpers` are
  unchanged.
- **Games read:** the job does not use `_paged`. `fetch_unscored_games` pages by id
  (`gt("id", last id)`, then `order("id")`, then `limit(PAGE_SIZE)`). A score landing
  mid-read shrinks the filtered set, which would shift an offset past an unread game.
- **Queue rows under merged ids:** `load_active_requests` reads every id that
  `enqueue_helpers.expand_to_aliases` returns. That includes ids merged into a survivor
  that no game names; the function was moved there from `audit_user_interest_teams`. So a
  row under such an id is seen, not missed.
- **Verdict:** `active_request_verdict(rows, …)` picks the row the queue RPC would pick:
  compatible first, then `requested_at`, then `id`. It returns `"none"`, `"reuse"`,
  `"already_queued"` or `"conflict"`. A NULL `is_deprecated` counts as deprecated, as it
  does in the SQL selectors.

## Context

The daily yesterday-games job (`scripts/enqueue_yesterday_games.py`, run by
`.github/workflows/enqueue-yesterday-games.yml` at 07:13 UTC) queues **both** teams of every
GotSport game from yesterday that still has no score. One team's scrape is enough: its
schedule carries the shared game, and the importer fills the one stored game row for both
sides. Measured on the evening of 2026-11-02: 1,007 of Saturday 2026-10-31's scored GotSport
games got their score while the other team has never been scraped since Saturday. The
count was 2,261 earlier the same day, before more second sides were scraped; see the
Measurements subsection.

For Sunday 2026-11-01, measured around 17:45 UTC on 2026-11-02, there were 8,559 unscored
games with both sides known, involving 16,345 distinct teams. The home sides alone were
8,345 teams, so one team per game needs about half. That day's run, scheduled for 07:13 UTC
but started by GitHub at 17:00 UTC, actually queued 13,631 teams after its own skips.

The change: queue a small set of teams that still covers every unscored yesterday game, built
with a greedy set cover. That is a heuristic, so it gives few teams but does not promise the
fewest. Games with only one possible team are settled first, and after that, teams in
several unscored games are picked first. When one side of a game cannot be scraped, the
other side covers it. Everything else stays as today: priority 2, request
type `yesterday_game`, merge resolution, the "already scraped today" skip, and the game-side
GotSport id each queue row carries. The owner chose this change alone, without the weekend
double-scrape or day-3 retry ideas. Expected outcome: big-weekend yesterday-game queues
roughly halve. Help Clear Queue fills spare room with other teams, so the saving shows up as
a smaller queue, not fewer scrapes per manual run.

The owner settled the design on 2026-11-02:
- **Pick in Python, change nothing in the database.** The script reads yesterday's games
  through PostgREST and picks there, so no migration is applied by hand.
- **Keep `find_yesterday_null_score_teams` live but uncalled.** Its only caller is this
  script (`scripts/enqueue_yesterday_games.py:61`), and dropping it would need a hand-applied
  migration that buys nothing.
- **Show both counts on a dry run.** It prints the old rule's count beside the new one, so
  the change can be checked on a real day before it runs live.

## Pattern Survey

### Analogous Features
- `scripts/enqueue_yesterday_games.py:53-70` is today's thin RPC wrapper.
  - `--dry-run` logs the first 20 targets; the enqueue loop counts successes and failures.
  - The docstring's "200/run" is stale: the drainer runs 40 per run.
- `supabase/migrations/20260822000000_resolve_merges_in_scrape_enqueue_rpcs.sql:42-79` holds
  the newest RPC definition, and its rules carry over exactly:
  - the **game's** `provider_id` must be GotSport;
  - `home_score IS NULL` only — no `away_score` test and no `is_excluded` filter;
  - each side needs a non-null master id and a non-null provider id;
  - merges resolve one hop through `team_merge_map`;
  - `provider_team_id` is the **game-side** `home/away_provider_id`, not the team row's. The
    header at `:20-24` explains why: 243 of 295 merge survivors hold more than one GotSport
    registration.
  - a team qualifies when `is_deprecated = false AND (last_scraped_at IS NULL OR
    last_scraped_at::date < CURRENT_DATE)`.
  - It reads games first because a teams-first version timed out on Memorial Day 2026, with
    7,214 unscored games.
- `scripts/enqueue_viewed_teams.py:150` (`select_targets`) is the closest template for a
  selection done in Python: read with `_paged`, `resolve_merges`, load the team rows, apply
  eligibility, sort. A separate `main` does the dry run and the enqueue. Helpers are
  imported in packaged form at `:47`.
- `scripts/requeue_failed_scrape_requests.py:204` (`load_teams`) is a local team loader that
  selects `is_deprecated`. Its skip loop names a counter for each ineligible reason.
- `scripts/exclude_unscored_fixture_twins.py:72-83` (`fetch_unscored`) reads unscored games
  with `.is_("home_score", "null")` and `.order("id")`. It keeps the selection in a separate
  pure function (`select_twins`, `:104`), which is the shape to copy for the cover.
- **Do not copy:**
  - `scripts/enqueue_stranded_merge_fixtures.py` pages with `.range()` and no `.order()`.
  - `src/utils/merge_resolver.py` imports pandas, which the workflow does not install, and
    silently returns an empty map when its load fails.
- No set-cover or pick-one-side logic exists anywhere in the repo. The cover is new code.

### Reusable Utilities
- `scripts/enqueue_helpers.py`:
  - `_paged` (`:23`) pages with `.order("id")` in pages of 1,000. `games.id` is a unique uuid.
  - `_chunks` (`:42`) batches in 100s for `.in_()`.
  - `resolve_merges` (`:47`) resolves merges in one hop, batched, using only the standard
    library.
  - `load_team_rows` (`:67`) is **not** reusable as is. `TEAM_ROW_COLUMNS` (`:20`) has no
    `is_deprecated`, and `tests/unit/test_enqueue_helpers.py` pins that column set exactly.
    Use a local loader.
- `src/utils/provider_ids.py` `is_blank_provider_id` treats `''`, `'None'` and `'null'` as
  "no team". It uses only the standard library, and `src/utils/__init__.py` guards its pandas
  import, so it imports under the workflow's minimal install. Several scripts already import
  it this way, for example `scripts/exclude_none_opponent_games.py:42`.
- `scripts/enqueue_viewed_teams.py:119` (`scraped_within_cooldown`) shows how to parse
  `last_scraped_at`, including the case of a value with no timezone.

### Convention Anchors
- **Script skeleton** (`scripts/enqueue_viewed_teams.py:25-60`): optional `truststore`, then
  `load_dotenv(".env.local")` and `load_dotenv(".env")`, then `sys.path.append(<repo root>)`,
  then `from scripts.enqueue_helpers import ...  # noqa: E402`. `get_gotsport_provider_id` is
  copy-pasted in every enqueue script; that is IMP-167, so leave it alone.
- **Workflow** (`.github/workflows/enqueue-yesterday-games.yml:44-55`): installs only
  `supabase python-dotenv truststore certifi`, sets `PYTHONPATH=$PWD`, and maps `--dry-run`
  through `DRY_RUN_FLAG`. No change is needed.
- **Test doubles:** `tests/unit/test_enqueue_viewed_teams.py:40-150` is the strict double
  CLAUDE.md asks for.
  - It applies its filters, projects only the selected columns, raises on `range()` without
    `order()`, records an RPC at `execute()`, and raises on an unseeded table.
  - It has **no `is_()`**. The existing `is_()` in `test_exclude_unscored_fixture_twins.py`
    reads `row.get(column)`, which lets a misspelled column read as NULL; do not copy it.
  - Today's `tests/unit/test_enqueue_yesterday_games.py` uses a bare `Mock` that records at
    `rpc()` and filters nothing. Replace it.
- **SQL guard:** `tests/unit/test_scrape_activity_predicate.py:26-30, 235-238` asserts that
  the "revival" producers, `find_yesterday_null_score_teams` among them, never carry the
  dormant-team eligibility predicate. Once the script stops calling the RPC, that guard
  covers a function nothing calls, so a Python test must pin the same rule.
- **Queue RPC** (`supabase/migrations/20261020020000_atomic_matchbalance_refresh.sql`, newest
  `enqueue_scrape_request` at `:102-131`, which wraps `enqueue_scrape_request_once` at
  `:21-93`):
  - The queue holds one active (pending or processing) row per team:
    `idx_scrape_requests_active_team`, `:3-5`.
  - Enqueueing a team that already holds an active row **reuses** that row. A compatible
    pending row also gets its priority promoted with `LEAST`.
  - It **raises** in these cases:
    - 23505 when the existing row has a different `provider_id` or `provider_team_id`;
    - 23505 when, for a non-`missing_game` request, the existing row's `game_date` is later
      than `p_game_date`;
    - 23505 when `p_game_date` falls outside the existing row's `game_date ± 90` days;
    - 55000 when a `processing` row is more than 24 hours old.
  - Under today's both-sides rule, a refused team's opponent was still queued, so its game
    stayed covered. A one-team-per-game cover has to read active rows first.
  - **Scrape windows** (verified on `origin/main`):
    - `process_missing_games` scrapes `game_date ± 90` around the row's own `game_date`
      (`scripts/process_missing_games.py:197-221`, `:428-492`).
    - `drain_queue` scrapes from `teams.last_scraped_at` onward (`scripts/drain_queue.py`).
    - So a compatible **pending** row whose window holds yesterday covers yesterday's game.
    - A **processing** row may be stranded, because nothing reclaims it (CLAUDE.md), so it
      does not reliably cover anything.

### Proposed Alignment
Follow the table-reading enqueue pattern:
- Read yesterday's unscored GotSport games with `_paged`.
- Resolve merges with `resolve_merges`, and load teams with a local loader that includes
  `is_deprecated`.
- Judge each side's eligibility with the RPC's exact rules, plus `is_blank_provider_id`
  and a one-read check against the team's active queue row.
- Do the cover in a pure function.
- Keep `enqueue_team` and `main`'s enqueue loop unchanged.
- Test against a strict double extended with a strict `is_()`.

## Implementation Steps

1. **Set up an isolated workspace off `origin/main`.**
   - The shared checkout `C:\PitchRank` is a detached HEAD far behind `origin/main`. It
     carries uncommitted edits to tracked files, one of them in scope:
     `.claude/skills/merging-duplicate-teams/SKILL.md`. Do not branch in place, and do not
     stash or unstage that work.
   - Create a worktree: `git worktree add C:\pitchrank-yesterday-one-team -b
     yesterday-games-one-team-per-game origin/main`. This is the global CLAUDE.md exception
     for an unrelated HEAD holding dirty in-scope files.
   - Check the baseline: `git -C C:\pitchrank-yesterday-one-team status --short` must print
     nothing, and `git -C C:\pitchrank-yesterday-one-team log -1 --format=%H` must equal
     `git rev-parse origin/main`. If either check fails, stop and recreate the worktree.
   - Copy this plan into the worktree's `.turbo/plans/`, so it ships with the PR.
   - Python tests run in the worktree as is. For the read-only dry run in Verification, copy
     the root `.env` from `C:\PitchRank`; it is gitignored, and its values must never be
     printed.

2. **Rewrite the selection in `scripts/enqueue_yesterday_games.py`.**
   - **Preserve from the current file:**
     - the shebang, the `truststore` block, the two `load_dotenv` calls in order, the
       `sys.path.append`, and the `logging.basicConfig` line;
     - the constants `GOTSPORT_PROVIDER_CODE`, `PRIORITY_YESTERDAY_GAME = 2` and
       `REQUEST_TYPE = "yesterday_game"`;
     - `get_gotsport_provider_id` as is;
     - `enqueue_team` (`:73`), with its exact signature and payload, `p_game_date` still
       yesterday;
     - `main`'s env-var check, `--dry-run` flag, and the success/fail enqueue loop with its
       final log line.
   - **Imports**, after `sys.path.append`, each with `# noqa: E402`:
     - `from scripts.enqueue_helpers import _chunks, _paged, resolve_merges`
     - `from src.utils.provider_ids import is_blank_provider_id`
     - `datetime` and `timezone` from `datetime`
   - **Dates:** derive one `today = datetime.now(timezone.utc).date()` in `main`, and set
     `yesterday = today - timedelta(days=1)`. That replaces both `date.today()` calls (`:60`
     and `:99`). The runner and the RPC's `CURRENT_DATE` already run in UTC, so CI behaviour
     does not change; a local run late in the evening can no longer pick the wrong day.
     - `today` and `yesterday` stay `date` objects for comparisons only.
     - Everything sent over the wire takes `yesterday.isoformat()`: the `games` filter and
       `enqueue_team`'s `game_date` argument.
     - The RPC body is serialized as JSON, and a `date` object raises `TypeError` there.
       `main`'s `except Exception` would then count every enqueue as failed while the job
       exits green.
   - **`fetch_unscored_games(supabase, provider_id, game_date)`:**
     - `_paged` over `games`, selecting
       `id,home_team_master_id,away_team_master_id,home_provider_id,away_provider_id`;
     - filter `.eq("game_date", game_date)`, `.eq("provider_id", provider_id)` and
       `.is_("home_score", "null")`;
     - the same filters as the RPC, with no `is_excluded` and no `away_score` test.
   - **`load_teams(supabase, team_ids)`:** a local loader selecting
     `team_id_master,team_name,is_deprecated,last_scraped_at`, batched with `_chunks`. It
     mirrors `requeue_failed_scrape_requests.load_teams` (`:204`). Do not widen
     `enqueue_helpers.TEAM_ROW_COLUMNS`.
   - **`scraped_today(last_scraped_at, today)`:**
     - parse as `scraped_within_cooldown` does (`enqueue_viewed_teams.py:119`), treating a
       value with no timezone as UTC;
     - return `parsed.astimezone(timezone.utc).date() >= today`;
     - a missing value returns `False`.
   - **`load_active_requests(supabase, canonical)`**, where `canonical` is the raw → canonical
     map `resolve_merges` returned:
     - Read `scrape_requests` for every id in `set(canonical) | set(canonical.values())`, so
       both the raw ids the games carry and their survivors are covered. Select
       `team_id_master,status,provider_id,provider_team_id,game_date,requested_at`.
     - Filter `.in_("status", ["pending", "processing"])`, and batch
       `.in_("team_id_master", batch)` with `_chunks`.
     - Key each row by `canonical.get(row["team_id_master"], row["team_id_master"])`. The RPC
       likewise matches active rows on the merge-resolved id
       (`20261020020000:58-70`).
     - A canonical can hold two rows: one under its own id and one under a pre-merge id. 43
       pending rows sat under pre-merge ids on 2026-11-02.
       - In that case keep the row the RPC would choose: a compatible row first (same
         `provider_id` and `provider_team_id`, `game_date` on or before yesterday, and
         yesterday within its ±90 days);
       - otherwise the earliest `requested_at`.
     - A row under a pre-merge id that appears in no game today is still missed. If it
       collides, the enqueue is counted as failed, as it is today.
   - **`active_request_verdict(row, unit, gotsport_provider_id, yesterday)`**, a pure
     function. It mirrors the RPC's refusal rules (`20261020020000:116-127`) for the one
     request type this job sends.
     - PostgREST returns `scrape_requests.game_date`, a `date` column, as an ISO string. Parse
       it with `date.fromisoformat(row["game_date"])` before comparing it with `yesterday`.
     - It returns one of three values:
     - `"none"` — there is no active row. Enqueue as normal.
     - `"conflict"` — the row is `processing`, or it has a different `provider_id` or
       `provider_team_id`, or yesterday falls outside its `game_date ± 90`.
       - The unit becomes ineligible, under skip counter `active_request_conflict`, and the
         opponent covers the game.
       - A processing row is excluded whether or not it is stranded. It cannot be reliably
         told apart, and the opponent is a safe fallback.
     - `"covered"` — a compatible pending row whose window already holds yesterday.
       - If its `game_date` is on or before yesterday, the unit stays eligible and is
         enqueued: the RPC reuses the row and promotes its priority, as today.
       - If its `game_date` is later than yesterday, the unit stays eligible but is **not**
         enqueued, because the RPC would raise 23505 on it. It is counted as
         `already_queued`, since that row's ±90-day scrape covers yesterday.
   - **`pick_cover(game_candidates)`**, a pure function:
     - Input: one entry per game, each a set of eligible units `(team_id_master,
       provider_team_id)`. A set holds 0, 1 or 2 units; a game whose two sides resolve to the
       same unit holds 1.
     - **Settle forced games first.** Take every game with exactly one eligible unit and pick
       that unit, unless a sibling registration of the same master is already picked.
       - Each forced pick marks **all** of its games covered, not just the forced one, and
         blocks its siblings, exactly as a greedy pick does.
       - With `{X}` and `{X,Y}`, the cover is X alone.
       - Do this before any greedy step, because a forced registration must not lose to a sibling the
       greedy step would favour. Peer counterexample: with `{A1,B}`, `{A1,C}` and `{A2}`,
       greedy-first picks A1 and strands `{A2}`, whereas forced-first picks A2, B and C and
       covers all three.
     - Count, for every unit, the uncovered games it covers.
     - Repeatedly pick the unit with the highest count. Break ties on `team_id_master`, then
       `provider_team_id`, ascending, so runs are deterministic.
     - After each pick, mark its games covered and lower the other units' counts.
     - Block every other unit with the same `team_id_master`: the queue holds one active row
       per team, and a second registration raises 23505.
     - Return the picked units, plus two uncovered counts: `uncovered_no_side` (the game had
       no eligible unit) and `uncovered_sibling_blocked` (its only units were blocked
       siblings). Forced-first removes the known case, but the cover remains a heuristic.
     - A lazy max-heap keeps it fast at weekend volume: about 20K units and 10K games.
   - **`find_teams_to_enqueue(supabase, gotsport_provider_id, yesterday, today)`.** Keep the
     name so `main`'s call site stays recognisable. It returns `(picks, stats)`.
     - Fetch the games.
     - Collect the non-null raw master ids from both sides, then call `resolve_merges`. Then
       run `load_teams` over the canonical ids, and `load_active_requests` over the raw →
       canonical map.
     - For each game side, the side is eligible only when:
       - its master id is non-null;
       - its game-side provider id is not blank (`is_blank_provider_id`);
       - the canonical team row exists;
       - `is_deprecated` is false;
       - `scraped_today` is false;
       - and `active_request_verdict` is not `"conflict"`.
     - Count each reason a side is skipped, using `requeue_failed_scrape_requests`'s
       vocabulary: `no_master`, `blank_provider_id`, `missing_team`, `deprecated`,
       `scraped_today`, `active_request_conflict`.
     - The old-rule count is the number of distinct canonical masters with a side passing the
       **old** RPC's rules, so that it reproduces what the RPC returned:
       - the master id is non-null;
       - the provider id is non-null — `IS NOT NULL` only, so a placeholder `'None'` passes;
       - the team row exists, `is_deprecated` is false, and `scraped_today` is false.
       - No active-request check applies.
     - Run `pick_cover`.
     - `picks` are dicts `{team_id_master, team_name, provider_team_id, enqueue}`, sorted by
       `team_id_master`.
       - `provider_team_id` is the picked unit's **game-side** id.
       - `enqueue` is `False` only for the `already_queued` case above.
     - `stats` is a dict holding:
       - `games`, `old_rule_teams`, `picked` and `already_queued`;
       - `uncovered_no_side` and `uncovered_sibling_blocked`;
       - one entry per skip counter.
       - Tests assert on `stats` directly.
     - `main` logs one summary line from `stats` on dry and live runs alike: `"{games}
       unscored games on {yesterday}; old rule would queue {old_rule_teams} teams; queueing
       {picked} ({already_queued} already queued); {uncovered_no_side} games had no scrapeable
       side, {uncovered_sibling_blocked} blocked by a sibling registration"`. The skip
       counters follow it.
     - `main` enqueues only the picks with `enqueue=True`. Its final line already reports
       successes and failures.
   - **Must not add** any dormant-team or scrape-activity filter, such as `scrape_attempts` or
     `last_played_at`. This job is a revival producer (see the SQL guard above).
   - **Docstring:** rewrite it to say the job queues one team per unscored game, selected in
     Python, and drop the stale "200/run".

3. **Replace `tests/unit/test_enqueue_yesterday_games.py` with tests against a strict double.**
   - Copy the double from `tests/unit/test_enqueue_viewed_teams.py:40-150` (`_Result`,
     `_Table`, `_RpcBuilder`, `FakeSupabase`) and add `is_(column, value)`:
     - it accepts only `"null"`;
     - it raises at build time on a column not present in the seeded rows;
     - it matches on `row[column] is None`.
     - Keep `order()`'s keyword-only `desc` and the record-at-`execute()` RPC builder.
     - In `_RpcBuilder.execute()`, run `json.dumps(self._params)` before recording, so a
       non-JSON value such as a `date` raises here exactly as httpx raises in production.
     - Make `.single()` raise on zero rows, as PostgREST's PGRST116 does
       (`supabase-pitchrank` skill).
     - Seed a `scrape_requests` table: `load_active_requests` reads it, and an unseeded table
       raises.
     - Seed every date column as an ISO string, as PostgREST returns it: `games.game_date`,
       `scrape_requests.game_date` and `teams.last_scraped_at`. A seeded `date` object would
       let a date-vs-string comparison pass here and then crash in production.
   - **Seeding rule for guard tests:**
     - Each test that proves a guard (an ineligible side, a blocked sibling, an
       active-request conflict) must give the guarded unit the **winning** tie-break position.
       That means the lower `team_id_master`, or a second game of its own so the greedy count
       favours it.
     - Seeded otherwise, the opponent wins the tie anyway, so deleting the guard leaves the
       picks unchanged and the mutation survives.
   - **Pure tests for `pick_cover`:**
     - one game: one pick;
     - a hub team in three games against three different opponents: only the hub is picked;
     - a chain A–B, B–C: only B is picked;
     - sibling registrations of one master: only one is picked, and the game held by the
       blocked sibling falls to its opponent;
     - the forced-first counterexample `{A1,B}`, `{A1,C}`, `{A2}`: the picks are A2, B and C,
       and both uncovered counts are 0;
     - a forced pick covering a second game, `{X}` and `{X,Y}`: the picks are `[X]` only;
     - a self-game (both sides the same unit): one pick;
     - a game with no eligible unit: counted as uncovered;
     - a tie: the lower `team_id_master` wins.
   - **Composition tests** call `find_teams_to_enqueue` through the double, so the read and
     its filters are exercised (CLAUDE.md, "bind the test at the altitude where the failure
     lives"). Seed **one row per condition**, each violating exactly one:
     - a scored game, a game on another date and a game under another provider: none of
       their teams is picked;
     - each ineligible-side reason in turn (null master id, `'None'` provider id, no team
       row, deprecated canonical, scraped today): the opponent is picked instead;
     - a merged side (raw id in `team_merge_map`): the canonical id is picked, carrying the
       **game-side** provider id, not the team row's;
     - both sides ineligible: no pick, and `stats["uncovered_no_side"]` counts it;
     - active requests, one row each:
       - a `processing` row: the opponent is picked;
       - a pending row with a different `provider_team_id`: the opponent is picked;
       - a pending row with the **same** `provider_team_id` but a different `provider_id`,
         dated today: the opponent is picked.
         - Without the provider check, this row reads as `already_queued` and neither side
           is queued.
         - The case is real: `enqueue_viewed_teams.enqueue_team` writes the team row's own
           `provider_id` (`scripts/enqueue_viewed_teams.py:141`), and that job runs before
           this one.
       - a `completed` row that would conflict if it were read: the team is still picked,
         with `enqueue=True`. This pins the `status` filter;
       - a conflicting pending row stored under the side's **raw pre-merge id**, where the
         game names that raw id: the opponent is picked. This pins the read by raw and
         canonical id;
       - a pending row whose `game_date` is more than 90 days from yesterday: the opponent is
         picked;
       - a compatible pending row dated yesterday or earlier: the team is picked with
         `enqueue=True`;
       - a compatible pending row dated today: the team is picked with `enqueue=False`, and
         `stats["already_queued"]` counts it;
     - `last_scraped_at` late yesterday (UTC) is eligible, while early today is not;
     - **revival rule:** a team seeded with dormant-looking activity columns (high
       `scrape_attempts`, old `last_played_at`) is still picked;
     - `stats["old_rule_teams"]` equals a literal expected value for a fixture where the old
       rule and the cover differ. The fixture includes one `'None'` provider-id side, which
       the old rule counts and the cover skips.
   - **`main` tests:**
     - `--dry-run` makes no `enqueue_scrape_request` call;
     - a live run makes one call per pick with `enqueue=True`, and none for `already_queued`
       picks. Each call carries `p_priority == 2`, `p_request_type == "yesterday_game"` and
       `p_game_date == "2026-11-01"`, asserted as that **string** literal, with `today`
       frozen to 2026-11-02 by patching the module's `datetime`. Do not read the wall clock
       in the assertion.
     - An RPC failure for one team is counted and does not stop the loop.

4. **Update the docs that describe this job.**
   - `CLAUDE.md:664` (workflow table): "Queue teams whose yesterday games have null scores"
     becomes "Queue one team per yesterday game with a null score".
   - `CLAUDE.md:867` (producer table): "Teams whose yesterday games have null scores,
     excluding any already scraped today" becomes "One team per yesterday game with a null
     score — a greedy cover, not both sides — excluding any already scraped today or holding
     a conflicting queue row".
   - `scripts/enqueue_helpers.py:5-9`: take `enqueue_yesterday_games` out of the RPC-driven
     list. It now reads `games` directly and uses `_paged`, `_chunks` and `resolve_merges`.
   - `tests/unit/test_scrape_activity_predicate.py:26-30`: add one sentence to the comment.
     The yesterday job no longer calls `find_yesterday_null_score_teams`; it selects in
     Python, and `test_enqueue_yesterday_games.py` pins the same revival rule. Keep the
     function in `REVIVAL_FUNCTIONS`, since it is still live in the database.
   - `.claude/skills/merging-duplicate-teams/SKILL.md:879` and
     `references/pipeline-gotchas.md:63-70`: one sentence each saying the yesterday job now
     resolves merges in Python (`resolve_merges`), while `find_recently_active_teams` still
     does it in SQL. Edit the worktree copies; the dirty copy in `C:\PitchRank` is someone
     else's work.

## Verification

- **New tests:** `python -m pytest tests/unit/test_enqueue_yesterday_games.py -q` — all pass.
- **CI gate:** `python -m ruff check src/ scripts/ config/ tournament_intake.py dashboard.py`
  and `python -m pytest tests/ --ignore=tests/test_enhanced_pipeline.py`, both green. That
  includes `test_scrape_activity_predicate.py` and `test_enqueue_helpers.py`, which this
  change must not disturb.
- **Mutation checks**, one at a time. Collect the failing test **names**; a red suite alone
  proves nothing. Each mutation must fail a named test in `test_enqueue_yesterday_games.py`:
  - drop `.is_("home_score", "null")`, then `.eq("provider_id", …)`, then
    `.eq("game_date", …)`, each separately;
  - remove each eligibility condition separately: blank provider id, missing team,
    deprecated, scraped today;
  - make `pick_cover` return every unit (the old both-sides behaviour);
  - remove the same-master sibling block;
  - remove the forced-first step;
  - make a forced pick mark only its own forced game covered;
  - drop the `.in_("status", …)` filter from `load_active_requests`;
  - read active rows for canonical ids only, not raw ids;
  - remove each `active_request_verdict` conflict condition separately: `processing`,
    different `provider_id`, different `provider_team_id`, and the ±90-day window;
  - enqueue `already_queued` picks anyway;
  - pass `yesterday` (the `date`) instead of `yesterday.isoformat()` to `enqueue_team`;
  - make `scraped_today` compare with `>` instead of `>=`;
  - drop `.execute()` from `enqueue_team`.
- **Read-only dry run against production**, from the worktree with `.env` copied in:
  `python scripts/enqueue_yesterday_games.py --dry-run`.
  - Expect the summary line, with "queueing" at roughly half of "old rule would queue" on
    a day after a weekend game day.
  - Cross-check the old-rule count against the live RPC for the same date via
    `mcp__supabase__execute_sql`:
    `select count(distinct team_id_master) from find_yesterday_null_score_teams(current_date - 1, (select id from providers where code = 'gotsport'))`.
  - Run the RPC query back to back with the dry run. `old_rule_teams` reproduces the RPC's
    rules, placeholders included, so the two counts should be equal. Any difference has to
    be explained by a team scraped or merged between the two reads.
  - The dry run must make no write. A new-row count alone cannot show that, because an
    enqueue that reuses an existing row only promotes it. Every `enqueue_scrape_request` call
    does, however, insert one `scrape_request_intents` row, whether it reuses a row or
    inserts one (`20261020020000:87-88`, `:113-115`).
    - Note the dry run's start and end times.
    - Confirm `select count(*) from scrape_request_intents where created_at between '<start>'
      and '<end>'` returns 0. Any row must be traced to a different writer, such as a user
      click.
    - The `main` dry-run test separately proves no RPC is executed.
- **After merge — volume:**
  - At the first scheduled run after a weekend, the workflow log's summary line should show
    "queueing" at roughly half of "old rule would queue".
  - The final line `Enqueued {success} ..., {fail} failed` should show `fail` near 0.
    Conflicts are filtered before the enqueue, so any failure left is a race; read the
    failure warnings.
  - The number of `yesterday_game` rows inserted that hour (count `requested_at` in the run's
    hour) should be at most `picked − already_queued`. A team whose compatible pending row
    was reused is promoted, not re-inserted.
  - A count of 0 with `success > 0` means every pick was reused. That is possible but
    unlikely on a weekend, and if it happens, inspect it before trusting the run.
- **After merge — outcome (the check that matters):**
  - Fewer scrapes must not mean fewer scores. Eight days after the first post-merge weekend,
    measure the share of that Saturday's and Sunday's GotSport games that have a score.
  - Use the same query as the baseline below. The two prior weekends, measured 8–15 days
    after they were played, give the band:
    - 2026-10-17: 75.4% · 2026-10-18: 82.7%
    - 2026-10-24: 77.7% · 2026-10-25: 82.6%
    - These were read on the evening of 2026-11-02. The 10-24/25 rates were still rising
      slightly (77.5% and 82.4% earlier the same day), so compare at a similar lag.
  - A post-merge weekend inside or above that band means coverage held.
  - A drop of more than about 3 points below the band means one side's scrape is not
    filling some games. Look first at games whose picked side is the only side with an
    aliased GotSport id.

### Measurements behind the Context figures (read-only SQL, run 2026-11-02)

```sql
-- Scored share for a game date (baseline band above; rerun with the post-merge dates)
select game_date, round(100.0 * count(*) filter (where home_score is not null) / count(*), 1)
from games where provider_id = (select id from providers where code = 'gotsport')
  and coalesce(is_excluded, false) = false and game_date in ('2026-10-24', '2026-10-25')
group by 1;

-- 2,261: Saturday games scored with only one side ever scraped since Saturday
with g as (select home_team_master_id h, away_team_master_id a from games
  where game_date = '2026-10-31' and home_score is not null
    and provider_id = (select id from providers where code = 'gotsport')
    and home_team_master_id is not null and away_team_master_id is not null),
s as (select distinct team_id from team_scrape_log
  where scraped_at >= '2026-10-31' and status <> 'error')
select count(*) from g left join s sh on sh.team_id = g.h left join s sa on sa.team_id = g.a
where (sh.team_id is null) <> (sa.team_id is null);

-- 16,345 vs 8,345: Sunday unscored games with both sides known
with g as (select home_team_master_id h, away_team_master_id a from games
  where game_date = '2026-11-01' and home_score is null
    and provider_id = (select id from providers where code = 'gotsport')
    and home_team_master_id is not null and away_team_master_id is not null
    and home_provider_id is not null and away_provider_id is not null)
select (select count(distinct x) from (select h x from g union all select a from g) u) both_sides,
       (select count(distinct h) from g) home_side_only;
```

All three queries depend on when they run, because scraping keeps filling games and reaching
second sides. Taken around 17:45 UTC on 2026-11-02, the last two returned 2,261 and
16,345/8,345. Rerun on the evening of 2026-11-02, they returned 1,007 and 14,462/7,379.

- The one-side count shrinks because the second team of many games was scraped *after*
  the score had already landed. So 1,007 is the stricter figure: games scored while the
  other side has **never** been scraped since Saturday.
- The two-to-one ratio holds at both times.
- Neither query resolves merges, so read both as evidence for the premise, not as exact
  figures.

## Context Files

- `scripts/enqueue_yesterday_games.py`: the file being rewritten; preserve list in step 2.
- `supabase/migrations/20260822000000_resolve_merges_in_scrape_enqueue_rpcs.sql` (`:20-79`):
  the selection rules to carry over exactly.
- `scripts/enqueue_viewed_teams.py`: the template for imports (`:25-60`), `select_targets`
  (`:150`) and timestamp parsing (`:119`).
- `scripts/enqueue_helpers.py`: `_paged`, `_chunks`, `resolve_merges`, and why
  `TEAM_ROW_COLUMNS` stays as is.
- `tests/unit/test_enqueue_viewed_teams.py` (`:1-150`): the strict double to copy and extend.
- `src/utils/provider_ids.py`: `is_blank_provider_id`.
- `tests/unit/test_scrape_activity_predicate.py` (`:20-40`, `:235-238`): the revival rule the
  Python path must keep.
- `supabase/migrations/20261020020000_atomic_matchbalance_refresh.sql` (`:1-70`, `:102-131`):
  why only one registration per team can be queued.
