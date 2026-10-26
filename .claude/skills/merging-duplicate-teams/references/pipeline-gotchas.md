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

Every insert or update on `team_merge_map` passes the `check_merge_chains` trigger
(`prevent_merge_chains`). It refuses a row whose canonical has its own `team_merge_map` row or is
flagged `is_deprecated`, and a row retiring a team others are merged into. The merge RPC stays
inside it by cascading the incoming rows first. An undo must reverse the merge first — delete the
team's own row and clear its `is_deprecated`, as `revert_team_merge` does — before pointing earlier
merges back at it; until then the trigger refuses any row naming it as canonical. A test double for
`team_merge_map` must refuse the same rows, or tests pass on a write order production refuses.

## The RPC reports failure on success

The RPC's success payload carries a `message` key, and supabase-py's client (postgrest-py) reads
any response whose data holds `message` as an API error. So a committed merge raises `APIError`
with the message `JSON could not be generated`; the real payload, containing `"success": true`,
sits in the exception's `details` and so in its text.

`scripts/run_all_merges.py` and `scripts/apply_vetted_team_merges.py` both parse it out. Any
new caller must do the same, or it reports every committed merge as failed. The applier also reads
each merge's `team_merge_map` row back after the call, which is what its `--revert` replays, so a
reply lost altogether still leaves a revertable entry.

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
RPCs through `team_merge_map`, and is applied — verified 2026-08-31, both function bodies
confirmed to read `team_merge_map`. The paragraph above is therefore history, not current
behaviour. `scripts/enqueue_stranded_merge_fixtures.py` remains only for fixtures stranded
before that date.

What a merge still leaves behind is the *played* fixture recorded twice; see
`scripts/exclude_merge_duplicate_games.py` and Step 7 of the skill.

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

A batch `apply_vetted_team_merges.py` applied is undone from its own log with `--revert`, which
also points back the merges into each retired team and the aliases its merge moved;
`revert_team_merge` alone leaves the incoming merges on the survivor and moves back only the
aliases the retired team's games name. It stops at an entry whose run never read back its merge
row; SKILL.md Step 6 says how to settle that team by hand.

`scripts/revert_fuzzy_auto_merges.py` is for merges with no such log: it un-deprecates the team,
repoints `team_alias_map` and drops the `team_merge_map` row, reading the snapshot from
`team_merge_audit`.

**Pass the actor explicitly — the default is wrong for merges this skill applies.** The script
hardcodes `pitchrank-bot`, which is what the weekly job records; `apply_vetted_team_merges.py`
records its `--actor`, `pitchrank-operator` by default. Reverting an operator-applied batch with
default arguments matches zero rows and reports success, which is indistinguishable from a
completed revert.

Scope a revert by date and actor. Judge what to revert from the audit snapshots rather than a
naive birth-year sweep over current names: normalization drops a year from band names, so
names that agreed at merge time can look disjoint afterwards, and such a sweep over-reports
heavily.
