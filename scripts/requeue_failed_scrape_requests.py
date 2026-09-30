#!/usr/bin/env python3
"""
Re-enqueue teams whose scrape request failed for a reason that is not the team's.

A drain finalizes every claimed row it could not scrape with one blanket message,
"Team not found or scrape error", so a provider outage and a permanently stale
provider_team_id land in 'failed' looking identical. Rows that never reached the
finalize at all stay in 'processing'. Neither status is ever revisited:
claim_queue_items selects only 'pending', and there is no lease or reaper.

So a run that failed wholesale takes its teams out of the pipeline until a producer
happens to re-select them, and the producers are fixed-N selectors ordered by other
criteria -- a team the safety net skipped once can wait weeks for its next turn.
This is the operator repair: it reads those rows, keeps the ones whose message does
not name a permanent fault, resolves merges, drops the teams already re-scraped
since, and re-enqueues each at the priority its original request carried.

Rows are read, never rewritten. Clearing the stranded 'processing' rows is
scripts/retire_stranded_scrape_requests.py's job, and the two are independent:
idx_scrape_requests_pending_team is UNIQUE only WHERE status = 'pending', so a row
left in 'processing' does not stop a fresh pending one being created for its team.

Writing is opt-in. --execute is required; without it this reports and exits.

Usage:
    python scripts/requeue_failed_scrape_requests.py --since-hours 168
    python scripts/requeue_failed_scrape_requests.py --since-hours 168 --execute
    python scripts/requeue_failed_scrape_requests.py --since-hours 168 --only failed --execute
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import truststore
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

from supabase import create_client

truststore.inject_into_ssl()

sys.path.append(str(Path(__file__).resolve().parent.parent))

from scripts.enqueue_helpers import resolve_merges, teams_with_pending_user_request  # noqa: E402

console = Console()

# Both files, .env.local first so its values win. Mirrors
# scripts/retire_stranded_scrape_requests.py.
REPO_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(REPO_ROOT / ".env.local")
load_dotenv(REPO_ROOT / ".env")

SUPABASE_URL = os.getenv("SUPABASE_URL")
SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
SUPABASE_KEY = SERVICE_ROLE_KEY or os.getenv("SUPABASE_KEY")

# A live drain holds rows in 'processing' for the length of its run. Same floor as
# retire_stranded_scrape_requests.py, for the same reason.
DEFAULT_MIN_STRANDED_AGE_HOURS = 24

PAGE_SIZE = 1000
ID_BATCH = 100
PROGRESS_EVERY = 500

REQUEST_COLUMNS = (
    "id,team_id_master,request_type,priority,status,error_message,game_date,processed_at,completed_at"
)

# Messages naming a fault re-running cannot clear. Anything else -- the blanket
# message, a connection reset, a proxy error -- is treated as retryable, and the
# dry run prints the message breakdown so the operator can see what that admitted.
PERMANENT_ERROR_MARKERS = (
    "not found on gotsport (404)",
    "no scraper available for provider",
)


def get_client():
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise SystemExit("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set")
    return create_client(SUPABASE_URL, SUPABASE_KEY)


def _paged(build_query, *order_columns: str) -> list[dict]:
    """Page a scrape_requests select, ordered so the page boundary is stable.

    id breaks ties because the ties here are enormous: a bulk claim or a bulk
    finalize stamps every row it touches with one timestamp, so thousands share a
    single processed_at or completed_at. Ordering on that alone lets OFFSET paging
    skip rows.
    """
    rows: list[dict] = []
    offset = 0
    while True:
        query = build_query()
        for column in order_columns:
            query = query.order(column)
        page = query.order("id").range(offset, offset + PAGE_SIZE - 1).execute().data or []
        rows.extend(page)
        if len(page) < PAGE_SIZE:
            return rows
        offset += PAGE_SIZE


def fetch_failed(client, since_iso: str) -> list[dict]:
    """Every 'failed' row finalized on or after the cutoff."""
    return _paged(
        lambda: (
            client.table("scrape_requests")
            .select(REQUEST_COLUMNS)
            .eq("status", "failed")
            .gte("completed_at", since_iso)
        ),
        "completed_at",
    )


def fetch_stranded(client, since_iso: str, min_age_iso: str) -> list[dict]:
    """Every 'processing' row claimed inside the window but old enough to be dead."""
    return _paged(
        lambda: (
            client.table("scrape_requests")
            .select(REQUEST_COLUMNS)
            .eq("status", "processing")
            .gte("processed_at", since_iso)
            .lt("processed_at", min_age_iso)
        ),
        "processed_at",
    )


def is_retryable(row: dict) -> bool:
    message = (row.get("error_message") or "").lower()
    return not any(marker in message for marker in PERMANENT_ERROR_MARKERS)


def attempt_time(row: dict) -> datetime | None:
    """When the drain took this row on.

    processed_at is the claim, which both the finalize and the stranded path leave
    alone. completed_at is not interchangeable: retire_stranded_scrape_requests.py
    stamps it with the retirement, long after the attempt, so preferring it would
    date a days-old failure to the cleanup that swept it up.
    """
    stamp = row.get("processed_at") or row.get("completed_at")
    return datetime.fromisoformat(stamp) if stamp else None


def _rank(row: dict) -> tuple[int, float]:
    """Highest priority first, then most recent."""
    when = attempt_time(row)
    return (row["priority"], -(when.timestamp() if when else 0.0))


def _scrape_covered_failure(last_scraped: str | None, failed_at: datetime | None) -> bool:
    """Whether a productive scrape has happened since the failure."""
    if not last_scraped or failed_at is None:
        return False
    return datetime.fromisoformat(last_scraped) > failed_at


def best_request_per_team(rows: list[dict]) -> dict[str, dict]:
    """The highest-priority request each team held, priority 1 being highest.

    A tie goes to the most recent, so game_date comes from the latest request at
    that priority rather than whichever the page order happened to yield first.
    """
    best: dict[str, dict] = {}
    for row in rows:
        team_id = row.get("team_id_master")
        if not team_id:
            continue
        held = best.get(team_id)
        if held is None or _rank(row) < _rank(held):
            best[team_id] = row
    return best


def latest_attempt_per_team(rows: list[dict]) -> dict[str, datetime | None]:
    """The newest attempt each team made, across every one of its retryable rows.

    The skip rule reads this rather than the chosen request's own timestamp: if a
    team's newest attempt failed, it needs re-queueing whatever an older one did.
    """
    latest: dict[str, datetime | None] = {}
    for row in rows:
        team_id = row.get("team_id_master")
        if not team_id:
            continue
        when = attempt_time(row)
        held = latest.get(team_id)
        if team_id not in latest or (when is not None and (held is None or when > held)):
            latest[team_id] = when
    return latest


def load_teams(client, team_ids: list[str]) -> dict[str, dict]:
    """The provider fields the RPC needs plus the columns the skip rules read."""
    teams: dict[str, dict] = {}
    for i in range(0, len(team_ids), ID_BATCH):
        rows = (
            client.table("teams")
            .select("team_id_master,team_name,provider_id,provider_team_id,is_deprecated,last_scraped_at")
            .in_("team_id_master", team_ids[i : i + ID_BATCH])
            .execute()
            .data
        ) or []
        for row in rows:
            teams[row["team_id_master"]] = row
    return teams


def summarize_sources(rows: list[dict], dropped: list[dict]) -> None:
    by_day: dict[str, int] = {}
    by_status: dict[str, int] = {}
    by_message: dict[str, int] = {}
    for row in rows:
        stamp = row.get("completed_at") or row.get("processed_at") or ""
        by_day[stamp[:10] or "unknown"] = by_day.get(stamp[:10] or "unknown", 0) + 1
        status = row.get("status") or "unknown"
        by_status[status] = by_status.get(status, 0) + 1
        message = (row.get("error_message") or "(none)")[:60]
        by_message[message] = by_message.get(message, 0) + 1

    table = Table(title="Retryable requests in scope")
    table.add_column("Failed/claimed on", style="bold")
    table.add_column("Rows", justify="right")
    for day in sorted(by_day):
        table.add_row(day, f"{by_day[day]:,}")
    console.print(table)

    console.print("[dim]By status: " + ", ".join(f"{k}={v:,}" for k, v in sorted(by_status.items())) + "[/dim]")
    console.print("[dim]By error message:[/dim]")
    for message, count in sorted(by_message.items(), key=lambda kv: -kv[1]):
        console.print(f"[dim]  {count:>6,}  {message}[/dim]")
    if dropped:
        console.print(f"[dim]Excluded as permanent faults: {len(dropped):,} rows[/dim]")


def enqueue(client, ready: list[dict]) -> tuple[int, int]:
    ok = failed = 0
    for i, team in enumerate(ready, start=1):
        try:
            client.rpc(
                "enqueue_scrape_request",
                {
                    "p_team_id_master": team["team_id_master"],
                    "p_team_name": team["team_name"],
                    "p_provider_id": team["provider_id"],
                    "p_provider_team_id": team["provider_team_id"],
                    "p_game_date": team["game_date"],
                    "p_request_type": team["request_type"],
                    "p_priority": team["priority"],
                },
            ).execute()
            ok += 1
        except Exception as exc:  # noqa: BLE001
            failed += 1
            console.print(f"[red]  FAILED {str(team['team_name'])[:44]!r}: {str(exc)[:110]}[/red]")
        if i % PROGRESS_EVERY == 0:
            console.print(f"  Progress: {i:,} / {len(ready):,}")
    return ok, failed


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--since-hours",
        type=int,
        required=True,
        help="how far back to look for failed or stranded requests (no default, so the scope is explicit)",
    )
    parser.add_argument(
        "--only",
        choices=("failed", "stranded"),
        default=None,
        help="narrow to one source (default: both 'failed' rows and rows stranded in 'processing')",
    )
    parser.add_argument(
        "--min-stranded-age-hours",
        type=int,
        default=DEFAULT_MIN_STRANDED_AGE_HOURS,
        help=f"ignore 'processing' rows claimed more recently than this (default {DEFAULT_MIN_STRANDED_AGE_HOURS})",
    )
    parser.add_argument("--limit", type=int, default=None, help="enqueue at most this many teams")
    parser.add_argument("--execute", action="store_true", help="Enqueue. Without this, report only.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report only. This is already the default; the flag states it explicitly and overrides --execute.",
    )
    args = parser.parse_args()

    # Writing is opt-in, and --dry-run wins when both are passed, so a script
    # invoked with both can never enqueue by accident. Mirrors
    # retire_stranded_scrape_requests.py.
    dry_run = args.dry_run or not args.execute

    if args.since_hours < 1:
        console.print("[red]--since-hours must be at least 1[/red]")
        return 1
    if args.min_stranded_age_hours < 1:
        console.print("[red]--min-stranded-age-hours must be at least 1; a live drain holds rows while it works[/red]")
        return 1

    # scrape_requests is service-role only, reads included
    # (20260908120000_lock_down_scrape_requests_writes.sql revoked the browser
    # roles' default grant), so both modes need the key and the report's own
    # SELECT is what fails without it.
    if not SERVICE_ROLE_KEY:
        console.print("[red]ERROR: SUPABASE_SERVICE_ROLE_KEY is required; RLS blocks scrape_requests otherwise[/red]")
        return 1

    now = datetime.now(timezone.utc)
    since_iso = (now - timedelta(hours=args.since_hours)).isoformat()
    min_stranded_iso = (now - timedelta(hours=args.min_stranded_age_hours)).isoformat()

    client = get_client()

    rows: list[dict] = []
    if args.only != "stranded":
        rows.extend(fetch_failed(client, since_iso))
    if args.only != "failed":
        rows.extend(fetch_stranded(client, since_iso, min_stranded_iso))

    console.print(f"Requests in window: {len(rows):,}")
    if not rows:
        return 0

    retryable = [row for row in rows if is_retryable(row)]
    dropped = [row for row in rows if not is_retryable(row)]
    summarize_sources(retryable, dropped)
    if not retryable:
        return 0

    best = best_request_per_team(retryable)
    attempts = latest_attempt_per_team(retryable)
    canonical = resolve_merges(client, list(best))
    per_team: dict[str, dict] = {}
    per_team_attempt: dict[str, datetime | None] = {}
    for team_id, row in best.items():
        target = canonical[team_id]
        held = per_team.get(target)
        if held is None or _rank(row) < _rank(held):
            per_team[target] = row
        when = attempts.get(team_id)
        held_when = per_team_attempt.get(target)
        if target not in per_team_attempt or (when is not None and (held_when is None or when > held_when)):
            per_team_attempt[target] = when

    team_ids = sorted(per_team)
    console.print(f"Distinct teams after merge resolution: {len(team_ids):,}")

    teams = load_teams(client, team_ids)
    protected = teams_with_pending_user_request(client, team_ids)

    ready: list[dict] = []
    skipped = {"missing": 0, "deprecated": 0, "no_provider": 0, "scraped_since_failure": 0, "user_pending": 0}
    for team_id in team_ids:
        team = teams.get(team_id)
        if not team:
            skipped["missing"] += 1
            continue
        if team.get("is_deprecated"):
            skipped["deprecated"] += 1
            continue
        if not team.get("provider_id") or not team.get("provider_team_id"):
            skipped["no_provider"] += 1
            continue
        # The scrape has to postdate the failure to have covered it. A fixed
        # wall-clock window cannot tell the two apart once --since-hours is wider
        # than the window: it re-enqueues a week-old failure the team already
        # recovered from, and skips a failure from an hour ago because the team
        # was scraped yesterday. last_scraped_at only advances on an attempt that
        # reached the provider, so "later than the failure" means real coverage.
        if _scrape_covered_failure(team.get("last_scraped_at"), per_team_attempt.get(team_id)):
            skipped["scraped_since_failure"] += 1
            continue
        if team_id in protected:
            skipped["user_pending"] += 1
            continue
        request = per_team[team_id]
        ready.append(
            {
                "team_id_master": team_id,
                "team_name": team["team_name"],
                "provider_id": team["provider_id"],
                "provider_team_id": team["provider_team_id"],
                "request_type": request["request_type"],
                # The request's own date, not today: process_missing_games scrapes a
                # +/-90 day window around it, so re-anchoring on today moves the
                # window off the date a user actually asked about.
                "game_date": request["game_date"] or date.today().isoformat(),
                "priority": request["priority"],
            }
        )

    console.print(
        "[dim]Skipped: "
        + ", ".join(f"{name}={count:,}" for name, count in skipped.items() if count)
        + "[/dim]"
    )

    if args.limit is not None:
        ready.sort(key=lambda team: team["priority"])
        ready = ready[: args.limit]

    by_priority: dict[int, int] = {}
    for team in ready:
        by_priority[team["priority"]] = by_priority.get(team["priority"], 0) + 1
    console.print(f"[bold]Enqueueable teams: {len(ready):,}[/bold]")
    console.print("[dim]By priority: " + ", ".join(f"p{k}={v:,}" for k, v in sorted(by_priority.items())) + "[/dim]")
    if not ready:
        return 0

    if dry_run:
        console.print("\n[yellow]DRY RUN — nothing enqueued. Re-run with --execute.[/yellow]")
        return 0

    ok, failed = enqueue(client, ready)
    console.print(f"\n[green]Enqueued {ok:,} teams[/green], {failed:,} failed.")
    console.print("[dim]process_missing_games drains 40 teams every 15 minutes; "
                  'run "Help Clear Queue" for a bulk drain.[/dim]')
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
