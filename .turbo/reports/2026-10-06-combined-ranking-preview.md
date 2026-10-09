# Combined rankings preview: completed placement review

Reviewed October 6, 2026 (America/Phoenix). Saved inputs end August 31, 2026. No live rankings changed.

## Conclusion

The approved newest-30/365 selection and 10-game minimum are implemented correctly in the combined offline preview. The original gender and ceiling safeguards remain intact. The exact selected games, eligibility counts and all 18 boards reproduce the planned policy. The investigated Texas and Washington teams remain outside the top 100.

This does **not** establish that every high placement is justified. There are **23 flagged top-100 teams, including nine top-25 teams**, all admitted by the preserved play-up exception. None of those 23 is newly eligible under the 10-game rule. Their support varies: some have results against older teams that finish high; others rely on opponents that look strong before the ceilings but finish much lower. The owner must see these concrete exceptions before any publication approval. No merge or publication recommendation is automatic, and no new ranking rule has been designed or tuned here.

This is a completed assistant source-and-artifact review, not an independent external review or human approval. The original generated report remains unchanged with its review flag false; the separate review receipt records the completed inspection.

## What was compared

- **Incumbent:** archived engine with the old pull, selection and minimum, from the existing August run.
- **Foundation:** PR #1255 pull/gender/ceiling-safeguard package with the old selection and 12-game minimum.
- **Combined:** the foundation plus PR #1257 newest 30 valid games within 365 days and minimum 10. Frozen local integration commit `e5c575a7b4a4219b063078c2e6d47ba47cc0e69b`.

Only one new full engine run was made. The completed incumbent and foundation were reused. The derived input file is an exact date-filtered subset of the original 393-day snapshot; both manifests and all hashes are preserved. The fetch implementation is unchanged. Upstream score equality is **not** required or claimed across these intentional selection/eligibility changes. Historical safeguard-only equality and repeatability checks remain separate evidence.

## Eligibility and movement

- **65,388 eligible teams**, compared with 60,640 in both archived reference runs: **5,057 joining, 309 leaving**.
- **786 of the 1,095** teams that would fall below the former 12-game minimum remain eligible at 10. The earlier eligibility projection was reproduced exactly by the full run.
- **72 newly eligible teams enter the top 100; seven enter the top 25.** Every one is included in the review.
- 2,730 teams disappear from the candidate output because they have zero games in the new window; all were previously inactive.
- Against the foundation, 60,116 of 60,331 common eligible teams change rank; 12,922 move more than 300 places.
- Against the incumbent, **35,993** common eligible teams move more than 300 places; median absolute movement is **406 places**. This is expected movement on saved August data, not a prediction of today's live counts.

Adding teams changes positions even when relative ordering is stable. Selection, the shorter window and eligibility were changed together, so these movements are not attributed to the minimum alone.

## All 18 boards: combined versus foundation

| Board | Common eligible | Changed rank | Largest move | Top-25 entrants | Top-100 entrants |
|---|---:|---:|---:|---:|---:|
| U10 girls | 827 | 820 | 625 | 9 | 24 |
| U10 boys | 1,509 | 1,500 | 1,386 | 12 | 21 |
| U11 girls | 2,918 | 2,908 | 1,304 | 10 | 25 |
| U11 boys | 5,351 | 5,343 | 1,915 | 11 | 27 |
| U12 girls | 3,170 | 3,159 | 1,050 | 12 | 28 |
| U12 boys | 5,802 | 5,788 | 2,180 | 7 | 31 |
| U13 girls | 3,365 | 3,356 | 1,279 | 6 | 19 |
| U13 boys | 5,844 | 5,837 | 2,280 | 14 | 38 |
| U14 girls | 3,093 | 3,075 | 823 | 5 | 13 |
| U14 boys | 5,172 | 5,158 | 1,767 | 9 | 20 |
| U15 girls | 2,882 | 2,861 | 790 | 3 | 15 |
| U15 boys | 4,615 | 4,605 | 1,679 | 8 | 24 |
| U16 girls | 2,151 | 2,141 | 591 | 3 | 11 |
| U16 boys | 3,532 | 3,519 | 1,452 | 6 | 21 |
| U17 girls | 1,636 | 1,626 | 833 | 2 | 13 |
| U17 boys | 2,679 | 2,666 | 1,365 | 9 | 15 |
| U19 girls | 2,308 | 2,292 | 976 | 3 | 14 |
| U19 boys | 3,477 | 3,462 | 1,484 | 6 | 16 |

The companion evidence also includes all 18 board comparisons against the incumbent. In the fixed incumbent-isolated group, 51,916 teams remain eligible in both runs and 31,468 move more than 300 positions. That old isolation indicator is a diagnostic grouping; it is not proof that every team in it is weak.

## U10 requires separate attention

