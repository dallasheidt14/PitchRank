# Ceiling placement investigation and band isolation

October 7, 2026. Saved August 31 combined preview with newest 30 valid games within 365 days and minimum 10. Comparison reference: `78425319d4cd319560751ee254facbf02077fece`. This is a ceiling-only replay, not a new engine run or a production ranking.

## Decision

Retain the correction that computes compressed score bands within each age, gender and eligibility status. Other genders and inactive teams must not change the score slots assigned to an active board. The earlier ordering repair already respected those boundaries; the initial compression did not.

**This does not solve the broader national-placement concern.** The pooled-age numeric cutoff calculation, fixed cap depths and existing supported in-state/play-up exceptions remain unchanged. No publication is authorized.

A separate prototype also moved the cutoff lookup onto individual boards. Reject that prototype: it created 1,248 new zero scores, including 1,244 U17 girls, and moved 10,503 active teams by more than 300 places. A cap depth at or beyond the bottom of a smaller board can pick a zero cutoff. Unchanged numeric thresholds do not mean unchanged policy when the population changes. The rejected source and measurements are preserved separately; none of that cutoff change is in the release diff.

## FC Europa and the underlying issue

FCE U10 Boys Pre ECNL (`8a00593d-56be-496f-ad8d-9036041cfcde`) moves **#28 to #27 nationally** and stays **#5 in Pennsylvania**. The user estimated about #6 in PA and #150 nationally; the latter is not established ground truth and was not used as a tuning target.

The saved 15-game record is 13 wins, one draw and one loss, against 13 opponents. Every recorded game is selected. Its rank is #25 by Glicko rating, #6 after normalization and uncertainty adjustment, and #7 before ceilings. ML reduces its score. The high rating therefore begins before the ceilings.

None of its 12 same-age opponents has a selected same-age raw top-100 non-loss outside the fixed group of FC Europa plus its 13 opponents. That is a limited corroboration finding, not proof the group is weak. The schedule graph reaches 1,715 of 1,900 active U10 boys, so this is not a disconnected component.

| U10 boys team | Before ceilings | Prior final | Current final |
|---|---:|---:|---:|
| FC Europa | 7 | 28 | 27 |
| Philadelphia Ukrainian Nationals Black | 207 | 20 | 20 |
| Penn Fusion Elite 2017 | 234 | 22 | 22 |
| Philadelphia SC Surf Azzurri | 248 | 24 | 24 |
| FC Delco Black Conshy | 2 | 2 | 2 |

FC Europa beat Ukrainian Nationals twice and Penn Fusion once. Their softer ceiling exceptions still place those teams ahead of it. This demonstrates the large effect of ceiling groups; it does not establish a definitive head-to-head ordering or identify a single cause of regional inflation.

## Scope and bounded checks

- All 136,044 prior scores reproduce exactly. The candidate repeats exactly; scores stay within bounds and never exceed their own pre-ceiling score. The cap choices and numeric cutoff values are identical to the reference.
- All 65,388 active teams remain eligible. Selected games and pre-ceiling scores are reused unchanged. Source comparison permits changes only to `_apply_publication_cap_band`.
- Given the unchanged cutoff values, every board/status group matches processing that group independently. This claim is about compression; the preserved numeric cutoffs still use the pooled age group.
- 15,344 ranks change, 75 by more than 100 places, none by more than 300. Largest move: 129. Scores rise for 15,529 active teams and fall for 584; no score newly becomes zero.
- There are seven new top-100 entrants and two new top-25 entrants. All 26 top-100 flags remain the same teams; 11 are in the top 25. A flag count is not a ranking-quality verdict.
- Review refreshed 361 teams, 7,162 selected opponent relationships and all 185 preserved older-opponent credits. Raw evidence ranks and final ranks are separate; final-rank corroboration is descriptive and can change when opponents move.

## All 18 boards

| Board | Active | Ranks changed | Moves over 100 | Largest move | Flagged top 100 |
|---|---:|---:|---:|---:|---:|
| U10 girls | 1046 | 417 | 0 | 42 | 3 |
| U10 boys | 1900 | 723 | 0 | 95 | 5 |
| U11 girls | 3220 | 736 | 0 | 86 | 5 |
| U11 boys | 5896 | 1284 | 13 | 118 | 2 |
| U12 girls | 3346 | 629 | 0 | 66 | 2 |
| U12 boys | 6126 | 1306 | 7 | 114 | 5 |
| U13 girls | 3553 | 622 | 0 | 48 | 1 |
| U13 boys | 6219 | 1293 | 53 | 129 | 1 |
| U14 girls | 3245 | 637 | 0 | 47 | 0 |
| U14 boys | 5408 | 1204 | 0 | 95 | 1 |
| U15 girls | 3008 | 621 | 0 | 49 | 0 |
| U15 boys | 4869 | 1107 | 2 | 105 | 0 |
| U16 girls | 2300 | 551 | 0 | 34 | 1 |
| U16 boys | 3820 | 1114 | 0 | 92 | 0 |
| U17 girls | 1800 | 509 | 0 | 31 | 0 |
| U17 boys | 2978 | 1023 | 0 | 75 | 0 |
| U19 girls | 2645 | 540 | 0 | 42 | 0 |
| U19 boys | 4009 | 1028 | 0 | 77 | 0 |

