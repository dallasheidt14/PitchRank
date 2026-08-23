#!/usr/bin/env bash
# SessionStart(startup|resume|clear|compact|fork): sync the active checkout and
# print repo state plus the current cohort mapping. stdout is injected into the
# session.
here=$(dirname "$0")
. "$here/_lib.sh" || exit 0
cwd=$(jq -r '.cwd // ""' 2>/dev/null)
root=$(hook_root "$cwd") || exit 0
cd "$root" || exit 0
sync_note=""
git fetch --all --prune --quiet 2>/dev/null || sync_note="; fetch FAILED (offline?), counts may be stale"
branch=$(git branch --show-current)
dirty=$(git status --porcelain -uno | wc -l | tr -d ' ')
counts() { git rev-list --left-right --count origin/main...HEAD 2>/dev/null; }
read -r behind ahead <<<"$(counts)"
ff=""
if [ "$branch" = main ] && [ "$dirty" -eq 0 ] && [ "${behind:-0}" -gt 0 ]; then
  if git merge --ff-only --quiet origin/main 2>/dev/null; then
    ff=" (fast-forwarded from $behind behind)"
    read -r behind ahead <<<"$(counts)"
  else
    ff=" (fast-forward FAILED)"
  fi
fi
gone=$(git branch -vv | grep -c ': gone\]')
worktrees=$(git worktree list | tail -n +2 | wc -l | tr -d ' ')
prs=$(gh pr list --state open --limit 100 --json number -q length 2>/dev/null)
cohort=$(CLAUDE_PROJECT_DIR=$root python "$here/cohort_line.py" 2>/dev/null)
echo "## Repo state $(date +%F)"
echo "- checkout $root on $branch: behind origin/main ${behind:-?}, ahead ${ahead:-?}$ff; dirty tracked files $dirty$sync_note"
echo "- local branches whose remote is gone: $gone; linked worktrees: $worktrees; open PRs: ${prs:-?}"
[ -n "$cohort" ] && echo "- $cohort"
exit 0