- **Girls:** 1,046 eligible, up from 833; 219 join and six leave. Sixteen newly eligible teams enter the top 100. Three isolation/weak-evidence flags remain in the top 100, including ranks **1 and 19**. Median absolute movement among common-team movers versus the foundation is 61 positions.
- **Boys:** 1,900 eligible, up from 1,523; 391 join and 14 leave. Twelve newly eligible teams enter the top 100, including three top-25 entrants. Four isolation/weak-evidence flags remain in the top 100, including ranks **9 and 10**. Median absolute movement among common-team movers is 157 positions.

Earlier September U10 uncertainty is unchanged. This preview did not test later-game outcomes and does not prove that the earlier U10 concern has been fixed.

## Investigated cases

| Case | Incumbent | Original pull/gender | Foundation safeguards | Combined |
|---|---:|---:|---:|---:|
| Texas U13 boys | 1225 | 98 | 537 | 498 |
| Washington U13 girls | 210 | 64 | 313 | 276 |
| California U12 girls control | 361 | 9 | 51 | 40 |

The Texas and Washington cases still receive the stricter 1,800 score-threshold bucket. It is applied correctly and inactivity does not bypass it. The California control has stronger same-age evidence and retains the intended in-state treatment.

## Why the 23 flagged teams can still rank highly

The fixed flag is: isolated diagnostic, zero same-age raw top-100 opponents, at most two raw top-500 opponents, and at most one raw top-500 non-loss opponent. It is a review screen, not a verdict about team quality. The count stays 23 versus the foundation; the top-25 count rises from six to nine.

All 23 satisfy the current play-up rule: at least 40% of evidence-window games against the next older age, non-losses against at least two raw top-500 and four raw top-1,000 older opponents, and average older-opponent power at least 0.58. The actual ceiling function returns the existing 250 bucket for all 23, before stricter isolation restrictions are considered. Every credited older opponent and qualifying game is recorded in the companion evidence.

**The 250 label is a score ceiling based on pre-ceiling scores; it is not a guarantee of a final position below #250.** Other teams are capped too, so a team in this bucket can finish in the top 25 or even first. Each inspected team respects its numeric score ceiling. This is existing policy behavior, not a missed execution of the newly fixed inactivity rule.

Eight of the 23 have at least one credited raw top-500 older opponent that finishes outside the top 500. For U10 boys **#10** (`8ed299df-239a-496d-b06a-02d44216a139`), both older opponents counted toward the required two raw top-500 non-losses finish **#1,003 and #1,226**; another credited raw top-1,000 opponent finishes #216. That does not prove the team is weak, but it leaves a concrete reason to question whether this evidence supports a national top-10 placement.

Conversely, U12 boys #15 has non-losses against seven credited older raw top-500 teams that all remain top 500, including five older opponents finishing top 100. The flag must not erase that stronger evidence. Location or lack of out-of-state travel alone is not a disqualification.

### Every remaining flagged top-100 placement

“Raw 500 retained” counts credited raw top-500 older opponents that remain final top 500. “Older final 100” counts credited older raw top-1,000 opponents that finish top 100. All rows use the play-up exception; adequacy of the resulting position remains a policy judgment.

