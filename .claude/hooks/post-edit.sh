#!/usr/bin/env bash
# PostToolUse(Edit|Write|MultiEdit). Ordering is load-bearing: replace_all_check
# counts the file the edit itself produced, so it runs before ruff-fix can
# rewrite lines; dry-run-check must see the file ruff leaves behind, so it runs
# last. Claude Code runs sibling hook entries in parallel, so all three run from
# here in order. Advisory: anything unresolvable stays silent.
here=$(dirname "$0")
. "$here/_lib.sh" || exit 0
command -v jq >/dev/null || exit 0
input=$(cat)
path=$(printf '%s' "$input" | jq -r '.tool_input.file_path // ""') || exit 0
root=$(hook_root "$(printf '%s' "$input" | jq -r '.cwd // ""')") || exit 0
rel=$(hook_relative_path "$path" "$root") || exit 0
ra_note=""
if [ "$(printf '%s' "$input" | jq -r '.tool_input.replace_all // false')" = "true" ]; then
  # The raw payload goes to Python as bytes: shell capture strips trailing
  # newlines from new_string and Windows jq CRLFs embedded ones.
  ra_note=$(printf '%s' "$input" | python -P "$here/replace_all_check.py" "$rel" "$root" 2>/dev/null)
fi
notes=$(printf '%s' "$ra_note"; echo; bash "$here/ruff-fix.sh" "$rel" "$root"; echo; bash "$here/dry-run-check.sh" "$rel" "$root")
notes=$(printf '%s' "$notes" | sed '/^$/d')
[ -n "$notes" ] || exit 0
jq -n --arg ctx "$notes" '{hookSpecificOutput: {hookEventName: "PostToolUse", additionalContext: $ctx}}'
exit 0
