# MatchBalance evidence and cohort-order preview

MatchBalance keeps three separate orders: the published PowerScore baseline, its tournament recommendation, and the operator's manual order. National rankings are unchanged.

## Operator workflow

1. Use **Start a new tournament** to save the active run and return to a blank pasted-roster intake. A failed save keeps the active work in place. Give the new run a descriptive name before importing U12, U13, or another cohort.
2. Import and match the accepted roster as usual.
3. Under **Recommendation method (optional)**, choose **Whole-cohort comparison — preview** or **Opponent-adjusted recent results — preview**, then **Build seeding sheets**. Changing the selector alone never replaces saved recommendations.
4. Review movement explanations, supporting and contrary game examples, limited evidence, and tier risks. A preview requires placement review. Manual orders and holds remain available.
5. Export the ranked cheat sheet. The PDF, printable HTML, and Excel keep the ranked list, PowerScore, state rank, saved W-L-D record, tier separators, compact formats, and material cautions. Detailed movement reasons and game examples remain in the expandable operator view and CSV.

The current method remains the default until an untouched historical confirmation supports a release. Preview output is available for inspection; it is not evidence that prediction accuracy improved.

To extend an existing event, return to Import and expand **Add age groups to this run**. Paste only the new cohorts and confirm their complete lists. Existing roster identities, matching decisions, notes, and cohort reviews stay in place. Replacement lists and unimported drafts cannot be silently discarded by **Start a new tournament**.

## Evidence correction

Compare and new Seeding builds resolve complete merge chains and normalize both sides of each game. Old team names therefore contribute to recent form, head-to-head history, common opponents, and evidence counts. Cycles and failed exclusion reads stop the build. Fetches use stable pagination, bounded ID batches, scored non-excluded games, and an explicit 365-day window ending on the analysis date.

Original participant IDs, provider/source metadata, canonical identities, omitted-game reasons, exact team inputs, calibration inputs, and model parameters are retained with new snapshots. Repeated reads of the same game ID count once. Possible cross-provider or merged-identity duplicates remain recorded for source review and block affected placements; ordinary repeat meetings remain observations. Unknown opponent ratings are visible and do not receive invented strengths. Each cohort has its own input digest. Freshness checks describe changed rating fields, game additions/removals/corrections, analysis dates, and model inputs without replacing the saved analysis.

Pack schema 9, analysis schema 12, and content version 11 support an offline upgrade that preserves older embedded predictions, ordering methods, and format policies. Applying the joint model requires an explicit rebuild; applying the adaptive catalog requires a rebuild or format update. Matching overrides, manual orders, holds, notes, and tier names survive compatible roster identities. Model source, parameters, formats, and preferences participate in cache and export identities.

## Preview methods

**Whole-cohort comparison** averages each team's projected points against every assessed opponent, using win probability plus half the draw probability. Every opponent counts once. Exact ties retain the frozen baseline. Evidence can move teams beyond two seeds without requiring a one-goal predicted reversal. Limited history produces a caution rather than an automatic immobility rule.

A zero-centered regularized Bradley–Terry diagnostic fits the same frozen pair probabilities. With a complete equally weighted field, its ordering agrees with expected points; agreement checks the formulation rather than providing independent evidence of accuracy. It never replaces the saved recommendation or changes national ratings.

**Opponent-adjusted recent results** fits team and opponent strength together from the saved game graph. Each physical game supplies one weighted comparison, and shared opponents connect the estimates. A fixed neutral opponent converts the immutable rating inputs into supporting goal-scale priors. The fit minimizes weighted squared capped-margin errors plus a prior penalty of 0.5 per team. It never treats the prior as an independent observed game.

Margins are capped at four goals. Calendar weights have a 90-day half-life, with half weight before the August season boundary. Repeat opponents contribute at most one total unit of support. Sparse or disconnected histories remain explicit. The graph contains the entrant histories and the saved ratings of their opponents; it is not an import of every opponent's full history. These versioned parameters are development hypotheses, not validated estimates of optimal weights. A checked sparse solver stops the build on non-convergence.

The displayed game examples include supporting and contrary results when available, with score, date, opponent club, and opponent name. The operator can inspect the saved source links. Examples explain the evidence being used; a single result does not prove an exact seed. Result-removal and shared team/event resampling refit the entire graph, so changes propagate through shared opponents.

A coherent Poisson score distribution supplies expected points and mismatch risks. It is an experimental distribution, without an outcome-confidence calibration claim. Evidence quantity is reported separately. Current competitive thresholds remain unchanged, but passing those limits under a candidate model does not establish better real-world balance.

