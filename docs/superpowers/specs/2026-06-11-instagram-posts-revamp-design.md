# Instagram Posts Revamp — Design

**Date:** 2026-06-11
**Status:** Approved by Dallas (brainstorming session with visual mockups)
**Scope:** The Instagram posts drafted by `scripts/marketing_pipeline.py` (`generate_social_posts()`). Newsletter, blog, X thread, trend posts, and the Postiz approval gate are unchanged.

## Goal

Replace the current 3-post Instagram week (rankings-live, mover spotlight, state spotlight) with a 5-post week that drops all "jumped X spots" mover claims, showcases state top-10s with team tagging, and previews ranked-vs-ranked weekend matchups.

## Weekly schedule (all drafted to Postiz, user approves before publish)

| Day | Post | Image |
|---|---|---|
| Mon 12:00 PM MT | Rankings are Live | New generic "Rankings Live" graphic |
| Tue 9:00 AM MT | State Top-10 #1 | Top-10 graphic (combo 1) |
| Tue 12:00 PM MT | State Top-10 #2 | Top-10 graphic (combo 2) |
| Tue 5:00 PM MT | State Top-10 #3 | Top-10 graphic (combo 3) |
| Thu 7:30 PM MT | Big Games This Weekend | Matchup slate graphic |

## Post 1 — Monday "Rankings are Live"

**Captions.** Both `SOCIAL_TEMPLATES["rankings_live"]` variants lose all team-specific mover claims:

- Variant 1: `New rankings are live.\n\nWhere does your team stand?\n\npitchrank.io/rankings\n\n#YouthSoccer #ClubSoccer #SoccerRankings`
- Variant 2: `Monday means new rankings.\n\n{total_teams} teams updated.\n\npitchrank.io/rankings\n\n#YouthSoccer #SoccerRankings`

`{total_teams}` is the existing live count (`rankings_full` excluding status `Not Enough Ranked Games`), formatted with thousands separators. If the count is unavailable (0/error), the count line is dropped entirely — never a made-up number. The other "25,000+" fallbacks in `marketing_pipeline.py` that feed user-facing copy get the same drop-the-line treatment.

**Image.** New `/api/infographic/rankings-live` route: generic branded "New Rankings Are Live" graphic showing the live team count and week date. Replaces the movers infographic on this post. The `if top_climber` gate around Post 1 is removed (the post no longer depends on mover data).

## Post set 2 — Tuesday State Top-10 (3 posts)

**Rotation.** Each week pick 3 combos of (state, age group, gender):

- State pool: the live state pillar list — `STATE_PILLAR_SLUGS` in `frontend/lib/cohort-seo.ts` (19 states as of 2026-06). The pipeline keeps its own mirror of this list (Python side); a comment in both files cross-references them.
- Age pool: the platform's age groups u10–u19 (no u18 — merges into u19, per `AGE_GROUPS`).
- Gender: boys/girls.
- Selection is deterministic, seeded by ISO week number: states cycle so all 19 are covered before any repeats; age and gender assignments vary week to week. `--dry-run` prints the selected combos.
- Viability: a combo needs ≥10 ranked teams in that state/age/gender; thin combos are deterministically re-picked.

**Data.** Reuse the existing `get_state_rankings(p_state, p_age, p_gender, p_limit, p_offset)` RPC — it already returns `team_id_master`, team/club names, W-L-D, `power_score_final`, `rank_in_state_final`, and `status`. Apply the existing over-fetch + `status='Active'` filter so provisional teams never appear (as `/api/infographic/state` already does). No new RPC needed. *(Amended 2026-06-12: the originally planned `get_state_top10` RPC is unnecessary — verified against `origin/main`.)*

**Graphic.** Reuse the existing `/api/infographic/state?state=&age=&gender=` next/og route on `origin/main` — it already renders "TOP 10 U{age} {GENDER} IN {STATE}" in the approved design (white+yellow PITCHRANK logo, gold/silver/bronze top-3, W-L-D + PowerScore columns) via the shared `_shared/{assets,components,theme}` modules. No new route needed. *(Amended 2026-06-12: the spec was drafted against a stale local branch; `origin/main` already has this route.)*

