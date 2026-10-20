"""Preview or resume missing-game requests for one saved MatchBalance run."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv  # noqa: E402

from src.tournaments.seeding_refresh import RefreshQueue, refresh_run, refresh_summary  # noqa: E402
from src.tournaments.seeding_run_store import load_run  # noqa: E402
from supabase import create_client  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_file", type=Path, help="Saved seeding_run.json; never modified by this command")
    parser.add_argument("--execute", action="store_true", help="Write queue requests and their recovery journal")
    parser.add_argument("--status-only", action="store_true", help="Update existing receipts without enqueueing")
    parser.add_argument("--retry-failed", action="store_true")
    args = parser.parse_args()
    load_dotenv()
    directory = args.run_file.resolve().parent
    run = load_run(directory.name, base_dir=directory.parent)
    client = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])
    journal = refresh_run(run, directory, RefreshQueue(client), retry_failed=args.retry_failed,
                          status_only=args.status_only, dry_run=not args.execute)
    print(json.dumps({"dry_run": not args.execute, "counts": refresh_summary(journal),
                      "teams": journal["teams"]}, indent=2))


if __name__ == "__main__":
    main()
