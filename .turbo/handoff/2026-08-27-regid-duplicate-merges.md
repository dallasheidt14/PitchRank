# Registration-ID placeholder teams: names backfilled, 639 duplicates merged

**Date**: 2026-08-27 · **Actor**: `pitchrank-operator` · **Status**: batch complete, remainder held

## Root cause

`teams` held 13,626 rows named `unknown_<provider_team_id>`. They split cleanly by ID space:

| ID space | GotSport teams | Resolvable via `team_details` |
|---|---|---|
| below 3,000,000 (rankings team ID) | 168,426 | yes — 99.8% already named |
| 3,000,000+ (org_event registration ID) | 4,200 | **no — 0.2%**, 404s permanently |

The 3M+ values are **per-event registration IDs**, not team IDs — documented at
`src/scrapers/gotsport.py:2190`. `discover_teams_from_opponents.py` created teams keyed by
one, so `team_details` was never going to resolve them.

The event page is the only source that mints them, and it yields either identifier: a
registration ID ~90% of the time, the real team ID ~10%. The rankings page always yields the
real team ID.

**Age was never the discriminator.** `backfill_unknown_team_names.py` claimed pre-May-2026 IDs
were dead and defaulted `--created-after` to `2026-05-01`. Both ID spaces were minted across
the same March–April window, so that date filter separated nothing and hid 253 recoverable
teams — including all 168 that were publicly ranked under an `unknown_` name.

## What ran

1. **Name backfill** — `backfill_unknown_team_names.py --created-before 2026-05-01 --limit 300
   --delay 3`. 221 renamed, 32 genuine 404s, 1 unusable name, 0 errors. Zero publicly-ranked
   placeholders remain in the rankings ID space.
2. **Duplicate merge** — 639 Tier A pairs via `apply_vetted_team_merges.py` (25 first, verified,
   then 614). 639 merged, 0 failed.
3. **Stranded fixtures** — `enqueue_stranded_merge_fixtures.py --include-past --execute`.
   1 fixture enqueued (`Capo FC - 2015 Irvine`). Migration
   `20260822000000_resolve_merges_in_scrape_enqueue_rpcs.sql` is **not applied** to the
   database, so this step is still required after any merge batch.

## How Tier A was decided

Candidates came from game evidence, not names — the placeholder has no name to compare, and
`find_fuzzy_duplicate_teams.py` (which feeds `decide_team_merges.py`) is name-similarity based,
so it cannot generate these pairs at all.

A pair is proposed when both rows share `(game_date, opponent_uuid, own_score, opp_score)`, with
opponents resolved through `team_merge_map` and NULL-score fixtures skipped. Tier A additionally
requires every one of the placeholder's games matched, at least 3 of them, exactly one candidate
target, and that the two rows never played each other.

Verified end to end on `unknown_3686075` → `Challenge SC ECNL 2013`: six games, and each
opponent's own record shows the same result twice that day — one copy with `event_name` set
(org_event scrape), one without (rankings scrape). One match, imported twice.

Generator: `scratchpad/build_regid_merges.py`. Logs: `regid_merge_log_batch{1,2}.json`.
Proposed list: `data/exports/regid_tierA_proposed_merges.csv`.

## Held — these need a human decision, not a rule

| Held | Count | Why |
|---|---|---|
| Partial history matched | 280 | Placeholder has games the target lacks, which argues they are **not** the same row. Do not merge on the current evidence. |
| Played each other | 79 | Definitively different teams. Never merge; exclude permanently. |
| More than one candidate target | 27 | 2–4 equally-supported targets. No rule separates them. |
| Fewer than 3 scored games | ~1,000 | Never evaluated. A single shared 1-0 at a busy tournament is a realistic coincidence. |

`decide_team_merges.py` refuses **all** of these pairs and should not be used on them. Three
independent blockers, each an artifact rather than a judgment: `basics_disagree` compares club
strictly and every placeholder has `club_name = NULL`; it compares state strictly and 41% differ
because the placeholder's state is event-derived (a Colorado team stamped `MI` for a Michigan
showcase); and the `dates_a & dates_b` rule refuses on same-day play, which is precisely this
duplicate's signature.

## Remaining

3,553 registration-ID placeholders and 45 rankings-ID placeholders.

The only way to name the registration-ID rows is the org_event schedule page, reachable via
`GotsportScraper.extract_event_teams_by_bracket()` → `EventTeam(team_id, team_name)`. The live
ones sit across ~154 event pages. That scrape would also confirm the held tiers by giving a
second independent signal (name) to agree with the game evidence, and would name the ~1,800 rows
that have no duplicate at all. Deferred 2026-08-27 — the user declined the rescrape.

## Also found, not acted on

- `apply_vetted_team_merges.py:37` loads env from `.env.local`, which does not exist on this
  checkout. Its comment says a bare `load_dotenv()` "comes back empty" — no longer true, root
  `.env` now carries the Supabase keys. The script fails on credentials unless env is preloaded.
- 3 gender disagreements from the name backfill, written to
  `data/exports/unknown_backfill_mismatches_20260827_100337.csv`, deliberately not applied.
- `rankings_full` still holds the merged rows until the next `calculate-rankings.yml` run.
