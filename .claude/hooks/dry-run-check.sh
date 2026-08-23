#!/usr/bin/env bash
# Files already on origin/main are left alone so legacy scripts do not re-warn
# on every edit. Advisory: anything unresolvable stays silent.
rel=$1; root=$2
case "$rel" in
  scripts/*.py|src/*.py) ;;
  *) exit 0 ;;
esac
cd "$root" || exit 0
[ -f "$rel" ] || exit 0
git rev-parse --verify -q 'origin/main^{commit}' >/dev/null || exit 0
listed=$(git ls-tree origin/main -- "$rel" 2>/dev/null) || exit 0
[ -z "$listed" ] || exit 0
# Whitespace is squashed so `.table("x")` and `.update(` on adjacent lines match.
if tr -s '[:space:]' ' ' <"$rel" | grep -qE 'table\([^)]*\) *\.(insert|update|upsert|delete)\(|\.rpc\(' \
  && ! grep -qE 'dry[_-]run' "$rel"; then
  printf '%s' "$rel writes to Supabase but has no --dry-run/dry_run guard. CLAUDE.md requires one on every data-mutating script or method."
fi
exit 0
