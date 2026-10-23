# Joint-field ranking investigation and native integration

The native profile `joint-field-quality-support-v1` now connects the measured
joint snapshot to `compute_all_cohorts` and the ranking command. The source
integration has passed its full frozen-input comparison. The ranking command now
defaults to this profile; `reproducible-v2` is the previous complete rollback. The numerical equations and quality-support policy
are the previously evaluated candidate, not new settings selected from U19 ranks.

`joint_field_scoring.py` prepares the existing clipped/newest-game selections
once, fits one snapshot, and reuses it for both scoring passes. Offense/defense,
schedule strength, connectivity and explanations use the same global opponent
state with the existing age-anchor offset. SOS does not multiply the fitted
opponent's league adjustment a second time. The conditional solver is bypassed
rather than run and overwritten. The old profile remains an explicit rollback.

The motivating calculation defect is repeated application of an uncentered
league multiplier to fitted opponent ratings. In a neutral all-draw field,
that operation can change the field's rating level with its history length.
The experiment instead fits one Gaussian prior per parameter and one fractional
logistic likelihood per selected physical game. League field effects are fitted
from cross-field results; same-field games cancel that field's shared intercept.
Existing league categories supply the initial prior centers. There are no team
exceptions or targets for particular ranks.

Numerical settings are fixed for this candidate: 50 Newton steps maximum,
maximum absolute gradient below `1e-8`, preconditioned CG with relative tolerance
`1e-10`, absolute tolerance `1e-12`, 2,000 CG iterations maximum, and an Armijo
line search with 30 halvings maximum. A rounding-scale descent may be accepted
only when the objective change is below its resolution and the maximum gradient
falls by more than half. Non-finite values and failed solves raise visibly.

The Hessian is loss curvature. Team uncertainty must include the shared field
variance and team-field covariance; a reciprocal Hessian diagonal omits them.
Neither this curvature nor a count of opponents is a calibrated probability.
The shared field prior also changes marginal team priors; it must not be described
as preserving the original independent Glicko prior distribution.

The experiment preserves each team's selected record list and source eligibility.
Its joint likelihood uses the union of games selected by either endpoint, so
incident likelihood evidence can exceed a team's own 30-record list. That change
in inference semantics must remain explicit in the comparison and release review.

Focused numerical verification:

```powershell
python -m pytest tests/unit/test_joint_field_solver.py tests/unit/test_joint_field_uncertainty.py -q
```

These fixtures check the numerical equations, uncertainty behavior and failure
guards. They do not establish final ranking accuracy, predictive benefit, or
empirical calibration. Adoption still requires the locked all-board comparison,
case review, repeatability and provenance checks.

## Measured October 12 results

The first complete joint-field scoring replay preserves all 61,058 eligible
teams and every own selected record. It changes Venom from California 3 to 41,
Salmon Creek from Washington 10 to 10, Surf from Washington 3 to 3, and Wenatchee
from Washington 13 to 14. These are measured movements, not independently
validated placements. The shared-field model has a different prior distribution
and uses the union of endpoint selections as described above.

A separate, pre-locked `support-retained-provisional-v1` publication experiment
keeps the existing provisional uncertainty deduction out of the shared discount
credit. It preserves all model, evidence, ML, raw-shrink and publication-penalty
inputs. The combined experiment places Venom California 73, Salmon Creek
Washington 15, Surf Washington 7 and Wenatchee Washington 11. The initial Salmon
Creek concern was its top-ten placement; no requirement specifies an exact
replacement rank or requires it to fall outside the top 25.

The joint-only historical agreement change is +1.10264 percentage points. The
combined experiment changes agreement by +0.94256 points overall, with a paired
team-aware 95% interval from +0.85081 to +1.03431. However, U10 girls remains
inconclusive under the pre-locked board margin: -0.36307 points, interval
[-1.08411, +0.35797], against a -1.0-point margin. The combined candidate remains
on hold. These reused October outcomes do not establish predictive benefit.

