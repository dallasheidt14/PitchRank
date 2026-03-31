# Git Workflow Safety

## Verify branch before every commit
Always run `git branch --show-current` before `git commit`. The sandbox resets CWD between Bash calls, which can silently switch back to main. Commits have landed on main instead of feature branches because of this.

## Never git stash
Use branches instead. `git stash pop` fails on .pyc binary conflicts and the stash cannot be cleanly recovered. This has caused complete loss of implementation work. When you need to compare against main, use `git diff` or a worktree.

## Code review before pushing ranking changes
Always run a code review (e.g., /review-code or /peer-review) before pushing code that triggers production ranking workflows. A 5-minute review is always cheaper than a failed 60-minute ranking run. This has been learned the hard way.
