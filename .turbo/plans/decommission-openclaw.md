---
status: done
---

# Plan: Decommission the openclaw multi-agent system

## Context

"openclaw" was a multi-agent orchestration system (a MOLTBOT orchestrator plus Cleany/Scrappy/Ranky/Codey/Compy/Watchy/Movy/Socialy/Blogy personas) that fed a "Mission Control" task board in the PitchRank frontend. It is retired and no longer used. Its artifacts are scattered across the repo: dead Next.js API routes, five Supabase tables, a pile of status-report markdown files, a set of persona "learnings" skill files, persona working-memory files (`memory/WORKING-*.md`), and stale entries in the root and frontend `CLAUDE.md` reference docs. They add confusion (e.g. `SUB_AGENTS.md` references a `SOUL.md`/`AGENTS.md`/`HEARTBEAT.md` that no longer exist) and a small latent write surface (the `agent-webhook` endpoint can still insert rows if its secret leaked).

This plan removes the openclaw footprint while preserving everything that was repurposed or is unrelated. The `/mission-control` route was **rebuilt** into a live, admin-gated ML-ops monitor (model accuracy + prospective-prediction eval + training readiness) with a Stripe **Subscriptions** view — that stays. The work is a structured deletion plus one irreversible database teardown, sequenced so the destructive step is isolated and reversible-in-practice via a pre-drop backup.

### Decisions made during planning

- **Keep the model-snapshot dashboard.** `app/mission-control/page.tsx` → `ModelSnapshotDashboard` reads live data (`prospective_match_predictions`, `model_training_runs`, `prediction_feature_history`, `games`) via `app/api/mission-control/model-snapshot/route.ts`. It is not openclaw and not empty. Therefore: no redirect, no `next.config.ts` change, and `hooks/useMissionControl.ts` (imported only by `ModelSnapshotDashboard.tsx`) **stays**.
- **Teardown migration goes in the live root `supabase/migrations/`** (timestamped `YYYYMMDDHHMMSS`, applied through the maintained MCP/CLI path), not the manual `frontend/supabase/migrations/` set.
- **Extract salvageable knowledge into auto-memory** (`C:/Users/Dallas Heidt/.claude/projects/C--Users-Dallas-Heidt/memory/`) before deleting the knowledge-bearing docs — this is outside the repo, so it is not part of any commit.
- **DB path = backup → remove code → drop.** Conservative fallback (leave tables, remove code only) is acceptable if you decide not to touch prod yet.

### Out of scope (explicitly NOT touched)

- `.agents/product-marketing.md` — actively used as a product-feature source of truth.
- `memory/2026-02-15.md` and `memory/MOBILE-OPTIMIZATION-INVESTIGATION.md` — not openclaw persona logs; retained (only the `memory/WORKING-*.md` files are openclaw).
- `agent_skills/pitchrank-club-normalizer/` — a real domain skill.
- Non-persona domain/SEO skills under `.claude/skills/`: `pitchrank-domain`, `supabase-pitchrank`, `rankings-audit`, `rankings-algorithm`, `scraper-patterns`, `github-actions-debug`, `expert-coder`, `pitchrank-alias-normalizer/`, `review-workflows/`, `pr/`, and the `seo*` skills.
- Existing `frontend/supabase/migrations/00x_*.sql` + `agent_activity.sql` — kept as immutable history; the tables they created are dropped by a new forward migration, the files are not deleted.
- `announcements` table and `update_updated_at_column()` function — created in `001_mission_control_tasks.sql` but shared with KEEP code; must survive the teardown.
- Creating a root `AGENTS.md` and adding a prettier PostToolUse hook — separate enhancements, tracked outside this plan.

## Pattern Survey

### Analogous Features
- `frontend/next.config.ts` `async redirects()` returns 308 permanent redirects (`{ source, destination, permanent: true }`) — the repo's idiomatic page-relocation mechanism. **Not needed here** (model-snapshot kept), noted only to rule out.
- `frontend/middleware.ts` — `ADMIN_ROUTES = ['/mission-control', '/analytics']`; admin gate enforced via `user_profiles.plan === 'admin'`, prefix-based (`startsWith('/mission-control')`). Route removals need **no** middleware edit (matchers are prefix-based, not per-route).
- `frontend/app/mission-control/subscriptions/page.tsx` — KEEP page; server component (`export const dynamic = 'force-dynamic'`) relying on middleware for the admin gate.
- `frontend/app/api/announcements/route.ts` — KEEP route still using the `announcements` table (born in `001_mission_control_tasks.sql`). Teardown must drop only the 5 named openclaw tables (incl. `mission_chat`).
- SQL teardown precedent: `frontend/supabase/migrations/002_fix_task_status_values.sql` uses `ALTER TABLE ... DROP CONSTRAINT IF EXISTS`. No existing migration does `DROP TABLE`; none carry a down/rollback section → write a **forward** teardown migration.