The retained-provisional publication experiment has exact scoring repetitions.
The joint model's point estimates, Hessian and priors also repeat exactly. The
full scoring attribution and joint scoring repeat have completed. Both complete
joint scoring runs have identical stage hashes, selected records, scoring columns
and ranks. The completed comparison covers all 18 boards and 983 required cases.
Baseline B's score table and all 289 stages exactly match baseline A, but its
process exited during compact export when the disk filled. The explainability
export was reconstructed byte-for-byte from its own saved Pass2 captures.
Its export-recovery record preserves that failure and explicitly leaves the
unserialized call counters unknown; it is not a fabricated normal completion.

## Resume and ordering review

The selected-union audit contains 32,694 same-board eligible pairs with at least
two wins by one team and no selected loss to the other. Publication-step
reversals number 229 for production, 310 for joint/current publication and 179
for joint/retained-provisional publication. Total reversed orders number 3,183,
2,988 and 3,069 respectively. Retention creates 290 and removes 209 reversals
relative to joint/current publication. These counts are review triggers, not
an invariant requiring a head-to-head winner to rank higher. Older unselected
games are outside this particular diagnostic.

The joint candidate has 164 new national top-25 entrants; the combined candidate
has 201. All have at least one selected win against a baseline-eligible opponent.
Eligibility alone does not establish opponent strength or validate an entrant.
U19 boys requires particular scrutiny: original MLS NEXT HD representation in
the national top 25 falls from 20 teams to 3 in the joint candidate. Philadelphia
falls from 1 to 9; Seattle falls from 9 to 54 despite its score increasing.
Direct selected U19 HD-versus-ECNL coverage is only three physical games, so
that slice alone cannot validate the newly inferred national league order.

Exact core reconstruction also confirms that the old centered schedule and
evidence shrinkage can raise below-1500 ratings. This is not a new unexplored
candidate: the earlier SOS consistency experiment already evaluated the weak-SOS
direction correction and was rejected. Shrinkage toward a prior is not itself
a defect. In the joint replay Salmon's own schedule and evidence adjustments
both lower its rating (1567.36269 to 1561.81309). No new direction-only policy
is proposed or implemented by this check.

The completed core-only attribution puts Venom at California 41 and Salmon at
Washington 10, before using consistent global opponent lookups for derived
scoring. Consistent lookups leave those state positions unchanged. Thus the
joint rating model accounts for Venom's 3-to-41 movement. The separate
publication experiment accounts for Salmon's 10-to-15 movement. Intermediate
profiles remain attribution only; none is substituted as a preferred candidate.

The U10 girls publication-only difference changes agreement on 81 historical
games: 38 gains and 43 losses. In 42 of the 43 losses, the actual winning team
has higher joint uncertainty; 35 also have fewer selected games. This is a
measured uncertainty tradeoff, not a newly discovered convergence failure.
It does not justify relaxing the pre-locked acceptance margin.

The numerical kernel, problem builder and retained-provisional profile pass
46 focused tests together. The builder tests cover physical-game counting,
rematch weights, field/reference priors, actual cross-gender and cross-age
rows, timezone equivalence, cache-input fingerprints and invalid inputs.
These synthetic checks do not replace full frozen-input builder parity or
the repository-wide Python suite.

The source problem builder preserves the full evaluated priors, precision and
node inputs exactly. Its largest edge-input difference from the prototype is
`2.22e-16` (the prototype serialized cross-gender input through CSV); its largest
rating difference is `4.55e-13` points. Two native point solves repeat exactly.
Full source curvature parity has completed. The maximum deviation difference
from the measured prototype is `1.14e-13` rating points. This numerical port is
not a new historical accuracy result. Small snapshot/curvature fixtures pass.

`requirements-offline-rankings.txt` declares the optional solver requirements;
the production requirements files are unchanged. The separate
`requirements-offline-rankings.lock` records the additional measured optional
accelerator versions. They are needed for practical full-input exact inversion;
the production model selection remains unchanged. Without Numba, large inversions
fail explicitly and small correctness fixtures use the identical Python recursion.

