"""Order stdin's pending fixtures with the same pure sampler used by intake; no I/O except stdio."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.predictions.collection_selection import select_fixture_candidates  # noqa: E402


def main():
    rows = json.load(sys.stdin)
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError("Expected pending fixture rows")
    ordered = select_fixture_candidates([(None, row) for row in rows], len(rows))
    print(json.dumps([row["id"] for _, row in ordered]))


if __name__ == "__main__":
    main()
