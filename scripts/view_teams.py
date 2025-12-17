#!/usr/bin/env python3
"""
View and print teams filtered by age group, gender, and state.

Usage examples:
    # View U13 Male teams in Arizona
    python scripts/view_teams.py --age-group u13 --gender Male --state AZ

    # View all U14 Female teams nationally
    python scripts/view_teams.py --age-group u14 --gender Female

    # Export U13 Male AZ teams to CSV
    python scripts/view_teams.py --age-group u13 --gender Male --state AZ --export teams.csv

    # View with rankings included
    python scripts/view_teams.py --age-group u13 --gender Male --state AZ --with-rankings
"""
import argparse
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

from supabase import create_client
import os
import pandas as pd
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table
from rich.panel import Panel


console = Console()

# Load environment variables - prioritize .env.local if it exists
env_local = Path('.env.local')
if env_local.exists():
    load_dotenv(env_local, override=True)
else:
    load_dotenv()


def get_supabase_client():
    """Initialize and return Supabase client."""
    supabase_url = os.getenv('SUPABASE_URL')
    supabase_key = os.getenv('SUPABASE_SERVICE_ROLE_KEY')

    if not supabase_url or not supabase_key:
        console.print("[red]Error: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set in .env[/red]")
        sys.exit(1)

    return create_client(supabase_url, supabase_key)


def fetch_teams(
    supabase,
    age_group: str = None,
    gender: str = None,
    state_code: str = None,
    include_deprecated: bool = False
) -> pd.DataFrame:
    """
    Fetch teams from database with optional filters.

    Args:
        supabase: Supabase client
        age_group: Filter by age group (e.g., 'u13')
        gender: Filter by gender ('Male' or 'Female')
        state_code: Filter by state code (e.g., 'AZ')
        include_deprecated: Include deprecated/merged teams

    Returns:
        DataFrame with team data
    """
    query = supabase.table('teams').select(
        'team_id_master, team_name, club_name, age_group, gender, state_code, state, birth_year, is_deprecated'
    )

    # Apply filters
    if age_group:
        # Normalize age group to lowercase
        query = query.eq('age_group', age_group.lower())

    if gender:
        # Normalize gender to title case
        query = query.eq('gender', gender.title())

    if state_code:
        # Normalize state code to uppercase
        query = query.eq('state_code', state_code.upper())

    if not include_deprecated:
        query = query.eq('is_deprecated', False)

    # Execute query
    result = query.execute()

    if not result.data:
        return pd.DataFrame()

    return pd.DataFrame(result.data)


def fetch_rankings(supabase, team_ids: list) -> pd.DataFrame:
    """
    Fetch rankings for specified team IDs.

    Args:
        supabase: Supabase client
        team_ids: List of team_id_master UUIDs

    Returns:
        DataFrame with ranking data
    """
    if not team_ids:
        return pd.DataFrame()

    rankings_data = []
    batch_size = 150  # Avoid Supabase URL length limits

    for i in range(0, len(team_ids), batch_size):
        batch = team_ids[i:i+batch_size]
        try:
            result = supabase.table('rankings_full').select(
                'team_id, national_rank, state_rank, national_power_score, '
                'games_played, wins, losses, draws, strength_of_schedule, status'
            ).in_('team_id', batch).execute()

            if result.data:
                rankings_data.extend(result.data)
        except Exception as e:
            console.print(f"[yellow]Warning: Failed to fetch rankings batch: {e}[/yellow]")
            continue

    return pd.DataFrame(rankings_data) if rankings_data else pd.DataFrame()


def display_teams(teams_df: pd.DataFrame, rankings_df: pd.DataFrame = None, title: str = "Teams"):
    """Display teams in a formatted table."""
    if teams_df.empty:
        console.print("[yellow]No teams found matching the criteria.[/yellow]")
        return

    # Merge rankings if available
    if rankings_df is not None and not rankings_df.empty:
        teams_df = teams_df.merge(
            rankings_df,
            left_on='team_id_master',
            right_on='team_id',
            how='left'
        )

    # Sort by national_rank if available, otherwise by team_name
    if 'national_rank' in teams_df.columns:
        teams_df = teams_df.sort_values(
            by=['national_rank', 'team_name'],
            ascending=[True, True],
            na_position='last'
        )
    else:
        teams_df = teams_df.sort_values(by='team_name')

    # Create table
    table = Table(title=title, show_lines=False)

    # Add columns
    if 'national_rank' in teams_df.columns:
        table.add_column("#", style="cyan", justify="right", width=5)
    table.add_column("Team Name", style="white", max_width=45)
    table.add_column("Club", style="blue", max_width=30)
    table.add_column("Age", style="yellow", justify="center", width=5)
    table.add_column("State", style="magenta", justify="center", width=6)

    if 'national_rank' in teams_df.columns:
        table.add_column("Nat. Rank", style="green", justify="right", width=10)
        table.add_column("State Rank", style="green", justify="right", width=11)
        table.add_column("PowerScore", style="cyan", justify="right", width=11)
        table.add_column("GP", style="dim", justify="right", width=4)
        table.add_column("W-L-D", style="dim", justify="center", width=9)

    # Add rows
    for idx, row in teams_df.iterrows():
        row_data = []

        if 'national_rank' in teams_df.columns:
            rank = row.get('national_rank')
            row_data.append(str(int(rank)) if pd.notna(rank) else "-")

        row_data.extend([
            str(row.get('team_name', 'Unknown'))[:45],
            str(row.get('club_name', '') or '')[:30],
            str(row.get('age_group', '')).upper(),
            str(row.get('state_code', '')),
        ])

        if 'national_rank' in teams_df.columns:
            nat_rank = row.get('national_rank')
            state_rank = row.get('state_rank')
            power_score = row.get('national_power_score')
            gp = row.get('games_played')
            wins = row.get('wins', 0)
            losses = row.get('losses', 0)
            draws = row.get('draws', 0)

            row_data.extend([
                str(int(nat_rank)) if pd.notna(nat_rank) else "-",
                str(int(state_rank)) if pd.notna(state_rank) else "-",
                f"{power_score:.4f}" if pd.notna(power_score) else "-",
                str(int(gp)) if pd.notna(gp) else "-",
                f"{int(wins) if pd.notna(wins) else 0}-{int(losses) if pd.notna(losses) else 0}-{int(draws) if pd.notna(draws) else 0}",
            ])

        table.add_row(*row_data)

    console.print(table)