## Resumed investigation: opponent results and evaluation coverage

The October 12 selected-union audit finds 41 games by Salmon Creek's opponents
against teams outside its immediate opponent set: 17 wins, eight draws and 16
losses. Fourteen were against baseline ranking-eligible opponents, with two
wins. Surf's opponent set had 117 outside games, including 75 against eligible
opponents and 40 wins in those games. Eligibility is a coverage measure, not a
claim of strong opposition. These figures do not justify a generic isolation
penalty or an exact replacement rank.

The historical agreement metric includes 329,846 games but directly evaluates
only 59,811 of the 61,058 eligible teams. Salmon Creek has zero evaluated games;
Venom has four. Zero omitted eligible games must not be described as validation
of every team's placement. Of the baseline's U.S. state top-ten entries, 66
have no selected ranking-eligible opponents and 320 have no decided same-board
game in the historical metric. These are different coverage definitions.
The audit preserves all original acceptance rules and changes no scores.

The U10 girls publication-only regressions also differ from Salmon's resume:
all 43 newly missed games have winners with at least one selected win against
an eligible opponent; 39 have at least three. These reused outcomes identify
a tradeoff to investigate, not a threshold to tune to or independent accuracy
validation. No new policy was selected from these counts alone.

## Quality support v1: separate development candidate

The subsequent `quality-support-lock.md` fixed a new candidate before its real
scoring outputs: retain own provisional uncertainty, but remove the separate
four-opponent prior-mass dilution from publication support. Existing independent
opponent masses still weight the observed quality/outcome average. Recency,
rematch discounts, outcome scoring, older-game inclusion and connectivity remain
unchanged. This is a policy experiment, not a claim that every overlapping
uncertainty adjustment is mathematically wrong.

`PublicationExperiment("support-quality-only-v1")` implements this optional offline
policy. `publication_support.quality_only_support` is its single computation path.
The publication operator rejects a stale support checkpoint for this profile.
The combined adoption candidate is `joint-field-quality-support-v1`; production
defaults and both previously measured worktrees remain unchanged.

Both new control runs reproduce the existing publication output exactly. Both
candidate repetitions have identical scoring and diagnostic outputs. The native
source port also reproduces both paths exactly. Full source verification is
recorded separately; do not infer it merely from the prototype tests.

The source suite completed with 11,525 passed, 16 skipped and one existing
expected failure. After import ordering and string-line wrapping cleanup, the
non-import AST is unchanged, all 196 focused publication/Windows tests pass,
required Python lint passes, and the final native publication replay still
matches every measured scoring and diagnostic column exactly. No scoring
equations or settings changed during that cleanup.

On the October 12 freeze, state ranks are Venom California 3 to 77, Salmon Creek
Washington 10 to 14, Surf Washington 3 to 5 and Wenatchee Washington 13 to 13.
These are measured placements, not independent truth or fitted rank targets.

Overall historical agreement improves by 1.04867 percentage points, paired
team-aware 95% interval [0.95943, 1.13791]. All 18 board margins and both
predefined subgroup margins pass. U10 girls is -0.07780 points with interval
[-0.76531, 0.60971]; U10 boys is -0.33293 with interval [-0.74177, 0.07590].
Passing non-inferiority must not be described as improvement on every board.
No acceptance margin changed. The earlier retained-provisional candidate's
inconclusive verdict remains intact.

The comparison prepares 1,044 case packets containing 20,626 selected records;
193 new national top-25 entrants all have selected wins against eligible opponents.
Four have no non-loss against a baseline top-500 same-board opponent. Baseline
ranks are themselves affected by the defect under investigation, so that flag
requires review rather than automatic rejection. U19 boys remains a material
uncertainty: MLS NEXT HD representation changes from 20 to two national top-25
teams, and direct selected U19 HD-versus-ECNL coverage is only three games.

