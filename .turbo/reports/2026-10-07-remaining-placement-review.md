# Remaining high-placement review and connectivity rule-order correction

October 7, 2026. Implementation, tests and bounded placement review are complete. Saved August 31 combined preview, newest 30 games within 365 days and minimum 10. The comparison below is against the preceding ceiling-order replay at `241998686a6580b7edd86113f3ee6b67de0dda5f`, not current production.

## Decision and confirmed fix

The review found a shared rule-order defect in two of the four additional concerning cases. The severe-connectivity fallback returned a 400 ceiling bucket before evaluating existing 1,800 thin-schedule and 1,500 weak-result restrictions. The fix evaluates those stricter restrictions first. It changes no thresholds and preserves explicit supported in-state and play-up exceptions.

- Massachusetts U13 boys: **#91 to #397**; Texas U13 boys: **#88 to #385**. Both already met the existing 1,800 rule but received 400 because of the early return.
- Michigan U12 boys: **#96 to #94**; Maine U14 boys: **#100 to #96**. Neither matches the bypass. Both have wider network links and same-age results worth retaining; exact placement is not independently established.
- **2,134 of 136,044 rows receive stricter caps**, including 1,947 active teams. The changes are 2,055 cases of 400 to 1,800 and 79 of 400 to 1,500. No cap is relaxed.
- Across 65,388 eligible teams, **11,539 ranks change**, 537 by more than 100 places and 233 by more than 300; largest move 599. No new top-25 entrant appears.

Keep this verified fix in draft PR #1255. The remaining play-up evidence concerns are documented below; this review does not certify every top placement or authorize publication. Do not demote all flagged teams merely for their location or lack of travel.

## What the flags actually mean

The flag combines the existing isolation diagnostic with no raw same-age top-100 opponent, at most two raw same-age top-500 opponents and at most one non-loss against them. It is a prompt to inspect evidence, not a finding that a team is disconnected or ranked incorrectly. Raw evidence ranks differ from the final published order.

All 27 originally investigated teams have paths into the large same-gender schedule networks. The selected-game graph has 139,506 nodes and 691,090 undirected links. Edges use valid same-gender observations selected by either endpoint. The 23 original flags have a path to another state/province in one or two games; Michigan, the additional Texas case and Maine have three-game paths. Massachusetts has a direct New York opponent. These paths show reachability only. A long chain, a high model-derived opponent rank or travel alone does not establish strong evidence.

All 23 original flags still use the explicit older-opponent exception. **Thirteen have stronger corroboration:** a selected non-loss against a next-age final top-100 opponent that itself has a selected same-age final top-500 non-loss. **Ten have more limited top-end corroboration.** These are descriptive review categories, not new acceptance criteria; even the stronger group is not independently certified. The categories use refreshed opponent ranks after this fix.

The total flag count is now **26 top-100 teams, eight top-25**: the original 23 plus three entrants promoted when other teams move down. Counting only the original 23 would miss those entrants. All 26 are included in the detailed review. A rising or falling flag count alone does not measure ranking quality.

## Four additional cases

| Case and team ID | Record / opponents | Before -> after | Evidence and conclusion |
|---|---|---:|---|
| MA U13 boys `29b048b8-949e-4c18-a9ab-335665ddbcfc` | 21-1-4 / 9 | 91 -> 397 | No selected same-age or next-age final top-500 non-loss. Existing thin-schedule restriction was bypassed. Fixed. |
| TX U13 boys `86759578-eb09-44b3-b424-d74b1b578d24` | 17-1-0 / 6 | 88 -> 385 | Repetitive schedule; one selected same-age final top-500 non-loss. Existing thin-schedule restriction was bypassed. Fixed. |
| MI U12 boys `853e6105-c296-4c36-909b-e6fc3432c060` | 9-7-0 / 7 | 96 -> 94 | Wins against final #122; other previous top-500 opponents fall outside 500 after this correction. Four of seven opponents connect beyond its immediate group. No matching bypass; evidence remains narrow. |
| ME U14 boys `ab04ed43-9b88-43bf-83b3-ae1971ceb46a` | 16-3-0 / 15 | 100 -> 96 | Non-losses against final #102, #103, #143 and #230. All 15 opponents have links beyond its immediate group. No matching bypass. |

