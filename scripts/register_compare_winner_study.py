"""Verify and register a fixed winner-study manifest; no forecast or target-result reads."""

import argparse
import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT))

from scripts.settle_prospective_match_predictions import _supabase_client  # noqa: E402
from src.predictions.winner_study import register_study  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    logging.getLogger("httpx").setLevel(logging.WARNING)
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    print(json.dumps(register_study(_supabase_client(), manifest, ROOT, dry_run=not args.execute), indent=2))


if __name__ == "__main__":
    main()
