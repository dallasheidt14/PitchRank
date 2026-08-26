# Deleted `claude/*` branches — 2026-08-26

All 39 `origin/claude/*` branches were deleted on 2026-08-26 as part of item 8 of the agent-readiness plan ("retire what contradicts"). This file is the record of what they were.

## Why they went

They were agent session branches from **2025-11-15 to 2026-04-13**. Not one of them ever opened a pull request — the only `claude/*` branch that ever did was `claude/fix-missing-teams-rankings-RHHh2` (PR #626, merged), and it had already been deleted.

## Read the diff numbers with care

`main` takes squash merges, which rewrite its commits. Every branch here forked before that rewriting caught up with it, so for the older ones `git merge-base origin/main <branch>` resolves all the way back to the **2025-11-03 project root**. A diff against that merge-base therefore shows six weeks of repo history that *did* land on `main` under different SHAs, not the branch's own work. The 400-file, 100k-line numbers are that artifact.

So the file counts below are **not** a measure of unique work, and the manifest does not claim they are. What was checked directly, path by path against today's `origin/main`, is the six branches in the next section.

## The six that held real unlanded work

Each path below was confirmed absent from `origin/main` with `git ls-tree -r --name-only origin/main -- <path>` on 2026-08-26.

| Branch | What it held | Confirmed absent from `main` |
|---|---|---|
| `claude/integrate-pitchrank-clawdbot-1vHyR` | A whole `clawdbot/` package — setup guides, agent definitions, SKILL/SOUL/TOOLS docs. 15 files, 4,562 lines. | `clawdbot/` |
| `claude/pitchrank-instagram-graphics-9vjqp` | Five Instagram SVGs plus captions and prompt notes. | `frontend/public/social/instagram/` |
| `claude/design-pitchrank-animation-2GVfa` | A homepage animation component and its `page.tsx` wiring. | `frontend/components/PitchRankAnimation.tsx` |
| `claude/create-project-skill-hNQLU` | A skill-creator skill. Superseded in practice by the `create-skill` skill now installed. | `.claude/skills/skill-creator/` |
| `claude/move-games-between-teams-beuBa` | A script, a `debug-merge` API route, and a one-off migration for moving Playmaker games. | `scripts/move_games_between_teams.py` |
| `claude/investigate-ranking-tests-GtEVe` | A ranking audit test, 1,029 lines. | `tests/unit/test_ranking_audit.py` |

The rest hold analysis, audit, and review markdown — which is what item 8 exists to retire.

## Recovering one

The tip SHAs are below. GitHub keeps unreachable objects for a while after a branch is deleted, so `git fetch origin <sha>` may still work in the near term. That is not a durable guarantee and the objects are garbage-collected eventually. **Treat this table as a record of what existed, not as a backup.**

## The 39

`Forked` is the merge-base date — where `git` thinks the branch left `main`, per the caveat above.

| Last commit | Branch | Tip SHA | Forked | Commits ahead | Files vs merge-base |
|---|---|---|---|---|---|
| 2025-11-15 | `claude/python-expert-session-01CbJw2UEy7cjbg2VoGHgm42` | `158a26347` | 2025-11-03 | 103 | 220 — see caveat |
| 2025-11-16 | `claude/python-dev-01BSS5rgPuk1HMWRjnZTgBLm` | `4aa623e94` | 2025-11-03 | 109 | 209 — see caveat |
| 2025-11-16 | `claude/review-sos-fixes-011F1sbHuYxCiQ4foJaVXPbS` | `77251a399` | 2025-11-03 | 111 | 214 — see caveat |
| 2025-11-17 | `claude/review-frontend-components-01V4yVJy8e5Lanq31snEFKR9` | `a2d9e8460` | 2025-11-03 | 109 | 210 — see caveat |
| 2025-11-17 | `claude/compare-web-dev-practices-01WCeVG8ePZxvyLhCEFohhWM` | `e0050ce4a` | 2025-11-03 | 110 | 228 — see caveat |
| 2025-11-17 | `claude/python-development-015mskAiqXKrM7PZNZm3mvRq` | `f8476632e` | 2025-11-03 | 122 | 215 — see caveat |
| 2025-11-18 | `claude/review-header-state-rank-018VCmfATKLF9Ag1en9zg3MB` | `d2cc7814d` | 2025-11-03 | 185 | 246 — see caveat |
| 2025-11-18 | `claude/review-weekly-action-01APZu9yZs9URC3parpM3CKg` | `4046ac7a8` | 2025-11-03 | 219 | 261 — see caveat |
| 2025-11-24 | `claude/fix-nc-teams-display-01S2dovP9fRkvHmbsk6JWNaC` | `5a39dce4f` | 2025-11-03 | 506 | 288 — see caveat |
| 2025-11-24 | `claude/review-rankings-component-01J8RzLMkZ1ghqypEKMiicmF` | `1675b5efd` | 2025-11-03 | 510 | 287 — see caveat |
| 2025-11-25 | `claude/fix-team-header-display-01PJKWhFj8VD2wRQErgUeLmv` | `00788fb60` | 2025-11-03 | 537 | 296 — see caveat |
| 2025-11-26 | `claude/review-rankings-engine-01GFbtYpYLhHRjLNJGSBQ4SD` | `aff1b231a` | 2025-11-03 | 546 | 297 — see caveat |
| 2025-12-10 | `claude/fix-frontend-loading-011JsMgETPHGP5kJR8p7qyDH` | `8a0edaf54` | 2025-11-03 | 814 | 360 — see caveat |
| 2025-12-10 | `claude/investigate-missing-team-states-01FUNqzLv8f1xnjpbBqtU8f7` | `35ab457f8` | 2025-11-03 | 814 | 361 — see caveat |
| 2025-12-11 | `claude/frontend-audit-testing-01XDSg7313zcJgtKVKTQsAjd` | `dea888763` | 2025-11-03 | 851 | 393 — see caveat |
| 2025-12-16 | `claude/add-team-state-code-lookup-GTQYR` | `4578c8df3` | 2025-11-03 | 933 | 411 — see caveat |
| 2025-12-23 | `claude/investigate-team-merge-alias-awmoT` | `7288e2c08` | 2025-11-03 | 1010 | 425 — see caveat |
| 2025-12-24 | `claude/fix-streamlit-white-screen-Pzt1a` | `a18d2d2cb` | 2025-11-03 | 1011 | 425 — see caveat |
| 2025-12-28 | `claude/review-team-performance-iBe1X` | `a1537ca90` | 2025-11-03 | 1011 | 426 — see caveat |
| 2026-01-01 | `claude/ai-search-optimization-wENzu` | `eb68e1997` | 2025-11-03 | 1031 | 432 — see caveat |
| 2026-01-16 | `claude/fix-games-import-conflict-aDD57` | `c042f3a8d` | 2025-11-03 | 1060 | 439 — see caveat |
| 2026-01-27 | `claude/integrate-pitchrank-clawdbot-1vHyR` | `8dfeae85f` | 2026-01-23 | 6 | `clawdbot/COMPLETE_SETUP_GUIDE.md`<br>`clawdbot/MAC_MINI_SETUP.md`<br>`clawdbot/SKILL.md`<br>`clawdbot/SOUL.md`<br>`clawdbot/TOOLS.md`<br>`clawdbot/__init__.py`<br>`clawdbot/agents/README.md`<br>`clawdbot/agents/cleaner.md`<br>…and 7 more |
| 2026-02-09 | `claude/review-code-audit-rankings-0OHq7` | `34d4677ae` | 2026-02-08 | 2 | `AUDIT_U14_MALE_AZ_RANKINGS.md` |
| 2026-02-11 | `claude/create-project-skill-hNQLU` | `73d21d3bb` | 2026-02-11 | 1 | `.claude/skills/skill-creator/SKILL.md`<br>`.claude/skills/skill-creator/references/output-patterns.md`<br>`.claude/skills/skill-creator/references/workflows.md`<br>`.claude/skills/skill-creator/scripts/init_skill.py`<br>`.claude/skills/skill-creator/scripts/package_skill.py` |
| 2026-02-11 | `claude/meta-cognitive-reasoning-3PZnb` | `288439d5b` | 2026-02-11 | 3 | `docs/RANKINGS_ENGINE_AUDIT.md`<br>`src/etl/v53e.py` |
| 2026-02-18 | `claude/review-ranking-engine-Qpnhx` | `0944e8302` | 2026-02-17 | 4 | 9396 — see caveat |
| 2026-02-23 | `claude/debug-tgs-scrape-action-sp2zX` | `b88162d66` | 2026-02-23 | 2 | `scripts/extract_and_import_tgs_teams.py`<br>`scripts/scrape_tgs_event.py`<br>`src/utils/team_utils.py` |
| 2026-02-23 | `claude/fix-team-game-count-VzuRI` | `db0f1dea8` | 2026-02-23 | 1 | `scripts/diagnose_team_games.py`<br>`src/rankings/data_adapter.py` |
| 2026-02-26 | `claude/llm-seo-analysis-1hWjy` | `5d892ede0` | 2026-02-24 | 1 | `docs/GEO-REDDIT-STRATEGY.md` |
| 2026-03-05 | `claude/fix-gh-action-game-import-ra2Hr` | `c7c7b4431` | 2026-03-04 | 2 | `.github/workflows/process-missing-games.yml`<br>`frontend/hooks/useScrapeRequestNotifications.ts`<br>`scripts/process_missing_games.py` |
| 2026-03-10 | `claude/review-etl-pipeline-GDoSb` | `c16355af9` | 2026-03-10 | 2 | `docs/etl-pipeline-review-2026-03-10.md` |
| 2026-03-10 | `claude/audit-performance-MNzCN` | `0b4f159bb` | 2026-03-10 | 2 | `docs/performance-audit-2026-03-10.md` |
| 2026-03-11 | `claude/move-games-between-teams-beuBa` | `78140bf54` | 2026-03-11 | 5 | `frontend/app/api/debug-merge/route.ts`<br>`scripts/move_games_between_teams.py`<br>`supabase/migrations/20260311000000_move_playmaker_games_between_premier_touch_teams.sql` |
| 2026-03-12 | `claude/pitchrank-instagram-graphics-9vjqp` | `0d6573860` | 2026-03-11 | 2 | `frontend/public/social/instagram/01-what-is-pitchrank.svg`<br>`frontend/public/social/instagram/02-how-rankings-work.svg`<br>`frontend/public/social/instagram/03-national-coverage.svg`<br>`frontend/public/social/instagram/04-weekly-rankings-teaser.svg`<br>`frontend/public/social/instagram/05-find-your-team.svg`<br>`frontend/public/social/instagram/CAPTIONS-AND-POST-ORDER.md`<br>`frontend/public/social/instagram/NANO-BANANA-PROMPTS.md` |
| 2026-03-13 | `claude/design-pitchrank-animation-2GVfa` | `a21c68cec` | 2026-03-11 | 1 | `frontend/app/page.tsx`<br>`frontend/components/PitchRankAnimation.tsx` |
| 2026-03-14 | `claude/add-claude-documentation-ReLqE` | `55bb88a56` | 2026-03-13 | 1 | `CLAUDE.md` |
| 2026-03-21 | `claude/investigate-ranking-tests-GtEVe` | `26bedd82a` | 2026-03-20 | 1 | `tests/unit/test_ranking_audit.py` |
| 2026-03-25 | `claude/audit-github-cleanup-u12mx` | `f28e49ea3` | 2026-03-25 | 1 | 69 — see caveat |
| 2026-04-13 | `claude/stripe-webhooks-streamlit-setup-2C9c4` | `db480b91d` | 2026-04-11 | 1 | `frontend/app/api/stripe/checkout/__tests__/route.test.ts` |
