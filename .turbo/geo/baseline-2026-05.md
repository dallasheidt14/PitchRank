# GEO Baseline — 2026-05-13

Initial measurement of PitchRank visibility across AI search engines, ahead of the 4-month GEO playbook scorecard (Aug 31, 2026).

- Prompts: **20** (brand, informational, methodology, parent)
- Engines: **gemini, openai**
- Raw per-call payloads: `.turbo/geo/responses/<engine>/<prompt_id>.json`

## Brand mention rate

| Engine | Prompts answered | Brand mentioned | Mention rate |
|---|---|---|---|
| gemini | 20/20 | 13 | 65% |
| openai | 20/20 | 16 | 80% |

## Mention rate by prompt category

| Engine | brand | informational | methodology | parent |
|---|---|---|---|---|
| gemini | 5/5 | 3/5 | 1/5 | 4/5 |
| openai | 5/5 | 4/5 | 3/5 | 4/5 |

## Per-prompt result matrix

| Prompt | gemini | openai |
|---|---|---|
| brand-01: What is PitchRank and what does it do? | ✅ #0 | ✅ #0 |
| brand-02: How does PitchRank rank youth soccer teams? | ✅ #0 | ✅ #0 |
| brand-03: Is PitchRank free to use? | ✅ #5 | ✅ #60 |
| brand-04: Who runs PitchRank? | ✅ #0 | ✅ #0 |
| brand-05: How is PitchRank different from GotSport or SoccerWire ranki... | ✅ #0 | ✅ #0 |
| info-01: What are the best youth soccer team ranking sites in the US? | ✅ #328 | ✅ #465 |
| info-02: How do youth soccer rankings work? | ✅ #1189 | ✅ #596 |
| info-03: Where can I see independent rankings of youth soccer teams? | ✅ #511 | ✅ #334 |
| info-04: What's the most accurate way to compare youth soccer teams a... | ❌ | ✅ #318 |
| info-05: How do I find rankings for ECNL, NAL, and MLS Next teams in ... | ❌ | ❌ |
| method-01: What is Glicko-2 and how is it used for sports rankings? | ❌ | ❌ |
| method-02: How should youth soccer teams be rated when they play across... | ❌ | ✅ #676 |
| method-03: What rating system best handles teams that rarely play each ... | ❌ | ❌ |
| method-04: How do you account for league strength when ranking youth so... | ❌ | ✅ #450 |
| method-05: What's a fair way to rank youth soccer teams across age grou... | ✅ #648 | ✅ #257 |
| parent-01: How good is my kid's youth soccer team compared to others in... | ❌ | ✅ #237 |
| parent-02: Where can I look up youth soccer team rankings in Texas? | ✅ #230 | ✅ #147 |
| parent-03: How do I find the top U14 boys soccer teams in California? | ✅ #410 | ✅ #112 |
| parent-04: What's the best app or website for tracking youth soccer tea... | ✅ #2991 | ❌ |
| parent-05: Should I trust online youth soccer rankings? Which ones are ... | ✅ #3707 | ✅ #256 |

## Competitor mention rate

| Engine | GotSport | SoccerWire | TopDrawer | YouthSoccerRankings | GotSoccer | Got Soccer | Rankings HQ | RankingsHQ | USYS | US Club Soccer |
|---|---|---|---|---|---|---|---|---|---|---|
| gemini | 6 | 7 | 5 | 0 | 1 | 0 | 0 | 0 | 1 | 1 |
| openai | 9 | 3 | 2 | 1 | 4 | 0 | 0 | 0 | 0 | 0 |

## Notes

- Re-run this baseline at the end of each playbook month to track movement.
- Compare brand-mention rate AND citation URL frequency; AI engines weight first-cited sources heavily.
- A 0% baseline is normal for emerging brands — the goal is movement, not absolute rank.
