#!/usr/bin/env python3
"""
Retire scrape_requests rows abandoned in 'processing'.

A drain flips rows to 'processing' when it claims them and back to a terminal
status when it finishes. Nothing else ever touches them: there is no lease, no
expiry, no reaper, and claim_queue_items only selects 'pending'. A run that died
between those two points therefore left its rows stranded permanently.

Rows are retired to 'failed', NOT back to 'pending'. They are days old by the
time anyone notices, and returning thousands of stale requests to the queue would
push them ahead of current work. The producers re-request whichever teams still
need it, and a stranded row blocks that from happening in the meantime:
idx_scrape_requests_pending_team is UNIQUE only WHERE status = 'pending', so a
'processing' row does not stop a fresh 'pending' one being created.

Writing is opt-in. --execute is required; without it this reports and exits.

Usage:
    python scripts/retire_stranded_scrape_requests.py                    # report only
    python scripts/retire_stranded_scrape_requests.py --execute
    python scripts/retire_stranded_scrape_requests.py --older-than-hours 48 --execute
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import truststore
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

from supabase import create_client

truststore.inject_into_ssl()

sys.path.append(str(Path(__file__).resolve().parent.parent))

console = Console()

# Both files, .env.local first so its values win. Root .env is where this repo's
# SUPABASE_* keys live, so reading it only when .env.local is absent leaves the
# script without credentials on any machine that has both. Mirrors
# scripts/enqueue_safety_net.py.
REPO_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(REPO_ROOT / ".env.local")
load_dotenv(REPO_ROOT / ".env")

SUPABASE_URL = os.getenv("SUPABASE_URL")
SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
SUPABASE_KEY = SERVICE_ROLE_KEY or os.getenv("SUPABASE_KEY")

# A live drain holds rows in 'processing' for the length of its run. This floor
# keeps the cleanup off anything a drain might still be working on; the observed
# strandings are days old, so nothing legitimate sits near the boundary.
DEFAULT_MIN_AGE_HOURS = 24

PAGE_SIZE = 1000
UPDATE_BATCH = 100
RETIRE_MESSAGE = "Retired by retire_stranded_scrape_requests.py: claimed by a drain that never finalized"


def fetch_stranded(client, cutoff_iso: str) -> list[dict]:
    """Every 'processing' row whose claim predates the cutoff, paginated."""
    rows: list[dict] = []
    offset = 0
    while True:
        page = (
            client.table("scrape_requests")
            .select("id, team_id_master, request_type, processed_at")
            .eq("status", "processing")
            .lt("processed_at", cutoff_iso)
            .order("processed_at")
            # id breaks ties, and the ties here are enormous: a bulk claim stamps
            # every row it takes with one timestamp, so 5,981 rows shared a single
            # processed_at. Ordering on that alone lets OFFSET paging skip rows —
            # it silently missed 503 of 6,482 on the first run.
            .order("id")
            .range(offset, offset + PAGE_SIZE - 1)
            .execute()
            .data
        ) or []
        rows.extend(page)
        if len(page) < PAGE_SIZE:
            break
        offset += PAGE_SIZE
    return rows


def summarize(rows: list[dict]) -> None:
    by_day: dict[str, int] = {}
    by_type: dict[str, int] = {}
    for row in rows:
        day = (row.get("processed_at") or "")[:10] or "unknown"
        by_day[day] = by_day.get(day, 0) + 1
        req_type = row.get("request_type") or "unknown"
        by_type[req_type] = by_type.get(req_type, 0) + 1

    table = Table(title="Stranded requests")
    table.add_column("Claimed on", style="bold")
    table.add_column("Rows", justify="right")
    for day in sorted(by_day):
        table.add_row(day, f"{by_day[day]:,}")
    console.print(table)

    console.print("[dim]By request type: " + ", ".join(f"{k}={v:,}" for k, v in sorted(by_type.items())) + "[/dim]")


def retire(client, rows: list[dict]) -> int:
    """Mark rows failed in batches. Returns the number of rows written."""
    now_iso = datetime.now(timezone.utc).isoformat()
    written = 0
    ids = [row["id"] for row in rows]
    for i in range(0, len(ids), UPDATE_BATCH):
        batch = ids[i : i + UPDATE_BATCH]
        try:
            result = (
                client.table("scrape_requests")
                .update({"status": "failed", "completed_at": now_iso, "error_message": RETIRE_MESSAGE})
                .in_("id", batch)
                .eq("status", "processing")
                .execute()
            )
            # Count what PostgREST says it changed, not the batch size. Incrementing
            # by len(batch) reports a full run even when every update matched nothing,
            # which is how a partial write passes for a complete one.
            written += len(result.data or [])
        except Exception as e:
            console.print(f"[red]Failed to retire batch {i // UPDATE_BATCH + 1}: {e}[/red]")
        if (i // UPDATE_BATCH) % 10 == 0:
            console.print(f"  Progress: {min(i + UPDATE_BATCH, len(ids)):,} / {len(ids):,}")
    return written


def main() -> None:
    parser = argparse.ArgumentParser(description="Retire scrape_requests stranded in 'processing'")
    parser.add_argument(
        "--older-than-hours",
        type=int,
        default=DEFAULT_MIN_AGE_HOURS,
        help=f"Only touch claims older than this (default {DEFAULT_MIN_AGE_HOURS}); keeps a live drain safe.",
    )
    parser.add_argument("--execute", action="store_true", help="Write the changes. Without this, report only.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report only. This is already the default; the flag states it explicitly and overrides --execute.",
    )
    args = parser.parse_args()

    # Writing is opt-in rather than opt-out, matching the convention for changes
    # that are awkward to undo. --dry-run wins when both are passed, so a script
    # invoked with both in a workflow can never write by accident.
    dry_run = args.dry_run or not args.execute

    if args.older_than_hours < 1:
        console.print("[red]--older-than-hours must be at least 1; a live drain holds rows while it works[/red]")
        sys.exit(1)

    if not SUPABASE_URL or not SUPABASE_KEY:
        console.print("[red]ERROR: Missing SUPABASE_URL or SUPABASE_KEY[/red]")
        sys.exit(1)

    # RLS grants UPDATE on scrape_requests to service_role alone
    # (20251113150557_add_scrape_requests.sql). Under any other key every batch
    # matches nothing and PostgREST still answers 200, so the run would report a
    # data problem instead of the permissions problem it actually hit. SELECT is
    # open to all, so a report-only run needs no service-role key.
    if not dry_run and not SERVICE_ROLE_KEY:
        console.print(
            "[red]ERROR: --execute needs SUPABASE_SERVICE_ROLE_KEY; "
            "RLS blocks the update under any other key[/red]"
        )
        sys.exit(1)

    client = create_client(SUPABASE_URL, SUPABASE_KEY)
    # processed_at is TIMESTAMPTZ and its writers now stamp UTC, so this compares
    # like with like. Rows claimed by a local drain before that fix read as their
    # naive local time, which sits west of UTC and so ages out early.
    cutoff = datetime.now(timezone.utc) - timedelta(hours=args.older_than_hours)

    console.print(f"\n[bold]Stranded scrape requests[/bold] claimed before {cutoff.isoformat(timespec='seconds')}\n")
    rows = fetch_stranded(client, cutoff.isoformat())

    if not rows:
        console.print("[green]Nothing stranded.[/green]")
        return

    summarize(rows)

    if dry_run:
        console.print(f"\n[yellow]Would retire: {len(rows)}[/yellow]  [dim](re-run with --execute to write)[/dim]")
        return

    console.print(f"\n[dim]Retiring {len(rows):,} rows...[/dim]")
    written = retire(client, rows)
    console.print(f"[green]Retired: {written}[/green]")

    if written < len(rows):
        console.print(f"[red]{len(rows) - written:,} rows could not be retired[/red]")
        sys.exit(1)


if __name__ == "__main__":
    main()
