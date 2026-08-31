---
status: ready
---

# Plan: Probe ledger, then a targeted contradiction audit

Two PRs, in order. **PR1** records every GotSport probe outcome, including the ones that
change nothing. **PR2** adds the targeted audit that consumes it.

## Context

`teams.state_code` is wrong for roughly 5,700 teams and the free tiers find them only
partly, because every tier is learned from the column being audited. A club whose teams are
uniformly mislabelled agrees with itself. `scripts/assign_team_states.py:606-610` names the
blind spot in its own comment, and Tier A — the GotSport registration record — is the only
external truth available.

Tier A is expensive (one paid ZenRows call per team) and today it is only ever spent on
`disputed | stateless` (`scripts/assign_team_states.py:623`). 175,688 stated teams have a
GotSport record and only 5,873 have ever been probed.

The targeting rule, measured rather than guessed:

> a team whose `state_code` contradicts a club-mate's already-confirmed `state_source = 'tier_a'`
> state, for clubs where every confirmed team agrees on one state.

Measured 2026-08-31 against production: **1,210 such teams, 50.4% genuinely wrong** when
probed (150 sampled, 129 answered, 65 confirmed), against a **2.9%** base rate for a random
team no tier disputes. Full measurements are in
`.turbo/reports/2026-08-31-targeting-the-gotsport-probe.md`.

**The audit's value is targeting, not exclusivity.** 457 of the 1,173 selected candidates
(39%) are already in the `disputed` set, so a full sweep probes them too — `club_derived_state`
(`:377`) excludes the team being decided from its own club counts, so the Mandeville shape
(2 teams at AL/TX against 41 at LA) *is* disputed by Tier B. What the audit changes is the
price: a full sweep reaches those 457 at a cost of ~6,200 calls, the audit reaches all 1,173
for ~1,110. The remaining 716 are reachable no other way.

### Why the ledger comes first

Nothing records a probe that *agrees* with the stored value. `team_state_audit` is written
only by the triggers `log_team_state_update` / `log_team_state_insert`
(`supabase/migrations/20260829120000_add_team_state_provenance.sql:318-333`), which fire on a
`state_code` change, and `state_source = 'tier_a'` is stamped only by `apply_team_state`
(`:403`), which only runs on a write.

That is not merely a lost saving. It makes a budgeted audit **stall**. A candidate that
produces no change — no GotSport alias, a failed call, or an answer that agrees — gets no
`tier_a` stamp, so it still matches the selector next run and still sorts to the same place.
With deterministic ordering and a prefix budget, once N such teams occupy the head, every
later `--probe-limit N` run re-probes exactly them and never reaches the tail.

