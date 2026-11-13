"""Register a reviewed, qualified form candidate; preview by default. Never deploys a model."""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.settle_prospective_match_predictions import _supabase_client  # noqa: E402
from src.predictions.challenger_capture import register_candidate  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("qualification_report", type=Path)
    parser.add_argument("--reviewed", action="store_true",
                        help="The qualifying report has had a separate release review")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    report = json.loads(args.qualification_report.read_text(encoding="utf-8"))
    result = register_candidate(_supabase_client(), report, reviewed=args.reviewed, dry_run=not args.execute)
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
