# Improvements — archive

Closed entries moved out of `.turbo/improvements.md` so the live backlog stays the
list of open work. IDs are stable and never reused, so a reference to `IMP-042`
resolves here or there but never to two different items.

Nothing in this file is open. See `.turbo/improvements.md` for the schema.

### calculate_rankings.py --dry-run still persists game residuals + explainability

- **ID**: IMP-057
- **Status**: done
- **Type**: direct
- **Category**: reliability
- **Where**: `scripts/calculate_rankings.py` (compute_all_cohorts call sites ~745-770), `src/rankings/calculator.py:50`
- **Why**: `--dry-run` gates the rankings save (lines 987-997) but never passes `persist_game_residuals=False`, so a `--dry-run --ml` run still writes `batch_update_ml_overperformance` + explainability to prod games during Pass 2. Fix: pass `persist_game_residuals=not args.dry_run` at all compute_all_cohorts call sites.
- **Noted**: 2026-06-11
- **Refs**: fix/dry-run-skip-residual-history-writes (2026-08-24) — persist flags + save_snapshot wired at both call sites; tests/unit/test_dry_run_skips_persistence.py

### Fix main-red test: _DummySupabase mock missing .table after #884

- **ID**: IMP-060
- **Status**: done
- **Type**: direct
- **Category**: testing
- **Where**: `tests/unit/test_ranking_history_relocation.py` (test_compute_all_cohorts_invokes_calculate_rank_changes_after_final_rank)
- **Why**: Red on main at 8044d8477 — #884's metadata fetch path now calls `client.table(...)` which the `_DummySupabase` mock lacks (`AttributeError`). Every PR inherits the failure. Fix: add a `table()` stub returning the dummy query chain (test_glicko_sos_role.py's `_DummySupabaseQuery` has the pattern).
- **Noted**: 2026-06-12
- **Refs**: #886 (merged) — the entry said 'awaiting merge'; it landed
- **Update**: Fix authored in PR #886 (2026-06-12), awaiting merge

### Roll config/settings.py _BIRTH_YEARS forward for the 2026-27 season

- **ID**: IMP-072
- **Status**: done
- **Type**: plan
- **Category**: reliability
- **Where**: `config/settings.py:88-102` (`_BIRTH_YEARS` feeding `AGE_GROUPS`), consumer `dashboard.py:4407`, stale copy `dashboard.py:641,658`, stale comment `config/settings.py:90`
- **Why**: `_BIRTH_YEARS` hardcodes the 2025-season map (`10: 2016 … 17: 2009, 19: 2007`) and never rolls, while `_soccer_season_year()` advances on its own every Aug 1. `dashboard.py:4407` writes `'birth_year': AGE_GROUPS.get(new_age_group, {}).get('birth_year')` on every admin team edit, so once the Aug 2026 rollover relabels `teams.age_group`, setting a team to u11 writes `birth_year` 2015 when a 2026-27 u11 is born 2016 — and `scripts/fix_team_age_groups.py` then reads that wrong year and rolls the team's `age_group` back down a cohort. Goes live the moment the migration is applied. Deferred out of the rollover PR (plan item 6) because the constant has 12+ consumers whose blast radius was never surveyed; start with that audit. Surfaced by review-consistency during /polish-code on the age rollover.
- **Noted**: 2026-07-31
- **Refs**: fix/derive-birth-years-from-season (2026-08-24) — derived from team_utils.CURRENT_YEAR; consumer audit done

### Two GotSport tier-persistence tests are failing on main

- **ID**: IMP-093
- **Status**: done
- **Type**: investigate
- **Category**: testing
- **Where**: `tests/integration/test_gotsport_tier_persistence.py` (`test_golden_path_persists_tier_fields_to_jsonl`, `test_u7_micro_cohort_dropped_loose_age_kept`), raised from `src/scrapers/gotsport_tier_parser.py:764`
- **Why**: Both fail with `TierSubfetchError: event 42433 group 365847 subfetch failed (malformed_html) ... zero ?team= anchors; residue='Red'`.
- **Noted**: 2026-08-19
- **Refs**: #978 — misdiagnosed as main-red; the tests only fail where ZENROWS_API_KEY is set, fixed by pinning use_zenrows = False in the fixture

### Make calculate_rankings --dry-run actually skip every write