So the ledger is a prerequisite for a *capped* audit. It also turns the rule from a
fixed-cost sweep into one that improves: a club whose probes keep contradicting its anchor is
a name collision (Elite FC, North FC — see the report's false-positive table), and only a
record of agreements can reveal that.

---

# PR1 — Record every probe outcome

Branch `state-probe-ledger` off `origin/main`.

## Implementation Steps

1. **Migration `supabase/migrations/<ts>_add_team_state_probe_log.sql`**
   - Table `team_state_probe_log`: `id bigserial primary key`, `team_id_master uuid not null`,
     `provider text not null default 'gotsport'`, `provider_team_id text`,
     `outcome text not null`, `reported_state_code character(2)`,
     `stored_state_code character(2)`, `agreed boolean`,
     `probed_at timestamptz not null default now()`, `actor text not null`.
   - `provider_team_id` is nullable on purpose: a selected candidate with no alias still gets a
     row (step 3).
   - **Store the raw per-probe outcome string**, exactly as `probe()` returns it at
     `scripts/assign_team_states.py:432-452`: `mapped`, `no such team (404)`,
     `no association in payload`, `unmapped code <raw>`, `unparseable payload`,
     `request failed (<ExcType>)`, `http <status>`. The run's histogram is *not* the same
     thing — the fan-in loop at `:456` normalises `request failed (<Type>)` down to
     `request failed` before counting, so the counter key and the per-probe string differ. The
     ledger keeps the raw string; the histogram keeps its normalised category.
   - Index on `(team_id_master, probed_at DESC)` — the audit's only read is "when was this team
     last probed, and with what outcome".
   - **Enable RLS with the `deny_all` / `service_role_all` pair.** New tables here are
     anon-writable by default via `pg_default_acl`; that is how `team_merge_audit` and
     `team_link_audit` reached the security advisory. Copy
     `supabase/migrations/20260829120000_add_team_state_provenance.sql:190-208`, which is the
     current pair and carries the `DROP POLICY IF EXISTS` idempotency guards. Do **not** model on
     `20240215000000_add_row_level_security.sql:250-274` — that range holds two `deny_all`
     policies on two different tables, not a pair, and lacks the drops.
   - **Do not copy `team_match_review_queue`'s confidence CHECK**
     (`supabase/migrations/20240201000003_add_match_review_queue.sql:14`), which pins confidence
     to `>= 0.75 AND < 0.90` and rejects both values this domain uses.
   - No RPC is needed: the writer inserts in batches from Python. If one is ever added it must
     take `(p_after, p_batch_size)` and return a cursor — an RPC gets a hard 8s
     `statement_timeout` and `SET LOCAL` inside a function body is inert.
     `scripts/refresh_team_scrape_activity.py:102,112` is the model.

2. **Write the log from `probe_associations` (`:402`)**
   - Signature becomes `probe_associations(provider_team_ids, workers, sb, stored_states)`.
     `sb` and `stored_states` (`{team_id_master: stored_state_code}`) are **required together**;
     raise if one is given without the other. The return shape `(states, outcomes)` is
     unchanged, so `probe_is_unusable` and the histogram at `:631-632` keep working — but the
     **call site at `:630` must be updated to pass both**. A default-`None` parameter with an
     untouched call site would leave the ledger inert in every real run while the unit tests
     passed.
   - **Insert on the main-thread fan-in loop at `:454-458`, never inside `probe()`.** That loop
     already consumes `pool.map`'s iterator in the main thread and does all dict mutation there.
     Every other `ThreadPoolExecutor` in `src/` and `scripts/` keeps Supabase out of the worker;
     `scripts/backfill_missing_club_names.py:361` records the rule in a comment ("resolve in
     workers, then update DB sequentially"). supabase-py publishes no thread-safety guarantee.
   - Buffer rows and flush in `IN_BATCH` (`:150`) chunks. **Flush before returning**, so the
     `probe_is_unusable` abort at `:633-639` still leaves the run's rows on disk — a blocked run
     must keep what it learned, or the money is spent twice.
   - An insert failure is **fatal**, not swallowed. A silently half-written ledger is worse than
     none: the audit would treat the missing rows as "never probed" and re-probe them, and the
     present rows as verified.
   - `agreed` is `reported_state_code == stored_state_code` when both are present, else NULL.
     That column is what makes an agreement visible; without it the ledger reproduces today's
     blind spot in a new table.

3. **Record selected candidates that have no alias**
   - `fetch_gotsport_aliases` (`:242`) returns only the teams it finds, so a selected candidate
     with no GotSport alias never reaches `probe_associations` and would never get a row. At the
     measured ~5% no-alias rate that is about 60 of 1,173 — enough to fill a `--probe-limit 50`
     prefix outright and stall every later capped run.
   - Write those rows from `build_snapshot`, immediately after the alias lookup at `:628`, with
     `outcome = 'no gotsport alias'`, `provider_team_id = NULL`, `reported_state_code = NULL`,
     `agreed = NULL`.

4. **Docs for PR1 — the dry run now writes**
   - The default, documented dry run begins writing rows to the database. Three places promise
     otherwise and all three must change to "a dry run performs **no team-state and no
     review-queue writes, but does persist paid-probe observations**":
     - the **argparse help at `scripts/assign_team_states.py:998`**, which reads
       `help="Default. Decide and report, write nothing"` — the one a user sees from `--help`,
       and the one most easily missed;
     - `SKILL.md` Step 2, which says "Writes nothing";
     - the module docstring (`:33-40`), which describes the dry run as snapshotting and writing
       decisions to `--out`.
   - State the reason in the same place so it is not re-opened: the call is paid for whether or
     not the result is recorded, and discarding it is what made the audit stall.
   - Add `team_state_probe_log` to the skill's reference material with a one-line note on what it
     holds and that it grows by one row per probe.

5. **Tests**
   - **Add `"team_state_probe_log"` to `NEW_TABLES` at
     `tests/unit/test_team_state_provenance_migration.py:26`** — one line. That file already
     resolves objects by name across all migrations, strips comments before matching, and
     asserts the exact policy bodies (`TO anon, authenticated USING (false) WITH CHECK (false)`
     and `TO service_role USING (true) WITH CHECK (true)`) via
     `test_every_new_table_ships_with_rls_and_both_policies` (`:473`). Re-deriving that
     comment-stripping in a new file is how a commented-out clause comes to satisfy an assertion.
   - **`tests/unit/test_state_probe_log.py`** covers the writer only, in the conventions of
     `tests/unit/test_assign_team_states.py`: no Supabase double beyond `MagicMock`, assertions
     on what reached `.insert()`.
     - A `mapped` probe whose answer equals the stored state writes a row with `agreed = True` —
       the case the whole PR exists for.
     - `no such team (404)`, `unparseable payload` and `request failed (...)` each write a row
       with a NULL `reported_state_code`, and the raw string is stored, not the histogram's
       normalised `request failed`.
     - A selected candidate with no alias writes a row with `outcome = 'no gotsport alias'`.
     - `probe_associations` called with `sb` but no `stored_states` (or the reverse) raises.
     - The insert happens after `pool.map` is consumed, not inside `probe()`.
     - The `--dry-run` argparse help no longer contains "write nothing" — a string assertion, so
       the false safety guarantee cannot survive the PR that falsifies it.

## PR1 Verification

- `python -m pytest tests/unit/test_state_probe_log.py tests/unit/test_team_state_provenance_migration.py -q`
  — new cases pass; each guard fails when reverted against a scratch copy.
- `python -m ruff check src/ scripts/ config/ tournament_intake.py dashboard.py` — clean.
- Apply the migration, then confirm the advisor is quiet: `mcp__supabase__get_advisors` with
  `type: "security"` must not name `team_state_probe_log`. This is the check that would have
  caught the `team_merge_audit` mistake.
- One live single-team probe (`--team <uuid>`, **no** `--execute`) writes exactly one row; a
  second run of the same team writes a second row with `agreed = True`.
- **Repair the migration ledger by hand** if the migration is hand-applied:
  `supabase migration repair --status applied <version>`. Skipping it leaves the next
  `supabase db push` re-running the file.

---

# PR2 — The contradiction audit

Branch `state-contradiction-audit`, cut **after PR1 merges**. See the barrier at the bottom.

## Pattern Survey

### Analogous Features

- `scripts/assign_team_states.py:580` — `build_snapshot(sb, use_tier_a, workers, only_team=None)`.
  A first `decide` pass with an empty association map (`:614-618`) yields `disputed`; `:622` adds
  `stateless`; `:623` sets `candidates = sorted(disputed | stateless)`. **There is no budget
  anywhere on this path** — `:626-639` probes every candidate.
- `scripts/assign_team_states.py:611-612` — the `only_team` branch is the existing precedent for
  probing a team no free tier disputes. This generalises it from one id to a derived set.
- `scripts/assign_team_states.py:641-648` — the second `decide` pass, filtered with
  `only_team in (None, d["team_id"])`. That filter is the shape audit mode reuses.
- `scripts/repair_out_of_board_cohorts.py:96-97` — `--limit` applied when *selecting* the paid
  population. **Its idiom is `rows[:limit] if limit else rows`, which treats 0 as "no limit".**
  Do not copy that; see step 5.
- `scripts/assign_team_states.py:774-787` — `--fills-only` filters *before* `--limit`,
  deliberately, guarded by `tests/unit/test_assign_team_states.py:365`.

### Reusable Utilities

- `scripts/assign_team_states.py:284` — `build_club_index(teams)`, the only existing per-club
  aggregate. It counts `state_code`, **not** `state_source`, so the anchor index is a new sibling.
- `:154` `club_key` (placeholders key to `""`); `:175` `fetch_live_teams` (selecting exactly
  `team_id_master,team_name,club_name,state_code,state` at `:182` — **`state_source` is not
  selected**, and no Python in the repo reads that column today); `:196` `fetch_revert_blocks`
  and `:221` `fetch_queue_rows` (both hand-roll the `PAGE_SIZE` loop a new reader needs);
  `:242` `fetch_gotsport_aliases`; `:402` `probe_associations`; `:462` `probe_is_unusable`;
  `:480` `decide`; `:566` `_decision`; `:596` the `fetch_revert_blocks` call; `:678`
  `apply_decision`; `:696` `queue_decision`; `:734` `mirror_rankings`; `:758` `apply_snapshot`;
  `:843` `summarize`; `:1040` the `build_snapshot` call in `main()`.
- `:138` `CANADIAN_PROVINCES`, consulted by `decide` at `:492`.
- **`probe_is_unusable` (`:462`) already encodes the durable/transient split** this plan needs:
  it counts an outcome as a failure when it `startswith(("http", "request failed", "unparseable"))`.
  Step 3 reuses that same tuple rather than hand-listing the transient outcomes.

### Convention Anchors

- **The snapshot decides, `--execute` replays.** A new candidate source must widen
  `build_snapshot`'s probe set, not add a parallel write path.
- **Where a budget goes**: paid-call budgets bound *selection*; `--limit` bounds *writes*
  (`:1003`, sliced at `:786-787`). Negative-limit guard at `:782-785`.
- **Error-message style**: `:1026` and `:1033` in `main()`.
- **Nothing under `src.scrapers` at module scope** — AST test at `tests/unit/test_assign_team_states.py:270-286`.
- **Test structure**: no Supabase double. `team(**fields)` (`:32`), `decision(...)` (`:44`), and
  `replay(monkeypatch, decisions, ...)` (`:294-311`), which monkeypatches the DB-touching
  functions and drives the real `apply_snapshot`.
- **Derive a guarded list, never hand-write one** — `tests/unit/test_placeholder_clubs.py:93-150`.
- **The reference docs have no gate.** `tests/unit/test_agent_doc_references.py:42` globs
  `.claude/skills/*/SKILL.md` only, not `references/*.md`. That prose must be fixed by hand.
- **`check_state_skill_assumptions.py` does not cover candidate selection.**
  `check_decision_rules` (`:191`) drives `decide` for R7, R6, name-corrections, the reported-state
  guard, R9 and R17; the file contains no reference to `build_snapshot` or candidate selection.

### Proposed Alignment

Add the contradiction set as an alternative candidate source inside `build_snapshot`, keep it
deterministically ordered, and apply the probe budget to that list *before*
`fetch_gotsport_aliases`. `_decision`, `apply_snapshot`, the queue, the ledger and
`mirror_rankings` need no change. Four genuine deviations: `fetch_live_teams` must select
`state_source`; the `decisions` list must be scoped **and restricted to Tier A answers**; the
snapshot gains reporting keys; and the reference prose must be corrected by hand.

## Resolved decisions

| Decision | Choice | Why |
|---|---|---|
| What audit mode may write | **Only decisions backed by a mapped Tier A answer** | A contradiction candidate always has a stored state, so every decision is a correction — and R5 (`:558`) auto-applies corrections from A *or B*. Without this restriction, a candidate whose probe never answered gets a Tier B correction auto-applied on exactly the clubs the report's false-positive table shows are unreliable. |
| Corrections auto-apply or queue | **Auto-apply, after the gates that outrank R5** | A probe that agrees produces no decision (`:532-533`). R17 (a reverted proposal, `:538`) and R8 (stored `DC`, `:544`) queue *before* Tier A's exemptions are reached, so a Tier A hit on either still goes to review. Every write is ledgered and reversible. |
| Scheduled or operator-run | **Operator-run only, no workflow** | The 1,210 is a backlog, not a flow. A scheduled job would need `ZENROWS_API_KEY` plus a much heavier install than `fill-team-states-weekly.yml`'s five packages. |
| The "≥2 anchors" refinement | **Order by it, never filter** | Untested. Ordering spends the budget on the strongest evidence first and measures the idea; filtering would exclude real fixes and teach us nothing. |
| Probe set | **Its own run** | `--audit-contradictions` probes the contradiction set *instead of* `disputed \| stateless`. |
| Re-probe window | **90 days effective, `--reprobe-after-days`, unset by default** | A GotSport registration changes at season boundaries at most, and the backlog drains in one uncapped run, so the window only has to outlast the gap between capped runs. The flag's argparse default is `None`, not 90: the flag is rejected outside audit mode, and with a literal default an omitted flag is indistinguishable from an explicit one, so that check would reject every normal run. The effective 90 is derived inside audit mode. |
| What the window does | **Suppresses *and* caches** | A recent durable outcome keeps a team off the probe list; a recent `mapped` outcome additionally seeds its answer into `association_states`, so an answer already paid for still produces its decision. Suppressing without caching is what strands an aborted run's answered teams (step 3). |

## Validated scope

Measured against production 2026-08-31 using the tool's own `club_key` semantics:

| | Teams |
|---|---|
| Candidates matching the rule | 1,210 |
| …that store a Canadian province (R7 returns `None`; the call buys nothing) | 37 |
| **Selected after the Canadian exclusion** | **1,173** |
| …already in `disputed`, so a full sweep probes them too | 457 (39%) |
| …**marginal — reachable no other way** | **716** |
| …expected to carry a GotSport alias (~95%, from 143 of 150 sampled) | **≈1,110 paid calls** |
| …that store `DC` (R8 queues rather than applies — kept deliberately, step 3) | 23 |
| Anchored by 2+ confirmed club-mates | 622 |
| Anchored by exactly 1 | 588 |

**Selected candidates are not paid calls.** Only alias-bearing teams reach
`probe_associations`, because `fetch_gotsport_aliases` (`:242`) returns only the teams it finds.

The 39% overlap was measured by intersecting the candidate set with the decisions in workflow
run 33419639457's snapshot. Whether it falls evenly across the 1-anchor and 2+-anchor buckets is
unmeasured; the first uncapped run reports it.

## Implementation Steps

1. **Select `state_source` in `fetch_live_teams` (`:182`)**
   - Add `state_source` to the `.select(...)` list; note in the docstring that this is the first
     Python reader of that column.

2. **Add `build_anchor_index(teams)` beside `build_club_index` (`:284`)**
   - Mirror its shape: iterate teams, key on `club_key(team.get("club_name"))`, skip falsy keys.
   - Consider only teams with `state_source == "tier_a"` and a non-empty `state_code`.
   - Return `Dict[str, Tuple[str, int]]`: club key → `(the one confirmed state, how many teams
     confirm it)`. A club whose confirmed teams disagree is **omitted**, not resolved.

3. **Add `fetch_recent_probes(sb, cutoff)` and `contradiction_candidates(...)`**
   - `fetch_recent_probes(sb, cutoff) -> Dict[str, Tuple[str, Optional[str]]]` returns
     `team_id_master → (latest qualifying outcome, reported_state_code)` for probes newer than
     `cutoff`. Place it beside `fetch_revert_blocks` (`:196`) and `fetch_queue_rows` (`:221`) and
     hand-roll the `PAGE_SIZE` loop — `team_state_probe_log` passes the 1,000-row PostgREST cap
     after two runs.
   - **Page with `.order("id")` ascending, last-write-wins per team — the `fetch_queue_rows`
     (`:221`) idiom, not `fetch_revert_blocks` (`:196`).** The two differ in exactly the way that
     matters: `fetch_revert_blocks` builds a *set*, so order is irrelevant to it, while this
     reader keeps the latest row per team in a *dict* and therefore needs both a deterministic
     "latest" and stable `.range()` paging. The migration's `(team_id_master, probed_at DESC)`
     index serves the lookup, not the paging order.
   - **Only durable outcomes qualify.** An outcome suppresses a re-probe unless it
     `startswith(("http", "request failed", "unparseable"))` — the same tuple
     `probe_is_unusable` (`:462`) already uses to decide a run was blocked rather than quiet.
     The reason is concrete: that function aborts a run when more than 20% of calls fail, and by
     then every id in the batch already has a row. An outcome-blind window would make the
     re-run skip exactly the teams the WAF blocked, for 90 days, and report a smaller candidate
     set instead of an error.
   - `contradiction_candidates(teams, anchor_index)` returns `List[Tuple[str, int]]` —
     `(team_id_master, anchor_count)` — ordered by `(-anchor_count, team_id_master)`: strongest
     evidence first, deterministic for a slice.
   - Include a team only when: its club is in `anchor_index`; its `state_code` is non-empty and
     differs from the anchor state; and its `state_source` is not already `tier_a`.
   - **It does not take the recency map and does not suppress.** Suppression belongs to a second,
     equally pure helper: `probe_list(candidates, recent, probe_limit) -> List[str]`, which drops
     any candidate whose recent outcome is durable and then applies the budget, returning the
     ordered ids to probe. `build_snapshot` calls `contradiction_candidates` then `probe_list`.
     Two small pure functions rather than logic inline in `build_snapshot` is what lets step 7
     test the suppression and the slice without a Supabase double. A prototype of the suppress-inside-selection
     shape was built and run (2026-08-31): after an aborted run with 8 `mapped` and 2 `http 403`
     outcomes, the next run produced **decisions for the 2 transient teams and nothing at all for
     the 8 already answered**, because they were no longer candidates and the decision set is
     scoped to candidates. It raised no error and reported nothing — eight corrections silently
     not made.
   - **Exclude a stored Canadian province** (`CANADIAN_PROVINCES`, `:138`) — `decide` returns
     `None` outright at `:492`, so the call buys nothing. 37 teams.
   - **Do not exclude stored `DC`** (23 teams). R8 (`:544`) queues rather than applies, which is
     not nothing: the operator gets a review row carrying the provider's answer, and R8 exists
     because DC associations report MD, which is a judgement a person should make. That is the
     deliberate contrast with the Canadian exclusion.
   - Placeholder clubs fall out because `club_key` returns `""`; assert it in a test.

4. **Wire it into `build_snapshot` (`:580`)**
   - Add `audit_contradictions: bool = False`, `probe_limit: Optional[int] = None`,
     `reprobe_after_days: Optional[int] = None`. **The 90-day default is applied inside the audit
     branch, not in the signature and not in argparse.** `main()` always passes the parsed value,
     so a literal signature default never applies and `None` would reach `timedelta(days=None)` —
     a `TypeError` on the very first command PR2 Verification runs.
   - Build the anchor index alongside `build_club_index` / `build_locality_index` and print its
     size, matching the `console.print` lines at `:592-598`.
   - When `audit_contradictions`: call `fetch_recent_probes`, set `candidates` from
     `contradiction_candidates(...)` **instead of** `sorted(disputed | stateless)`, and **skip
     the first `decide` pass entirely** (`:614-618`) — it walks every team to build a `disputed`
     set this mode never uses.
   - **Three sets, not two.** This is the shape a prototype settled on 2026-08-31 after the
     two-set shape lost eight corrections silently:

     | Set | How it is built | What it is for |
     |---|---|---|
     | **Candidates** | `contradiction_candidates(teams, anchor_index)` — no recency filter | the population, and the scope of `decisions` |
     | **Probe list** | candidates minus any team whose recent outcome is **durable**, then sliced by `--probe-limit` | what costs money |
     | **Decision set** | candidates that have an answer in `association_states`, from this run's probe **or** from the cache | what gets written |

   - Build `association_states` from the **cache first** — every recent `mapped` row's
     `reported_state_code` — then add this run's probe answers on top. That ordering is what
     makes an aborted run's answers survive: `probe_is_unusable` fires at >20% failures, so up to
     80% of an aborted batch can be `mapped` when the run exits at `:639`, before the decide pass
     at `:641-648` and before any snapshot is written, and PR1 has already flushed those rows.
     The same orphan arises when `apply_snapshot` skips a decision whose pre-image moved.
   - Observed on the prototype: with 8 cached `mapped` and 2 transient, the next run probes 2 and
     decides 10 — the 8 for free. With `--probe-limit 3` it probes the same 2 and still decides
     10, because the budget bounds the probe list and the cache is not in it.
   - A candidate with a recent **durable but non-`mapped`** outcome (`no such team (404)`,
     `no association in payload`, `unmapped code <raw>`, `no gotsport alias`) is in neither the
     probe list nor the decision set. Count and report those as skipped rather than dropping them
     silently — observed: all 10 candidates skipped, 0 probed, 0 decided, on an all-404 fixture.
   - `no gotsport alias` is durable, so a candidate with no alias is not re-checked until the
     window expires. That is deliberate — it is what stops ~60 alias-less teams occupying the
     head of the list forever — and the cost is a bounded delay before a newly-added alias is
     noticed, not a permanent hole.
   - The staleness is bounded and safe. `decide` compares the proposal against the state as of
     the snapshot, and `apply_decision` carries the pre-image as a predicate, so a cached answer
     for a team that has since moved is skipped and reported rather than written blindly.
     Observed: a cached `mapped` answer that **agrees** with the stored state yields no decision
     at all (`decide` returns `None` at `:532-533`), and the team stays suppressed for the window.
     It is **re-paid once the window lapses**: an agreeing probe writes nothing, so `state_source`
     never becomes `tier_a`, the team stays a candidate, and its ledger row eventually ages out.
     Sized from the report's own funnel — 1,173 selected → ~1,118 alias-bearing → ~1,009 answered
     → 45.7% agreeing — that is roughly **460 re-paid calls** on a run more than 90 days after the
     last. That is the deliberate cost of a window rather than permanent suppression; do not build
     permanent suppression instead.
   - Apply `probe_limit` by slicing the **probe list** — candidates minus durable-suppressed —
     *before* `fetch_gotsport_aliases` (`:628`), then write the no-alias ledger rows PR1 step 3
     specifies. Slicing the candidate list instead would cap the decision set too, discarding
     cached answers that cost nothing to use.
   - **Scope and restrict `decisions`.** `:641-648` filters only on
     `only_team in (None, d["team_id"])`. In audit mode it must additionally keep only decisions
     whose team has a **mapped answer in `association_states`**. Scoping alone is not enough:
     it would still emit Tier B corrections for unanswered candidates, which R5 auto-applies.
   - **`--execute --snapshot audit.json` therefore applies only Tier A audit decisions**, and
     `--limit N` slices those. Say so in the flag's help text.
   - **Zero the diagnostics.** `undecidable` and `undecidable_and_visible` (`:653-658`) count
     stateless teams absent from `decisions`. In audit mode no stateless team is probed, so the
     count would be an artifact of not asking, and `ranked_and_active` would spend ~26 PostgREST
     round trips on a list the operator must ignore. Set `undecidable` to `0` and
     `undecidable_and_visible` to `[]`, skip the `ranked_and_active` call, and have `summarize`
     print "not examined in audit mode".
   - **Snapshot keys.** Write `mode` on **every** snapshot (`"normal"` or `"audit"`), and add, in
     audit mode:

     | Key | Holds |
     |---|---|
     | `candidates_selected` | size of the **candidate** set — the unfiltered contradiction population |
     | `probed` | the **ordered ids actually handed to `fetch_gotsport_aliases`** — what the starvation check asserts against |
     | `aliases_found` | how many of `probed` had a GotSport alias |
     | `probes_answered` | mapped answers obtained by **this run's probe** only |
     | `cached_answers` | mapped answers taken from the ledger, costing nothing |
     | `skipped_durable` | candidates kept off the probe list by a recent durable non-`mapped` outcome |
     | `anchor_counts` | `team_id → anchor count`, for the bucket comparison |
     | `answered` | `team_id → bool` |

     Every reader uses `snapshot.get("mode", "normal")` so snapshots written by the old code still
     replay. Note beside `tier_a_probed` (`:664`, `len(association_states)`) that in audit mode it
     now counts cache-seeded entries too and is **not** a paid-call count — `aliases_found` is.
   - **`--team` wins, and the Tier A restriction does not apply to it.** With both flags,
     `only_team` still selects the candidate and the run still probes that one team, but the
     audit-mode "mapped answer required" filter is skipped — otherwise the one-off route
     `failure-modes.md` documents would start printing "No decision" for a team whose Tier B, C
     or E decision is exactly what the operator asked for. `--probe-limit` and
     `--reprobe-after-days` are inert on that path.
   - **The abort moves after the decisions in audit mode.** `probe_is_unusable` (`:462`) reads
     only *this run's* outcomes and `build_snapshot` exits at `:633-639` before the decide pass at
     `:641-648`. So a retry that also fails strands the cache exactly as the first run did: 7
     cached `mapped` plus 3 transient, retried with `--probe-limit 3`, probes the 3, sees 100%
     failure, exits, and emits none of the 7. In audit mode, therefore, a blocked probe **warns
     loudly and exits non-zero *after* building and writing the cache-backed decisions**. That is
     safe only because audit mode already drops decisions lacking a mapped answer, so nothing
     unverified rides along. **Normal mode keeps today's exit-before-decisions behaviour.**
     (The gap came from review, not from running it: the first prototype's Case 1 assumed the
     retry succeeds. The fix was then put back through the prototype — with the abort ordered
     first, a retry of 7 cached + 3 transient at `--probe-limit 3` emits **0** decisions; with it
     ordered last, **7**, plus the non-zero exit.)
   - **Preserve**: the `only_team` branch and comment (`:606-612`), the `tier_d_ready` warning
     (`:602-604`), the `fetch_revert_blocks` call (`:596`), the histogram itself (`:631-632`), and
     the existing snapshot keys (`created_at`, `actor`, `live_teams`, `tier_a_probed`,
     `tier_d_available`, `undecidable`, `undecidable_and_visible`, `decisions`).

5. **Add the CLI flags in `main()` (`:996-1016`)**
   - `--audit-contradictions`, `--probe-limit N`, `--reprobe-after-days N`, next to
     `--no-tier-a`. **`--reprobe-after-days` takes `default=None`**, and the effective 90 is
     derived inside audit mode. A literal `default=90` would make an omitted flag
     indistinguishable from an explicit one, so the conflict check below would reject every
     normal run.
   - **`--probe-limit 0` means probe nothing.** Use an explicit `if probe_limit is not None`
     test, never the truthiness idiom at `repair_out_of_board_cohorts.py:97`, which treats 0 as
     "no limit" and would spend the entire paid population.
   - Reject a negative `--probe-limit` the way `--limit` does at `:782-785`.
   - `--audit-contradictions` with `--no-tier-a` is a contradiction in terms; `--probe-limit` or
     `--reprobe-after-days` without `--audit-contradictions` silently caps or alters a sweep that
     has no budget by design. All three exit with a message in the style of `:1026` / `:1033`.
     `--team` with `--audit-contradictions` is **not** rejected — see step 4; `--team` wins.
   - **Validate every flag conflict before the credential guard at `:1018-1020`.** CI sets no
     `SUPABASE_URL` / `SUPABASE_KEY`, so anything after that guard exits 1 for every argv and a
     test asserting only the exit code cannot fail.
   - Thread the three arguments through the `build_snapshot` call at `:1040`.

6. **Report the audit in `summarize` (`:843`)**
   - Read the mode as `snapshot.get("mode", "normal")`.
   - When `"audit"`, print: candidates selected, aliases found, probes answered, Tier A decisions
     produced, and how many of those queued rather than applied (R17/R8).
   - Print the hit rate **per anchor bucket** — 1 anchor vs 2+ — with **`probes_answered` in that
     bucket as the denominator, not candidates selected**. Using selected would dilute each
     bucket by its no-alias and no-answer teams and confound the very comparison the ordering
     decision exists to enable.
   - Guard every rate against a zero denominator; `--probe-limit 0` and a fully-drained candidate
     list both produce one.
   - Note that a `--probe-limit` run draws only from the 2+-anchor cohort, because candidates sort
     by `-anchor_count`, so the bucket comparison is meaningful only on an unlimited run.

7. **Tests in `tests/unit/test_assign_team_states.py`**
   - Pure-function, in the existing `Counter`/dict style:
     - `build_anchor_index`: a unanimous club yields `(state, count)`; a club whose confirmed
       teams disagree is omitted; a team without `state_source == 'tier_a'` never anchors.
     - `contradiction_candidates`: a contradicting team is selected; one agreeing with the anchor
       is not; an already-`tier_a` team is not; a stored Canadian province is not; a stored `DC`
       team **is**; a placeholder club is not. **A recently-probed team still is** — candidacy
       does not consider recency; that is the probe list's job, and asserting it here is what
       stops the two-set regression the prototype caught.
     - `probe_list`: excludes a team with a recent durable outcome, keeps one with a recent
       transient outcome, applies `--probe-limit` to what remains, and preserves anchor order.
     - `fetch_recent_probes` against a **two-page fixture**, since every action-layer test
       monkeypatches it and no capped live command is guaranteed to cross the 1,000-row boundary:
       one team represented on **both** sides of the boundary, asserting the ranges requested are
       `0-999` then `1000-1999` and that the globally latest qualifying row wins — which is what
       `.order("id")` plus last-write-wins buys.
     - **Outcome-aware recency**: a team whose last outcome was `mapped` or `no such team (404)`
       is suppressed; one whose last outcome was `http 403`, `request failed (ConnectionError)`
       or `unparseable payload` is **not**.
     - Ordering: a 2-anchor club sorts ahead of a 1-anchor club; ties break on `team_id_master`.
   - **Action-layer tests, in the `replay()` style at `:294-311`** — the half that spends money,
     which no pure-function test can cover. Monkeypatch `fetch_live_teams`, `fetch_revert_blocks`,
     **`fetch_recent_probes`**, `fetch_gotsport_aliases` and `probe_associations`, call the real
     `build_snapshot(audit_contradictions=True, probe_limit=N)`, and assert:
     - the exact id list handed to `fetch_gotsport_aliases` is the first N of the **probe list**
       in anchor order — this fails if the selector is never called, if the code falls through to
       `sorted(disputed | stateless)`, if the slice happens after the alias lookup, or if the
       slice is taken on candidates rather than the probe list;
     - a candidate with a cached `mapped` outcome is **absent from that id list but present in
       `decisions`** — the assertion the prototype's failing two-set run would not satisfy;
     - `probe_limit=0` calls neither `fetch_gotsport_aliases` nor `probe_associations`, **and
       still emits decisions from a warm cache** — the budget bounds new probes, not the decision
       set. Use an explicitly **empty** recency fixture for the genuine no-decision case;
     - `decisions` contains only candidates **with a mapped answer** — a candidate that got no
       answer produces no decision even when its club index would support a Tier B correction;
     - `undecidable == 0` and `undecidable_and_visible == []`;
     - `mode == "audit"`, and a normal run writes `mode == "normal"`. Add `ranked_and_active` to
       the monkeypatch list for that normal-mode case: it is reached at `:658` whenever the
       fixture holds a stateless team no tier decides, and `sb=None` would raise `AttributeError`.
     - **`--team` overrides everything.** A fixture naming a team that is *not* an audit
       candidate, carrying a recent durable outcome, with `probe_limit=0`: the named id is still
       probed and its non-Tier-A decision is still emitted. Without this, an audit-candidate
       branch or a `probe_limit == 0` shortcut could suppress the explicitly requested team while
       every other test passes.
   - **Repeated-run regression**, with the first run's outcomes fed back through
     `fetch_recent_probes`. Unconditional disjointness would be the wrong oracle: transient
     outcomes are deliberately re-eligible, so when failures stay at or below the 20% abort
     threshold the run completes and deterministic ordering re-selects those same ids — which is
     correct. Assert instead:
     - an id whose first-run outcome was **durable** (`mapped`, `no such team (404)`,
       `no association in payload`, `unmapped code <raw>`, `no gotsport alias`) is **absent from
       the second run's probe list** — and **still present in its candidate set**, because
       candidacy does not consider recency. Asserting absence from the *candidate* set is the
       two-set regression the prototype exposed, and a test written that way would enforce it;
     - an id whose first-run outcome was **transient** (`http <N>`, `request failed (<Type>)`,
       `unparseable payload`) **may recur in the probe list**, and the test must not fail when it
       does;
     - an id whose first-run outcome was **`mapped`** is absent from the second run's **probe
       list** but still present in its **decisions**, seeded from the cache — this is the case
       that proves an aborted run's answers are not stranded;
     - full probe-list disjointness only on an all-durable fixture;
     - **a retry that also aborts still emits its cached decisions**: a fixture whose probe
       outcomes are >20% failures asserts that the run exits non-zero *and* that the cache-backed
       decisions were built and written first.
     Together these are what prove the ledger cures the starvation it was added for.
   - A guard on the `.select(...)` projection at `:182` asserting `state_source` is requested, so
     dropping it is caught rather than silently disabling every anchor.
   - Flag-conflict tests assert on the **emitted message**, not the exit code. Include the
     inverse: an **ordinary invocation with no audit flags at all** passes validation, which is
     what fails if `--reprobe-after-days` is given a literal argparse default instead of `None`.
   - Verify each new guard by reverting it against a scratch copy before trusting it.

8. **Correct the operator docs — by hand, since nothing gates them**
   - `.claude/skills/assigning-team-states/references/failure-modes.md:23-28` — "a sweep never
     looks at a team nothing disputes" and "**Fixing it:** `--team <uuid>` on any one of them"
     are what this change falsifies. The contradiction audit is now the systematic remedy; keep
     `--team` as the one-off route.
   - `.claude/skills/assigning-team-states/references/evidence-tiers.md`, Tier A — "It is only
     probed for teams something else already disputes" becomes false. Replace with the three ways
     a team gets probed: the disputed/stateless sweep, the contradiction audit, and `--team`.
   - `.claude/skills/assigning-team-states/SKILL.md:63` — name the audit's ≈1,110 calls beside the
     sweep's ~6,200, and add a step covering when to run it and what hit rate to expect.
   - `tests/unit/test_agent_doc_references.py:42` globs `.claude/skills/*/SKILL.md` only, so
     **neither reference file has any gate**. Re-read both after editing.
   - Add an assertion to `scripts/check_state_skill_assumptions.py` `check_decision_rules` (`:191`)
     that `contradiction_candidates` selects a team no free tier disputes — otherwise the
     corrected Tier A prose ships unguarded.
   - **Re-measure the three drifted figures while you are in these files.** Running
     `check_state_skill_assumptions.py` on 2026-08-31 passed every assertion but reported
     `teams_without_state` 3,068 against a recorded 2,543 (+21%), `ledger_rows` 8,055 against
     1,273 (+533%) and `queue_pending` 542 against 50 (+984%), and ends with "Re-measure the
     prose." Those baselines live in the checker's own `measure()` (`:290`); update them and any
     prose quoting them in the same pass.

## PR2 Verification

- `python -m pytest tests/unit/test_assign_team_states.py -q` — new cases pass; each new guard
  fails when reverted against a scratch copy.
- `python -m ruff check src/ scripts/ config/ tournament_intake.py dashboard.py` — clean.
- `python -m pytest tests/ --ignore=tests/test_enhanced_pipeline.py -q` — no new failures. A
  *pre-existing* failure in `test_agent_doc_references.py` appears only when another session has
  uncommitted skill docs in the shared checkout; it does not occur on a clean worktree or in CI.
- `python scripts/check_state_skill_assumptions.py` — assertions pass, including the new one.
- **Decide-only run — no team-state or review-queue writes, but paid-probe observations ARE
  persisted:**
  `python scripts/assign_team_states.py --audit-contradictions --probe-limit 50 --out audit.json`
  Expect `candidates_selected` ≈ **1,173** (the unfiltered population — only the probe list is
  sliced) with `probed` ≈ **50**, ~47 of those carrying an alias, every decision's team holding a
  mapped answer, `undecidable: 0`, `mode: "audit"`, and ≈ **50** `team_state_probe_log` rows —
  one per *probed* team including its no-alias members, **not** one per selected candidate.
  Ledgering all 1,173 would stamp ~1,123 never-probed teams with a durable outcome and suppress
  the whole audit for 90 days.
- **Zero budget:** `--audit-contradictions --probe-limit 0 --out zero.json` makes no alias
  lookup and no probe calls, and its summary does not divide by zero. Run immediately after the
  command above it will still produce **decisions from the warm cache** — that is correct, and an
  implementation returning early and discarding them is the bug this checks for.
- **Conflicts:** `--audit-contradictions --no-tier-a`, `--probe-limit 10` alone, and
  `--reprobe-after-days 30` alone each print their message and exit non-zero — check the message
  text, since the credential guard would also exit 1.
- **Small live batch, verified from the database rather than the run's output:**
  `python scripts/assign_team_states.py --execute --snapshot audit.json --limit 25`
  then the `team_state_audit` query from the skill's Step 4. `state_source = 'tier_a'` on all 25
  is now the correct assertion, because audit mode emits nothing else.
- **Starvation cure:** run the capped decide-only command twice in succession and compare the
  two snapshots' **`probed`** lists, not their candidate sets — a durably-answered team stays a
  candidate by design. Every team the first run resolved durably (`mapped`, `404`,
  `no association`, `unmapped code`, `no gotsport alias`) must be absent from the second
  `probed`, and the second must reach ids the first never probed. Teams whose first outcome was
  transient may legitimately reappear; that is the policy working, not a failure.
- **Rollback:** `revert_team_states('assign_team_states', <start>, <end>, '<you>', NULL, 500, false, '<why>')`,
  looping on `last_team_id`.

## Context Files

- `scripts/assign_team_states.py` — the whole file. The module docstring (`:1-60`) carries the
  design rules this must not break, and `:33-40` is one of the dry-run claims PR1 falsifies.
- `.turbo/reports/2026-08-31-targeting-the-gotsport-probe.md` — the measurements this rests on.
- `.turbo/handoff/2026-08-29-team-state-assignment.md` — the migration traps PR1 must respect.
- `supabase/migrations/20260829120000_add_team_state_provenance.sql` — the sibling provenance
  tables, their triggers, `apply_team_state`, and at `:190-208` the RLS pair PR1 copies.
- `tests/unit/test_team_state_provenance_migration.py` — the existing migration guard PR1 extends
  by one line, rather than reimplementing.
- `tests/unit/test_assign_team_states.py` — `team()`, `decision()` and `replay()`.
- `tests/unit/test_placeholder_clubs.py` — the derive-a-guarded-list convention and `club_key`.
- `.claude/skills/assigning-team-states/references/failure-modes.md` and `evidence-tiers.md` —
  the prose this change makes stale, neither of which has a test gate.

## Branches, and the barrier between them

`C:/PitchRank` is a **shared checkout** and was, at plan time, on another session's branch with
that session's work staged in the shared index. Do not branch or commit there. Work in a
worktree, and when staging name paths explicitly — never `git add -A`.

**PR1** on `state-probe-ledger`, cut from `origin/main`.

**PR2** on `state-contradiction-audit`, cut from `origin/main` **after PR1 has merged**. PR2's
`fetch_recent_probes` reads a table PR1 creates, so:

- PR2 cannot be cut, and its live verification cannot run, until **PR1 is merged, its migration
  applied, and the migration ledger repaired**.
- Do not collapse the two into one branch. The migration is the reviewable unit that needs the
  `migration-reviewer` agent; the audit is the unit that needs the measured hit rate.

Before editing either, confirm the baseline:

```bash
git fetch --quiet && git rev-list --left-right --count origin/main...HEAD
```

Expect `0 0`. If it is not, rebase onto `origin/main` before starting.
