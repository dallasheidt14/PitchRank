# November 14–15 Compare diagnostic

This is a separate preliminary test. It does not change public predictions, select
a winning model, qualify a challenger, or alter the November 16–January 10 studies.

Before November 14 UTC, register three forecasts for every eligible fixture in a
chosen authenticated forecast archive:

1. The original saved Compare forecast (55% model / 45% outcome prior).
2. The same TypeScript predictor with only the outcome blend changed to 75% / 25%.
3. The same predictor with both recent-form scalar contributions set to zero.

The unchanged research mode must reproduce the collecting predictor and saved
forecast before either alternative is accepted. Other signals, including ML trend,
goal profiles, ratings, volatility, and common opponents, remain fixed. Forecasts,
frozen inputs, replay receipts, code, cohort membership, grouping, and this protocol
are registered together in the existing private input-archive bucket. Registration
uses the database clock and must finish before November 14, 00:00 UTC.

Only November 14–15 targets qualify. Physical duplicates are deduplicated, reversed
orientations stay grouped, and inferred competition-week groups are labeled. No
outcome query runs before November 16, 00:00 UTC. Settlement must match the exact
original source and unchanged frozen forecast; conflicting duplicate results are
excluded.

The daily action checks at 10:20 AM Phoenix time. The first snapshot with at least
1,000 paired settled matches and 20 groups becomes the immutable private report.
Before that, it reports coverage only. If those minimums remain unmet on November
23 UTC, it saves an insufficient-data report. Repeated runs reuse the final report.
Results arriving after that snapshot do not silently replace it.

Primary measurement is multiclass log loss; secondary is multiclass Brier score.
Both count draws. Report winner accuracy under the existing decision policy, draw
calibration, margin error, 4+ risk, and provider/cohort/history slices. Paired group
bootstrap uses 2,000 resamples with seed 20261113 and 97.5% intervals for each of
the two baseline comparisons (Bonferroni family confidence 95%). Subgroup results
are descriptive. Missing settlements and inferred groups limit interpretation;
these weekend results alone cannot authorize deployment.

Preview commands create no files and write no remote data:

```powershell
python scripts/compare_weekend_tuning.py prepare SOURCE_ARCHIVE_SHA
python scripts/compare_weekend_tuning.py report WEEKEND_BUNDLE_SHA
```

Use a clean committed checkout, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`,
`SUPABASE_ACCESS_TOKEN`, and a new private output directory to prepare and register:

```powershell
python scripts/compare_weekend_tuning.py prepare SOURCE_ARCHIVE_SHA --execute --output-dir PRIVATE_NEW_DIRECTORY
```

After verifying the returned server registration time and archive contents, set
the GitHub Actions repository variable `COMPARE_WEEKEND_TUNING_ARCHIVE` to the
bundle SHA. The action also requires the `SUPABASE_ACCESS_TOKEN` repository secret
alongside its existing Supabase URL and service-key secrets. It resolves that
authenticated bundle's code revision and never uploads match data or accuracy
metrics to public Actions artifacts or logs. The full report stays private.
