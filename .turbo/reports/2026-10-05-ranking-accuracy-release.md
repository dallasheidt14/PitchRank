# Combined ranking release: September screening report

The complete offline validation batch finished. This report describes September screening evidence; September informed the design and cannot confirm the release. Nothing in this report authorizes publication.

Completed and reviewed October 6, 2026. Ranking/CLI/scorer source was frozen at `8d816d85910c91d2cd81c6b13323506ede8b82c5`; the actual full-release checkout was `2e285f395c99d11e587f1378ae96604b09591b69`. The intervening commit only corrects a cross-platform test fixture and its review note. All 15 frozen source hashes still match. Main base: `974ad02f8`. The original combination and C1 reference remain pinned.

The full package improves September agreement from **62.647% to 64.977% (+2.330 points)** versus the frozen incumbent, with positive estimates on 16 of 18 boards. The ceiling safeguards correct the investigated placement loopholes, but **do not add a demonstrated prediction gain** over the original pull/gender combination: -0.138 points, with a 95% interval of [-0.369, +0.093], and an equal-weight board change of -0.092. These figures fall short of the fixed +0.25-point and positive-board-average improvement bars. The design and future decision rules remain unchanged.

U10 remains unresolved: compared with the incumbent, boys are -2.878 points and girls -5.023 points. The intervals are wide enough to include both no loss and substantial harm. The package is implemented and technically validated, but has not earned merge/publication approval.

## Scope and reproduction

The release combines the tested SCF-off configuration, the convergence gender correction, connectivity restored only to ceiling decisions, and the freshness/evidence rule-order correction. Existing in-state and play-up exceptions remain. No thresholds, selection policy, or calculation rounds changed.

The archived combination was reproduced exactly, followed by an exact repeat. C1 and the complete release passed exact comparisons of selected games, eligibility, engine and ML stages, upstream helper results, and scores before ceilings. The two safeguard comparisons therefore differ only at the permitted ceiling boundary. The release-versus-C1 comparison also passes exactly.

| Verification | Result | Captured artifacts compared |
| --- | --- | ---: |
| Archived combination vs first repeat | Exact, including every final team column | 9 legacy pre-ceiling files |
| First vs second combination repeat | Exact, including every final team column | 226 |
| C1 vs combination | Exact upstream boundary | 226 |
| Release vs combination | Exact upstream boundary | 226 |
| Release vs C1 | Exact upstream boundary | 226 |

The completion review rechecked all six archived/new run receipts, training/input hashes, loaded source hashes, output hashes, 36 engine and 36 ML captures per new run, and nine pre-ceiling age files. The frozen incumbent denotes the engine used by this experiment, not a claim about which snapshot is currently published.

## September prediction results

Rankings use games through August 31. The measurement counts decided September games between Active teams on the same age/gender board. A tied rating earns half credit. Changes are percentage points; intervals and p-values account for games sharing teams. These descriptive p-values are not new pass/fail decisions.

| Comparison | Games | Change (points) | 95% interval | p |
| --- | ---: | ---: | --- | ---: |
| C1 vs original combination | 21,009 | -0.148 | [-0.373, +0.078] | 0.1991 |
| Release vs C1 | 21,009 | +0.010 | [-0.060, +0.079] | 0.7893 |
| Release vs original combination | 21,009 | -0.138 | [-0.369, +0.093] | 0.2422 |
| Release vs incumbent | 21,009 | +2.330 | [+1.757, +2.903] | 1.515e-15 |

| Comparison | Baseline agreement | Candidate agreement | Equal-weight board change |
| --- | ---: | ---: | ---: |
| C1 vs original combination | 65.115% | 64.967% | -0.111 |
| Release vs C1 | 64.967% | 64.977% | +0.018 |
| Release vs original combination | 65.115% | 64.977% | -0.092 |
| Release vs incumbent | 62.647% | 64.977% | +2.184 |

## All 18 boards

Each change and interval below compares the complete release with the stated reference.

