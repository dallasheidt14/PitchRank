# Combined ceiling corrections — saved-ranking review, 2026-10-12

**Recommendation: advance the boys/girls cutoff correction and older-opponent exception fix together for code review.** Both are targeted corrections to existing rules. The saved-data comparison supports restoring the exception for qualifying teams; it does not establish every resulting placement or solve all weak-schedule high rankings. Neither fix has been merged or published by this work.

The older-opponent fix changes the ceiling category for **27 ranked teams**, all of which already meet the unchanged support requirements. It corrects the eight previously identified cases without undoing Pizzicata's lower placement. Twenty-six of these teams gain score and rank; one keeps the same score and moves down three positions because other teams rise.

## Fixed behavior and boundaries

The original evidence-ceiling decision is preserved. If that decision imposes a stricter category than the existing soft category 250, the existing older-opponent support predicate can soften it to 250. Teams already uncapped or entitled to a softer category retain that treatment. Teams that do not qualify receive no new exception.

Qualification still requires at least 40% play-up games, two distinct top-500 and four distinct top-1000 older non-loss opponents, and mean older-opponent power at least 0.58. These are the engine's raw references, not final published ranks or independent ground truth. The existing full-window evidence calculation and exact one-year-older definition remain unchanged; U17-to-U19 support remains outside that definition. No thresholds, game selection, eligibility, earlier penalties, rating/ML scores or numerical stopping settings changed.

The wrapper retains all existing restriction logic under `_publication_evidence_cap_rank`; an AST comparison confirms the rest of the calculator is unchanged. Of 99 active teams satisfying the support predicate, 94 now have category 250 and five remain uncapped. Only 27 categories change. Category numbers are **score restrictions, not literal national rank floors**.

## Comparison and reproducibility

Three views use the same October 12 frozen pre-ceiling scores: original pooled-gender cutoffs; corrected gender-specific cutoffs alone; both corrections together. The old and corrected cutoff helpers and the actual new support wrapper were executed against preserved stage frames and private ceiling connectivity. This task ran zero full ranking calculations, fetched zero games and performed zero production writes.

The gender-only replay reproduces the completed engine and previous report exactly. The original source, input and completion hashes remain intact; the other 175 frozen source files match. Runtime matches Python 3.13.6, pandas 2.3.3, numpy 2.2.6, XGBoost 3.1.2 and scikit-learn 1.7.1. All 18 boards have finite bounded scores, respected caps, exact repeated final-step replay and gender independence. Saved selection, outcomes, eligibility and pre-ceiling scores are preserved by construction. This is not a fresh full A/A or rating-convergence test.

Prior verified engine source: `8319d7697f8218c5bb66404bec59c811dcd05106`. Branch base: `41d908df912dbc0419ab6ddb9cc331adb31756d2`. Exact implementation and evidence hashes are in the companion evidence JSON. Frozen manifest SHA256: `cd96fb5f2df7d2b70b8268c2c2f74b0f58593be71b11d53aa66203bb6da1b27e`.

The saved engine's upstream limitation remains: 12 first-pass and 11 second-pass solves reached the production 30-step limit without meeting its convergence criterion. U10 boys and girls met that criterion in both passes. This comparison isolates final ceilings on those saved scores; it does not certify a fully settled rating solution. Historical September reports remain unchanged.

## Movement across all 18 boards

Out of 61,058 ranked teams, adding the older-opponent fix to gender-only changes **4,561 ranks** and **5,150 final scores**. Only 27 ceiling categories change; the existing score-band remapping changes scores for 5,124 other teams as well. Eleven teams move more than 100 places, all with changed categories. Other teams move down by at most five places. Eligibility changes: zero.

Both corrections versus original pooled cutoffs change **37,053 ranks** and **32,580 scores**; 24,651 teams move more than 100 places. Median absolute rank movement is 40. These are distinct from the prior correction-only counts.

