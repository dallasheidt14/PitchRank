#!/usr/bin/env python3
"""
Extract and import TGS teams from games CSV.
Run this BEFORE importing games for 10-15x speedup.

Usage:
    python3 scripts/extract_and_import_tgs_teams.py data/raw/tgs/games.csv tgs [--dry-run]

Performance:
    - Extracts ~10k unique teams from 109k games in ~5 seconds
    - Batch imports in ~15 seconds
    - Total: ~20 seconds vs 5-6 hours if done during game import
"""

import argparse
import csv
import logging
import sys
import uuid
from datetime import datetime
from pathlib import Path

# Add parent directory to path
sys.path.append(str(Path(__file__).parent.parent))

import os

from dotenv import load_dotenv
from rich.console import Console
from rich.progress import track

from supabase import create_client

# Set up logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)
console = Console()

# Load environment (check .env.local first, then .env)
env_local = Path(".env.local")
if env_local.exists():
    load_dotenv(env_local)
else:
    load_dotenv()


def calculate_age_group_from_birth_year(birth_year: int) -> str:
    """
    Calculate age group (U##) from birth year using soccer season year.
    Formula: CURRENT_YEAR - birth_year + 1 (season rolls over Aug 1).
    Example: 2014 → U12 (2025-26 season)
    """
    from src.utils.team_utils import CURRENT_YEAR

    age = CURRENT_YEAR - birth_year + 1
    return f"u{age}"


# Full state name → 2-letter code. CSV's `state` column may carry either form.
STATE_NAME_TO_CODE = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR",
    "california": "CA", "colorado": "CO", "connecticut": "CT", "delaware": "DE",
    "florida": "FL", "georgia": "GA", "hawaii": "HI", "idaho": "ID",
    "illinois": "IL", "indiana": "IN", "iowa": "IA", "kansas": "KS",
    "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD",
    "massachusetts": "MA", "michigan": "MI", "minnesota": "MN", "mississippi": "MS",
    "missouri": "MO", "montana": "MT", "nebraska": "NE", "nevada": "NV",
    "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM", "new york": "NY",
    "north carolina": "NC", "north dakota": "ND", "ohio": "OH", "oklahoma": "OK",
    "oregon": "OR", "pennsylvania": "PA", "rhode island": "RI", "south carolina": "SC",
    "south dakota": "SD", "tennessee": "TN", "texas": "TX", "utah": "UT",
    "vermont": "VT", "virginia": "VA", "washington": "WA", "west virginia": "WV",
    "wisconsin": "WI", "wyoming": "WY", "district of columbia": "DC",
}
VALID_STATE_CODES = frozenset(STATE_NAME_TO_CODE.values())
NO_CLUB_VALUES = frozenset({
    "", "n/a", "na", "none", "null", "no club", "no club listed",
    "no club selection", "no club assigned", "no club selected",
    "not selected", "not applicable", "unassigned",
    "select club", "select a club", "choose club",
})


def _resolve_state_code(state_field: str, state_code_field: str) -> str | None:
    """CSV may put a 2-letter code in either column. Return canonical 2-letter or None."""
    for v in (state_code_field, state_field):
        if not v:
            continue
        v = v.strip()
        if v.upper() in VALID_STATE_CODES:
            return v.upper()
        code = STATE_NAME_TO_CODE.get(v.lower())
        if code:
            return code
    return None


def _is_meaningful_club(club_name: str) -> bool:
    return bool(club_name) and club_name.strip().lower() not in NO_CLUB_VALUES