## All original flags and new flagged entrants

Same-age and older columns count distinct selected same-gender opponents with a win or draw, using final top-100 / top-500 ranks. Older means the next age, as stored in the snapshot. Age labels were not independently verified. S = stronger corroboration as defined above; L = limited top-end corroboration.

| Board / state | Team ID | Before -> after | Same-age 100 / 500 | Older 100 / 500 | Review |
|---|---|---:|---:|---:|---|
| U10 boys AZ | `01f1234d-af96-486b-b292-304003c0b8d9` | 7 -> 7 | 0 / 0 | 0 / 1 | L |
| U10 boys CA | `8ed299df-239a-496d-b06a-02d44216a139` | 8 -> 8 | 0 / 3 | 0 / 3 | L |
| U10 boys OH | `0a0925c8-3231-49dc-ae40-50bb0ba8d1bd` | 32 -> 32 | 0 / 1 | 1 / 3 | S |
| U10 boys PA | `f4bff5a7-0489-4cba-b712-3fce5d05999f` | 37 -> 37 | 0 / 1 | 2 / 5 | S |
| U10 boys AZ | `1610353d-452e-4dc6-b210-86336395a76c` | 105 -> 92 | 0 / 0 | 0 / 2 | L; new flag |
| U10 girls CA | `6d7fa4c2-b008-4097-aa36-f9e3cae8b657` | 1 -> 1 | 0 / 0 | 1 / 4 | L |
| U10 girls TX | `771ccdde-9f65-4640-a9bd-d030c89eed70` | 21 -> 21 | 0 / 2 | 0 / 2 | L |
| U10 girls PA | `9d2df9bf-3809-461f-b0a2-75ccd829d42f` | 86 -> 79 | 1 / 1 | 1 / 6 | S |
| U11 boys TX | `7eebf48a-d652-4c89-a536-5310da674e36` | 55 -> 55 | 0 / 2 | 2 / 3 | S |
| U11 boys FL | `c99e4e74-ed31-4a01-97f7-f8a2dc27ae81` | 73 -> 71 | 0 / 0 | 0 / 3 | L |
| U11 girls MO | `bda3f7ac-611a-4461-a297-c693ab82aa6b` | 22 -> 22 | 0 / 3 | 0 / 5 | L |
| U11 girls MI | `d70ac4c7-50c2-477f-b925-67ea889a00f3` | 24 -> 24 | 0 / 0 | 0 / 4 | L |
| U11 girls CA | `5243f853-4bb0-4f3d-9f4f-8afc27a88af6` | 85 -> 75 | 0 / 1 | 1 / 4 | S |
| U11 girls OH | `7c2b49a7-714c-4ef9-b9e5-a91f225ccf85` | 102 -> 89 | 0 / 3 | 1 / 9 | S; new flag |
| U11 girls TX | `19cfa8d3-1f45-42e7-947d-632388bf417d` | 103 -> 90 | 0 / 0 | 1 / 4 | S; new flag |
| U12 boys NY | `a8801c99-44b8-44af-818a-d9052e813615` | 15 -> 15 | 0 / 0 | 5 / 9 | S |
| U12 boys FL | `70bb6fb5-6e5a-411f-aa3b-6d8de016bec1` | 50 -> 50 | 0 / 0 | 4 / 7 | S |
| U12 boys TX | `4e087db8-3151-42f4-a079-27fc31e90c03` | 54 -> 54 | 0 / 0 | 3 / 6 | S |
| U12 boys WY | `7285134c-d8ff-47aa-9689-bca438d7e538` | 80 -> 75 | 0 / 0 | 2 / 3 | S |
| U12 boys FL | `563c1a33-e694-40df-ab31-5a80ff337fd3` | 83 -> 78 | 0 / 0 | 0 / 1 | L |
| U12 girls FL | `5269cdce-d6a3-437a-a35a-988e2c9aa3fd` | 28 -> 28 | 0 / 0 | 3 / 5 | S |
| U12 girls WA | `d008a0f6-ad00-460a-a1ab-bfc043cfc08a` | 58 -> 56 | 0 / 1 | 0 / 2 | L |
| U13 boys FL | `b0862050-bf1e-4fe7-8bb2-63c7ed9d4888` | 26 -> 26 | 0 / 1 | 1 / 5 | S |
| U13 girls WA | `0fa30277-0033-4b7f-96cf-680947fe9545` | 24 -> 24 | 0 / 0 | 1 / 5 | S |
| U14 boys FL | `5f43d163-20df-43b5-91d9-8d6be8dc86db` | 48 -> 48 | 0 / 0 | 1 / 7 | S |
| U16 girls IN | `9dd5030b-346b-4afb-a780-43c17a5eb566` | 56 -> 56 | 0 / 1 | 0 / 3 | L |