### Reusable Utilities
- `frontend/hooks/useUser.ts` → `hasAdminAccess(profile)` (`profile.plan === 'admin'`) — client admin predicate. Unaffected.
- `frontend/hooks/useMissionControl.ts` → `useMissionControlSnapshot()` — imported **only** by `frontend/components/mission-control/ModelSnapshotDashboard.tsx`. **KEEP** (model-snapshot kept).
- `frontend/lib/supabase/server.ts` → `createServerSupabase` and `frontend/lib/supabase/service.ts` → `createServiceSupabase` — standard helpers; the openclaw routes use these directly. There is no shared "openclaw lib" module to delete, only the route files.
- `update_updated_at_column()` (`frontend/supabase/migrations/001_mission_control_tasks.sql`) — shared trigger function. Drop openclaw triggers, **not** the function.

### Convention Anchors
- **Two migration systems.** Live/automated: `C:/PitchRank/supabase/migrations/` (`YYYYMMDDHHMMSS_snake_case.sql`; newest `20260528000000_seed_somsports_provider.sql`). Manual: `frontend/supabase/migrations/` (`001_`…`004_` + un-numbered `agent_activity.sql`, "run in SQL editor"). Teardown goes in the **root** system → next file is a fresh timestamp greater than `20260528000000` (e.g. `20260608HHMMSS_drop_openclaw_mission_control_tables.sql`).
- **`robots.txt` is static** (`frontend/public/robots.txt`), broadly disallows `/mission-control` and `/api/` — no per-route openclaw entries. `frontend/app/sitemap.ts` does not enumerate these routes; `frontend/app/mission-control/layout.tsx` sets `index:false`. **No robots/sitemap edits.**
- **Plan/file shape** mirrors `.turbo/plans/fix-null-score-immutable-backfill.md` and `fix-supabase-rpc-statement-timeouts.md`: symbol-anchored steps, explicit preserve-callouts, isolated irreversible step.

### Verify-before-delete facts (all confirmed by survey)
- `task_comments` referenced only in `agent-webhook/route.ts` + `tasks/[id]/comments/route.ts` (both deleted) + `001` migration + `frontend/CODEY_REPORT.md` (a doc being deleted). No KEEP code uses it → safe to drop.
- `socialy-seo.skill.md` and `blogy-writer.skill.md` (repo-root `.claude/skills/`) are openclaw persona logs (Socialy uses `sessions_spawn`/"spawn Codey"; Blogy has a stale macOS path + outdated `blog-posts.tsx` reference). They embed reusable SEO/blog knowledge → extract before deleting.
- Nothing external POSTs to `/api/agent-webhook`; only `frontend/scripts/test-mission-control-api.sh` (manual curl) and openclaw docs reference it. `moltbot.json` has no mission-control reference.
- Dependent DB objects of the migration-defined tables (from `001`/`003`/`agent_activity.sql`): view `active_agent_sessions`; functions `get_agent_status()`, `cleanup_old_sessions()`; `agent_activity` realtime-publication membership + its RLS policy; `update_updated_at` triggers on `agent_tasks`/`agent_sessions`. `mission_chat` has realtime-publication membership only (no RLS): `frontend/mission_chat_schema.sql` is just `CREATE TABLE` + one index + `ALTER PUBLICATION supabase_realtime ADD TABLE mission_chat` — no `ENABLE ROW LEVEL SECURITY`, no policy (unlike `agent_activity.sql`, which has both).

### Proposed Alignment
Blend, leaning on existing conventions: delete the openclaw route files and docs/skills outright (no middleware/robots/sitemap/next.config edits); write a single forward teardown migration in the root system that drops the 5 openclaw tables (incl. `mission_chat`) + their dependent objects while explicitly preserving `announcements` and `update_updated_at_column()`; back up all 5 tables to CSV before the drop.

## Blast Radius

