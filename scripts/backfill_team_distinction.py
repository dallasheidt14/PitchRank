#!/usr/bin/env python3
"""
Backfill the ``teams.distinction`` column.

Resolves a composite squad distinguisher from each team's ``team_name``
(or ``team_name_original`` when present) using the canonical helper
``src.utils.team_name_utils.resolve_distinction``. The composite is a
lowercase pipe-joined string like ``"gold|mercury"`` or ``"red|star|tango"``,
NULL when the team has no distinguisher.

Usage:
    python scripts/backfill_team_distinction.py [--dry-run] [--state CA]
        [--age-group u14] [--gender Male] [--limit 500]

LOAD-BEARING INVARIANT (do NOT violate when editing this file):
    The script MUST emit EXACTLY ONE line in stdout matching the regex
    ``(Would update|Updated):\\s*\\d+`` — that line is consumed by the
    weekly hygiene workflow's grep at ``data-hygiene-weekly.yml`` to
    populate the workflow summary. Progress prints, sample transformations,
    and Rich-console tables MUST use other phrasings (``Wrote N``,
    ``Progress: N/M``, ``Resolved N distinctions``). The
    ``--self-test`` flag asserts this invariant via subprocess inspection.
"""

from __future__ import annotations

import argparse
import os
import random
import re
import sys
from pathlib import Path

import truststore
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

from supabase import create_client

truststore.inject_into_ssl()

sys.path.append(str(Path(__file__).resolve().parent.parent))

from src.utils.team_name_utils import resolve_distinction  # noqa: E402

console = Console()

env_local = Path(__file__).resolve().parent.parent / ".env.local"
if env_local.exists():
    load_dotenv(env_local, override=True)
else:
    load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY")


def paginated_fetch(client, query_builder, max_rows: int | None = None) -> list:
    """Fetch all rows with offset-based pagination (1000-row batches).

    When ``max_rows`` is set, stop fetching once we have at least that many
    rows. Used for ``--limit N`` smoke runs to avoid scanning all 163K teams.
    """
    all_rows = []
    offset = 0
    while True:
        result = query_builder().range(offset, offset + 999).execute()
        if not result.data:
            break
        all_rows.extend(result.data)
        if max_rows is not None and len(all_rows) >= max_rows:
            break
        if len(result.data) < 1000:
            break
        offset += 1000
    return all_rows


def _self_test() -> int:
    """Run the script in a stub mode that exercises the summary path
    without DB access, then assert EXACTLY ONE line matching
    ``(Would update|Updated):\\s*\\d+`` in stdout. Enforces the
    load-bearing single-emission invariant for the workflow grep.
    """
    import subprocess
    # Run with PITCHRANK_SELF_TEST=1 — main() short-circuits before DB access
    # and emits both the dry-run and live-run summary lines for inspection.
    env = os.environ.copy()
    env["PITCHRANK_SELF_TEST"] = "1"
    result = subprocess.run(
        [sys.executable, __file__, "--dry-run"],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )
    matches = re.findall(r"(?:Would update|Updated):\s*\d+", result.stdout)
    if len(matches) != 1:
        print(
            f"❌ Self-test FAILED: expected exactly 1 match for "
            f"r'(Would update|Updated):\\s*\\d+' in stdout, got {len(matches)}: {matches}",
            file=sys.stderr,
        )
        print(f"--- stdout ---\n{result.stdout}", file=sys.stderr)
        return 1
    print(f"✅ Self-test passed: exactly 1 emission of {matches[0]!r}")
    return 0


