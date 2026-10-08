---
name: measuring-ranking-changes
description: "Measures what a PitchRank ranking-engine change would do before it ships: freezes production inputs read-only, re-rates them offline with the baseline and the candidate code, and compares rank, points and agreement with recorded results. Use when asked to measure a ranking change, size its blast radius, count how many teams a change moves, compare two engine versions, run a shadow, offline or before/after re-rating, or confirm the committed code matches what was measured. A change to the games fetch is measured at its input, not on a board."
---

# Measuring Ranking Changes

For the C1 ceiling-only connectivity experiment, use [the C1 capture and evaluation supplement](references/c1-evaluation.md).

Re-rate one set of frozen production inputs with the baseline code and with the candidate, then compare the two runs. Nothing here writes to the database: the freeze sends only GET requests, and a board runs on an in-memory client that raises on every write.

A board hands the frozen games straight to `compute_all_cohorts`, so it never runs `fetch_games_for_rankings`. A change to the games query, the exclusion list, merge resolution of game rows or de-duplication does not reach a board. Measure such a change at the input instead: freeze once with each code root on the same `--today`, then compare the two `<freeze dir>/games.parquet` files for games added or removed, teams affected, and teams crossing `MIN_GAMES_PROVISIONAL` (12). A board whose code root changed the fetch's files, the helpers it calls, or the fetch window lists them in `fetch_code_not_measured`.

## Step 1: Prepare One Worktree per Code Version

- Run `git fetch --all --prune`, then `git worktree add --detach <dir> origin/main` for the baseline.
- Give the candidate its own worktree too, holding the change staged or committed, rather than the shared main checkout: `config/settings.py` loads the code root's env files, and other sessions edit that checkout.
- Put flag-controlled behavior in code. A board clears every `SCF_`, `SOS_CREDIT_`, `RECORD_RECONCILE_`, `ML_` and `USE_LOCAL_SUPABASE` environment variable so both runs use code defaults, and stops if the code root's env files set one again.
- Leave both trees untouched until their boards finish. Remove the worktrees with `git worktree remove <dir>` once the report is written.

## Step 2: Freeze the Inputs Once

```bash
python <skill dir>/scripts/shadow_harness.py freeze \
  --code-root <origin/main worktree> --env-file <main checkout>/.env --today "$(date -u +%F)" --out <freeze dir>
```

- `<skill dir>` is this skill's folder as an absolute path, in any checkout that has it; engine code is imported only from `--code-root`.
- Use a worktree at origin/main as the code root, so the fetch is production's current code. Pass today's UTC date: the freeze reads the database as it is now, so a past date does not reproduce that day's inputs. A time split (Step 5) passes its split date instead.
- The freeze fetches games over production's window (`WINDOW_DAYS` + `WINDOW_GRACE_DAYS`, 393 days), then the team metadata and the merge map. It takes about 20 minutes.
- Before a fresh fetch, look for a saved input snapshot: a games file an earlier shadow run wrote (Codex worktrees keep those runs in folders under `data/cache/`). Pass it with `--games-from <file>` and the `--today` that run used. The freeze refuses a file whose columns or dates do not fit, which also rules out the engine's own per-cohort cache files (`rankings_<hash>_games.parquet`).
- A reused snapshot is resolved against older merges and cannot reveal fetch-code changes. Report the manifest's `team_ids_deprecated_in_merge_map` as drift.
- Keep freezes and runs outside the repo, in the session scratchpad. A freeze is about 350 MB.

## Step 3: Run One Board per Code Version

```bash
cd <scratch dir> || exit 1
PYTHONDONTWRITEBYTECODE=1 nohup python -B <skill dir>/scripts/shadow_harness.py board \
  --code-root <worktree> --freeze <freeze dir> --out <run dir> > <run dir>.console.log 2>&1 &
echo $! > <run dir>.pid
```

- `--out` must name a directory that does not exist yet.
- A board takes about 70 minutes, peaks around 5.4 GB and writes about 900 MB, half of it the engine's own cache under `<run dir>/data/cache`. Delete that folder once `<run dir>/completed.json` exists. Run at most two boards at once. Before starting, read free memory as `FreePhysicalMemory` from `Get-CimInstance Win32_OperatingSystem`: start one board only with about 6.5 GB free, and two only with about 12 GB free. These minimums protect the boards, not a watcher shell.
- A board stamps `last_calculated` with the freeze's `today`, so its evidence gates measure freshness from the date its engine rated as of, and boards run on different days stay comparable.
- Launch detached, as above. Claude Code stops background shells when memory runs low; a nohup'd board survives that, but a watcher loop may not. Learn that a run finished from `<run dir>/completed.json` and from its process.
- When the session will sit idle while the boards run, chain both board commands and the Step 5 comparison with `&&` inside one nohup'd `sh -c`, each command keeping its own console log, and write the chain's `$!` to a pid file as above. Launch it only with the one-board minimum free, since the second board starts without a check of its own. The report then exists even if every watcher is stopped; run the Step 4 checks before trusting it.

