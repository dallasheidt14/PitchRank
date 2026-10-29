# GEO Re-run — 2026-10-27

Re-run of the 2026-05-13 baseline (`baseline-2026-05.md`), same 20 prompts in `prompts.json`.

- Prompts: **20** (brand, informational, methodology, parent)
- Engines: **gemini, openai**
- Raw per-call payloads: `.turbo/geo/responses-2026-10/<engine>/<prompt_id>.json`

## Brand mention rate

| Engine | Prompts answered | Brand mentioned | Mention rate |
|---|---|---|---|
| gemini | 20/20 | 16 | 80% |
| openai | 20/20 | 17 | 85% |

## Mention rate by prompt category

| Engine | brand | informational | methodology | parent |
|---|---|---|---|---|
| gemini | 5/5 | 5/5 | 2/5 | 4/5 |
| openai | 5/5 | 5/5 | 3/5 | 4/5 |

## Per-prompt result matrix

| Prompt | gemini | openai |
|---|---|---|
| brand-01: What is PitchRank and what does it do? | ✅ #0 | ✅ #0 |
| brand-02: How does PitchRank rank youth soccer teams? | ✅ #0 | ✅ #28 |
| brand-03: Is PitchRank free to use? | ✅ #0 | ✅ #21 |
| brand-04: Who runs PitchRank? | ✅ #0 | ✅ #0 |
| brand-05: How is PitchRank different from GotSport or SoccerWire ranki... | ✅ #0 | ✅ #29 |
| info-01: What are the best youth soccer team ranking sites in the US? | ✅ #368 | ✅ #919 |
| info-02: How do youth soccer rankings work? | ✅ #459 | ✅ #2480 |
| info-03: Where can I see independent rankings of youth soccer teams? | ✅ #1016 | ✅ #927 |
| info-04: What's the most accurate way to compare youth soccer teams a... | ✅ #566 | ✅ #2215 |
| info-05: How do I find rankings for ECNL, NAL, and MLS Next teams in ... | ✅ #747 | ✅ #4491 |
| method-01: What is Glicko-2 and how is it used for sports rankings? | ❌ | ❌ |
| method-02: How should youth soccer teams be rated when they play across... | ✅ #1815 | ✅ #1589 |
| method-03: What rating system best handles teams that rarely play each ... | ❌ | ❌ |
| method-04: How do you account for league strength when ranking youth so... | ✅ #510 | ✅ #2050 |
| method-05: What's a fair way to rank youth soccer teams across age grou... | ❌ | ✅ #1123 |
| parent-01: How good is my kid's youth soccer team compared to others in... | ❌ | ✅ #1536 |
| parent-02: Where can I look up youth soccer team rankings in Texas? | ✅ #99 | ✅ #372 |
| parent-03: How do I find the top U14 boys soccer teams in California? | ✅ #176 | ✅ #503 |
| parent-04: What's the best app or website for tracking youth soccer tea... | ✅ #4153 | ❌ |
| parent-05: Should I trust online youth soccer rankings? Which ones are ... | ✅ #2915 | ✅ #3320 |

## Competitor mention rate

| Engine | GotSport | SoccerWire | TopDrawer | YouthSoccerRankings | GotSoccer | Got Soccer | Rankings HQ | RankingsHQ | USYS | US Club Soccer |
|---|---|---|---|---|---|---|---|---|---|---|
| gemini | 4 | 8 | 3 | 0 | 2 | 0 | 0 | 0 | 0 | 2 |
| openai | 5 | 2 | 2 | 1 | 3 | 0 | 0 | 0 | 9 | 0 |

## Notes

- Re-run this baseline at the end of each playbook month to track movement.
- Compare brand-mention rate AND citation URL frequency; AI engines weight first-cited sources heavily.
- A 0% baseline is normal for emerging brands — the goal is movement, not absolute rank.

## Method differences from May (read before comparing)

- **OpenAI model changed.** `gpt-4o-search-preview` is deprecated (404), so OpenAI ran on `gpt-5-search-api`. Treat the OpenAI delta as roughly flat, not a measured gain.
- **Gemini citations are resolved.** Gemini returns `vertexaisearch.cloud.google.com` redirect links, so May's data cannot show which sites were cited. This run follows each redirect to the real URL; the May Gemini citation data is not comparable.
- **Single run per engine.** One or two prompts of movement is within noise. Claude and Perplexity were not run (no keys).
- `run_baseline.py` at the repo root of this folder still has the deprecated model and the unresolved Gemini links, and it caches into `responses/`, which holds the May results. Fix those before re-running it.

## Citations of pitchrank.io (answers with at least one link)

- gemini: 17/20, openai: 17/20. Most-cited Gemini page: `/blog/youth-soccer-rankings-complete-guide` (8 answers).
- One Gemini answer cited `pitchrank.fyi`, an unrelated site.
