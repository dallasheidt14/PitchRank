# Decision: what the weekly fuzzy merge becomes

**Written:** 2026-08-19 · **Status:** recommendation, nothing changed yet
**Answers:** item 1 of `.turbo/handoff/2026-08-19-stabilize-unknown-teams.md`

---

## Bottom line

**Retire `--auto-merge` permanently. Make the job report-only.** Do not build a "safe subset"
auto tier, and do not route suggestions into a review queue.

But **that is not the first thing to do.** 218 teams are being silently re-merged right now by
the scrape queue, unrevertably. That ships first.

---

## Correction to the handoff's premise

The handoff says every fix is another categorical guard and squad numbers still leak. That is
half right, and the half that is wrong matters.

`scripts/_team_distinction.py` (417 lines, wired in at `find_fuzzy_duplicate_teams.py:279`) is
**not** a fourth categorical patch. It is a general set-based discriminator guard comparing
colors, directions, programs, `team_number`, location codes, squad words, age tokens,
`secondary_nums` and state codes. Plus a hard same-club requirement at line 276.

Tested against HEAD, all four documented shapes are blocked and the legit pair still merges:

| pair | merges today? | blocked by |
|---|---|---|
| `Richmond United B2014/15 1` / `2` | no | `should_skip_pair` (team_number) |
| `PDA South ECNL I` / `II` | no | `should_skip_pair` (team_number) |
| `Mustang SC 2014 Elite II` / `III` | no | both layers |
| `unknown_781631` / `unknown_781653` | no | `score_team_pair` (#972) |
| `EPIC SC 2008 Dash` / `2009` | no | `score_team_pair` (#972) |
| `Rangers FC - 2017 White` / `Rangers FC 2017 White` | **yes** | correctly allowed |

So the "103 sibling groups still leaking" measurement predates the guard being wired in.

**But there is a fifth shape, live now, that #972 does not catch.** `birth_years()` does not
expand apostrophe shorthand:

```
birth_years("Elite '09") -> set()      # should be {'2009'}
score_team_pair("Surf SC Elite '09", "Surf SC Elite '08") -> 1.0
```

The birth-year guard needs both sides to state a year. Apostrophe form states none, so the guard
never fires and two different birth years score a clean 1.000. This is exactly the shape #972
was written to close, still open in its most common notation.

**This does not rescue auto-merge — it is the argument against it.** Five shapes now, each found
only after it caused damage, in a guard set that already looked complete. The next one is found
the same way.

---

## Why report-only, and not the alternatives

### Not a review queue

`team_match_review_queue` has 11,202 pending rows going back to 2025-12-11. It looks worked —
11,611 approved, 150 rejected — but every single decision was made by a script:

| reviewed_by | status | n | last |
|---|---|---|---|
| `auto-merge-script` | approved | 5,698 | **2026-08-19** |
| `cleanup-script` | approved | 5,524 | 2026-02-05 |
| `affinity-matcher-auto` | approved | 250 | 2026-03-02 |
| `bot:auto-clean` | rejected | 149 | 2026-02-10 |
| `dallasheidt@gmail.com` | rejected | **1** | 2026-03-16 |

One human decision in nine months. Routing suggestions into a review queue is routing them into
a queue with a demonstrated human throughput of one. It would read as responsible and function as
"never merge again" — while creating the *appearance* that duplicates are being handled.

A committed CSV is the honest version of the same thing: durable, greppable, diffable, reviewable
whenever you next sit down, and it does not pretend to be a workflow.

### Not a "provably safe" exact-name auto tier

This was the strongest candidate and it does not survive. The proposed safety guard was a
same-day-different-opponent conflict veto — "one team cannot play two different opponents on the
same date." That premise is false here: 395,499 of 2,460,235 team-days (16.1%) already have a
team facing 2+ distinct opponents, because tournaments schedule 2–3 games a day. Since a duplicate
is *by definition* a team whose games are split across two rows, a tournament day routinely puts
opponent X on row A and opponent Y on row B and manufactures a fake conflict.

Measured against ground truth, the veto is inert:

- False-positive rate on 2,928 known-true duplicates (your hand merges, never reverted): 16.2% / 9.7% / 6.7% at thresholds ≥1/≥2/≥3
- Observed conflict rate in the candidate tier itself: 14.3% / 7.1% / 4.3%

The tier's signal is *below* the false-positive rate at every threshold. Implied count of truly
distinct pairs: zero. It would block ~10 good merges to catch approximately none.

It is also structurally inapplicable to 67 of 207 pairs (32.4%) that have zero games on at least
one side — and those are the worst ones to merge blind, because `execute_team_merge` repoints
`team_alias_map`, so every future scrape lands on the canonical, games are immutable, and no
conflict signal can ever appear afterward.

### Not `--min-score`

Dead as a lever, and the handoff is right about why. Reconfirmed live: legit `Rangers FC - 2017
White` / `Rangers FC 2017 White` and wrong `Elite '09` / `Elite '08` both score exactly 1.000.

### The volume does not justify machinery

Club-scoped duplicate groups arrive at roughly **19/month** (19 Aug, 13 Jun, 2 May, 53 Apr,
26 Mar, 49 Feb) — 4–5 pairs a week. You merge by hand at 16 reverted of 2,945 (0.5%). The bot is
at 5,000 of 12,178 (41.1%). Automating 19 groups a month at 80× your own error rate is a bad
trade.

---

## Ship order

### 0. Repair the 218 — before anything else

The reverts restored team rows to live but did **not** restore their `team_alias_map` rows.
Verified:

```
263 reverted teams are live with zero alias rows
218 of them have their provider key currently pointing at a DIFFERENT live master
188 played within the last 180 days
```

Scraping is queue-driven and drains every 15 minutes. Every scrape of those provider IDs resolves
through the alias to the canonical and writes the games there — **with no `team_merge_map` row and
no `team_merge_audit` row**. Nothing to revert, nothing to audit, nothing a CSV can surface. This
is strictly worse than the merges being retired, and it is happening now.

New `scripts/repair_zero_alias_teams.py`: for each, take `(provider_id, provider_team_id)` from
its own `team_merge_audit.deprecated_team_snapshot` and restore the alias row. Refuse any case
where the key resolves to a different live master without explicit `--force`. Dry-run by default,
`--execute` to write. Re-verify the count reaches zero.

### 1. Fix the normalizer — required regardless of the policy decision

`scripts/find_queue_matches.py:94` strips the tier tokens with no word boundaries:

```python
n = re.sub(r"\s*(ecnl|ecnl-rl|rl|pre-ecnl|mls next|ga|academy)\s*", " ", n)
```

Reproduced live:

```
'Orlando City 2010' -> 'o ando city 2010'     # "rl" inside Orlando
'Galaxy 2014 Blue'  -> 'laxy 2014 blue'       # "ga" inside Galaxy
'Regal SC 2013'     -> 're l sc 2013'
'Legacy 2012 Red'   -> 'le cy 2012 red'
```

Add `\b` anchors, and add apostrophe-year expansion (`'08` → `2008`) in the same edit so
`birth_years()` stops returning empty. This is a prerequisite **whatever is decided about the
fuzzy job**, because Step 4 keeps running through the same function.

### 2. Make the fuzzy job report-only

`scripts/find_fuzzy_duplicate_teams.py`: delete `--auto-merge`, the merge-execution block, and
the `from run_all_merges import execute_merge` import. Deleting the flag takes the
`--auto-merge --dry-run performs real merges` footgun with it, rather than fixing it. (Note: that
line is **353** on origin/main, not 337 — the handoff's number predates #972.) Add `--output`
writing a CSV, and drop the 50-row print truncation.

Rename `FUZZY_AUTO_MERGE_ENABLED` → `MERGE_WRITES_ENABLED` rather than deleting it — its `false`
value is the only reason nothing is merging today — and extend it to gate Step 4.

Remove `find_fuzzy_duplicate_teams.py` from `ALWAYS_WRITING_SCRIPTS` in
`tests/unit/test_age_rollover_freeze_coverage.py:39-48` once it genuinely writes nothing.

### 3. Close the other unattended writers

- `find_queue_matches.py:1390` upserts `team_alias_map` with `match_method='fuzzy_auto'` — it
  never calls `execute_team_merge`, so it is an unattended **alias** writer, not a merge path.
  2,113 rows written since 2025-11-04, still going (35/30/124/138 per month Aug/Jul/Jun/May), and
  `auto-merge-script` approved rows as recently as **today**. `team_alias_map` has no audit table
  and no revert RPC, so its writes are *less* recoverable than the merges being retired.
- `.github/workflows/auto-merge-queue.yml` runs the same script, gated only by
  `AGE_ROLLOVER_FREEZE` (whose `'false'` **permits**), with `workflow_dispatch` defaults of
  `dry_run='false'`, `limit='2000'`. Least safe default in the repo. Same flag, same PR.
- `scripts/run_all_merges.py:431-437` — `--dry-run` is `action='store_true'`, so a bare
  invocation merges across all states/ages/genders with no cap. Flip to require `--execute --yes`.

### 4. Record what a merge was based on

`run_all_merges.py:249-261` never passes `p_confidence_score`. 0 of 10,280 `team_merge_map` rows
carry a confidence score, which is why forensics had to be rebuilt from timestamp windows. Pass it
through, and stop inferring success by string-sniffing exception text.

Separately, a migration so `execute_team_merge` records the **alias IDs** it moved as jsonb rather
than only the `aliases_updated` count. That single change is what would have made the 5,016-merge
revert clean instead of leaving 780 stranded aliases and the 263 above.

---

## Open questions

1. Clear the ~190 standing duplicate groups in one sitting from the CSV, or leave them? I am
   recommending no automation either way; this is about your time versus duplicates on the board.
2. Step 4 (`find_queue_matches.py --execute --yes`) — gate it off entirely, or only until the `\b`
   fix ships? It has written 2,113 aliases since November and some is presumably wanted. I default
   it off because it has no revert path.
3. Is the 0.90–0.999 fuzzy band worth reporting at all? It is 28.5% wrong, but its 5,231 kept
   merges consolidated 59,575 games in shapes exact matching will never find.

## Explicitly out of scope

- Draining the 11,202-row review queue backlog — evidence for this decision, not part of it.
- 550 pairs where a `teams` row holds a provider key that `team_alias_map` maps elsewhere (521 are
  `match_method='direct_id'`, only 2 trace to a reverted merge). Pre-existing, needs its own look.
- The modular11 double-import defect (one fixture under two `game_uid` formats). Games-quarantine
  question, not a merge question.

## Invariant this adds

`MERGE_WRITES_ENABLED` stays `false` until the alias repair has run and the `\b` fix has shipped.
The alias repair ships before any new merge writer — a writer shipping first makes its merges
exactly as un-revertable as the 5,016.
