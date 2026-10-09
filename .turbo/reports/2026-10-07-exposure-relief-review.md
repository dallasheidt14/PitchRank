# Require results for the exposure-based ceiling exception

October 7, 2026. Saved August 31 combined newest-30/365, minimum-10 preview. Comparison reference: `57c736b23ec8dadd7f9ad90e34cd33814235ed04`. All movement is against that saved preview, not current production.

## Implemented policy and what it accomplishes

The late connectivity exception now requires at least one win or draw against a same-age opponent in the engine's existing raw top-100 evidence group. Merely playing those opponents and losing every game does not earn the 250 ceiling bucket; the existing 400 restriction applies instead. Missing result counts do not grant relief. Freshness still applies. Earlier supported in-state, authority, play-up and stricter-restriction branches are unchanged.

This is an explicitly approved exception-policy change, measured separately from the earlier rule-order bug. It adds no new threshold value, data source, rating calculation, selection policy, eligibility rule or database/API change. Raw evidence ranks are not final published ranks; this rule does not require beating a team that ultimately publishes in the top 100.

**The California U10 boys case remains #94.** Its exception changes from 250 to 400, but its score is already below both numeric ceilings. Removing the exception therefore does not address this team's high placement. The saved score is `0.549502592041005`; the old/new limits are `0.6454546715598009` / `0.6146157261353179`. Ceiling numbers name score thresholds, not final-rank floors.

The bounded effect is still material elsewhere:

- **1,308 rows receive a stricter cap**, including **1,190 active teams**. Of those active teams, 185 lose score and 1,005 keep the same score because the limit does not bind. No cap is loosened.
- Across 65,388 eligible teams, **1,614 ranks change**, with a largest move of 67. No team moves more than 100 places.
- **32 previous top-25 teams drop out**, and 63 teams newly enter the top 100. Pennsylvania U10 boys #4 moves to #28; a different California U10 boys team #5 moves to #30.
- The full board reshuffle changes other teams' score slots too: 825 active scores decrease and 905 increase. A stricter cap for one team does not imply that every other score falls.
- Top-100 flags remain **26**. Top-25 flags rise **8 to 11** as preserved play-up exceptions move upward. No ranking-quality improvement is inferred from the count.

Keep the implemented exception and its evidence reviewable in draft PR #1255. This does not complete the broader goal of preventing every unsupported high placement, and it is not approval to publish.

## Top-placement review

All 175 previous top-100 teams whose caps change, all 32 new top-25 entrants, all 63 new top-100 entrants, all 26 flagged teams and the earlier investigated cases are included: **352 distinct teams and 6,976 selected opponent relationships**. Every cap return path is traced. Opponent ranks below are refreshed after this correction.

Five top-25 entrants lack a selected same-age or next-age final top-100 non-loss; each has top-500 support. Those five require context:

| Team / ID | Before -> after | Supporting results and limit of the evidence |
|---|---:|---|
| WA U13 boys `1b6cb88c-cc79-45dc-8363-a7fdef74afe5` | 28 -> 23 | Seven same-age final top-500 non-loss opponents; its raw top-100 result retains exposure relief. |
| NY U13 boys `49c7460b-a188-4c28-9e96-92e891602716` | 30 -> 25 | Only one same-age final top-500 non-loss: a 3-3 draw against #346. Its raw top-100 result retains relief; exact top-25 placement remains weakly corroborated. |
| TX U13 girls `7179914d-4d54-46ca-8665-e2cd94e8d2e8` | 27 -> 25 | Six same-age final top-500 non-loss opponents, including #106. Raw top-100 evidence retains relief. |
| PA U10 girls `c8f4617d-4c2a-42c3-b46c-4e4c455fb1b6` | 32 -> 25 | Six same-age final top-500 non-loss opponents, including #101; unchanged 400 cap. |
| CA U11 boys `d6408243-3390-43df-bfaf-78a2a017cea5` | 27 -> 23 | One same-age final top-500 non-loss: 5-4 against #258, which has no selected same-age final top-500 non-loss itself. Raw evidence relief remains; top-end corroboration is limited. |

The one new top-100 entrant with no same-age/next-age top-500 non-loss is **NC U17 girls #101 to #99** (`6fc431a7-c2ed-4ea0-a5b9-d86f6b41fb69`). That screen excludes its substantial U19 results: nine distinct final top-500 non-loss opponents (#104, #108, #110, #117, #144, #146, #170, #248 and #344), each with top-500 support of its own. The case must not be described as having no quality results overall. The age+1 screen and existing relief policy are unchanged.