| Board | Games | vs combination | 95% interval | vs incumbent | 95% interval |
| --- | ---: | ---: | --- | ---: | --- |
| U10 boys | 417 | +0.959 | [-3.969, +5.887] | -2.878 | [-7.875, +2.119] |
| U10 girls | 219 | -3.196 | [-9.069, +2.676] | -5.023 | [-11.390, +1.345] |
| U11 boys | 2,418 | -0.331 | [-0.949, +0.288] | +1.592 | [+0.203, +2.981] |
| U11 girls | 1,332 | +0.150 | [-0.847, +1.148] | +1.914 | [-0.181, +4.009] |
| U12 boys | 2,871 | -0.209 | [-0.795, +0.377] | +0.871 | [-0.617, +2.358] |
| U12 girls | 1,523 | +0.263 | [-0.392, +0.918] | +2.167 | [+0.283, +4.051] |
| U13 boys | 2,343 | -0.427 | [-0.980, +0.127] | +3.094 | [+1.358, +4.830] |
| U13 girls | 1,240 | -0.242 | [-1.031, +0.547] | +3.669 | [+1.235, +6.103] |
| U14 boys | 2,239 | -0.447 | [-0.956, +0.062] | +2.099 | [+0.300, +3.898] |
| U14 girls | 1,545 | -0.129 | [-0.776, +0.517] | +4.337 | [+2.164, +6.509] |
| U15 boys | 1,130 | -0.265 | [-1.133, +0.602] | +3.363 | [+0.729, +5.996] |
| U15 girls | 830 | -0.120 | [-0.971, +0.730] | +1.928 | [-1.176, +5.032] |
| U16 boys | 786 | +0.382 | [-0.912, +1.675] | +2.354 | [-0.964, +5.671] |
| U16 girls | 523 | +0.191 | [-1.158, +1.541] | +6.119 | [+2.613, +9.624] |
| U17 boys | 405 | -0.494 | [-3.061, +2.073] | +2.963 | [-2.010, +7.936] |
| U17 girls | 410 | +0.976 | [-0.528, +2.479] | +0.976 | [-2.563, +4.514] |
| U19 boys | 374 | +0.535 | [-0.948, +2.018] | +4.813 | [-0.814, +10.440] |
| U19 girls | 404 | +0.743 | [-0.085, +1.570] | +4.950 | [+1.087, +8.814] |

## Isolation and U10 uncertainty

The isolation subgroup is fixed from the incumbent: SCF below 0.6, with a game counted once when either qualifying team faces a team from a known different state. U10 boys and girls appear separately above; pooled U10 appears below. An overall gain does not establish a U10 fix, and a wide interval does not establish safety.

| Comparison/subgroup | Games | Change (points) | 95% interval | p |
| --- | ---: | ---: | --- | ---: |
| C1 vs original combination: isolation | 2,024 | -0.543 | [-1.287, +0.200] | 0.1518 |
| C1 vs original combination: pooled U10 | 636 | -0.786 | [-4.592, +3.020] | 0.6856 |
| Release vs C1: isolation | 2,024 | +0.099 | [-0.263, +0.461] | 0.5928 |
| Release vs C1: pooled U10 | 636 | +0.314 | [-0.302, +0.931] | 0.3174 |
| Release vs original combination: isolation | 2,024 | -0.445 | [-1.249, +0.360] | 0.2786 |
| Release vs original combination: pooled U10 | 636 | -0.472 | [-4.305, +3.362] | 0.8094 |
| Release vs incumbent: isolation | 2,024 | +1.556 | [-0.186, +3.299] | 0.08006 |
| Release vs incumbent: pooled U10 | 636 | -3.616 | [-7.569, +0.336] | 0.07294 |

## Ranking movement

Positions are within age and gender among Active teams. A ceiling depth is not a guaranteed final rank. Scores and positions can change when other teams move.

| Comparison | Active in both | Positions changed | Move >25 | Move >100 | Move >300 | Ceiling changed |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| C1 vs original combination | 60,640 | 20,182 | 15,465 | 9,571 | 2,412 | 16,775 |
| Release vs C1 | 60,640 | 17,893 | 4,575 | 741 | 466 | 3,194 |
| Release vs original combination | 60,640 | 20,295 | 16,043 | 10,615 | 3,046 | 19,969 |
| Release vs incumbent | 60,640 | 60,546 | 56,756 | 48,201 | 33,889 | 19,496 |

No team changes eligibility, selected-game count, or crosses the 12-game publication minimum.

## Reviewed high placements

The unchanged descriptive flag uses incumbent isolation, no top-100 same-age opponents, at most two top-500 same-age opponents, and at most one top-500 non-loss opponent. It identifies cases for review, not proven weak teams. A lower flagged count alone does not prove quality.

