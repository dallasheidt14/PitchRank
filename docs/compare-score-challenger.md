# Offline Compare score candidates

These candidates adjust projected scores while preserving the collecting predictor's
three outcome probabilities and selected winner. They are not imported by the live
Compare API, registered automatically, or enabled by a public feature flag.

The default candidate, `blend_25`, mixes 75% of the baseline score distribution with
25% of a supplied learned attack/defense distribution. `tail_guard_full` is a separate
experiment that uses the learned distribution while preserving the baseline's reported
four-goal-margin probability. `baseline` returns the original prediction unchanged.
Do not silently combine the two experimental definitions.

Both distributions are independent Poisson score grids from zero through 40 goals,
conditioned on the baseline's final win/draw probabilities. Each displayed candidate
score is the most probable score consistent with the baseline's selected outcome.
Equal modal cells prefer the lowest total, then the smallest margin. Unsupported goal
rates fail rather than truncate substantial probability mass. The baseline control
retains the original displayed score, even when it differs from the grid's mode.

## Build a private replay

Supply an existing frozen rate-batch JSON and its fitted-model JSON. The batch's
`model_sha256` must match the model's exact bytes. Preview computes the candidates
and prints aggregate coverage; it writes nothing:

```powershell
python scripts/build_compare_score_challenger.py --input C:/private/rate-batch.json --fit C:/private/fitted-model.json
```

To save a new artifact, pass `--execute --output` together. Its parent directory must
exist and Git must ignore the destination. Existing artifacts cannot be overwritten.

```powershell
python scripts/build_compare_score_challenger.py --input C:/private/rate-batch.json --fit C:/private/fitted-model.json --candidate blend_25 --execute --output .turbo/private-score-blend.json
```

The batch contract is:

- `model_sha256`: SHA256 of the supplied fit file.
- `rows`: nonempty list with unique `id` baseline forecast IDs and unique exact
  `source_game_id` fixture IDs, plus ISO `game_date` and explicit `eligibility`.
- Each row has `variants.baseline` in the Compare prediction format and two
  `learned_rates`, ordered team A then team B. Missing rates or a status other than
  `eligible` retain the full baseline and report the fallback reason.
- The fit's `receipt` supplies `cutoff`, `latest_training_game`, and a successful
  `optimizer_success`. Training results must precede both cutoff and target day.

The runner hashes its input, fit, code, and candidate definition. Its candidate signature
binds the configuration, scorer code, and model; input hashes identify each batch.
This tool consumes the rates already supplied in the frozen batch. It does not
independently reconstruct them from fitted parameters or authenticate archive provenance.

## Evaluation and release

Replay matching baseline and candidate fixtures, including unchanged fallbacks. Track
displayed goal error, exact scores, score log loss, four-goal risk, and eligible coverage.
Verify winner probabilities and decisions are identical before interpreting score gains.
Tail-protected risk is unchanged by construction; do not report it as a risk improvement.

These outputs are explicitly offline replays. They do not establish capture before kickoff,
authorize deployment, or register a prospective study. Future confirmation must bind the
candidate code and fitted model before collection, preserve the baseline's exact source
identity, record missing captures, and respect existing sealed study windows. Keep all
existing frozen forecasts and manifests intact; create a distinct candidate artifact.