## Step 4: Check Each Run Before Comparing

- `<run dir>.console.log` contains no `Traceback` and no `BlockedCall`; an uncaught error prints there, not to `run.log`. A `BlockedCall` names a call the frozen client does not serve: extend `FrozenClient` and the freeze to serve it rather than catching it.
- `<run dir>/run.log` contains no `Failed to check is_deprecated`. That step catches its own errors and carries on, so a run can finish without it.
- `<run dir>/completed.json` exists. A read the freeze does not serve never gets this far, so a `frozen_client_calls` count that differs between the runs means the candidate made the served reads a different number of times, usually because it ranks a different set of teams.
- `<run dir>/provenance.json` names the code root, head and engine-file hashes you meant to run, and its `fetch_code_not_measured` is empty.

## Step 5: Compare the Runs

```bash
python <skill dir>/scripts/compare_runs.py --base <run dir> --cand <run dir> --freeze <freeze dir> \
  --out <report.json> --label "<change>"
```

It refuses two runs made on different freezes, or a `--freeze` the runs did not use, and prints its warnings. The report holds:

- `checks.teams_with_engine_or_ml_change`: teams whose `mu`, `powerscore_adj` or `powerscore_ml` changed. Zero means the change never reaches the engine, given the A/A check in Step 6.
- `checks.became_active`, `left_active`, `crossed_min_games_up` and `crossed_min_games_down`: the status and `MIN_GAMES_PROVISIONAL` crossings the blast radius needs. A team one run dropped entirely counts as absent with no games, and `teams_only_in_base` and `teams_only_in_cand` count those teams.
- `checks.config_differences`: config and environment keys that differ between the runs. Each must be one your change sets on purpose.
- `checks.gate_columns_comparable`: false when the runs' `last_calculated` differ, which two pinned boards on one freeze never do.
- `movement`: per board, for teams Active in both runs, each ranked on its own run's board: ranks changed, the largest move, points deltas on the 0–100 scale, and top-25 and top-100 entrants.
- `big_movers`: teams moving more than 25, 100 and 300 places, each labelled with one change that co-occurred with the move (an ML swing over 0.3, else a changed ceiling depth, else other). A label is a hypothesis, not a cause.
- `agreement_with_recorded_results_pct`: per board and overall, for engine (`mu`) and published scores, base against candidate, over decided games between teams Active in both runs.

### Score on later games (a time split)

In-sample agreement rewards fitting the games a board was built from. To judge a change on games the ratings never saw:

1. Freeze with `--today` set to the split date. The freeze still reads the database as it is now, but the games fetch keeps only dates up to that day, so no later result reaches a board, and every board shares the freeze. Confirm the freeze's latest game date before running boards.
2. Run the baseline and each candidate on that freeze, as in Steps 3 and 4.
3. Score them on games from a later freeze:

```bash
python <skill dir>/scripts/score_later_games.py --base <run dir> \
  --cand <name>=<run dir> [--cand <name>=<run dir> ...] \
  --train-freeze <split freeze dir> --heldout-freeze <later freeze dir> --start <first day> --end <last day> \
  [--scf-cand <name>] --out <report.json>
```

**Do not let the script decide a result on its own.** Its checks record problems without stopping a verdict (IMP-303), so confirm by hand that `--start` falls after the split freeze's `today` (nothing compares them, and an earlier start scores games the boards were rated on), that the report's `isolation.passed` is true, and that, in a call whose baseline has dampening on, `--scf-cand` names the dampening-off candidate exactly (an unmatched name skips the cut, and the screen then treats the cut as passed). Keep `--start`, `--end`, both freeze paths and `--scf-cand` beside the report, which records none of them.

