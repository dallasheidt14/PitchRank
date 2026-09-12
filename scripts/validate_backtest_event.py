#!/usr/bin/env python3
"""Validate one completed Backtest event against a named acceptance profile."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.tournaments.backtest_acceptance import (
    ACCEPTANCE_PROFILES,
    validate_backtest_acceptance,
)
from src.tournaments.storage._io import write_json


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event-key", required=True)
    parser.add_argument("--profile", choices=sorted(ACCEPTANCE_PROFILES), required=True)
    parser.add_argument("--model-artifact", required=True)
    parser.add_argument("--reports-dir", default="reports")
    parser.add_argument("--output", default="")
    args = parser.parse_args()
    report = validate_backtest_acceptance(
        args.event_key,
        ACCEPTANCE_PROFILES[args.profile],
        model_artifact=args.model_artifact,
        base_dir=args.reports_dir,
    )
    if args.output:
        write_json(Path(args.output), report)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