- **API route deletions** (`agent-webhook`, `agent-status`, `agent-activity`, `tasks/*`): endpoints disappear. Only consumer is a manual test script (also deleted). No frontend KEEP code imports them.
- **`task_comments` / `agent_*` / `mission_chat` table drops**: irreversible. No KEEP code references them (verified — `mission_chat` only via the deleted chat route + deleted docs). Mitigate with a pre-drop CSV backup of all 5 tables.
- **Must-not-touch in the teardown**: `announcements` table, `update_updated_at_column()` function (both shared with KEEP code).
- **Docs/skills deletions**: documentation only; no code imports. `GOTCHAS.md`/`LEARNINGS.md`/`DECISION_TREES.md`/`INCIDENT_PLAYBOOK.md` + the persona learnings carry real knowledge → extract first.

## Setup Hazard

- **Branch first.** A PreToolUse hook blocks `git commit` on `main` and blocks all `git merge` (exit 2). Branch from `origin/main`, e.g. `chore/decommission-openclaw`. Before editing, confirm a clean tree against the intended baseline: `git -C C:/PitchRank fetch origin && git -C C:/PitchRank status` (no unrelated staged/modified files in scope).
- **`frontend/.env.local` must be present** in the working checkout for `tsc`/`vitest`/build to run.
- **Supabase write path**: the project `.mcp.json` `supabase` server is `--read-only`. Use the read-only server (or `execute_sql` SELECT) for the CSV backup and table-reference checks; apply the `DROP` migration through a **write-capable** Supabase MCP (`apply_migration`) or hand the SQL block to the user to run in the SQL editor. Do not assume the project server can write.

## Implementation Steps

1. **Branch and confirm baseline.**
   - From `C:/PitchRank`, branch `chore/decommission-openclaw` off fresh `origin/main`; verify the working tree is clean for all in-scope paths.

2. **Extract salvageable knowledge to auto-memory (do this BEFORE any deletion).**
   - Read the knowledge-bearing sources: `docs/GOTCHAS.md`, `docs/LEARNINGS.md`, `docs/DECISION_TREES.md`, `docs/INCIDENT_PLAYBOOK.md`, `.claude/skills/codey-learnings.skill.md`, the other `*-learnings.skill.md` + `socialy-seo.skill.md` + `blogy-writer.skill.md`, and the 12 persona working-memory files `memory/WORKING-*.md` (cleany/codey/compy/movy[/-tuesday/-wednesday]/ranky/scrappy[/-monday/-wednesday]/socialy/watchy) — skim all for still-true, non-obvious engineering/SEO/blog patterns. Exclude `memory/2026-02-15.md` and `memory/MOBILE-OPTIMIZATION-INVESTIGATION.md` (not openclaw).
   - Distill only what is still accurate (cross-check against current repo reality — many reference dead paths like `blog-posts.tsx`) into one or more new memory topic files under `C:/Users/Dallas Heidt/.claude/projects/C--Users-Dallas-Heidt/memory/`, each with a one-line `MEMORY.md` index pointer. Skip anything already captured in existing memory or CLAUDE.md.
   - This step writes outside the repo; it is a prerequisite gate for Step 5, not a commit.

3. **Delete dead openclaw code.**
   - Remove route files: `frontend/app/api/agent-webhook/route.ts`, `frontend/app/api/agent-status/route.ts`, `frontend/app/api/agent-activity/route.ts`, `frontend/app/api/chat/route.ts`, `frontend/app/api/tasks/route.ts`, `frontend/app/api/tasks/[id]/route.ts`, `frontend/app/api/tasks/[id]/comments/route.ts`, `frontend/app/api/tasks/seed/route.ts` (and remove the now-empty `agent-webhook/`, `agent-status/`, `agent-activity/`, `chat/`, `tasks/` directories). `/api/chat` is the admin-gated openclaw operator chat backing `mission_chat` (GET last 50 / POST insert with `author_type` human|agent) — not a user-facing AI chat; verified no KEEP code consumes it.
   - Remove `frontend/scripts/test-mission-control-api.sh`, `frontend/mission_chat_schema.sql` (loose openclaw schema file at the frontend root, not part of the numbered migrations), root `moltbot.json`, root `SUB_AGENTS.md`.
   - **Do NOT touch** `frontend/hooks/useMissionControl.ts`, `frontend/app/api/mission-control/*`, `frontend/app/mission-control/*`, `frontend/components/mission-control/*`, `frontend/lib/mission-control/*`, `frontend/types/mission-control.ts`, `frontend/app/api/announcements/route.ts`.

4. **Verify code removal (gate before deleting docs).**
   - Run the Verification commands below. Fix any dangling import before proceeding.