The California U10 girls #1 case illustrates why a high older-opponent rank is insufficient by itself: it beat U11 girls #43 by 3-0 on August 30, but that opponent has no selected same-age final top-500 non-loss. The team also beat older final #108, #172 and #314, whose own same-age support is stronger. Those results provide context, not proof that #1 is justified. Arizona U10 boys #7 now has only one next-age final top-500 non-loss as several credited opponents receive stricter caps. U10 deserves continued caution.

The 185 previously audited credited older-opponent relationships remain preserved, with refreshed opponent ranks recorded separately. Twenty-one have qualifying games outside the selected 30 but inside the saved 365-day window. That reflects the existing broader evidence pool; this correction does not change it. Saved selected schedules also contain cross-gender rows: those are retained in the audit trail but excluded from the same-gender support counts and connectivity graph above.

## Newly entering the top 100

All 67 entrants were traced through their exact cap decision and selected opponents: 43 retain a 400 bucket, 20 retain 250 and four retain 800. Nineteen have no selected same-age/next-age final top-100 non-loss; one has none in the final top 500. These are review findings, not automatic exclusion rules. All 1,813 selected opponent relationships for the 96 reviewed teams are retained in the evidence, including game IDs, dates, scores and refreshed placements.

| Board / state | Team ID | Before -> after | Cap bucket | Same-age 100 / 500 | Older 100 / 500 |
|---|---|---:|---:|---:|---:|
| U10 boys TX | `98d83f84-f249-4130-9cfe-87dd06fbe575` | 101 -> 89 | 250 | 1 / 1 | 0 / 0 |
| U10 boys CA | `fda869ff-25e6-435e-9a37-69e01ee8175b` | 103 -> 90 | 250 | 1 / 6 | 0 / 1 |
| U10 boys NJ | `e3eb462b-39dd-415a-b1e6-1eaaea820def` | 104 -> 91 | 250 | 0 / 2 | 0 / 0 |
| U10 boys AZ | `1610353d-452e-4dc6-b210-86336395a76c` | 105 -> 92 | 250 | 0 / 0 | 0 / 2 |
| U10 boys PA | `59c331be-4628-487a-bdad-87e40f400d45` | 106 -> 93 | 250 | 1 / 1 | 0 / 0 |
| U10 boys CA | `13fdc86b-1ff5-4641-aded-4e6f781f1c75` | 107 -> 94 | 250 | 0 / 0 | 0 / 0 |
| U10 boys CA | `5efd6074-a1c6-4efc-a48f-8acbf1669288` | 108 -> 95 | 400 | 2 / 6 | 0 / 0 |
| U10 boys MN | `20c188d2-2fee-4920-990f-b22e3b507fe3` | 110 -> 96 | 400 | 0 / 3 | 0 / 0 |
| U10 boys CT | `da7fcac8-6f7c-4316-96c4-ae916590a93a` | 111 -> 97 | 800 | 0 / 1 | 0 / 0 |
| U10 boys TX | `163da59f-594b-4a6e-a6e5-bf1b2d46412e` | 113 -> 98 | 800 | 2 / 4 | 1 / 2 |
| U10 boys NY | `d82d9222-4ec5-4610-95e3-2bffed5b8fce` | 114 -> 99 | 800 | 0 / 5 | 0 / 0 |
| U10 boys NY | `bcef1126-0c33-432d-bf4e-bd6206c62db3` | 115 -> 100 | 800 | 1 / 2 | 0 / 0 |
| U10 girls OK | `65246e27-b40f-43cb-8a69-ec49d7bbe1db` | 103 -> 92 | 250 | 0 / 0 | 0 / 1 |
| U10 girls MN | `70ac7885-e6bd-45ba-9072-a5daf8006558` | 105 -> 93 | 250 | 1 / 5 | 0 / 0 |
| U10 girls MN | `c6eb9bf4-8485-4c28-b1f4-befebbe63391` | 106 -> 94 | 400 | 2 / 5 | 0 / 0 |
| U10 girls MN | `8733342e-80f2-496a-9e52-7c16692047cd` | 107 -> 95 | 400 | 2 / 3 | 0 / 0 |
| U10 girls TX | `e945f71a-2390-4e95-b7d1-a6e4eed8c9fb` | 108 -> 96 | 400 | 1 / 3 | 0 / 0 |
| U10 girls MN | `d8528d35-afe5-47a8-9a95-4e4f42726e7e` | 109 -> 97 | 250 | 1 / 6 | 0 / 0 |
| U10 girls CA | `49af4cee-aa44-4750-9a73-968c450f339a` | 110 -> 98 | 400 | 1 / 2 | 0 / 0 |
| U10 girls MN | `2c00e3ad-7ce6-4f94-a54a-b5243a31dafc` | 111 -> 99 | 400 | 2 / 5 | 0 / 1 |
| U10 girls PA | `f21fef12-6078-414e-9062-15b04202dad8` | 112 -> 100 | 250 | 1 / 3 | 0 / 0 |
| U11 boys VA | `05a7cb20-d529-4b28-a05b-ba3972963281` | 101 -> 99 | 400 | 2 / 8 | 0 / 0 |
| U11 boys OH | `de53e3d6-4e97-44a5-bf0f-0cf2fb08efd2` | 102 -> 100 | 400 | 1 / 5 | 0 / 0 |
| U11 girls OH | `879a3299-bc7a-4c51-bdc0-7178bd7e3bdd` | 101 -> 88 | 250 | 4 / 8 | 0 / 0 |
| U11 girls OH | `7c2b49a7-714c-4ef9-b9e5-a91f225ccf85` | 102 -> 89 | 250 | 0 / 3 | 1 / 9 |
| U11 girls TX | `19cfa8d3-1f45-42e7-947d-632388bf417d` | 103 -> 90 | 250 | 0 / 0 | 1 / 4 |
| U11 girls NY | `c6e7c635-6e5e-45eb-bee6-56c5bf161762` | 104 -> 91 | 400 | 1 / 3 | 1 / 1 |
| U11 girls TX | `cb1eb87f-b1d1-466b-9f7a-05ef6aab3b61` | 105 -> 92 | 250 | 1 / 3 | 0 / 1 |
| U11 girls FL | `08febb19-2d21-46a5-a952-08a8042b56e0` | 106 -> 93 | 400 | 1 / 3 | 0 / 0 |
| U11 girls FL | `3af6dbb1-9846-4682-8774-903ae368ffd5` | 107 -> 94 | 400 | 1 / 7 | 0 / 0 |
| U11 girls NJ | `43cfff01-fcd7-4a42-ae11-a181960dad23` | 108 -> 95 | 400 | 1 / 5 | 0 / 0 |
| U11 girls CT | `471cb7d3-317e-4312-9db7-dd38265a9101` | 109 -> 96 | 400 | 0 / 3 | 0 / 0 |
| U11 girls CA | `0c354093-39fa-4207-8acb-8a4b5a6eaf1e` | 110 -> 97 | 400 | 1 / 2 | 0 / 0 |
| U11 girls PA | `d5f741b2-fbe3-4f46-9720-1cc167a21dcc` | 111 -> 98 | 400 | 3 / 7 | 0 / 0 |
| U11 girls CA | `5768b260-12bb-4a20-99b5-bd6891cdef54` | 112 -> 99 | 250 | 3 / 7 | 0 / 1 |
| U11 girls TX | `0cba1363-4767-490e-8df0-df62646167a7` | 113 -> 100 | 400 | 0 / 1 | 0 / 0 |
| U12 boys CA | `ccef72a1-6957-4b4e-802a-ba5e6e49d67b` | 102 -> 95 | 250 | 0 / 5 | 0 / 0 |
| U12 boys TX | `42448923-c1a4-41aa-ba75-43d6b86b48a7` | 101 -> 99 | 400 | 4 / 6 | 0 / 0 |
| U12 boys IN | `ebb283e0-5234-4478-b50e-0cb2fe831c5f` | 103 -> 100 | 400 | 2 / 7 | 0 / 0 |
| U12 girls OH | `16772e49-4d93-4acc-8037-12ab81395200` | 101 -> 98 | 400 | 0 / 5 | 0 / 0 |
| U12 girls MA | `c914d708-da46-4348-ab5d-81aa58ebae57` | 103 -> 99 | 400 | 0 / 5 | 0 / 0 |
| U12 girls TX | `aed0ce0d-26e9-4c17-a647-b928a10fea37` | 104 -> 100 | 400 | 0 / 4 | 1 / 2 |
| U13 boys OH | `55fb3a31-2b7b-48b0-b3bd-b8d5926a7c01` | 102 -> 94 | 400 | 1 / 6 | 0 / 0 |
| U13 boys FL | `12897a41-b75e-42a5-9bea-9a4a56459845` | 101 -> 95 | 250 | 0 / 4 | 0 / 0 |
| U13 boys TX | `b2fee7fc-747e-4880-9238-c5afd2fbe3d1` | 103 -> 96 | 400 | 0 / 3 | 0 / 0 |
| U13 boys NJ | `7f7d9a3d-7e21-4b43-aea7-b696dbae4ccb` | 104 -> 97 | 400 | 3 / 7 | 0 / 1 |
| U13 boys FL | `ef1c0b51-8250-4c41-a815-4824c52467a0` | 106 -> 98 | 400 | 1 / 5 | 0 / 0 |
| U13 boys ID | `6139c04f-b518-4724-bcdf-17da65419e36` | 105 -> 99 | 250 | 0 / 4 | 0 / 0 |
| U13 boys MA | `2e24b144-8811-4a59-b3b8-1fd85e211cb2` | 107 -> 100 | 400 | 2 / 3 | 0 / 1 |
| U13 girls TX | `d4623534-11b9-400f-9bf4-328357238938` | 101 -> 95 | 400 | 1 / 3 | 0 / 0 |
| U13 girls DE | `0feb63ce-1aaa-404d-936b-fb4ba288f074` | 102 -> 96 | 400 | 0 / 5 | 0 / 0 |
| U13 girls MT | `06ff83fb-d8de-4b4d-9283-e7b59d8ceeb7` | 103 -> 97 | 400 | 2 / 2 | 0 / 0 |
| U13 girls TX | `fe883550-401f-4e96-9a75-d1054774c263` | 106 -> 98 | 400 | 1 / 6 | 0 / 0 |
| U13 girls FL | `aa5dd6e0-c7ae-4406-8345-4a07bffb365f` | 107 -> 99 | 400 | 1 / 5 | 0 / 0 |
| U13 girls CA | `4a8b211a-0a5e-408f-9723-63e6ff758338` | 109 -> 100 | 400 | 1 / 6 | 0 / 0 |
| U14 boys TX | `96a2104f-a8c5-4406-a46b-4c4977225d5d` | 101 -> 97 | 400 | 2 / 3 | 0 / 0 |
| U14 boys TX | `de306832-c91c-43d0-8b2b-0fe9efb5ccaa` | 102 -> 98 | 400 | 3 / 6 | 0 / 1 |
| U14 boys TX | `8d2ea2bc-acc9-40f3-970b-1bf99a93a8b5` | 103 -> 99 | 400 | 0 / 3 | 0 / 0 |
| U14 boys WA | `61151178-9c30-4737-af67-c409c014c809` | 104 -> 100 | 400 | 2 / 5 | 0 / 0 |
| U15 boys TX | `45552b98-2a0b-4bc2-bbb3-19d1a46c6b32` | 101 -> 100 | 400 | 1 / 5 | 0 / 0 |
| U15 girls WA | `c02f2a56-397e-4678-82bb-ba8aefe08140` | 101 -> 99 | 400 | 0 / 1 | 0 / 0 |
| U15 girls MI | `dd8e88ca-7f07-42ce-a552-83ff35faf983` | 102 -> 100 | 400 | 0 / 0 | 3 / 5 |
| U16 boys GA | `997f22fa-5bb8-4b03-9dd5-80adbf518c20` | 101 -> 96 | 250 | 2 / 8 | 0 / 0 |
| U16 boys CA | `6346673d-6dfa-4597-9813-9b18c4840de8` | 102 -> 97 | 250 | 0 / 2 | 0 / 1 |
| U16 girls CA | `3a7da08f-01de-4f6c-b081-5748ab93441c` | 101 -> 100 | 400 | 5 / 8 | 0 / 0 |
| U17 boys NY | `b65284da-800e-4238-bb4e-89b751973504` | 101 -> 100 | 400 | 1 / 5 | 0 / 0 |
| U19 boys MO | `7212c087-f1d6-4f9e-8d23-03ce36779095` | 101 -> 100 | 400 | 1 / 8 | 0 / 0 |

