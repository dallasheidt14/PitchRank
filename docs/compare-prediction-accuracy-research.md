# Compare tab and game predictions: how to make them more accurate

Research report, 2026-09-24. Read-only: nothing in this document changes production.
It surveys the code, the committed evidence, the project's own history, and the
published literature on soccer match prediction, and ends with a phased plan.

The database was not reachable from the session that wrote this, so every number below
comes from committed files, pull request bodies, or a synthetic run of the live predictor.
Section 8 lists what to measure first once a database session is available.

---

## 1. Plain-English summary

**What the compare tab does today.** When you pick two teams, the site adds up about a
dozen hand-weighted signals (rating gap, strength of schedule, last-eight-game form,
offense-versus-defense matchup, win record, head-to-head, common opponents, and several
"evidence" adjustments), squashes the sum into a share of goals, splits an age-typical
goal total between the two teams, and reads win / draw / loss chances off two independent
Poisson goal distributions. It then pushes those chances through two hand-fitted
corrections, and finally mixes 45% of a fixed prior (43% / 13% / 43%) into whatever came
out.

**How accurate it actually is.** On about a thousand real pre-game forecasts frozen in
April 2026, the live model picked the right result 56 to 58% of the time and scored a
three-way log loss of 0.93. Guessing "each result is equally likely" would score 1.10, so
the model is only modestly better than knowing nothing. It called a draw on 1.3% of games
while 13 to 16% of games are draws. The "74.7% accuracy" still quoted in
`docs/MATCH_PREDICTION_IMPLEMENTATION.md` was an in-sample number from January 2025 on
594 games, measured with current rankings leaking into past games. It does not describe
the live model.

**The single biggest problem is a hard ceiling on confidence.** Because of the final prior
blend, the compare tab can never give any team more than about a 73% chance of winning,
or less than about a 20% chance of losing. Running the live predictor on the number one
team in a cohort against the worst team gives 73% / 7% / 20%, when the teams' own Glicko
ratings say 99%. Youth soccer is full of mismatches (16 to 28% of games are decided by
four or more goals, depending on age), and the model is forced to be wrong-footed on every
one of them. Fixing this alone should move log loss more than anything else on the list.

**The second problem is that the probability engine has no statistical basis.** The
chain of weights, sigmoids, and correction tables was tuned by hand, mostly on in-sample
data, and it double-counts the same games several times over. The published research is
consistent: a well-fitted model on the rating gap alone (an "ordered logit", one slope and
two cut points per cohort) beats form-based and hand-weighted models, and recent form adds
roughly nothing once the rating already decays old games. PitchRank already has the
ingredients this needs: Glicko mu and RD, offense and defense residuals, cohort goal
averages, and a weekly point-in-time snapshot table since April 2026.

**The recommended order of work** is in section 7. In one line: build an honest
walk-forward scorecard first, replace the probability core with a fitted rating-gap
model, derive the scoreline from attack-and-defense Poisson means with a per-cohort draw
correction, and only then consider a gradient-boosted model on top. Each step is gated on
the scorecard, not on a re-run of the current in-sample tuning scripts.

---

## 2. Terms used below, in plain words

- **Log loss.** How surprised the model is by what actually happened, averaged over games.
  Lower is better. Predicting "33% each" scores 1.10 on three outcomes. Top-league
  bookmakers sit near 1.0 on balanced leagues and near 0.81 on the World Cup, where
  mismatches are common. Youth soccer should sit closer to the World Cup regime.
- **Brier score.** Squared error between the probabilities and what happened. Lower is
  better. Also usable per outcome ("was the draw probability right on average?").
- **RPS (ranked probability score).** Brier's cousin that treats "predicted a win, got a
  draw" as less wrong than "predicted a win, got a loss". The soccer-prediction
  convention. Around 0.19 to 0.21 is the professional benchmark.
- **Calibration.** When the model says 70%, does that team win about 70% of the time? A
  reliability table checks this bucket by bucket. "Classwise" means checking the draw
  column on its own, which is where youth models usually fail first.
