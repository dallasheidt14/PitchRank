# Running a whole state

Doorway D run one state at a time, from scan to applied merges. Oklahoma, Kentucky, North
Carolina and Texas were worked this way on 2026-09-24 (1,488 merges). The reviewers and the owner
page are the same ones Steps 5 and 6 describe; this is how to run them at a state's scale
without losing track of a pair.

## Contents

- Scan and slice
- One brief for every reviewer
- Check every verdict file against its input
- Re-check the flags from the other side
- Keep two lists: the owner page and the fix list
- Apply, then build the owner page
- After applying

## Scan and slice

```bash
python scripts/find_squad_key_duplicates.py --state <XX> --out-dir <dir>
```

From its CSV, take three inputs: the `proposed` rows, the `held` rows, and the `rejected` rows
whose reason is `both played a game on the same day` (Step 4's four-step test applies to those
unchanged).

- **Proposals:** 30 to 40 pairs per reviewer, so each one reads its slice pair by pair.
- **Held pairs:** group by club, `age_group` and `gender` before slicing, so every pair of one
  cluster reaches the same reviewer. Slicing held pairs by club alone put 133 of North Carolina's
  held pairs, all Charlotte Soccer Academy, on one reviewer.
- **Same-day refusals:** about 35 per reviewer.

At most 20 subagents run at once. A launch past the cap fails with "Concurrent subagent limit
reached" and is not queued, so at state scale this replaces Step 5's single-message launch:
start as many slices as the cap allows, run them in the background, and start the next slice as
each reviewer finishes.

## One brief for every reviewer

Write the brief once per state and point every reviewer at the file. It carries the database
access, the evidence that separates squads, the hard stops, the survivor rule from Step 6, and
the state's own traps (see "Regional shapes" in [failure-modes.md](failure-modes.md)).

It also fixes the output shape: one object per input pair, in input order, with `merge_id`,
`keep_id`, `merge_name` and `keep_name` copied **verbatim** from the pair the object judges, a
`verdict`, a boolean `swap` (true when the other row should survive), and a `reason` that names
that pair's own teams. Proposal reviewers give `merge`, `hold` or `reject`; held-cluster
reviewers give `merge`, `separate` or `owner`; same-day reviewers give `refusal_stands`,
`promote` or `owner`. Held-cluster reviewers add `"redundant": true` to a pair whose two rows
both merge into a third row, and `"extra": true` to a merge between two rows no input pair
joins.

## Check every verdict file against its input

Before combining anything, compare each output file with its input line by line on those four
fields, and count the lines. A reviewer that writes its verdicts from a separate script can
attach one pair's verdict to its neighbour: in Oklahoma a line meant for the owner was applied
as a merge because its verdict and reason sat on the next pair's line. The check finds that
before anything is written.

Then combine: orient each merge by its `swap`, drop exact repeats, and look for any row
retired into two survivors or any survivor that is itself retired (a chain). Send every cluster
that check catches to the owner page instead of applying it.

## Re-check the flags from the other side

Send every `hold` and `reject` from the proposal reviewers to a second pass with the opposite
prior (Step 5). At state scale this replaces Step 5's single re-checker: split the flags across
several re-checkers once they pass about 50. Where two
re-checkers, or a re-checker and a first reviewer, disagree about the same cluster, send the
cluster to the owner rather than choosing between them.

## Keep two lists: the owner page and the fix list

- **Fix list:** a pair whose row holds two squads, carries another team's provider id, or hits a
  hard stop. Those rows need repair first (**Splitting a fused row**); the owner cannot settle
  them with a click. Leave out any merge that touches a fix-list row.
- **Owner page:** everything else that review could not settle.

## Apply, then build the owner page

Apply the vetted merges (Step 6) before building the owner page, so each card shows games
merged together. Re-point every owner pair at the survivors first: a pair whose row was retired
into a survivor is still a question, about that survivor. Drop a pair whose two rows now point at
the same survivor; the batch has already joined them.

When the collector refuses with "these merges disagree about which team survives" because the
owner chose Merge on every card of a cluster, the owner has said the rows are one squad. Keep one
survivor for the whole cluster, chosen by Step 6's order with the owner's name choice first, and
merge the rest into it.

## After applying

Run `scripts/exclude_merge_duplicate_games.py`, dry run first; a pair promoted from a same-day
refusal usually leaves one match recorded twice.

Then check the survivors for signs of a wrong merge: a game against itself, names stating both
genders, names two or more birth years apart, and dates with games in two different events.
Split the two-event dates by where the games came from: already on a single row before this
batch, the same score recorded under two event labels, or created by this batch's merges.
Only the last is a question about this batch. In Texas, 331 flagged dates came down to 3
created by the batch, and 2 of those were unplayed placeholders.
