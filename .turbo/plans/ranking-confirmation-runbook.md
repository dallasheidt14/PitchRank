# November confirmation execution record

Status: design frozen October 6; waiting for the October 31 training cutoff. No decision or publication is authorized.

The [month audit](../reports/2026-10-06-ranking-confirmation-audit.md) selects November. The [machine-readable design and pending lock](ranking-confirmation-lock.json) is authoritative for code hashes, configurations, runtime, exact comparison family and run inventory. Preserve the existing September evidence and references. The September completion worker must not be reused: it directly computes descriptive statistics without the confirmation gates.

## Training preparation — November 1, 2026, 9 AM Arizona or later

1. Verify every frozen source, capture-tool and runtime entry before fetching data. Do not fast-forward the four reference worktrees or silently accept changed packages. If a frozen dependency is unavailable or differs, stop and report it.
2. Inspect `C:\Users\Dallas Heidt\Documents\PitchRank validation\confirmation-2026-11` for existing receipts and matching PID/create-time identities before starting anything. Reuse valid completed phases. A partial or stopped phase is evidence to inspect, not permission to overwrite or launch another full batch.
3. Use the recorded capture `shadow_harness.py freeze`, incumbent code root, existing local environment file, `--today 2026-10-31` and a new `training` output directory. This is a read-only fetch. Confirm the manifest and every game date are at or before October 31; hash games, team metadata and merge map. Do not fetch November outcomes at this stage.
4. Execute exactly the five recorded board runs sequentially: incumbent, combo-a1, combo-a2, c1-diagnostic, release. Use `--capture-stages` for each, and `--ceiling-connectivity` only for C1 and release. Check 6.5 GiB free before each run. Save exclusive process/start/completion receipts and logs; use hidden background processes on Windows. All database persistence remains disabled.
5. Validate every run with `c1_validation.validate_run`. Require exact final-team equality for combo-a1 versus combo-a2, plus exact boundary comparisons for C1 versus combo-a1, release versus combo-a1, and release versus C1. Verify selected-game multiplicities, eligibility, engine/ML/helper stages, pre-ceiling scores, input/output hashes, configuration, runtime and loaded module hashes. Any missing data, mismatch or run failure stops the batch; preserve evidence and report the cause. No automatic extra batch.
6. Create a new `evaluation-lock.json` in the artifact directory from the committed pending lock. Bind the training-manifest hash and role source hashes from validated provenance; verify these equal the design record. Record a UTC timestamp and justified continued lack of November outcome access, then set the final lock booleans true. Record all completion-receipt hashes in a companion execution receipt. Preserve the pending template unchanged.

## Outcome evaluation — December 1, 2026, 9 AM Arizona or later

Before any November result access, verify the final lock, source hashes, exact dates, validated receipts and absence of design changes. A missing or invalid lock blocks the outcome fetch. Read November results once after the month ends into a new immutable held-out freeze with `--today 2026-11-30`; record capture time and hashes. Score only November 1–30. Report data coverage and missing results; do not silently extend the month or fetch a more favorable sample.

Use the pinned release scorer and these fixed arguments, with paths rooted in the artifact directory:

```text
score_later_games.py --profile legacy --base incumbent --cand scfgender=combo-a1 --scf-cand scfgender --record-evaluation --train-freeze training --heldout-freeze heldout --start 2026-11-01 --end 2026-11-30 --out first-stage.json
```

The legacy scorer can emit a verdict even when checks fail. Independently validate run receipts, cutoff ordering, intended candidate family, subgroup flag, all 18 board estimates and input bindings before accepting it. Only a valid first-stage `pass` permits the second command. Failure, inconclusive evidence or an invalid run means no adoption; do not evaluate the package on outcomes after a failed prerequisite.

```text
score_later_games.py --profile ceiling-release --base combo-a1 --cand release=release --isolation-reference incumbent --prerequisite-report first-stage.json --design-lock evaluation-lock.json --train-freeze training --heldout-freeze heldout --start 2026-11-01 --end 2026-11-30 --out release-decision.json
```

Retain the existing +0.25-point improvement, p < .05, positive equal-board average and isolation sample/interval rules. A significant overall loss, credible board/isolation harm, or cumulative harm versus incumbent takes precedence over a pass. Missing statistics cannot pass. The numerical rules and comparison sequence are copied exactly into the lock; no threshold or hypothesis changes after outcomes are accessed. C1 is only for boundary, movement and placement diagnostics, not a third outcome test.

## Decision report and publication boundary

Report both stages when legitimately evaluated, all 18 boards, U10 boys/girls/pooled, isolation estimates and intervals, eligibility, movement over 25/100/300 places, and the fixed thin-evidence top-25/top-100 flag from the September report. Inspect the full flagged union across combination, C1 and release; include every retained play-up exception and its credited older opponents. Recheck Texas `8f77aa25-9bef-492d-a4b1-add0ef8eaed8` and Washington `5cbbc1e9-e08f-4a0d-b991-ffde8a021c20`, including their score/ceiling path. New-month positions need not equal September ranks. Flag counts alone are not proof of quality.

Update draft PR #1255 with one decision. Failure or inconclusive evidence means **do not ship** and ends this release effort. An invalid run means no publication and a concrete failure report; it does not authorize unbounded reruns. A pass leads to one explicit owner approval request including expected movement and unresolved uncertainty. No automatic merge or publication.

After approval only, record the prior release and publication snapshot, run the normal production workflow, and verify stored scores/ranks, all 18 boards and investigated cases. A release-caused defect requires reverting the package and rebuilding with the prior engine. Keep the previous September heartbeat paused; any new automatic follow-up needs authorization for these later checkpoints.
