# Handoff: Agent-readiness review, item 8 (the last one)

## What this is

A 2026-08-24 review of how well this repo supports an AI agent produced 98 cited findings and a
ranked 8-item plan. Full report:
https://claude.ai/code/artifact/9e4525fa-4bb1-4844-9ea4-873e36de5d6f

**Items 1 through 7 are done.** Item 8 is all that remains. The predecessor handoff,
`.turbo/handoff/2026-08-25-agent-readiness-items-1-8.md`, covers items 1-4 and is still worth
reading for its traps section; this file supersedes it for items 5-8.

Backlog pointer: `.turbo/improvements.md` -> IMP-117.

## Shipped since the last handoff

| PR | Item | What landed |
|----|------|-------------|
| #1029 `0274d5e62` | 5 | `scripts/pr_wait.py` (bounded Codex poll, then merge), `ci.yml` concurrency group, curated allowlist in tracked `.claude/settings.json`, new PR template |
| #1030 `0c56f0614` | 7 | `git-guard.sh` reads a shell wrapper's quoted argument as a command, refuses `commit --amend` once HEAD is on a remote, resolves `git -C` / `cd` once; `dry-run-check.sh` fires when a tracked file *gains* a Supabase write |
| #1031 `8b1a83414` | — | `pr_wait.py` reads a check's `conclusion`, not its `status` |
| #1033 `57c961e54` | 6 | Session banner reports rankings / CI-on-main / backlog / handoff, with ATTENTION lines for what needs a decision |

Three decisions inside those, so they are not re-litigated:

- **`gh pr merge --auto` is deliberately unused**, though the plan named it. It stays armed across
  a later push and GitHub decides on required checks alone, so a commit pushed after arming merges
  unreviewed. `pr_wait.py` merges exactly the commit it inspected.
- **The ranking-engine push gate was built and removed on request.** It was the one piece adding a
  new stop rather than restoring a guarantee CLAUDE.md already made. Do not rebuild it.
- **The tracked allowlist stops short of landing a change**: no `gh pr merge`, no `pr_wait.py`, no
  `powershell`. `tests/unit/test_claude_config_json.py` pins that line.

## Item 8, with the review's claims checked

The review's description of item 8 is **wrong in two places**. Verified 2026-08-26 against the
tree at `57c961e54`:

| Piece | Review said | Actually |
|---|---|---|
| `PROJECT_FLOW.md` | "2024, describes v53e" | Last touched **2026-08-23**, but by #1008 (untracking CSVs), a mechanical edit. The **substance holds**: line 7 says "The system uses a sophisticated v53e rankings engine", and lines 189-299 document v53e as the engine. Production runs Glicko-2; v53e is reachable only via `--engine v53e`. So it is a live contradiction with CLAUDE.md, just not a 2024 one. |
| orphaned `docs/` files | "87 orphaned" | **123** `docs/*.md` total. **112** unreferenced outside `docs/`; **78** unreferenced by anything at all. Neither is 87. |
| `claude-review` workflow | always red | Confirmed. Two files: `.github/workflows/claude-code-review.yml` and `claude.yml`. Tracked as **IMP-104**. |
| stale worktree | "has uncommitted work" | Confirmed and worse than it sounds: `C:/PitchRank_tournament_beta` on `shell/gotsport-tier-section-parser-02`, **20 changed files**, including `src/tournaments/reports/compute.py` — source, not just reports. |
| `origin/claude/*` branches | "39, 4-9 months old" | Confirmed. 39 branches, **2025-11-15 to 2026-04-13**. |

**Where the 87 probably came from.** `git log -- PROJECT_FLOW.md` contains
`fix: restore all 87 files accidentally deleted by Cursor in 2679b46` (2026-02-07). The review
most likely picked that number up from there. Re-measure before quoting it.

Re-measure the orphan count yourself before deleting anything — the two counts above differ by 34
depending on whether a doc referenced only by another doc counts as orphaned, and that is a
judgment call nobody has made yet.

## Traps

- **Doc fixes need verifying as hard as code fixes.** Four separate review passes in this arc each
  caught a false statement introduced *by the fix*. Item 8 is almost entirely deletion, which is
  the easiest to review and the easiest to get wrong.
- **The worktree is not safe to `git worktree remove`.** 20 files of uncommitted work, some of it
  source. Decide what happens to that work *first*, with the user. Its branch
  `shell/gotsport-tier-section-parser-02` also exists locally.
- **Check the PR's review comments, not just its checks.** `gh pr checks` reports run status only;
  Codex's findings live on the review. `python scripts/pr_wait.py` now does both. It exits 2 on
  findings and refuses to merge.
- **Codex reviews about half of PRs**, 3.4-8.7 min after open, never later. It does **not**
  re-review on later pushes — comment `@codex review` to request another round. In this arc it
  raised 15 findings across four PRs; every one was real, including a false positive one of the
  fixes had introduced. Budget for two rounds.
- **`claude-review` is red on every PR and is not required.** It reads `CLAUDE_CODE_OAUTH_TOKEN`
  (present) and fails on the first turn at $0 spend, which is an auth rejection, not a missing
  secret. IMP-104 already corrected that premise once; do not re-diagnose it as `ANTHROPIC_API_KEY`.
- **A concurrent Codex session shares this checkout.** It has left files in the tree mid-session
  before. Check `git worktree list` and running processes before reverting anything unexplained.
- **`[[ $x =~ [^;&|]* ]]` is a bash syntax error** — bash tokenises the operators before the regex
  is read. Patterns with shell metacharacters must come from a variable.

## State right now

- `main` at `57c961e54`, clean, no open PRs. Both post-merge runs on main passed.
- Six merged branches deleted. Four unrelated local branches left alone: `_tmp_rankings`,
  `feat/sincsports-via-proxy`, `feat/somsports-scraper`, `scraper/squadi-nj`, plus
  `shell/gotsport-tier-section-parser-02` (the worktree's).
- Full CI gate verified locally: ruff, 2508 pytest, eslint, prettier, tsc, 519 vitest, llms.txt.

## Unrelated, found by the new banner and left alone on request

Two scheduled workflows are failing and are **not** part of item 8:

- `weekly-prospective-refresh.yml` — failed 2026-08-25, 08-18 **and 08-11**. Three weeks.
- `update-missing-club-and-state.yml` — failed 2026-08-24, green 08-17 and 08-10. New.

The user said to leave `weekly-prospective-refresh` for now.

## Next concrete action

Start item 8 by settling the two questions that gate the rest, because both are the user's call
and neither is reversible: **what happens to the 20 files of uncommitted work in
`C:/PitchRank_tournament_beta`**, and **which definition of "orphaned" governs the `docs/` sweep**
(112 unreferenced outside `docs/`, or 78 unreferenced anywhere). Then do the safe, mechanical
parts first — `PROJECT_FLOW.md` and the 39 `origin/claude/*` branches — and land the `docs/`
deletion separately so its diff can be read on its own.
