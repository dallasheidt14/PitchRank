#!/usr/bin/env python3
"""
Exclude all games for a team within a date range from rankings.

Uses the exclude_games_for_team_in_range RPC if available, otherwise falls
back to direct queries. The DB propagation trigger automatically excludes
perspective duplicates (same logical game scraped from different sources).

Usage:
    # Dry run (preview only)
    python scripts/exclude_games_by_team_date.py \
        --team c2f8e0aa-2f96-4c23-b5ae-6782ce392bc9 \
        --start-date 2026-01-02 --end-date 2026-01-04

    # Execute exclusion
    python scripts/exclude_games_by_team_date.py \
        --team c2f8e0aa-2f96-4c23-b5ae-6782ce392bc9 \
        --start-date 2026-01-02 --end-date 2026-01-04 --execute
"""
import argparse
import os
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table
from supabase import create_client

# Load environment variables
env_local = Path('.env.local')
if env_local.exists():
    load_dotenv(env_local, override=True)
else:
    load_dotenv()

console = Console()


def get_supabase():
    url = os.getenv('SUPABASE_URL')
    key = os.getenv('SUPABASE_SERVICE_ROLE_KEY')
    if not url or not key:
        console.print("[red]Error: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set[/red]")
        sys.exit(1)
    return create_client(url, key)


def fetch_games_for_team(supabase, team_id: str, start_date: str, end_date: str):
    """Fetch all games involving a team in the date range."""
    or_filter = f'home_team_master_id.eq.{team_id},away_team_master_id.eq.{team_id}'
    result = supabase.table('games').select(
        'id, game_date, game_uid, home_team_master_id, away_team_master_id, '
        'home_score, away_score, home_provider_id, away_provider_id, '
        'provider_id, competition, event_name, is_excluded'
    ).or_(or_filter).gte(
        'game_date', start_date
    ).lte(
        'game_date', end_date
    ).not_.is_(
        'home_score', 'null'
    ).not_.is_(
        'away_score', 'null'
    ).order('game_date').execute()
    return result.data or []


def resolve_team_names(supabase, master_ids: set):
    """Resolve master IDs to team names."""
    if not master_ids:
        return {}
    names = {}
    batch = list(master_ids)
    for i in range(0, len(batch), 100):
        chunk = batch[i:i + 100]
        result = supabase.table('teams').select(
            'team_id_master, team_name'
        ).in_('team_id_master', chunk).execute()
        if result.data:
            for row in result.data:
                names[row['team_id_master']] = row['team_name']
    return names


def find_perspective_duplicates(supabase, games: list):
    """Find perspective duplicates for each game (same date + master teams + scores)."""
    duplicates = []
    seen_ids = {g['id'] for g in games}

    for game in games:
        home_master = game.get('home_team_master_id')
        away_master = game.get('away_team_master_id')
        if not home_master or not away_master:
            continue

        game_date = game['game_date']
        home_score = game.get('home_score')
        away_score = game.get('away_score')

        # Query for games on same date with same master team pair (either orientation)
        or_filter = (
            f'home_team_master_id.eq.{home_master},away_team_master_id.eq.{home_master},'
            f'home_team_master_id.eq.{away_master},away_team_master_id.eq.{away_master}'
        )
        result = supabase.table('games').select(
            'id, game_date, game_uid, home_team_master_id, away_team_master_id, '
            'home_score, away_score, home_provider_id, away_provider_id, '
            'provider_id, competition, event_name, is_excluded'
        ).eq('game_date', game_date).or_(or_filter).not_.is_(
            'home_score', 'null'
        ).not_.is_(
            'away_score', 'null'
        ).execute()

        if not result.data:
            continue

        for row in result.data:
            if row['id'] in seen_ids:
                continue
            # Check if it's actually the same logical game (same team pair + scores)
            r_home = row.get('home_team_master_id')
            r_away = row.get('away_team_master_id')
            r_h_score = row.get('home_score')
            r_a_score = row.get('away_score')

            same_orientation = (
                r_home == home_master and r_away == away_master
                and r_h_score == home_score and r_a_score == away_score
            )
            swapped_orientation = (
                r_home == away_master and r_away == home_master
                and r_h_score == away_score and r_a_score == home_score
            )

            if same_orientation or swapped_orientation:
                duplicates.append(row)
                seen_ids.add(row['id'])

    return duplicates


