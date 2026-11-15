# Compare formula diagnostics

This offline study explains formula behavior and compares SOS and record alternatives on identical frozen inputs. It cannot change the website, register a candidate, or write to the forecast ledger. Predictor source remains pinned to `c061cfc042953d0e677ea5474cbb509758f14593` (`heuristic_v8_continuous_transitions_v1`); calibration comes from the registered frozen runtime snapshot.

## Run the study

Use a checkout of this research change with its locked frontend dependencies. The runner verifies the collecting predictor's source hashes and refuses a different version. After a live formula change, retain this checkout for this study; do not update the pin to combine experiments.

Create a private, gitignored output directory first. The Python commands read `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` from the environment. Do not paste credentials into commands or commit the artifacts.

```powershell
# Repository root. Preview counts only; no files or database writes.
python -B scripts/export_compare_formula_inputs.py --signature c24e9a7feb9e34b45209ae5aeb369ec0ba1d7982ec3debb6fba3490e4ad13b9b

# Save a new immutable input export. Never reads target scores.
python -B scripts/export_compare_formula_inputs.py --signature c24e9a7feb9e34b45209ae5aeb369ec0ba1d7982ec3debb6fba3490e4ad13b9b --execute --output .turbo/formula-study/inputs.json

cd frontend
# Runs in memory and prints aggregate diagnostics. No output files by default.
node scripts/audit-compare-formula.mjs --input ../.turbo/formula-study/inputs.json --synthetic

# Save traces, candidate outputs and history audits privately.
node scripts/audit-compare-formula.mjs --input ../.turbo/formula-study/inputs.json --synthetic --execute --output ../.turbo/formula-study/formula.json

cd ..
# Preview only. The existing server gate decides which results are open.
python -B scripts/evaluate_compare_formula.py --report .turbo/formula-study/formula.json

# When results are open, score them and save a new private report.
python -B scripts/evaluate_compare_formula.py --report .turbo/formula-study/formula.json --execute --output .turbo/formula-study/evaluation.json
```

Use a new filename for each saved artifact; existing files are never overwritten. All output commands require an ignored directory. `--execute` permits local artifact writes; these tools have no database mutation path. Use the `.mjs` launcher so loader disk caching is disabled before TypeScript loads.

The exporter first reads capture metadata and the frozen history query's date cutoff, without scores. It withholds captures whose histories could contain protected results before requesting their payloads. The existing date-wide release gate seals a continuous suffix of past dates: every active protected interval extends through today. It checks the later of the UTC capture day and the frozen query cutoff, covering retained games, omissions and differences between collector and server clocks. Missing or invalid history cutoffs are withheld separately. The export records withheld captures and release decisions alongside the server cutoff, model registration, capture timestamps and eligible payloads. If all captures are withheld, stop after the coverage preview and retry after their dates are released; the formula runner requires at least one eligible capture.

Reports include input, configuration, source and generated-code hashes, the Node/TypeScript versions, and the original forecast clock. Null calibration files remain null, preserving the website's built-in defaults. The runner compiles the actual TypeScript source in memory and requires unchanged-mode equality for all prediction fields plus replay against the saved baseline.

## Experiments and trace

The baseline is the SOS multiplier 1 arm. The other multiplier arms are 0, 0.5 and 1.5. Constant SOS arms use 0.06, 0.12 or 0.18 while retaining each fixture's baseline values for all other coefficients; there is no renormalization. The final arm disables only `recordDiff * 0.08`. Its record fallback inside the strength calculation remains available when Glicko is absent. No arm combines changes, and both ML contributions remain intact.

Each trace records strength, adaptive weights, every additive contribution, mismatch amplification, goal share, projected goals and pre-calibration probabilities. Separate diagnostic controls hold all four adaptive weights fixed or only SOS fixed during a one-input perturbation. They explain interactions and are not candidates.

The deterministic synthetic suite uses seed 1449 and the original 1,500 input pairs. Additional sweeps cover both sides of the 0.05/0.08 PowerScore transition, positive/negative rating gaps and aligned/conflicting schedules. Reports include reversal counts, largest drops, changed winners, controls and team-swap checks. These are behavioral tests, not accuracy measurements.

## History and result boundaries

The history audit observes the saved games and uses the pinned service's source-fixture parser and ordering. It reports missing/short histories, recent-game ages, repeated opponents, missing ML, invalid scores, exclusions, future results and ordering problems. It flags repeated proven source keys for investigation without filtering games. Same-day teams and scores, or different team-history URLs, cannot prove a duplicate or a rematch.

Frozen history cannot reveal a game that was never fetched. Pagination, merge resolution, exclusions and same-day ordering are also exercised through the real fetch path in `seedingPredictions.test.ts`. Fresh database observations must be labeled separately from frozen replay and must exclude protected target dates; they cannot replace the archived inputs in a backtest.

Result evaluation uses the existing `compare_monitor_review` server gate before looking up any score. Preview reads no outcomes. Execution resolves only released fixtures through the existing exact-source settlement function, without writing a settlement. It reports missing candidates, unresolved results and unknown groups. Duplicate/reversed observations share one physical result; the earliest capture wins for every arm.

Fewer than 1,000 paired settled matches or 20 event groups produces coverage only. Above that threshold, the report includes log loss, Brier score, accuracy of the predictor's emitted winner, draw calibration, margin error, four-goal risk, provider/age/history slices and paired group-bootstrap intervals. Groups retain their verified-event or inferred-competition-week labels. Saved evaluations retain the replay digest, model/configuration identity, server observation time and exact scored observations so later result corrections are traceable. All alternative outputs are reconstructed from frozen inputs, not claimed as pre-match captures. These comparisons authorize neither candidate selection nor deployment; any release needs a separate reviewed confirmation experiment.

## SOS already present in ratings

The production joint rating snapshot estimates team strength from a connected network of opponents. `JointFieldScoring.effective_map` supplies those strengths to `glicko_engine` for schedule and performance summaries; the ranking pipeline then applies normalization, uncertainty, publication support and the ML layer. Compare consumes those published ratings and offense/defense summaries, then adds its own SOS contribution.

That establishes overlapping information paths, not harmful double counting. Changing the extra contribution requires paired accuracy evidence. A synthetic reversal alone does not justify altering the production ranking engine or Compare weights.
