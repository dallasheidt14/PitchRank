#!/usr/bin/env python3
"""
Backfill league column on teams table.

Classifies teams into leagues based on:
1. team_alias_map.division (HD/AD for MLS NEXT teams)
2. Team name patterns (ECNL, ECNL RL, DPL, GA, NPL, etc.)

Usage:
    python scripts/backfill_team_leagues.py [--dry-run]
"""

import argparse
import os
import re
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

from supabase import create_client

console = Console()

env_local = Path(__file__).resolve().parent.parent / ".env.local"
if env_local.exists():
    load_dotenv(env_local, override=True)
else:
    load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY")
if not SUPABASE_URL or not SUPABASE_KEY:
    console.print("[red]ERROR: Missing SUPABASE_URL or SUPABASE_KEY[/red]")
    sys.exit(1)

sb = create_client(SUPABASE_URL, SUPABASE_KEY)


# ── League detection patterns ───────────────────────────────────────────
# Order matters: check more specific patterns first (ECNL RL before ECNL)

LEAGUE_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("ECNL_RL", re.compile(r"\bECNL[\s\-]*RL\b", re.IGNORECASE)),
    ("ECNL_RL", re.compile(r"\bECRL\b", re.IGNORECASE)),
    ("ECNL", re.compile(r"\bECNL\b", re.IGNORECASE)),
    ("DPL", re.compile(r"\bDPL\b", re.IGNORECASE)),
    ("GA", re.compile(r"\bGA\b(?!\s*(?:Gold|Green|Gray|Grey|United|SC|FC|Academy\b))", re.IGNORECASE)),
    ("NPL", re.compile(r"\bNPL\b", re.IGNORECASE)),
    ("ASPIRE", re.compile(r"\bAspire\b", re.IGNORECASE)),
    ("NL", re.compile(r"\bNL\b(?!\s*(?:Premier|Next))", re.IGNORECASE)),
    ("EA", re.compile(r"\bElite\s*Academy\b", re.IGNORECASE)),
]

MLS_NEXT_DIVISION_MAP = {
    "HD": "MLS_NEXT_HD",
    "AD": "MLS_NEXT_AD",
}


def detect_league_from_name(team_name: str) -> str | None:
    """Detect league from team name using regex patterns."""
    for league, pattern in LEAGUE_PATTERNS:
        if pattern.search(team_name):
            return league
    if re.search(r"\bMLS\s*NEXT\b", team_name, re.IGNORECASE):
        return None
    if re.search(r"\bPre[\s\-]*ECNL\b", team_name, re.IGNORECASE):
        return None
    if re.search(r"\bPre[\s\-]*MLS\b", team_name, re.IGNORECASE):
        return None
    return None


def paginated_fetch(table: str, select: str, filters: dict | None = None) -> list:
    """Fetch all rows with offset-based pagination (1000-row batches)."""
    all_rows = []
    offset = 0
    while True:
        q = sb.table(table).select(select).range(offset, offset + 999)
        if filters:
            for col, val in filters.items():
                q = q.eq(col, val)
        result = q.execute()
        if not result.data:
            break
        all_rows.extend(result.data)
        if len(result.data) < 1000:
            break
        offset += 1000
    return all_rows


def main():
    parser = argparse.ArgumentParser(description="Backfill league column on teams table")
    parser.add_argument("--dry-run", action="store_true", help="Print changes without writing to DB")
    args = parser.parse_args()

    console.print("\n[bold]Backfilling team leagues[/bold]\n")

    # 1. Fetch all teams
    console.print("[dim]Fetching teams...[/dim]")
    teams = paginated_fetch("teams", "team_id_master, team_name, is_deprecated")
    console.print(f"  Found {len(teams):,} teams")

    # 2. Fetch alias map divisions (for MLS NEXT HD/AD detection)
    console.print("[dim]Fetching team_alias_map divisions...[/dim]")
    aliases = paginated_fetch("team_alias_map", "team_id_master, division")
    division_map: dict[str, str] = {}
    for alias in aliases:
        div = alias.get("division")
        tid = alias.get("team_id_master")
        if div and tid and div in MLS_NEXT_DIVISION_MAP:
            division_map[tid] = MLS_NEXT_DIVISION_MAP[div]
    console.print(f"  Found {len(division_map):,} MLS NEXT teams with division data")

    # 3. Classify each team
    updates: dict[str, str] = {}
    for team in teams:
        tid = team["team_id_master"]
        name = team.get("team_name", "")

        if tid in division_map:
            updates[tid] = division_map[tid]
        else:
            league = detect_league_from_name(name)
            if league:
                updates[tid] = league

    # 4. Summary
    league_counts: dict[str, int] = {}
    for league in updates.values():
        league_counts[league] = league_counts.get(league, 0) + 1

    summary = Table(title="League Classification Summary")
    summary.add_column("League", style="bold")
    summary.add_column("Count", justify="right")
    for league, count in sorted(league_counts.items(), key=lambda x: -x[1]):
        summary.add_row(league, str(count))
    summary.add_row("[dim]Unaffiliated (NULL)[/dim]", str(len(teams) - len(updates)))
    summary.add_row("[bold]Total[/bold]", str(len(teams)))
    console.print(summary)

    if args.dry_run:
        console.print("\n[yellow]DRY RUN — no changes written[/yellow]")
        return

    # 5. Write updates in batches
    console.print(f"\n[dim]Writing {len(updates):,} league updates...[/dim]")
    batch_items = list(updates.items())
    written = 0
    for i in range(0, len(batch_items), 50):
        batch = batch_items[i : i + 50]
        for tid, league in batch:
            sb.table("teams").update({"league": league}).eq("team_id_master", tid).execute()
            written += 1
        if written % 500 == 0 or written == len(batch_items):
            console.print(f"  ✓ Updated {written:,} / {len(updates):,}")

    console.print(f"\n[bold green]Done — {written:,} teams updated with league data[/bold green]")


if __name__ == "__main__":
    main()
