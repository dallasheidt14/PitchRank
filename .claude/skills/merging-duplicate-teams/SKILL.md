---
name: merging-duplicate-teams
description: "Finds and safely merges duplicate team rows in PitchRank, deciding each pair from game evidence rather than name similarity. Use when asked to merge duplicate teams, clean up duplicate team records, run or re-enable the weekly fuzzy duplicate merge (Step 3 of data-hygiene-weekly), review proposed team merges, undo or revert a team merge, or investigate whether a team row is actually two squads fused together."
---

# Merging duplicate teams

Treat every merge as a data-destroying write until game evidence says otherwise: it deprecates
a team row and repoints its provider alias, so if the rows were different squads a real team
stops existing and its future games are attributed to another team.

Copy this checklist and check off items as you complete them:

```
Task Progress:
- [ ] Step 1: Decide every candidate from evidence
- [ ] Step 2: Adversarially review the approved set
- [ ] Step 3: Apply only what survives review
- [ ] Step 4: Repair the downstream side effects
- [ ] Step 5: Record what ran and what was held
```

## Step 1: Decide every candidate from evidence

`scripts/decide_team_merges.py` imports `_UAGE_TOKEN` and `birth_years` from
`src/utils/team_name_utils.py`. Confirm both exist there before running; on a checkout that
predates them the scan fails with an `ImportError` that does not name the branch as the cause.

```bash
mkdir -p .turbo/step3
python scripts/decide_team_merges.py --all-cohorts --out .turbo/step3/decisions.json
```

This scans every age group and both genders at the `--min-score 0.90` the weekly workflow
passes, then judges each candidate. It writes every decision plus a `_approved.json` holding
only the `MERGE` verdicts. Scheduled runs of the workflow cover male only, so `--all-cohorts`
is the wider set.

Scope it with `--age-group`/`--gender`, or judge a supplied list with `--candidates <file>`.

Read [references/evidence-rules.md](references/evidence-rules.md) before changing any
threshold or arguing with a verdict. Every setting looser than the current one destroyed real
teams in testing.

Expect roughly a third of candidates to reach `MERGE`. A larger share means a threshold was
loosened; treat that as a regression rather than an improvement.

## Step 2: Adversarially review the approved set

The rules produce a candidate list, not a safe list. Expect roughly one in fourteen approved
pairs to fail review — including, in past runs, a 2008 team about to absorb a 2009 team and a
boys squad about to absorb a girls squad.

Split the approved pairs into disjoint slices, sized so each agent examines its slice pair by
pair rather than sampling. Launch all agents in a single message. Run them in the foreground
so all results return in this turn (`model: "opus"`, no `name`). Give each agent database
access, an adversarial stance — assume each merge is wrong and try to prove it — and a
directive to treat the repository and its git index as read-only.

Then re-examine every flagged pair with the opposite prior: that the merge is fine and clubs
re-register squads constantly. Spawn a single subagent in the foreground (`model: "opus"`, no
`name`). Most flags do not survive this, and acting on unverified flags discards good merges.

Read [references/failure-modes.md](references/failure-modes.md) for the shapes already known,
and direct review at what per-pair name comparison structurally cannot see — two rows in
different flights of one league, a club-specific squad qualifier the other row lacks, a
surviving row nothing has ever confirmed the identity of.

Rows carrying three or more registrations from one provider are already routed to `REVIEW` and
will not appear here. The residual risk is a **two**-registration fusion.

## Step 3: Apply only what survives review

Filter `.turbo/step3/decisions_approved.json` down to the pairs that survived review, keeping
the same object shape. Then dry-run:

```bash
python scripts/apply_vetted_team_merges.py --file <vetted.json>
```

Output the vetted list and the held-pair count as text, then use `AskUserQuestion` to confirm
before writing. On approval:

```bash
python scripts/apply_vetted_team_merges.py --file <vetted.json> --execute --out <log.json>
```

`--limit N` applies at most N, which is the escape hatch for a first execute. The script
resolves both sides through `team_merge_map`, orders chains so a row receives its merges
before it is itself merged away, drops a row claimed by two different survivors, and refuses a
stale list outright.

Verify against the database rather than the script's own report — see
[references/pipeline-gotchas.md](references/pipeline-gotchas.md), which explains why the RPC's
reply cannot be trusted and how to revert. Confirm each intended row is deprecated, its
canonical matches, and no surviving row was deprecated except where a chain accounts for it.
Revert a wrong merge with `scripts/revert_fuzzy_auto_merges.py`, scoped by date and actor.

## Step 4: Repair the downstream side effects

A merge strands the deprecated row's unplayed fixtures.

```bash
python scripts/enqueue_stranded_merge_fixtures.py --since <YYYY-MM-DD> --merged-by pitchrank-operator
python scripts/enqueue_stranded_merge_fixtures.py --since <YYYY-MM-DD> --merged-by pitchrank-operator --execute
```

`pitchrank-operator` is the actor `apply_vetted_team_merges.py` records. The default covers
fixtures dated today onward; add `--include-past` when repairing a batch merged days earlier,
since already-played fixtures with NULL scores need the backfill too.

Skip this step once
`supabase/migrations/20260822000000_resolve_merges_in_scrape_enqueue_rpcs.sql` is applied,
which closes the hole at the source. Confirm it is applied before skipping.

## Step 5: Record what ran and what was held

Write a short record next to the logs: how many merged, how many were held and the specific
reason for each, and anything found that needs separate work. A held pair without a stated
reason gets re-proposed and re-argued on the next run.

State plainly that the held pairs need a human decision rather than a rule.

## Re-enabling the weekly job

`FUZZY_AUTO_MERGE_ENABLED` stays `'false'` while the shipped
`scripts/find_fuzzy_duplicate_teams.py` still decides on name similarity.

Before that flag moves, port the rules into the scan itself, run it in report-only mode for
several weeks, and compare each week's proposals against what a person would approve. Then
auto-merge only the narrowest class — a side with no games at all — and keep the rest as a
report.
