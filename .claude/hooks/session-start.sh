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
  # --branch main because the workflow also takes a manual dispatch, and an
  # experiment run from a feature branch is not production health either way it
  # lands: green it hides a stalled weekly run, red it invents an outage.
  gh run list --workflow=calculate-rankings.yml --branch main --limit 1 \
    --json conclusion,status,createdAt \
    -q '.[0] | "\(.createdAt[0:10]) \(if (.conclusion // "") == "" then .status else .conclusion end)"' \
    >"$tmp/rank" 2>/dev/null &
  # One query per scheduled workflow rather than a window over recent runs. Any
  # shared window is measured in runs, so a single 15-minute job failing in a
  # loop fills it and hides everything else. Reading the workflow files means a
  # new schedule is covered without editing this.
  mkdir -p "$tmp/sched"
  for wf in $(grep -lE '^[[:space:]]*schedule:' "$root"/.github/workflows/*.yml 2>/dev/null); do
    name=${wf##*/}
    gh run list --workflow "$name" --event schedule --limit 1 --json conclusion,name \
      -q '.[0] | select(.conclusion == "failure") | .name' >"$tmp/sched/$name" 2>/dev/null &
  done
  wait
fi
read_tmp() { [ -n "$tmp" ] && cat "$tmp/$1" 2>/dev/null; }
prs=$(read_tmp prs)
ci=$(read_tmp ci)
rank=$(read_tmp rank)
sched=""
for f in "$tmp"/sched/*; do
  [ -s "$f" ] || continue
  sched="$sched, $(cat "$f")"
done
sched=${sched#, }
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