U10 boys and girls remain separate above. No prediction-confirmation result or accuracy improvement is claimed for this change.

## Every new top-25 or top-100 entrant

Counts below are distinct selected same-age non-loss opponents at final top 100 / 500. Every entrant has such evidence, but that alone does not certify its exact placement.

| Board / state | Team ID | Before to after | Same-age 100 / 500 |
|---|---|---:|---:|
| U11 girls CA | `5487572b-0eda-462c-9200-ca70703392ed` | 26 to 25 | 2 / 5 |
| U14 boys FL | `b97a506a-49d4-4673-83a1-b1e9e4004add` | 101 to 100 | 1 / 3 |
| U15 boys MI | `639b5e65-bd7a-4a8f-9701-d83595a75eb2` | 101 to 96 | 1 / 4 |
| U15 boys CA | `aa96aff8-95fa-435b-be67-ac7268f3b374` | 103 to 97 | 4 / 15 |
| U15 boys HI | `14f98f75-c189-47ea-a029-c2553b389694` | 104 to 98 | 0 / 2 |
| U15 boys AZ | `a952bdce-9f3b-4515-8b16-125341edfd09` | 105 to 100 | 0 / 4 |
| U17 boys FL | `430dd20c-5a83-4fc3-90b0-a0cbae6eb6d7` | 26 to 25 | 5 / 16 |
| U19 boys CA | `1dba1293-c6a6-4121-bc1b-1da55c2718d0` | 101 to 100 | 1 / 3 |
| U19 girls MO | `3b84f36d-43d8-478d-afa6-cadece3c6811` | 103 to 100 | 4 / 11 |

Hawaii U15 boys #98 has the narrowest same-age evidence among these entrants: a 1-0 win against final #442 and a 2-2 draw against #453, with no final top-100 non-loss. It keeps its existing 400 cap; the move from #104 comes from score-band separation, not newly earned evidence. Its top-100 placement remains a judgment question.

## All flagged high placements and older-opponent exceptions

The unchanged flag combines isolation with no raw same-age top-100 opponent, at most two raw top-500 opponents and at most one raw top-500 non-loss. All flagged teams retain the existing play-up exception. S means a non-loss against a next-age final top-100 opponent that itself has a same-age final top-500 non-loss. L means that particular corroboration is absent. These are review descriptions, not acceptance thresholds: 16 S and 10 L, unchanged.