def backfill_existing_team_facts(
    supabase, provider_id: str, teams: dict, existing_aliases: set, dry_run: bool = False
) -> dict:
    """For TGS teams already in alias map, fill missing club_name / state_code on the
    `teams` row using the CSV facts. Never overwrite an existing non-empty value.

    Returns stats: {existing_seen, club_filled, state_filled, both_filled, no_change}.
    """
    stats = {
        "existing_seen": 0, "club_filled": 0, "state_filled": 0,
        "both_filled": 0, "no_change": 0, "errors": 0,
    }
    # Build provider_team_id → CSV facts map (best/last value wins)
    facts_by_pid: dict[str, dict] = {}
    for t in teams.values():
        pid = str(t.get("provider_team_id") or "").strip()
        if not pid or pid not in existing_aliases:
            continue
        existing = facts_by_pid.get(pid, {})
        club = (t.get("club_name") or "").strip()
        if _is_meaningful_club(club):
            existing["club_name"] = club
        sc = _resolve_state_code(t.get("state", ""), t.get("state_code", ""))
        if sc:
            existing["state_code"] = sc
        if existing:
            facts_by_pid[pid] = existing

    if not facts_by_pid:
        console.print("[dim]No existing-team CSV facts to backfill.[/dim]")
        return stats

    stats["existing_seen"] = len(facts_by_pid)
    console.print(f"\n[bold]Backfilling missing club/state for {len(facts_by_pid)} existing teams...[/bold]")

    # Map provider_team_id → team_id_master via team_alias_map (approved only)
    pid_to_master: dict[str, str] = {}
    pids = list(facts_by_pid.keys())
    for i in range(0, len(pids), 200):
        batch = pids[i:i+200]
        try:
            rows = (
                supabase.table("team_alias_map")
                .select("provider_team_id, team_id_master")
                .eq("provider_id", provider_id)
                .eq("review_status", "approved")
                .in_("provider_team_id", batch)
                .execute().data or []
            )
            for r in rows:
                pid_to_master[str(r["provider_team_id"])] = r["team_id_master"]
        except Exception as e:
            logger.warning(f"Error mapping aliases (batch {i // 200 + 1}): {e}")

    # Pull current teams data so we only fill missing fields
    masters = list(pid_to_master.values())
    current_by_master: dict[str, dict] = {}
    for i in range(0, len(masters), 200):
        batch = masters[i:i+200]
        try:
            rows = (
                supabase.table("teams")
                .select("team_id_master, club_name, state_code, state, is_deprecated")
                .in_("team_id_master", batch)
                .execute().data or []
            )
            for r in rows:
                current_by_master[r["team_id_master"]] = r
        except Exception as e:
            logger.warning(f"Error fetching teams (batch {i // 200 + 1}): {e}")

    # Build per-team update payloads
    updates = []  # list of (team_id_master, payload, club_filled, state_filled)
    for pid, facts in facts_by_pid.items():
        master = pid_to_master.get(pid)
        if not master:
            continue
        cur = current_by_master.get(master)
        if not cur or cur.get("is_deprecated"):
            continue
        payload: dict = {}
        cur_club = (cur.get("club_name") or "").strip()
        cur_state = (cur.get("state_code") or "").strip()
        new_club = facts.get("club_name")
        new_state = facts.get("state_code")
        if new_club and not _is_meaningful_club(cur_club):
            payload["club_name"] = new_club
        if new_state and not cur_state:
            payload["state_code"] = new_state
            payload["state"] = next(
                (n for n, c in STATE_NAME_TO_CODE.items() if c == new_state), None
            )
            if payload["state"]:
                payload["state"] = payload["state"].title()
        if not payload:
            stats["no_change"] += 1
            continue
        club_filled = "club_name" in payload
        state_filled = "state_code" in payload
        if club_filled and state_filled:
            stats["both_filled"] += 1
        elif club_filled:
            stats["club_filled"] += 1
        elif state_filled:
            stats["state_filled"] += 1
        updates.append((master, payload, club_filled, state_filled))

    if dry_run:
        console.print(
            f"[yellow]DRY RUN — would update {len(updates)} teams "
            f"({stats['club_filled']} club only, {stats['state_filled']} state only, "
            f"{stats['both_filled']} both, {stats['no_change']} skipped no-op)[/yellow]"
        )
        for sample in updates[:10]:
            mid, payload, _, _ = sample
            console.print(f"  {mid[:8]}…: {payload}")
        return stats

    # Apply updates one-by-one (update is per-row anyway, batching not helpful)
    for mid, payload, _, _ in track(updates, description="Backfilling teams"):
        try:
            supabase.table("teams").update(payload).eq("team_id_master", mid).execute()
        except Exception as e:
            stats["errors"] += 1
            logger.warning(f"Error updating {mid}: {e}")
    return stats


