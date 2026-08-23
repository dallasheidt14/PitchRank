#!/usr/bin/env bash
# ruff check --fix on one file (same scope as .pre-commit-config.yaml).
# Advisory: a missing tool stays silent.
. "$(dirname "$0")/_lib.sh" || exit 0
rel=$1; root=$2
case "$rel" in
  src/*.py|scripts/*.py|config/*.py|dashboard.py|tournament_intake.py) ;;
  *) exit 0 ;;
esac
cd "$root" || exit 0
[ -f "$rel" ] || exit 0
# -P keeps the repo root off sys.path so a stray ruff.py cannot shadow the tool.
out=$(python -P -m ruff check --fix "$rel" 2>&1); rc=$?
case "$out" in *"No module named"*|*"command not found"*|*"not recognized"*) exit 0 ;; esac
[ $rc -le 1 ] || exit 0
if printf '%s' "$out" | grep -qE '[0-9]+ fixed'; then
  printf '%s' "ruff check --fix rewrote $rel on disk; re-read it before further edits. $out"
elif [ $rc -eq 1 ]; then
  printf '%s' "ruff check reports unresolved issues in $rel (file unchanged): $out"
fi
exit 0