- **ID**: IMP-100
- **Status**: done
- **Type**: direct
- **Category**: reliability
- **Where**: `scripts/calculate_rankings.py:741-768`, `src/rankings/calculator.py:2306-2335,2476,3347`
- **Why**: `--dry-run` prints "no database writes" but calls `compute_all_cohorts` without passing it, so game residuals (`_persist_game_residuals`) and the `ranking_history` snapshot (`save_snapshot=True` default) are persisted before the CLI's guards. Pass `persist_residuals=False, save_snapshot=False` when `args.dry_run`.
- **Noted**: 2026-08-23
- **Refs**: fix/dry-run-skip-residual-history-writes (2026-08-24) — same fix as the narrower residuals entry above it

### Set the ANTHROPIC_API_KEY secret so automated PR review runs again

- **ID**: IMP-078
- **Status**: dropped
- **Type**: direct
- **Category**: dx
- **Where**: repo secrets, consumed by `.github/workflows/claude-code-review.yml`
- **Why**: The `claude-review` check logs `ANTHROPIC_API_KEY:` empty and fails on every PR.
- **Noted**: 2026-08-11
- **Refs**: Duplicate of IMP-104, and the premise is wrong either way — the workflow reads `CLAUDE_CODE_OAUTH_TOKEN` (`claude-code-review.yml:38`), never `ANTHROPIC_API_KEY`; `git log -S ANTHROPIC_API_KEY` on that file returns nothing. Setting the named secret would have changed nothing. Tracked as IMP-104.

### Fix or disable the always-failing claude-review workflow

