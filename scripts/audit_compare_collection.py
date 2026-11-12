"""Print an outcome-blind coverage audit; --execute saves an aggregate local report only."""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.settle_prospective_match_predictions import _supabase_client  # noqa: E402
from src.predictions.collection_coverage import collection_coverage  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--execute", action="store_true", help="Save a new local aggregate report; no database writes")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.execute and args.output is None:
        parser.error("--execute requires --output")
    report = collection_coverage(_supabase_client(), limit=args.limit)
    if args.execute:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2, allow_nan=False)
    print(json.dumps(report, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
