# Ceiling ordering correction: saved combined preview

October 7, 2026. Implementation, ceiling-only replay, local tests and report review are complete. Neither draft PR is merged or published.

## Result and remaining limitation

The ceiling step reversed some stronger and weaker teams that had the same restriction. The fix assigns the existing score slots in pre-ceiling order within each board, eligibility status and ceiling group. It preserves the ceiling values, widths and evidence exceptions. Scores never exceed their original pre-ceiling value or numeric ceiling. Deterministic ties remain ordered after age scaling where nonzero floating-point scores permit separation; zero cannot encode an additional distinction.

On the saved newest-30/365, minimum-10 combined preview, adjacent same-ceiling ordering violations fall from **95 to zero**. The Florida U13 boys example moves **#5 to #26**. This fixes an ordering error; it does not certify the remaining high placements.

**15,420 of 65,388 eligible teams change rank**, including 3,195 moving more than 100 places and 894 moving more than 300. The largest movement is 841. Selection, eligibility, ceiling decisions and pre-ceiling scores are unchanged. The same 23 flagged teams remain top 100; top-25 flags fall from nine to eight. All 112 newly entering top-100 teams retain their existing 400 ceiling bucket.

The broader review identifies four additional cases for owner consideration below. Do not treat completion of this implementation as approval to publish or as proof that the isolated-schedule concern is fully resolved. No threshold or play-up redesign was added.

## Replay boundaries and provenance

This replays only `_apply_publication_cap_band` on nine saved age-group captures from the completed combined preview at `e5c575a7b4a4219b063078c2e6d47ba47cc0e69b`. It uses 136,044 saved rows, including inactive teams, and checks all 18 active boards. No engine, ML, game selection, eligibility calculation, live database query or later-outcome evaluation was rerun.

The exact frozen module reproduces every recorded original final score and numeric cap. Only the corrected pure cap-band function is substituted for the second pass. PR #1257 also differs in upstream cache orchestration; importing the frozen module prevents that unrelated code difference from affecting this replay. A second invocation reproduces the corrected scores exactly. All numeric caps and original-score bounds hold. On these actual inputs, each group's score-slot multiset is exactly unchanged; the floating-point tie repairs are exercised by synthetic regression cases.

Source, runtime, input, selected-game, metadata and output hashes are in the [machine-readable evidence](2026-10-07-ceiling-order-replay-evidence.json). The candidate calculator SHA-256 is `699387fa9666e6412ff0b4390144dcb87c64aa114547197c683e312df84a00f1`. The output SHA-256 is `f69fd4a2c41c5798560bba05b9feefdd6d3768f88927a580826f13df23c7588b`. Original and derived August inputs and prior September reports remain preserved. The scratch replay, output parquet and original receipts are retained at `C:\Users\Dallas Heidt\AppData\Local\Temp\pitchrank-ceiling-order-20261007`. Historical September prediction statistics are not results for this correction.

## All 18 boards

Changes compare the corrected ceiling replay with the saved combined preview, not with the incumbent production rankings. Entrants were outside the indicated range in that preview and inside after this correction. Eligibility is unchanged.

| Board | Eligible | Rank changes | Moves over 100 | Largest move | New top 25 | New top 100 |
|---|---:|---:|---:|---:|---:|---:|
| U10 girls | 1,046 | 585 | 18 | 320 | 0 | 0 |
| U10 boys | 1,900 | 1,164 | 70 | 673 | 4 | 0 |
| U11 girls | 3,220 | 639 | 82 | 477 | 0 | 0 |
| U11 boys | 5,896 | 1,243 | 779 | 836 | 4 | 9 |
| U12 girls | 3,346 | 538 | 80 | 387 | 4 | 10 |
| U12 boys | 6,126 | 1,192 | 570 | 795 | 1 | 8 |
| U13 girls | 3,553 | 602 | 82 | 385 | 4 | 8 |
| U13 boys | 6,219 | 1,236 | 513 | 841 | 5 | 8 |
| U14 girls | 3,245 | 603 | 65 | 366 | 0 | 4 |
| U14 boys | 5,408 | 1,135 | 207 | 740 | 3 | 9 |
| U15 girls | 3,008 | 589 | 62 | 352 | 1 | 7 |
| U15 boys | 4,869 | 1,088 | 171 | 659 | 1 | 6 |
| U16 girls | 2,300 | 559 | 50 | 308 | 0 | 6 |
| U16 boys | 3,820 | 1,112 | 119 | 655 | 4 | 15 |
| U17 girls | 1,800 | 491 | 36 | 262 | 0 | 8 |
| U17 boys | 2,978 | 1,049 | 135 | 532 | 5 | 5 |
| U19 girls | 2,645 | 519 | 48 | 282 | 0 | 2 |
| U19 boys | 4,009 | 1,076 | 108 | 619 | 5 | 7 |