def normalize_gender(gender: str) -> str:
    """
    Normalize gender to DB format.
    Boys/B/Male → Male
    Girls/G/Female → Female
    """
    if not gender:
        return "Male"  # Default

    g = gender.strip().lower()
    if g in ("boys", "b", "male", "m"):
        return "Male"
    elif g in ("girls", "g", "female", "f"):
        return "Female"
    else:
        return "Male"  # Default fallback


def extract_unique_teams_from_csv(csv_file: str) -> dict:
    """
    Parse games CSV and extract unique teams.

    Returns:
        dict: {(team_id, age_year, gender): {team_name, club_name, ...}}

    Note: TGS games CSV has perspective-based data (each game appears twice),
          so we extract both team_id and opponent_id as separate teams.
    """
    teams = {}  # (team_id, age_year, gender) → team_data

    with open(csv_file, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)

        for row in reader:
            # Extract team 1 (from team_id columns)
            team1_key = (row["team_id"].strip(), row["age_year"].strip(), row["gender"].strip())
            if team1_key not in teams:
                teams[team1_key] = {
                    "provider_team_id": row["team_id"].strip(),
                    "team_name": row["team_name"].strip(),
                    "club_name": row["club_name"].strip(),
                    "age_year": row["age_year"].strip(),
                    "gender": row["gender"].strip(),
                    "state_code": row.get("state_code", "").strip(),
                }

            # Extract team 2 (from opponent columns)
            team2_key = (row["opponent_id"].strip(), row["age_year"].strip(), row["gender"].strip())
            if team2_key not in teams:
                teams[team2_key] = {
                    "provider_team_id": row["opponent_id"].strip(),
                    "team_name": row["opponent_name"].strip(),
                    "club_name": row["opponent_club_name"].strip(),
                    "age_year": row["age_year"].strip(),
                    "gender": row["gender"].strip(),
                    "state_code": row.get("state_code", "").strip(),
                }

    return teams


