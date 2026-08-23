#!/usr/bin/env bash
# PreToolUse(Edit|Write|MultiEdit): refuse secrets and npm lockfiles; ask before
# editing a migration that already exists on origin/main. A guard that cannot
# load its inputs fails closed.
. "$(dirname "$0")/_lib.sh" || { echo "BLOCKED: protect-paths cannot load _lib.sh." >&2; exit 2; }
command -v jq >/dev/null || { echo "BLOCKED: protect-paths needs jq on PATH (https://jqlang.github.io/jq/). Install it or remove the hook from .claude/settings.json." >&2; exit 2; }
input=$(cat)
path=$(printf '%s' "$input" | jq -r '.tool_input.file_path // ""') || { echo "BLOCKED: protect-paths could not parse the hook payload." >&2; exit 2; }
deny() { echo "$1" >&2; exit 2; }
ask() {
  jq -n --arg reason "$1" \
    '{hookSpecificOutput: {hookEventName: "PreToolUse", permissionDecision: "ask", permissionDecisionReason: $reason}}'
  exit 0
}

# Win32 resolves `.ENV`, `.env `, `.env.` and `.env::$DATA` to `.env`.
base=$(basename "${path//\\//}" | tr 'A-Z' 'a-z' | sed -E 's/:.*$//; s/[. ]+$//')
case "$base" in
  .env.example) exit 0 ;;
  .env|.env.*) deny "BLOCKED: $path holds secrets and is never committed. Edit .env.example instead (CLAUDE.md: never commit .env)." ;;
  package-lock.json|pnpm-lock.yaml|yarn.lock) deny "BLOCKED: $path is generated. Regenerate it with npm instead of editing (CLAUDE.md: keep the working tree clean)." ;;
esac

root=$(hook_root "$(printf '%s' "$input" | jq -r '.cwd // ""')") || exit 0
rel=$(hook_relative_path "$path" "$root") || exit 0
case "$rel" in
  supabase/migrations/*.sql)
    cd "$root" || exit 0
    git rev-parse --verify -q 'origin/main^{commit}' >/dev/null \
      || ask "origin/main is not available, so it is unknown whether $rel is already applied. Fetch first, or add a new timestamped migration."
    listed=$(git ls-tree origin/main -- "$rel" 2>/dev/null) \
      || ask "origin/main could not be read, so it is unknown whether $rel is already applied."
    if [ -n "$listed" ]; then
      ask "$rel already exists on origin/main and is likely applied; editing it will not re-run. Add a new timestamped migration unless this is a pre-apply fix."
    fi ;;
esac
exit 0
