# Reproducible ranking profile: release integration

The owner authorized production rollout on October 21, 2026 after reviewing the
corrected offline results. This branch connects that measured correction to the
production entry point. Publication is complete only after the full-board run
and the stored-ranking verification described below succeed.

## Exact profile

The ranking CLI selects `reproducible-v2` for Glicko, coupling:

- `fixed-prior-mode-v2`: a fixed Gaussian prior logistic posterior-mode estimator,
  not standard iterative Glicko-2. The prior, outcome scoring, raw recency/rematch
  weights, convergence equation, tolerances and maximum iterations are the
  measured implementation.
- `support-continuous-v2`: the same continuous publication transformation for
  every team. Selected same-gender results against same-age or older opponents
  earn outcome-weighted support. Older opponents keep their own-cohort quality;
  there is no new age multiplier or protected legacy final score.

The library defaults remain legacy. Explicit experimental configurations remain
blocked from live fetching and persistence. Only the named complete profile
admits the verified solver/policy combination to the normal production path.
Both passes receive the same profile and one resolved UTC calculation timestamp.
Unknown profiles, experimental solver overrides and mixed profile settings fail.
Non-convergence propagates and aborts the ranking calculation.

No team-specific ordering, manual rank target, eligibility change, new game
selection, scoring change, league adjustment, ML setting change or migration is
included. Evidence weights and support are diagnostics, not calibrated confidence
probabilities. The engine, posterior solver, publication functions, ML, adapters,
constants and merge handling retain the measured scoring implementation.

## Activation and rollback after approval

The existing all-board workflow command uses the new profile through the CLI:

```powershell
python scripts/calculate_rankings.py --ml --force-rebuild --engine glicko
```

Explicit selection is also available:

```powershell
python scripts/calculate_rankings.py --ml --force-rebuild --engine glicko --ranking-profile reproducible-v2
```

Rollback restores legacy ratings and hard-cap policy, retaining corrected UTC
date handling. Recalculate every board rather than mixing saved snapshots:

```powershell
python scripts/calculate_rankings.py --ml --force-rebuild --engine glicko --ranking-profile legacy
```

The v53e entry point keeps its existing default. The corrected profile rejects
filtered publication before creating a database client, because cleanup of a
partial board must not remove omitted teams. Use the existing dry-run mode for
filtered inspection. Production approval is required before any live command.
After an approved full run, verify the common calculation timestamp and board
coverage from stored rankings, then verify the Surf/Wenatchee scores and display
order from the newly published data. October 12 test ranks are not promised ranks
for a later production snapshot.

## Evidence and limits

Measured correction revision: `73e9a847e3be5811c635082d07169efc3a45ab47`.
The completed frozen October 12 comparison placed Surf third and Wenatchee
thirteenth in Washington, versus nineteenth and fourth under the legacy policy.
Cap-caused repeated-win reversals fell from 1,383 to 182. Both candidate runs
matched exactly, including all engine and ML stages. All 18 boards improved
agreement with already-played results; overall agreement was 77.3055 percent
versus 74.1648 percent. These are historical screening results, not predictive
validation or proof that individual placements are deserved.

Local integration checks verify the actual CLI, dry-run flags, full-board
publication requirement, exact agreement of the production adapter with the
explicit measured path, propagation to both passes, and fatal solver failures.
A separate source check confirms identical scoring syntax across all eleven
ranking dependencies after removing only the named-profile adapter wiring.
No additional full numerical experiment is introduced by this integration.
