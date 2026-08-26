#!/usr/bin/env bash
# A file already on origin/main warns only when the edit adds a write it did not
# have, so legacy scripts do not re-warn on every unrelated change while a newly
# introduced write still gets caught. Advisory: anything unresolvable stays silent.
rel=$1; root=$2
case "$rel" in
  scripts/*.py|src/*.py) ;;
  *) exit 0 ;;
esac
cd "$root" || exit 0
[ -f "$rel" ] || exit 0

# Whitespace is squashed so `.table("x")` and `.update(` on adjacent lines match.
WRITES='table\([^)]*\) *\.(insert|update|upsert|delete)\(|\.rpc\('
# Counted, not just detected: the squash puts everything on one line, so `grep -c`
# would say 1 and a file that already wrote could never trip on adding another.
count_writes() { tr -s '[:space:]' ' ' | grep -oE "$WRITES" | wc -l | tr -d '[:space:]'; }

now=$(count_writes <"$rel")
[ "${now:-0}" -gt 0 ] || exit 0
grep -qE 'dry[_-]run' "$rel" && exit 0

git rev-parse --verify -q 'origin/main^{commit}' >/dev/null || exit 0
listed=$(git ls-tree origin/main -- "$rel" 2>/dev/null) || exit 0
if [ -n "$listed" ]; then
  was=$(git show "origin/main:$rel" 2>/dev/null | count_writes)
  [ "${now:-0}" -gt "${was:-0}" ] || exit 0
fi
printf '%s' "$rel writes to Supabase but has no --dry-run/dry_run guard. CLAUDE.md requires one on every data-mutating script or method."
exit 0
