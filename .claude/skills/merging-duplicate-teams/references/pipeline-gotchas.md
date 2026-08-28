# Pipeline behaviour around a merge

What `execute_team_merge` actually does, and the places downstream that do not expect it.

## Contents

- What a merge writes
- The RPC reports failure on success
- Resolve ids before counting anything
- Merged teams stop being scraped
- Merged teams lose their rank chart
- Which row survives
- Reverting

## What a merge writes

Four writes and an audit row: cascade any incoming `team_merge_map` rows, insert a
`team_merge_map` row, repoint `team_alias_map` to the canonical, set `is_deprecated = TRUE`,
and record a full JSONB snapshot of the deprecated row in `team_merge_audit`.

It does **not** touch `games` — `v_games_affected` is a count, not an update. Games stay
immutable and resolve to the surviving team at read time. It also copies no columns onto the
survivor, so any field populated only on the deprecated row disappears from the live team
(recoverable from the snapshot).

Because the snapshot is complete and games are untouched, a merge is genuinely reversible.

## The RPC reports failure on success

PostgREST cannot serialise the RPC's JSONB return and raises `JSON could not be generated`
even when the merge has committed. The real payload, containing `"success": true`, sits inside
the exception text.

`scripts/run_all_merges.py` and `scripts/apply_vetted_team_merges.py` both parse it out. Any
new caller must do the same. The danger is not the misreport but the log: a run that records
every merge as failed produces a revert file that is a silent no-op.

Verify a batch against the database — each intended row deprecated, its canonical matching,
no surviving row deprecated without a chain to explain it — rather than trusting the reply.

## Resolve ids before counting anything

Read games for a team **and** for every team already merged into it. A row that is the
canonical target of earlier merges reads as empty when counted by raw id, which removes the
evidence a decision depends on. In one batch this made a row holding 33 inherited games look
empty, nearly handing a 2008 squad's identity to the club's 2009 squad.

This applies to every derived signal, not just counts: shared dates, shared opponents and
season overlap are all wrong if computed on unresolved ids.

## Merged teams stop being scraped

`find_yesterday_null_score_teams` and `find_recently_active_teams` match games by the raw
`team_id_master` and then require `teams.is_deprecated = false`. After a merge neither side
satisfies both — the game names the deprecated row, which is filtered out, and the survivor is
named by no game. The team's unplayed fixtures stop being enqueued for a score fill, and no
other producer looks at NULL scores.

`supabase/migrations/20260822000000_resolve_merges_in_scrape_enqueue_rpcs.sql` resolves both
RPCs through `team_merge_map`. Until it is applied, run
`scripts/enqueue_stranded_merge_fixtures.py` after every merge batch.

## Merged teams lose their rank chart

`ranking_history` is keyed by the raw `team_id` and a merge never rewrites those rows, so a
surviving team's history stays filed under the ids it absorbed. Reading the canonical id alone
returns an empty chart.

`getRankHistory` in `frontend/lib/api.ts` and the insights route both read across the merged
id set via `resolveMergedTeamIds` in `frontend/lib/team-merge.ts`. Use that helper for any new
reader. Dedupe by snapshot date, preferring the canonical team's own row — the weeks before a
merge hold one snapshot per team, and a plain union double-plots them.

## Which row survives

`pick_canonical_pair` in `scripts/find_fuzzy_duplicate_teams.py` scores name aesthetics —
club name present, mixed case, length — and is uncorrelated with which row holds the data.
It is duplicated as `pick_canonical` in `scripts/run_all_merges.py`, so the two must change
together.

Ranking on game volume instead makes things worse: measured on a real batch it roughly doubled
the number of stranded fixtures, because the long-history row is usually the dead registration
while the short one holds the live schedule. If the rule changes at all, rank on live activity
— most recent game, or the presence of unscored future fixtures.

## Reverting

`scripts/revert_fuzzy_auto_merges.py` un-deprecates the team, repoints `team_alias_map` and
drops the `team_merge_map` row, reading the snapshot from `team_merge_audit`.

**Pass the actor explicitly — the default is wrong for merges this skill applies.** The script
hardcodes `pitchrank-bot`, which is what the weekly job records; `apply_vetted_team_merges.py`
records `pitchrank-operator`. Reverting an operator-applied batch with default arguments
matches zero rows and reports success, which is indistinguishable from a completed revert.

Scope a revert by date and actor. Judge what to revert from the audit snapshots rather than a
naive birth-year sweep over current names: normalization drops a year from band names, so
names that agreed at merge time can look disjoint afterwards, and such a sweep over-reports
heavily.
