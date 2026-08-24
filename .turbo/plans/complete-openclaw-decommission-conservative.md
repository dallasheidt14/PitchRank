---
status: done
---

# Plan: Complete the openclaw decommission — remove leftover persona artifacts (conservative scope)

## Context

PR #879 (`chore/decommission-openclaw`, commit `5d18f795b`) merged to `origin/main` and decommissioned the retired openclaw multi-agent persona system — it removed the frontend Mission Control subsystem, the `.claude/skills/*` persona skills, the `memory/WORKING-*` working files, eight sibling persona docs (LEARNINGS, GOTCHAS, DECISION_TREES, SKILLS_ROADMAP, WEEKLY_GOALS, AGENT_MODELS, CODEY_TEMPLATES, INCIDENT_PLAYBOOK), `SUB_AGENTS.md`, `moltbot.json`, and added a DB-teardown migration. Its file survey under-scoped the cleanup and left a set of persona operational artifacts behind in `docs/`, `scripts/`, and `reports/`.

This plan completes the decommission for the **conservative scope only**: the 12 clearly-dead persona artifacts that have been verified to have no live consumers. A separate, later judgment pass will decide the fate of ~14 "ambiguous" docs (SEO/content/data-quality reference material that merely mentions a persona); those are **explicitly out of scope here**. The outcome is a small follow-up deletion PR off `origin/main` that references #879 as its parent.

## Pattern Survey

