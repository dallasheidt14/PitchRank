# Ceiling restriction order: implementation and frozen replay

**The confirmed rule-order defect is fixed locally.** A stale or lightly active schedule no longer receives a mild ceiling instead of a stricter applicable evidence restriction. In the frozen diagnostic replay, the Texas U13 example falls from #99 to #537 and the Washington U13 example from #55 to #313.

This is a separate change on `codex/ceiling-restriction-order`, based on C1 commit `e0ccc2c04495c74a167c735e339cb72761a2ccc2`. The original October candidate and C1 reference are unchanged. Nothing has been pushed, merged, deployed, or locked for holdout evaluation.

## Behavior changed

Previously, either of two checks returned ceiling depth 400 immediately: too few recent games, or a stale schedule. Stronger weak-results and regional restrictions later in the function were therefore skipped.

The change retains the existing freshness restriction while allowing the subsequent evidence decision to impose a stricter ceiling. If that decision would allow depth 250 or no ceiling, the freshness limit still applies. Explicit earlier relief for supported play-up schedules and strong broad evidence remains in its existing place. No thresholds, opponent-strength definitions, game selection, upstream ratings, or score-band calculations changed.

Only `_publication_cap_rank` changes in the engine. This is not a general rewrite that chooses the strictest of every rule, and it does not make a ceiling depth into a guaranteed final rank.

## Measured effects

Comparison: **C1 plus the rule-order fix versus C1**, using the same saved August 31, 2026 inputs and scores before ceilings. Every position below is within age and gender among Active teams.

| Case | C1 | C1 plus fix | Ceiling depth |
| --- | ---: | ---: | --- |
| Texas U13 boys, `8f77aa25` | 99 | 537 | 400 → 1,800 |
| Washington U13 girls, `5cbbc1e9` | 55 | 313 | 400 → 1,800 |
| California U11 boys, `3fbafa0b` | 937 | 910 | Remains 2,000 |
| Florida U16 boys, `2f6b6e08` | 877 | 864 | Remains 2,000 |
| California U12 girls control, `7e411cad` | 51 | 51 | Remains 400 |
| California U10 girls with play-up support, `844c94a5` | 6 | 6 | Remains 250 |

Unchanged ceilings can still have changed positions because other teams move. This is why checking only a team's assigned ceiling is insufficient.

Across 60,640 Active teams on all 18 boards:

- 3,194 teams receive stricter ceilings; none receives a looser ceiling.
- 17,893 positions change; 466 teams move more than 300 places.
- 63 teams leave a top 100. No team leaves a top 25.
- No team whose ceiling changes has an increased final unanchored score.
- Game selection, team eligibility, and the 12-game minimum are unchanged. No games are removed or added by this change, and no team crosses the publication minimum because of it.

Across all 138,774 stored team rows, including non-Active teams, 23,722 ceiling depths change: 15,161 from 400 to 1,800; 7,199 to 1,500; 1,232 to 2,000; 103 to 800; and 27 to 1,000.

## Review of actual top positions

The existing descriptive screen is unchanged: incumbent isolation flag, no top-100 same-age opponents, at most two top-500 same-age opponents, and at most one top-500 same-age opponent against which the team has a win or draw. These are model-derived review flags, not proof of weakness and not an adoption rule.

The flagged top-100 count falls from **53 to 23**. All 29 teams from the original review list that remained in C1's top 100 without qualifying play-up support now leave it. Of the original 79 cases, 11 remain; all have qualifying play-up support. The flagged top-25 count remains six.

Every one of the 23 currently flagged top-100 teams qualifies for the existing play-up exception. I recomputed their play-up evidence from the frozen games and reproduced their recorded counts exactly. All have at least one credited older opponent still in its own top 500 after ceilings, but support varies:

- The California U10 girls team now at #1 has four credited older top-500 opponents; three remain top 500 after ceilings, and two have at least three top-100 same-age opponents themselves.
- The New York U12 boys team at #21 has eight such older opponents; all eight remain top 500 and five have at least three top-100 same-age opponents.
- The Arizona U10 boys team at #7 has three credited older opponents, but only one remains top 500 after ceilings; two have no top-100 same-age opponents themselves.

These descriptions identify stronger and thinner supporting schedules; they do not independently establish how strong those teams are. Removing play-up relief wholesale would discard real competitive evidence. Its adequacy is a separate question requiring a separate design and validation. The score-ceiling versus final-position gap and the pooled boys/girls ceiling reference also remain unchanged.

## Verification and limits

- 204 focused and related ranking tests pass, including 22 new regression cases. They cover both escape paths, retention of the freshness limit, supported play-up relief, all nine age policies, existing evidence gates, C1 isolation, eligibility, and publication contracts.
- Three in-memory mutations each fail the new tests: restoring the low-volume early return fails nine cases; restoring the stale early return fails nine; deleting the freshness floor fails two. Measured source files were never changed for these probes.
- Repository Python lint and lint of the new tests pass; the diff has no whitespace errors.
- The repeated C1 diagnostic replay matches the prior replay's scores, ceiling depths, ceiling scores, and ranks exactly.
- Input and output hashes are verified. All saved frame columns other than ceiling depth, ceiling score, and final unanchored score match exactly between the two replays. A source-structure check confirms that `_publication_cap_rank` is the only changed top-level engine definition.
- This turn ran the 204 relevant checks, not another full repository suite. The earlier full-suite baseline failures remain documented separately.

**This is a diagnostic replay of the ceiling stage, not a completed end-to-end C1 validation or evidence of improved predictive accuracy.** The earlier full validation was interrupted and remains unfinished. September supplied design evidence; no October outcomes were fetched or examined. Any holdout comparison for this new candidate must be specified and locked before inspecting that period's outcomes. These results do not authorize production adoption.

## Next decision

The demonstrated precedence fix is ready for code review as its own change. Complete the end-to-end reference/candidate validation before adopting it. Keep the 23 play-up cases in the top-placement review, with attention to the strength and connectivity of their credited older opponents. A broader elite-placement rule or percentile ceiling retune remains a separate candidate; neither is silently included here.

Evidence: `C:\Users\Dallas Heidt\AppData\Local\Temp\pitchrank-ceiling-order-20261005` contains per-age reference and candidate replay outputs, `comparison.json`, `movement.csv`, the original and remaining review queues, the play-up opponent audit, test receipts, and reproducible replay/comparison scripts. The original frozen snapshot and October-candidate artifacts remain untouched.
