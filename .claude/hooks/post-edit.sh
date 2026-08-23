#!/usr/bin/env bash
# PostToolUse(Edit|Write|MultiEdit). dry-run-check must see the file ruff
# leaves behind, and Claude Code runs sibling hook entries in parallel, so both
# run from here in order. Advisory: anything unresolvable stays silent.
here=$(dirname "$0")
. "$here/_lib.sh" || exit 0
command -v jq >/dev/null || exit 0
input=$(cat)
path=$(printf '%s' "$input" | jq -r '.tool_input.file_path // ""') || exit 0
root=$(hook_root "$(printf '%s' "$input" | jq -r '.cwd // ""')") || exit 0
rel=$(hook_relative_path "$path" "$root") || exit 0
notes=$(bash "$here/ruff-fix.sh" "$rel" "$root"; echo; bash "$here/dry-run-check.sh" "$rel" "$root")
notes=$(printf '%s' "$notes" | sed '/^$/d')
[ -n "$notes" ] || exit 0
jq -n --arg ctx "$notes" '{hookSpecificOutput: {hookEventName: "PostToolUse", additionalContext: $ctx}}'
exit 0
