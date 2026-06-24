---
name: trend-research
description: "Produce the weekly PitchRank youth-soccer trend-research file (brand/trend-research/<ISO-week>.json) with source-verified, youth-centered X posts. Use when the user says \"trend research\", \"run the weekly trend-research routine\", \"trend posts\", \"weekly trend posts\", or \"last 30 days content\"."
---

# Weekly Trend Research

Generate the trend-research file the Monday marketing pipeline consumes. Work in `C:/PitchRank` on a fresh `trend-research-<ISO-week>` branch off `origin/main`.

The full procedure — rotation index, JSON schema, per-post rules, brand voice, and PR steps — lives in `docs/marketing/trend-research-routine.md`. Read that file and follow it, with the three changes below. If the file is absent on the current branch, read it from main: `git -C C:/PitchRank cat-file -p origin/main:docs/marketing/trend-research-routine.md`.

## Override 1: Research via WebSearch

The spec says research via `/last30days`. On this host that engine is key-less and TLS-blocked, so use the `WebSearch` tool instead. Load both deferred tools first: `ToolSearch` with query `select:WebSearch,WebFetch`. Open each candidate article with `WebFetch` to read it and confirm its publish date.

## Override 2: Dedup against recent published files

Before drafting, read the 3 most recent `brand/trend-research/*.json` files. Pick stories whose `source_url` and core storyline do **not** appear in them. The weekly topic rotation varies the topic, not the underlying story, so a fresh week can still surface a story already covered.

## Override 3: Confirm the non-negotiables before writing each post

The fabrication failures this routine has shipped all violated one of these. Treat each as a hard gate per post:

```
Per-post gate (all must pass):
- [ ] Youth is the SUBJECT (youth team/league/age group/national team). Pro news is a hook only.
- [ ] source_url published within the last ~30 days — verified by opening the article, not just that the link resolves.
- [ ] Every number, date, and factual claim in the tweet appears in that one source_url. No blending figures across sources.
- [ ] Speculative items framed as "linked"/"could", never as confirmed.
- [ ] < 280 chars, references rankings or pitchrank.io, brand voice per spec (esp. no "Glicko-2", no "cohort", pitchrank.io not .com).
```

If the only honest source for a story is older than ~30 days, replace the story rather than reframing the stale date as "forward-looking". If a topic yields fewer than 3 in-window youth stories, fall back to the single most-discussed youth-soccer storyline of the last 30 days (spec Step 6) rather than padding with evergreen content.

## Finish

Validate the file per spec Step 8, and confirm each per-post gate above passes. Commit and open a PR titled `trend research: <ISO-week>` per spec Step 9. Do not use `[skip ci]`.

Override the spec's auto-merge (Step 10): leave the PR for review — the operator gates every merge.