| Board | Ranked | Categories changed by older fix | Rank changes vs gender-only | Rank changes vs original | >100 places vs original | Thin top-100 flags: original → gender-only → combined |
|---|---:|---:|---:|---:|---:|---:|
| U10 girls | 1,317 | 2 | 44 | 1,304 | 625 | 1 → 1 → 1 |
| U10 boys | 2,514 | 1 | 30 | 2,058 | 1,165 | 3 → 3 → 3 |
| U11 girls | 3,152 | 2 | 43 | 2,107 | 1,649 | 4 → 5 → 5 |
| U11 boys | 5,801 | 0 | 0 | 2,233 | 1,488 | 5 → 5 → 5 |
| U12 girls | 3,210 | 1 | 53 | 2,128 | 1,665 | 1 → 1 → 1 |
| U12 boys | 5,857 | 3 | 368 | 2,269 | 1,542 | 4 → 5 → 7 |
| U13 girls | 3,279 | 5 | 448 | 2,142 | 1,620 | 1 → 0 → 0 |
| U13 boys | 5,711 | 0 | 0 | 2,247 | 1,352 | 1 → 2 → 2 |
| U14 girls | 3,072 | 2 | 225 | 2,099 | 1,512 | 0 → 0 → 1 |
| U14 boys | 5,054 | 0 | 0 | 2,233 | 1,460 | 1 → 1 → 1 |
| U15 girls | 2,613 | 5 | 1,132 | 2,062 | 1,530 | 1 → 1 → 2 |
| U15 boys | 4,172 | 0 | 0 | 2,182 | 1,289 | 1 → 1 → 1 |
| U16 girls | 2,078 | 4 | 1,147 | 1,979 | 1,439 | 0 → 1 → 2 |
| U16 boys | 3,293 | 2 | 1,071 | 2,129 | 1,285 | 1 → 2 → 3 |
| U17 girls | 1,697 | 0 | 0 | 1,662 | 1,207 | 0 → 0 → 0 |
| U17 boys | 2,653 | 0 | 0 | 2,084 | 1,117 | 0 → 0 → 0 |
| U19 girls | 2,260 | 0 | 0 | 2,015 | 1,418 | 0 → 0 → 0 |
| U19 boys | 3,325 | 0 | 0 | 2,120 | 1,288 | 0 → 0 → 0 |

U10 girls: the older fix changes two categories and 44 ranks, maximum 39 places; U10 boys: one category and 30 ranks, maximum 29 places. Neither U10 board has an additional move over 100 places from this fix. The combined comparison still has the much larger gender-cutoff movement; this is not evidence that all U10 placements are right.

## Every changed category

National positions below are three saved-score alternatives, **not live-site before/after numbers**.

| Team | Board | Category | Original | Gender-only | Combined |
|---|---|---:|---:|---:|---:|
| DKSC PRE-ECNL G2016/17 Chavez | U10 girls | 400 → 250 | 26 | 46 | 7 |
| G2016/17 Black | U10 girls | 400 → 250 | 21 | 40 | 4 |
| Tuzos Academy GTA BU10 | U10 boys | 400 → 250 | 29 | 33 | 4 |
| PreECNL 2015 | U11 girls | 400 → 250 | 40 | 56 | 17 |
| GTFC Impact 2015 Premier PRE ECNL G15 | U11 girls | 400 → 250 | 35 | 52 | 16 |
| SYC 2015 Pre-GA | U12 girls | 400 → 250 | 75 | 91 | 41 |
| Pipeline SC PreECNL 2014 | U12 boys | 1,500 → 250 | 287 | 360 | 45 |
| Central 2014 B Academy 1 | U12 boys | 800 → 250 | 193 | 238 | 57 |
| Philadelphia Union Juniors U12 2014 | U12 boys | 400 → 250 | 48 | 57 | 10 |
| SJEB FC - 2013 GA | U13 girls | 400 → 250 | 53 | 67 | 25 |
| SLAMMERS FC PRE-ECNL 2014 | U13 girls | 400 → 250 | 46 | 59 | 17 |
| SLSG Navy ECNL G2013/14 | U13 girls | 1,800 → 250 | 274 | 451 | 24 |
| New York City FC - 2013 Aspire | U13 girls | 400 → 250 | 72 | 85 | 33 |
| Charlotte Independence SC - 2013 GA Charlotte Independence Soccer Club | U13 girls | 800 → 250 | 141 | 260 | 43 |
| Midwest United - 2012 GA | U14 girls | 800 → 250 | 160 | 254 | 44 |
| SJEB FC - 2012 GA | U14 girls | 400 → 250 | 131 | 146 | 82 |
| Utah Royals FC-AZ ECNL 2011 | U15 girls | 2,000 → 250 | 672 | 1,155 | 189 |
| St. Louis Development Academy - 2011 GA | U15 girls | 1,000 → 250 | 190 | 327 | 46 |
| SC Del Sol GA | U15 girls | 400 → 250 | 76 | 91 | 48 |
| Midwest United FC ECNL 2011 | U15 girls | 800 → 250 | 163 | 269 | 56 |
| SJEB FC - 2011 GA | U15 girls | 400 → 250 | 229 | 217 | 220 |
| ECNL 2010 | U16 girls | 400 → 250 | 69 | 84 | 41 |
| SJEB FC - 2010 GA | U16 girls | 400 → 250 | 72 | 87 | 44 |
| 2010 GA | U16 girls | 2,000 → 250 | 717 | 1,197 | 237 |
| San Antonio City SC - SA City SC 10GA | U16 girls | 800 → 250 | 176 | 309 | 59 |
| WVFC 2010 - Black | U16 boys | 2,000 → 250 | 682 | 1,039 | 21 |
| Pipeline SC ECNL 2010 | U16 boys | 400 → 250 | 52 | 54 | 14 |

The previously identified severe cases now retain older evidence: Utah Royals 1,155 → 189, 2010 GA 1,197 → 237, and WVFC 1,039 → 21 relative to gender-only. Their selected schedules include positive results against older raw-reference 60/88/92, 43/141/239 and 64/67/72 respectively. These are reasons to remove an inconsistent severe restriction, not evidence for those exact final ranks.