5. **Delete openclaw docs and skills** (after Step 2 extraction is done).
   - `frontend/`: `MISSION_COMPLETE.md`, `LIVE_STATUS_FLOW.md`, `LIVE_AGENT_STATUS.md`, `CODEY_REPORT.md`, `AGENT_STATUS_IMPLEMENTATION.md`, `AGENT_COMMS_MIGRATION.md`, `MISSION_CONTROL_FIXES.md`.
   - `docs/`: `AGENT_MODELS.md`, `CODEY_TEMPLATES.md`, `SKILLS_ROADMAP.md`, `WEEKLY_GOALS.md`, `GOTCHAS.md`, `LEARNINGS.md`, `DECISION_TREES.md`, `INCIDENT_PLAYBOOK.md`.
   - `reports/system_status.md`.
   - `.claude/skills/`: `cleany-learnings.skill.md`, `scrappy-learnings.skill.md`, `ranky-learnings.skill.md`, `codey-learnings.skill.md`, `watchy-learnings.skill.md`, `movy-learnings.skill.md`, `socialy-seo.skill.md`, `blogy-writer.skill.md`, `orchestrator-patterns.skill.md`, `agent-quickstart.skill.md`, `cleany-conservative.skill.md`.
   - Leave all other `.claude/skills/` entries (the domain/SEO skills listed in Out of Scope) untouched.
   - **Edit (do not delete) `frontend/CLAUDE.md`**: remove the stale openclaw entries — the deleted endpoints documented as live (`GET|POST|PUT|DELETE /api/tasks/*`, `POST /api/chat`, `GET /api/agent-status`, `GET|POST /api/agent-activity`) and the `components/agent-hq/` + `lib/agents/` directory-map entries (both already empty/orphaned). Leave the KEEP entries (`/api/mission-control/*`, `/api/announcements`) intact.
   - **Delete the 12 openclaw persona working-memory files**: `memory/WORKING-cleany.md`, `WORKING-codey.md`, `WORKING-compy.md`, `WORKING-movy.md`, `WORKING-movy-tuesday.md`, `WORKING-movy-wednesday.md`, `WORKING-ranky.md`, `WORKING-scrappy.md`, `WORKING-scrappy-monday.md`, `WORKING-scrappy-wednesday.md`, `WORKING-socialy.md`, `WORKING-watchy.md` (after Step 2 extraction). Leave `memory/2026-02-15.md` and `memory/MOBILE-OPTIMIZATION-INVESTIGATION.md`.
   - **Edit (do not delete) root `C:/PitchRank/CLAUDE.md`**: remove the `## Agent System` section (the Codey/Ranky/Scrappy/Cleany/Movy/Compy/Watchy/Socialy persona table, ~lines 455-468); remove the two dead Key-Files rows `frontend/lib/agents/config.ts` (~line 506) and `frontend/lib/agent-config.ts` (~line 507) — both paths confirmed non-existent; and fix the stale repo-structure / route entries (the `memory/` "Agent working memory files" note ~line 81 and the "tasks, agent endpoints" wording ~line 358). Keep all non-openclaw content intact. Locate by heading/symbol, not by the cited line numbers (they drift).

6. **Back up the five openclaw tables (gate before the drop).**
   - Via the read-only Supabase MCP / `execute_sql`, `SELECT *` from `agent_sessions`, `agent_tasks`, `agent_activity`, `task_comments`, `mission_chat`; save each to CSV (or a one-off SQL dump) outside the repo. Record row counts.

7. **Write the forward teardown migration.**
   - New file `C:/PitchRank/supabase/migrations/<YYYYMMDDHHMMSS>_drop_openclaw_mission_control_tables.sql` (timestamp greater than `20260528000000`).
   - Contents (idempotent, `IF EXISTS`):
     - `DROP VIEW IF EXISTS active_agent_sessions;`
     - `DROP FUNCTION IF EXISTS get_agent_status(text);` and `DROP FUNCTION IF EXISTS cleanup_old_sessions();` — note the `(text)` argument: `get_agent_status` is defined as `get_agent_status(p_agent_name TEXT)` (`003_agent_sessions_tracking.sql:47`), and Postgres resolves `DROP FUNCTION` by argument type, so a zero-arg `get_agent_status()` would be a silent no-op that leaves the real function orphaned. `cleanup_old_sessions()` is genuinely zero-arg.
     - Drop the RLS policy on `agent_activity` (which genuinely has one), and remove both `agent_activity` and `mission_chat` from the realtime publication (`ALTER PUBLICATION supabase_realtime DROP TABLE agent_activity;` and `... DROP TABLE mission_chat;`, each guarded for membership). `mission_chat` has no RLS policy, so any `DROP POLICY IF EXISTS` for it is a defensive no-op — do not hunt for one.
     - `DROP TABLE IF EXISTS mission_chat, task_comments, agent_activity, agent_tasks, agent_sessions CASCADE;` (CASCADE clears the `update_updated_at` triggers on these tables). `mission_chat` is defined in `frontend/mission_chat_schema.sql`; the other four come from the `frontend/supabase/migrations/00x` set.
   - **Preserve** (must NOT appear in any DROP): `announcements` table, `update_updated_at_column()` function. Add a header comment noting both are intentionally retained.