- **ID**: IMP-104
- **Status**: done
- **Type**: direct
- **Category**: dx
- **Where**: `.github/workflows/claude-code-review.yml` + repo Actions secrets
- **Why**: The check fails on every PR and is not required, so a permanent red X sits beside the seven that are — which trains reviewers to ignore red. Still live as of 2026-08-25 (#1025, #1026). The remedy is **not** the `ANTHROPIC_API_KEY` secret this entry and IMP-078 both named: the workflow reads `CLAUDE_CODE_OAUTH_TOKEN` at line 38, that secret is present, and the run fails on its first turn with $0 spend — an auth rejection, not a missing secret. Diagnose the token, or disable the workflow.
- **Noted**: 2026-08-23 (premise corrected 2026-08-25; absorbed IMP-078)
- **Refs**: #1039 (`chore/disable-claude-review-trigger`)
- **Update (2026-08-26)**: the `pull_request` trigger is commented out, so the red X is gone.
  Traced one more level first: Claude Code initializes and reports `claude-sonnet-5`, then the
  run ends after one turn in 1.9s with `total_cost_usd` 0 and an empty `modelUsage` — the first
  model call is rejected, confirming a live-but-rejected `CLAUDE_CODE_OAUTH_TOKEN` rather than a
  missing secret. Rotating that secret is the remaining work and it is not a repo change;
  re-enabling afterwards is a two-line edit. `claude.yml` was left alone — it only fires on
  `@claude` mentions and contributed no red check.

### Work through items 2–8 of the 2026-08-24 agent-readiness review

- **ID**: IMP-117
- **Status**: done
- **Type**: plan
- **Category**: dx
- **Where**: https://claude.ai/code/artifact/9e4525fa-4bb1-4844-9ea4-873e36de5d6f (98 cited findings); CLAUDE.md, .claude/, .github/workflows, docs/
- **Why**: The review's ranked plan lives only in the artifact. Shipped: item 1 agent-reachable credentials (#1019), item 2 documented commands = CI commands plus the wrong code patterns (#1023), item 3 part 1 the doc-reference parity test (#1024), item 3 part 2 the seven remaining contradictions given one owner each (#1025), item 3 part 3 the prose de-duplication — seven duplicated bodies each given one owner, measured rather than estimated (the "31 bodies" figure was a duplicated-*line* count) (#1026). **Item 3 is done.** Item 4 is done too: this file's own lifecycle — the ID/Status schema, `scripts/sweep_improvements.py`, the `sweep-improvements` skill, `.turbo/improvements-archive.md` and `tests/unit/test_improvements_backlog.py`. Still open: item 6 a richer session-start hook; item 7 the git-guard gaps; item 8 retiring contradicting docs, the always-red claude-review workflow (tracked separately as IMP-104), and the stale worktree/branches.
- **Noted**: 2026-08-24 (updated 2026-08-25, after item 4)
- **Refs**: #1034, #1035, #1036, #1037, #1038, #1039, #1040
- **Update (2026-08-26)**: item 8 is done, and with it all eight. `PROJECT_FLOW.md` says
- **Update (2026-08-25)**: item 7 is done too. `git-guard.sh` now reads a shell wrapper's quoted argument as a command (`powershell -Command "git push --force"` and four other spellings passed straight through before), refuses `commit --amend` once HEAD is on a remote, and resolves `git -C <dir>` / a leading `cd <dir>` once so the checks read the repository git will actually run in. The review's fourth piece, a content gate on ranking-engine paths, was built and then dropped on request: it was the one part that added a new stop rather than restoring a guarantee CLAUDE.md already made, and the friction was not wanted. `dry-run-check.sh` now fires when a tracked file gains a Supabase write, not only on brand-new files. Measured before changing anything: wrapper-plus-git usage across 5,618 calls was zero, so blocking it costs nothing, while `git commit --amend` had 7 legitimate uses, which is why that one keys on whether HEAD is pushed rather than refusing outright.
  Glicko-2 where production runs Glicko-2, and four adjacent claims in the blocks it touched were
  wrong too and were corrected against code: ML alpha is 0.08 not 0.12, the residual floor is 12
  games not 6, `RANKING_CONFIG` is the v53e parameter set rather than the Glicko-2 one, and
  `rankings_full` is the primary output table rather than `current_rankings`. `--ml` turned out to
  be a no-op: `Layer13Config.__post_init__` overwrites `enabled` from `ML_CONFIG` whatever the
  caller passed, so `ML_LAYER_ENABLED` is the real switch (#1035). `docs/` went from 123 files to
  36 — the 87 that nothing in the repo references, verified afterwards to leave zero dangling
  links; the stricter reading would have taken 111 and was not used (#1038). The 39
  `origin/claude/*` branches are deleted, with a manifest committed first because six of them held
  work that never landed anywhere (#1036). The `C:/PitchRank_tournament_beta` worktree is gone; its
  branch was already on `origin` at the same commit, so only its loose edits needed keeping
  (#1037). `claude-review` no longer runs on PRs (#1039, closing IMP-104).
  **The review's own numbers were wrong twice.** It said 87 orphaned docs and the last handoff
  re-measured that as 78; two independent methods both return 87, so the review was right and the
  correction was the error (#1034). Two findings in this arc were also introduced *by* a fix —
  disabling `claude-review` left `CLAUDE.md` and the PR template telling reviewers it still runs,
  and the archived `run_intake.ps1` kept a usage line that cannot work from `.turbo/reports`.
  Codex caught both, plus a real bug in `pr_wait.py`: it read `headRefOid` to check Codex's review
  and then merged without `--match-head-commit`, so it could merge a commit it never inspected —
  the exact hole that ruled out `gh pr merge --auto` (#1040).

### UnknownOpponentLink subline duplicates club_name visible in composed line above

- **ID**: IMP-031
- **Status**: dropped
- **Type**: plan
- **Category**: readability
- **Where**: `frontend/components/UnknownOpponentLink.tsx` (search dropdown row :549-552 + selected-team confirmation panel :677-679); same pattern likely exists in `RankingsTable.tsx` after PR #722
- **Why**: After the composeTeamDisplay rollout, the composed top line begins with `abbreviateClubName(club_name)`, and the muted subline immediately below renders raw `team.club_name` again — e.g. `Phoenix Rising SC ECNL White` / `Phoenix Rising Soccer Club • AZ • U14 Boys`. Visually duplicates club identity in two forms. PR #722 introduced this for the rankings table by design ("keep club identity and region visible at a glance"), but in a search dropdown row where vertical space matters more, the redundancy is more pronounced. Fix: drop `club_name` from subline in UnknownOpponentLink dropdown + selected-team confirmation; keep state/age/gender. Consider mirroring in rankings table for consistency. Pre-existing PR #722 design choice; flagged 2026-05-05 during /polish-code on the rollout PR. **Partially addressed 2026-08-18** (branch fix/search-result-labels): both sublines now delegate state/age/gender to composeTeamMeta, fixing a literal U0 and a double bullet in the confirmation panel. The club_name redundancy this entry describes is unchanged as of that date.
- **Noted**: 2026-05-05
- **Refs**: branch `show-team-name-in-rankings` (teamDisplayName rollout, which inverted this entry's premise)
- **Update (2026-08-27)**: Premise inverted, closing as dropped. The rankings/search top line is no longer `abbreviateClubName(club_name)` — `teamDisplayName` renders the registered `team_name` (branch `show-team-name-in-rankings`), so the subline's club is no longer a second form of the line above it. The same PR *added* the subline to `GlobalSearch` and `TeamSelector` for exactly that reason: `useTeamSearch` matches on `club_name`, so without it a row matched by club looks unrelated to the query. The redundancy this entry describes does survive for the ~39% of ranked teams whose `team_name` embeds its `club_name` (46,248 of 119,949 measured 2026-08-27) — that is now an accepted cost of club-matched search legibility, not an oversight.

### Fix `fetchModular11TeamIds` silent empty-Set under anon RLS — MLS Next short-circuit no-op in global search

- **ID**: IMP-034
- **Status**: dropped
- **Type**: investigate
- **Category**: reliability
- **Where**: `frontend/hooks/useTeamSearch.ts` (`fetchModular11TeamIds`, lines ~24-46); Supabase RLS on `team_alias_map` + `providers`
- **Why**: PR #722 added a `has_modular11_alias` short-circuit in `composeTeamDisplay` so MLS Next teams render their clean raw `team_name`. The flag is populated by `fetchModular11TeamIds()` querying `team_alias_map` joined to `providers!inner` filtered by `code = 'modular11'`. Under the anon Supabase key, this returns an empty Set — verified live during PR #726 testing: `Phoenix Rising AD` search showed MLS Next teams as `Phoenix Rising FC MLS Next AD AD` instead of clean `Phoenix Rising FC U13 AD`. ~14k MLS Next teams affected. No console warning fires (zero rows ≠ error), so the failure was invisible until manual UI verification. Likely RLS on `team_alias_map` and/or the embedded join blocking anon SELECT — service-role queries from Python confirm the data is present. Fix candidates: (a) grant anon SELECT on `team_alias_map` + `providers` (low risk, both reference data), or (b) move the modular11 lookup server-side and ship the flag in `useTeamSearch`'s payload (cleaner). Either way, also harden `fetchModular11TeamIds` to log a warning when the Set is empty so future regressions surface in the console. PR #726 (`70d9a097c`) mitigates the UX impact via the disambiguator subline but the short-circuit itself remains broken.
- **Noted**: 2026-05-06
- **Refs**: superseded by IMP-119 (remove `has_modular11_alias` end-to-end)
- **Update (2026-08-27)**: Superseded by IMP-119 — do not fix this, remove it. `teamDisplayName` (branch `show-team-name-in-rankings`) means `composeTeamDisplay` now runs only for blank/`unknown_` names, so the short-circuit this entry wants working can no longer affect any rendered string. Repairing the RLS grant would restore a branch that IMP-119 shows is counterproductive.

### Reclaim scrape_requests rows stranded in 'processing'

- **ID**: IMP-127
- **Status**: done
- **Type**: plan
- **Category**: reliability
- **Where**: `scripts/process_missing_games.py:434` (sets 'processing'), `scripts/drain_queue.py:319-371` (`_finalize_queue_items` / `_release_queue_items`), `supabase/migrations/20260526100000_claim_queue_items.sql` (claims only 'pending')
- **Why**: Measured 2026-08-27, `scrape_requests` holds **6,482 rows permanently in `processing`** — ~4% of the 169,999 ever created (160,550 completed, 2,690 failed, 279 pending). Nothing reclaims them: no lease, no expiry, no reaper, and `claim_queue_items` selects only `pending`. CLAUDE.md documents the mechanism but not that it has accumulated at this scale. Each stranded row is a team whose scrape never completed and which cannot be re-enqueued, because `enqueue_scrape_request` keeps at most one pending row per team and these are not pending — so those teams are silently dropped from the queue-driven pipeline. It also makes queue depth unreadable: at 279 pending the queue is starved, not backlogged, which the raw table does not make obvious.
- **Noted**: 2026-08-27
- **Refs**: PR #1050 (release on interrupt), `scripts/retire_stranded_scrape_requests.py` (cleanup)
- **Update (2026-08-28)**: the "cannot be re-enqueued" reasoning above is **wrong**. `idx_scrape_requests_pending_team` is `UNIQUE … WHERE status = 'pending'`, so a `processing` row does not block a fresh pending one, and 1,974 of the 6,392 stranded teams had already been re-queued. The cost was unreadable queue depth, not lost teams. Root cause was also not gradual decay: a cancelled `clear-queue` run stranded 5,981 rows in one second on 08-23, and a second event added 500. Fixed by releasing claims on interrupt (`BaseException`, since a cancellation is SIGINT) and by `scripts/retire_stranded_scrape_requests.py`, which retired all 6,482 to `failed`. No lease or reaper was needed.
