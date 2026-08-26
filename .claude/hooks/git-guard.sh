#!/usr/bin/env bash
# PreToolUse(Bash): block commits/pushes on main, blanket staging, force pushes,
# hard resets, and whole-file ruff format. A typo-catcher over shell text, not
# a security boundary. No `set -e`: exit codes are the hook contract.
command -v jq >/dev/null || { echo "BLOCKED: git-guard needs jq on PATH (https://jqlang.github.io/jq/). Install it or remove the hook from .claude/settings.json." >&2; exit 2; }
input=$(cat)
cmd=$(printf '%s' "$input" | jq -r '.tool_input.command // ""') || { echo "BLOCKED: git-guard could not parse the hook payload." >&2; exit 2; }
case "$cmd" in *git*|*ruff*) ;; *) exit 0 ;; esac

deny() { echo "$1" >&2; exit 2; }

stripped=$(printf '%s\n' "$cmd" | awk '
  # Join backslash-newline continuations so a verb and its flags share a line.
  /\\$/ { held = held substr($0, 1, length($0) - 1) " "; next }
  { $0 = held $0; held = "" }
  in_heredoc {
    line = $0
    if (dash) sub(/^[ \t]+/, "", line)
    if (line == tag) in_heredoc = 0
    next
  }
  {
    orig = $0
    # Inside quotes, separators and spaces become a control byte: prose cannot
    # look like a command, while `git add "."` and `git -C "a dir"` still parse.
    out = ""
    while (match($0, /("[^"]*"|'"'"'[^'"'"']*'"'"')/)) {
      before = substr($0, 1, RSTART - 1)
      seg = substr($0, RSTART + 1, RLENGTH - 2)
      # ...except after a shell wrapper flag, where the quoted argument is itself
      # a command. The flag becomes a `;` so the verb inside lands at a command
      # position and every rule below reads it. Without this,
      # `powershell -Command "git push --force"` passed straight through.
      if (before ~ /(^|[ \t])(-c|-lc|-command|-Command|-EncodedCommand|\/c|\/k)[ \t]+$/)
        sub(/(-c|-lc|-command|-Command|-EncodedCommand|\/c|\/k)[ \t]+$/, "; ", before)
      else
        gsub(/[ \t;&|()`]/, "\001", seg)
      out = out before seg
      $0 = substr($0, RSTART + RLENGTH)
    }
    $0 = out $0
    # `<<` (not `<<<`) plus a trailing tag opens a heredoc.
    if (match(orig, /(^|[^<])<<-?[ \t]*([A-Za-z_][A-Za-z0-9_]*|"[A-Za-z_][A-Za-z0-9_]*"|'"'"'[A-Za-z_][A-Za-z0-9_]*'"'"')[ \t]*$/)) {
      tag = substr(orig, RSTART, RLENGTH)
      dash = (tag ~ /<<-/)
      sub(/^.*<<-?[ \t]*/, "", tag); gsub(/["'"'"']/, "", tag); sub(/[ \t]+$/, "", tag)
      in_heredoc = 1
    }
    print
  }')

nl=$'\n'
# Guarded verbs only count at a command position.
wrapper='(env|exec|xargs|sudo|nice|time|then|do|else)'
assign='([A-Za-z_][A-Za-z0-9_]*=[^[:space:]]*[[:space:]]+)*'
at_cmd="((^|[;&|(\`{${nl}])[[:space:]]*${assign}|(^|[[:space:]])${wrapper}[[:space:]]+${assign})"
end='([[:space:];&|)]|$)'
end_or_eq='([[:space:];&|)=]|$)'
git_opts='((-[Cc][[:space:]]+[^[:space:]]+|--[a-z-]+(=[^[:space:]]+)?)[[:space:]]+)*'
git_cmd="${at_cmd}git[[:space:]]+${git_opts}"
push_args="${git_cmd}push([[:space:]]+[^[:space:];&|()]+)*[[:space:]]+"

branch_of() { [ -d "$1" ] && git -C "$1" branch --show-current 2>/dev/null; }

if [[ $stripped =~ ${git_cmd}(commit|push)${end} ]]; then
  cwd=$(printf '%s' "$input" | jq -r '.cwd // ""')
  [ -d "$cwd" ] || cwd=$CLAUDE_PROJECT_DIR
  branch=$(branch_of "$cwd")
  if [[ $stripped =~ git[[:space:]]+-C[[:space:]]+([^[:space:]]+)[[:space:]]+(-c[[:space:]]+[^[:space:]]+[[:space:]]+)*(commit|push)${end} ]]; then
    branch=$(branch_of "${BASH_REMATCH[1]//$'\001'/ }")
  fi
  if [ "$branch" = main ]; then
    deny "BLOCKED: branch is main. Run 'git checkout -b <feature> origin/main' first (CLAUDE.md: never commit to main)."
  fi
  # Amending is fine until the commit is on a remote. After that the only way to
  # land it is a force push, which the guard below blocks, so the branch strands
  # with no way back.
  amend_re="${git_cmd}commit[[:space:]][^;&|()]*--amend${end}"
  if [[ $stripped =~ $amend_re ]]; then
    amend_dir=$cwd
    if [[ $stripped =~ git[[:space:]]+-C[[:space:]]+([^[:space:]]+)[[:space:]] ]]; then
      amend_dir=${BASH_REMATCH[1]//$'\001'/ }
    fi
    if [ -d "$amend_dir" ] && [ -n "$(git -C "$amend_dir" branch -r --contains HEAD 2>/dev/null)" ]; then
      deny "BLOCKED: HEAD is already pushed, so amending it would need the force push this guard refuses. Add a new commit instead (.claude/rules/git-workflow.md)."
    fi
  fi
  # A `cd` earlier in the command moves where git runs, so check that checkout too.
  cd_re="${at_cmd}cd[[:space:]]+([^[:space:];&|)]+)"
  if [[ $stripped =~ $cd_re ]]; then
    cd_target=${BASH_REMATCH[${#BASH_REMATCH[@]}-1]//$'\001'/ }
    case "$cd_target" in /*|[A-Za-z]:*) ;; *) cd_target="$cwd/$cd_target" ;; esac
    if [ "$(branch_of "$cd_target")" = main ]; then
      deny "BLOCKED: this command changes into a checkout that is on main before committing or pushing (CLAUDE.md: never commit to main)."
    fi
  fi
  # .claude/rules/git-workflow.md requires a review before pushing anything that
  # reaches the weekly ranking run, and had no enforcement. A bad run costs
  # 2.5-3.7 hours, which is why this is a stop rather than a note.
  ranking_re='^(src/rankings/|src/etl/glicko_|src/etl/v53e\.py|src/utils/merge_resolver\.py|scripts/calculate_rankings\.py|\.github/workflows/calculate-rankings\.yml)'
  if [[ $stripped =~ ${git_cmd}push${end} ]] && [[ $cmd != *RANKING_REVIEWED=1* ]] && [ -d "$cwd" ]; then
    if git -C "$cwd" diff --name-only origin/main...HEAD 2>/dev/null | grep -qE "$ranking_re"; then
      deny "BLOCKED: this push changes the ranking engine, which .claude/rules/git-workflow.md says to review first. Run the ranking-change-reviewer agent, then re-run as 'RANKING_REVIEWED=1 git push ...'."
    fi
  fi
  if [[ $stripped =~ ${git_cmd}(checkout|switch)[[:space:]]+(-[^[:space:]]+[[:space:]]+)*main${end}(.*) ]] \
    && [[ ${BASH_REMATCH[${#BASH_REMATCH[@]}-1]} =~ ${git_cmd}(commit|push)${end} ]]; then
    deny "BLOCKED: this command switches to main before committing or pushing (CLAUDE.md: never commit to main)."
  fi
fi
if [[ $stripped =~ ${push_args}(\+?[^[:space:]]*:(refs/heads/)?main|main|(-d|--delete)[[:space:]]+(refs/heads/)?main)${end} ]]; then
  deny "BLOCKED: pushing to main directly. Open a PR instead (CLAUDE.md: never commit to main)."
fi
if [[ $stripped =~ ${git_cmd}add[[:space:]]+(--[[:space:]]+)?(-A|--all|-u|--update|\.|\./)${end} ]]; then
  deny "BLOCKED: git add -A/-u/. stages everything. Stage by path (CLAUDE.md: stage selectively)."
fi
if [[ $stripped =~ ${push_args}(-[A-Za-z]*f[A-Za-z]*|--force[a-z-]*|\+[^[:space:]]+)${end_or_eq} ]]; then
  deny "BLOCKED: force push rewrites shared history and main forbids it. Push a new commit instead (CLAUDE.md: never force-push)."
fi
if [[ $stripped =~ ${push_args}(--all|--branches|--mirror)${end} ]]; then
  deny "BLOCKED: git push --all/--mirror includes local main. Push the current branch explicitly."
fi
if [[ $stripped =~ ${git_cmd}reset[[:space:]]+(--hard|--merge)${end} ]]; then
  deny "BLOCKED: git reset --hard discards work. Use 'git stash' then 'git stash pop --index', or 'git checkout -- <path>' (.claude/rules/git-workflow.md)."
fi
while IFS= read -r segment; do
  [ -n "$segment" ] || continue
  [[ $segment == *--diff* || $segment == *--check* ]] \
    || deny "BLOCKED: ruff format rewrites unrelated lines. Use 'python -P -m ruff format --diff <file>' and hand-apply (CLAUDE.md: no whole-file ruff format)."
done <<<"$(printf '%s\n' "$stripped" | grep -oE '(^|[[:space:]/])ruff[[:space:]]+format[^;&|]*')"
exit 0