**Caption.** Names the cohort (e.g. "New York U14 Boys — Top 10 in the state"), link, hashtags, then @mentions for each top-10 team via the existing `enrich_post_with_handles()` + `_resolve_tag_targets()` post-pass in `scripts/marketing_pipeline.py` — team-level handle preferred, club handle as fallback, teams with neither are listed on the graphic but skipped in the mention list. Handles with `review_status` of `confirmed` **or** `auto_approved` may be mentioned (`POSTIZ_TAG_INCLUDE_AUTO_APPROVED=true`); the Postiz draft review is the human gate. *(Amended 2026-06-12: tagging machinery already exists on `origin/main`; auto-approved handles enabled per Dallas.)*

## Post 3 — Thursday "Big Games This Weekend"

**Selection.** Scan upcoming Friday–Sunday games (relative to the Thursday post date; upcoming = `game_date > today` per platform convention) across every state/age/gender. A game qualifies when **both** teams are ranked top-25 in the same state cohort. Qualifying games are ordered by combined state rank (lower sum = bigger game) and the best are taken, up to 5. The post runs with as few as 1 qualifying matchup; with 0 it is skipped for the week (no padding with weak matchups).

**Data.** New read-only RPC `get_big_weekend_games(p_start_date, p_end_date, p_rank_ceiling int default 25, p_limit int default 5)` returning, per game: both team names/clubs/team_ids, their state ranks, state, age group, gender, and game date. *(Amended 2026-06-12: no kickoff-time column exists on `games` — day labels only; state rank is computed per-candidate with a deterministic tiebreaker, mirroring the live state-rankings ordering. The RPC is called only by the pipeline with the service-role key — see Architecture.)*

**Graphic.** New `/api/infographic/big-games` next/og route: slate layout with the brand header, "BIG GAMES THIS WEEKEND" title, date range, and one row per matchup — cohort + day label (FRI/SAT/SUN), both teams with their state ranks, and the yellow circular VS badge styled after the existing Head-to-Head infographic (`HeadToHeadPreview.tsx`). *(Amended 2026-06-12: the route is a pure renderer — the pipeline passes the matchups as a base64url JSON payload in the image URL; the route makes no database call.)*

**Caption.** Hook line, then one `⚔️ @teamA vs @teamB (STATE AGE GENDER)` line per matchup (same handle precedence as the top-10 posts; teams without handles appear by name), link, hashtags.

## Architecture

- **Image generation:** new next/og edge routes alongside the existing `movers`/`spotlight`/`state` routes under `frontend/app/api/infographic/`. The rankings-live route queries via the anon key (lean count RPC); the big-games route is a **pure renderer** fed a payload by the pipeline — no database call, no timeout exposure. *(Amended 2026-06-12.)*
- **Shared data:** caption and graphic draw from one source per post — the Tuesday posts and Monday count use the same RPCs as their routes; the big-games caption and payload are built from a single RPC result in the pipeline — so caption and graphic can never disagree. *(Amended 2026-06-12.)*
- **Pipeline:** `generate_social_posts()` is rewritten around the new 5-post week. The retired `mover_spotlight` and `state_spotlight`/`data_flex` IG templates are removed along with their generation branches (after confirming no other consumer uses them).
- **Scheduling:** all posts drafted to Postiz (existing client), publish windows per the schedule table.

## Failure handling

- Thin top-10 cohort → deterministic re-pick.
- Zero qualifying weekend games → Thursday post skipped.
- Team-count query failure → count line dropped from Monday caption.
- Missing IG handle → no @mention for that team; graphic unaffected.
- A single post failing to draft does not block the other posts (matches current behavior).

## Out of scope / unchanged

Newsletter, weekly blog post, X thread, trend posts, Postiz approval gate, `POSTIZ_DRAFTS_ENABLED` kill switch, `--dry-run` flag (extended to print the week's combos and matchups).

## Verification

- `--dry-run` shows: revised Monday captions with the real count, 3 deterministic top-10 combos with captions/mention lists, and the weekend slate (or an explicit skip notice).
- New infographic routes render correctly in a browser for a known-good combo and for edge cases (long team names, 10-mention captions).
- Re-running the pipeline for the same ISO week reproduces identical combo selections.
