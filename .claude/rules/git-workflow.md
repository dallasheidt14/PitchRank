# Git Workflow Safety

## Verify branch before every commit
Always run `git branch --show-current` before `git commit`. The sandbox resets CWD between Bash calls, which can silently switch back to main. Commits have landed on main instead of feature branches because of this.

## git stash works; preserve the staged split
The old prohibition existed because 9,381 `.pyc` files were tracked, so every stash swept up binary bytecode that could not pop cleanly, and implementation work was lost outright. Those files were untracked in #1005. Verified 2026-08-22 with 473 `.pyc` on disk: a one-line edit stashed to 341 bytes carrying one file, and popped clean.

What still bites: a plain `git stash pop` restores everything as unstaged, so a carefully staged set comes back flattened. Use `git stash pop --index` when the staged/unstaged split matters.

## Code review before pushing ranking changes
Always run a code review (e.g., /review-code or /peer-review) before pushing code that triggers production ranking workflows. A 5-minute review is always cheaper than a failed ranking run — the weekly run takes 2.5-3.7 hours (four runs, Aug 2026). This has been learned the hard way.

`git-guard.sh` enforces this rather than trusting it to be remembered. A push whose
diff against `origin/main` touches `src/rankings/`, `src/etl/glicko_*`,
`src/etl/v53e.py`, `src/utils/merge_resolver.py`, `scripts/calculate_rankings.py` or
`calculate-rankings.yml` is refused until it runs as `RANKING_REVIEWED=1 git push ...`.
Review first, then set it.

Two read-only reviewer agents in `.claude/agents/` support pre-push review:
- `ranking-change-reviewer` — ranking-engine diffs (scope list in its frontmatter).
- `migration-reviewer` — changed `supabase/migrations/*.sql`.
