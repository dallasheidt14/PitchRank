# Approved 10-game minimum: eligibility impact

The owner approved 10 games on October 6, 2026. Newest-30/365 selection stays fixed. The earlier 12-game report is historical; this addendum supersedes only its minimum-game policy and eligibility projection.

## Saved August 31 snapshot

Of the 1,095 previously ranked teams that fell below 12 after expired games were removed, **786 remain eligible at 10** and **309 still fall out**. Of the 504 with a game in the prior 60 days, 319 are restored and 185 still fall out.

Another **5,057 previously unranked teams** qualify, including 1,345 with a game in the prior 60 days. Eligibility rises from 60,640 to **65,388**: 60,640 - 309 + 5,057. These are archived-data eligibility counts, not completed candidate ranks or current production counts.

## All 18 boards

| Board | Previously ranked | Restored from 12-game losses | Still leave | Newly eligible | Eligible at 10 |
|---|---:|---:|---:|---:|---:|
| U10 female | 833 | 25 | 6 | 219 | 1,046 |
| U10 male | 1,523 | 21 | 14 | 391 | 1,900 |
| U11 female | 2,942 | 47 | 24 | 302 | 3,220 |
| U11 male | 5,381 | 43 | 30 | 545 | 5,896 |
| U12 female | 3,187 | 36 | 17 | 176 | 3,346 |
| U12 male | 5,830 | 84 | 28 | 324 | 6,126 |
| U13 female | 3,388 | 43 | 23 | 188 | 3,553 |
| U13 male | 5,887 | 79 | 43 | 375 | 6,219 |
| U14 female | 3,108 | 46 | 15 | 152 | 3,245 |
| U14 male | 5,202 | 74 | 30 | 236 | 5,408 |
| U15 female | 2,898 | 34 | 16 | 126 | 3,008 |
| U15 male | 4,635 | 51 | 20 | 254 | 4,869 |
| U16 female | 2,159 | 56 | 8 | 149 | 2,300 |
| U16 male | 3,548 | 50 | 16 | 288 | 3,820 |
| U17 female | 1,639 | 28 | 3 | 164 | 1,800 |
| U17 male | 2,688 | 20 | 9 | 299 | 2,978 |
| U19 female | 2,312 | 23 | 4 | 337 | 2,645 |
| U19 male | 3,480 | 26 | 3 | 532 | 4,009 |

## Previously top-100 teams affected by the 12-game cutoff

These are archived baseline positions, not new positions. Qualifying for a rank does not establish support for a high placement.

| Team ID | Board | Old rank | Games in new window | Eligible at 10 |
|---|---|---:|---:|---|
| 31c414a1-4dbb-492d-abde-dda7f0297c12 | U10 female | 66 | 10 | Yes |
| ace679f8-3d9a-4c86-a587-03202537fa4b | U10 female | 7 | 9 | No |
| be8aaf62-accf-4c40-8fea-0d90d892494c | U10 female | 13 | 8 | No |
| ed352161-9fc8-47be-8b0d-6f123eb00352 | U10 female | 43 | 11 | Yes |
| 1c69dc93-7575-4c57-badc-7884141ce40e | U10 female | 11 | 11 | Yes |
| 18953f3f-5f43-45ae-9222-f4f8786f4181 | U11 female | 93 | 11 | Yes |
| 138021e2-dcbf-42b6-9fe9-e4768a9b72c7 | U13 female | 87 | 6 | No |
| 098a9210-4d7a-4c22-997f-f251d17d26e7 | U13 female | 35 | 10 | Yes |
| 9498f76a-4dfd-43a8-aaa7-87b923718646 | U13 male | 34 | 8 | No |
| 48562ef5-d082-41dc-9b7c-83c51289514d | U14 female | 86 | 11 | Yes |
| 8c9578f5-6b80-4cc8-82e7-b6acce420c49 | U16 male | 63 | 11 | Yes |

## Verification and limits

The saved selection receipt, all four output hashes, original input hashes, distinct team/game pairs, selected-game counts and latest-game dates were verified. Reapplying 12 exactly reproduced the prior eligibility labels; reapplying 10 produced the counts above. The 10-game policy changes eligibility, not game selection. Inactivity and the separate ML/evidence-support thresholds remain unchanged. Ceiling safeguards are supplied by PR #1255 and will be retained in the combined preview.

The combined preview must check final ranks, newly eligible high placements, all boards, and the Texas/Washington cases. No ranking improvement or safe publication is inferred from eligibility counts alone.

Source and artifact hashes are in the companion evidence JSON. The original September and 12-game reports remain intact.

Verification: 269 affected engine, ceiling, configuration and pipeline tests pass; repository Python lint passes. The new tests cover eligibility at 10 and 11, rejection at 9, expired-game exclusion, inactive teams, both rating passes, the normal calculator entry point, and cache invalidation when the eligibility minimum changes. Full current-head CI is tracked on PR #1257.
