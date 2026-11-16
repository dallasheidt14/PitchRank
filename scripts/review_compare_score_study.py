"""Report coverage while sealed; after release, compare the fixed score candidates privately."""

import argparse
import json
import logging
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.settle_prospective_match_predictions import _supabase_client  # noqa: E402
from src.predictions.score_study_review import preserve_report, review_scores  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("study_signature")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if not re.fullmatch(r"[a-f0-9]{64}", args.study_signature):
        parser.error("Use a registered SHA256 study signature")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    client = _supabase_client()
    report = review_scores(client, args.study_signature, dry_run=not args.execute)
    receipt = preserve_report(client, args.study_signature, report, dry_run=not args.execute)
    print(json.dumps({"status": report["status"], "private_report": receipt, "production_promotion": False}, indent=2))


if __name__ == "__main__":
    main()
