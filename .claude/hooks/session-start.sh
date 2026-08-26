#!/usr/bin/env bash
# SessionStart(startup|resume|clear|compact|fork): sync the active checkout and
# print repo state plus the current cohort mapping. stdout is injected into the
# session.
#
# This runs before every conversation, so a line that is always the same is a
# tax on all of them. Standing state gets one line; anything that wants a
# decision gets its own ATTENTION line and is otherwise silent.
here=$(dirname "$0")
. "$here/_lib.sh" || exit 0
cwd=$(jq -r '.cwd // ""' 2>/dev/null)
root=$(hook_root "$cwd") || exit 0
cd "$root" || exit 0
sync_note=""
git fetch --all --prune --quiet 2>/dev/null || sync_note="; fetch FAILED (offline?), counts may be stale"

# The gh queries do not depend on each other and cost about a second each, so
# they run together rather than in series.
tmp=$(mktemp -d 2>/dev/null)
if [ -n "$tmp" ]; then
  gh pr list --state open --limit 100 --json number -q length >"$tmp/prs" 2>/dev/null &
  # A run still going has no conclusion, so fall back to its status rather than
  # printing a blank. `//` will not do it: gh returns "" there, not null, and jq
  # only falls back on null.
  gh run list --workflow=ci.yml --branch main --limit 1 --json conclusion,status \
    -q '.[0] | if (.conclusion // "") == "" then .status else .conclusion end' >"$tmp/ci" 2>/dev/null &
  gh run list --workflow=calculate-rankings.yml --limit 1 --json conclusion,status,createdAt \
    -q '.[0] | "\(.createdAt[0:10]) \(if (.conclusion // "") == "" then .status else .conclusion end)"' \
    >"$tmp/rank" 2>/dev/null &
  # Filtered to failures on purpose. A plain recent-runs window is dominated by
  # the two every-15-minute schedules, which spend 60 entries in about seven
  # hours and push a weekly job's failure out of sight; 30 scheduled *failures*
  # reaches back months instead.
  gh run list --event schedule --status failure --created ">=$(date -d '7 days ago' +%F)" \
    --limit 30 --json name -q '[.[].name] | unique | .[]' >"$tmp/sched" 2>/dev/null &
  wait
fi
read_tmp() { [ -n "$tmp" ] && cat "$tmp/$1" 2>/dev/null; }
prs=$(read_tmp prs)
ci=$(read_tmp ci)
rank=$(read_tmp rank)
sched=$(read_tmp sched)
[ -n "$tmp" ] && rm -rf "$tmp"

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

# A worktree holding uncommitted work cannot be removed without losing it, and
# that is exactly when someone reaches for `git worktree remove`.
unclean=""
while IFS= read -r wt; do
  [ -d "$wt" ] || continue
  # Untracked counts here, unlike the tracked-drift count above: a scratch file
  # nobody committed is the one that exists in no other copy.
  [ "$(git -C "$wt" status --porcelain 2>/dev/null | wc -l)" -gt 0 ] && unclean="$unclean ${wt##*/}"
done < <(git worktree list --porcelain | awk '/^worktree /{print substr($0, 10)}' | tail -n +2)

backlog=$(grep -c '^- \*\*Status\*\*: open' .turbo/improvements.md 2>/dev/null)
handoff=$(ls -t .turbo/handoff/*.md 2>/dev/null | head -1)
cohort=$(CLAUDE_PROJECT_DIR=$root python "$here/cohort_line.py" 2>/dev/null)

# The weekly run is every Monday, so a gap past eight days means it stopped.
rank_note=""
if [ -n "$rank" ]; then
  read -r rank_day rank_state <<<"$rank"
  age=$(( ( $(date +%s) - $(date -d "$rank_day" +%s 2>/dev/null || echo 0) ) / 86400 ))
  case "$rank_state" in
    success) [ "$age" -gt 8 ] && rank_note="no rankings run in $age days (weekly job stalled?)" ;;
    # A run takes 2.5-3.7 hours, so in_progress is the healthy state for most of
    # a Monday and must never read as a failure.
    in_progress | queued | requested | waiting | "") ;;
    *) rank_note="last rankings run $rank_day $rank_state" ;;
  esac
fi

# A workflow that failed and then recovered is not worth a line, so its latest
# scheduled run decides. Costs nothing on the usual day, when nothing failed.
still_failing=""
while IFS= read -r wf; do
  [ -n "$wf" ] || continue
  latest=$(gh run list --workflow "$wf" --event schedule --limit 1 --json conclusion \
    -q '.[0].conclusion' 2>/dev/null)
  [ "$latest" = failure ] && still_failing="$still_failing, $wf"
done <<<"$sched"
sched=${still_failing#, }

echo "## Repo state $(date +%F)"
echo "- checkout $root on $branch: behind origin/main ${behind:-?}, ahead ${ahead:-?}$ff; dirty tracked files $dirty$sync_note"
echo "- local branches whose remote is gone: $gone; linked worktrees: $worktrees; open PRs: ${prs:-?}"
echo "- rankings ${rank:-?}; CI on main ${ci:-?}; backlog ${backlog:-?} open"
[ -n "$handoff" ] && echo "- latest handoff: $handoff"
[ -n "$cohort" ] && echo "- $cohort"
case "$ci" in success | in_progress | queued | "") ;; *) echo "- ATTENTION: CI on main is $ci" ;; esac
[ -n "$rank_note" ] && echo "- ATTENTION: $rank_note"
[ -n "$sched" ] && echo "- ATTENTION: scheduled workflows failing: $sched"
[ -n "$unclean" ] && echo "- ATTENTION: worktrees with uncommitted work:$unclean"
exit 0