def display_games(games: list, team_names: dict, title: str):
    """Display games in a rich table."""
    table = Table(title=title, show_lines=True)
    table.add_column("Date", style="cyan")
    table.add_column("Home Team", style="green")
    table.add_column("Score", style="bold")
    table.add_column("Away Team", style="green")
    table.add_column("Competition")
    table.add_column("Excluded", style="red")
    table.add_column("Game UID", style="dim", max_width=50)
    table.add_column("ID", style="dim", max_width=12)

    for game in games:
        home_name = team_names.get(game.get('home_team_master_id'), game.get('home_provider_id', '?'))
        away_name = team_names.get(game.get('away_team_master_id'), game.get('away_provider_id', '?'))
        score = f"{game.get('home_score', '?')}-{game.get('away_score', '?')}"
        excluded = "YES" if game.get('is_excluded') else "no"
        excluded_style = "bold red" if game.get('is_excluded') else "dim"
        competition = game.get('competition') or game.get('event_name') or ''

        table.add_row(
            game.get('game_date', ''),
            home_name[:40],
            score,
            away_name[:40],
            competition[:30],
            f"[{excluded_style}]{excluded}[/{excluded_style}]",
            (game.get('game_uid') or '')[:50],
            str(game.get('id', ''))[:12],
        )

    console.print(table)


def exclude_games(supabase, game_ids: list):
    """Set is_excluded = TRUE on the given game IDs."""
    excluded_count = 0
    for game_id in game_ids:
        try:
            supabase.table('games').update(
                {'is_excluded': True}
            ).eq('id', game_id).eq('is_excluded', False).execute()
            excluded_count += 1
        except Exception as e:
            console.print(f"[red]Error excluding game {game_id}: {e}[/red]")
    return excluded_count


def main():
    parser = argparse.ArgumentParser(
        description="Exclude games for a team in a date range from rankings"
    )
    parser.add_argument('--team', required=True, help='Team master ID (UUID)')
    parser.add_argument('--start-date', required=True, help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end-date', required=True, help='End date (YYYY-MM-DD)')
    parser.add_argument(
        '--execute', action='store_true',
        help='Actually exclude games (default is dry-run preview)'
    )
    parser.add_argument(
        '--skip-duplicates', action='store_true',
        help='Skip searching for perspective duplicates (faster but less thorough)'
    )
    args = parser.parse_args()

    supabase = get_supabase()

    console.print(f"\n[bold]Searching for games...[/bold]")
    console.print(f"  Team: {args.team}")
    console.print(f"  Date range: {args.start_date} to {args.end_date}")
    console.print(f"  Mode: {'[red bold]EXECUTE[/red bold]' if args.execute else '[yellow]DRY RUN[/yellow]'}\n")

    # Fetch direct games for this team
    games = fetch_games_for_team(supabase, args.team, args.start_date, args.end_date)

    if not games:
        console.print("[yellow]No games found for this team in the date range.[/yellow]")
        return

    # Resolve team names for display
    master_ids = set()
    for g in games:
        if g.get('home_team_master_id'):
            master_ids.add(g['home_team_master_id'])
        if g.get('away_team_master_id'):
            master_ids.add(g['away_team_master_id'])

    team_names = resolve_team_names(supabase, master_ids)

    console.print(f"[bold]Found {len(games)} direct game row(s) for this team:[/bold]")
    display_games(games, team_names, "Direct Games")

    # Find perspective duplicates
    all_games = list(games)
    if not args.skip_duplicates:
        console.print(f"\n[bold]Searching for perspective duplicates...[/bold]")
        duplicates = find_perspective_duplicates(supabase, games)
        if duplicates:
            # Resolve any new team names
            for d in duplicates:
                if d.get('home_team_master_id'):
                    master_ids.add(d['home_team_master_id'])
                if d.get('away_team_master_id'):
                    master_ids.add(d['away_team_master_id'])
            team_names = resolve_team_names(supabase, master_ids)

            console.print(f"[bold yellow]Found {len(duplicates)} perspective duplicate(s):[/bold yellow]")
            display_games(duplicates, team_names, "Perspective Duplicates")
            all_games.extend(duplicates)
        else:
            console.print("[green]No perspective duplicates found.[/green]")

    # Identify games that need exclusion
    to_exclude = [g for g in all_games if not g.get('is_excluded')]
    already_excluded = [g for g in all_games if g.get('is_excluded')]

    console.print(f"\n[bold]Summary:[/bold]")
    console.print(f"  Total game rows found: {len(all_games)}")
    console.print(f"  Already excluded: {len(already_excluded)}")
    console.print(f"  Need exclusion: {len(to_exclude)}")

    if not to_exclude:
        console.print("\n[green bold]All games are already excluded. Nothing to do.[/green bold]")
        return

    if args.execute:
        console.print(f"\n[red bold]Excluding {len(to_exclude)} game(s)...[/red bold]")
        game_ids = [g['id'] for g in to_exclude]
        count = exclude_games(supabase, game_ids)
        console.print(f"[green bold]Done! Excluded {count} game(s).[/green bold]")
        console.print(
            "[dim]Note: The DB propagation trigger will automatically exclude "
            "any additional perspective duplicates.[/dim]"
        )
    else:
        console.print(
            f"\n[yellow]Dry run — {len(to_exclude)} game(s) would be excluded. "
            f"Re-run with --execute to apply.[/yellow]"
        )


if __name__ == '__main__':
    main()