The California U10 boys entrant **#107 to #94** (`13fdc86b-1ff5-4641-aded-4e6f781f1c75`) is the clearest remaining weakness. Its complete saved window has 21 games: 15 same-age and six younger, with no play-up games. It lost 1-7 to final #18 and 2-5 to #15; its best selected non-loss is against #604. The existing connectivity-constrained rule grants the 250 bucket for top-100 opponent exposure, without requiring a result against that opponent. This is an existing policy limitation, not the severe-connectivity fallback bypass corrected here.

Four other entrants have no selected same-age/next-age top-100 non-loss and only one top-500 non-loss opponent: Connecticut U10 boys #97, Oklahoma U10 girls #92, Texas U11 girls #100 and Washington U15 girls #99. Their detailed schedules remain in the evidence.

All three newly flagged entrants use the preserved play-up exception. Arizona U10 boys #92 has non-losses against older #387/#412 but no older top-100 non-loss. Texas U11 girls #90 has draws against older #68, whose own schedule includes five same-age top-100 and ten top-500 non-loss opponents. Ohio U11 girls #89 has a draw against older #89, plus nine older and three same-age top-500 non-loss opponents. Across all 26 flags, the descriptive categories total **15 stronger and 11 limited**; the earlier 13/10 split refers only to the original 23.

