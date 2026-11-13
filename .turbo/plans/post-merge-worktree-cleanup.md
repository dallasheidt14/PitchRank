---
status: done
---

# Plan: Remove worktree folders once their PR has merged

## Context

On 2026-11-12, 37 linked worktrees sat on this machine. `scripts/pr_wait.py` merges a PR and stops, and nothing on the
PR path ever removes the worktree the work happened in. A survey that day split them as follows:

- 5 belong to a PR that has merged (#1426, #1427, #1430, #1433, #1231). These are the true leftovers, and all 5 are clean.
- 27 have never had a PR opened. Most are Codex experiments, some with 10–25 commits that are not on main.
- The rest are live work, or the hourly team-cleanup task's own folder (`C:\pitchrank-weekly`).

The manual recipe exists only in memory (`merged-branch-cleanup-recipe`, `worktree-remove-deletes-ignored-logs`), and it
has bitten twice:

- `git worktree remove` deletes ignored files with the folder, which once lost a rollback log.
- Removing a folder that a shell still sits in fails with "Permission denied" after git has already deregistered it,
  leaving an empty directory.

Owner decision (2026-11-12, "Merged PRs + list others"):

- Remove worktrees whose PR merged, both the existing five and each new one after `pr_wait.py` merges.
- Also print the never-PR'd folders so the owner can decide on them.
- Delete none of the never-PR'd folders.

The owner chose to plan directly rather than run turboplan.

## Pattern Survey

### Analogous Features
- `.claude/hooks/session-start.sh:71-82`: counts linked worktrees and gone-remote branches, and flags dirty worktrees.
  - The dirty test is `git -C "$wt" status --porcelain` with untracked files counted and ignored files not.
  - The porcelain is parsed as `/^worktree /`, skipping the first entry, which is the main checkout.
  - Pinned by real-temp-repo tests in `tests/unit/test_claude_hooks.py:478-509`.
- `scripts/pr_wait.py`:
  - `resolve_pr` (:85-90) fetches `headRefOid` and `state`.
  - The merge is pinned with `--match-head-commit` (:239). `--dry-run` prints `[dry-run] would run: ...` (:240-242).
  - `--no-merge` returns before the merge (:227-229).
  - Exit codes are documented at :39-40.
- `scripts/team_cleanup/advance.py:185-204`: runs git through subprocess with `cwd=ROOT` and a timeout, and returns a
  reason string instead of raising. `pin_code` keeps `C:\pitchrank-weekly` detached at origin/main.
- `scripts/team_cleanup/windows/register_team_cleanup.ps1:14`: registers the hourly task with `-WorkingDirectory 'C:\pitchrank-weekly'`.
- `scripts/exclude_unplayed_forfeit_games.py:442-509`: dry run by default, `--execute`, logs under `data/backups`, and the
  standard footer `DRY RUN — nothing written. Re-run with --execute.`
- `data/backups/ea-scraper-worktree-2026-10-15/`: a prior hand rescue of one worktree's ignored files into a dated
  folder, keeping their relative paths.

### Reusable Utilities
- `scripts/pr_wait.py:63-71` `gh()` / `gh_json()`: the gh wrappers. They have no encoding and no timeout;
  `scripts/team_cleanup/apply_stage.py:388-413` `_listing` shows the `encoding="utf-8", errors="replace"` + timeout form.
- `src/tournaments/seeding_run_store.py:101` `_shared_checkout_root(project_root)`: finds the primary checkout from a
  linked worktree via `.git` → `commondir`, with no subprocess. It is private to `tournaments`. The script needs the
  same answer, because `Path(__file__)` inside a worktree's copy points at that worktree's own `data/backups`.
- `scripts/apply_vetted_team_merges.py:264` `new_log` (refuses an existing path) and `:280` `write_log` (atomic
  `.tmp` + `os.replace`).
- `tests/unit/test_claude_hooks.py:73-96` `_git` / `_init_repo` / `_fresh_repo`: a real temp repo with
  `update-ref refs/remotes/origin/main HEAD`. These are module-private.
- `tests/integration/test_form_study_registration.py:17-39`: a temp-repo fixture with `core.autocrlf false`, a
  per-command identity, and `commit.gpgsign=false`.

### Convention Anchors
- Script shape:
  - Docstring with `Usage:` and `Exit status:` blocks.
  - `argparse` with `description=__doc__, formatter_class=RawDescriptionHelpFormatter`.
  - `main() -> int`, then `sys.exit(main())`.
  - `ROOT = Path(__file__).resolve().parent.parent`.
- Dry run is the default with `--execute`, which 53 scripts use. Output is plain `print`.
  - CLAUDE.md: a dry run writes nothing, local files included, so the rescue copy is a write.
  - A printed next-step command must follow the run's own mode.
- Import a sibling script packaged (`from scripts.x import ...`), never bare.
- Merged detection: read the PR's state from gh, never `merge-base`. `delete_branch_on_merge` means the remote branch
  is already gone, so only local cleanup remains.
- How tests fake things:
  - Patch the module wrapper by dotted path (`monkeypatch.setattr("scripts.pr_wait.gh", ...)`).
  - Assert expected commands as literal lists.
  - Doubles must refuse what production refuses, carry literals on both sides, and use one fixture per conjunct.
  - A mutation must kill the named new test.
  - No test may reach the real `gh` (logged in on this machine; pr_wait's merge is live).
- CI runs Python tests on Linux, and Windows only for the files listed in `ci.yml`'s Windows job. A `schtasks` or
  rename-probe branch never runs in CI unless it is faked.

### Proposed Alignment
- Shape the new script like `pr_wait.py`, with its own utf-8 + timeout subprocess wrapper.
- Parse porcelain the way `session-start.sh` does, and use the same dirty test.
- Default to a dry run, with the standard footer.
- Put rescues under the main checkout's `data/backups`, found through `commondir`.
- Test git against a real temp repo, and fake gh and schtasks at module level.

## Implementation Steps

0. **Branch setup (local-state hazard).**
   - The main checkout `C:\PitchRank` sits on `chore/carry-forward-local-notes` with unrelated staged files
     (`.claude/skills/supabase-pitchrank/SKILL.md`, `.turbo/improvements.md`, `scripts/view_teams.py`). Do not branch
     in place and do not stash.
   - Create a worktree off `origin/main`: `git worktree add C:/pitchrank-worktree-cleanup -b feat/clean-merged-worktrees origin/main`.
   - Copy this plan file into it.
   - `git -C C:/pitchrank-worktree-cleanup status --porcelain` must be empty, apart from the plan, before edits begin.

1. **Share the checkout-root lookup.**
   - Move `_shared_checkout_root` out of `src/tournaments/seeding_run_store.py` into `src/utils/git_checkout.py` as
     public `shared_checkout_root(project_root: Path) -> Path`.
   - Keep `seeding_run_store` importing it under its old private name, so `tests/unit/test_seeding_run_store.py:46`
     still exercises the same function. Grep for other callers first.
   - Do not write a second copy, per the single-source-of-truth rule.

2. **New script `scripts/clean_merged_worktrees.py`.** Dry run by default, with `--execute`. The docstring carries
   `Usage:` and `Exit status:` (0 ran, 1 refused to run, e.g. schtasks unreadable on Windows).
   - `run(*args, cwd)`: subprocess with `encoding="utf-8", errors="replace"` and a timeout. It returns
     `CompletedProcess` and is the single place every git, gh and schtasks call goes through, so tests record there.
   - `list_worktrees(main_root) -> list[Worktree]`: parses `git worktree list --porcelain`.
     - Fields: path, HEAD, branch (or None when detached), locked, prunable.
     - Drop the first entry, which is the main checkout.
   - `pr_for_branch(branch) -> PrState`: one call to
     `gh pr list --state all --head <branch> --json number,state,headRefOid`, classified as:
     - **open**: any OPEN PR. This wins.
     - **merged**: a MERGED PR whose `headRefOid` equals the worktree HEAD.
     - **merged-with-later-commits**: a MERGED PR whose `headRefOid` does not equal HEAD.
     - **closed**: closed without merging.
     - **none**: no PR at all.
   - `scheduled_task_folders() -> set[Path]`:
     - On `os.name == "nt"`, parse every `Start In:` line of `schtasks /query /fo LIST /v`, skipping `N/A` and
       "Multiple actions".
     - On any other OS, return an empty set.
     - If the query fails on Windows, raise, so the run refuses everything and exits 1. Fail closed.
   - `in_use(path) -> bool`:
     - On Windows, try `os.rename(path, sibling_temp)` and rename it straight back.
     - A `PermissionError` means some process (a shell, an editor, another session) holds the folder.
     - This replaces the memory recipe's "skip folders touched in the last day or two" rule. That rule would also
       block every post-merge cleanup, since a just-merged folder was always just touched. And the temp review
       worktrees it guarded against are detached, so they are never candidates here.
     - Off Windows, return False.
   - `candidate_reason(wt) -> str | None`: `None` means the worktree is removable; otherwise the reason it stays. Its
     checks, in order:
     1. The worktree is detached.
     2. The worktree is locked or prunable.
     3. The PR state is not `merged`.
     4. `git -C <wt> status --porcelain` is non-empty (tracked changes or untracked files).
     5. The path is a scheduled task's Start In folder, or inside one. Compare with `os.path.normcase` on
        `Path.resolve()`, since porcelain says `C:/x` and schtasks says `C:\x`.
     6. The current working directory is inside the worktree.
     7. `in_use(path)` is true.

     Each check yields its own reason string, so each can be tested and mutated alone.
   - `ignored_to_rescue(wt) -> list[Path]`:
     - List ignored entries with `git -C <wt> ls-files --others --ignored --exclude-standard --directory`, so
       dependency folders stay collapsed.
     - Drop the disposable set: `node_modules/`, `__pycache__/`, `.pytest_cache/`, `.ruff_cache/`, `.mypy_cache/`,
       `.next/`, `.vite/`, `*.pyc`, `*.tsbuildinfo`, and `.env` / `.env.local` copies.
     - The `.env` / `.env.local` copies are not duplicated into backups, because the main checkout holds the
       originals. Any other env-style file (`.env.production.local`, a `.env.local.bak-*`) is copied, since it
       may exist nowhere else.
     - Expand the remaining directories into files.
   - `rescue(wt, files, dest_root)`:
     - The destination is `<main_root>/data/backups/worktree-rescue/<YYYY-MM-DD>_<branch with / → ->/`, keyed by
       branch, because a branch can be checked out in only one worktree and many basenames repeat (`PitchRank`, `code`).
     - Refuse an existing destination, as `new_log` does.
     - Copy keeping relative paths.
     - Any copy error aborts that worktree's removal.
   - `remove(wt)`:
     - Run `git -c core.longpaths=true worktree remove <path>` from `main_root`, with no `--force`, so git's own dirty
       check stands as a second guard.
     - Only if that succeeds, run `git branch -D <branch>`. A squash merge is not an ancestor, so `-d` would refuse.
     - On failure, print git's message and continue with the next worktree.
   - `sweep(execute: bool, show_others: bool) -> Report`: the composition, wiring porcelain → gh → checks → rescue →
     remove, and returning what it removed and kept.
     - Dry run prints, for each removable worktree:
       `would remove <path> (#<n> merged); would copy <k> ignored files (<MB>) to <dest>; would delete branch <b>`.
     - Execute prints what it did.
     - With `show_others`, add one line per kept worktree: its path, reason, and for `none` / `closed`, the commits not
       on `origin/main` (`git rev-list --count origin/main..HEAD`) and the last commit's age (`git log -1 --format=%cr`).
     - End a dry run with the standard footer.
   - `main()`: `--execute`. The `main_root` comes from `shared_checkout_root(ROOT)`. Run the git subprocesses with
     `cwd=main_root`.

3. **Hook it into `scripts/pr_wait.py`.**
   - After `gh(*merge)` / `print("merged")` (:243-244), call `sweep(execute=True, show_others=False)` through
     `from scripts.clean_merged_worktrees import sweep`.
     - Put the repo root on `sys.path` first: the script runs as `python scripts/pr_wait.py`, so `sys.path[0]` is
       `scripts/`.
     - Wrap the call in `try/except Exception`. On failure print `worktree cleanup failed: <err>; run
       python scripts/clean_merged_worktrees.py --execute from <main_root>`. The exit code stays 0 because the
       merge succeeded.
   - It sweeps **all** merged worktrees, not just this PR's.
     - `pr_wait` usually runs from inside the PR's own worktree, which `in_use` / cwd then keeps.
     - Sweeping everything removes it at the next merge instead of leaving it forever.
     - When the PR's own worktree is kept for that reason, print the one command to run once the shell has left the
       folder.
   - `--dry-run`: after the existing `[dry-run] would run: gh pr merge ...` line, print
     `[dry-run] would then remove merged worktrees (python scripts/clean_merged_worktrees.py)`, without calling
     anything.
   - `--no-merge`: unchanged; no cleanup.
   - Add `headRefName` to `resolve_pr`'s fields only if the kept-own-worktree message needs it.
   - Update the docstring's flow description.

4. **Tests: `tests/unit/test_clean_merged_worktrees.py`.**
   - Use a real temp repo. Mirror `test_claude_hooks.py`'s `_init_repo` / `_fresh_repo` setup locally, since those
     are module-private. Set `core.autocrlf false`, an identity via `-c`, and an `origin/main` ref.
   - Each worktree comes from `git worktree add -b`.
   - Fake gh by patching the module's gh call (`scripts.clean_merged_worktrees.<gh wrapper>`):
     - The fake honours `--head` and `--state`, and returns `[]` for an unknown branch, as real gh does.
     - It records only when called.
   - Fake schtasks by patching `scheduled_task_folders`.
   - One test per kept reason, each fixture violating exactly one check:
     - detached; open PR; closed PR; merged with later commits; tracked change; untracked file;
     - scheduled-task folder; cwd inside; in-use (patch `os.rename` to raise `PermissionError` with the Windows
       branch forced on); locked.
     - Each asserts the worktree still exists, the branch still exists, and the literal reason.
   - Happy path: one merged, clean worktree with an ignored `data/backups/x.json` and an ignored `node_modules/a.js`.
     - Dry run: nothing removed, nothing copied, the footer printed.
     - Execute: folder gone, branch gone, `x.json` present under `worktree-rescue/<date>_<branch>/data/backups/`,
       `node_modules` not copied, the main worktree untouched.
     - Expected paths, SHAs and commands are literals.
   - A rescue destination that already exists: refused, worktree kept.
   - Schtasks query failure on Windows: `main()` returns 1 and nothing is removed.
   - `tests/unit/test_pr_wait_gating.py`:
     - `test_the_merge_is_pinned_to_the_commit_that_was_inspected` (:125-151) now also patches
       `scripts.pr_wait.sweep` with a recorder and asserts one call with `execute=True`.
     - A new test makes `sweep` raise and asserts `main() == 0` plus the printed fallback command.
     - The `--dry-run` and `--no-merge` tests assert `sweep` is never called (`pytest.fail` recorder).

5. **Docs.**
   - In `CLAUDE.md:37`, add one clause: after merging, `pr_wait.py` removes worktrees whose PR merged, copying their
     ignored files to `data/backups/worktree-rescue/`, and keeps any folder still in use.
   - In `.github/pull_request_template.md:4`, add the same clause if that line describes what happens after the merge.

## Verification

- `python -m pytest tests/unit/test_clean_merged_worktrees.py tests/unit/test_pr_wait_gating.py tests/unit/test_seeding_run_store.py -q`
- Mutation checks:
  - Delete each of the seven checks in `candidate_reason` one line at a time.
  - Each deletion must fail that check's named test, not just redden the suite.
  - Also drop the `--directory` / disposable filter, and the rescue-before-remove ordering.
- Live dry run from `C:\PitchRank`: `python scripts/clean_merged_worktrees.py`.
  - Expect "would remove" for exactly the merged-PR worktrees still present (the five from 2026-11-12, plus this PR's
    once merged), each with a rescue destination.
  - Expect `C:\pitchrank-weekly` kept as a scheduled-task folder.
  - Expect every never-PR'd worktree listed with its commits-not-on-main and last-commit age.
  - Expect nothing on disk to change (`git worktree list` is identical before and after).
- After this PR merges through `pr_wait.py`, run from the feature worktree: confirm the sweep removes the older merged
  worktrees, keeps the feature worktree as in use, and prints the follow-up command. Then run that command from
  `C:\PitchRank` and confirm the feature worktree and branch are gone, and its rescue folder exists.

## Context Files

- `scripts/pr_wait.py`: the script being hooked, and the shape to mirror.
- `tests/unit/test_pr_wait_gating.py`: the merge-path tests that change.
- `.claude/hooks/session-start.sh:71-82`: the existing porcelain parse and dirty test.
- `src/tournaments/seeding_run_store.py:101-130`: the checkout-root lookup being shared.
- `tests/unit/test_claude_hooks.py:73-96,478-509`: the real-temp-repo worktree fixtures to mirror.
- `scripts/apply_vetted_team_merges.py:264-290`: `new_log` / `write_log`, the refuse-existing and atomic-write conventions.

## As built (2026-11-12)

Departures from the steps above, each found while building or verifying:

- **Every PR is looked up before anything is removed.** The first live dry run hit a GitHub timeout partway through.
  With one pass, an `--execute` run would have removed the earlier worktrees and then stopped. It now does all the
  lookups first, eight at a time. That also brought the 38-worktree dry run from 56 s to 24 s.
  `test_github_failing_for_any_branch_stops_the_sweep_before_it_removes_one` pins the ordering.
- **Ignored files are deduplicated.** `git ls-files --directory` listed both `data/` and `data/backups/`, so the
  first version counted and copied every file under them twice.
- **The rename probe runs only under `--execute`.** It renames the folder and back, which is a write, so a dry run
  says it does not test for a held folder.
- **`seeding_run_store` imports `shared_checkout_root` under its public name.** Its tests patch `_PROJECT_ROOT`,
  never the helper, so no private alias was needed.
- **The PR template was left alone.** Its `pr_wait` bullet is about what happens before a merge.

Verification:

- The three test files pass (89 tests).
- Mutations: every guard in `keep_reason`, the scheduled-folder direction, the open-PR precedence, the
  rescue-exists refusal, the disposable filter, deduplication, rescue-before-remove, the Start In refusal, both probe
  behaviours, the retry hint and the lookup ordering. Each was killed by its own named test.
- The four `pr_wait` hook mutations were each killed by their named test.
- The live dry run from `C:\PitchRank` (38 linked worktrees):
  - would remove the four merged and clean ones (#1426, #1427, #1430, #1433);
  - kept #1231, which holds untracked files;
  - kept `C:\pitchrank-weekly`, which is detached;
  - kept the rest as open PRs, never-PR'd or detached;
  - wrote nothing.

### Review round 1 (2026-11-12)

The seven-reviewer pass changed the script in these ways:

- **Folder links are unlinked before removal.** On Windows `git worktree remove` deletes through a junction. A
  worktree set up the usual way has `frontend/node_modules` as a junction into the main checkout's, so removing it
  would have emptied the main install. The reviewer reproduced this. The script now unlinks every folder link inside
  the worktree first (`os.rmdir` on a junction keeps its target), and the copy walk no longer follows links.
  `test_a_folder_link_is_unlinked_first_so_its_target_survives` catches the defect on Windows only, so the test file
  now also runs in ci.yml's Windows job.
- **The folder walk raises instead of skipping.** `os.walk` passed over folders it could not read, so files there
  were neither copied nor a reason to keep the worktree. It now raises, and walks with the `\\?\` long-path prefix
  on Windows, since this machine has long paths disabled.
- **New reasons to keep a worktree:**
  - another registered worktree sits inside it;
  - its HEAD moved after the PR lookup;
  - it has untracked files, read with `--untracked-files=normal` so the setting that hides them is overridden.
- **Failures come back as results.** `run()` turns a command that cannot start or finish into a failed result.
  `gh` output that is not JSON stops the sweep. `git worktree remove` gets a 900 s limit.
- **The main checkout is git's own first porcelain entry.** Step 1 above was reverted: `seeding_run_store` is
  unchanged, and the script no longer imports `src.utils`.
- **A second rescue on the same day takes `<name>-2`** instead of keeping the worktree.
- **Smaller changes:** git runs with `--no-optional-locks`, the skip states are folded into `KEPT_FOR_STATE`, and
  the open-folder wording now says what the probe detects: a process running in the folder, or a file open in it.
  A watcher on the folder itself, or a PowerShell sitting in it, does not block the rename. In both cases git then
  removes the folder cleanly.
- **Left as they are:**
  - "Multiple actions" scheduled tasks: 1 of 306 on this machine, and it is Microsoft's.
  - The 100-PR lookup cap.
  - Porcelain `-z`: Windows forbids newlines in paths.
  - pr_wait's own `gh` wrapper, which predates this change.
  - Broadening the env-file filter.
  - The forfeit script writing its log inside the worktree, which is out of scope.

Re-verified after the round:

- 102 tests pass, including a real Windows check: a process running in the folder makes the probe report it in use.
- A second mutation battery of 37, covering every guard above, was killed in full, each mutation by its own named
  test.
- The full CI suite passed except 2 Compare-predictor tests and 1 registration-fixture error. All three need
  `frontend/node_modules`, which the feature worktree lacks, and all three pass in `C:\PitchRank`.