The revised candidate clears development screening and merits untouched
confirmation. It does not yet establish predictive non-inferiority, validate
Salmon's placement (zero evaluated games), or authorize production publication.
No further coefficient search is justified by this passing historical screen.

### Reproduce the policy paths without fetching or writing rankings

From the experiment directory, use a new output directory for each invocation:

```powershell
python -B replay_quality_support_native.py --profile support-continuous-v2 --out NEW_BASELINE_DIRECTORY
python -B replay_quality_support_native.py --profile joint-field-quality-support-v1 --out NEW_CANDIDATE_DIRECTORY
```

These commands validate sealed upstream checkpoints, refuse network calls,
retain their as-of timestamp, and invoke the source implementation. They perform
fresh publication calculations, not fresh model/ML fitting. Input hashes, loaded
modules, canonical score columns and completion receipts are recorded. State-rank
aliases in the checkpoint table are not regenerated; use the comparison's ranks.

Before untouched evaluation, freeze final candidate source and metric, lock
explicit evaluation dates, then capture training inputs after that lock. Evaluate
the following 30 complete UTC days. The October screen is development evidence
and cannot substitute for that confirmation.


## Native runner checks

The controlled neutral-field regression reproduces the previous multiplier
feedback at U14, U15, U16, U17 and U19. With only draws and otherwise identical
inputs, ECNL ratings fell from approximately 1412 with four independent opponents
to 946 with thirty; HD stayed at 1500. The joint model leaves the ECNL prior
center at 1470 for both sample sizes, with lower uncertainty for more independent
results. This establishes a calculation defect across ages. It does not establish
that every newly inferred league ordering or individual placement is correct.

The native integration tests exercise the actual all-cohort orchestrator, ensure
one model fit serves both passes, reject changed inputs/configuration, and prove
a failed fit stops before scoring or persistence. They also cover consistent
cross-age explanations and direct SOS without repeated tier multiplication.

```powershell
python -m pip install -r requirements-ranking-model.lock
python -m pytest tests/unit/test_joint_field_scoring.py tests/unit/test_production_ranking_profile.py -q
python scripts/calculate_rankings.py --ml --force-rebuild --dry-run --ranking-profile joint-field-quality-support-v1
```

Joint runs require all age/gender cohorts and all providers. A filtered command
is rejected before connecting to the database, including during a dry run. The
complete selection universe is necessary because league effects are shared across
ages. The joint path bypasses legacy caches; it cannot reuse a conditional-fit
cache as a joint snapshot. The runtime dependency lock includes Numba for the
large exact-curvature calculation and leaves the general application lock intact.

Rollback uses the previous complete profile, not the older legacy solver:

```powershell
python scripts/calculate_rankings.py --ml --force-rebuild --ranking-profile reproducible-v2
```

The October agreement figures remain historical development evidence. The
attempted later confirmation capture failed before sealing predictions and is
not a valid prospective evaluation. Numerical correctness, reproducibility and
historical comparisons must not be presented as empirically calibrated confidence
or proof of future predictive improvement.


## Native integration release verification

The fresh native run completed all 36 engine passes and the full publication
calculation on the October 12 freeze. Every own selected record and eligibility
status matches the evaluated candidate, with 61,058 Active teams and zero final
rank differences. Maximum final-score difference is 1.06e-15; maximum rating
difference is 4.55e-13 points. The run took approximately 56 minutes on the local
Windows machine. Network and database writes were blocked throughout.

The full Python run passed 11,702 tests; two Compare tests initially failed because
the isolated checkout lacked its frontend runtime. After attaching the installed
runtime with an identical dependency lock, all 159 affected/required Windows checks
passed. All 24 native integration tests passed. Frontend lint, formatting,
typecheck, all 1,314 tests and generated-content drift checks passed. The remaining
activation edits change CLI selection/labels and remove an unused cache directory;
they do not change any scoring equation or numerical setting.