U10 boys and girls are shown separately. Their eligibility and selected games are unchanged. This ordering correction neither resolves nor remeasures the historical U10 accuracy uncertainty.

## Investigated cases

| Case | Combined preview | Corrected replay | Interpretation |
|---|---:|---:|---|
| Florida U13 boys | 5 | 26 | The same-ceiling reversal is removed; its pre-ceiling rank was 149. |
| California U10 boys | 10 | 8 | The fix is not a blanket demotion. Its full schedule includes wins against opponents finishing #216, #246 and #285. The two older opponents credited as raw top-500 non-losses move from #1,003/#1,226 to #867/#1,088; the linked evidence preserves both snapshots and their game IDs. |
| New York U12 boys | 15 | 15 | Five distinct older final top-100 non-losses; pre-ceiling rank 1. |
| Original Texas U13 boys case | 498 | 465 | Remains outside the top 100 with the stricter 1,800 bucket. |
| Original Washington U13 girls case | 276 | 270 | Remains outside the top 100 with the stricter 1,800 bucket. |

## Expanded high-placement review

The review covers all **217 teams**: the 105 prior cases and 112 new top-100 entrants. The evidence retains **3,384 selected opponent relationships**, dates, scores, opponent ages and final ranks, plus the reproduced cap decision for every reviewed team. The 185 previously credited older-opponent relationships are also preserved with original and corrected ranks and verified game outcomes. For 21 relationships, the credited non-loss games are in the saved 365-day inputs but outside that team's selected games; the evidence explicitly records that distinction. Existing evidence thresholds, play-up relief and in-state exceptions are unchanged.

The original flag tests sparse same-age raw top-100/top-500 evidence together with the existing isolation diagnostic. Keep that flag unchanged for historical comparison. Review now also considers results against opponents one age group older, their final placements, repeat opponents, and observed links from each opponent's own selected schedule. This adds context without making those model-derived ranks independent evidence of quality.

All 23 flagged top-100 teams retain play-up relief and have at least two distinct non-losses against older final top-500 teams; 13 have at least one against an older final top-100 team. All have observed opponent links beyond one region. That supports reviewing play-up evidence individually; it does not prove each placement is justified.

Among the 112 new top-100 entrants, 41 have no selected win/tie against a same-age or next-age final top-100 opponent. One has none against a final top-500 opponent. Three have no observed external-region links in the selected schedules examined. These review filters do not establish an automatic failure rule or an approved policy change.