def batch_create_teams_and_aliases(
    supabase, provider_id: str, teams: dict, dry_run: bool = False, batch_size: int = 500
):
    """
    Batch INSERT teams and aliases, skipping teams that already have a direct_id alias.

    Checks team_alias_map first to avoid creating duplicate teams. Only teams
    whose provider_team_id has no existing alias get a new master team + alias.

    Args:
        supabase: Supabase client
        provider_id: Provider UUID
        teams: Dict of unique teams
        dry_run: If True, don't actually insert
        batch_size: Number of records per batch (500 for Supabase)
    """
    team_records = []
    alias_records = []
    stats = {"total_teams": len(teams), "created": 0, "skipped_existing": 0, "errors": 0}

    # Convert teams dict to list for progress tracking
    teams_list = list(teams.values())

    # Pre-check: fetch existing aliases to avoid creating duplicate teams
    all_provider_ids = [t["provider_team_id"] for t in teams_list]
    existing_aliases = set()

    console.print(f"\n[bold]Checking {len(all_provider_ids)} teams against existing aliases...[/bold]")
    for i in range(0, len(all_provider_ids), 100):  # Batch to avoid URI length limits
        batch_ids = all_provider_ids[i : i + 100]
        try:
            result = (
                supabase.table("team_alias_map")
                .select("provider_team_id")
                .eq("provider_id", provider_id)
                .in_("provider_team_id", batch_ids)
                .execute()
            )
            for row in result.data:
                existing_aliases.add(str(row["provider_team_id"]))
        except Exception as e:
            logger.warning(f"Error checking existing aliases (batch {i // 100 + 1}): {e}")

    if existing_aliases:
        console.print(
            f"[yellow]  Found {len(existing_aliases)} teams already in alias map "
            "— skipping creation; will backfill missing club/state on existing rows[/yellow]"
        )
        backfill_stats = backfill_existing_team_facts(
            supabase, provider_id, teams, existing_aliases, dry_run=dry_run
        )
        stats["existing_backfilled_club"] = backfill_stats["club_filled"] + backfill_stats["both_filled"]
        stats["existing_backfilled_state"] = backfill_stats["state_filled"] + backfill_stats["both_filled"]

    # Filter to only new teams
    new_teams = [t for t in teams_list if t["provider_team_id"] not in existing_aliases]
    stats["skipped_existing"] = len(teams_list) - len(new_teams)

    console.print(
        f"[bold]Preparing {len(new_teams)} new teams for import "
        f"(skipping {stats['skipped_existing']} existing)...[/bold]"
    )

    for team_data in track(new_teams, description="Processing teams"):
        try:
            team_id = team_data["provider_team_id"]
            team_name = team_data["team_name"]
            club_name = team_data["club_name"]
            age_year = int(team_data["age_year"])
            gender = normalize_gender(team_data["gender"])
            state_code = team_data.get("state_code")

            # Calculate age group from birth year
            age_group = calculate_age_group_from_birth_year(age_year)

            # Generate UUID for master team ID
            team_id_master = str(uuid.uuid4())

            # Prepare team record
            team_record = {
                "team_id_master": team_id_master,
                "team_name": team_name,
                "club_name": club_name or team_name,  # Use team_name if club_name is empty
                "age_group": age_group,
                "gender": gender,
                "state_code": state_code if state_code else None,
                "provider_id": provider_id,
                "provider_team_id": team_id,
                "created_at": datetime.utcnow().isoformat() + "Z",
            }

            # Prepare alias record (direct_id mapping)
            alias_record = {
                "provider_id": provider_id,
                "provider_team_id": team_id,
                "team_id_master": team_id_master,
                "match_method": "direct_id",
                "match_confidence": 1.0,
                "review_status": "approved",
                "created_at": datetime.utcnow().isoformat() + "Z",
            }

            team_records.append(team_record)
            alias_records.append(alias_record)

        except Exception as e:
            logger.error(f"Error preparing team {team_data.get('team_name')}: {e}")
            stats["errors"] += 1
            continue

    if dry_run:
        console.print(f"\n[yellow]DRY RUN - Would create {len(team_records)} teams[/yellow]")
        console.print("Sample team record:")
        console.print(team_records[0] if team_records else "No teams to show")
        return stats

    # Batch INSERT teams (upsert to handle partial duplicates)
    console.print(f"\n[bold green]Inserting {len(team_records)} teams...[/bold green]")

    for i in track(range(0, len(team_records), batch_size), description="Inserting teams"):
        batch = team_records[i : i + batch_size]
        try:
            supabase.table("teams").insert(batch).execute()
            stats["created"] += len(batch)
        except Exception as e:
            # Batch failed — fall back to one-by-one to save non-duplicate rows
            if "duplicate key" in str(e).lower() or "23505" in str(e):
                batch_num = i // batch_size + 1
                logger.info(f"Batch {batch_num}: conflict detected, falling back to row-by-row insert")
                for record in batch:
                    try:
                        supabase.table("teams").insert(record).execute()
                        stats["created"] += 1
                    except Exception as row_err:
                        if "duplicate key" in str(row_err).lower() or "23505" in str(row_err):
                            stats["skipped_existing"] += 1
                        else:
                            logger.error(f"Error inserting team {record.get('team_name')}: {row_err}")
                            stats["errors"] += 1
            else:
                logger.error(f"Error inserting team batch {i // batch_size + 1}: {e}")
                stats["errors"] += len(batch)

    # Batch INSERT aliases (with row-by-row fallback)
    console.print(f"\n[bold green]Inserting {len(alias_records)} aliases...[/bold green]")

    for i in track(range(0, len(alias_records), batch_size), description="Inserting aliases"):
        batch = alias_records[i : i + batch_size]
        try:
            supabase.table("team_alias_map").insert(batch).execute()
        except Exception as e:
            if "duplicate key" in str(e).lower() or "23505" in str(e):
                batch_num = i // batch_size + 1
                logger.info(f"Alias batch {batch_num}: conflict detected, falling back to row-by-row insert")
                for record in batch:
                    try:
                        supabase.table("team_alias_map").insert(record).execute()
                    except Exception as row_err:
                        if "duplicate key" in str(row_err).lower() or "23505" in str(row_err):
                            pass  # Already exists, skip silently
                        else:
                            logger.error(f"Error inserting alias for {record.get('provider_team_id')}: {row_err}")
            else:
                logger.error(f"Error inserting alias batch {i // batch_size + 1}: {e}")

    return stats


