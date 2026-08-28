---
name: merging-duplicate-teams
description: "Finds and safely merges duplicate team rows in PitchRank, deciding each pair from game evidence rather than name similarity. Use when asked to merge duplicate teams, clean up duplicate team records, run or re-enable the weekly fuzzy duplicate merge (Step 3 of data-hygiene-weekly), review proposed team merges, investigate why a real duplicate was refused, undo or revert a team merge, or investigate whether a team row is actually two squads fused together."
---

# Merging duplicate teams

Treat every merge as a data-destroying write until game evidence says otherwise: it deprecates
a team row and repoints its provider alias, so if the rows were different squads a real team
stops existing and its future games are attributed to another team.

A refusal is not free either. The pipeline refuses on artifacts as well as on evidence, and a
pair refused on an artifact is refused identically every week forever. Steps 4 and 5 are a
matched pair: one hunts wrong approvals, the other hunts wrong refusals. Running only the
first is how the same true duplicate survives a year of weekly runs.

Copy this checklist and check off items as you complete them:

```
Task Progress:
- [ ] Step 1: Preflight — credentials, then prove the guards still fire
- [ ] Step 2: Generate candidates from both doorways
- [ ] Step 3: Decide every candidate from evidence
- [ ] Step 4: Review the refusals
- [ ] Step 5: Adversarially review the approved set
- [ ] Step 6: Apply only what survives review
- [ ] Step 7: Repair the downstream side effects
- [ ] Step 8: Record what ran and what was held
```

## Step 1: Preflight

**Credentials.** `decide_team_merges.py` and `apply_vetted_team_merges.py` both call
`load_dotenv(... / '.env.local')`. That file does not exist on this checkout — the Supabase
keys are in root `.env`. Run as documented, both exit with
`SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set`, which reads like missing credentials
rather than the wrong file. Preload the environment from root `.env` before Step 3.

**Imports.** `decide_team_merges.py` imports `_UAGE_TOKEN` and `birth_years` from
`src/utils/team_name_utils.py`. On a checkout that predates them the scan fails with an
`ImportError` that does not name the branch as the cause.

**Prove this skill is still true.** Most of what follows is a claim about code behaviour or a
row count, and both rot. Run the checker before trusting any of it:

```bash
python scripts/check_merge_skill_assumptions.py              # assertions + live counts
python scripts/check_merge_skill_assumptions.py --code-only  # no database, seconds
```

It exits non-zero when an assertion breaks. **A failure means this skill is now wrong, not that
the codebase is** — most assertions encode a *bug* the guidance routes around, so fixing the bug
fails the check and sends you here to delete the workaround. It also warns when a quoted figure
has drifted more than 20%, which is the signal to re-measure the prose.

Read its output rather than skimming it. That the birth-year guard returns nothing for a U-label,
and raises no conflict against either 2008 or 2009, is not a failure to fix — it is the blindness
you carry into every later judgement. See [references/failure-modes.md](references/failure-modes.md).

When you change the skill's claims, update `RECORDED` in that script in the same commit.

## Step 2: Generate candidates from both doorways

There are two independent ways to nominate a pair, and the skill's tooling only covers one.

**Doorway A — name similarity.** `scripts/find_fuzzy_duplicate_teams.py`, called in-process by
`decide_team_merges.py`. This is the recall ceiling for everything in Step 3: a pair it cannot
propose is never judged, never reviewed, and never merged. It proposes a pair only when the two
rows agree on **all** of stored gender, stored age group, `state_code` bucket, and byte-identical
lowercased `club_name`, and then score >= the threshold.

So these are invisible at any threshold: same club with rows stamped in different states; the
same club spelled two ways; either row named `unknown_<digits>`; either name containing a space
followed by `EA` (3,256 live rows, 2,148 of them East/Eagles names — see failure-modes).

A fifth loss sits below all of these: `fetch_teams` pages without an `.order()` clause, so each
cohort scan silently drops a share of its own input — 16% when reproduced on `u19`. Those rows
reach no rule and appear in no report. Every per-cohort count this pipeline produces is a floor.