The three flagged teams newly entering the top 25 use preserved play-up relief: Ohio U10 boys #32 to #21, Pennsylvania U10 boys #37 to #24 and Florida U13 boys #26 to #21. All 26 flags still qualify for play-up relief. With refreshed opponent placements, 16 have the stronger corroborating chain described in the prior report and 10 have limited top-end corroboration. This descriptive split is model-derived context, not an acceptance test. The Missouri U11 girls case switches categories only because an older opponent moves from #101 to #100; there is no new match evidence.

The 185 previously documented credited older-opponent relationships and their game IDs remain preserved, with new opponent ranks recorded separately. Their broader 365-day evidence pool is unchanged. Selected same-gender, same/next-age review counts and all saved game details are retained; cross-gender rows remain in the audit trail but do not count as quality support.

## All new top-25 and top-100 entrants

Counts are distinct selected same-gender opponents with a win or draw against final top-100 / top-500 teams. Older means exactly one age higher. All per-opponent games and cap traces are in the [evidence](2026-10-07-exposure-relief-review-evidence.json).

| Board / state | Team ID | Before -> after | New tier | Same-age 100 / 500 | Older 100 / 500 |
|---|---|---:|---|---:|---:|
| U10 boys MA | `f2934340-5fbe-43b3-b914-6f874819d24a` | 26 -> 18 | top 25 | 1 / 3 | 0 / 1 |
| U10 boys MN | `10c5ac63-2ff1-4183-a508-5fc355fe6d3d` | 28 -> 19 | top 25 | 1 / 3 | 0 / 0 |
| U10 boys PA | `f526800e-556c-4961-a01a-347a456f7334` | 30 -> 20 | top 25 | 3 / 4 | 0 / 0 |
| U10 boys OH | `0a0925c8-3231-49dc-ae40-50bb0ba8d1bd` | 32 -> 21 | top 25 | 0 / 1 | 1 / 3 |
| U10 boys PA | `ed1a4c28-ad59-49de-a0eb-5886d323543c` | 34 -> 22 | top 25 | 1 / 1 | 0 / 0 |
| U10 boys NJ | `83ea7aa9-3999-40fd-9c73-544b5ecc2681` | 36 -> 23 | top 25 | 0 / 0 | 4 / 9 |
| U10 boys PA | `f4bff5a7-0489-4cba-b712-3fce5d05999f` | 37 -> 24 | top 25 | 0 / 1 | 3 / 5 |
| U10 boys NY | `f6800087-6328-4f19-bef6-26911e83d1ec` | 38 -> 25 | top 25 | 1 / 1 | 0 / 0 |
| U10 girls NJ | `86783365-eff3-42b1-81ac-5c4c908438fd` | 29 -> 22 | top 25 | 5 / 8 | 0 / 0 |
| U10 girls CA | `7a5e60cb-131f-41ed-8c1b-6e93c7dc2459` | 30 -> 23 | top 25 | 2 / 5 | 0 / 0 |
| U10 girls NV | `1c69dc93-7575-4c57-badc-7884141ce40e` | 31 -> 24 | top 25 | 2 / 5 | 0 / 0 |
| U10 girls PA | `c8f4617d-4c2a-42c3-b46c-4e4c455fb1b6` | 32 -> 25 | top 25 | 0 / 6 | 0 / 0 |
| U11 boys OH | `3b4391ae-1f93-442e-8b89-86a85917d8ca` | 26 -> 22 | top 25 | 1 / 2 | 0 / 0 |
| U11 boys CA | `d6408243-3390-43df-bfaf-78a2a017cea5` | 27 -> 23 | top 25 | 0 / 1 | 0 / 0 |
| U11 boys CA | `a316dd62-e628-4afa-8bef-301d8c609e69` | 29 -> 24 | top 25 | 3 / 6 | 0 / 0 |
| U11 boys CA | `a22441ed-a549-4579-b566-b6ecb677c6ef` | 30 -> 25 | top 25 | 1 / 6 | 0 / 0 |
| U11 boys PA | `d6dfa38f-02b8-4444-87c6-ee63b999ab11` | 101 -> 90 | top 100 | 1 / 6 | 0 / 0 |
| U11 boys MI | `5b13b498-d304-44b5-96d5-06ec97162824` | 102 -> 92 | top 100 | 1 / 3 | 0 / 0 |
| U11 boys NY | `8f404a15-dd07-4566-91b2-ecaf80254264` | 103 -> 94 | top 100 | 1 / 5 | 0 / 1 |
| U11 boys IL | `18be825f-a234-4bea-86d8-b0fca9b88b8f` | 104 -> 95 | top 100 | 0 / 3 | 0 / 0 |
| U11 boys DE | `726c8640-fd61-42e3-9149-39f9e192ed36` | 105 -> 97 | top 100 | 2 / 10 | 0 / 0 |
| U11 boys FL | `3d0cb402-0e63-4e18-8a66-4af2597451d4` | 106 -> 99 | top 100 | 0 / 4 | 0 / 0 |
| U11 boys NJ | `cd684aeb-0baf-44ef-a68e-36746dbe5099` | 107 -> 100 | top 100 | 3 / 10 | 0 / 0 |
| U11 girls PA | `2850c170-f462-4c03-ac17-abba48ed40ca` | 27 -> 23 | top 25 | 10 / 15 | 0 / 0 |
| U11 girls MI | `3e0f9c8c-2624-42ed-b85b-e442f629187d` | 29 -> 24 | top 25 | 3 / 5 | 0 / 0 |
| U11 girls OK | `dcd0bb97-5363-4de6-94d0-98ee917515f3` | 28 -> 25 | top 25 | 2 / 7 | 0 / 1 |
| U12 boys VA | `3ca7dd5c-2e40-4aa0-b2e9-9695baa71063` | 26 -> 25 | top 25 | 5 / 15 | 0 / 0 |
| U12 boys MA | `061747ce-b2ce-43b2-bb79-6a057d92d468` | 101 -> 96 | top 100 | 0 / 4 | 0 / 0 |
| U12 boys FL | `04092dc8-fbc6-4fae-b496-d75fb61862f9` | 102 -> 98 | top 100 | 3 / 9 | 0 / 0 |
| U12 boys GA | `e6e9af5c-b00d-44d7-a207-87be5a5040e0` | 103 -> 99 | top 100 | 2 / 6 | 0 / 0 |
| U12 boys FL | `ae30d726-63d9-4fae-98a6-fc183f697abe` | 104 -> 100 | top 100 | 3 / 10 | 0 / 0 |
| U12 girls TX | `ec84cc73-a667-4d3d-8a8a-4181fed771e5` | 27 -> 25 | top 25 | 2 / 4 | 0 / 0 |
| U12 girls MO | `a8875d7c-7c52-4b79-9713-8c0ab1d492d2` | 101 -> 100 | top 100 | 0 / 3 | 0 / 0 |
| U13 boys FL | `b0862050-bf1e-4fe7-8bb2-63c7ed9d4888` | 26 -> 21 | top 25 | 0 / 1 | 1 / 5 |
| U13 boys VA | `3dad14ed-305b-43c9-a936-ecc43577d893` | 27 -> 22 | top 25 | 4 / 8 | 0 / 0 |
| U13 boys WA | `1b6cb88c-cc79-45dc-8363-a7fdef74afe5` | 28 -> 23 | top 25 | 0 / 7 | 0 / 0 |
| U13 boys NJ | `5b387689-5346-4a87-86db-7db7ef05ce46` | 29 -> 24 | top 25 | 3 / 5 | 0 / 0 |
| U13 boys NY | `49c7460b-a188-4c28-9e96-92e891602716` | 30 -> 25 | top 25 | 0 / 1 | 0 / 0 |
| U13 boys GA | `6ab6ae07-ea4b-4f92-92c9-cb71e517cb1c` | 101 -> 99 | top 100 | 1 / 4 | 0 / 0 |
| U13 girls CA | `e193c40b-67a6-4cad-b232-a577c5786596` | 26 -> 24 | top 25 | 5 / 10 | 1 / 3 |
| U13 girls TX | `7179914d-4d54-46ca-8665-e2cd94e8d2e8` | 27 -> 25 | top 25 | 0 / 6 | 0 / 0 |
| U14 boys UT | `85b4d66e-1c33-4f86-b340-4ff85f776c89` | 101 -> 92 | top 100 | 2 / 4 | 0 / 0 |
| U14 boys ME | `47216173-8061-4b56-8dd1-1c016c9b0ed4` | 102 -> 94 | top 100 | 0 / 2 | 0 / 0 |
| U14 boys ME | `ed76022c-ce78-4193-8e80-018ea1dfc10c` | 103 -> 95 | top 100 | 1 / 4 | 0 / 0 |
| U14 boys NJ | `a1a8a34e-ca0c-4955-b368-e8b38e490919` | 104 -> 96 | top 100 | 0 / 7 | 0 / 0 |
| U14 boys FL | `d65ea8f0-ba0f-4284-8e9c-aac3241a8563` | 105 -> 97 | top 100 | 0 / 6 | 0 / 0 |
| U14 boys CA | `6a30982c-0bc3-469b-a4e3-08665574d331` | 106 -> 98 | top 100 | 2 / 6 | 0 / 1 |
| U14 boys OH | `797c27f1-e2e0-4da5-8e3e-c451802531aa` | 107 -> 99 | top 100 | 3 / 7 | 0 / 0 |
| U14 boys IN | `3616e3fe-b042-4b38-a2a3-973830b14ddc` | 109 -> 100 | top 100 | 0 / 6 | 0 / 0 |
| U14 girls NY | `f8490030-313c-40cb-9be4-4e486e9930ea` | 101 -> 92 | top 100 | 0 / 1 | 0 / 1 |
| U14 girls NJ | `b97edb80-0831-4811-9605-be8ac75203af` | 102 -> 95 | top 100 | 0 / 0 | 5 / 12 |
| U14 girls MD | `55667ed4-5e87-4e49-90f3-2dcbf46b37c1` | 103 -> 96 | top 100 | 1 / 5 | 0 / 0 |
| U14 girls NJ | `c44aecc7-49ba-4a14-b7da-9fecfdf2d128` | 104 -> 97 | top 100 | 1 / 5 | 0 / 0 |
| U14 girls WA | `4c1affe5-6f90-476b-92b8-51bb7293f883` | 105 -> 98 | top 100 | 3 / 5 | 0 / 0 |
| U14 girls CT | `c22bded9-4a7d-4c64-92ca-a20cc511bcbb` | 106 -> 99 | top 100 | 2 / 4 | 0 / 0 |
| U14 girls WA | `5819f09f-4ead-4823-b3ed-07abdf376801` | 107 -> 100 | top 100 | 0 / 4 | 0 / 0 |
| U15 boys MI | `e66702fd-547b-4aba-b5ba-4f02e3ddf012` | 103 -> 97 | top 100 | 0 / 4 | 0 / 0 |
| U15 boys CA | `60e8f25b-229b-41d3-ab26-e609eef835b0` | 101 -> 98 | top 100 | 4 / 13 | 0 / 0 |
| U15 boys GA | `ea0e412f-5e39-42ba-9b36-450bd82acbda` | 102 -> 99 | top 100 | 4 / 10 | 0 / 0 |
| U15 boys OH | `4da8e6f6-89c8-4992-a1f6-d4e662923d3f` | 104 -> 100 | top 100 | 4 / 14 | 0 / 0 |
| U15 girls AK | `0a6c91cb-175b-49e1-bbeb-91cd346a64eb` | 101 -> 97 | top 100 | 1 / 2 | 0 / 0 |
| U15 girls MT | `24b6a8a9-e350-4695-b28f-2d2bb1fb7ecf` | 102 -> 98 | top 100 | 0 / 6 | 1 / 2 |
| U15 girls MI | `f117f96f-74f2-40de-b85f-3d6be62091a3` | 103 -> 99 | top 100 | 0 / 6 | 0 / 0 |
| U16 boys PA | `73b585d9-af7b-4a30-aa22-9bf4e595781f` | 26 -> 24 | top 25 | 3 / 8 | 0 / 0 |
| U16 boys NJ | `b21af0f5-3ad6-47f4-8c49-c02963eff4fe` | 28 -> 25 | top 25 | 3 / 10 | 0 / 0 |
| U16 boys TN | `42fa2c4f-195c-4c64-8c60-058a4fc70dca` | 101 -> 94 | top 100 | 1 / 7 | 0 / 0 |
| U16 boys NJ | `67e8dfe3-8bff-4ef5-aa9d-d503943a662a` | 102 -> 95 | top 100 | 5 / 12 | 3 / 3 |
| U16 boys TX | `29695338-dec7-4f5b-9655-c66964446d0c` | 103 -> 96 | top 100 | 2 / 10 | 0 / 0 |
| U16 boys WA | `c9a326f6-e0d3-4029-b79c-c49ca50d689f` | 104 -> 97 | top 100 | 1 / 6 | 0 / 0 |
| U16 boys CA | `9e9abdc3-b0aa-496e-a2a4-fae26bd8ceee` | 105 -> 98 | top 100 | 1 / 10 | 0 / 0 |
| U16 boys CT | `e9d31d91-6edc-4196-9581-0f89e54fed1a` | 106 -> 100 | top 100 | 3 / 7 | 0 / 0 |
| U16 girls PA | `9cb121c2-5476-4ca0-b0ef-c8c4df40bbd0` | 101 -> 98 | top 100 | 0 / 5 | 0 / 0 |
| U16 girls TX | `9de139d6-f27a-4037-9382-dd03c1fb599e` | 102 -> 99 | top 100 | 0 / 7 | 0 / 0 |
| U16 girls KS | `5cd71008-7a1d-41f1-a069-fe077cd86f99` | 103 -> 100 | top 100 | 4 / 9 | 0 / 0 |
| U17 boys NJ | `0426bdf2-7163-4d59-95f4-27b50cac75bc` | 27 -> 25 | top 25 | 5 / 14 | 0 / 0 |
| U17 boys MA | `53f72e00-8977-405c-b55d-a4f81d289763` | 101 -> 92 | top 100 | 2 / 6 | 0 / 0 |
| U17 boys MN | `5aaff081-8db0-4e0d-96dc-87d61b9a05ca` | 102 -> 93 | top 100 | 2 / 6 | 0 / 0 |
| U17 boys TX | `753b456c-e5ee-4ad4-9c89-6a38f5e15b87` | 103 -> 94 | top 100 | 0 / 3 | 0 / 0 |
| U17 boys UT | `1285ccc8-f36d-496b-8dfa-6bb7830e31ef` | 104 -> 95 | top 100 | 1 / 10 | 0 / 0 |
| U17 boys TX | `38c3eba4-b442-458e-b1bc-550a55127ad2` | 105 -> 96 | top 100 | 5 / 12 | 0 / 0 |
| U17 boys NH | `a2a6c2f8-8a11-416d-b6ae-d51cf3cc2107` | 106 -> 97 | top 100 | 2 / 7 | 0 / 0 |
| U17 boys TX | `aba6dd52-1a8c-415b-9b83-3f00d948968f` | 107 -> 98 | top 100 | 2 / 13 | 0 / 0 |
| U17 boys CA | `8e4fdbf1-eaf8-4325-bd79-ada0fac92c05` | 108 -> 99 | top 100 | 0 / 4 | 0 / 0 |
| U17 boys FL | `435ba3be-7676-42e2-82d8-b2aec0717ab6` | 109 -> 100 | top 100 | 2 / 11 | 0 / 0 |
| U17 girls NC | `6fc431a7-c2ed-4ea0-a5b9-d86f6b41fb69` | 101 -> 99 | top 100 | 0 / 0 | 0 / 0 |
| U17 girls KS | `eaaa7cd4-3436-4d28-9cba-5feff682ab76` | 102 -> 100 | top 100 | 2 / 3 | 0 / 0 |
| U19 boys NC | `7f006218-1873-4d9a-baf0-b6fd8fa3fedf` | 26 -> 25 | top 25 | 2 / 9 | 0 / 0 |
| U19 boys TX | `ebd230b3-161c-408a-902e-138be1f17594` | 101 -> 92 | top 100 | 1 / 5 | 0 / 0 |
| U19 boys OH | `ccdda93e-f0fc-45c6-a6a0-b6bba6f1d44d` | 102 -> 93 | top 100 | 0 / 4 | 0 / 0 |
| U19 boys NC | `062456c7-d555-4385-ab27-093ee5ac4f26` | 104 -> 94 | top 100 | 0 / 9 | 0 / 0 |
| U19 boys NY | `2888ede3-b221-471c-8855-13d26ad6d991` | 105 -> 95 | top 100 | 0 / 9 | 0 / 0 |
| U19 boys TX | `d0d54d6b-4d35-480c-ab5b-67122b15017d` | 106 -> 96 | top 100 | 1 / 4 | 0 / 0 |
| U19 boys TX | `7cfc2638-cc7d-4d52-aeb8-f6086a813400` | 103 -> 97 | top 100 | 3 / 9 | 0 / 0 |
| U19 boys VA | `2a1d445a-3752-4449-9a31-27c0f74982c0` | 107 -> 98 | top 100 | 2 / 17 | 0 / 0 |
| U19 boys MA | `8ae98b3c-720c-457f-bbf3-97680a8f00d3` | 108 -> 100 | top 100 | 0 / 3 | 0 / 0 |