- **Walk-forward evaluation.** Predict each game using only what was known the day before
  it, then score. This is the only evaluation that counts. Anything else leaks the answer.
- **Ordered logit.** Turn a single number (the rating gap) into three probabilities using
  one slope and two cut points, fitted by maximum likelihood. Simple, stable, and the
  model that won the 2010 comparison against every form-based alternative.
- **Poisson goal model.** Assume each team's goals follow a Poisson distribution with a
  mean set by its attack, the opponent's defense, and the cohort's typical total. The
  grid of scoreline probabilities then gives win, draw, loss, expected margin, and the
  chance of a blowout, all from one coherent source.
- **Dixon-Coles / diagonal inflation.** Small corrections to the Poisson grid that give
  draws the extra mass independent Poisson under-predicts.

---

## 3. What the compare tab does today

The request path is `frontend/app/api/match-prediction/route.ts` →
`frontend/lib/matchPredictionService.ts` → `predictMatch` in `frontend/lib/matchPredictor.ts`.
No Python model runs on the request path. The version string is
`heuristic_v6_neutral_selection_prior`. The same function drives MatchBalance seeding and
backtests and the head-to-head infographic.

Inputs per team: `power_score_final`, `glicko_rating`, `glicko_rd`, `sos_norm`,
`offense_norm`, `defense_norm`, record, ten same-age "evidence" columns, four
`team_predictive_view` columns (absent in the live schema, so null), and up to 365 days
of both teams' scored games.

The computation, in order (line numbers refer to `frontend/lib/matchPredictor.ts` at
commit `03086132`):

1. `powerDiff`, shrunk toward neutral by an evidence reliability score (`:1161-1164`).
2. Glicko gap → Elo-style win probability → multiplied by an RD reliability factor and
   by 0.55, then added to `0.25 × powerDiff` and a predictive-view signal (`:1206-1208`).
3. Adaptive weights by mismatch score, then a weighted sum of strength, SOS, form,
   matchup, record, ML residual trend, evidence gap, head-to-head, and common-opponent
   signals (`:1210-1225`), with a further amplification above mismatch 0.4.
4. Cohort goal total from `age_group_parameters.json`, adjusted by offense, defense,
   recent totals (`:1247-1275`); goal share from `sigmoid(4.34 × compositeDiff)`;
   margin rescaled by an age multiplier; both means clamped to [0.15, 7.5] (`:1277-1295`).
5. Independent Poisson grid to 10 goals → win / draw / loss, modal score, P(4+ goal
   margin) (`buildOutcomeDistribution`, `:1045`).
6. The decisive share (win A over win A + win B) goes through a hand-typed piecewise
   table (`calibrateProbability`, `:724-772`) whose source data is discussed in 5.4.
7. A draw boost for close and sparse matchups (`:1321-1331`).
8. The prior blend: `p_out = 0.55 × p + 0.45 × prior` with prior 0.433 / 0.133 / 0.433
   (`applyOutcomeCalibration`, `:875-908`, parameters in
   `frontend/public/data/calibration/heuristic_outcome_calibration.json`).
9. Predicted winner is the larger win probability; a draw is called only for U13 and U15
   when the raw draw probability crosses a threshold and the win gap is under 0.10.

What the user sees (`EnhancedPredictionCard.tsx`): a rounded modal score, three
probability bars, a confidence badge, and four explanation factors.

---

## 4. What the evidence says