SJEB 2011 GA is the exception to a rank improvement: category 400 → 250, unchanged own score, rank 217 → 220 as other teams rise. That outcome is preserved rather than described as a scoring loss.

## Placement review and remaining uncertainty

The companion case appendix updates 354 directly represented cases plus the preserved merged historical case. It reuses the previously reviewed, hash-bound schedules, selected-game membership and opponent links; no evidence was refreshed. Coverage includes all 38 old/new flagged high placements across the three views, 193 distinct new top-25/top-100 entrants relative to original, all 99 active older-support teams, all 27 changed categories and all named cases. The review rechecks positive results, losses and outside-opponent links for the affected promotions. The full packet contains 2,022 teams, 56,106 game rows and 45,881 opponent relationships.

Relative to gender-only, ten teams enter the top 100 and eleven enter the top 25, overlapping into 19 teams. Every one has a changed category and qualifies under the existing older-support rule. Examples warranting caution include G2016/17 Black and Tuzos rising to national U10 #4, and WVFC rising to U16 #21. Black has ten wins including same-age raw100 and older raw196; Tuzos has a win over same-age raw54 but also losses against older raw505/1535. WVFC has eight distinct older raw500 non-loss opponents, including a win over64 and draws with67/72. These schedules contain support; these rank magnitudes are not independently certified.

The unchanged evidence policy uses the full frozen window, while the rating selects the newest 30 games. This materially affects Tuzos: all three older raw-top500 non-loss opponents are outside its selected 30 (a 1-1 draw with raw94 on November 28, 2025, a 4-3 win over raw177 on December 5, and a 4-2 win over raw406 on December 7). Its selected 30 contain zero older raw-top500 non-loss opponents. Restoring relief under that existing rule moves Tuzos from33 to4; that magnitude remains unverified. Central 2014 B Academy1 qualifies with two older raw500 non-loss opponents in that window but only one among the selected 30. That existing distinction is explicit in the appendix; neither selection nor support counting was changed here.

The thin-same-age flag means zero raw top100 opponents and at most two raw top500 opponents. Top100 flags go 24 → 28 → 34; top25 flags go 4 → 5 → 7. All six additional flagged top100 teams versus gender-only have qualifying older support. A flag is not proof of isolation or incorrect placement, and lowering the count is not the objective. Forty-seven combined top100 teams still lack a selected same-age/older raw500 non-loss; this existing unresolved screen is unchanged in count.

- **Pizzicata:** original national615/AZ6 → combined958/AZ17; adding the older fix changes neither its score nor placement. It has no qualifying older support. The 5-4 CCV win remains. The prior live358/AZ4 used different inputs and must not be substituted for this baseline. BRUSA stays unranked with four games; whether its thin rating credit inflates Pizzicata remains unproved.
- **Surf Azzurri:** original71/PA4 → gender-only26/PA1 → combined27/PA1. Qualifying draws against older raw315 and497 remain credited. The fix does not establish PA1.
- **Europa/Delco:** Europa remains375/PA21 after gender-only; Delco moves30 → 31 and remainsPA3 as Tuzos rises. No desired placement was fitted.
- **California in-state control:** remains national17/CA8 after gender-only, with strong same-age results retained. In-state geography alone is not penalized.
- **New Hampshire Rapids:** gender-only29 → combined31, stillNH1; its unchanged category400 permits a high placement without a same-age raw500 non-loss. This remains unresolved.
- **Wildcats:** stays80 after gender-only, with its positive raw100 draw retained. Prior graph evidence does not show a disconnected schedule; that does not certify national80.
- **North Carolina U17 / Wyoming U14 girls:** remain122 and35 after gender-only. The two-year older definition issue and Wyoming's mean older power below0.58 are unchanged.
- **Original Texas/Washington and two supported controls:** remain inactive or below the minimum-game requirement on this freeze; no new rank is assigned.

## Tests and review

The new regression suite produced 20 failures and 11 passes before the fix. With the fix, the 216-test affected suite passes; it covers all 18 age/gender combinations, each existing support requirement, missing evidence, preservation of uncapped teams and the real private-connectivity entry point without shared-row mutation. Python lint and diff checks pass. Six internal review dimensions found no actionable findings; external code transfer remains waived.

Full Python verification: 9,286 passed, 110 shell-runtime failures and 14 skipped. All 112 shell-hook tests passed after selecting Git Bash (two overlap with original passes), giving 9,396 unique passing tests after the recheck. Full logs and their hashes are in the companion validation receipt. The initial full run's only failures were shell-hook tests invoking WSL bash on Windows paths; the actual traces identify that runtime mismatch. Frontend and CI inputs are unchanged from the already verified base and are reused. No production workflow, new full engine run, UI publication check or independent ranking-quality confirmation is claimed.

The code, tests and this evidence form one focused correction. The recommendation is to review both fixes together; remaining weak-schedule placement policy is separate work requiring a separate decision.