## All 26 flagged teams

| Board / state | Team ID | Before -> after | Older 100 / 500 | Corroboration |
|---|---|---:|---:|---|
| U10 boys AZ | `01f1234d-af96-486b-b292-304003c0b8d9` | 7 -> 5 | 0 / 1 | limited |
| U10 boys CA | `8ed299df-239a-496d-b06a-02d44216a139` | 8 -> 6 | 0 / 3 | limited |
| U10 boys OH | `0a0925c8-3231-49dc-ae40-50bb0ba8d1bd` | 32 -> 21 | 1 / 3 | stronger |
| U10 boys PA | `f4bff5a7-0489-4cba-b712-3fce5d05999f` | 37 -> 24 | 3 / 5 | stronger |
| U10 boys AZ | `1610353d-452e-4dc6-b210-86336395a76c` | 92 -> 92 | 0 / 2 | limited |
| U10 girls CA | `6d7fa4c2-b008-4097-aa36-f9e3cae8b657` | 1 -> 1 | 1 / 4 | limited |
| U10 girls TX | `771ccdde-9f65-4640-a9bd-d030c89eed70` | 21 -> 20 | 0 / 2 | limited |
| U10 girls PA | `9d2df9bf-3809-461f-b0a2-75ccd829d42f` | 79 -> 79 | 1 / 6 | stronger |
| U11 boys TX | `7eebf48a-d652-4c89-a536-5310da674e36` | 55 -> 39 | 2 / 3 | stronger |
| U11 boys FL | `c99e4e74-ed31-4a01-97f7-f8a2dc27ae81` | 71 -> 57 | 0 / 3 | limited |
| U11 girls MO | `bda3f7ac-611a-4461-a297-c693ab82aa6b` | 22 -> 19 | 1 / 5 | stronger |
| U11 girls MI | `d70ac4c7-50c2-477f-b925-67ea889a00f3` | 24 -> 21 | 0 / 4 | limited |
| U11 girls CA | `5243f853-4bb0-4f3d-9f4f-8afc27a88af6` | 75 -> 75 | 1 / 4 | stronger |
| U11 girls OH | `7c2b49a7-714c-4ef9-b9e5-a91f225ccf85` | 89 -> 89 | 1 / 9 | stronger |
| U11 girls TX | `19cfa8d3-1f45-42e7-947d-632388bf417d` | 90 -> 90 | 1 / 4 | stronger |
| U12 boys NY | `a8801c99-44b8-44af-818a-d9052e813615` | 15 -> 15 | 5 / 9 | stronger |
| U12 boys FL | `70bb6fb5-6e5a-411f-aa3b-6d8de016bec1` | 50 -> 38 | 4 / 7 | stronger |
| U12 boys TX | `4e087db8-3151-42f4-a079-27fc31e90c03` | 54 -> 40 | 3 / 6 | stronger |
| U12 boys WY | `7285134c-d8ff-47aa-9689-bca438d7e538` | 75 -> 67 | 2 / 3 | stronger |
| U12 boys FL | `563c1a33-e694-40df-ab31-5a80ff337fd3` | 78 -> 71 | 0 / 1 | limited |
| U12 girls FL | `5269cdce-d6a3-437a-a35a-988e2c9aa3fd` | 28 -> 26 | 3 / 5 | stronger |
| U12 girls WA | `d008a0f6-ad00-460a-a1ab-bfc043cfc08a` | 56 -> 51 | 0 / 2 | limited |
| U13 boys FL | `b0862050-bf1e-4fe7-8bb2-63c7ed9d4888` | 26 -> 21 | 1 / 5 | stronger |
| U13 girls WA | `0fa30277-0033-4b7f-96cf-680947fe9545` | 24 -> 22 | 2 / 5 | stronger |
| U14 boys FL | `5f43d163-20df-43b5-91d9-8d6be8dc86db` | 48 -> 44 | 1 / 7 | stronger |
| U16 girls IN | `9dd5030b-346b-4afb-a780-43c17a5eb566` | 56 -> 56 | 0 / 3 | limited |

