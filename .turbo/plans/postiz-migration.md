---
status: done
---

# Plan: Postiz Migration (Buffer + tweepy → unified Postiz drafts, with team-handle tagging)

## Context

Today's weekly marketing pipeline (`scripts/marketing_pipeline.py`, triggered by the `Calculate Rankings` workflow_run every Monday 9:45 AM MT) publishes a Beehiiv newsletter, commits a weekly blog post, schedules 3 social posts to Buffer (Instagram), and posts a 4-tweet X thread via tweepy. Two separate posting paths, two separate auth surfaces, and zero human review before posts go live.

This plan unifies social posting through Postiz hosted (Team tier, $39/mo). Every social artifact lands in Postiz as a **draft** — the user approves in the Postiz UI before the pre-set publish window fires. Adds a new weekly trend-post generator sourced from a curated `brand/trend-research/YYYY-WW.json` artifact. Adds Instagram team-handle tagging for ranking posts using the existing `team_social_profiles` enrichment pipeline (Phase 1 club handles + Phase 2 team handles, confirmed status only). Beehiiv newsletter and blog publishing steps are not touched.

**Outcomes:** one social API replaces two; native approval gate replaces "post and pray"; trend reactions become a routine output instead of ad-hoc work; tagged teams get reach + notification on Instagram; Buffer subscription can be cancelled after two clean cycles.

## Pattern Survey

**Baseline:** `HEAD` (working tree at `C:/PitchRank`). `scripts/marketing_pipeline.py` and `.github/workflows/marketing-pipeline.yml` are clean (only `.pyc` files dirty). Cited line numbers verified against current HEAD: `main()` at 1091, dry-run block 1149-1170, Buffer block 1187-1192, tweepy block 1194-1200, summary 1203-1210, exit-code 1214. Re-verify by `grep -n "^def\|^if args.dry_run" scripts/marketing_pipeline.py` before edits — if main() has shifted by more than ~5 lines, the implementer should re-anchor each cited line range.

### Analogous Features
- `scripts/marketing_pipeline.py:378-410` — `publish_to_beehiiv()`: idiomatic Bearer-auth REST POST. Reads API key from env, builds JSON payload, single `requests.post(..., timeout=60)`, accepts `(200, 201)`, logs response body trimmed to 500 chars on failure. **This is the closest model for a Postiz `POST /posts` draft call.**
- `scripts/marketing_pipeline.py:351-375` — `get_beehiiv_publication_id()`: env-first lookup with REST fallback (`GET /publications`) plus `raise_for_status()`. Mirrors how a Postiz "fetch integrations to draft into" lookup should work.
- `scripts/marketing_pipeline.py:843-859` — `get_buffer_profiles()`: query-param token auth (legacy Buffer style); explicit `if resp.status_code != 200: log.error ... return []` early-out. To be DELETED.
- `scripts/marketing_pipeline.py:862-907` — `schedule_to_buffer()`: per-post loop with form-encoded multi-value (`profile_ids[]`), UTC ISO timestamp formatting, per-post boolean result list returned to orchestrator. **The "per-post result list" return shape is the contract `main()` relies on (line 1190, 1208).** To be REPLACED by a Postiz draft loop.
- `scripts/marketing_pipeline.py:915-937` — `get_x_client()`: OAuth1 tweepy client builder; returns `None` on missing creds so caller short-circuits. To be DELETED.
- `scripts/marketing_pipeline.py:958-1032` — `generate_thread_tweets()`: builds `list[str]` (one entry per tweet); milestone-driven, falls back to generic CTA. **Output shape (list of strings) needs to be reconciled with Postiz dict shape** if X content collapses into the unified draft path.
- `scripts/marketing_pipeline.py:1035-1059` — `post_thread_to_x()`: chained `in_reply_to_tweet_id` loop; honors `dry_run`, returns single bool. To be REPLACED.
- `scripts/marketing_pipeline.py:755-835` — `generate_social_posts()`: returns `list[dict]` with keys `{"text", "media_url", "scheduled_at" (datetime), "type"}`. **This is the canonical post-shaped dict in the codebase. The trend-posts generator should mirror this shape exactly.** Note `scheduled_at` is a `datetime` (tz-aware) — `save_artifacts` calls `.isoformat()` on it (line 1084).
- `scripts/backfill_beehiiv_lifecycle.py:95-134` — same `requests` + Bearer pattern as Beehiiv publish, second confirmation of the convention.

### Reusable Utilities
- `scripts/marketing_pipeline.py:36-37` — `requests` + `markdown` (already imported, no need for new HTTP lib).
- `scripts/marketing_pipeline.py:49` — `MT_OFFSET` Mountain Time tz constant for `scheduled_at` datetimes.
- `scripts/marketing_pipeline.py:940-955` — `_format_cohort()` / `_milestone_line()`: text formatters reusable for trend-post body composition.
- `scripts/marketing_pipeline.py:1067-1088` — `save_artifacts()`: writes `newsletter_*.html` + `social_posts_*.json` to `artifacts/`. **Already serializes the canonical post dict shape**; trend posts should flow through this if they reuse the dict shape, otherwise add a parallel serializer.
- `scripts/marketing_pipeline.py:63-73` — `get_supabase_client()`: standard env loader (relevant if trend posts need to enrich with team data).

