"""Capture the registered winner candidates on future current-Compare fixtures; preview by default."""

import argparse
import json
import logging
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT))

from scripts.settle_prospective_match_predictions import _supabase_client  # noqa: E402
from src.predictions.winner_study import capture_winners  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("study_signature")
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if not re.fullmatch(r"[a-f0-9]{64}", args.study_signature) or not 1 <= args.limit <= 500:
        parser.error("Use a registered SHA256 signature and limit between 1 and 500")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    summary = capture_winners(_supabase_client(), args.study_signature, ROOT,
                             dry_run=not args.execute, limit=args.limit)
    print(json.dumps(summary, indent=2, allow_nan=False))
    if summary["errors"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
