# Handoff: Agent-readiness review, items 1–8

## What this is

A 2026-08-24 review of how well this repo supports an AI agent produced 98 cited findings
and a ranked 8-item plan. Full report (artifact, includes every finding with evidence):
https://claude.ai/code/artifact/9e4525fa-4bb1-4844-9ea4-873e36de5d6f

A companion sweep of `.turbo/improvements.md` entries noted 2026-08-18..24 lives at:
https://claude.ai/code/artifact/e7cdb2a1-3b83-4f23-a45d-b967b9a5122d

Backlog pointer: `.turbo/improvements.md` → "Work through items 2–8 of the 2026-08-24
agent-readiness review".

## Shipped

| PR | Item | What landed |
|----|------|-------------|
| #1019 `40e0a48b7` | 1 | Supabase reachable for agents: `.mcp.json` pinned to 0.11.0 with `--project-ref` and fail-closed `${SUPABASE_ACCESS_TOKEN:-}`; `enabledMcpjsonServers` in tracked settings; `/.mcp.json` in CODEOWNERS; `.env.example` Agent Tooling section; `tests/unit/test_claude_config_json.py` |
| #1023 `b9f82f6ff` | 2 | Documented commands now match CI exactly + a "Reproducing the CI gate locally" block; four paste-fatal patterns fixed; wrong DB columns in the Supabase/domain skills corrected; ten missing workflow rows; README's three deleted-script commands |
| #1024 `5b97c8c08` | 3 (part 1) | `tests/unit/test_agent_doc_references.py` — six checks over the 25 agent-loaded markdown files; `test_claude_agent_frontmatter.py` extended to all 12 skills; five live violations fixed |
| #1025 `8b8255eb1` | 3 (part 2) | The seven contradictions, each fact given one owner: expert-coder's commit style deleted, age groups fixed to the `u14` form, both GotSport rate-limit statements replaced with pointers at the code, PlayMetrics + Affinity WA added to the provider table (README's list dropped), the pandas remedy deferred to the rule, the `lib/api` inventory moved to `frontend/CLAUDE.md`, the u19 count rounded |

Item 1's operator half is also **done**: root `.env` now carries `SUPABASE_URL` /
`SUPABASE_KEY` / `SUPABASE_SERVICE_ROLE_KEY` (verified against the live DB — 200,051 teams),
`frontend/.env.local` gained `SUPABASE_SERVICE_ROLE_KEY`, and `SUPABASE_ACCESS_TOKEN` is set
at Windows User scope and validated against the Management API.

## State right now

- **Item 3 is complete.** Its three parts shipped as #1024 (the parity test), #1025 (the seven
  contradictions) and #1026.
- Full CI gate run locally, all seven green: ruff, pytest, eslint, prettier, tsc, vitest,
  llms.txt drift.

## What PR3 actually was

**The "31 duplicated bodies" figure in earlier drafts of this handoff was wrong** — it was a
count of duplicated *lines*, not blocks, and it made PR3 sound roughly four times larger than
it was. Measured on the merged tree with a normalized line-match across all 25 corpus files,
64 lines appeared in 2+ files, resolving to seven real bodies. Those seven are done:

| Body | Owner | Copy that now points at it |
|------|-------|----------------------------|
| Birth-year table, `14B` shorthands, U18→U19 rule | `CLAUDE.md` | `pitchrank-domain` |
| API-route auth snippet | `frontend/CLAUDE.md` | `CLAUDE.md` |
| Frontend command list | `frontend/CLAUDE.md` | `CLAUDE.md` |
| Branching / staging / push rules | `CLAUDE.md` § Git Discipline | two other CLAUDE.md sections |
| `rankings_full` column semantics | `rankings-algorithm` | `supabase-pitchrank` |
| Escalation criteria | `rankings-audit` | `ranking-engine` agent |
| `age_group` stored format | `CLAUDE.md` | `supabase-pitchrank` |

After the change, 33 shared lines remain and every one is deliberate: the reviewer SHIP/HOLD
protocol (below), a `for i in range(0, len(records), ...)` Python idiom, `| Table | Purpose |`
markdown headers, and frontmatter `skills:` lists. **There is no de-duplication work left** —
re-run `find_dupes`-style line matching before believing any future claim that there is.

Two things PR3 turned up that were not de-duplication and were fixed in passing: the domain
skill still carried "26,442 `u19`" after #1025 corrected it in CLAUDE.md (the predicted
divergence, live), and its "Season-year vs calendar-year trap" told an agent to go fix code
that #1018 had already fixed, naming a hardcoded 2026 set that no longer exists.

Explicitly **left alone**, and still the right call: the two `AGENTS.md` shims (the imperative
"Read CLAUDE.md" line is what works; a bare `@import` is inert), the
workflow-table/github-actions-debug overlap (already a clean owner/delta split), README's
outsider-facing repeats, and the shared SHIP/HOLD block in the two reviewer agents — rules
load into every session, so homing agent-only protocol in `.claude/rules/` would tax every
unrelated conversation to save six lines, and the parity check in the guard covers it.

Also deliberately **not** done: `CLAUDE.md`'s Coding Conventions and Common Pitfalls sections
restate four of the same rules (pagination, merge resolution, game immutability, PowerScore
bounds). That is a checklist deliberately mirroring the conventions, not accidental
duplication — collapsing it would be a restructure of the always-loaded file, and a separate
decision from this one.

## Next concrete action

Items 4–8 below. Item 4 (backlog lifecycle) is the natural next one: it is self-contained,
and every later item wants a working way to close an entry.

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
- **Doc fixes need verifying as hard as code fixes.** Three independent review passes have now
  each caught a false statement introduced *by the fix* — `CRON_SECRET` was claimed absent from
  both env templates when it is in `frontend/.env.example`; "omitting `--auto-import` is the dry
  run" was wrong, because `scripts/scrape_games.py:511` writes `team_scrape_log` and
  `teams.last_scraped_at` before the import branch; and #1025's own GotSport pointer claimed the
  scrape workflows set all five `GOTSPORT_*` knobs inline when none of them sets
  `GOTSPORT_RETRY_DELAY`.
- **A pointer can overclaim exactly like a value can, and PR3 is nothing but pointers.**
  Replacing a stale number with "read the code" feels safe, but the sentence carrying the
  pointer still asserts *where* the value comes from, and that assertion is as checkable — and
  was as wrong — as the number it replaced. Before writing a Form C pointer, confirm the named
  source is really the one that decides the value at runtime, not merely a place the name
  appears.
- **`claude-review` is red on every PR and is not a required check.** It reads
  `CLAUDE_CODE_OAUTH_TOKEN` (present); the run fails on the first turn with `$0` spend, which
  is an auth rejection, not a missing secret. Do not diagnose it as a code problem.
- **CI's prettier gate covers `frontend/CLAUDE.md`.** `ci.yml`'s Frontend Format job runs
  `npx prettier --check .` from `frontend/`, so any markdown table added there must be
  prettier-formatted — it pads every cell to the column width. Root `CLAUDE.md` and `README.md`
  are outside that job and are not checked. `npx prettier --write frontend/CLAUDE.md` touched
  only the new table, so it is safe to use on that file.
- **A concurrent Codex session shares this checkout.** It left files in the tree twice during
  this session. Before reverting anything a subagent did not report creating, check
  `git worktree list` and running processes — `C:/PitchRank-movers` appeared mid-session.