## All 18 boards

Rank movement includes both teams receiving stricter restrictions and teams moving as others fall. Ceiling bucket numbers map to score thresholds; they are not final-rank floors.

| Board | Eligible | Stricter caps | Rank changes | Moves >100 | Moves >300 | Largest move |
|---|---:|---:|---:|---:|---:|---:|
| U10 girls | 1,046 | 41 | 332 | 25 | 0 | 183 |
| U10 boys | 1,900 | 59 | 578 | 41 | 23 | 378 |
| U11 girls | 3,220 | 188 | 629 | 36 | 8 | 338 |
| U11 boys | 5,896 | 152 | 1,026 | 46 | 36 | 599 |
| U12 girls | 3,346 | 147 | 553 | 31 | 0 | 245 |
| U12 boys | 6,126 | 170 | 1,001 | 53 | 53 | 523 |
| U13 girls | 3,553 | 154 | 515 | 32 | 0 | 250 |
| U13 boys | 6,219 | 155 | 948 | 35 | 30 | 570 |
| U14 girls | 3,245 | 124 | 496 | 25 | 0 | 250 |
| U14 boys | 5,408 | 176 | 802 | 41 | 18 | 441 |
| U15 girls | 3,008 | 95 | 485 | 22 | 0 | 219 |
| U15 boys | 4,869 | 113 | 757 | 32 | 19 | 422 |
| U16 girls | 2,300 | 48 | 453 | 10 | 0 | 215 |
| U16 boys | 3,820 | 117 | 721 | 35 | 16 | 351 |
| U17 girls | 1,800 | 37 | 383 | 16 | 0 | 228 |
| U17 boys | 2,978 | 75 | 708 | 34 | 27 | 350 |
| U19 girls | 2,645 | 58 | 457 | 14 | 0 | 256 |
| U19 boys | 4,009 | 38 | 695 | 9 | 3 | 348 |