### Analogous Features
- `git show 5d18f795b` (#879, the predecessor decommission) — The prior art for this exact cleanup. On `CLAUDE.md` it removed: the `frontend/lib/agents/` and `frontend/lib/agent-config.ts` directory-tree lines, the `memory/` description ("Agent working memory" → "Investigation notes & working logs"), agent mentions in the auth-helper comment, the entire `## Agent System` section (the 8-persona table), and two "Agent config" rows in the file-location table. On `frontend/CLAUDE.md` it removed the `components/agent-hq/` and `lib/agents/` tree lines, three admin API route bullets, and an agent mention in an auth comment. **Pattern: strip whole persona sections/rows/tree-lines wholesale; rewrite (not delete) any surrounding descriptive line that merely mentioned agents.** This follow-up mirrors it for the leftover doc/script artifacts.

### Reusable Utilities
None. This is a pure deletion with no reusable-code surface.

### Convention Anchors
- **Dangling-reference surfaces (load-bearing).** On `origin/main`, the only references to the 12 target files from SURVIVING (non-deleted) files are exactly two:
  - `docs/DATA_QUALITY_CHECKLIST.md:68-69` — TWO dangling bullets under the "## Automation Scripts" list: `scripts/run_weekly_cleany.py` (line 68 — deleted by this PR) and `scripts/club_name_normalizer.py` (line 69 — a **pre-existing** dangling ref; this script does not exist on origin/main, the live equivalent is `src/utils/club_normalizer.py`). The other two siblings, `scripts/team_name_normalizer.py` and `scripts/find_duplicates.py`, do exist. **Remove both dangling bullets** (per user decision to fix line 69 as same-list hygiene, even though it is not an openclaw artifact).
  - `memory/2026-02-15.md:6` — `- DAILY_CONTEXT.md updated with findings` (basename only, no link, inside a dated historical log). **Frozen history; leave as-is** (file is explicitly preserved).
  - Every other grep hit is a self-reference INSIDE one of the 12 doomed files (vanishes on deletion) or coincidental (`PATTERNS`/"Patterns" prose in `CLAUDE.md:196`, `frontend/CLAUDE.md:136/192` is unrelated to `docs/PATTERNS.md`).
- **No central docs index/TOC exists** on `origin/main` (no `docs/README.md`, `docs/index.md`, `SUMMARY.md`, `mkdocs.yml`). Top-level `README.md` references none of the 12. Nothing to update.
- **llms.txt is clean.** `frontend/public/llms.txt` and its generator `frontend/scripts/generate-llms-txt.ts` reference none of the 12 (the generator covers blog/marketing content, not `docs/`/`scripts/`). No regeneration needed.
- **Workflows are clean.** No `.github/workflows/*.yml` references `movy_report`, `run_weekly_cleany`, or `watchy_health_check`. No workflow edits.
- **Commit convention:** `type(scope): subject (#PR)`, lowercase imperative; cleanup uses `chore:` (scopeless is fine — #879 used `chore: decommission…`). Footer: single `Co-authored-by: Claude Opus 4.8 (1M context) <noreply@anthropic.com>` line.

### Proposed Alignment
Follow #879's pattern: delete the 12 files, additionally remove the two dangling bullets at `docs/DATA_QUALITY_CHECKLIST.md:68-69`, leave the frozen `memory/2026-02-15.md:6` history line alone. No docs-index/llms.txt/workflow changes. `chore:`-prefixed message with the standard footer.

## Implementation Steps

1. **Create an isolated worktree off `origin/main` (local-state hazard — read carefully)**
   - The `C:\PitchRank` checkout is on an unrelated branch `fix/modular11-events-division-mapping` with staged unrelated work (somsports scraper, config), modified files, deleted logos, and dirty `.pyc` files — AND it **predates** commit `5d18f795b`. Do **not** branch in place (would bundle unrelated work and use the wrong base), and do **not** `git stash` (dirty `.pyc` files — see auto-memory `feedback_git_stash`).
   - From `C:\PitchRank`: `git fetch origin --prune`, then `git worktree add -b chore/decommission-openclaw-followup C:\pitchrank-openclaw-cleanup origin/main`.
   - Verify the baseline before any edits: in the worktree, `git status --short` must be **empty**; `git merge-base --is-ancestor 5d18f795b HEAD && echo OK` must print `OK` (decommission is in history). If the tree is not clean or the ancestor check fails, stop and re-create the worktree.
   - This is deletion-only: **no** `npm install`, `node_modules`, `frontend/.env.local`, or build is needed.

2. **Re-confirm no live consumers (in the worktree)**
   - Scripts have no CI/code callers: `git grep -nE "movy_report|run_weekly_cleany|watchy_health_check" -- '.github/**' 'src/**'` → expect **no output**.
   - Enumerate all surviving references to the 12 targets: `git grep -nE "AGENT_COMMS|AGENT_COLLABORATION|CODEY_TRUST_ZONE|CODEY_SEO_FIX_REPORT|DAILY_CONTEXT|LEARNINGS_TEMPLATE|SELF_IMPROVEMENT_LOOP|movy_report|run_weekly_cleany|watchy_health_check|movy_weekly_2026_02_10"` and confirm the only hits from files NOT in the delete list are `docs/DATA_QUALITY_CHECKLIST.md` (handled in step 4) and `memory/2026-02-15.md` (left alone). (Omit a bare `PATTERNS` term here — it's noisy prose; the only real `docs/PATTERNS.md` refs live inside doomed files.)

3. **Delete the 12 clearly-dead persona artifacts**
   - `git rm docs/AGENT_COMMS.md docs/AGENT_COLLABORATION.md docs/CODEY_TRUST_ZONE.md docs/CODEY_SEO_FIX_REPORT.md docs/DAILY_CONTEXT.md docs/LEARNINGS_TEMPLATE.md docs/SELF_IMPROVEMENT_LOOP.md docs/PATTERNS.md scripts/movy_report.py scripts/run_weekly_cleany.py scripts/watchy_health_check.py reports/movy_weekly_2026_02_10.md`

4. **Fix the dangling references (hygiene only)**
   - In `docs/DATA_QUALITY_CHECKLIST.md`, under the `## Automation Scripts` heading, remove **both** of these dangling bullets:
     - `` - `scripts/run_weekly_cleany.py` — Full weekly cleanup `` (line 68 — deleted by this PR)
     - `` - `scripts/club_name_normalizer.py` — Club case fixes `` (line 69 — pre-existing dangling ref; script absent on origin/main, live equivalent is `src/utils/club_normalizer.py`)
   - **Preserve** the `## Automation Scripts` heading and the two bullets whose scripts DO exist (`scripts/team_name_normalizer.py`, `scripts/find_duplicates.py`) and the rest of the file untouched. This file is in the deferred "ambiguous" set; this is a broken-link fix, **not** a keep/delete content judgment on the doc.
   - Do **not** modify `memory/2026-02-15.md` (frozen dated history, explicitly preserved). Do **not** touch any other ambiguous doc or `frontend/supabase/migrations/*`.

## Verification

- **No surviving references remain:** in the worktree, `git grep -nE "AGENT_COMMS\.md|AGENT_COLLABORATION\.md|CODEY_TRUST_ZONE\.md|CODEY_SEO_FIX_REPORT\.md|DAILY_CONTEXT\.md|LEARNINGS_TEMPLATE\.md|SELF_IMPROVEMENT_LOOP\.md|docs/PATTERNS\.md|movy_report\.py|run_weekly_cleany\.py|watchy_health_check\.py|movy_weekly_2026_02_10"` → the **only** expected hit is `memory/2026-02-15.md` (the frozen `DAILY_CONTEXT.md` history line). Anything else is a missed dangling reference to fix.
- **Change set is exactly as scoped:** `git status --short` shows 12 deletions (`D`) + 1 modification (`M docs/DATA_QUALITY_CHECKLIST.md`) and nothing else.
- **No dangling bullets remain in the edited list:** every `` - `scripts/…` `` bullet still under `## Automation Scripts` in `docs/DATA_QUALITY_CHECKLIST.md` must resolve to a real file. After the edit only `scripts/team_name_normalizer.py` and `scripts/find_duplicates.py` should remain — confirm both exist (`test -e scripts/team_name_normalizer.py && test -e scripts/find_duplicates.py`) and that no `run_weekly_cleany.py` or `club_name_normalizer.py` bullet survives.
- No build/test step — these files have zero live consumers (re-confirmed in step 2), so there is no observable runtime behavior to exercise.
- **PR framing (content, not mechanics):** the commit/PR is a `chore:` cleanup, e.g. title `chore: complete openclaw decommission — remove leftover persona artifacts`; body lists the 12 deleted files, notes the single `DATA_QUALITY_CHECKLIST.md` dangling-link fix, references #879 as the parent decommission, and states that ~14 ambiguous SEO/content/data-quality docs are deferred to a later judgment pass. Footer: `Co-authored-by: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`. Open the PR with base `main`. After merge, remove the worktree (`git worktree remove C:\pitchrank-openclaw-cleanup`) and delete the branch to avoid sprawl.

## Context Files

- `.turbo/improvements.md` (last entry, "Complete the openclaw decommission…") — the backlog item this plan implements; defines the clearly-dead vs deferred-ambiguous split.
- `docs/DATA_QUALITY_CHECKLIST.md` — the only surviving file to edit; read the `## Automation Scripts` section before removing both dangling bullets (lines 68-69).
- `git show 5d18f795b` (#879) — prior-art decommission diff; mirror its wholesale-removal pattern and commit/footer style.
- The 12 deletion targets are removed, not read — no need to open them.