## All 18 boards

| Board | Eligible | Stricter caps | Rank changes | Largest move |
|---|---:|---:|---:|---:|
| U10 girls | 1,046 | 39 | 66 | 38 |
| U10 boys | 1,900 | 55 | 63 | 32 |
| U11 girls | 3,220 | 53 | 58 | 39 |
| U11 boys | 5,896 | 90 | 118 | 56 |
| U12 girls | 3,346 | 72 | 85 | 52 |
| U12 boys | 6,126 | 82 | 108 | 59 |
| U13 girls | 3,553 | 68 | 81 | 44 |
| U13 boys | 6,219 | 65 | 93 | 51 |
| U14 girls | 3,245 | 76 | 74 | 39 |
| U14 boys | 5,408 | 100 | 118 | 52 |
| U15 girls | 3,008 | 60 | 81 | 45 |
| U15 boys | 4,869 | 62 | 110 | 57 |
| U16 girls | 2,300 | 49 | 64 | 46 |
| U16 boys | 3,820 | 74 | 131 | 63 |
| U17 girls | 1,800 | 44 | 54 | 38 |
| U17 boys | 2,978 | 86 | 124 | 67 |
| U19 girls | 2,645 | 42 | 46 | 46 |
| U19 boys | 4,009 | 73 | 140 | 60 |

