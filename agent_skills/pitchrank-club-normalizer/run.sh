#!/usr/bin/env bash
set -euo pipefail

AGE="${1:-}"
GENDER="${2:-}"
STATE="${3:-}"

if [[ -z "$AGE" || -z "$GENDER" || -z "$STATE" ]]; then
  echo "Usage: run.sh u15 Male PA"
  exit 2
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

OUTDIR="exports"
mkdir -p "$OUTDIR"

RAW="${OUTDIR}/${AGE}_${GENDER}_${STATE}.csv"
NORM="${OUTDIR}/${AGE}_${GENDER}_${STATE}__clubs_normalized.csv"
REVIEW="${OUTDIR}/${AGE}_${GENDER}_${STATE}__review_queue.csv"

echo "Exporting teams -> $RAW"
python scripts/view_teams.py -a "$AGE" -g "$GENDER" -s "$STATE" --export "$RAW"

echo "Normalizing clubs -> $NORM"
python agent_skills/pitchrank-club-normalizer/run.py --input "$RAW" --output "$NORM"

echo "Building review queue -> $REVIEW"
python agent_skills/pitchrank-club-normalizer/review_queue.py --input "$NORM" --output "$REVIEW"

echo "Done."
echo "RAW:    $RAW"
echo "NORMAL: $NORM"
echo "REVIEW: $REVIEW"
