"""Score frozen pre-event predictions; no database access or ranking writes."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.tournaments.seeding_validation import scorecard  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("records", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--baseline", default="baseline")
    parser.add_argument("--confirmation", action="store_true")
    args = parser.parse_args()
    result = scorecard(json.loads(args.records.read_text(encoding="utf-8")), baseline=args.baseline,
                       confirmation=args.confirmation)
    args.output.write_text(json.dumps(result, indent=2, allow_nan=False), encoding="utf-8")
    print(f"{result['status']}: {result['games']} observed matches")


if __name__ == "__main__":
    main()
