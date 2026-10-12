# Ceiling board boundaries: confirmed bug, local correction

The final ceiling calculation uses boys and girls together to translate a ceiling category into a score limit. The published rankings and opponent-evidence ranks are separate by age and gender. Consequently, changing boys' scores can change a girl's ceiling without changing her games or evidence.

The local correction keeps the reference scores on each gender's board. It changes no evidence threshold, play-up exception, game selection, eligibility rule, rating calculation or ML adjustment. This is separate from the gender correction in the earlier rating calculation and the already-merged separation of ceiling-band ordering.

**Recommendation: retain the correction for review, but do not publish it on this evidence.** The mechanical effect is substantial. The remaining question of which schedules justify high placements is unresolved.

## Direct evidence

In a four-team example, boys have pre-ceiling scores 0.9 and 0.8, girls 0.7 and 0.6, and all have ceiling category 2. Existing code assigns all four a ceiling of 0.799999. The corrected girls' ceiling is 0.599999; changing or removing boys leaves it unchanged.

The October 8 publication snapshot contains 62 age/category combinations represented by both genders. All 62 use identical ceiling scores for boys and girls. The production caller processes both genders together, and `_compute_publication_cap_scores` used the pooled score distribution. The correction separates references inside this helper while retaining its single-age contract and compatibility with callers that omit gender for a single board.

## Bounded historical sensitivity

The newer temporary full-stage outputs are no longer present at their recorded paths. October 8 published outputs remain preserved, but lack the complete pre-ceiling scores and private evidence needed for an exact reconstruction. No missing values were fabricated and no engine batch was restarted.

The surviving September 30 pre-ceiling captures passed all nine SHA-256 checks against their original completion receipt. Both comparisons use these exact scores and ceiling categories, with current ceiling-band ordering; only gender pooling in the cutoff calculation differs. This is a mechanical sensitivity check, **not a reproduction of October 8 and not a preview of the current engine**. The older capture used balanced game selection, a 12-game minimum, the pull and 180-day inactivity. Current main uses newest 30, a 10-game minimum, no pull and 155-day inactivity.

Across 61,372 active teams, 30,558 scores and 37,006 ranks change. Median absolute movement is 31 places; 24,591 teams move over 100. Game selection, eligibility, evidence categories and pre-ceiling scores are held fixed. All 18 boards retain finite bounded scores and respect their calculated ceilings. Repeating the cap replay and processing each gender separately reproduces the corrected values exactly; this is not an engine A/A run.

| Board | Active teams | Ranks changed | Median absolute move | Moved over 100 |
|---|---:|---:|---:|---:|
| U10 girls | 1,008 | 951 | 162.5 | 614 |
| U10 boys | 1,825 | 1,743 | 257 | 1,179 |
| U11 girls | 3,029 | 2,171 | 81 | 1,456 |
| U11 boys | 5,515 | 2,364 | 0 | 1,315 |
| U12 girls | 3,233 | 2,312 | 58 | 1,299 |
| U12 boys | 5,853 | 2,305 | 0 | 473 |
| U13 girls | 3,408 | 2,220 | 86 | 1,661 |
| U13 boys | 5,893 | 2,351 | 0 | 1,617 |
| U14 girls | 3,116 | 2,096 | 123 | 1,614 |
| U14 boys | 5,181 | 2,278 | 0 | 1,409 |
| U15 girls | 2,866 | 2,044 | 210 | 1,665 |
| U15 boys | 4,572 | 2,291 | 1 | 1,508 |
| U16 girls | 2,140 | 2,000 | 386.5 | 1,554 |
| U16 boys | 3,500 | 2,126 | 34 | 1,542 |
| U17 girls | 1,682 | 1,635 | 388.5 | 1,200 |
| U17 boys | 2,719 | 2,017 | 160 | 1,485 |
| U19 girls | 2,346 | 1,993 | 324.5 | 1,540 |
| U19 boys | 3,486 | 2,109 | 21 | 1,460 |

