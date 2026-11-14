# Compare transition fixes and separate ML experiment

`heuristic_v8_continuous_transitions_v1` blends adaptive feature weights continuously
between close-game and mismatch weights, avoiding abrupt probability changes at
threshold crossings. The sparse-history draw boost tapers from a five-point maximum
at equal win chances to zero at a six-point gap. It cannot raise draw probability
above 24%; an incoming draw probability above that level receives no boost.

Regression tests cover the audited rating-improvement cases, continuity,
normalization, team swaps and deterministic replay under website fallback settings.
They establish consistency, not improved winner accuracy.

The live ML coefficients remain unchanged. In particular, the additional
`residualSignal * 0.15` scoring-share term remains enabled.

## Private extra-ML experiment

From `frontend`, pass frozen cases on standard input to:

```sh
NODE_OPTIONS=--conditions=react-server npx tsx scripts/run-ml-share-research.ts < /private/frozen-cases.json
```

The payload has `cases`, each containing `context` and an explicit UTC
`reference_time`. Supply `prediction` when a saved reference is available; the
runner refuses a reference it cannot reproduce. Without a reference it labels
the baseline reconstructed. Explicit null calibration defaults require the
existing `verifiedProductionRuntime` flag and externally verified website
provenance; the flag alone does not establish that provenance.

Arm `1` reproduces the complete current baseline. Arm `0` disables only the extra
ML scoring-share term. It retains the first ML composite contribution, ML's
total-goals contribution, raw recent form, SOS and all other inputs. Every run
requires exact unchanged-mode parity and reports code hashes, original input
version and research version. It writes no database records and cannot promote
an arm. Freeze paired forecasts before matches to measure prospective accuracy;
reconstructed or synthetic output differences are not adoption evidence.

## Release and rollback

Verify the deployed runtime version and synthetic probes after release. Update
the live-monitor workflow's pinned revision only after a verified pilot. The
new predictor/research hashes create a separate monitoring registration. Preserve
earlier forecasts, studies and settings; never pool versions or read sealed
outcomes early. Reverting the release restores the prior live formula without
deleting either version's saved predictions.