| Board / state | Team ID | Before to after | Same-age 100 / 500 | Next-age 100 / 500 | Review |
|---|---|---:|---:|---:|---|
| U10 boys AZ | `01f1234d-af96-486b-b292-304003c0b8d9` | 5 to 5 | 0 / 0 | 0 / 1 | L |
| U10 boys CA | `8ed299df-239a-496d-b06a-02d44216a139` | 6 to 6 | 0 / 3 | 0 / 3 | L |
| U10 boys OH | `0a0925c8-3231-49dc-ae40-50bb0ba8d1bd` | 21 to 21 | 0 / 1 | 1 / 3 | S |
| U10 boys PA | `f4bff5a7-0489-4cba-b712-3fce5d05999f` | 24 to 24 | 0 / 1 | 3 / 5 | S |
| U10 boys AZ | `1610353d-452e-4dc6-b210-86336395a76c` | 92 to 92 | 0 / 0 | 0 / 2 | L |
| U10 girls CA | `6d7fa4c2-b008-4097-aa36-f9e3cae8b657` | 1 to 1 | 0 / 0 | 1 / 4 | L |
| U10 girls TX | `771ccdde-9f65-4640-a9bd-d030c89eed70` | 20 to 20 | 0 / 2 | 0 / 2 | L |
| U10 girls PA | `9d2df9bf-3809-461f-b0a2-75ccd829d42f` | 79 to 79 | 1 / 1 | 1 / 6 | S |
| U11 boys TX | `7eebf48a-d652-4c89-a536-5310da674e36` | 39 to 39 | 0 / 2 | 2 / 3 | S |
| U11 boys FL | `c99e4e74-ed31-4a01-97f7-f8a2dc27ae81` | 57 to 58 | 0 / 0 | 0 / 2 | L |
| U11 girls MO | `bda3f7ac-611a-4461-a297-c693ab82aa6b` | 19 to 19 | 0 / 3 | 1 / 5 | S |
| U11 girls MI | `d70ac4c7-50c2-477f-b925-67ea889a00f3` | 21 to 21 | 0 / 0 | 0 / 3 | L |
| U11 girls CA | `5243f853-4bb0-4f3d-9f4f-8afc27a88af6` | 75 to 78 | 0 / 1 | 1 / 4 | S |
| U11 girls OH | `7c2b49a7-714c-4ef9-b9e5-a91f225ccf85` | 89 to 89 | 0 / 3 | 1 / 9 | S |
| U11 girls TX | `19cfa8d3-1f45-42e7-947d-632388bf417d` | 90 to 90 | 0 / 0 | 1 / 4 | S |
| U12 boys NY | `a8801c99-44b8-44af-818a-d9052e813615` | 15 to 15 | 0 / 0 | 5 / 9 | S |
| U12 boys FL | `70bb6fb5-6e5a-411f-aa3b-6d8de016bec1` | 38 to 37 | 0 / 0 | 4 / 7 | S |
| U12 boys TX | `4e087db8-3151-42f4-a079-27fc31e90c03` | 40 to 40 | 0 / 0 | 3 / 6 | S |
| U12 boys WY | `7285134c-d8ff-47aa-9689-bca438d7e538` | 67 to 71 | 0 / 0 | 2 / 3 | S |
| U12 boys FL | `563c1a33-e694-40df-ab31-5a80ff337fd3` | 71 to 74 | 0 / 0 | 0 / 1 | L |
| U12 girls FL | `5269cdce-d6a3-437a-a35a-988e2c9aa3fd` | 26 to 26 | 0 / 0 | 3 / 5 | S |
| U12 girls WA | `d008a0f6-ad00-460a-a1ab-bfc043cfc08a` | 51 to 55 | 0 / 1 | 0 / 2 | L |
| U13 boys FL | `b0862050-bf1e-4fe7-8bb2-63c7ed9d4888` | 21 to 21 | 0 / 1 | 2 / 5 | S |
| U13 girls WA | `0fa30277-0033-4b7f-96cf-680947fe9545` | 22 to 22 | 0 / 0 | 2 / 5 | S |
| U14 boys FL | `5f43d163-20df-43b5-91d9-8d6be8dc86db` | 44 to 44 | 0 / 0 | 1 / 7 | S |
| U16 girls IN | `9dd5030b-346b-4afb-a780-43c17a5eb566` | 56 to 55 | 0 / 1 | 0 / 3 | L |

The existing U17-to-U19 credits remain in the detailed evidence; a next-age-only summary cannot substitute for those actual credits. This correction does not alter qualifying games or verify provider age labels.

## Previously investigated restrictions

Cap labels refer to reference-score cutoffs, not literal final-rank floors.

| Case | Before to after | Cap unchanged |
|---|---:|---:|
| Original Texas U13 boys | 439 to 437 | 1800 |
| Original Washington U13 girls | 239 to 239 | 1800 |
| Massachusetts U13 boys | 397 to 390 | 1800 |
| Additional Texas U13 boys | 385 to 377 | 1800 |
| California U10 boys | 94 to 94 | 400 |

## Broader ceiling work remains open

The design must treat the cutoff population, restriction strength and application together. It must preserve meaningful rating differences instead of making a soft exception an automatic route above nearly every stricter-capped team. National evidence must distinguish broad corroboration from teams validating each other within a small regional group. A path through the schedule graph, a state border or an opponent's model-derived rank alone is not sufficient proof.

Use FC Europa, Ukrainian Nationals, Penn Fusion and the flagged play-up teams as checks, not target ranks. Preserve genuinely supported in-state and older-opponent results. Recheck all boards, including small boards, and reject score collapse or order reversal before considering release. No new formula or threshold is selected or implemented by this report.

## Verification and evidence

The CI-defined Python scope passed 8,205 tests with 13 skips. Focused smoke passed 135 tests; Python lint passed. Reinstating old compression fails the gender/status isolation regressions. Source review, independent recount of all 361 evidence summaries and report review passed. No production write, merge, full engine rerun, live game fetch or later-outcome evaluation occurred.

[Detailed schedules, cap traces, older-opponent credits, hashes and rejected-candidate findings](2026-10-07-ceiling-band-isolation-evidence.json)