def main():
    parser = argparse.ArgumentParser(description="Extract and import TGS teams from games CSV (run BEFORE game import)")
    parser.add_argument("csv_file", help="Games CSV file")
    parser.add_argument("provider", help='Provider code (e.g., "tgs")')
    parser.add_argument("--dry-run", action="store_true", help="Show what would be created without actually inserting")
    parser.add_argument("--batch-size", type=int, default=500, help="Batch size for inserts (default: 500)")

    args = parser.parse_args()

    # Validate CSV file exists
    csv_path = Path(args.csv_file)
    if not csv_path.exists():
        console.print(f"[red]Error: File not found: {args.csv_file}[/red]")
        sys.exit(1)

    # Initialize Supabase
    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY")

    if not supabase_url or not supabase_key:
        console.print("[red]Error: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set[/red]")
        sys.exit(1)

    supabase = create_client(supabase_url, supabase_key)

    # Get provider ID
    try:
        result = supabase.table("providers").select("id").eq("code", args.provider).single().execute()
        provider_id = result.data["id"]
        console.print(f"[green]✓ Provider ID: {provider_id}[/green]")
    except Exception as e:
        console.print(f"[red]Error: Provider '{args.provider}' not found: {e}[/red]")
        sys.exit(1)

    # Extract unique teams
    console.print(f"\n[bold]Extracting unique teams from {csv_path.name}...[/bold]")
    start_time = datetime.now()

    teams = extract_unique_teams_from_csv(args.csv_file)

    extract_time = (datetime.now() - start_time).total_seconds()
    console.print(f"[green]✓ Extracted {len(teams)} unique teams in {extract_time:.1f}s[/green]")

    # Show sample
    sample_teams = list(teams.values())[:5]
    console.print("\n[bold]Sample teams:[/bold]")
    for i, team in enumerate(sample_teams, 1):
        console.print(f"  {i}. {team['team_name']} ({team['age_year']}, {team['gender']}) - {team['club_name']}")
    if len(teams) > 5:
        console.print(f"  ... and {len(teams) - 5} more")

    # Batch create teams and aliases
    import_start = datetime.now()
    stats = batch_create_teams_and_aliases(
        supabase, provider_id, teams, dry_run=args.dry_run, batch_size=args.batch_size
    )
    import_time = (datetime.now() - import_start).total_seconds()

    # Summary
    console.print("\n[bold green]═══════════════════════════════════════════[/bold green]")
    console.print("[bold green]          IMPORT SUMMARY[/bold green]")
    console.print("[bold green]═══════════════════════════════════════════[/bold green]")
    console.print(f"  Total teams:     {stats['total_teams']:,}")
    console.print(f"  [green]Created:         {stats['created']:,}[/green]")
    console.print(f"  [yellow]Skipped:         {stats['skipped_existing']:,}[/yellow]")
    console.print(f"  [red]Errors:          {stats['errors']:,}[/red]")
    console.print(f"  Extract time:    {extract_time:.1f}s")
    console.print(f"  Import time:     {import_time:.1f}s")
    console.print(f"  [bold]Total time:      {extract_time + import_time:.1f}s[/bold]")
    console.print("[bold green]═══════════════════════════════════════════[/bold green]\n")

    if args.dry_run:
        console.print("[yellow]Dry run completed - no changes made[/yellow]")
    else:
        console.print("[green]✓ Teams imported successfully![/green]")
        console.print("\n[bold]Next step:[/bold]")
        console.print(f"  python3 scripts/import_games_enhanced.py {args.csv_file} {args.provider}")


if __name__ == "__main__":
    main()
