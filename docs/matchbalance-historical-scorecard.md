# Historical prediction scorecard

Audited on 2026-10-07. This is an audit of an archived original-fixture replay,
not a new validation of the current predictor or observed results from proposed
divisions. The archived model failed its blowout-rate tolerance.

## Population and evidence

- Event: SAN ANTONIO LABOR CUP 26, GotSport 51783, U14 Boys.
- Run: `u14_male_20260915T221528_930fee90aafe`, completed September 15, 2026.
- Exclusive pre-event cutoff: September 5, 2026, 00:00 UTC.
- All 16 rating snapshots were created and calculated before the cutoff.
- All 231 history games occurred and were recorded before the cutoff. The
  latest game was August 30; the latest recording was September 2.
- Calibration availability was April 20, 2026, before the cutoff.
- The frozen input digest was recomputed successfully. The 29 observed game
  IDs are unique; their score margins reproduce the archived result totals.
- Predictions cover the captured original fixture graph, 29 of 29 matches.

## Results on the original schedule

| Metric | Observed | Projected | Error / saved criterion |
| --- | ---: | ---: | --- |
| Mean absolute goal difference | 2.172 | 1.470 | 0.703 goals; within the 1.0 tolerance |
| Four-or-more-goal margin | 6 / 29 (20.69%) | 6.83% average probability | 13.86 percentage points; exceeds the 10-point tolerance |
| Fixture count coverage | 29 | 29 | 100%; above the 95% minimum |

The margin error above is the difference between two cohort averages. It is
**not** per-match mean absolute error. No per-match probability calibration or
confidence interval is claimed from these aggregate metrics.

The model underpredicted severe mismatches on this cohort. Keep existing
competitive limits and provisional-history warnings; this scorecard does not
justify relaxing them. One event is insufficient to establish general accuracy.

## Reproducibility and limits

The read-only audit used `historical_inputs.json`, `request.json`, `summary.json`,
and `run_metadata.json` in the event's `reviewed-backtest/runs` folder. It checked
the input digest, every input's availability date, completion state, predictor
identity agreement, unique observed fixtures, and observed margin totals. The
saved sources remained byte-for-byte unchanged.

- Input digest: `bc91462855f59abbc8dfc095a2f223ef247888e4581079f33de3fadd94a479e8`
- Archived predictor: `274e0ff4a3791a30774d6496fd1aa112dc994b57c81f2746a7272946697ef4af`
- Historical input file: `1f27181de2855729e9c7ae14e21fb6236d36f65ebda29837c3b5fd689e4ab7b3`
- Summary file: `828218e3712eb3029ada765c5895a5933f182dc6b5363016e2e34476db867e80`

Current-predictor accuracy still requires a separately versioned historical
replay over more events. Alternative strength-tier benefits remain projections:
those alternative matchups were not played, and this release makes no claim of
measured improvement in actual tournament outcomes. Backtest remains separate
from the Seeding operator workflow.