| Team ID | Board | Rank | Games | Older raw 500 | Raw 500 retained | Older final 100 |
|---|---|---:|---:|---:|---:|---:|
| 01f1234d-af96-486b-b292-304003c0b8d9 | U10 boys | 9 | 23 | 2 | 1 | 0 |
| 8ed299df-239a-496d-b06a-02d44216a139 | U10 boys | 10 | 22 | 2 | 0 | 0 |
| 0a0925c8-3231-49dc-ae40-50bb0ba8d1bd | U10 boys | 32 | 30 | 3 | 2 | 0 |
| f4bff5a7-0489-4cba-b712-3fce5d05999f | U10 boys | 37 | 30 | 3 | 3 | 2 |
| 6d7fa4c2-b008-4097-aa36-f9e3cae8b657 | U10 girls | 1 | 28 | 4 | 4 | 1 |
| 771ccdde-9f65-4640-a9bd-d030c89eed70 | U10 girls | 19 | 30 | 2 | 2 | 0 |
| 9d2df9bf-3809-461f-b0a2-75ccd829d42f | U10 girls | 86 | 30 | 4 | 4 | 1 |
| 7eebf48a-d652-4c89-a536-5310da674e36 | U11 boys | 52 | 30 | 2 | 2 | 2 |
| c99e4e74-ed31-4a01-97f7-f8a2dc27ae81 | U11 boys | 73 | 30 | 3 | 3 | 0 |
| bda3f7ac-611a-4461-a297-c693ab82aa6b | U11 girls | 15 | 30 | 4 | 4 | 1 |
| d70ac4c7-50c2-477f-b925-67ea889a00f3 | U11 girls | 17 | 30 | 4 | 3 | 0 |
| 5243f853-4bb0-4f3d-9f4f-8afc27a88af6 | U11 girls | 85 | 24 | 4 | 4 | 1 |
| a8801c99-44b8-44af-818a-d9052e813615 | U12 boys | 15 | 21 | 7 | 7 | 5 |
| 70bb6fb5-6e5a-411f-aa3b-6d8de016bec1 | U12 boys | 38 | 12 | 4 | 4 | 4 |
| 4e087db8-3151-42f4-a079-27fc31e90c03 | U12 boys | 49 | 16 | 4 | 4 | 3 |
| 7285134c-d8ff-47aa-9689-bca438d7e538 | U12 boys | 80 | 20 | 4 | 4 | 2 |
| 563c1a33-e694-40df-ab31-5a80ff337fd3 | U12 boys | 83 | 30 | 3 | 1 | 0 |
| 5269cdce-d6a3-437a-a35a-988e2c9aa3fd | U12 girls | 20 | 14 | 5 | 5 | 2 |
| d008a0f6-ad00-460a-a1ab-bfc043cfc08a | U12 girls | 58 | 24 | 2 | 2 | 0 |
| b0862050-bf1e-4fe7-8bb2-63c7ed9d4888 | U13 boys | 5 | 30 | 7 | 5 | 2 |
| 0fa30277-0033-4b7f-96cf-680947fe9545 | U13 girls | 28 | 19 | 5 | 5 | 2 |
| 5f43d163-20df-43b5-91d9-8d6be8dc86db | U14 boys | 61 | 26 | 2 | 1 | 1 |
| 9dd5030b-346b-4afb-a780-43c17a5eb566 | U16 girls | 60 | 22 | 3 | 2 | 0 |

## Newly eligible teams

All seven newly eligible top-25 entrants have at least one non-loss against a same-age opponent that also finishes top 100. They are not automatically suspect merely because they have 10 or 11 games. Across all 72 newly eligible top-100 teams, 11 have no same-age opponent finishing top 100 and 23 have no non-loss against such an opponent. These describe the evidence; they are not new disqualification rules.

| Team ID | Board | Rank | Games | Same-age final top-100 opponents | Non-losses against those opponents |
|---|---|---:|---:|---:|---:|
| d78a6ae7-6314-429b-8bc9-a4f8991628da | U10 boys | 2 | 11 | 4 | 4 |
| 674f90b4-9c92-4eee-9b0d-1bb5750e5037 | U10 boys | 18 | 10 | 2 | 1 |
| 10c5ac63-2ff1-4183-a508-5fc355fe6d3d | U10 boys | 22 | 11 | 1 | 1 |
| 549e65de-74cb-40b7-8242-b3af72cc9c85 | U11 boys | 7 | 10 | 2 | 2 |
| 5d5bdb95-80d9-410b-854c-ae1bb53d9b99 | U11 girls | 20 | 10 | 4 | 2 |
| 66f4497b-bc07-4621-ac3c-177d61f1e726 | U12 boys | 18 | 11 | 1 | 1 |
| 5d5a4fde-277f-436b-9792-d7f3e4a8a0bd | U17 boys | 21 | 11 | 1 | 1 |

## Review coverage and verification

The review covers **105 distinct teams**: every flagged top-100 team in either the foundation or combined run, all 72 newly eligible top-100 teams, and the investigated cases. It re-derived every evidence field for those teams, matched missingness and nonmissing numeric values exactly, traced the actual ceiling return path for all 105, verified all applicable score ceilings, and inspected the 185 credited older-opponent links. The evidence records every same-age opponent supporting a top-100/top-500 count, with game IDs, dates and scores.

The original receipt checks and this review rechecked source/runtime/input/output hashes, 36 engine and 36 ML stage captures, fixed timestamps, complete connectivity diagnostics and permitted offline reads. The saved selector exactly matches the completed selected games and all eligible team IDs. No October outcomes, live fetches, production writes or engine reruns were used.

Both implementation PRs passed all 11 GitHub checks before this report-only addition. The combined source passed 357 unique focused tests and repository lint. This report adds no ranking code. Existing source references and September evidence remain frozen. No independent external reviewer has approved this report.

## Publication boundary

The preview and assistant review are complete. The remaining decision is whether the owner accepts the documented play-up and score-ceiling behavior for this release. The isolated-team goal is not certified as fully solved. No merge, publication, additional tuning, new experiment or threshold redesign has been performed. Any rule change needs a separate explicit decision; the preserved known-good exceptions must not be discarded wholesale.

[Complete evidence, hashes and all 105 review records](2026-10-06-combined-ranking-preview-evidence.json) includes the machine-readable per-board movement, all reviewed teams, supporting games and older opponents.
