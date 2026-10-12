# Current-input ceiling cutoff preview — reviewed 2026-10-12

**Recommendation: hold publication of the cutoff correction by itself.** The boys/girls cutoff bug is real and the corrected arithmetic reproduces exactly. But this change also pushes several teams with qualifying older-opponent results much farther down, while questionable high placements remain. The website was not changed.

Pizzicata improves from **Arizona #6 to #17, national #615 to #958** on the same October 12 inputs. That is a useful direction for the reported example, not proof of its correct rank or of a general solution to isolated schedules.

The next focused decision is how existing ceiling restrictions should respect qualifying older-opponent evidence, and how a restrictive score category can still permit a very high final placement. Keep the current release in place while deciding that work. No threshold, play-up definition, rating solver or selection policy was changed or proposed as a demonstrated fix here.

## What was compared

One approved corrected-engine run from the October 12 read-only freeze, followed by two final-step replays on its exact pre-cap scores. The baseline uses the old pooled boys/girls cutoff references; the candidate uses references within each gender. Both use the same current cap-band function. Game selection, eligibility, earlier scores and ceiling categories are identical by construction. This is not a second full baseline engine run and not a fresh full A/A test.

Frozen engine source: `8319d7697f8218c5bb66404bec59c811dcd05106`; parent `62a74f704fd76933795aebb4bb5be1c2c2f55063`. The preserved baseline helper matches the parent's full calculator AST. Existing newest 30/365-day/minimum 10 rules, 155-day inactivity and production 30-step settings remain.

These are **current-input placement diagnostics**, not held-out prediction results. The authorized freeze includes games through October 12. Do not describe this as an untouched October confirmation. Earlier September findings and the separate September 30 historical sensitivity report remain unchanged; its 37,006/61,372 counts are not these results.

## Verification

All 176 frozen source files, runtime and frozen input hashes, engine completion/output hashes, 36 engine stage captures and 36 ML captures were verified. Newest 30 selection, selected outcomes, minimum 10 and 155-day inactivity were checked. Ceiling connectivity coverage and its private boundary passed. The corrected replay exactly matches actual true/scaled scores, cutoffs and canonical national ranks; repeated replay and separate-gender replays agree. All 18 boards have finite bounded scores and respect their score caps.

The engine completed at 23:04:44 UTC (4:04 PM Arizona). The original Windows offline-guard startup failure happened before ranking computation and is preserved. The approved retry used the same freeze; no additional engine run followed. A report-only capitalization assertion was repaired with the failed report log and script preserved.

**Upstream limitation:** 12 first-pass and 11 second-pass solves hit the existing 30-step limit without meeting the production mean-change criterion. U10 boys/girls both met that criterion in both passes. The cutoff comparison remains exact on these saved scores; the scores are not certified fully settled or calibrated. No solver tuning was performed.

Previously completed source checks remain applicable: 91 ceiling tests; full Python: 9,362 passes/15 skips with two missing-runtime failures, then 129 affected runtime/Windows tests passing after locked dependencies were installed (overlapping counts). Existing implementation and mutation reviews remain recorded. This delivery adds reports only; no full test or ranking batch was repeated.

## All 18 boards

61,058 ranked teams; 37,009 change national position, 24,605 move more than 100 places, 32,579 change final score and 60,745 change cutoff. Median absolute movement across all ranked teams is 40. Eligibility changes: 0. A score-category number such as 1800 or 2000 is **not a literal final-rank floor**.

| Board | Ranked | Rank changes | Median absolute move | >100 places | Thin flags in top 100, before→after | New top 100 |
|---|---:|---:|---:|---:|---:|---:|
| U10 girls | 1,317 | 1,294 | 89 | 625 | 1→1 | 8 |
| U10 boys | 2,514 | 2,037 | 89 | 1,165 | 3→3 | 0 |
| U11 girls | 3,152 | 2,097 | 119 | 1,649 | 4→5 | 9 |
| U11 boys | 5,801 | 2,233 | 0 | 1,488 | 5→5 | 9 |
| U12 girls | 3,210 | 2,127 | 121 | 1,665 | 1→1 | 13 |
| U12 boys | 5,857 | 2,254 | 0 | 1,540 | 4→5 | 6 |
| U13 girls | 3,279 | 2,144 | 93 | 1,622 | 1→0 | 13 |
| U13 boys | 5,711 | 2,247 | 0 | 1,352 | 1→2 | 1 |
| U14 girls | 3,072 | 2,101 | 96 | 1,511 | 0→0 | 18 |
| U14 boys | 5,054 | 2,233 | 0 | 1,460 | 1→1 | 7 |
| U15 girls | 2,613 | 2,068 | 154 | 1,530 | 1→1 | 12 |
| U15 boys | 4,172 | 2,182 | 4 | 1,289 | 1→1 | 4 |
| U16 girls | 2,078 | 1,982 | 199 | 1,440 | 0→1 | 13 |
| U16 boys | 3,293 | 2,129 | 59 | 1,239 | 1→2 | 2 |
| U17 girls | 1,697 | 1,662 | 311 | 1,207 | 0→0 | 20 |
| U17 boys | 2,653 | 2,084 | 90 | 1,117 | 0→0 | 3 |
| U19 girls | 2,260 | 2,015 | 167 | 1,418 | 0→0 | 20 |
| U19 boys | 3,325 | 2,120 | 46 | 1,288 | 0→0 | 4 |