**The blockers stack, so do not read any one of them as the barrier.** A worked pair —
`Black Conshy '12 G` against `Black Conshy '11/'12 (G) *`, one squad registered twice — is
stopped independently by three: different `state_code` buckets, a score of 0.877 against a 0.90
threshold, and `_should_skip_pair` on mismatched age tokens. Repairing the state stamps alone
would still not surface it. Whenever you attribute a miss to one gate, check the others before
proposing a fix aimed at it.

**Doorway B — shared fixture fingerprints.** Two rows that independently recorded the same
`(game_date, merge-resolved opponent, own_score, opp_score)` under different game rows are the
same team's schedule imported twice. It reads no name, so it reaches the placeholder, laundered
and wrong-state classes that defeat Doorway A.

**It does not reach everything.** The fingerprint needs the opponent to resolve to a single row.
When a team is imported twice from two providers its opponents usually are too, the two schedules
name different opponent rows, and nothing matches. **Doorway B is blind to precisely the
cross-provider duplicate** — which is the class Step 4 exists to rescue from the same-day rule.
The two doorways have complementary blind spots; neither is a superset.

Require **at least two** shared fingerprints, and drop any pair that ever played each other. One
shared fixture is noise: measured over one season, 17,476 pairs share one, 1,709 share two, and
399 of those had met on the pitch.

**There is no committed tool.** The generator that produced the 639 merges of 2026-08-27 exists
only at
`%LOCALAPPDATA%\Temp\claude\C--PitchRank\4294a591-08b3-4a60-b3e3-e90baa5940cf\scratchpad\build_regid_merges.py`
— a finished session's temp directory, untracked, one cleanup from gone. **Copy it into the repo
before using it.** Read `.turbo/handoff/2026-08-27-regid-duplicate-merges.md` for what ran and
`.turbo/specs/second-layer-duplicate-detection.md` for the design and the generator's own known
blind spots.

Re-running it as written returns almost nothing: **the 639 batch exhausted its Tier A.** What
remains is the held tiers (280 partial, 79 head-to-head, 27 ambiguous, ~1,000 under the 3-game
floor), and those need a rule change or a person, not a rerun. Establish the remaining count from
the handoff before proposing to repeat anything.

A stale copy of the generator's outputs may also sit in the *current* session's scratchpad. A
`regid_tierA.json` of `[]` there means nothing — verify against the database, never against a
scratch file.

**Loosening a threshold and adding an independent signal are not the same move.** The measured
table in evidence-rules.md forbids the first. Doorway B is the second, and it is the only route
past the ceiling.

## Step 3: Decide every candidate from evidence

```bash
mkdir -p .turbo/step3
python scripts/decide_team_merges.py --all-cohorts --out .turbo/step3/decisions.json
```

Scope it with `--age-group`/`--gender`, or judge a supplied list with `--candidates <file>`.
`--all-cohorts` is wider than the scheduled workflow, which covers male only. It omits `u9`.

Read [references/evidence-rules.md](references/evidence-rules.md) before changing any threshold
or arguing with a verdict. Every setting looser than the current one destroyed real teams.

**Do not run Doorway B pairs through this script.** Three of its preconditions are artifacts that
refuse the double-import duplicate by construction: `club_name` compared as a raw string so NULL
mismatches everything, `state_code` compared as a raw string, and any shared calendar date
refused outright — which is that duplicate's own signature.

Step 4 does not apply to them either; its tells are keyed to reason strings a pair that never ran
through this script does not have. Judge a Doorway B pair on its own terms:

- Do the two rows share **two or more** identical `(date, opponent, own_score, opp_score)`
  fingerprints, opponents resolved through `team_merge_map`?
- Have they **ever played each other**? One head-to-head ends it.
- Does either row hold a fixture that **conflicts** with the other's — same date, a genuinely
  different opponent, different score? That argues two squads, and needs step 3 of Step 4's test
  applied to the opponent before you believe it.
- Do the stored cohort and gender agree, and does neither name contradict its own gender column?
- Which row holds the live schedule and the populated columns? That one survives (Step 6).

**Calibration applies to Doorway A only.** "Roughly a third reach MERGE" and "one in fourteen
approved pairs fail review" were measured on name-similarity candidates. The 2026-08-27 batch
approved 62% with zero failures and was not a regression. A rate well *below* a third is also
unexplained by this skill — read it as a cohort already cleaned, or as a broken scan, only after
checking which.