| Version | Flagged top 25 | Flagged top 100 |
| --- | ---: | ---: |
| combo | 4 | 79 |
| c1 | 6 | 53 |
| release | 6 | 23 |

| Case | Incumbent | Combination | C1 | Release |
| --- | ---: | ---: | ---: | ---: |
| Texas U13 boys | 1225 | 98 | 99 | 537 |
| Washington U13 girls | 210 | 64 | 55 | 313 |
| California U12 girls control | 361 | 9 | 51 | 51 |

All 23 remaining flagged teams were inspected individually; 23 meet the existing play-up exception. Credited opponent counts were recomputed from the frozen games and matched exactly. The table distinguishes raw opponent strength used by the rule from final placement and the older opponents' own same-age evidence. Model-derived support does not independently prove competitive strength.

| Team UUID | Board/state | Rank | Ceiling depth | Qualifying play-up | Credited older top 500 | Still top 500 | Older with ≥3 same-age top-100 opponents | Older with zero |
| --- | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: |
| `6d7fa4c2-b008-4097-aa36-f9e3cae8b657` | U10 female / CA | 1 | 250 | True | 4 | 3 | 2 | 1 |
| `844c94a5-847d-4253-87c7-d40a78001d76` | U10 female / CA | 6 | 250 | True | 3 | 3 | 0 | 0 |
| `01f1234d-af96-486b-b292-304003c0b8d9` | U10 male / AZ | 7 | 250 | True | 3 | 1 | 0 | 2 |
| `f4bff5a7-0489-4cba-b712-3fce5d05999f` | U10 male / PA | 13 | 250 | True | 5 | 5 | 1 | 1 |
| `a8801c99-44b8-44af-818a-d9052e813615` | U12 male / NY | 21 | 250 | True | 8 | 8 | 5 | 0 |
| `33f3a750-2c39-4c15-a113-5342efdabcba` | U10 female / NY | 24 | 250 | True | 6 | 6 | 1 | 0 |
| `563c1a33-e694-40df-ab31-5a80ff337fd3` | U12 male / FL | 26 | 250 | True | 4 | 2 | 0 | 3 |
| `286ed7e9-c9f7-4548-8c70-a58f968cf395` | U10 male / FL | 27 | 250 | True | 2 | 2 | 0 | 1 |
| `0fa30277-0033-4b7f-96cf-680947fe9545` | U13 female / WA | 36 | 250 | True | 4 | 4 | 0 | 3 |
| `19cfa8d3-1f45-42e7-947d-632388bf417d` | U11 female / TX | 38 | 250 | True | 6 | 5 | 3 | 1 |
| `7285134c-d8ff-47aa-9689-bca438d7e538` | U12 male / WY | 42 | 250 | True | 4 | 4 | 1 | 0 |
| `9d2df9bf-3809-461f-b0a2-75ccd829d42f` | U10 female / PA | 48 | 250 | True | 5 | 5 | 0 | 0 |
| `d70ac4c7-50c2-477f-b925-67ea889a00f3` | U11 female / MI | 57 | 250 | True | 4 | 2 | 0 | 2 |
| `c99e4e74-ed31-4a01-97f7-f8a2dc27ae81` | U11 male / FL | 57 | 250 | True | 6 | 5 | 3 | 1 |
| `9dd5030b-346b-4afb-a780-43c17a5eb566` | U16 female / IN | 61 | 250 | True | 3 | 2 | 0 | 3 |
| `7eebf48a-d652-4c89-a536-5310da674e36` | U11 male / TX | 63 | 250 | True | 4 | 4 | 2 | 0 |
| `b0862050-bf1e-4fe7-8bb2-63c7ed9d4888` | U13 male / FL | 64 | 250 | True | 6 | 4 | 1 | 2 |
| `844dd0d9-4b5d-4f40-bff4-de60ff3cf2eb` | U13 male / FL | 67 | 250 | True | 3 | 3 | 0 | 1 |
| `4e087db8-3151-42f4-a079-27fc31e90c03` | U12 male / TX | 72 | 250 | True | 4 | 3 | 2 | 0 |
| `5f43d163-20df-43b5-91d9-8d6be8dc86db` | U14 male / FL | 72 | 250 | True | 3 | 2 | 1 | 0 |
| `70bb6fb5-6e5a-411f-aa3b-6d8de016bec1` | U12 male / FL | 75 | 250 | True | 6 | 6 | 3 | 0 |
| `1fc603f1-3266-4ea9-9089-657d458a1c85` | U15 male / FL | 84 | 250 | True | 4 | 3 | 1 | 2 |
| `f6029ace-a78e-40c2-a4b8-a508b41ef8f8` | U11 male / TX | 91 | 250 | True | 7 | 5 | 0 | 3 |