- **What it scores:** decided same-board held-out games between teams Active in every run passed. Each game earns 1 when the team with the higher `power_score_true` won, and 0.5 when the two scores tie.
- **Uncertainty:** each candidate gets a per-game credit difference against the baseline, a standard error that treats games sharing a team as correlated, and Holm across the candidates in the call.
- **Split check:** the report's `isolation.passed` is false when the split freeze holds a game after its `today`, a run was rated on a freeze with a different games hash, a run made a read outside `ALLOWED_CALLS`, or a team row's `last_calculated` falls on another date. `ALLOWED_CALLS` copies the three read shapes `FrozenClient` serves, so a read added to `FrozenClient` (Step 4) belongs there too.
- **Design the comparisons.**
  - Give each change its own candidate. When the plan also scores a combination, score it against each of its parts as well as the baseline, one call per part with that part's run as `--base`, since a part's effect can depend on the others: the gender-mask fix was inconclusive alone (+0.02, with U17–U19 worse) and passed on top of dampening off (+0.34). Take the dampening cut only in a call whose `--base` has dampening on.
  - Make void (a check in the warning above fails), fail, pass and inconclusive mutually exclusive, and apply them in that order, so a wide interval blocks a pass without proving harm. A cut's own `harm` blocks a pass; it is not a fail.
  - Define any cut from one fixed run and apply it to both sides of every comparison, as the dampening cut uses the baseline's `scf`.
  - Name the testing sequence in the plan: which candidates share a call, and which is scored only after another passes. Holm adjusts only within one call, so a candidate added to a call needs a new locked plan.
- **Check the rule before and after locking it.** Try it first on a pair that barely differs, scored on a period already examined: the goal-clipping pair failed "no board losing more than 1.0 point" by chance (one board at −1.13, SE 0.53), which is why the board test uses the 95% upper bound. When restating a locked rule, or scoring a candidate whose rule was locked after the one the script encodes (next bullet), compare the two condition by condition and judge the candidate by its own rule, from the report's numbers, wherever they differ. A restatement of the ceiling candidate's rule once dropped its estimate condition; IMP-304 records how that rule differs from the script's. Correct a slip in a locked plan with a dated note, leaving the locked text as written.
- **Lock the rules, then score once.** Write the comparisons and the decision rule into the plan before any held-out result is seen. A period that shaped a candidate can screen it but not confirm it, so confirm on a period nobody has examined. The script's constants encode the rule locked on 2026-10-02: a gain of at least +0.25 percentage points of agreement with Holm p below 0.05, an equal-weight board average above zero, no board whose 95% upper bound is below −1.0, and, for the `--scf-cand` candidate, a dampened-team cut of at least 300 games whose estimate is no worse than −1.0 and whose 95% lower bound is no worse than −2.0.
- **Dampening off:** a run with dampening off writes no `scf` column. Pass `--scf-cand` for one such candidate per call, scored against a baseline with dampening on: its cut is the games of teams whose baseline `scf` is below 0.6 against opponents from other states, and a baseline without `scf` crashes. The flag defaults to `scf`, so a candidate named `scf` gets the cut without it.

## Step 6: Report Only What the Numbers Support

- After any change to the harness or the Python environment, run one A/A pair: the baseline twice. It must report zero engine or ML changes and no rank moves before a small nonzero count means anything.
- Call the agreement metric "agreement with recorded results (in-sample)". The ratings were fit to those same games, so it measures consistency with results already played, not predictive accuracy; unchanged agreement does not show a change is safe.
- Attribute movement with a controlled comparison: run the same upstream change with and without the ingredient in question, and report the net difference. Never report a `big_movers` label as the reason teams moved; counting co-occurrence once gave 839 where the controlled net was 411.
- Treat a large effect as neither harm nor benefit until an outcome test, such as a time split on later games, judges it.
- Report each outcome-test result under the verdict its locked rule gives, with the estimate and its 95% interval. Where that interval reaches the rule's harm threshold, describe it by those numbers, even under a pass, rather than as "no sign of harm", "protected" or "too noisy to call harm". A failed candidate rules out that change, not every alternative to it.
- Label every count of values that moved between two states (a game's result from win to draw, a team's status between runs) with its direction, and check the parts sum to the total. `pd.crosstab(before, after).to_dict()` is keyed by the `after` value first, so reading it as before-then-after reverses every transition.
- ML readings are percentile ranks, so one step is `100 · alpha / n` points of `powerscore_ml` on a board with `n` eligible teams (8 / n at alpha 0.08); the age anchor and the evidence gates shrink it further on the published scale. Set any fixed points threshold above the smallest board's step.
- A board's `today` is midnight while production rates as of the moment it runs, so a baseline board does not match production team for team. Base and candidate share the date, so their comparison is unaffected.
- Give the blast radius `.claude/rules/ranking-changes.md` asks for from the checks above, and keep the report's `provenance` and `freeze_manifest` with it.

## Step 7: Confirm the Committed Code Is What Was Measured

- `<run dir>/completed.json` records `loaded_module_sha256`, the sha256 of every module the board imported from its code root. Before committing, hash the same paths in the tree you commit and compare. Hash the working-tree files: with `core.autocrlf` on, `git show` output has different bytes.
- When an edit landed after the run, re-run the board, or show the edit is documentation only: revert it on a copy of the file and match the recorded sha256.