| Measurement | Model | Sample | Result | Source |
|---|---|---|---|---|
| Winner accuracy, all settled pre-game forecasts | live heuristic v4+ | settled prospective rows through 2026-04-20 | **56.4%** | `heuristic_outcome_calibration.json` |
| Same, Apr 17-19 holdout | live heuristic v4+ | 1,077 frozen forecasts | **58.3%**, log loss **0.927** | same file; PR #1190 |
| Predicted draw rate / draw recall | live heuristic v4+ | same | 1.3% predicted, 3.2% recall, vs 13.3% actual draws | same file |
| Temperature re-calibration benchmark | live heuristic | 795 dev + 1,072 holdout games | no holdout improvement, no production change | PR #1194 |
| Rolling walk-forward, 5 folds Jan-Nov 2025 | Python port of the older heuristic | 57K to 118K games per fold | accuracy 0.42 / 0.44 / 0.47 / 0.51 / 0.58, margin MAE 2.55; 97% of rows had age "unknown" | `data/calibration/cross_validation_results.json` |
| Reliability by bucket | older sigmoid | 452K games | 60-65% predicted → 74% actual; **70-75% predicted → 37% actual** (n=2,624) | `data/calibration/probability_parameters.json` |
| Margin MAE | older heuristic | 452K games | 2.47 goals vs 2.57 baseline; blowout MAE 5.3 | `margin_parameters_v2.json` |
| Original validation | v53e-era TS model | 594 games, in-sample, current-rankings leak (fixed in PR #551) | "74.7%", Brier 0.158 | `docs/MATCH_PREDICTION_IMPLEMENTATION.md` |
| Binary XGBoost | `MLMatchPredictor` | 1,000 / 4,000 test rows, random split, current rankings | 76% / 66%; inflated | `models/match_predictor/*_metadata.json` |
| Glicko rating only, ranking-engine backtest | engine, SCF on vs off | 13,702 holdout games, u17F + u16M | log loss 0.63 → 0.57, accuracy 67.9% → 71.6% | `.turbo/plans/scf-off-staging.md`; harness never committed (IMP-058); loss scale suggests two-way |

Data facts that shape the modelling, from `age_group_parameters.json` and
`docs/matchbalance-backtest-intake.md`:

| Age | Avg goals per team | Games decided by 4+ | Median margin |
|---|---|---|---|
| u10 | 3.06 | 27.9% | 3 |
| u11 | 2.73 | 23.7% | 2 |
| u12 | 2.44 | 19.6% | 2 |
| u13 | 2.22 | 18.2% | 2 |
| u14 | 2.02 | 16.6% | 2 |
| u15-u16 | 1.90-1.95 | 15.2% | 2 |

One tournament (San Antonio Labor Cup, 613 scored games) averaged a 3.0-goal margin with
32% of games decided by four or more, roughly double the league-wide rate. Tournament and
league play behave differently and the model currently cannot tell them apart except
through `event_name`.

The games table stores a date but no kickoff time, has home and away columns but no
neutral-site flag, and carries no lineups.

### 4.1 Synthetic run of the live predictor

Run on 2026-09-24 against `matchPredictor.ts` at commit `03086132`, with the committed
calibration files loaded, two U13 boys teams with no game history, RD 60:

| Matchup | Win A | Draw | Win B | Score | Margin | P(4+) | Glicko-only win A |
|---|---|---|---|---|---|---|---|
| Equal teams | 38% | 24% | 38% | 2-2 | 0.0 | 9% | 50% |
| +100 Glicko, +0.05 power | 46% | 17% | 37% | 2-1 | 0.35 | 9% | 64% |
| +200 Glicko, +0.10 power, off/def +0.1 | 62% | 12% | 26% | 3-0 | 2.2 | 26% | 76% |
| +400 Glicko, +0.30 power, off/def +0.3 | 72% | 8% | 20% | 3-0 | 3.7 | 51% | 91% |
| Rank 1 vs bottom, +800 Glicko, power 0.95 vs 0.05 | **73%** | 7% | **20%** | 4-0 | 4.4 | 64% | 99% |

Two things stand out. The fourth row says there is a 51% chance of a four-goal margin and
a 20% chance the favourite loses, which is not internally coherent. And the last two rows
are nearly identical: past a 400-point gap the model stops distinguishing.

---

## 5. Findings, ranked by expected effect on accuracy

### 5.1 The prior blend caps every forecast at roughly 73 / 20

`applyOutcomeCalibration` computes `0.55 × p + 0.45 × prior` for each outcome. With prior
0.433 for each win slot, the maximum any win probability can reach is
`0.55 × 1.0 + 0.45 × 0.433 = 0.745`, and the minimum is `0.45 × 0.433 = 0.195`. The
draw floor is `0.45 × 0.133 = 0.06`.

That blend was selected in April 2026 on settled tournament forecasts because it lowered
log loss versus the then-current model. It did so by fixing overconfidence on close games
at the cost of making mismatches, which are the majority of decisive youth games, badly
under-confident. A linear shrink toward a constant is the wrong shape for that problem.
The right shape is a fitted curve (section 6.2) that is soft near a zero gap and sharp at
large gaps.

Expected effect of fixing: large, on log loss and Brier, concentrated in the 20 to 30%
of games that are mismatches. Winner accuracy will move less because the ordering of
outcomes is unchanged.

### 5.2 The probability core is a stack of hand-tuned heuristics that double-count

`compositeDiff` sums nine signals, at least six of which are functions of the same
games: `power_score_final` already contains SOS, offense, defense, and ML Layer 13;
`sos_norm` is added again; `offense_norm` and `defense_norm` enter through the matchup
term and the mismatch amplifier; the win record, form, and common-opponent signals all
re-read the same recent results. The weights (`BASE_WEIGHTS`, `BLOWOUT_WEIGHTS`, the
`0.08 / 0.06 / 0.07 / 0.08` coefficients, `4.34` sensitivity) were tuned on the 594-game
in-sample set and later on a 0.03-point improvement (`optimal_weights.json`: 0.58919 →
0.58954).

The literature is consistent that a rating-gap model with an ordered logit beats every
form-based and hand-weighted benchmark short of bookmaker odds (Hvattum and Arntzen 2010),
that the 2017 and 2023 Soccer Prediction Challenge winners were rating features plus a
regularised gradient-boosted tree, and that recent form adds close to nothing once the
rating already decays old games. PitchRank's Glicko already has a 365-day window with a
recency lambda.

Expected effect: cleaner, more stable probabilities and far fewer parameters to drift.
Measured directly by the baseline ladder in 7.1.

### 5.3 Draws are modelled three separate ways and none is fitted

The Poisson grid supplies a draw mass; a "sparse close matchup" rule adds up to 5 points;
the prior blend adds a constant; two ages get an argmax override. The result predicts a
draw as the outcome on 1.3% of games, against a 13 to 16% base rate. Argmax will rarely
pick a draw in any three-way model, so "draw recall" is not the metric to chase. What
matters for log loss is whether the *draw probability* is right on average within each
bucket, which no committed report checks. Independent Poisson is known to under-predict
draws; the fixes are a Dixon-Coles rho or a diagonal-inflation weight, fitted per cohort,
and letting the draw term fall as expected total goals rise (younger cohorts score more,
so draw less).

### 5.4 The piecewise calibration table is built on data that is itself broken

`calibrateProbability` interpolates a table hand-transcribed from
`probability_parameters.json`. That file says teams predicted at 70 to 75% won 37% of the
time (n=2,624) while teams predicted at 60 to 65% won 74% (n=120,119). Real calibration
curves are never that non-monotonic at those sample sizes; that pattern is a sign of an
orientation or sign bug in the script that produced it, and 97% of the same run's rows
had age "unknown". The table was then pooled into a flat 0.686 across 62.5 to 72.5% raw.
The code applies this correction to the *decisive share* and then applies the prior blend
on top, so two corrections of unknown provenance stack. Both should be deleted and
replaced by one fitted curve.

### 5.5 The evaluation tooling cannot currently tell a better model from a worse one

- `scripts/predictor_python.py` claims to mirror the TypeScript predictor but has no
  draw probability, so `scripts/backtest_predictor.py` writes `draw_probability = 0`
  for every game. Every real draw is then scored at epsilon probability, which makes the
  backtest's log loss and Brier meaningless for three-way evaluation.
- `backtest_predictor.py` falls back to current rankings when no snapshot exists, which
  leaks the future; its own header says so.
- `MLMatchPredictor` uses a random split and current rankings (IMP-003, dropped unfixed).
- `PointInTimeMatchModel` tunes its draw label policy on training predictions, boosts
  draw class weights 1.6×, and fits its optional calibrator on the same holdout it then
  reports. Its only artifact expired on 2026-04-27 and the training workflow has failed
  since 2026-04-15.
- `data/calibration/*.json` and `frontend/public/data/calibration/*.json` have drifted.
  The frontend copies of `confidence_parameters_v2.json` and `margin_parameters_v2.json`
  were hand-edited (sign flip on `sample_strength`, per-age multipliers typed in), so the
  live app does not run the fitted parameters.
- The prospective pipeline that produced the only honest sample is paused (GotSport
  reCAPTCHA on event pages), so no new pre-game forecasts are accumulating.
- `MATCH_PREDICTION_IMPLEMENTATION.md` still advertises 74.7% and Brier 0.158.

There is, however, one asset that makes an honest evaluation possible today:
`prediction_feature_history` has held a weekly snapshot of every ranked team's inputs
since 2026-04-08. Any candidate can be scored walk-forward on every scored game since
then by joining the latest snapshot dated before the game.

### 5.6 The scoreline and the probabilities come from different places

The displayed score is the modal cell of the Poisson grid, but the displayed win
probability is not the grid's; it has been through two corrections and a prior blend.
That is why a "3-0, 51% chance of a four-goal margin" forecast can also say "20% chance
the favourite loses". MatchBalance seeding consumes both `expectedMargin` and
`blowout4PlusProbability` from the grid, so the numbers customers see on seeding sheets
and on the compare tab are inconsistent with each other today. A single fitted goal model
would make them one source.

### 5.7 Context the model cannot see

- **Tournament versus league.** Blowout rate in one tournament was double the league
  rate. Bracket games decided on penalties may be stored as wins or as the regulation
  draw; which one it is determines the draw rate in that slice and is unknown.
- **Home advantage.** No neutral-site flag exists, and youth "home" is often just
  listing order. Whether the home-listed team wins more than 50% of equal-rating games is
  a one-query test that has not been run.
- **Game length.** U10 to U12 play shorter halves, so goal means scale with age. The
  cohort goal averages already capture this, but any pooled model must carry age.
- **Cross-age matchups.** `AGE_TO_ANCHOR` already offsets ratings across cohorts, which
  is the FiveThirtyEight SPI approach to cross-league games. Those games need their own
  calibration cell.

---

## 6. What the literature recommends, applied to PitchRank

Full source list in section 10.

### 6.1 Evaluate honestly first

Walk-forward with the rule that every input was available the day before the game.
Report log loss, Brier, RPS, accuracy, and classwise reliability, sliced by cohort, by
cross-age versus same-age, and by tournament versus league where `event_name` allows.
Keep a base-rate model and a rating-only model as permanent baselines on every report.

### 6.2 Rating gap → three probabilities, fitted

Three standard forms; all take one number, the rating gap `d = mu_A − mu_B`, and produce
win / draw / loss. Fit by maximum likelihood on the walk-forward set, one parameter set
per cohort (age × gender) with shrinkage toward the pooled fit for thin cells.

- **Ordered logit.** `P(loss) = F(c1 − βd)`, `P(draw) = F(c2 − βd) − F(c1 − βd)`,
  `P(win) = 1 − F(c2 − βd)`, with `F` the logistic function. Three parameters per cohort.
  Winner of Hvattum and Arntzen's comparison.
- **Elo-Davidson.** `P(draw) = κ / (10^{d/2σ} + 10^{−d/2σ} + κ)`, wins split the rest in
  Elo proportion. Two parameters. Plain Elo is the `κ = 2` special case, which is why an
  Elo expected score is not a win probability.
- **Rao-Kupper.** `P(A) = λ_A / (λ_A + θλ_B)`, tie mass `(θ² − 1)λ_Aλ_B / ((λ_A + θλ_B)(θλ_A + λ_B))`.

Widen the gap's effective scale by rating uncertainty the way Glicko itself does,
`d_eff = d × g(sqrt(RD_A² + RD_B²))`, rather than treating RD as a separate additive
signal. Let the draw parameter depend on expected total goals (or on cohort, which is a
proxy), because draws fall as scoring rises.

### 6.3 Scoreline from attack and defense Poisson means

`log λ_A = α_cohort + β·d/400 + γ_off·off_A + γ_def·def_B` and symmetrically for B, fitted
as a Poisson regression on the walk-forward set. Then either a Dixon-Coles rho on the
0-0 / 1-0 / 0-1 / 1-1 cells or a diagonal-inflation weight ω on every draw cell, fitted
per cohort. The score grid then yields win / draw / loss, expected margin, most likely
scorelines, and blowout probability from one place. Check dispersion *after*
conditioning on ratings before reaching for a negative binomial; the unconditional
over-dispersion in youth data is mostly heterogeneity of means across mismatched games.
Keep the 10-goal cap. Show the top three scorelines with probabilities rather than one
rounded mode.

If the grid's three-way probabilities calibrate as well as the ordered logit, use the grid
alone; if not, use the ordered logit for the three outcomes and the grid for the
scoreline, and check that they agree on the ordering.

### 6.4 Calibration

For three classes with a systematically mis-sized draw column, temperature scaling cannot
help (it rescales all classes together). Use vector scaling or Dirichlet calibration, or
simply refit the ordered-logit cut points, which does the same job with fewer moving
parts. Platt-style parametric fits are preferable below about 1,000 to 2,000 games per
cell; isotonic wins above that. Most PitchRank cohort cells have tens of thousands of
games, so per-cohort fits are affordable, with shrinkage for the thin ones.

### 6.5 Machine learning, last

Both prediction-challenge winners were rating features plus a regularised gradient-boosted
tree, calibrated afterwards. The existing `PointInTimeMatchModel` is that shape and can be
kept as the Phase 3 candidate, once its evaluation is fixed (draw thresholds tuned out of
sample, class weights removed or accounted for in calibration, calibrator fitted on a
separate slice). It earns its place only if it beats the fitted rating model on the
walk-forward scorecard by a margin larger than the event-bootstrap interval.

### 6.6 Presentation

Say "chance", pair the number with a verbal band, and anchor to the base rate ("draws
happen 16% of the time in U13 boys league play; here the chance is 24%"). Drive the
confidence badge from RD and games played, not from the composite gap. Show scoreline
probabilities so a 6-0 forecast against a barely-rated team reads as uncertain.

---

## 7. Recommended plan

Each phase is gated on the walk-forward scorecard from Phase 0. No phase re-runs the
in-sample tuning scripts (`optimize_predictor_weights.py`, `calibrate_probability.py`,
`calibrate_margin_v2.py`, `calibrate_confidence_v2.py`).

### Phase 0: an honest scorecard (small, do first)

1. Build the walk-forward set: every scored, non-excluded game since 2026-04-08 whose
   both teams have a `prediction_feature_history` row with `snapshot_date < game_date`
   and `created_at < game_date`. Join the latest such snapshot per team. Store it as a
   local parquet or JSON; do not commit raw exports.
2. Score four baselines on it with one Python module: cohort base rate; Glicko-only Elo
   win probability with a fixed draw share; ordered logit on `d`; the live TypeScript
   predictor via `frontend/scripts/run-backtest-predictions.ts` (it already takes a
   batch payload). Metrics: log loss, Brier, RPS, accuracy, classwise reliability
   tables, per cohort and per same-age / cross-age, with event-level bootstrap intervals
   as `compare_benchmark.py` already does.
3. Answer the two data questions in 5.7 with one query each: home-listed win rate at
   equal rating, and how penalty-decided bracket games are stored.
4. Retire `scripts/predictor_python.py` from the backtest path, or add a three-way
   probability to it and a test that fails when it diverges from the TypeScript
   predictor on a fixed fixture. The current silent divergence is what makes every
   Python backtest number untrustworthy.

Output: one report that says how much the live model adds over "rating gap alone". If
the answer is "nothing or less than nothing", which the literature and the 73% ceiling
both predict, Phase 1 is justified without further debate.

### Phase 1: replace the probability core (medium)

1. Fit the ordered logit (or Elo-Davidson) per cohort on the Phase 0 set, with RD
   widening and shrinkage for thin cells. Commit only the parameters, as one JSON file
   with the fit date and the training window.
2. In `matchPredictor.ts`, compute win / draw / loss from that fit. Delete
   `calibrateProbability`, `applyOutcomeCalibration`, the sparse-draw boost, the U13/U15
   draw overrides, and `heuristic_outcome_calibration.json`.
3. Keep the composite signals only as inputs to the *explanation* text until Phase 3
   decides whether any of them survive as model features.
4. Bump `MATCH_PREDICTION_VERSION`; MatchBalance caches are keyed on it.

Expected result: log loss well under 0.9 on the same holdout, mismatch games forecast at
85 to 95% instead of 73%, no change to which team is favoured in most games.

### Phase 2: one goal model for score, margin, and blowout risk (medium)

1. Fit the Poisson regression in 6.3 on the same set, plus a per-cohort draw correction.
2. Derive expected score, expected margin, `blowout4PlusProbability`, and the top three
   scorelines from that grid. Remove the `totalGoals` heuristics, the `margin_mult`
   ladder, and `margin_parameters_v2.json`.
3. Reconcile with Phase 1: if the grid's three-way probabilities calibrate as well, drop
   the ordered logit and use the grid as the single source; otherwise keep both and
   assert ordering agreement.
4. Re-validate the MatchBalance backtest gates (average-margin error ≤ 1.0 goal,
   blowout-rate error ≤ 10 points) on a past event, since seeding consumes these outputs.

### Phase 3: features and a learned model, only if headroom remains (larger)

1. Repair `PointInTimeMatchModel` evaluation (5.5) and train it on rating-derived
   features: `d`, RD, offense and defense residuals, cohort, same-age share, cross-age
   flag, tournament flag from `event_name`, home-listed flag if Phase 0 finds an effect.
2. Calibrate with vector scaling on a separate slice.
3. Promote only if it beats Phase 2 on the walk-forward scorecard by more than the
   bootstrap interval, and keep Phase 2 as the fallback when the artifact is missing.
   Fix the artifact expiry (commit parameters, not a 14-day workflow artifact).

### Phase 4: presentation and honesty (small, can run in parallel)

1. Rewrite `docs/MATCH_PREDICTION_IMPLEMENTATION.md`'s validation section to the Phase 0
   numbers, and remove the 74.7% claim.
2. Show three chances with a verbal band and the cohort base rate; show scoreline
   probabilities; derive the confidence badge from RD and games played.
3. Reconcile `data/calibration/` with `frontend/public/data/calibration/` so there is one
   copy the app reads.

### What not to do

- Do not re-tune the current weights or add another signal. Every prior round did this
  (v2.2 through v2.5) and the honest number stayed near 56 to 58%.
- Do not use a temperature or a linear prior blend to fix calibration. The first cannot
  change the draw column's size; the second is the current ceiling.
- Do not evaluate on rankings that were computed after the game. The weekly rebuild
  includes the game's own result.
- Do not chase "draw recall" of the argmax prediction. Chase the draw column's
  reliability.
- Do not restart the prospective refresh workflow expecting fixtures; GotSport's event
  pages serve a CAPTCHA. The walk-forward set in Phase 0 replaces it as the evidence base.

---

## 8. Open questions that need a database session

1. How many scored games since 2026-04-08 have a valid prior snapshot for both teams?
   (Sets the Phase 0 sample size.)
2. Home-listed team win rate in games where `|d| < 50`, by provider.
3. How penalty-decided bracket games are stored (regulation draw, or a winner).
4. Draw rate by cohort and by league versus tournament, current season.
5. Conditional dispersion: variance of goals against the Poisson mean after conditioning
   on `d`, per cohort. Decides whether a negative-binomial tail is needed.
6. Whether `ENABLE_MATCH_PREDICTION_SHADOW_LOGGING` is set in production, and how many
   rows `match_prediction_shadow_log` holds. Those are additional real pre-game forecasts.

---

## 9. Backlog

Registered as IMP-266 in `.turbo/improvements.md`, pointing at this document.

---

## 10. Sources

Project files: `frontend/lib/matchPredictor.ts`, `frontend/lib/matchPredictionService.ts`,
`frontend/public/data/calibration/*.json`, `data/calibration/*.json`,
`src/predictions/point_in_time_match_model.py`, `src/predictions/compare_benchmark.py`,
`scripts/predictor_python.py`, `scripts/backtest_predictor.py`, `docs/COMPARE_BENCHMARK.md`,
`docs/MATCH_PREDICTION_IMPLEMENTATION.md`, `docs/matchbalance-backtest-intake.md`,
`.turbo/plans/scf-off-staging.md`, pull requests #551, #695, #1143, #1190, #1194.

Literature (reached through search excerpts; the network proxy blocked several full
texts, so treat quoted figures as reported rather than verified):

- Maher 1982, Modelling association football scores.
  https://onlinelibrary.wiley.com/doi/abs/10.1111/j.1467-9574.1982.tb00782.x
- Dixon and Coles 1997, low-score dependence and time decay.
  https://opisthokonta.net/?p=913 ; https://opisthokonta.net/?p=1013 ;
  https://metricgate.com/docs/dixon-coles-soccer-model/
- Karlis and Ntzoufras 2003, bivariate and diagonally inflated Poisson.
  http://www2.stat-athens.aueb.gr/~jbn/papers2/08_Karlis_Ntzoufras_2003_RSSD.pdf
- Conditional dispersion comparison. https://opisthokonta.net/?p=1210
- Ley, Van de Wiele, Van Eetvelde 2019, ten strength models compared by RPS.
  https://journals.sagepub.com/doi/abs/10.1177/1471082X18817650
- Hvattum and Arntzen 2010, Elo with margin and ordered logit.
  https://www.sciencedirect.com/science/article/abs/pii/S0169207009001708
- Szczecinski and Djebbi 2020, Elo-Davidson.
  https://www.degruyterbrill.com/document/doi/10.1515/jqas-2019-0102/html
- Rao and Kupper tie model. https://orca.cardiff.ac.uk/id/eprint/137067/1/ties%20AAM.pdf
- Adaptive Glicko-2 with ordered-logit draw model. https://arxiv.org/abs/2607.01722
- FiveThirtyEight SPI methodology.
  https://fivethirtyeight.com/features/how-our-club-soccer-predictions-work
- Constantinou and Fenton, pi-ratings.
  http://www.constantinou.info/downloads/papers/pi-ratings.pdf
- Draw frequency versus total goals. https://pena.lt/y/2015/12/12/frequency-of-draws-in-football/
- Guo et al. 2017, temperature scaling. https://proceedings.mlr.press/v70/guo17a.html
- Kull et al. 2019, Dirichlet calibration and classwise ECE.
  https://proceedings.neurips.cc/paper/2019/hash/8ca01ea920679a0fe3728441494041b9-Abstract.html
- Niculescu-Mizil and Caruana 2005, Platt versus isotonic sample sizes.
  https://www.cs.cornell.edu/~alexn/papers/calibration.icml05.crc.rev3.pdf
- Wheatcroft on RPS versus log loss. https://arxiv.org/pdf/1908.08980
- 2017 Soccer Prediction Challenge winner. https://link.springer.com/article/10.1007/s10994-018-5704-6
- 2017 and 2023 challenge organisers' reports.
  https://link.springer.com/article/10.1007/s10994-018-5747-8 ;
  https://link.springer.com/article/10.1007/s10994-024-06625-9
- Form adds little over Elo (practitioner).
  https://ofelipebandeira.medium.com/can-we-use-chess-to-predict-soccer-b7b22b75a92a
- Benchmarks in mismatch-rich competitions. https://arxiv.org/pdf/2607.17765
- Communicating forecast uncertainty.
  https://wmo.int/media/magazine-article/communicating-forecast-uncertainty-service-providers