The table's "true duplicates merged" column is measured **inside the candidate set the scan
produced**. It is not end-to-end recall and must never be reported as one.

## Step 4: Review the refusals

Every REFUSE in `decisions.json`, not a sample. The rules refuse on three artifacts that look
identical to real evidence in the output, and each has a specific tell:

| Reason string | Artifact tell | What to check |
|---|---|---|
| `states differ` | one side's state came from an event, not the club | do the two rows share a club and a schedule? state is not evidence |
| `clubs differ` | one side is NULL, coerced to `''` | is either `club_name` NULL? then nothing was compared |
| `both played a game on the same day` | the shared dates are the *same fixtures* | run the three-step test below — two steps are not enough |

That last row is the one that matters most, and it takes three steps, not two. The rule's stated
intent is that a squad cannot be in two places — but the code performs none of the opponent
verification evidence-rules.md describes.

1. **Same opponent row and same score on the shared date?** That is one match imported twice —
   the dominant duplicate shape here. Evidence *of* duplication, not against it.
2. **Different opponent rows?** Do not stop here. Look the opponents up by name.
3. **Are those differing opponents themselves a duplicate pair?** If they are, step 2 proved
   nothing — you are looking at one fixture recorded against two copies of one opponent.

Step 3 is not hypothetical. `Weston FC 2012 DPL` against `Weston FC U15G DPL` shares six dates
with *different* opponents on every one — and those opponents are
`W&H America U14 Adrenalina DPL` / `W&H America 15U Adrenalina DPL`, and
`Miramar DA U14 DPL` / `Miramar DA U15G DPL`: duplicate rows of one club. Another pair's opposing
row has the words `hold duplicate` in its own name.

Stopping at step 2 permanently refuses the cross-provider duplicate, which is exactly the class
this skill calls dominant. Only genuinely distinct opponents on a shared date are a real refusal.

A pair that clears all three is a Step 5 candidate that the rules refused. Promote it by hand and
say so in Step 8.

## Step 5: Adversarially review the approved set

The rules produce a candidate list, not a safe list. Expect roughly one in fourteen approved
pairs to fail review — including, in past runs, a 2008 team about to absorb a 2009 team and a
boys squad about to absorb a girls squad.

Split the approved pairs into disjoint slices, sized so each agent examines its slice pair by
pair rather than sampling. Launch all agents in a single message. Run them in the foreground so
all results return in this turn (`model: "opus"`, no `name`). Give each agent database access, an
adversarial stance — assume each merge is wrong and try to prove it — and a directive to treat
the repository and its git index as read-only.

Then re-examine every flagged pair with the opposite prior: that the merge is fine and clubs
re-register squads constantly. Spawn a single subagent in the foreground (`model: "opus"`, no
`name`). Most flags do not survive this, and acting on unverified flags discards good merges.

**Below about ten pairs, do this inline rather than fanning out.** The fan-out exists to make a
large batch examinable pair by pair; on three pairs it is pure overhead.

Read [references/failure-modes.md](references/failure-modes.md) for the shapes already known, and
direct review at what per-pair name comparison structurally cannot see — two rows in different
flights of one league, a club-specific squad qualifier the other row lacks, a surviving row
nothing has ever confirmed the identity of.

Rows carrying three or more registrations from one provider are already routed to `REVIEW` and
will not appear here. The residual risk is a **two**-registration fusion.

## Step 6: Apply only what survives review

Filter `.turbo/step3/decisions_approved.json` down to the pairs that survived review, keeping the
same object shape. Then dry-run:

```bash
python scripts/apply_vetted_team_merges.py --file <vetted.json>
```

**Check the direction before you apply.** `pick_canonical_pair` scores name aesthetics — club
name present, mixed case, length — and is uncorrelated with which row holds the data. A merge
copies no columns onto the survivor, so keeping the prettier row can leave the live team with a
wrong state, a NULL distinction and a shallower rank history. Where the two rows disagree, keep
the one with the live schedule and the populated columns, and swap `merge_id`/`keep_id` by hand.