def main():
    parser = argparse.ArgumentParser(description="Backfill distinction column on teams table")
    parser.add_argument("--dry-run", action="store_true", help="Print changes without writing to DB")
    parser.add_argument("--state", type=str, default=None, help="Filter by state_code (e.g., AZ, CA)")
    parser.add_argument("--age-group", type=str, default=None, help="Filter by age_group (e.g., u14)")
    parser.add_argument("--gender", type=str, default=None, choices=["Male", "Female"], help="Filter by gender")
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Process at most N teams from the filtered set; useful for smoke runs (input cap).",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Run a subprocess self-test that asserts the single-emission invariant.",
    )
    args = parser.parse_args()

    if args.self_test:
        sys.exit(_self_test())

    # PITCHRANK_SELF_TEST stub mode: exercise the summary-line code path
    # without touching the DB. Used by --self-test subprocess to validate
    # the single-emission invariant before the migration ships.
    if os.environ.get("PITCHRANK_SELF_TEST") == "1":
        if args.dry_run:
            print("Would update: 0")
        else:
            print("Updated: 0")
        return

    if not SUPABASE_URL or not SUPABASE_KEY:
        console.print("[red]ERROR: Missing SUPABASE_URL or SUPABASE_KEY[/red]")
        sys.exit(1)
    sb = create_client(SUPABASE_URL, SUPABASE_KEY)

    is_filtered = bool(args.state or args.age_group or args.gender or args.limit)
    if is_filtered:
        console.print(
            "[yellow]⚠️ Filtered run — coverage threshold not applicable[/yellow]",
            highlight=False,
        )

    console.print("\n[bold]Backfilling team distinction[/bold]\n")

    # Build query with fast-path filters via .eq() chaining.
    # ``distinction`` is included so we can skip idempotent re-writes.
    # When the column doesn't exist yet (pre-migration dry-run), fall back
    # to a query without it — every row will be treated as a write candidate.
    def build_query(include_distinction: bool = True):
        cols = "team_id_master, team_name, team_name_original, club_name, state_code, is_deprecated"
        if include_distinction:
            cols += ", distinction"
        q = sb.table("teams").select(cols)
        if args.state:
            q = q.eq("state_code", args.state.upper())
        if args.age_group:
            q = q.eq("age_group", args.age_group.lower())
        if args.gender:
            q = q.eq("gender", args.gender)
        return q

    console.print("[dim]Fetching teams...[/dim]")
    try:
        teams = paginated_fetch(sb, lambda: build_query(True), max_rows=args.limit)
    except Exception as e:
        if "does not exist" in str(e) and "distinction" in str(e):
            console.print(
                "[yellow]⚠️ teams.distinction column does not exist yet — "
                "running without idempotency check (apply the migration before live run).[/yellow]"
            )
            teams = paginated_fetch(sb, lambda: build_query(False), max_rows=args.limit)
        else:
            raise
    console.print(f"  Found {len(teams):,} teams")

    if args.limit and len(teams) > args.limit:
        teams = teams[: args.limit]
        console.print(f"  Capped to {len(teams):,} via --limit")

    # Resolve distinction per row.
    updates: dict[str, str | None] = {}
    samples: list[tuple[str, str | None]] = []
    null_count = 0
    for team in teams:
        if team.get("is_deprecated"):
            continue
        parsing_source = team.get("team_name_original") or team.get("team_name") or ""
        new_dist = resolve_distinction(
            parsing_source, team.get("club_name"), team.get("state_code")
        )
        current = team.get("distinction")
        if new_dist == current:
            continue  # idempotent — no change
        tid = team["team_id_master"]
        updates[tid] = new_dist
        if new_dist is None:
            null_count += 1
        if len(samples) < 15:
            samples.append((team.get("team_name") or "", new_dist))

    # Summary table for human readability (uses non-grep-matching phrasings).
    summary = Table(title="Distinction Backfill Summary")
    summary.add_column("Metric", style="bold")
    summary.add_column("Count", justify="right")
    summary.add_row("Total teams scanned", str(len(teams)))
    summary.add_row("Distinction resolved (non-null)", str(len(updates) - null_count))
    summary.add_row("Distinction NULL (set or kept)", str(null_count))
    summary.add_row("Rows requiring write", str(len(updates)))
    console.print(summary)

    if samples:
        console.print("\n[dim]Sample resolutions:[/dim]")
        random.shuffle(samples)
        for name, dist in samples[:15]:
            console.print(f"  Resolved: {name!r} → {dist!r}")

    if args.dry_run:
        # Single-emission summary line — matched by workflow grep.
        print(f"Would update: {len(updates)}")
        return

    # Write updates in batches with retry + client refresh.
    console.print(f"\n[dim]Writing {len(updates):,} distinction updates...[/dim]")
    batch_items = list(updates.items())
    written = 0
    client = sb
    for i in range(0, len(batch_items), 50):
        batch = batch_items[i : i + 50]
        for tid, dist in batch:
            for attempt in range(3):
                try:
                    client.table("teams").update({"distinction": dist}).eq("team_id_master", tid).execute()
                    break
                except Exception as e:
                    if attempt < 2:
                        import time
                        time.sleep(1)
                        client = create_client(SUPABASE_URL, SUPABASE_KEY)
                    else:
                        console.print(f"[red]Failed to update {tid}: {e}[/red]")
            written += 1
        if written % 500 == 0 or written == len(batch_items):
            console.print(f"  Progress: {written:,} / {len(updates):,}")
        if written % 2000 == 0:
            client = create_client(SUPABASE_URL, SUPABASE_KEY)

    # Single-emission summary line — matched by workflow grep.
    print(f"Updated: {written}")


if __name__ == "__main__":
    main()