The full union contains **92 teams**, including seven that reached the top 25 in at least one version. All 92 were inspected by comparing their same-age evidence, play-up evidence, ceiling depth and final placement. Of the 69 now outside the top 100, 38 receive a stricter connectivity-based ceiling in C1 and 31 receive a stricter evidence ceiling with the rule-order correction. The other 23 retain play-up relief. The [committed evidence record](2026-10-05-ranking-accuracy-release-evidence.json) includes every disposition, all four ranks, all three candidate ceiling depths, and all **104 credited older-opponent relationships**. Original local CSV/JSON artifacts are preserved with hashes.

The remaining top-25 cases illustrate why an exception is not proof of quality. Arizona U10 boys #7 qualifies through three older opponents ranked in the raw top 500, but only one remains top 500 after ceilings and two have no same-age top-100 opponents. New York U12 boys #21 has eight credited older opponents, all still top 500, with five having at least three same-age top-100 opponents. California U10 girls #1 has four credited older opponents, three still top 500. These differences remain visible in the audit; the unchanged rule does not establish that every high placement is deserved.

Connectivity restoration can also lift teams: the flagged top-25 count rises from four to six. The lower top-100 flag count is therefore not a blanket quality verdict. Play-up relief remains in scope unchanged; this report does not turn thinner supporting evidence into a demonstrated defect or new design.

## Implementation checks and review

The release passed 8,143 Python tests (13 skipped), 852 frontend tests, repository lint, frontend typecheck/format/generated-file checks and seven independent targeted mutation probes. Production-entry, dry-run, missing-data, source-cohort/cache and scoring-lock regressions are covered. The [implementation review](2026-10-05-ranking-release-review.md) records the source review and the tightly bounded Linux/Windows fixture correction. All GitHub checks passed on the measured checkout `2e285f395`; no GitHub reviewer findings were posted when this report was reviewed. This report adds evidence only and does not change measured code.

## Confirmation and publication

The unchanged original combination must first pass its locked untouched-month check against the incumbent. Only then evaluate this full release against the combination, treating both ceiling safeguards as one candidate. C1 remains diagnostic. Apply the incremental thresholds and cumulative board/isolation harm veto documented in the release plan. Freeze code, scorer, comparisons, input records and the unseen-outcome attestation before evaluation. Otherwise use the next untouched complete month. Failure or inconclusive results do not authorize publication.

Merge and publication still require explicit approval after a pass. Record the prior release and publication snapshot before adoption, verify stored rankings and all 18 boards afterward, and revert/rebuild with the previous engine for a release-caused defect.

## Evidence

Local artifact directory: `C:\Users\Dallas Heidt\AppData\Local\Temp\pitchrank-release-20261005`. The stopped October 4 run is preserved separately. The [committed evidence record](2026-10-05-ranking-accuracy-release-evidence.json) contains the exact September statistics, all-board movement, source/run verification, all 92 reviewed placements and 104 play-up relationships, plus SHA-256 hashes of the original artifacts. The raw frozen datasets and full captures remain local.

- Committed evidence SHA-256: `569cdcef81e971cd300895b6cc59dde572e52c89b39beb9b675de489aab0734d`

- Training manifest SHA-256: `1fcc7fb0d335f8dca38fbb3b3863f6980c75f031a5ae82e82bed59609157de10`
- September games SHA-256: `5feac9c024a2347920c2074bc706c5ecf387df523694511bdfa736501f8199be`
- incumbent completion receipt SHA-256: `b24e2a3a0ee4942090c331ff3cc310e4d8add3f176f0410d55569e10f1b48066`
- combo completion receipt SHA-256: `ea6f3150f1a9f47cc17b325dca830399db9a0066f27a25221a9dafdbc8938231`
- c1 completion receipt SHA-256: `d1b31cb67180645afb0bd5189cb049718dc93224a8581a0d92a2861dbb7717a7`
- release completion receipt SHA-256: `06b83ed15f8e1a77835bd7c5dbe011ac49688b4195b755eb29ec5d7b6dd170ee`