Output the vetted list and the held-pair count as text, then use `AskUserQuestion` to confirm
before writing. On approval:

```bash
python scripts/apply_vetted_team_merges.py --file <vetted.json> --execute --out <log.json>
```

`--limit N` applies at most N, which is the escape hatch for a first execute. Apply a small batch,
verify it against the database, then apply the rest — that is what the 639-merge batch did (25,
verified, then 614). The script resolves both sides through `team_merge_map`, orders chains so a
row receives its merges before it is itself merged away, drops a row claimed by two different
survivors, and refuses a stale list outright.

Verify against the database rather than the script's own report — see
[references/pipeline-gotchas.md](references/pipeline-gotchas.md), which explains why the RPC's
reply cannot be trusted and how to revert. Confirm each intended row is deprecated, its canonical
matches, and no surviving row was deprecated except where a chain accounts for it.

Revert with `scripts/revert_fuzzy_auto_merges.py`, scoped by date **and actor**. Its actor default
is `pitchrank-bot`; `apply_vetted_team_merges.py` records `pitchrank-operator`. A default-argument
revert of a batch this skill just told you to apply matches nothing and reports success.

## Step 7: Repair the downstream side effects

### The merged fixtures are now recorded twice

This follows directly from the shape Step 4 tells you to merge. When two rows held the same
match because it was imported twice, `games` holds **two rows** for it — and a merge does not
touch `games`. Both rows now resolve to the surviving team, so the survivor's schedule contains
each shared match twice.

Nothing downstream removes them. `src/rankings/data_adapter.py:291` dedupes with
`drop_duplicates(subset=["id"])` — the game row's own id — so two distinct rows describing one
real match both survive and both feed the engine. `game_uid` embeds the master team ids, so the
two copies never collided on insert either.

Measured on a 200-merge sample of the 2026-08-27 batch: **604 fixture tuples now resolve to two
game rows each.** No ranking run has consumed them yet.

`scripts/cleanup_dupe_games_by_composite.py` does **not** find these. It keys on the raw
`(home_team_master_id, away_team_master_id, game_date, home_score, away_score)`, and the two
copies still carry different raw master ids — the deprecated one and the canonical one. It also
deletes rows outright, which is a stronger write than the immutability rule allows.

So after any Doorway B batch, count the resolved duplicates yourself, and settle with the
operator whether to exclude the redundant copies (`is_excluded`) before the next ranking run.
Do not delete game rows.

### Stranded fixtures

A merge strands the deprecated row's unplayed fixtures.

```bash
python scripts/enqueue_stranded_merge_fixtures.py --since <YYYY-MM-DD> --merged-by pitchrank-operator
python scripts/enqueue_stranded_merge_fixtures.py --since <YYYY-MM-DD> --merged-by pitchrank-operator --execute
```

The default covers fixtures dated today onward; add `--include-past` when repairing a batch
merged days earlier, since already-played fixtures with NULL scores need the backfill too.

Skip this step once
`supabase/migrations/20260822000000_resolve_merges_in_scrape_enqueue_rpcs.sql` is applied, which
closes the hole at the source. Confirm it is applied against `schema_migrations` before skipping —
the file being on disk is not the same as it being applied, and as of 2026-08-27 it is not.

## Step 8: Record what ran and what was held

Write a short record next to the logs: how many merged, how many were held and the specific
reason for each, **how many refusals you promoted in Step 4 and why**, and anything found that
needs separate work. A held pair without a stated reason gets re-proposed and re-argued on the
next run; a promoted refusal without a stated reason gets re-refused.

Also record what is left in the class you just worked, so the next run starts from a count rather
than from a rescan.

State plainly that the held pairs need a human decision rather than a rule.

## Re-enabling the weekly job

`FUZZY_AUTO_MERGE_ENABLED` stays `'false'` while the shipped
`scripts/find_fuzzy_duplicate_teams.py` still decides on name similarity. The 2026-08-19 run
merged 1,772 pairs of distinct teams.

Before that flag moves, port the rules into the scan itself, run it in report-only mode for
several weeks, and compare each week's proposals against what a person would approve. Then
auto-merge only the narrowest class — a side with no games at all — and keep the rest as a report.
