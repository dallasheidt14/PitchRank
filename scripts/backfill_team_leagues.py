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
    # MLS NEXT HD/AD — check before ECNL patterns (some names contain both)
    ("MLS_NEXT_HD", re.compile(r"\bMLS\s*NEXT?\s*HD\b", re.IGNORECASE)),
    ("MLS_NEXT_HD", re.compile(r"\bMNHD\b", re.IGNORECASE)),
    ("MLS_NEXT_AD", re.compile(r"\bMLS\s*NEXT?\s*AD\b", re.IGNORECASE)),
    ("MLS_NEXT_AD", re.compile(r"\bNEXT\s*AD\b", re.IGNORECASE)),
    # Generic "MLS NEXT" without explicit AD/HD modifier → default to AD
    # (matches dry-run's generic→AD fallback). Negative lookahead prevents
    # double-matching when AD/HD is present (already handled above).
    ("MLS_NEXT_AD", re.compile(r"\bMLS\s*NEXT?\b(?!\s*(?:AD|HD))", re.IGNORECASE)),
    # ECNL RL — check before ECNL (more specific first)
    ("ECNL_RL", re.compile(r"\bECNL[\s\-]*RL\b", re.IGNORECASE)),
    ("ECNL_RL", re.compile(r"\bECRL\b", re.IGNORECASE)),
    ("ECNL_RL", re.compile(r"\bE64\s*RL\b", re.IGNORECASE)),
    # Standalone RL suffix — likely ECNL RL (e.g., "Alabama FC RL 2011")
    ("ECNL_RL", re.compile(r"\bRL\s+\d{4}\b", re.IGNORECASE)),  # "RL 2011"
    ("ECNL_RL", re.compile(r"\d{4}\s*[\-\s]*RL\b", re.IGNORECASE)),  # "2010 - RL" or "2010 RL"
    ("ECNL_RL", re.compile(r"\bRL\b$", re.IGNORECASE)),  # RL at end of name
    # ECNL (after RL patterns so we don't match "ECNL RL" as "ECNL")
    ("ECNL", re.compile(r"\bECNL\b", re.IGNORECASE)),
    # Other leagues
    ("DPL", re.compile(r"\bDPLO?\b", re.IGNORECASE)),  # DPL and DPLO
    ("GA", re.compile(r"\bGirls\s*Academy\s*(?:League)?\b", re.IGNORECASE)),
    ("GA", re.compile(r"\bGA\s*Gold\b", re.IGNORECASE)),
    ("GA", re.compile(r"\bGA\b(?!\s*(?:Green|Gray|Grey|United|SC|FC\b))", re.IGNORECASE)),
    ("NPL", re.compile(r"\bNPL\b", re.IGNORECASE)),
    ("ASPIRE", re.compile(r"\bAspire\b", re.IGNORECASE)),
    ("NL", re.compile(r"\bNational\s*League\b", re.IGNORECASE)),
    ("NL", re.compile(r"\bNAL\b", re.IGNORECASE)),  # National Academy League
    ("NL", re.compile(r"\bNL\b(?!\s*(?:Premier|Next))", re.IGNORECASE)),
    # EA2 before EA (more specific first)
    ("EA2", re.compile(r"\bEA\s*2\b", re.IGNORECASE)),
    ("EA", re.compile(r"\bElite\s*Academy\b", re.IGNORECASE)),
    ("EA", re.compile(r"\bEA\b(?!\s*2\b)", re.IGNORECASE)),  # standalone EA, not EA2
    # Standalone HD/AD suffix — likely MLS NEXT (e.g., "TFA-IE 2009 HD")
    ("MLS_NEXT_HD", re.compile(r"\b\d{4}\s*HD\b", re.IGNORECASE)),  # "2009 HD"
    ("MLS_NEXT_HD", re.compile(r"\bHD\b$", re.IGNORECASE)),  # HD at end of name
    ("MLS_NEXT_AD", re.compile(r"\b\d{4}\s*AD\b", re.IGNORECASE)),  # "2009 AD"
    ("MLS_NEXT_AD", re.compile(r"\bAD\b$", re.IGNORECASE)),  # AD at end of name
]

# Alias map division → league (supplements name-based detection)
MLS_NEXT_DIVISION_MAP = {
    "HD": "MLS_NEXT_HD",
    "AD": "MLS_NEXT_AD",
}


def detect_league_from_name(team_name: str) -> str | None:
    """Detect league from team name using regex patterns."""
    # Skip pre-development team names — these are separate tiers, not the parent league.
    if re.search(r"\bPre[\s\-]*ECNL\b", team_name, re.IGNORECASE):
        return None
    if re.search(r"\bPre[\s\-]*MLS\b", team_name, re.IGNORECASE):
        return None
    if re.search(r"\bPRE[\s\-]*ACADEMY\b", team_name, re.IGNORECASE):
        return None
    if re.search(r"\bPre[\s\-]*NPL\b", team_name, re.IGNORECASE):
        return None
    # Negative lookahead on Pre-NL prevents matching inside longer tokens like Pre-NLSA.
    if re.search(r"\bPre[\s\-]*NL\b(?!\w)", team_name, re.IGNORECASE):
        return None
    for league, pattern in LEAGUE_PATTERNS:
        if pattern.search(team_name):
            return league
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
    parser.add_argument(
        "--age-groups",
        type=str,
        default=None,
        help=(
            "Comma-separated age groups to filter (e.g., u13,u14,u15,u16,u17,u18,u19). "
            "Default: all age groups. League is ranking-engine scope (u13+) so a "
            "typical re-run uses --age-groups u13,u14,u15,u16,u17,u18,u19."
        ),
    )
    args = parser.parse_args()

    age_filter: set[str] | None = None
    if args.age_groups:
        age_filter = {a.strip().lower() for a in args.age_groups.split(",") if a.strip()}
        console.print(f"[yellow]Filtering to age_groups: {sorted(age_filter)}[/yellow]")

    console.print("\n[bold]Backfilling team leagues[/bold]\n")

    # 1. Fetch all teams (include age_group when filtering)
    console.print("[dim]Fetching teams...[/dim]")
    select_cols = "team_id_master, team_name, is_deprecated"
    if age_filter:
        select_cols += ", age_group"
    teams = paginated_fetch("teams", select_cols)
    console.print(f"  Found {len(teams):,} teams")
    if age_filter:
        before = len(teams)
        teams = [t for t in teams if (t.get("age_group") or "").lower() in age_filter]
        console.print(f"  Filtered to {len(teams):,} teams in age groups {sorted(age_filter)} (from {before:,})")

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

    # 5. Write updates in batches with retry + client refresh
    console.print(f"\n[dim]Writing {len(updates):,} league updates...[/dim]")
    batch_items = list(updates.items())
    written = 0
    client = sb
    for i in range(0, len(batch_items), 50):
        batch = batch_items[i : i + 50]
        for tid, league in batch:
            for attempt in range(3):
                try:
                    client.table("teams").update({"league": league}).eq("team_id_master", tid).execute()
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
            console.print(f"  ✓ Updated {written:,} / {len(updates):,}")
        # Refresh client every 2000 updates to avoid connection staleness
        if written % 2000 == 0:
            client = create_client(SUPABASE_URL, SUPABASE_KEY)

    console.print(f"\n[bold green]Done — {written:,} teams updated with league data[/bold green]")


if __name__ == "__main__":
    main()
