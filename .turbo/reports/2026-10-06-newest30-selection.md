# Newest 30 games within 365 days — selection impact

> Later owner decision: use a 10-game minimum. The original 12-game measurement below remains historical. See [the 10-game eligibility addendum](2026-10-06-minimum10-eligibility.md) for the approved policy and revised counts.

Implemented October 6, 2026 on a separate branch from `2aef9e0b2`. No live rankings changed.

## Policy and concrete behavior

Use each team's newest 30 valid games within 365 days. Sort by date, with stable IDs for same-date ties. Do not reserve places for older wins, strong opponents, travel or league membership. Remove the default 28-day grace period. Keep the 12-game minimum, inactivity rule, existing valid-game/exclusion/merge handling and the full-window record reconciliation unchanged.

The old balanced selector remains explicitly opt-in for historical comparisons; the production default is newest-only. Selection and full-window record use the same lower and upper date bounds. The engine cache is versioned and includes policy, game limit, window/grace and calculation timestamp. Both rating passes and the ML input receive the selected games.

## Measured impact on saved August 31 inputs

This is an exact selection replay against the completed release in PR #1255. The actual candidate selector was called for every team and checked against an independent date/ID oracle. It is not a new full rankings run and does not measure final ranking movement or prediction improvement.

- Narrowing the saved fetch window from 393 to 365 days removes **47,244 distinct games** (94,488 team perspectives), touching 34,069 teams. It adds no fetched games.
- Across the archived 138,774-team universe, selections change for **36,530 teams**, including **26,514 of 60,640 Active teams**.
- Selected perspectives: 1,743,839 before; 101,450 removed and 34,602 added; **1,676,991 after**. A perspective is one team's use of a game, so the same match can be retained by one opponent and dropped by the other.
- Removed perspectives involve 67,838 distinct games; added perspectives involve 33,599. These sets can overlap across opponents. **48,227 counterpart teams** appear on changed perspectives; that is not a count of changed rankings.
- **1,463 teams cross below 12 games; zero cross upward. Of those, 1,095 were Active and would lose eligibility.** The remaining 368 were already Inactive.
- **2,730 teams reach zero selected games. All were already Inactive**, with no games in the new window; none is an unexpected recent-team deletion.
- The eligibility losses include **3 former top-25 teams and 11 former top-100 teams**. These are consequences of removing expired games, not proof those teams were weak.

| Board | Active selections changed | Cross below 12 | Active teams losing eligibility |
|---|---:|---:|---:|
| U10 female | 274 | 35 | 31 |
| U10 male | 427 | 43 | 35 |
| U11 female | 1,362 | 80 | 71 |
| U11 male | 2,470 | 103 | 73 |
| U12 female | 1,634 | 60 | 53 |
| U12 male | 2,933 | 145 | 112 |
| U13 female | 1,755 | 87 | 66 |
| U13 male | 2,947 | 143 | 122 |
| U14 female | 1,622 | 72 | 61 |
| U14 male | 2,516 | 128 | 104 |
| U15 female | 1,520 | 74 | 50 |
| U15 male | 2,299 | 101 | 71 |
| U16 female | 927 | 99 | 64 |
| U16 male | 1,442 | 103 | 66 |
| U17 female | 439 | 46 | 31 |
| U17 male | 621 | 43 | 29 |
| U19 female | 616 | 51 | 27 |
| U19 male | 710 | 50 | 29 |

## Every former top-100 eligibility loss

Ranks are from the saved release; no candidate rank is assigned to an ineligible team.

| Board | Previous rank | Games before → after | Team ID |
|---|---:|---:|---|
| U10 female | 7 | 13 → 9 | `ace679f8-3d9a-4c86-a587-03202537fa4b` |
| U10 female | 11 | 13 → 11 | `1c69dc93-7575-4c57-badc-7884141ce40e` |
| U10 female | 13 | 12 → 8 | `be8aaf62-accf-4c40-8fea-0d90d892494c` |
| U10 female | 43 | 12 → 11 | `ed352161-9fc8-47be-8b0d-6f123eb00352` |
| U10 female | 66 | 14 → 10 | `31c414a1-4dbb-492d-abde-dda7f0297c12` |
| U11 female | 93 | 13 → 11 | `18953f3f-5f43-45ae-9222-f4f8786f4181` |
| U13 female | 35 | 14 → 10 | `098a9210-4d7a-4c22-997f-f251d17d26e7` |
| U13 female | 87 | 14 → 6 | `138021e2-dcbf-42b6-9fe9-e4768a9b72c7` |
| U13 male | 34 | 13 → 8 | `9498f76a-4dfd-43a8-aaa7-87b923718646` |
| U14 female | 86 | 22 → 11 | `48562ef5-d082-41dc-9b7c-83c51289514d` |
| U16 male | 63 | 14 → 11 | `8c9578f5-6b80-4cc8-82e7-b6acce420c49` |

## Correctness checks and review

- 458 ranking unit/integration regressions pass (452 unit and 6 pipeline tests), including production fetch/ML handoff, both engine passes, eligibility, 365-day endpoints, future-date exclusion, stable ties, no result/opponent/state/league preference and cache invalidation. Existing legacy-mode tests opt into their old policy explicitly.
- Repository Python lint and whitespace checks pass. Pre-push source review traced the old selection preference and the normal command through fetch, both passes, downstream selected-game reuse, eligibility and cache handling. No new score formulas, PowerScore clamp changes or ML time-split changes are introduced.
- The live-only `diagnose_ranking.py` command was not rerun: the recorded diagnosis is the selector path itself, and this is the owner's explicit game-selection policy. Running that command now would fetch current game outcomes, which this task does not need.
- A separate assistant review pass over the final changed files found no implementation blocker; it is not an independent external approval. Current-head GitHub checks/review are recorded on the PR.

The initial full Linux suite found one stale SOS assertion: its reference average included
future fixtures from the synthetic schedule while the new selector correctly excluded
them. The reference now uses selected games and explicitly requires no future rows;
the original correlation threshold remains unchanged. All six pipeline tests and the
13 newest-selection regressions pass. This follow-up changes tests/reporting only;
the audited engine files and all selection counts remain unchanged.

## Evidence and limits

[Machine-readable counts, hashes and all 11 cases](2026-10-06-newest30-selection-evidence.json) · [Replay script](2026-10-06-newest30-selection-audit.py). The completed receipt and per-team/added/removed/selected Parquet files remain at:

`C:\Users\Dallas Heidt\AppData\Local\Temp\pitchrank-newest30-20261006-selection`

The audit validates the saved game hash, baseline games-played counts, every selected team/game list, all 18 boards, arithmetic reconciliation and unchanged candidate source hashes. The existing freeze reports zero deprecated-ID merge drift. It cannot establish current database coverage or later merge changes.

The fetch change is measured at the saved input: the same resolved August rows filtered to the 365-day lower bound. The normal fetch call is covered by the integration test. No new production fetch, October outcome access, full ranking calculation or publication occurred.

Changing selected opponents can also change SOS, connectivity and other teams' scores. Final placement movement for this policy is not measured here. The September +2.33-point result and movement in PR #1255 belong to that unchanged package and must not be attributed to this separate change or their combination. The new selector has not been published.

Publication still requires explicit owner approval, rollback records and verification of stored rankings. Broader ceiling redesign and extra calculation rounds are outside this change.