8. **Apply the teardown migration.**
   - Apply via a write-capable Supabase MCP `apply_migration`, or hand the SQL block to the user for the Supabase SQL editor (the project `.mcp.json` server is read-only). This is the single irreversible step — run it last, after Steps 2–7 are committed.

## Verification

- **No dangling references after code removal (Step 4):**
  - `cd C:/PitchRank/frontend && npx tsc --noEmit` → clean (catches dangling imports; per the eslint/tsc-safety rule, this is the authoritative gate).
  - `cd C:/PitchRank/frontend && npx vitest run` → green; `lib/mission-control/modelSnapshot.test.ts` still passes.
  - `rg -n "agent-webhook|agent-status|agent-activity|api/chat|api/tasks" C:/PitchRank/frontend` → only matches inside files already deleted (ideally zero).
  - `rg -n "useMissionControl|model-snapshot|ModelSnapshotDashboard" C:/PitchRank/frontend` → still resolves (KEEP files intact).
- **KEEP surface still builds:** `/mission-control` and `/mission-control/subscriptions` render for an admin (dev server or `next build`); `/api/mission-control/model-snapshot` returns 200 for an admin.
- **After the DB drop (Step 8):** query `information_schema.tables` → `agent_sessions`, `agent_tasks`, `agent_activity`, `task_comments`, `mission_chat` absent; `announcements` **present**. Query `pg_proc` → `get_agent_status` and `cleanup_old_sessions` **absent**, `update_updated_at_column` **present**; `information_schema.views` → `active_agent_sessions` **absent**. `/api/announcements` still returns 200.
- **Stale-doc check:** `rg -n "agent-status|agent-activity|api/tasks|api/chat|agent-hq|lib/agents" C:/PitchRank/frontend/CLAUDE.md` → no matches after Step 5's `frontend/CLAUDE.md` edit.
- **Repo hygiene:** `rg -n "openclaw|moltbot|MOLTBOT|SUB_AGENTS" C:/PitchRank --glob '!**/node_modules/**' --glob '!**/graphify-out/**' --glob '!**/supabase/migrations/**'` → no matches. The `supabase/migrations/` exclusion is deliberate: `frontend/supabase/migrations/003_agent_sessions_tracking.sql:6` contains `-- OpenClaw session ID` and is intentionally retained as history, so one expected match there is acceptable.
- **Persona-footprint check** (the literal `openclaw` token does not appear in root `CLAUDE.md` or the memory files — they use persona names — so the hygiene grep above would miss them): `rg -n "agent-hq|lib/agents|Agent System|WORKING-" C:/PitchRank --glob '!**/node_modules/**' --glob '!**/.turbo/**'` → no matches, and `ls C:/PitchRank/memory/WORKING-*.md` → nothing.

## Context Files

- `frontend/app/api/agent-webhook/route.ts` — the canonical openclaw endpoint; confirms the table-write surface being removed.
- `frontend/app/api/chat/route.ts` + `frontend/mission_chat_schema.sql` — the missed openclaw chat surface (admin-gated, reads/writes `mission_chat`); confirms the 5th table to back up and drop.
- `frontend/app/api/mission-control/model-snapshot/route.ts` and `frontend/lib/mission-control/modelSnapshot.ts` — the KEEP ML-ops dashboard; reading these prevents accidental deletion of live tooling.
- `frontend/app/api/announcements/route.ts` — proves `announcements` (in `001_mission_control_tasks.sql`) must survive the teardown.
- `frontend/supabase/migrations/001_mission_control_tasks.sql`, `003_agent_sessions_tracking.sql`, `agent_activity.sql` — define the tables, triggers, view, functions, RLS, and publication membership the teardown migration must mirror in reverse.
- `frontend/middleware.ts` — confirms admin gating is prefix-based, so no edits are needed for route removal.
- `C:/PitchRank/CLAUDE.md` — root AI-assistant reference; its `## Agent System` section and two dead Key-Files rows must be edited out (the file is edited, not deleted).
- `.turbo/plans/fix-null-score-immutable-backfill.md` — structural reference for an isolated, irreversible DB-mutation plan in this repo.