### Convention Anchors
- **REST client convention**: bare `requests.{get,post}` with explicit `timeout=`, `headers={"Authorization": f"Bearer {key}", ...}`, accept `(200, 201)`, log `resp.text[:300-500]` on failure. No retries, no backoff anywhere in `marketing_pipeline.py`. No shared HTTP helper class. (`scripts/marketing_pipeline.py:363, 394, 850, 894`). **Postiz diverges only on auth: header is the raw key, no `Bearer` prefix.**
- **API constants at module top**: `BUFFER_API_URL`, `BEEHIIV_API_URL` defined near imports (line 52-55). New `POSTIZ_API_URL` constant should sit alongside; `BUFFER_API_URL` deleted.
- **Env-var auth, no client SDK preference**: Beehiiv uses raw REST + key; tweepy is the only SDK and it's slated for removal. Direction is toward fewer SDKs — Postiz uses `requests` directly, no `@postiz/node` equivalent in Python.
- **GitHub Actions workflow shape** (`marketing-pipeline.yml:55-82`): every secret passed via `env:` block in the run step; `DRY_RUN` mapped from `workflow_dispatch.inputs.dry_run` to a `--dry-run` flag; dependencies installed inline (`pip install ... tweepy ...`) — no `requirements.txt`. **`tweepy` should be removed from the pip line; no new dep needed for Postiz (uses `requests`).** Workflow is currently disabled (`if: false` at line 23) — see Step 9 for the gate-handling decision (leave disabled in this PR; one-line follow-up PR after two clean cycles).
- **No "draft-only" / "manual approval gate" pattern exists** in any marketing workflow. The Postiz draft model itself becomes the gate (no GHA env-protection rules needed).
- **Orchestrator step-failure pattern** (`scripts/marketing_pipeline.py:1091-1214`): each step wrapped in `try/except` with `log.error(...)` continuation; failures degrade gracefully (set local bool/list to falsy default and proceed). Final exit code is 0 unless BOTH newsletter AND all social posts fail (line 1214). **`--dry-run` flow:** all generators run, `save_artifacts` runs at line 1147, then `if args.dry_run:` (line 1149) logs each `social_posts` entry + each `thread_tweets` entry via `log.info` (lines 1158-1168), then `return` at line 1170 — no API calls made. The live branch (lines 1172+) calls Beehiiv → blog → `schedule_to_buffer` → `post_thread_to_x`. **Postiz draft calls must still respect `--dry-run`** (a draft created via API is a real record). This plan threads `dry_run=args.dry_run` into `draft_to_postiz` and places the call *before* the dry-run gate so the same code path runs in both modes — see Step 6.
- **Pipeline summary block** (lines 1203-1210): each step reported as `NAME: STATUS`. Replace the two existing "Social: ..." and "X Thread: ..." lines with a single unified `Social Drafts: N/M drafted to Postiz` line (drafts count includes IG + trend + X-thread).
- **Artifacts contract** (`save_artifacts`, line 1067): always saves both HTML + JSON, regardless of dry-run, before any API calls. Trend-post output should be appended to the same `social_posts_*.json` artifact (single canonical dict shape).

### `last30days` Integration — Greenfield
- **No PitchRank code consumes `last30days`.** Grep returned only unrelated `"last 30 days"` strings in admin metrics and the report-card spec.
- **Decision (Step 4):** curated checked-in research artifact at `brand/trend-research/YYYY-WW.json`. Mirrors `brand/blog-topics.json` pattern at line 421. User runs `/last30days` manually weekly and writes the JSON. Pipeline reads the latest file matching the current ISO week.

### Postiz Scaffolding
- **None.** Case-insensitive grep across the entire repo returned zero matches. Greenfield.

### Proposed Alignment
Follow `publish_to_beehiiv` REST pattern verbatim for Postiz draft calls: module-level `POSTIZ_API_URL` constant, `requests.post` with raw-key auth + 60s timeout, accept `(200, 201)`, log `resp.text[:500]` on failure, return per-post `(success, postId)` tuples. Mirror `generate_social_posts`'s `list[dict]` shape (`text`, `media_url`, `scheduled_at` datetime, `type`) for the new `generate_trend_posts(...)` so it flows through `save_artifacts` unchanged. Add a single translator at the publisher boundary (`_to_postiz_payload`) so generators stay platform-agnostic. Delete `get_buffer_profiles`, `schedule_to_buffer`, `get_x_client`, `post_thread_to_x`, `generate_thread_tweets`, and the `BUFFER_*` / `X_*` envs from the workflow. Replace tweepy `pip install` with nothing (Postiz uses `requests`, already pinned).

## Local-State Hazards

Before editing:
- **Branch from `origin/main`.** Run `git fetch origin && git switch -c postiz-migration origin/main` so the work doesn't inherit local dirty state. Per memory `env_cwd_resets.md`, always prefix shell commands with `cd C:/PitchRank &&`.
- **Verify working tree is clean against the new branch** with `git status --porcelain | grep -v '\.pyc$'` — expect zero lines. The survey baseline assumed only `.pyc` files were dirty; if `marketing_pipeline.py` or the workflow shows local edits, stash or commit before starting.
- **Memory `feedback_verify_branch.md` applies.** Confirm `git rev-parse --abbrev-ref HEAD == postiz-migration` after every shell-reset interruption before committing.

## Implementation Steps

1. **Add Postiz module constants and integration lookup**
   - At top of `scripts/marketing_pipeline.py`, alongside `BEEHIIV_API_URL` (line 52-55): add `POSTIZ_API_URL = "https://api.postiz.com/public/v1"`. Delete `BUFFER_API_URL`.
   - Add helper `get_postiz_integrations() -> dict[str, str]`: `GET {POSTIZ_API_URL}/integrations` with `headers={"Authorization": os.getenv("POSTIZ_API_KEY")}` (raw key, no `Bearer`) and `timeout=60`. Returns `{"x": "<integration_id>", "instagram": "<integration_id>"}` by filtering response for `identifier in ("x", "instagram")`.
   - **Fail-loud semantics:** on non-200, `log.error(f"Postiz integrations fetch failed ({resp.status_code}): {resp.text[:500]}")` and return `{}` (caller treats as total publisher failure). On 200 but missing either `"x"` or `"instagram"`: `log.error(f"Postiz integrations missing required platform(s): {missing}")` and return only the platforms that were found. The router in Step 5 then logs an ERROR for every post that would have routed to a missing channel and appends `False` to the result list, so a partially-discovered integration set surfaces in the exit-code logic (Step 6) rather than silently dropping a channel.
   - **Preserve from current file**: all imports (line 1-50), `MT_OFFSET` (line 49), `BEEHIIV_API_URL`, `BEEHIIV_PUBLICATION_ID` env handling, every other constant.