def export_to_csv(teams_df: pd.DataFrame, rankings_df: pd.DataFrame, filepath: str):
    """Export teams to CSV file."""
    if teams_df.empty:
        console.print("[yellow]No teams to export.[/yellow]")
        return

    # Merge rankings if available
    if rankings_df is not None and not rankings_df.empty:
        export_df = teams_df.merge(
            rankings_df,
            left_on='team_id_master',
            right_on='team_id',
            how='left'
        )
    else:
        export_df = teams_df.copy()

    # Sort by national_rank if available
    if 'national_rank' in export_df.columns:
        export_df = export_df.sort_values(
            by=['national_rank', 'team_name'],
            ascending=[True, True],
            na_position='last'
        )

    # Export to CSV
    export_df.to_csv(filepath, index=False)
    console.print(f"[green]Exported {len(export_df)} teams to {filepath}[/green]")


def main():
    parser = argparse.ArgumentParser(
        description='View and print teams filtered by age group, gender, and state.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # View U13 Male teams in Arizona
  python scripts/view_teams.py --age-group u13 --gender Male --state AZ

  # View all U14 Female teams nationally
  python scripts/view_teams.py --age-group u14 --gender Female

  # Export U13 Male AZ teams to CSV
  python scripts/view_teams.py --age-group u13 --gender Male --state AZ --export teams.csv

  # View with rankings included
  python scripts/view_teams.py --age-group u13 --gender Male --state AZ --with-rankings
        """
    )
    parser.add_argument('--age-group', '-a', type=str, help='Age group (e.g., u13, U14)')
    parser.add_argument('--gender', '-g', type=str, choices=['Male', 'Female', 'male', 'female'],
                        help='Gender (Male or Female)')
    parser.add_argument('--state', '-s', type=str, help='State code (e.g., AZ, CA, TX)')
    parser.add_argument('--with-rankings', '-r', action='store_true',
                        help='Include rankings data (national rank, power score, etc.)')
    parser.add_argument('--include-deprecated', action='store_true',
                        help='Include deprecated/merged teams')
    parser.add_argument('--export', '-e', type=str, metavar='FILE',
                        help='Export results to CSV file')
    parser.add_argument('--limit', '-l', type=int, default=None,
                        help='Limit number of teams displayed')

    args = parser.parse_args()

    # Build title
    filters = []
    if args.age_group:
        filters.append(args.age_group.upper())
    if args.gender:
        filters.append(args.gender.title())
    if args.state:
        filters.append(args.state.upper())

    title = " ".join(filters) + " Teams" if filters else "All Teams"

    # Initialize Supabase
    console.print(f"\n[bold blue]Fetching {title}...[/bold blue]\n")
    supabase = get_supabase_client()

    # Fetch teams
    teams_df = fetch_teams(
        supabase,
        age_group=args.age_group,
        gender=args.gender,
        state_code=args.state,
        include_deprecated=args.include_deprecated
    )

    if teams_df.empty:
        console.print("[yellow]No teams found matching the criteria.[/yellow]")
        return

    # Fetch rankings if requested
    rankings_df = pd.DataFrame()
    if args.with_rankings:
        team_ids = teams_df['team_id_master'].astype(str).tolist()
        rankings_df = fetch_rankings(supabase, team_ids)

    # Apply limit
    if args.limit:
        if not rankings_df.empty:
            # Merge first to sort by rank before limiting
            merged = teams_df.merge(
                rankings_df,
                left_on='team_id_master',
                right_on='team_id',
                how='left'
            ).sort_values('national_rank', na_position='last')
            teams_df = merged.head(args.limit)
            # Re-extract rankings for limited teams
            if not rankings_df.empty:
                rankings_df = rankings_df[rankings_df['team_id'].isin(teams_df['team_id_master'])]
        else:
            teams_df = teams_df.head(args.limit)

    # Summary
    summary_parts = [f"[bold]Found {len(teams_df)} teams[/bold]"]
    if args.age_group:
        summary_parts.append(f"Age: [cyan]{args.age_group.upper()}[/cyan]")
    if args.gender:
        summary_parts.append(f"Gender: [cyan]{args.gender.title()}[/cyan]")
    if args.state:
        summary_parts.append(f"State: [cyan]{args.state.upper()}[/cyan]")

    console.print(Panel(" | ".join(summary_parts), border_style="blue"))
    console.print()

    # Export or display
    if args.export:
        export_to_csv(teams_df, rankings_df, args.export)
    else:
        display_teams(teams_df, rankings_df if args.with_rankings else None, title=title)

    console.print()


if __name__ == '__main__':
    main()