U10 boys and girls are separate above. The earlier Massachusetts/Texas bypass cases remain #397/#385, and the original Texas/Washington cases remain #439/#239 with their 1,800 restrictions. Michigan U12 boys moves #94 to #88 and Maine U14 boys #96 to #84 as other teams move down; their cap rules are unchanged. No new prediction finding or solved-U10 claim is made.

## Replay boundaries and verification

The policy record was saved before measuring this change. Removing only the three added source lines makes the calculator AST identical to the saved reference. The only potentially changed decision must previously have yielded 250 with top-100 exposure and zero top-100 non-losses. Every one of those 1,367 rows is recomputed with both functions, and the candidate decision is repeated. Other cap decisions are reused from the previously verified replay, not newly recomputed.

Every prior final score across all 136,044 rows reproduces exactly from the saved captures. Every candidate band output repeats exactly. Numeric ceilings, finite scores, original-score bounds and same-ceiling ordering hold on all 18 boards. Eligibility, selected games, pre-ceiling scores and saved inputs remain unchanged. No ranking engine, ML fit, live database fetch or later-outcome evaluation was run.

The existing diagnosis command was exercised through a network-blocked saved-data adapter. Its legacy v53e formula simulation is not used to justify this Glicko change; conclusions use saved actual score layers and cap traces.

