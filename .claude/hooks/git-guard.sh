#!/usr/bin/env bash
# PreToolUse(Bash): block commits/pushes on main, blanket staging, force pushes,
# hard resets, junctioned worktree removal, main-checkout ignored-file cleanup,
# and whole-file ruff format. A typo-catcher over shell text, not a security
# boundary. No `set -e`: exit codes are the hook contract.
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
    # `\"` inside a double-quoted argument does not end it. Stopping there split
    # `bash -c "git commit -m \"x\"; git push --force"` so the force push landed
    # in a second segment and was neutralised as prose.
    while (match($0, /("([^"\\]|\\.)*"|'"'"'[^'"'"']*'"'"')/)) {
      before = substr($0, 1, RSTART - 1)
      seg = substr($0, RSTART + 1, RLENGTH - 2)
      # ...except after a shell wrapper flag, where the quoted argument is itself
      # a command. The flag becomes a `;` so the verb inside lands at a command
      # position and every rule below reads it. Without this,
      # `powershell -Command "git push --force"` passed straight through.
      # The wrapper name has to be there: on a bare `-c`, `rg -c "git add -A"`
      # would read its own search pattern as a command and refuse it.
      if (before ~ /(^|[ \t;&|(`])(powershell|pwsh|bash|sh|zsh|cmd)(\.exe)?([ \t]+(-[A-Za-z]+|--[A-Za-z][A-Za-z-]*(=[^ \t]*)?))*[ \t]+(-c|-lc|-command|-Command|-EncodedCommand|\/c|\/k)[ \t]+$/)
        sub(/[ \t]+(-c|-lc|-command|-Command|-EncodedCommand|\/c|\/k)[ \t]+$/, " ; ", before)
      else {
        gsub(/\\/, "\002", seg)
        # Keep an empty quoted argument as a token and keep backticks distinct
        # from harmless quoted whitespace. Both facts matter to destructive
        # Git command inspection below.
        if (seg == "") seg = "\003"
        gsub(/`/, "\004", seg)
        gsub(/[ \t;&|()]/, "\001", seg)
      }
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
wrapper='(env|exec|xargs|sudo|nice|time|command|builtin|then|do|else)'
assign='([A-Za-z_][A-Za-z0-9_]*=[^[:space:]]*[[:space:]]+)*'
at_cmd="((^|[;&|(\`{${nl}])[[:space:]]*${assign}|(^|[[:space:]])${wrapper}[[:space:]]+${assign})"
end='([[:space:];&|)]|$)'
end_or_eq='([[:space:];&|)=]|$)'
git_bin='git([.]exe)?'
git_value='[^[:space:];&|()]+'
# Git-wide short options either take the next/attached value or are one-letter
# switches. Long options are switches or use =value; work-tree and git-dir also
# accept a separate value. Keeping the grammar generic makes new long switches
# fail closed if they appear before a guarded verb.
git_opts="((-[Cc][[:space:]]+${git_value}|-C${git_value}|-c${git_value}|-[pPvVh]|--(work-tree|git-dir)[[:space:]]+${git_value}|--[a-z][a-z-]*(=${git_value})?)[[:space:]]+)*"
git_cmd="${at_cmd}${git_bin}[[:space:]]+${git_opts}"
push_args="${git_cmd}push([[:space:]]+[^[:space:];&|()]+)*[[:space:]]+"

branch_of() { [ -d "$1" ] && git -C "$1" branch --show-current 2>/dev/null; }

shell_path() {
  local path=${1//$'\001'/ }
  path=${path//$'\002'/$'\\'}
  path=${path//$'\003'/}
  path=${path//$'\004'/$'\x60'}
  if [[ $path =~ ^[A-Za-z]:[\\/] ]] && command -v cygpath >/dev/null 2>&1; then
    cygpath -u "$path"
  else
    printf '%s\n' "$path"
  fi
}

has_shell_path_syntax() {
  local path=$1
  [[ $path == *'$'* || $path == *'`'* || $path == '~'* || $path == *'*'* || $path == *'?'* ||
    $path == *'['* || $path == *'<'* || $path == *'>'* || $path == *'%'* ]]
}

execution_dir_for_segment() {
  local segment=$1 target=$2 honor_work_tree=$3
  local i token value work_tree= seen_git=false
  local -a tokens
  read -r -a tokens <<< "$segment"
  for ((i = 0; i < ${#tokens[@]}; i++)); do
    token=${tokens[i]//$'\001'/ }
    if ! $seen_git; then
      { [ "$token" = git ] || [ "$token" = git.exe ]; } && seen_git=true
      continue
    fi
    case "$token" in
      -C)
        ((i++))
        value=$(shell_path "${tokens[i]:-}")
        [ -n "$value" ] || continue
        case "$value" in /*|[A-Za-z]:*) ;; *) value="$target/$value" ;; esac
        target=$value
        ;;
      -C?*)
        value=$(shell_path "${token#-C}")
        case "$value" in /*|[A-Za-z]:*) ;; *) value="$target/$value" ;; esac
        target=$value
        ;;
      -c) ((i++)) ;;
      --work-tree)
        ((i++))
        work_tree=$(shell_path "${tokens[i]:-}")
        ;;
      --work-tree=*)
        work_tree=$(shell_path "${token#--work-tree=}")
        ;;
      clean|worktree) break ;;
    esac
  done
  if $honor_work_tree && [ -n "$work_tree" ]; then
    case "$work_tree" in /*|[A-Za-z]:*) ;; *) work_tree="$target/$work_tree" ;; esac
    printf '%s\n' "$work_tree"
  else
    printf '%s\n' "$target"
  fi
}

is_reparse_point() {
  local path=$1 native fsutil_cmd
  [ -L "$path" ] && return 0
  fsutil_cmd=$(command -v fsutil.exe 2>/dev/null || command -v fsutil 2>/dev/null)
  [ -n "$fsutil_cmd" ] || return 1
  native=$path
  command -v cygpath >/dev/null 2>&1 && native=$(cygpath -w "$path")
  "$fsutil_cmd" reparsepoint query "$native" >/dev/null 2>&1
}

guard_cwd=$(printf '%s' "$input" | jq -r '.cwd // ""')
guard_cwd=$(shell_path "$guard_cwd")
[ -d "$guard_cwd" ] || guard_cwd=$(shell_path "$CLAUDE_PROJECT_DIR")
cd_re="${at_cmd}cd[[:space:]]+([^[:space:];&|)]+)"
worktree_remove_re="${git_cmd}worktree[[:space:]]+remove[[:space:]]+([^;&|()]*)"
clean_re="${git_cmd}clean[[:space:]]+([^;&|()]*)"
env_scan=${stripped//$'\001'/ }
env_guarded_re="${at_cmd}env[[:space:]]+([^;&|()]*)${git_bin}[[:space:]]+${git_opts}(clean|worktree[[:space:]]+remove)${end}"
if [[ $env_scan =~ $env_guarded_re ]]; then
  deny "BLOCKED: guarded git clean and git worktree remove commands cannot be wrapped in env options. Run Git directly with literal paths."
fi
command_guarded_re="${at_cmd}(builtin[[:space:]]+)?command([[:space:]]+-[^[:space:];&|()]*)+[[:space:]]+${assign}${git_bin}[[:space:]]+${git_opts}(clean|worktree[[:space:]]+remove)${end}"
if [[ $env_scan =~ $command_guarded_re ]]; then
  deny "BLOCKED: guarded git clean and git worktree remove commands cannot be wrapped in command options. Run Git directly with literal paths."
fi
execution_wrapper_guarded_re="${at_cmd}(exec|xargs|sudo|nice|time)[[:space:]]+([^;&|()]*[[:space:]]+)?${git_bin}[[:space:]]+${git_opts}(clean|worktree[[:space:]]+remove)${end}"
if [[ $env_scan =~ $execution_wrapper_guarded_re ]]; then
  deny "BLOCKED: guarded git clean and git worktree remove commands cannot use an execution wrapper. Run Git directly with literal paths."
fi
if [[ $stripped == *\\* ]] &&
  { [[ $stripped == *git*clean* ]] || [[ $stripped == *git*worktree*remove* ]]; }; then
  deny "BLOCKED: guarded Git commands require quoted literal paths; backslash-escaped paths cannot be inspected safely."
fi

# Shell control flow decides whether `cd` runs and whether it persists. Rather
# than imitate a shell parser around a destructive clean, require the equivalent
# unambiguous `git -C <path> clean ...` form whenever a command also contains cd.
has_cd=false
[[ $stripped =~ ${at_cmd}cd${end} ]] && has_cd=true
has_git_context_override=false
if [[ $stripped =~ (^|[[:space:];&|])GIT_[A-Za-z0-9_]*= ]] || [[ $stripped =~ ${git_bin}[[:space:]].*(--git-dir|-c[[:space:]]|--config-env) ]]; then
  has_git_context_override=true
fi

while IFS= read -r segment; do
  [ -n "$segment" ] || continue
  if [[ $segment =~ $cd_re ]]; then
    next_cwd=$(shell_path "${BASH_REMATCH[${#BASH_REMATCH[@]}-1]}")
    case "$next_cwd" in /*|[A-Za-z]:*) ;; *) next_cwd="$guard_cwd/$next_cwd" ;; esac
    guard_cwd=$next_cwd
  fi

  if [[ $segment =~ $worktree_remove_re ]]; then
    remove_args=${BASH_REMATCH[${#BASH_REMATCH[@]}-1]}
    if [[ $segment == *\\* ]]; then
      deny "BLOCKED: git worktree remove requires quoted literal paths; backslash-escaped paths cannot be inspected safely."
    fi
    remove_target=
    for arg in $remove_args; do
      case "$arg" in --|-*) ;; *) remove_target=$(shell_path "$arg"); break ;; esac
    done
    if [ -n "$remove_target" ]; then
      if has_shell_path_syntax "$remove_target"; then
        deny "BLOCKED: git worktree remove requires a literal target path so frontend/node_modules can be inspected before removal."
      fi
      case "$remove_target" in
        /*|[A-Za-z]:*) ;;
        *)
          if $has_cd; then
            deny "BLOCKED: a relative git worktree remove target cannot be combined with cd. Run it separately, use an absolute target, or use git -C <path>."
          fi
          ;;
      esac
      remove_base=$(execution_dir_for_segment "$segment" "$guard_cwd" false)
      if has_shell_path_syntax "$remove_base"; then
        deny "BLOCKED: git worktree remove requires a literal git -C path so frontend/node_modules can be inspected before removal."
      fi
      remove_arg=$remove_target
      case "$remove_target" in
        /*|[A-Za-z]:*) requested_target=$(realpath -m "$remove_target") ;;
        *) requested_target=$(realpath -m "$remove_base/$remove_target") ;;
      esac
      registry_exact=
      registry_shorthand=
      registry_shorthand_count=0
      while IFS= read -r registry_line; do
        [[ $registry_line == worktree\ * ]] || continue
        registry_target=$(shell_path "${registry_line#worktree }")
        registry_target=$(realpath -m "$registry_target")
        if [ "$registry_target" = "$requested_target" ]; then
          registry_exact=$registry_target
          break
        fi
        if [[ $remove_arg != */* && $remove_arg != *\\* ]] &&
          [ "$(basename "$registry_target")" = "$remove_arg" ]; then
          registry_shorthand=$registry_target
          ((registry_shorthand_count++))
        fi
      done < <(git -C "$remove_base" worktree list --porcelain 2>/dev/null)
      if [ -n "$registry_exact" ]; then
        remove_target=$registry_exact
      elif [ "$registry_shorthand_count" -eq 1 ]; then
        remove_target=$registry_shorthand
      elif [ "$registry_shorthand_count" -gt 1 ]; then
        deny "BLOCKED: git worktree remove target is an ambiguous registered worktree name. Use its literal absolute path."
      else
        remove_target=$requested_target
      fi
      modules="$remove_target/frontend/node_modules"
      if is_reparse_point "$modules"; then
        case "$(uname -s)" in
          MINGW*|MSYS*|CYGWIN*) unlink_hint='cmd /c rmdir "frontend\node_modules"' ;;
          *) unlink_hint="unlink frontend/node_modules" ;;
        esac
        deny "BLOCKED: $modules is a junction or symlink. Run '$unlink_hint' inside that worktree first, then retry git worktree remove."
      fi
    fi
  fi

  if [[ $segment =~ $clean_re ]]; then
    clean_args=${BASH_REMATCH[${#BASH_REMATCH[@]}-1]}
    if has_shell_path_syntax "$(shell_path "$clean_args")"; then
      deny "BLOCKED: git clean requires literal arguments so ignored-file flags and paths can be inspected safely."
    fi
    cleans_ignored=false
    for arg in $clean_args; do
      case "$arg" in
        --*) ;;
        -*) [[ ${arg#-} == *x* || ${arg#-} == *X* ]] && cleans_ignored=true ;;
      esac
    done
    if $cleans_ignored; then
      if [[ $segment == *\\* ]]; then
        deny "BLOCKED: git clean -x/-X requires quoted literal paths; backslash-escaped paths cannot be inspected safely."
      fi
      if $has_cd; then
        deny "BLOCKED: git clean -x/-X cannot be combined with cd because shell control flow can hide the checkout. Run it separately or use git -C <path> clean."
      fi
      if $has_git_context_override || [ -n "${GIT_WORK_TREE:-}" ] || [ -n "${GIT_DIR:-}" ]; then
        deny "BLOCKED: git clean -x/-X cannot use Git environment, git-dir, or config overrides because they can hide the cleaned tree. Use git -C and --work-tree explicitly."
      fi
      clean_cwd=$(execution_dir_for_segment "$segment" "$guard_cwd" true)
      if has_shell_path_syntax "$clean_cwd"; then
        deny "BLOCKED: git clean -x/-X requires literal -C and --work-tree paths so the cleaned tree can be verified."
      fi
      clean_root=$(git -C "$clean_cwd" rev-parse --show-toplevel 2>/dev/null)
      clean_root=$(shell_path "$clean_root")
      if [ -z "$clean_root" ]; then
        deny "BLOCKED: git clean -x/-X target could not be resolved to a repository."
      fi
      if [ -n "$clean_root" ] && [ -d "$clean_root/.git" ]; then
        deny "BLOCKED: git clean -x/-X in the primary checkout can erase ignored worktrees, dependencies, and scratch files. Run it only in a disposable linked worktree."
      fi
    fi
  fi
done < <(printf '%s\n' "$stripped" | awk '{ gsub(/[;&|()`{}]/, "\n"); print }')

if [[ $stripped =~ ${git_cmd}(commit|push)${end} ]]; then
  cwd=$(printf '%s' "$input" | jq -r '.cwd // ""')
  [ -d "$cwd" ] || cwd=$CLAUDE_PROJECT_DIR
  # Where git will actually run: `git -C <dir>` wins, else a `cd` earlier in the
  # command, else the payload's cwd. Every check below that reads repository state
  # answers about the wrong repository otherwise.
  cd_re="${at_cmd}cd[[:space:]]+([^[:space:];&|)]+)"
  target=$cwd
  # The -C has to belong to the guarded verb: in `git -C /elsewhere status && git
  # push`, the first -C names a repository this push never touches.
  target_re="${git_bin}[[:space:]]+-C[[:space:]]+([^[:space:]]+)[[:space:]]+(-c[[:space:]]+[^[:space:]]+[[:space:]]+)*(commit|push)${end}"
  if [[ $stripped =~ $target_re ]]; then
    target=${BASH_REMATCH[2]//$'\001'/ }
  elif [[ $stripped =~ $cd_re ]]; then
    target=${BASH_REMATCH[${#BASH_REMATCH[@]}-1]//$'\001'/ }
    case "$target" in /*|[A-Za-z]:*) ;; *) target="$cwd/$target" ;; esac
  fi
  branch=$(branch_of "$cwd")
  if [[ $stripped =~ ${git_bin}[[:space:]]+-C[[:space:]]+([^[:space:]]+)[[:space:]]+(-c[[:space:]]+[^[:space:]]+[[:space:]]+)*(commit|push)${end} ]]; then
    branch=$(branch_of "${BASH_REMATCH[2]//$'\001'/ }")
  fi
  if [ "$branch" = main ]; then
    deny "BLOCKED: branch is main. Run 'git checkout -b <feature> origin/main' first (CLAUDE.md: never commit to main)."
  fi
  # Amending is fine until the commit is on a remote. After that the only way to
  # land it is a force push, which the guard below blocks, so the branch strands
  # with no way back.
  amend_re="${git_cmd}commit[[:space:]][^;&|()]*--amend${end}"
  if [[ $stripped =~ $amend_re ]]; then
    if [ -d "$target" ] && [ -n "$(git -C "$target" branch -r --contains HEAD 2>/dev/null)" ]; then
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