The expanded-v4 format profile prefers divisions of at least four. If no such arrangement passes, it builds an adaptive candidate: find the lowest possible worst normalized mismatch risk, then within 0.15 of that risk minimize undersized divisions, worst risk, violating pairings, pair-weighted average cost, division count, and deterministic boundaries. Use that candidate if no passing recommendation exists. The 0.15 band is an explicit practical preference, not an increase in the competitive limits: an over-limit selection is always a review-required compromise. An existing passing recommendation is replaced only when the adaptive candidate reduces the number of undersized divisions; a retained passing recommendation need not lie inside the adaptive risk band. Three-team divisions remain available when larger divisions require more risk than that band allows or the roster cannot support them. A six-team division may still use two pools of three.

Normalized risk is the larger of expected absolute goal difference divided by its limit and four-goal margin probability divided by its limit. A 0.15 change corresponds to 0.30 goals or 4.5 percentage points in the governing metric under the default limits. This product preference requires operator review and is not a claim that those changes are equally costly in real tournaments. Exhaustive and exact interval searches apply the same policy, including compromises.

Practical tiers still use consecutive effective seeds, the existing format catalog, and complete within-division matchup assessment. Manual edits and holds recalculate membership and guidance. Field sensitivity, removal of each team's largest weighted departure from its rating prior, and twelve deterministic team/event cluster resamples expose unstable seeds or tier memberships. Both participants in an observed game receive the same cluster weight; unknown event labels use individual game clusters. These stress checks are not confidence intervals and do not cover every possible history perturbation. Derived sensitivity is cached separately from immutable recommendation evidence, so changing a hold or format preference remains a valid saved edit.

## Validation and release boundary

`scripts/validate_matchbalance_evidence.py` scores observed matches from frozen pre-event inputs. Records must include game/event/team identities, cutoff and game dates, exact frozen JSON and its SHA-256, input-availability dates, and identical prediction coverage for all compared models. Use `frozen_validation_inputs(pack, cohort, candidate_packs={"baseline": baseline_pack, "candidate": candidate_pack})` to export the schema-2 contract. Each named candidate preserves its exact evidence, complete dated team features and scored games, model parameters and SHA-256, all five calibration payloads, suggested order, and pair forecasts. Explicitly missing optional ratings and empty histories are valid; placeholder input records are not.

Reported seeds and forecasts must match those frozen candidates. All observed games within an event cohort must use the same candidate freeze. Probability order is A win, draw, B win. The fixture in `tests/unit/test_seeding_validation.py` demonstrates the complete input contract.

The scorecard reports seed-order agreement separately from predicted-margin direction, with half credit for ties, alongside three-way Brier score, log loss, goal-margin error, severe-mismatch calibration, and recall at 30% risk. Approximate team-and-event clustered bootstrap intervals require at least five events and twenty teams; family-adjusted intervals use Bonferroni across the compared candidates. Optional record labels `limited_history`, `playing_up`, `age_group`, and `gender` provide subgroup breakdowns; missing labels are counted as unclassified. Repeated outcomes are rejected. Confirmation rejects previously examined events. The scorecard does not automatically approve a release.

Before changing the default, compare PowerScore order, the saved current method, corrected-history method, whole-cohort ordering, and results candidate on the same frozen inputs. Lock screening and untouched confirmation events before examining outcomes. Require improved seed-order agreement with its family-adjusted clustered interval entirely above zero on confirmation, no increased Brier score, margin error or severe-mismatch Brier score, and inspect mismatch recall and age/gender, playing-up, and limited-history subgroups. A failed isolation check voids the comparison; inadequate clusters, missing subgroup labels, or an interval crossing zero are inconclusive. Any additional candidate requires revisiting the locked comparison plan before opening confirmation outcomes.

The audited U14 field is development evidence, not untouched confirmation. Its manual order is a comparison reference, not training labels. Existing historical CSV predictions without their exact frozen model inputs cannot qualify the new candidate. Replaying a proposed split measures projected matchups only; demonstrated benefits require observed tournament outcomes.

## Frozen U13 development replay (2026-10-18)

The saved October 17 U13 Girls run contains 20 accepted entrants and 19 seedable teams. The joint-results preview places Inspire first, LFC second, Herndon third, Aspire eighth, Arlington ninth, and FCCH eleventh. This differs from the director's manual order and is not an accuracy score. Aspire's saved games include losses to Baltimore Armour Aspire and VA Rush Aspire; club names must be shown to avoid making those look like self-games. Opponent strength and those losses remain evidence to inspect, rather than a reason to force the director's preferred order.

The practical split is 4 + 11 + 4 and retains one over-limit pairing: BRYC versus Potomac, with expected absolute goal difference 2.14 and four-goal margin probability about 19%. A passing 4 + 12 + 3 alternative remains available. The model has not made this cohort uniformly safe. CSA's saved U14 identity is flagged against its U13 entry. PPA NCSL remains unplaced with three saved games, latest March 22, rather than being depicted as the weakest team.

Historical promotion remains blocked by insufficient independently frozen pre-event evidence. The available historical scorecard describes an older predictor and cannot establish accuracy for this model. Collect dated input snapshots before untouched events and apply the validation contract above; do not substitute today's ratings for pre-event ratings.