Verification:

- **8,200 passed and 13 skipped in the CI-defined Python scope**; all 177 focused cases pass. The broader local command also ran 45 tests in `tests/test_enhanced_pipeline.py`, which CI already excludes: 42 passed and 3 failed. Those unchanged legacy expectations use too-short IDs and a stale high-score message substring. They do not exercise this cap change. The XML scope audit retains every result; the entire broad invocation is not described as passing.
- All 25 new cases pass; before the change 13 fail and 12 controls pass. Removing the guard fails those 13 regressions; incorrectly requiring two results fails all nine one-result controls.
- Repository Python lint passes. Independent code/coverage review and saved-replay review approved the bounded change. No full engine or completed test batch was duplicated.

The [machine-readable evidence](2026-10-07-exposure-relief-review-evidence.json) contains all schedules, cap traces, source/runtime/input/output hashes and test receipts. Candidate calculator SHA-256: `5bddea06334c59bedfa82efaf75446a5a0fac7ca56fb6362c95dc5b8ded8a72c`. Output SHA-256: `d56f14caf94ddd4d74939cb0a1bcec1cbe1100e872956846c9a568b070f3dbf2`. Scratch scripts and outputs remain at `C:\Users\Dallas Heidt\AppData\Local\Temp\pitchrank-exposure-results-20261007`. Historical reports and frozen references are preserved.

Both release PRs remain drafts. No merge or publication is authorized. The implemented rule is narrower than a general guarantee against unsupported high placements; the unchanged California #94 case and remaining thin raw-rank exceptions make that limitation concrete.
