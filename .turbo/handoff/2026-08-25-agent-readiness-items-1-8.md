# Handoff: Agent-readiness review, items 1–8

## What this is

A 2026-08-24 review of how well this repo supports an AI agent produced 98 cited findings
and a ranked 8-item plan. Full report (artifact, includes every finding with evidence):
https://claude.ai/code/artifact/9e4525fa-4bb1-4844-9ea4-873e36de5d6f

A companion sweep of `.turbo/improvements.md` entries noted 2026-08-18..24 lives at:
https://claude.ai/code/artifact/e7cdb2a1-3b83-4f23-a45d-b967b9a5122d

Backlog pointer: `.turbo/improvements.md` → "Work through items 2–8 of the 2026-08-24
agent-readiness review".

## Shipped (all merged to main)

| PR | Item | What landed |
|----|------|-------------|
| #1019 `40e0a48b7` | 1 | Supabase reachable for agents: `.mcp.json` pinned to 0.11.0 with `--project-ref` and fail-closed `${SUPABASE_ACCESS_TOKEN:-}`; `enabledMcpjsonServers` in tracked settings; `/.mcp.json` in CODEOWNERS; `.env.example` Agent Tooling section; `tests/unit/test_claude_config_json.py` |
| #1023 `b9f82f6ff` | 2 | Documented commands now match CI exactly + a "Reproducing the CI gate locally" block; four paste-fatal patterns fixed; wrong DB columns in the Supabase/domain skills corrected; ten missing workflow rows; README's three deleted-script commands |
| #1024 `5b97c8c08` | 3 (part 1) | `tests/unit/test_agent_doc_references.py` — six checks over the 25 agent-loaded markdown files; `test_claude_agent_frontmatter.py` extended to all 12 skills; five live violations fixed |

Item 1's operator half is also **done**: root `.env` now carries `SUPABASE_URL` /
`SUPABASE_KEY` / `SUPABASE_SERVICE_ROLE_KEY` (verified against the live DB — 200,051 teams),
`frontend/.env.local` gained `SUPABASE_SERVICE_ROLE_KEY`, and `SUPABASE_ACCESS_TOKEN` is set
at Windows User scope and validated against the Management API.

## State right now

- On `main` at `5b97c8c08`, in sync with origin, **no open PRs**.
- One uncommitted file: `.turbo/improvements.md` (the backlog entry, updated to reflect
  items 1–3-part-1 as shipped). `main` refuses direct commits, so it needs to ride along
  with the next PR — stage it there rather than committing it alone.
- The guard passes on main: `python -m pytest tests/unit/test_agent_doc_references.py
  tests/unit/test_claude_agent_frontmatter.py -q` → 145 passed in ~2s.

## Next concrete action

Start **item 3, PR2**: the seven remaining contradictions, where two agent-facing files tell
an agent opposite things. Each was verified against the code this session:

1. `.claude/skills/expert-coder/SKILL.md:167-174` mandates conventional-commit prefixes
   (`feat:`, `fix:`); `CLAUDE.md` mandates imperative plain subjects, which is what the last
   15 commits on main actually use. **Delete expert-coder's Git Commit Style section.**
2. Age-group format: `CLAUDE.md` says normalize to `"14"`; `rankings-algorithm/SKILL.md:278`
   says `"u14"`. Code settles it — `scripts/calculate_rankings.py:683` help text says
   `u10, u11`, config keys are `f"u{age}"`. **Correct CLAUDE.md to the `u14` form.**
3. GotSport rate limits stated identically in `pitchrank-domain:79` and
   `scraper-patterns:13-18`, matching neither real scraper class
   (`src/scrapers/gotsport.py:310-313` is 1.5/2.5/3/30; `:1489-1492` is 0.1/0.3/2/15).
   **Replace both with a pointer at the code, since the values are env-overridable.**
4. Provider inventory: `CLAUDE.md:157-165` omits PlayMetrics and Affinity-WA, both of which
   have running workflows. README gives a third list. **CLAUDE.md wins and gains two rows;
   README drops its list.**
5. pandas `fillna` remedy differs: `.claude/rules/data-safety.md` says
   `where(col.notna(), None)`; `.claude/agents/ranking-engine.md:96` says `fillna(np.nan)`.
   **The rule wins; drop the agent's variant.**
6. `frontend/lib/api` membership listed three times, three different ways
   (`CLAUDE.md:595-604` omits `watchlist`, `CLAUDE.md:716` names three, `frontend/CLAUDE.md:79`
   is correct). **frontend/CLAUDE.md owns it.**