2. **Add `generate_trend_posts(week_iso: str, data: dict) -> list[dict]`**
   - New function inserted *after* `generate_social_posts` (which ends at line 835) — placement adjacent to other generators, around line 836. (Note: `generate_blog_post` at line 576 is *before* `generate_social_posts`, not after.)
   - Reads `brand/trend-research/{week_iso}.json` (e.g., `2026-W23.json`).
   - **Validation (ERROR-level for the failure modes that should surface in exit-code):**
     - Missing file: `log.error(f"Trend research file missing for {week_iso}: brand/trend-research/{week_iso}.json")`, return `[]`. Caller (`main()`) treats empty trend set as a failed deliverable: contributes a sentinel `False` to `draft_results` via Step 7's exit-code logic.
     - Malformed JSON (parse exception): `log.error(...)`, return `[]`.
     - Week mismatch (`payload.get("week") != week_iso`): `log.error(f"Trend research week mismatch: expected {week_iso}, got {payload.get('week')}")`, return `[]` (stale file, user forgot to update).
     - Per-entry: each must have non-empty string `suggested_tweet`. Skip entries that fail; log warning per skipped entry. If all entries fail validation, return `[]`.
   - Expected JSON schema (this becomes the user's authoring contract):
     ```json
     {
       "week": "2026-W23",
       "posts": [
         { "topic": "ECNL national rankings drop", "hook": "...", "suggested_tweet": "...", "source_url": "https://..." }
       ]
     }
     ```
   - For each valid entry, emit a dict matching the canonical `generate_social_posts` shape: `{"text": suggested_tweet, "media_url": None, "scheduled_at": <datetime>, "type": "trend"}`. Schedule across the week: post 1 → Wed 12:30 PM MT, post 2 → Fri 9:00 AM MT, post 3 → Sat 11:00 AM MT (using `MT_OFFSET` at line 49).
   - Cap at 3 posts. If JSON has more valid entries, log a warning and take the first 3.

3. **Add `generate_x_thread_posts(data: dict) -> dict`**
   - Rename and reshape `generate_thread_tweets` (line 958-1032) to return a single dict (not a list — Step 7's `[x_thread_post]` wrapping relies on this) with all thread entries in the canonical shape:
     ```python
     {"text": "<tweet 1>\n---\n<tweet 2>\n---\n<tweet 3>\n---<tweet 4>", "media_url": None, "scheduled_at": <Mon noon MT>, "type": "x_thread", "thread_parts": ["<t1>", "<t2>", "<t3>", "<t4>"]}
     ```
   - The `thread_parts` field is the X-thread-specific extension. The translator (Step 5) consumes `thread_parts` for X and ignores it for Instagram.
   - Reuse the existing thread-composition logic verbatim (milestone-driven, generic CTA fallback) from lines 958-1032; only the return shape changes.

4. **Add `_to_postiz_payload(post: dict, integration_id: str, platform: str) -> dict` translator**
   - New private helper near the Postiz publisher.
   - For `platform == "x"` and `post.get("thread_parts")`: emit `value` as `[{"content": t, "image": []} for t in post["thread_parts"]]`, `settings = {"__type": "x", "who_can_reply_post": "everyone"}`.
   - For `platform == "x"` without `thread_parts` (trend posts): emit `value` as `[{"content": post["text"], "image": []}]`, same settings.
   - For `platform == "instagram"`: emit `value` as `[{"content": post["text"], "image": [{"path": post["media_url"]}] if post.get("media_url") else []}]`, `settings = {"__type": "instagram", "post_type": "post", "is_trial_reel": False, "collaborators": []}`.
   - Wrap each in the full request envelope: `{"type": "draft", "date": post["scheduled_at"].isoformat(), "shortLink": False, "tags": [], "posts": [{"integration": {"id": integration_id}, "value": ..., "settings": ...}]}`.

5. **Add `draft_to_postiz(posts: list[dict], integrations: dict[str, str], dry_run: bool) -> list[bool]`**
   - **Prerequisite — fix `mover_spotlight` IG asset (line 801):** change `f"{PITCHRANK_URL}/api/infographic/spotlight?platform=twitter"` to `f"{PITCHRANK_URL}/api/infographic/spotlight?platform=instagram"`. The router below sends `mover_spotlight` to Instagram; a twitter-targeted asset URL would render with wrong dimensions in the IG draft. Fix at the source so the translator stays platform-agnostic.
   - Inserted where `schedule_to_buffer` lives (replace lines 843-907 entirely).
   - **Routing rule** (explicit, default-case design — not an allowlist):
     - `post["type"] in ("x_thread", "trend")` → X integration (`integrations.get("x")`)
     - All other types route to Instagram integration (`integrations.get("instagram")`). For reference, current types emitted by `generate_social_posts` are `"rankings_live"`, `"mover_spotlight"`, `"state_spotlight"`, `"data_flex"`. New types added later automatically route to IG via the default case — no router changes needed unless they target X.
   - If the routed integration is missing (e.g., `integrations.get("x")` is `None`): `log.error(f"No Postiz integration for routed platform; skipping [{post['type']}]")`, append `False` to result list. This contributes to the exit-code logic in Step 7 — partial discovery does not exit 0.
   - On `dry_run=True`: **silently** append `True` to result list without calling the API and without per-post logging. The caller (`main()` dry-run block) already emits a human-readable per-post preview AND an aggregate "N/M would be drafted" line — adding per-post Postiz payload logs here would triple-log every post. Implementer can opt into payload logging behind a `POSTIZ_DRY_RUN_VERBOSE` env var if needed for debugging, but the default is silent.
   - On live call: `requests.post(f"{POSTIZ_API_URL}/posts", headers={"Authorization": os.getenv("POSTIZ_API_KEY"), "Content-Type": "application/json"}, json=_to_postiz_payload(...), timeout=60)`. Accept `(200, 201)`. On non-2xx: `log.error(f"Postiz draft failed [{post['type']}] ({resp.status_code}): {resp.text[:500]}")`, append `False`.
   - Return `list[bool]` — same contract as the old `schedule_to_buffer` so `main()`'s summary block (line 1203-1210) needs minimal change.

6. **Add `enrich_post_with_handles(post: dict, supabase, target_team_ids: list[str]) -> dict`**

   **6a. Hard prerequisite — extend the `get_biggest_movers` RPC to return `team_id`.**
   The current RPC at `supabase/migrations/20260308000000_filter_biggest_movers_min_games.sql:12-18` returns only `(team_name, club_name, state_code, rank_change, current_rank)`. Without `team_id`, every enrichment wiring snippet below KeyErrors on first call.
   - Create new migration `supabase/migrations/<YYYYMMDD>_add_team_id_to_get_biggest_movers.sql`.
   - `CREATE OR REPLACE FUNCTION get_biggest_movers(...)` matching the existing signature, but extend `RETURNS TABLE (...)` with `team_id UUID` (sourced from `rf.team_id`, which is `teams.team_id_master` per memory `gotcha_rankings_full_fk_team_id_master.md`).
   - Add `rf.team_id AS team_id` to the SELECT list.
   - Apply via `npx supabase db push` (or via the MCP `apply_migration` tool).
   - **Verify** with `SELECT team_id, team_name FROM get_biggest_movers(...) LIMIT 1;` — expect a non-null UUID.
   - After RPC ships, `data["climbers"]`, `data["fallers"]`, and `data["spotlight_teams"]` (all populated from this RPC at `fetch_ranking_highlights`) will carry a `team_id` field. No Python-side change to `fetch_ranking_highlights` is needed — it forwards the row dicts unchanged.

   **6b. New function placed near `generate_social_posts` (around line 836, alongside other generators).**
   - **Query:** `supabase.from_("team_instagram_handles").select("team_id, handle, profile_level").in_("team_id", target_team_ids).eq("review_status", "confirmed").execute()`. Note: `team_instagram_handles` view (per `supabase/migrations/20260314000002_add_profile_level_to_social_profiles.sql:48`) exposes `review_status` and pre-filters to `auto_approved OR confirmed`; the further `.eq("review_status", "confirmed")` is the v1 safety filter (only human-verified handles get tagged).
   - **Threshold env override:** `os.getenv("POSTIZ_TAG_INCLUDE_AUTO_APPROVED", "false").lower() == "true"` widens to `("confirmed", "auto_approved")` via `.in_("review_status", ...)` if needed later. Default off.
   - **Handle preference:** for each `team_id`, prefer `profile_level == "team"`, fall back to `profile_level == "club"` — mirror `frontend/hooks/useInstagramHandles.ts:collectHandlesForCaption`. Dedupe by lowercased handle.
   - **Caps:** max 10 @-mentions per caption (IG hard limit is 20; 10 keeps it natural). If caption + tag block would exceed 2,200 chars (IG limit), truncate handle list to fit and log warning with dropped count.
   - **Mutation:** appends `\n\nTagging: @h1 @h2 @h3` to `post["text"]`. Skips silently if no handles found.
   - **Tag stats:** writes `post["_tag_stats"] = {"tagged_count": N, "target_count": len(target_team_ids), "missing_team_ids": [...]}` — preserved through `save_artifacts` (see Step 8) for review and enrichment-coverage feedback.
   - **Failure mode:** Supabase query exception → log warning, write `post["_tag_stats"] = {"tagged_count": 0, "target_count": len(target_team_ids), "error": str(e)}`, return post unchanged (don't fail the whole pipeline over missing tags).

   **6c. Wiring location — post-pass in `main()`, NOT inside `generate_social_posts`.**
   `generate_social_posts(data: dict)` (line 755) is a pure synchronous generator with no Supabase dependency. Keeping it pure matches the "generators stay platform-agnostic" principle from Proposed Alignment. Enrichment runs as a post-pass after the generator call. Add to `main()` (see Step 7) immediately after `social_posts = generate_social_posts(data)`:
   ```python
   # Resolve target team IDs per post type and enrich captions with IG handles.
   for post in social_posts:
       targets = _resolve_tag_targets(post["type"], data)
       if targets:
           enrich_post_with_handles(post, supabase, targets)
   ```
   And add the resolver helper near `enrich_post_with_handles`:
   ```python
   def _resolve_tag_targets(post_type: str, data: dict) -> list[str]:
       if post_type == "rankings_live":
           return [c["team_id"] for c in data["climbers"][:3] if c.get("team_id")]
       if post_type == "mover_spotlight":
           target = data["climbers"][1] if len(data["climbers"]) > 1 else (data["climbers"][0] if data["climbers"] else None)
           return [target["team_id"]] if target and target.get("team_id") else []
       if post_type == "state_spotlight":
           return [t["team_id"] for t in (data.get("spotlight_teams") or [])[:3] if t.get("team_id")]
       return []  # data_flex, x_thread, trend — no tagging
   ```

   **6d. Coordination with Step 5's `mover_spotlight` asset fix.**
   Step 5 prescribes editing `mover_spotlight`'s `media_url` (line 801) `platform=twitter` → `platform=instagram`. Step 6's wiring tags the same post via the post-pass above. Both edits land in different files (Step 5 = `generate_social_posts` at line 798-805; Step 6 = new helper + `main()` wiring). No conflict; apply Step 5 first, then Step 6's helpers, then Step 6's wiring in `main()`.

   **6e. Dry-run contract clarification.**
   The "no API calls made" log line at line 1169 means **no Postiz API calls** — Supabase reads were always allowed in dry-run (`fetch_ranking_highlights` at line 1103 runs unconditionally). Enrichment Supabase queries during dry-run are intentional: they let Verification Step 1's tag-coverage check run against real handle data without touching Postiz. Document this scope explicitly in the dry-run log block summary.

7. **Update `main()` orchestrator (lines 1091-1214)**
   - **Derive ISO week** between current line 1135 (after data fetch / blog generation) and the new draft branch:
     ```python
     current_iso_week = data["date"].strftime("%G-W%V")
     ```
     `%G`/`%V` are ISO year and ISO week, avoiding the year-boundary off-by-one bug `%Y`/`%U` introduces (e.g., 2025-12-30 is ISO week 2026-W01).
   - **Replace the entire "Step 4 + Step 5" block (lines 1136-1144)** — the existing `social_posts = generate_social_posts(data)` and `thread_tweets = generate_thread_tweets(data)` — with a single kill-switch-gated draft-prep block. This guards ALL generators (social, X thread, trend) and the integrations lookup behind one flag, so flipping `POSTIZ_DRAFTS_ENABLED=false` actually skips everything:
     ```python
     # Step 4-5: Generate all social drafts (kill-switch gated)
     drafts_enabled = os.getenv("POSTIZ_DRAFTS_ENABLED", "true").lower() == "true"
     if drafts_enabled:
         social_posts = generate_social_posts(data)
         # Enrich IG-bound posts with team handles (Step 6c post-pass)
         for post in social_posts:
             targets = _resolve_tag_targets(post["type"], data)
             if targets:
                 enrich_post_with_handles(post, supabase, targets)
         x_thread_post = generate_x_thread_posts(data)
         trend_posts = generate_trend_posts(current_iso_week, data)
         all_drafts = social_posts + [x_thread_post] + trend_posts
     else:
         log.warning("POSTIZ_DRAFTS_ENABLED=false — skipping social drafts entirely")
         social_posts, all_drafts = [], []
         x_thread_post = {"thread_parts": []}  # sentinel for existing dry-run log block
     ```
     Note the `x_thread_post` sentinel: it satisfies the rewritten dry-run log block below without leaking into actual Postiz drafts (already gated by `all_drafts = []`).
   - **Move + retarget `save_artifacts` call (currently line 1147)**: must come *after* `all_drafts` is built; pass `all_drafts` instead of `social_posts`: `save_artifacts(newsletter_html, all_drafts, data)`. See Step 8 for serializer changes that make this safe.
   - **Rewrite the existing dry-run log block (lines 1158-1168)** because `thread_tweets` is gone after Step 3's rename. The old loop at lines 1164-1168 iterating `thread_tweets` becomes:
     ```python
     for post in social_posts:
         log.info(f"[{post['type']}] {post['scheduled_at'].strftime('%A %I:%M %p MT')}")
         if post.get("media_url"):
             log.info(f"  Image: {post['media_url']}")
         log.info(post["text"])
         log.info("")
     if x_thread_post.get("thread_parts"):
         log.info("--- X THREAD ---")
         for i, tweet in enumerate(x_thread_post["thread_parts"]):
             log.info(f"Tweet {i + 1}/{len(x_thread_post['thread_parts'])}: {tweet}")
             log.info("")
     ```
     This is the human-readable preview — it stays. The new Postiz-payload preview (next bullet) is the only network-respecting check.
   - **Add Postiz dry-run summary AFTER the existing dry-run logs, before the `return`** at line 1170 (still BEFORE leaving the dry-run gate). To avoid the zero-network-in-dry-run regression and double-logging, pass a sentinel integrations dict and tell `draft_to_postiz` to skip per-post logging:
     ```python
         # New Postiz dry-run preview (after the existing human-readable preview above):
         if drafts_enabled:
             stub_integrations = {"x": "DRY_RUN_X_ID", "instagram": "DRY_RUN_IG_ID"}
             draft_results = draft_to_postiz(all_drafts, stub_integrations, dry_run=True)
             log.info(f"DRY RUN: {sum(draft_results)}/{len(draft_results)} would be drafted to Postiz")
         log.info("Artifacts saved. No API calls made.")
         return
     ```
     **Tighten the existing "no API calls made" log line** (currently line 1169) to clarify the Postiz-only scope per Step 6e: replace with `log.info("Artifacts saved. No Postiz API calls made (Supabase reads ran for data fetch + handle enrichment).")`. This way an operator reading dry-run output knows enrichment-coverage data in `_tag_stats` was sourced from real Supabase queries, not stubbed.
     Stub integration IDs keep dry-run zero-network for Postiz. **Update Step 5** (already done) to make `draft_to_postiz(dry_run=True)` log only the aggregate count, NOT per-post payloads (silences the double-log). Per-post logs come from the existing human-readable block above.
   - **Replace the Buffer block at lines 1187-1192** with the live Postiz call (live branch — `get_postiz_integrations` runs HERE, not before the dry-run gate, preserving the zero-network dry-run contract):
     ```python
     draft_results = []
     try:
         if drafts_enabled:
             integrations = get_postiz_integrations()
             draft_results = draft_to_postiz(all_drafts, integrations, dry_run=False)
     except Exception as e:
         log.error(f"Postiz drafting failed: {e}")
     ```
   - **Delete the entire tweepy X-thread block** at lines 1194-1200 (the `try: post_thread_to_x(thread_tweets)` wrapper). Confirm with `grep -n "post_thread_to_x\|get_x_client\|generate_thread_tweets\|thread_tweets" scripts/marketing_pipeline.py` returns zero matches after edits.
   - **Update the summary block (lines 1203-1210):** replace the two-line "Social: ..." + "X Thread: ..." with a single line: `log.info(f"  Social Drafts: {sum(draft_results)}/{len(draft_results)} drafted to Postiz")`.
   - **Update exit-code logic (line 1214):** `if not newsletter_ok and not any(draft_results): sys.exit(1)`. **Deliberate behavior change:** the old logic checked only `buffer_results` (Instagram), so X-thread failures were invisible to the exit code. The new logic counts X drafts, IG drafts, and trend drafts equally — a failed X thread now contributes to exit-code 1 (which is the desired safety after collapsing two paths into one).
   - **Preserve from current `main()`:** Beehiiv newsletter call (line 1175), blog-post commit-and-push step (line 1183), `args.dry_run` parsing at top (line 1094), all existing log lines, the `if not data["climbers"]...` early-exit at lines 1109-1111.

8. **Update `save_artifacts` (line 1067-1088) — hard prescription**
   - **Signature stays the same** (`save_artifacts(newsletter_html, social_posts, data)`); the *caller* now passes `all_drafts` as the second arg (see Step 7).
   - **Rename the parameter** `social_posts` → `drafts` inside the function body for clarity.
   - **Extend the per-post dict construction** (the loop that builds entries around lines 1071-1086, currently emitting `{type, text, media_url, scheduled_at}`):
     ```python
     entry = {
         "type": p["type"],
         "text": p["text"],
         "media_url": p.get("media_url"),
         "scheduled_at": p["scheduled_at"].isoformat(),
     }
     if p.get("thread_parts"):
         entry["thread_parts"] = p["thread_parts"]
     if p.get("_tag_stats"):
         entry["_tag_stats"] = p["_tag_stats"]
     serializable.append(entry)
     ```
     This preserves the per-tweet split in the saved JSON artifact so X-thread review during approval has all 4 tweets visible.
   - **Verify** with `python -c "import json,glob; data=json.load(open(sorted(glob.glob('artifacts/social_posts_*.json'))[-1])); print([e for e in data if 'thread_parts' in e])"` after a dry-run — output should contain exactly one entry (the X thread) with a 4-string `thread_parts` array.

9. **Delete dead code**
   - Remove `get_buffer_profiles` (line 843-859).
   - Remove `schedule_to_buffer` (line 862-907) — the entire function, the `BUFFER_API_URL` constant already deleted in Step 1.
   - Remove `get_x_client` (line 915-937).
   - Remove `generate_thread_tweets` (line 958-1032) — superseded by `generate_x_thread_posts`.
   - Remove `post_thread_to_x` (line 1035-1059).
   - Remove `import tweepy` (and any tweepy-related top-level imports).
   - Memory check (`feedback_init_exports.md`): `scripts/__init__.py` doesn't re-export from `marketing_pipeline`, but grep `from scripts.marketing_pipeline import\|from marketing_pipeline import` across the repo to confirm no other module references the deleted symbols.

10. **Update `.github/workflows/marketing-pipeline.yml`**
   - **Replace `if: false` (line 23)** with `if: github.event_name == 'workflow_dispatch'`. Rationale: job-level `if: false` is a constant that skips the job regardless of trigger (verified against GitHub Actions docs — `workflow_dispatch` is also skipped). The conditional form blocks the auto `workflow_run` trigger from Calculate Rankings (so the pipeline doesn't fire automatically before validation) while still allowing manual `gh workflow run` for smoke testing. After two successful cycles, the follow-up PR removes this `if:` line entirely.
   - Remove from `env:` block (line 70-74): `BUFFER_ACCESS_TOKEN`, `X_CONSUMER_KEY`, `X_CONSUMER_SECRET`, `X_ACCESS_TOKEN`, `X_ACCESS_TOKEN_SECRET`.
   - Add to `env:` block: `POSTIZ_API_KEY: ${{ secrets.POSTIZ_API_KEY }}`.
   - Update `pip install` line (line 58): remove `tweepy`. Keep `supabase python-dotenv requests rich markdown`.
   - **Workflow gate decision:** see the first bullet in this step — `if: false` becomes `if: github.event_name == 'workflow_dispatch'` so manual dispatch works for smoke testing while auto-trigger stays blocked. After two successful live cycles (per Verification Step 5), open a one-line follow-up PR to remove the `if:` line entirely and re-enable automatic Monday-after-rankings triggers.
   - **Also add to `env:` block:** `POSTIZ_DRAFTS_ENABLED: ${{ vars.POSTIZ_DRAFTS_ENABLED || 'true' }}` so the kill switch from Step 7 can be flipped via a repo variable without a code push. Default `'true'` (drafts enabled).
   - **Preserve from current workflow**: `on:` block (`workflow_run` trigger from Calculate Rankings + `workflow_dispatch` with `dry_run` input), `BEEHIIV_API_KEY` env, `SUPABASE_URL` / `SUPABASE_SERVICE_ROLE_KEY` envs, the python setup steps, the `[skip ci]` blog-commit step, the artifact upload step, every other unchanged top-level key.

11. **Add `POSTIZ_API_KEY` to GitHub Secrets — ALREADY DONE 2026-06-02**
    - Key set in GH Secrets (verify with `gh secret list --repo dallasheidt14/PitchRank | grep POSTIZ`).
    - Key also written to local `C:/PitchRank/.env` (gitignored).
    - Postiz MCP server registered locally; available next Claude Code session.
    - Do NOT remove `BUFFER_ACCESS_TOKEN` and `X_*` secrets from GitHub yet — leave them for one cycle as rollback insurance. After Verification confirms two successful weekly drafts, **explicitly ask the user before** running `gh secret delete` (destructive op per memory `feedback_no_merge_without_approval.md`). Do not run autonomously.

12. **Create initial `brand/trend-research/` directory + this week's seed file**
    - `mkdir -p brand/trend-research`
    - Create `brand/trend-research/<current-iso-week>.json` (e.g., `2026-W23.json`) with one stub entry. This serves as both the schema example and the smoke-test input.
    - Add `brand/trend-research/.gitkeep` so the directory survives empty weeks.

13. **Update memory file `marketing-pipeline.md`**
    - Path: `C:/Users/Dallas Heidt/.claude/projects/C--Users-Dallas-Heidt/memory/marketing-pipeline.md`.
    - Rewrite step 6 to: "Drafts X thread + Instagram posts (with team-handle tagging from `team_instagram_handles`) + trend posts to **Postiz** (draft status; user approves in Postiz UI)."
    - Remove step 7 (X tweepy is gone — collapsed into step 6).
    - Update "Social posting split" line: "Unified via Postiz — X + Instagram both drafted as Postiz posts. tweepy + Buffer removed."
    - Update "GitHub Secrets needed": replace X_* and BUFFER_ACCESS_TOKEN with `POSTIZ_API_KEY`.

14. **Wire brand fonts + logo into `@vercel/og` infographic endpoints**

    Visual polish so weekly autogenerated images match the brand system used in `campaigns/creative/` heroes. Assets already exist and deploy with the Next.js app — no new files needed.

    **14a. Add shared loader helpers** (new file `frontend/app/api/infographic/_shared/assets.ts`):
    ```ts
    const ORIGIN = process.env.NEXT_PUBLIC_SITE_URL || 'https://pitchrank.io';

    export async function loadBrandFonts() {
      const [oswaldBold, oswaldReg, dmSansBold, dmSansReg] = await Promise.all([
        fetch(`${ORIGIN}/fonts/Oswald-Bold.woff`).then(r => r.arrayBuffer()),
        fetch(`${ORIGIN}/fonts/Oswald-Regular.woff`).then(r => r.arrayBuffer()),
        fetch(`${ORIGIN}/fonts/DMSans-Bold.woff`).then(r => r.arrayBuffer()),
        fetch(`${ORIGIN}/fonts/DMSans-Regular.woff`).then(r => r.arrayBuffer()),
      ]);
      return [
        { name: 'Oswald', data: oswaldBold, weight: 700 as const, style: 'normal' as const },
        { name: 'Oswald', data: oswaldReg, weight: 400 as const, style: 'normal' as const },
        { name: 'DM Sans', data: dmSansBold, weight: 700 as const, style: 'normal' as const },
        { name: 'DM Sans', data: dmSansReg, weight: 400 as const, style: 'normal' as const },
      ];
    }

    export const LOGO_URL = `${ORIGIN}/logos/logo-primary.svg`;
    ```

    **14b. Update each route.tsx** (`frontend/app/api/infographic/{movers,spotlight,state}/route.tsx`):
    - Import the helpers: `import { loadBrandFonts, LOGO_URL } from '../_shared/assets';`
    - Replace the text wordmark block at the top of each JSX template — currently a `<div>` rendering `'PITCHRANK'` text — with `<img src={LOGO_URL} width={isStory ? 360 : 280} height="auto" alt="" />`.
    - Replace `fontFamily: 'Arial, sans-serif'` on the outer container with `fontFamily: 'DM Sans, sans-serif'`.
    - For the big headline `<div>`s (e.g. `BIGGEST MOVERS`, `TEAM SPOTLIGHT`, `{state} CHAMPIONS`) add `fontFamily: 'Oswald'` inline style so display copy uses the display face.
    - Extend the `ImageResponse(...)` call's options object to include `fonts: await loadBrandFonts()`.

    **14c. Coordinate with Step 5's `mover_spotlight` URL fix.**
    - Step 5 changed `media_url` `platform=twitter` → `platform=instagram`. This step doesn't change the URL, only what the rendered image looks like. No conflict.

    **14d. `frontend/public/` deploy check.**
    - `frontend/public/fonts/{Oswald-Bold,Oswald-Regular,DMSans-Bold,DMSans-Regular}.woff` already deploy to `pitchrank.io/fonts/...` (verified — `ls frontend/public/fonts/` returns all four files).
    - `frontend/public/logos/logo-primary.svg` already deploys to `pitchrank.io/logos/logo-primary.svg` (verified — `ls frontend/public/logos/` returns the file).
    - No new asset commits needed.

    **14e. Smoke test (local Next.js dev server):**
    - From `C:/PitchRank/frontend`: `npm run dev` then visit `http://localhost:3000/api/infographic/movers?platform=instagram` — image should render with Oswald headline, DM Sans body, and the PITCHRANK logo (white + gold lockup) in the header instead of letter-spaced text.
    - Repeat for `/api/infographic/spotlight?platform=instagram` and `/api/infographic/state?platform=instagram&state=TX`.

## Verification

Run in order. Each step has an observable outcome.

1. **Local dry-run smoke test:**
   - From `C:/PitchRank`: `cd C:/PitchRank && python scripts/marketing_pipeline.py --dry-run` (the pipeline auto-loads `.env`/`.env.local` at lines 29-34 — no env-var prefix needed). Dry-run does NOT call Postiz (stub integration IDs used in dry-run); `POSTIZ_API_KEY` is only required for the live smoke test in Step 2.
   - Expected: pipeline runs through every step; existing human-readable preview logs each social post + each X thread tweet; new `DRY RUN: N/M would be drafted to Postiz` aggregate line appears once; `artifacts/social_posts_*.json` written and contains the X thread entry with populated `thread_parts`; each Instagram ranking post (rankings_live, mover_spotlight, state_spotlight) carries `_tag_stats` with `tagged_count` ≥ 0; the post's `text` ends with `Tagging: @...` when any handles were found; exit code 0.
   - **Tag coverage check:** `python -c "import json,glob; data=json.load(open(sorted(glob.glob('artifacts/social_posts_*.json'))[-1])); print({e['type']: e.get('_tag_stats') for e in data if e.get('_tag_stats')})"` — expected output: a dict of post types to `{tagged_count, target_count, missing_team_ids}`.
     - If the printed dict is **non-empty but all `tagged_count == 0`**: the `team_instagram_handles` view has zero `confirmed` rows for the target team IDs — investigate via `team_instagram_review_queue` and run `scripts/enrich_instagram_handles.py` if needed.
     - If the printed dict is **empty (`{}`)**: no `_tag_stats` key was written to any post. The most likely cause is Step 6a's RPC migration not being applied — `data["climbers"]/[fallers]/[spotlight_teams]` lack the `team_id` field, so `_resolve_tag_targets` returns `[]` for every post. Confirm with `SELECT team_id FROM get_biggest_movers(...) LIMIT 1;` — if NULL or missing column, re-apply the migration.
   - Edge case (missing trend research): delete `brand/trend-research/<current-week>.json` and re-run — expect `log.error("Trend research file missing for ...")`, trend count = 0 in the dry-run summary; pipeline continues but final `draft_results` is shorter by 3 entries.
   - Edge case (stale trend research): create `brand/trend-research/<wrong-week>.json` with `"week": "2099-W01"` — expect `log.error("Trend research week mismatch: expected ..., got 2099-W01")`, trend count = 0.
   - Edge case (no Postiz key, live): clear `POSTIZ_API_KEY` env and re-run *live* (no `--dry-run`) — expect `get_postiz_integrations()` logs error and returns `{}`, all router calls log "No Postiz integration for routed platform", all drafts result in `False`, exit code 1. (Dry-run is unaffected — it never calls `get_postiz_integrations`.)
   - Edge case (kill switch): set `POSTIZ_DRAFTS_ENABLED=false` and re-run with `--dry-run` — expect log shows `POSTIZ_DRAFTS_ENABLED=false — skipping social drafts entirely`, no social/thread/trend generators run, `all_drafts` is `[]`, dry-run summary shows `0/0 would be drafted`, the existing human-readable preview shows no social posts and an empty X thread section, exit code 0 (newsletter still ran).

2. **Live API smoke test (one cycle, gated):**
   - **Prune duplicate-risk first.** Each `gh workflow run` creates a fresh batch of drafts in Postiz — there is no client-side dedup. Before any smoke run, open Postiz UI → Drafts → delete any prior `postiz-migration` smoke drafts to keep counts unambiguous.
   - The workflow's `if: github.event_name == 'workflow_dispatch'` (per Step 10) allows manual dispatch while blocking auto-trigger. Run via `gh workflow run marketing-pipeline.yml --ref postiz-migration -f dry_run=false`.
   - Expected: GitHub Actions run succeeds. Within ~30s of run completion, draft posts appear in Postiz UI under Drafts tab — 1 X thread (4 tweets), 3 Instagram drafts, up to 3 X trend drafts (if seed JSON populated). Each draft shows the pre-set MT publish window.
   - Inspect the X thread draft in Postiz UI: confirm `thread_parts` render as a 4-tweet chain (not a single concatenated post).
   - **If re-running the smoke test** (e.g., after a bugfix): prune the prior batch of drafts in Postiz UI first. Otherwise you'll have N×2, N×3 drafts queued for the same publish window. This is a known v1 limitation; a `GET /posts` dedup pre-check is a future enhancement.
   - Test the kill switch: set `gh variable set POSTIZ_DRAFTS_ENABLED --body false --repo dallasheidt14/PitchRank`, then re-run `gh workflow run marketing-pipeline.yml --ref postiz-migration -f dry_run=true`. Confirm log shows `POSTIZ_DRAFTS_ENABLED=false — skipping social drafts entirely`, no new Postiz drafts appear. Restore with `gh variable set POSTIZ_DRAFTS_ENABLED --body true`.

3. **End-to-end weekly verify:**
   - After first real Monday trigger: open Postiz UI → Drafts → approve each post → verify they fire at the pre-set MT windows. Check Postiz Analytics tab after 24h for delivery confirmation.

4. **Rollback path (if any verification step fails):**
   - `git switch main && git branch -D postiz-migration` (no remote changes).
   - GitHub secrets `BUFFER_ACCESS_TOKEN` + `X_*` still present (not deleted until Step 11's deferred cleanup), so reverting the workflow file restores the old pipeline immediately.

5. **Two-cycle cleanup (after two successful weekly cycles — user-gated):**
   - Cancel Buffer subscription.
   - **Ask user before** running `gh secret delete BUFFER_ACCESS_TOKEN X_CONSUMER_KEY X_CONSUMER_SECRET X_ACCESS_TOKEN X_ACCESS_TOKEN_SECRET --repo dallasheidt14/PitchRank`. Do not run autonomously.
   - In a follow-up one-line PR, remove the `if: false` gate at workflow line 23 so Monday triggers re-enable automatically.

## Context Files

Read these in full before starting implementation:

- `scripts/marketing_pipeline.py` — the entire file. Every step touches it; line numbers in this plan assume the surveyed baseline. Re-verify line numbers against current HEAD before editing.
- `frontend/app/api/infographic/movers/route.tsx` — model edge function for Step 14; mirror its structure for `spotlight/route.tsx` and `state/route.tsx`.
- `frontend/public/logos/` (`logo-primary.svg` + variants) and `frontend/public/fonts/` (`Oswald-{Regular,Bold}.woff`, `DMSans-{Regular,Bold}.woff`) — confirm files exist before Step 14; they're referenced by URL at edge runtime.
- `.github/workflows/marketing-pipeline.yml` — workflow shape, env passthrough, `if: false` gate at line 23.
- `scripts/marketing_pipeline.py:378-410` — `publish_to_beehiiv()` is the REST-pattern model the Postiz helpers must mirror.
- `scripts/marketing_pipeline.py:755-835` — `generate_social_posts()` defines the canonical post-dict shape that trend posts and the X thread must match.
- `brand/blog-topics.json` — file convention model for `brand/trend-research/<week>.json` artifacts.
- **`scripts/enrich_instagram_handles.py:1-80`** — discovery pipeline overview (read for context, do not modify in this plan). Confidence bands, two-phase club/team approach.
- **`frontend/hooks/useInstagramHandles.ts`** — handle-collection logic; mirror the team-first / club-fallback rule and the dedupe-by-lowercased-handle pattern.
- **`supabase/migrations/20260314000001_add_team_social_profiles.sql`** + **`20260314000002_add_profile_level_to_social_profiles.sql`** — schema + `team_instagram_handles` view definition. FK is `team_id → teams.team_id_master` (memory `gotcha_rankings_full_fk_team_id_master.md` applies if joining via rankings_full).
- Memory `feedback_verify_branch.md`, `env_cwd_resets.md`, `feedback_init_exports.md`, `postiz_api.md`, `gotcha_gh_actions_if_false_dispatch.md` — apply during edits and dead-code removal.
- Postiz API docs (external, do not re-fetch unless ambiguity): `https://docs.postiz.com/public-api/posts/create.md`, `https://docs.postiz.com/public-api/integrations/list.md`, `https://docs.postiz.com/public-api/providers/x`, `https://docs.postiz.com/public-api/providers/instagram.md`.