The broad screen (zero same-age raw top-100 opponents and at most two top-500 opponents) declines from 35 to 28 top-100 teams. That decline is not evidence of better placements. Individual current schedules were not reviewed again against this obsolete scoring configuration, and this is not a completed adoption review of those 28 teams or the new top-100 entrants.

Historical examples underscore the limitations: Surf remains 46 and Europa 12; the Texas U11 girls control falls from 700 to 1,035; Wyoming U14 girls falls from 296 to 563. Those historical ceiling categories differ from the October 8 publication. None of these numbers is a forecast for the current site, and the losses cannot be dismissed because the flag count falls.

## Older-opponent evidence remains an open issue

The separate October 8 audit reconstructed the named teams' available games and matched their stored evidence metrics. Surf's current rule fails the requirement for two non-loss results against distinct raw top-500 older opponents: it has one by that definition, although four selected older non-loss opponents finish in their published top 500. Published opponent positions depend on ceilings themselves, so using those positions instead is not an independently validated fix.

The evidence helper also defines play-up as exactly one year older. North Carolina U17 girls' 19 results against U19 therefore do not count toward the play-up exception; the active ranking boards have no U18. A separate evidence-only sensitivity reproduced the original metrics for all 14 named schedules, then included all older opponents while retaining the existing raw-strength and result requirements. North Carolina gains eight distinct raw top-500 non-loss opponents and eleven top-1000 non-loss opponents, with average older-opponent power 0.664; it meets the existing play-up support conditions. It is the only one of the 14 to change that support decision. Surf remains below the two-top-500 non-loss requirement. Wyoming's average older-opponent power rises to 0.573, still below 0.58.

This identifies an exclusion to address separately; it does not establish new published positions. Broadening these shared metrics would also alter earlier ML authority, penalties and bonuses, so it is not a ceiling-only change. No play-up or threshold change is bundled here. The sensitivity is saved at `C:\PitchRank\.turbo\publication-reviews\2026-10-08\older-credit-sensitivity.json`, including input and script hashes and a newline-normalized source-text hash.

## Validation and next step

The two new cutoff unit tests fail on the unchanged function and pass with the correction. The ceiling suite, including a new test through `compute_all_cohorts`, passes 91 tests. Substituting the original cutoff helper in a separate test process also makes that new composition test fail, without modifying the reviewed working tree.

The full Python suite returned 9,362 passed, 15 skipped and two failures caused by the isolated checkout's missing frontend predictor runtime. After installing its locked dependencies, all 129 tests in the affected runtime and required Windows subsets passed, including both failures and the previously skipped runtime test. These counts overlap and must not be added. No ranking source changed during that repair. Python lint and diff checks pass. The unchanged frontend/CI inputs reuse successful base-commit CI run 38301719723. All six internal code review dimensions and the documentation/evidence reviews returned no actionable findings. External peer review remains waived. There is no changed interactive surface; the composition test exercises the ranking entry point offline.

The user authorized one current-input, read-only capture and one local preview on October 12. The corrected code supplies the full run; replaying the original cutoff helper against its exact pre-ceiling captures supplies the comparison without a second engine run. Preserve all upstream scores, selected games, eligibility and ceiling categories between the two outputs. Inspect all resulting high placements and the supported controls before any merge or publication. The broader ceiling policy is not solved by this bug fix. The preview will wait for at least 6.5 GiB of available memory, with its evidence retained under `C:\PitchRank\.turbo\ceiling-preview-20261012`.

Local evidence: `C:\PitchRank\.turbo\ceiling-gender-review-20261012\evidence.json`, `replay.parquet`, `boards.csv`, `cases.csv`, and `placement-review.csv`. Replay script: `C:\PitchRank\.turbo\publication-reviews\2026-10-08\replay_gender_cutoffs.py`. The JSON records input, source, script, runtime and output hashes. Base source is main commit `62a74f704fd76933795aebb4bb5be1c2c2f55063`.