U10 boys and girls remain separate above. No new prediction result or claim of a solved U10 quality concern is made. The original Texas U13 boys case moves #465 to #439 and original Washington U13 girls #270 to #239; both retain the 1,800 restriction. They are distinct from the additional Texas case fixed above. Florida U13 boys remains #26; California U10 boys remains #8.

## Verification, provenance and limits

Only `_publication_cap_rank` changes in the calculator AST. The offline replay reproduces every prior cap decision and final score exactly, then substitutes the corrected rule order. Every changed cap decision and every new band output is repeated exactly. All numeric caps, finite-score bounds and pre-ceiling score bounds hold; no same-ceiling ordering violation remains. Eligibility, selected games, upstream scores, explicit relief definitions and source snapshots are unchanged. No full ranking run or live database fetch was performed.

The repository diagnostic was also exercised against an offline saved-data adapter for all 27 original cases. Its legacy v53e simulator is not the current Glicko engine; its simulated values are not used as evidence. Actual conclusions use saved Glicko score layers and exact current cap traces.

- Full Python suite: **8,175 passed, 13 skipped**. Focused regressions: **152 passed**. Before the fix, 18 new cases failed and three exception/fallback controls passed.
- Python lint passed. Independent source and coverage reviews approved the change. The code comment cleanup changes no executable behavior.

[Machine-readable evidence](2026-10-07-remaining-placement-review-evidence.json) contains source/runtime/input/output hashes, all case traces, schedules, paths, cap changes and tests. Scratch scripts, logs and parquet outputs are retained at `C:\Users\Dallas Heidt\AppData\Local\Temp\pitchrank-remaining-placements-20261007`. Historical September and earlier replay reports remain intact.

Candidate calculator SHA-256: `ea56672b40503aafa32cbf2e5e7977633afb17b99eefeccdbf33992c1c9a5f2c`. Output SHA-256: `0c1af8929ef7dfbe3f85a83506d4e4e40169d279496a4b892a8400eb9ff7f7b2`.

This is evidence for a specific implementation correction, not independent validation of every model-derived rank. Remaining concerns concern relief based on strong-opponent exposure or older-opponent results, including the difference between raw evidence ranks and final opponent ranks. Changing that policy would require a separate explicit decision. Neither PR is merged or published.