| Additional case | Before -> after | Evidence and remaining concern |
|---|---|---|
| Massachusetts U13 boys, `29b048b8-949e-4c18-a9ab-335665ddbcfc` | 107 -> 91 | 26 games against nine opponents. No same-age or next-age final top-500 non-loss; lost 1-5 to #41. All nine opponents have external-region links, so connectivity alone does not establish adequate opponent quality. |
| Michigan U12 boys, `853e6105-c296-4c36-909b-e6fc3432c060` | 106 -> 96 | 16 games against seven opponents. Non-losses against final #130, #317 and #373; four losses to #430. No external-region link observed in the inspected schedules. |
| Texas U13 boys, `86759578-eb09-44b3-b424-d74b1b578d24` | 103 -> 88 | A different team from the original Texas case. 18 games against six opponents. One final top-500 non-loss (3-0 against #365), a 1-7 loss to #223, and many repeat wins against much lower teams. No external-region link observed. |
| Maine U14 boys, `ab04ed43-9b88-43bf-83b3-ae1971ceb46a` | 112 -> 100 | 19 games against 15 opponents; four final top-500 non-losses (#107, #108, #151, #247). No external-region link observed. |

Each of these four follows an unchanged cap-400 decision. That number maps to a pre-ceiling **score**, not a guarantee of a final position below #400. The ordering correction can promote a stronger member of a ceiling group into the top 100 while a weaker member leaves it. This is why numeric-cap compliance and a lower flag count do not establish overall ranking quality.

Regional links use raw state/province metadata, including Canadian ON and an invalid `J ` label retained in the evidence. They are descriptive, not a new isolation metric. The three no-external-link examples remain single-state within the selected schedules examined; this does not prove the complete historical graph is disconnected. Missing or limited evidence is not proof of either weakness or safety.

### The 23 remaining flagged teams

Older counts below are distinct opponents with a selected win or tie, evaluated using the corrected final rank on their own board. They are not counts of games. UUIDs map directly to the full game evidence.

| Board / state | Before | After | Older top-100 non-losses | Older top-500 non-losses | Team ID |
|---|---:|---:|---:|---:|---|
| U10 boys AZ | 9 | 7 | 0 | 3 | `01f1234d-af96-486b-b292-304003c0b8d9` |
| U10 boys CA | 10 | 8 | 0 | 3 | `8ed299df-239a-496d-b06a-02d44216a139` |
| U10 boys OH | 32 | 32 | 0 | 3 | `0a0925c8-3231-49dc-ae40-50bb0ba8d1bd` |
| U10 boys PA | 37 | 37 | 2 | 5 | `f4bff5a7-0489-4cba-b712-3fce5d05999f` |
| U10 girls CA | 1 | 1 | 1 | 4 | `6d7fa4c2-b008-4097-aa36-f9e3cae8b657` |
| U10 girls TX | 19 | 21 | 0 | 2 | `771ccdde-9f65-4640-a9bd-d030c89eed70` |
| U10 girls PA | 86 | 86 | 1 | 6 | `9d2df9bf-3809-461f-b0a2-75ccd829d42f` |
| U11 boys TX | 52 | 55 | 2 | 3 | `7eebf48a-d652-4c89-a536-5310da674e36` |
| U11 boys FL | 73 | 73 | 0 | 2 | `c99e4e74-ed31-4a01-97f7-f8a2dc27ae81` |
| U11 girls MO | 15 | 22 | 0 | 5 | `bda3f7ac-611a-4461-a297-c693ab82aa6b` |
| U11 girls MI | 17 | 24 | 0 | 3 | `d70ac4c7-50c2-477f-b925-67ea889a00f3` |
| U11 girls CA | 85 | 85 | 1 | 4 | `5243f853-4bb0-4f3d-9f4f-8afc27a88af6` |
| U12 boys NY | 15 | 15 | 5 | 9 | `a8801c99-44b8-44af-818a-d9052e813615` |
| U12 boys FL | 38 | 50 | 4 | 7 | `70bb6fb5-6e5a-411f-aa3b-6d8de016bec1` |
| U12 boys TX | 49 | 54 | 3 | 6 | `4e087db8-3151-42f4-a079-27fc31e90c03` |
| U12 boys WY | 80 | 80 | 2 | 4 | `7285134c-d8ff-47aa-9689-bca438d7e538` |
| U12 boys FL | 83 | 83 | 0 | 3 | `563c1a33-e694-40df-ab31-5a80ff337fd3` |
| U12 girls FL | 20 | 28 | 3 | 5 | `5269cdce-d6a3-437a-a35a-988e2c9aa3fd` |
| U12 girls WA | 58 | 58 | 0 | 2 | `d008a0f6-ad00-460a-a1ab-bfc043cfc08a` |
| U13 boys FL | 5 | 26 | 1 | 5 | `b0862050-bf1e-4fe7-8bb2-63c7ed9d4888` |
| U13 girls WA | 28 | 24 | 1 | 5 | `0fa30277-0033-4b7f-96cf-680947fe9545` |
| U14 boys FL | 61 | 48 | 1 | 7 | `5f43d163-20df-43b5-91d9-8d6be8dc86db` |
| U16 girls IN | 60 | 56 | 0 | 3 | `9dd5030b-346b-4afb-a780-43c17a5eb566` |

## Verification and publication boundary

- 131 focused regressions pass, including 11 new ordering cases. The original behavior fails the new boundary checks.
- Independent code review found two tie cases: chained score slots and age-scaled ties. Both are fixed and covered. Removing either correction makes its regression fail. Reviewers report no remaining code or coverage blocker; an additional 200 in-memory probes checked ordering and bounds.
- Python lint and the new test-file lint pass. Across the full Python suite and the targeted environment repair, 8,154 unique tests pass and 13 skip. The first run had 110 shell-hook failures because Windows selected WSL Bash, which could not open Windows script paths. With Git Bash first on PATH, all 112 hook tests pass; no product or test source changed to resolve that environment issue.
- No production publication, merge, threshold redesign or extra ranking batch was performed. Both existing draft PRs will carry this replay and its limitations. Any broader evidence-policy change requires a separate owner decision.
