# Accuracy improvements with ceiling safeguards

User approved implementation on October 5, 2026. This release remains unmerged and
unpublished until an untouched-period decision and explicit publication approval.

## October 6 confirmation update

The completed September report and tested draft PR are delivered. The owner approved
implementation of the final decision plan and selected “Not sure—verify first” for
October exposure. The audit could not establish October independence, so the approved
fallback is now **November 1–30**, trained through **October 31**, for a decision in
early December. This supersedes the provisional October timing below; no scoring
threshold or release behavior changes.

See the [month audit](../reports/2026-10-06-ranking-confirmation-audit.md),
[execution record](ranking-confirmation-runbook.md) and
[pending evaluation lock](ranking-confirmation-lock.json). Design/source/runtime are
frozen; the data-bound lock remains invalid until the future training inputs and run
receipts are verified. No confirmation ranking run or outcome fetch has started.

## Fixed scope

Use the tested SCF-off default and convergence gender correction, restore connectivity
only inside ceiling decisions, and retain the stricter evidence ceiling when a freshness
restriction also applies. Preserve play-up and strong in-state relief. No game-selection,
threshold, iteration-limit, age-anchor, or board-pooling redesign belongs in this package.
Under-10 anchors, eligible-team ML normalization, and outcome-preserving goal clipping
are already in main.

References remain pinned: October combination `b46c20813`, C1 `e0ccc2c04`, and the
ceiling rule-order change `c03d7612`. The release starts from main `974ad02f8`.
Its ranking code is unchanged from the original September incumbent `8338d25a7`.

## Implementation contract

The normal Glicko ranking command explicitly enables `ceiling_connectivity_enabled`.
The library retains its false default for controlled comparisons. Enabled mode requires
Glicko and SCF off, transports diagnostics separately from ordinary engine/ML rows,
validates the surviving source cohort, and bypasses engine-cache reads and writes.
The production path may fetch and persist; the offline harness continues blocking all
network and database writes independently. Missing diagnostics abort before final
ranking publication. No migration or public API is introduced.

## Bounded verification

On the saved August 31 freeze, complete two repetitions of the original combination,
one C1 run, and one release run. Preserve stopped artifacts in their original directory.
Require exact baseline reproduction and exact selected games, eligibility, upstream
helper results and pre-ceiling scores for both safeguard comparisons. Record hashes,
completion receipts, all 18 boards, U10 separately and combined, and movement over
25/100/300 positions. Report September descriptively, without an adoption verdict.

Reproduce the Texas U13 boys and Washington U13 girls cases; inspect every flagged
top-25/top-100 placement, including the older opponents credited to play-up cases.
Flags identify review cases, not proven weak teams. Run focused and full checks,
production-entry and dry-run tests, independent mutation checks, and pre-push review.

## Untouched evaluation

The original October comparison, candidate family, and scoring rules stay unchanged.
Only after that comparison passes, evaluate the complete release against the fixed
combination. C1 alone is diagnostic, not another holdout candidate. Use the
`ceiling-release` scorer profile and its separate lock, never a C1 lock relabelled after
outcomes have been viewed.

Second-stage rules: gain at least +0.25 percentage points with dyadic p < .05;
positive equal-weight mean across all 18 boards; no board or isolation subgroup with
a 95% upper bound below -1; isolation subgroup n >= 300, estimate >= -1 and lower
bound >= -2. Define isolated teams from incumbent SCF < .6 on the same training
freeze and count a game once when either qualifying team plays a known other state.
Verdicts: void, harm, pass, inconclusive. Incomplete statistics cannot pass.

The final package also receives a cumulative board/isolation harm veto against the
incumbent: a 95% upper bound below -1 overrides an incremental pass. This is not a
third improvement hypothesis; report estimates and intervals even when not conclusive.

Lock exact code, scorer, comparisons, inputs and unseen-outcome attestation before
reading October results. Train through September 30, evaluate October 1-31 after the
month ends. If October informed the design, use the next untouched complete month.
This document records the approved design, not a completed data-bound lock.

## Completion and publication

Immediate deliverables: tested release branch, draft PR, completed descriptive September
report. Final deliverable: one documented ship-or-reject decision. Failure or uncertainty
does not authorize adoption. No new redesign is silently added if the package fails.

After a pass, present the measured release for merge/publication approval. Before its
first publication, record the previous release and publication snapshot. Afterward verify
stored values, every board, and the investigated cases. A release-caused defect requires
reverting the package and rebuilding with the prior engine. A green workflow alone is
not proof of correct publication.
