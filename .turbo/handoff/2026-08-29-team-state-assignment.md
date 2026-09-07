# Handoff: Team state assignment and correction

## What this is

Making `teams.state_code` evidence-driven, auditable and reversible. Today the column
is write-once in practice, nothing can correct a wrong value, and there is no provenance
or rollback. Four PRs; two are done.

**The spec is the source of truth and it is committed**: `.turbo/specs/team-state-assignment.md`
(36 requirements, R1–R36, each assigned to exactly one PR). Supporting research with the
verified numbers: `.turbo/reports/2026-08-28-state-code-landscape.md`. Both survived four
review rounds. **Read the spec first; do not re-derive it.**

## Status

| PR | What | State |
|----|------|-------|
| PR1 | Repair the dead club/state workflow | **Merged** (#1054, `82cfffa6e`) |
| PR2 | Source fixes: discovery state, TGS event name | **Merged** (#1055, `b391194ca`) |
| PR3 | Migration: provenance, audit ledger, queue, `tgs_events` | **Merged** (#1057) and **applied** |
| PR4 | The assignment tool, skill and review queue | **Merged** (#1058, `c091a1282`) and **applied** |

PR1 was verified end to end on a real runner (run 33235368592): all steps green, Step 6
correctly skipped. The weekly chain is alive again after being fully dead 2026-08-20 →
2026-08-29.

## Start here

All four PRs are merged, all three migrations applied, and **the sweep has run in full**
(2026-08-30, actor `assign_team_states`, 18:36-19:4x UTC, 6,439 writes from one snapshot).

What is left is ongoing rather than a build:

- **600 rows pending in the review queue.** Work them in the dashboard's
  **State Review Queue** section. Rejecting is what stops a refused proposal returning.
- **1,925 teams no tier can decide** and that cannot be queued either, because a review
  row needs a proposal. None is visible on a state board. `--set` is the only path.
- **The migration ledger is repaired** (2026-08-30): all nine of `20260822000000`
  through `20260829210000` are recorded and match what is applied. It had been uniformly
  unrecorded, which was safe only by accident — `20260829210000` supersedes a function
  `20260829120000` defines, so recording part of the list would have let a `db push`
  re-run the older file and strip the board mirror out of `revert_team_states` in silence.

Undo for the sweep, if it is ever needed:

    SELECT * FROM revert_team_states('assign_team_states',
      '2026-08-30 18:30+00', '2026-08-30 23:59+00', '<you>', NULL, 500, false, '<why>');

Loop on `last_team_id`. It leaves the 32 hand calls alone: those are stamped `operator`.

### What the sweep did, measured

197,925 of 200,270 live teams now carry a state (98.8%), and 6,731 carry provenance:
5,873 from GotSport registration records, 689 from club evidence, 102 from a place learned
in the name, 32 by hand, 36 from names and conflicts. The boards agree with `teams` to
within zero Active rows.

**The provider check earned its cost.** Where it and the club both answered on 5,536
teams they agreed 97.4%; the 146 disagreements are writes the free sweep would have got
wrong, and it decided 158 teams no other tier reached. Examples no club count could
settle: *Ohio County Soccer* is in Kentucky; *Bulls Rush (SC)* was stored NC.

### Whole clubs found filed under the wrong state

Four, all invisible to every tier because each club agreed with itself. This is the shape
to keep hunting; `scratchpad`-style club sweeps found them by asking of each club whether
its name points somewhere none of its teams are stored.

| Club | Was | Now | Teams | Settled by |
|---|---|---|---|---|
| Boise Timbers \| Thorns | WY/CA | ID | 6 | provider record |
| Hawaii Rush | WA | HI | 17 | operator; "Kauai Rush" is decisive |
| Legends FC Arizona | CA | AZ | 11 | operator; no provider record exists |
| TCSL (Twin Cities Soccer League) | IL/IA/ND/SD | MN | 162 | provider record, per team |

TCSL was the largest single mislabel in the database and was a documented deferred item.
Two of its teams are genuinely Wisconsin (*Western Wisconsin*, a real border club) and a
bulk write would have created those errors; the per-team probe caught them. 23 remain in
IL with no provider record to confirm them.

**False positives are the norm in that hunt**, so never write from a name alone: Beaumont
is in Texas, Scarborough in Maine, Bethlehem in New York, Oregon is a city in Ohio,
Delaware is a city in Ohio and a county in Indiana, Georgia and Milton are towns in
Vermont. 26 of 27 candidate clubs I probed were correctly stored.

## Traps this project already paid for — do not rediscover these

1. **An RPC gets 8 seconds, hard.** `pg_db_role_setting` carries `statement_timeout=8s`
   for `authenticator` and has no `service_role` entry. `SET LOCAL statement_timeout`
   inside a function body is inert. Every bulk operation takes `(p_after, p_batch_size)`
   and returns a cursor; the caller loops. Model: `scripts/refresh_team_scrape_activity.py`.
   Do **not** copy `backfill_total_game_stats`, which is cancelled on every production run.

2. **A session GUC does not survive PostgREST.** Verified twice against production:
   `set_config(..., false)` on backend pid 3262723, then `current_setting` returned NULL
   on pid 3262724 the next request. The actor and action reach the trigger only via
   `set_config(..., true)` — transaction-local — inside the same function that does the
   `UPDATE`. Writes from other paths fall back to the role name with `action = 'external'`.

3. **Two triggers, not one.** Postgres rejects
   `CREATE TRIGGER … AFTER INSERT OR UPDATE … WHEN (OLD.…)` at creation. Ship
   `AFTER UPDATE … WHEN (OLD.state_code IS DISTINCT FROM NEW.state_code)` and
   `AFTER INSERT … WHEN (NEW.state_code IS NOT NULL)`, both calling one trigger function.
   The `WHEN` clauses are not optional: `teams` takes ~3,840 `last_scraped_at` writes a day.

4. **New tables are anon-writable by default.** `pg_default_acl` grants `arwdDxtm` to
   `anon` on every new public relation here. That is exactly how `team_merge_audit` and
   `team_link_audit` reached the security advisory. Enable RLS in the migration with the
   `<table>_deny_all` / `<table>_service_role_all` pair from
   `supabase/migrations/20240215000000_add_row_level_security.sql`.

5. **Do not copy `team_match_review_queue`'s CHECK.** It constrains confidence to
   `>= 0.75 AND < 0.90`, which rejects both confidences this design queues (0.90 and 0.95).

6. **Scripts run without the repo root on `sys.path`.** The hygiene workflows invoke
   `python3 scripts/x.py` and install only `supabase python-dotenv requests`, with no
   `PYTHONPATH`. A bare `from src...` raises `ModuleNotFoundError` on the runner while
   working locally. Use the `sys.path.append(str(Path(__file__).resolve().parent.parent))`
   pattern, and only for modules with no heavy imports.

7. **`ruff check --fix` runs on every Python edit and strips imports added before their
   use site.** Write the usage first, then the import, or write the whole file at once.

8. **`.turbo/` is tracked in this repo**, despite generic tooling assuming otherwise.

## The load-bearing product decision

A team's state means **where its club is based**, not where it plays. Every travel-derived
signal (opponents, venues) is corroboration only. This is why Step 6 of the weekly
workflow is switched off permanently, and why opponent dominance is a rejected tier.

Canadian provinces are legitimate data and are never flagged or corrected.

## Open, not blocking

- **41 of 69 club home states are unconfirmed.** The operator hand-confirmed four
  (`arizona arsenal soccer club`→AZ, `city sc`→CA, `soccer chance academy`→OR,
  `steel city fc`→PA), 4 for 4 with the analysis. The rest have proposed values. This
  reads naturally as a PR4 review of `src/utils/club_state_registry.py`; it does not
  block PR3. It is the only external ground truth this problem has.
- **Four more clubs confirmed by the operator on 2026-08-29**: `legends fc (ca)`→CA,
  `socal reds fc`→CA, `nj14 soccer club`→NJ, `hex fc`→PA. **None needs a registry
  entry** — each is cleanly single-meaningful-state once `club_name` is normalized
  (CA 519/AZ 7, CA 240/AZ 7, NJ 27/MD 2, PA 135/NJ 1), so Tier B reaches all four on its
  own. They are worth carrying as fixture cases: the operator's answer and the computed
  answer agree, independently, on all four.
  Their minority buckets are the live question — 7 AZ under `legends fc (ca)`, 7 AZ under
  `socal reds fc`, 2 MD under `nj14`, 1 NJ under `hex fc`, every one of them `txt0`.
  **Do not blind-correct them to the club's home.** Establish first whether each is a
  mislabelled state or a correctly-stated team wearing the wrong `club_name`; the second
  wants a re-club, not a state correction, and the two are indistinguishable from
  `state_code` alone.
- **Group clubs on `lower(btrim(club_name))`, never the raw column.** Raw grouping split
  single clubs across case and whitespace variants and turned 3 genuine disagreements
  into 14 during the 2026-08-29 review. It is the same key the registry uses.
- **IMP-141** records the one thing PR2 deliberately left alone:
  `export_unknown_opponents.py` has the same broken resolver, but it feeds *matching*
  rather than creation, so fixing it shifts match-versus-create outcomes for ~6,400 teams
  a week with no test coverage. Wants a measured before/after.
- **IMP-140** records a dry-run label that reads as a live write.

## Working tree at handoff

`.turbo/improvements.md` is **uncommitted and contains two writers' work**: IMP-140 and
IMP-141 from this session, plus another session's archival of IMP-135. Do not stage it
wholesale. Another live session is also mid-edit on
`.claude/skills/merging-duplicate-teams/**`, `scripts/check_merge_skill_assumptions.py`
and `scripts/find_queue_matches.py`. **This checkout is shared — stage by explicit path,
never `git add -A`.**

## Next concrete action

Read `.turbo/specs/team-state-assignment.md`, then implement PR3 (the migration, R12–R18
and R26) on a branch off `origin/main`, following the "Data model" section and the traps
above. It changes no behaviour, so it can ship as soon as the migration reviewer is happy.