U10 girls: 1,294/1,317 move; 625 move more than 100 places; largest move 1,033. U10 boys: 2,037/2,514 move; 1,165 move more than 100 places; largest move 1,486. Their median absolute move is 89 each. This preview does not establish a general U10 improvement.

## Placement review

The packet covers 2,022 teams, 56,106 full game rows, 48,991 selected rows and 45,881 opponent relationships. The focused appendix covers 355 cases including the canonical successor of a merged historical team. Reviewed all 32 old/new thin-flag top 100 placements (including top 25), 162 new top 100 entrants, 19 new top 25 entrants (179 distinct new high placements), 99 active teams satisfying the unchanged older-support predicate, 26 historical flags and 16 named cases. Full schedules and selected-game membership are preserved; references and WDL were reconstructed, not inferred from final opponent ranks.

The thin flag means zero same-age raw-reference top 100 opponents and at most two top 500 opponents; it does not label a team isolated or incorrectly ranked. Top 100 flags go 24→28 and top 25 flags 4→5. Eight enter the flagged top 100 set and four leave. All eight entrants have qualifying older-opponent support. Their games deserve credit; fewer flags would not by itself establish quality.

All 162 new top 100 entrants have at least one selected same-age or older raw-reference top 500 non-loss. That is supporting evidence, not independent certification: raw and final references are outputs of this same model. An additional 47 existing top 100 teams have no such selected result; 46 also lack one in the full saved window, while Nevada FC 14/15G has qualifying earlier same-age wins excluded from the newest 30 games. These are unresolved screens, not 47 proven errors. Their actual best results and losses were reviewed and remain in the appendix and full packet.

### Older-opponent support can still lose priority

The support predicate itself stays unchanged for all 99 active qualifying teams. Tracing the existing cap function shows the early play-up relief applies when connectivity is constrained. A well-connected team with little same-age evidence can instead hit later severe same-age rules. The cutoff correction lowers the resulting score ceiling further. This pre-existing interaction conflicts with the goal of protecting legitimately supported play-up teams.

| Team | Board | National before→after | Positive selected older evidence |
|---|---|---:|---|
| Utah Royals FC-AZ ECNL 2011 | U15 girls | 672→1,155 | 1-0 win versus raw-reference 60; draws versus 88 and 92 |
| 2010 GA (`986655d3…`) | U16 girls | 717→1,197 | draw versus 43; draw versus 141; win versus 239 |
| WVFC 2010 Black | U16 boys | 682→1,039 | 3-1 win versus 64; draws versus 67 and 72 |
| SLSG Navy ECNL G2013/14 | U13 girls | 274→451 | draws versus 80 and 81 |
| Charlotte Independence 2013 GA | U13 girls | 141→260 | draw versus 69; win versus 139 |
| St. Louis Development Academy 2011 GA | U15 girls | 190→327 | win versus 72; draw versus 202 |
| Midwest United ECNL 2011 | U15 girls | 163→269 | wins versus 31 and 116 |
| San Antonio City 10GA | U16 girls | 176→309 | draw versus 180; win versus 212 |

These results do not establish an exact deserved rank, but they are positive evidence against treating these schedules as untested. The biggest three receive category 2000 through the same-age evidence cascade despite `has_play_up_support=true`. No hypothetical remedy was applied or scored.

### Specific remaining concerns

