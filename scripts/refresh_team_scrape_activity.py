#!/usr/bin/env python3
"""
Refresh the ``teams`` scrape-activity columns.

Calls the ``refresh_team_scrape_activity`` RPC, which recomputes
``last_played_at``, ``last_fixture_at``, ``game_row_count`` and
``scrape_attempts`` from ``games`` and ``team_scrape_log`` — both resolved
through ``team_merge_map`` — and writes back only the rows whose values moved.
Those four columns are what the scrape-eligibility functions read, so nothing
is filtered until this has run.

Usage:
    python scripts/refresh_team_scrape_activity.py [--dry-run] [--batch-size 2000]

The RPC handles ONE keyset page per call and this script walks the table, feeding
each page's last team id back as ``p_after``. That split is not an optimisation:
a function cannot raise its own statement_timeout (PostgreSQL arms that timer
once per top-level client command and statements inside a function never re-arm
it), and a service-role PostgREST request inherits ``authenticator``'s 8-second
budget, so a single whole-table call is cancelled every time. Keeping each call
small is what makes the refresh finish at all.

There is deliberately NO Python fallback for the aggregation itself. Computing it
client-side would page roughly 3M game rows plus 2.5M scrape-log rows over
PostgREST, which is the reason the work lives in Postgres. A failure here is a
failure: the script exits non-zero and the workflow retries, leaving the previous
refresh's values in place.

LOAD-BEARING INVARIANT (do NOT violate when editing this file):
    The script MUST emit EXACTLY ONE stdout line of the form ``Updated: N`` or
    ``Would update: N``, with exactly one space after the colon — the workflow
    greps it for the run summary. Progress prints and Rich-console output MUST
    use other phrasings (``Rows changed: N``, ``Page N``). Pinned by
    tests/unit/test_refresh_team_scrape_activity.py, which drives the real code
    path rather than a stub.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import truststore
from dotenv import load_dotenv
from rich.console import Console

from supabase import create_client

truststore.inject_into_ssl()

sys.path.append(str(Path(__file__).resolve().parent.parent))

console = Console()

env_local = Path(__file__).resolve().parent.parent / ".env.local"
if env_local.exists():
    load_dotenv(env_local, override=True)
else:
    load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY")

# Teams per RPC call. The ceiling is the server's 8s statement_timeout, not the
# client's; 2,000 keeps a page's aggregate plus its guarded UPDATE well inside it.
DEFAULT_BATCH_SIZE = 2000


def main():
    parser = argparse.ArgumentParser(description="Refresh the teams scrape-activity columns")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report how many rows would change without writing to the DB",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help=f"Teams per RPC call (default {DEFAULT_BATCH_SIZE}); each call must fit the server timeout.",
    )
    args = parser.parse_args()

    if not SUPABASE_URL or not SUPABASE_KEY:
        console.print("[red]ERROR: Missing SUPABASE_URL or SUPABASE_KEY[/red]")
        sys.exit(1)

    sb = create_client(SUPABASE_URL, SUPABASE_KEY)

    mode = "dry run" if args.dry_run else "live"
    console.print(f"\n[bold]Refreshing team scrape activity[/bold] ([dim]{mode}[/dim])\n")

    changed = 0
    pages = 0
    after = None
    while True:
        try:
            result = sb.rpc(
                "refresh_team_scrape_activity",
                {"p_after": after, "p_batch_size": args.batch_size, "p_dry_run": args.dry_run},
            ).execute()
        except Exception as e:
            console.print(f"[red]refresh_team_scrape_activity failed after {pages} pages: {e}[/red]")
            sys.exit(1)

        rows = result.data or []
        if not rows:
            break

        after = rows[0].get("last_team_id")
        changed += rows[0].get("rows_changed") or 0
        pages += 1
        console.print(f"[dim]  Page {pages}: {changed:,} rows changed so far[/dim]")

        # A page with no last id is an empty page: the walk is done.
        if after is None:
            break

    console.print(f"[green]✓[/green] Rows changed: {changed:,} across {pages} pages")

    # Single-emission summary line — matched by the workflow grep, which requires
    # exactly one space after the colon.
    if args.dry_run:
        print(f"Would update: {changed}")
    else:
        print(f"Updated: {changed}")


if __name__ == "__main__":
    main()