7. `CLAUDE.md:129` says "26,442 `u19`"; live count is ~27,700. **Reword as "no `u18` teams
   and roughly 28K `u19`" rather than refreshing an exact number that re-breaks weekly.**

Then **PR3** (large, splittable by tier): insert the one-line pointers and delete the
duplicated prose bodies — 16 blocks owned by `CLAUDE.md`, 5 by `frontend/CLAUDE.md`, 10 by a
skill or rule. Two fixed pointer forms, applied mechanically:

- Form P: `> Canonical: CLAUDE.md "<exact heading>". This file adds only <the delta>.`
- Form C: `> Source of truth: <repo-relative path>. Check it when the value matters.`
  (preferred wherever a code constant exists — it removes the fact from markdown entirely)

Ownership rule so nothing needs re-deciding: **a fact is owned by the narrowest file
guaranteed loaded when the fact is needed.** Always-loaded and needed unprompted → CLAUDE.md.
Frontend-scoped → frontend/CLAUDE.md. Trigger-time depth → the skill. Change-approach
mechanics → `.claude/rules/`.

Explicitly **leave alone**: the two `AGENTS.md` shims (the imperative "Read CLAUDE.md" line is
what works; a bare `@import` is inert), the workflow-table/github-actions-debug overlap
(already a clean owner/delta split), and README's outsider-facing repeats. Do **not** create
`.claude/rules/reviewer-protocol.md` for the shared SHIP/HOLD block — rules load into every
session, so homing agent-only protocol there taxes every unrelated conversation to save six
lines; the parity check in the new test covers it instead.

## Then items 4–8

4. **Backlog lifecycle** — `.turbo/improvements.md` is append-only by construction; nothing on
   the PR path closes an entry. Add ID/Status/Refs fields, a close step in `/ship`, a
   `/sweep-improvements` pass, and an archive file.
5. **Per-change wait** — median PR is 63 min against a 3.2-min CI. Use `gh pr merge --auto`,
   a bounded Codex poll, commit the permission allowlist to tracked `settings.json`, replace
   the 102-line Nov-2025 PR template, add a CI `concurrency` group.
6. **Richer session-start hook** — print CI-on-main, last rankings run, failed scheduled
   workflows, dirty worktrees, backlog size, latest handoff (~6s via `gh`).
7. **git-guard gaps** — `powershell -Command "git push --force …"` bypasses it entirely
   (reproduced); `commit --amend` on a pushed HEAD is unguarded; no content-aware gate on
   ranking-engine paths despite the review-before-push rule; `dry-run-check` only fires on
   brand-new files.
8. **Retire what contradicts** — `PROJECT_FLOW.md` (2024, describes v53e), 87 orphaned
   `docs/` files, the always-red `claude-review` workflow, the stale
   `C:/PitchRank_tournament_beta` worktree (has uncommitted work — check before removing) and
   39 `origin/claude/*` branches 4–9 months old.

## Traps worth knowing before you start

- **Check the PR's review comments, not just its checks.** `gh pr checks` reports status only;
  the Codex bot's inline findings live at `gh api repos/dallasheidt14/PitchRank/pulls/<N>/comments`.
  Missing that on #1019 shipped a false statement that had to be corrected in a follow-up.
  Codex posts 3–8 min after open, on roughly half of PRs; past ~10 min it skipped.
- **The new guard resolves paths against `git ls-files` only, never the working directory.**
  That was deliberate: an untracked local file (`frontend/.env.local`) made the test green
  locally and red in CI. Keep it that way.
- **Doc fixes need verifying as hard as code fixes.** Two independent review passes each
  caught false statements introduced *by the fix* — `CRON_SECRET` was claimed absent from both
  env templates when it is in `frontend/.env.example`, and "omitting `--auto-import` is the dry
  run" was wrong: `scripts/scrape_games.py:511` writes `team_scrape_log` and
  `teams.last_scraped_at` before the import branch.
- **`claude-review` is red on every PR and is not a required check.** It reads
  `CLAUDE_CODE_OAUTH_TOKEN` (present); the run fails on the first turn with `$0` spend, which
  is an auth rejection, not a missing secret. Do not diagnose it as a code problem.
- **A concurrent Codex session shares this checkout.** It left files in the tree twice during
  this session. Before reverting anything a subagent did not report creating, check
  `git worktree list` and running processes — `C:/PitchRank-movers` appeared mid-session.