- **Pizzicata:** 7W2L1D and the 5-4 CCV win are retained. CCV is raw-reference 1056 on this freeze, versus inside 1000 in the prior live audit; current category is 2000. The previous live ranking was national #358/AZ #4 and used different inputs. The correction-only comparison on this freeze is national #615→#958 and AZ #6→#17. BRUSA remains unranked with four games in one weekend, two against Pizzicata, but has internal rating 1896.15 / RD 92.99. Thin-opponent credit is a concern, not demonstrated causal attribution.
- **Surf Azzurri:** 71→26 nationally and PA #4→PA #1, despite unchanged own score. Current older support qualifies: selected draws against Cohansey raw 315 and FUTBOLTECH raw 497. The earlier failed support finding used different inputs. Preserve these results; near-cutoff evidence and other teams falling do not establish PA #1.
- **G Varsity Wildcats:** 165→80 even though its final score falls from 0.608011 to 0.602982 under the cap-band remapping. Its record is 3W2D5L in ten games. A draw against raw-reference 100 Surge earns the existing 250 category. Its tiny two-hop neighborhood prompted a graph check, but it belongs to a 55,558-team same-gender connected component. It is **not demonstrated disconnected**. Connection to the graph and one internally ranked opponent also do not establish national 80.
- **New Hampshire Rapids:** 27→29 with no same-age raw 500 non-loss. Its one raw 100 encounter was a 3-5 loss; positive results include wins against raw 569 and 838, plus younger teams. Existing 400 score category still permits national 29. The cutoff correction does not resolve this concern.
- **California in-state control:** CVFA U12G stays 16→17 nationally and CA #8. Selected win versus raw 13, draw versus 31 and win versus 87 support a high placement without travel. Geography alone is not a reason to demote it.
- **North Carolina U17 girls:** 102→122; 19 U19 games still excluded by the existing exact+1-year support definition. **Wyoming U14 girls:** 30→35; older results remain positive even though average opponent power 0.565 falls below 0.58. Neither definition nor threshold changed.

## Named-case inventory

| Case | Team | Status | National before→after | Last saved game |
|---|---|---|---:|---|
| California U10 boys exposure-only case | 16/17B BLACK | Active | 548→636 | 2026-10-03 |
| Surf Azzurri U10 boys | Philadelphia SC Surf 2016 Azzurri | Active | 71→26 | 2026-09-19 |
| FC Europa U10 boys | FCE U10 Boys Pre ECNL | Active | 287→375 | 2026-10-04 |
| Delco U10 boys | Black Conshy '16/'17 (B) * | Active | 26→30 | 2026-10-10 |
| Texas U11 girls control | Texoma Youth Soccer Association - Sherman Attitude 2016 | Inactive | unranked→unranked | 2026-05-09 |
| Pizzicata F.C. | Pizzicata F.C. | Active | 615→958 | 2026-08-09 |
| BRUSA Martins Black | BRUSA FC 2015/2016 Martins Black | Not Enough Ranked Games | unranked→unranked | 2026-08-09 |
| California in-state U12 girls | CVFA U12G Academy | Active | 16→17 | 2026-10-04 |
| California U13 girls control | Beach FC (CA) G2014 SB Souza | Inactive | unranked→unranked | 2026-03-14 |
| original Washington U13 girls | 3RSC G14 Copa Wright | Inactive | unranked→unranked | 2026-05-08 |
| California U13 girls younger-heavy | GU11 HB Koge Pre-ECNL | Active | 277→454 | 2026-10-10 |
| original Texas U13 boys | Lion Kings FC 2013/2014 | Inactive | unranked→unranked | 2026-03-15 |
| Wyoming U14 girls | Blades 2012/13G Red | Active | 30→35 | 2026-06-22 |
| Pennsylvania U16 boys | Hulmeville N1 B2010/2011 Demons (PA) | Active | 59→61 | 2026-07-26 |
| New Hampshire U16 boys | Rapids U15 Boys | Active | 27→29 | 2026-06-14 |
| North Carolina U17 girls | Charlotte Independence SC - 2009 GA Charlotte Independence Soccer Club | Active | 102→122 | 2026-10-04 |

The original TX/WA cases and the TX U11/CA U13 girls controls are currently inactive. Their absence is not evidence that the cutoff correction fixed prior placement problems. The merged historical flag `1610353d…` resolves through the frozen merge map to `c72e8817…`, national 476→564; it was not dropped from review.

## Evidence and completion

[Machine-readable review and hashes](2026-10-12-ceiling-current-evidence.json) and [focused case appendix](2026-10-12-ceiling-current-cases.json) are committed with this report. The local evidence directory is `C:\PitchRank\.turbo\ceiling-preview-20261012\report-v1`; its immutable generated receipts retain `human_review_complete=false` because those stages were only data generation. The separate completed-review receipt records the reviewed recommendation and binds their hashes. Full parquet schedules, opponent relationships, failed-launch evidence and historical reports are preserved locally.

Supplemental display names were fetched read-only and saved separately; they never entered frozen ranking inputs. No games were refreshed after the authorized freeze. No ranking source changed during validation. Report-only syntax, document consistency and evidence checks complete this delivery; no new changelog entry is warranted for a report-only commit.

**Review complete; publication held.** The immediate next work should be one focused ceiling-policy decision addressing these demonstrated conflicts, with preservation of older-opponent and strong in-state evidence. That would require a separate implementation decision. This report authorizes no new run, redesign, merge or publication.
