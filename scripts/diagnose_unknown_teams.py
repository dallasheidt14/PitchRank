#!/usr/bin/env python3
"""
Diagnostic script to identify and fix "Unknown" team issues
"""
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

from supabase import create_client
import os
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box

load_dotenv()
console = Console()

def main():
    """Run diagnostics on unknown team issues"""

    supabase = create_client(
        os.getenv('SUPABASE_URL'),
        os.getenv('SUPABASE_SERVICE_ROLE_KEY')
    )

    console.print(Panel.fit(
        "[bold cyan]Unknown Team Diagnostics[/bold cyan]\n"
        "This script will identify why teams are showing as 'Unknown'",
        box=box.DOUBLE
    ))

    # 1. Check for games with NULL team IDs
    console.print("\n[bold yellow]1. Checking for unmatched games...[/bold yellow]")
    result = supabase.rpc('exec_sql', {
        'query': """
            SELECT
                COUNT(*) as total_games,
                COUNT(home_team_master_id) as home_matched,
                COUNT(away_team_master_id) as away_matched,
                COUNT(CASE WHEN home_team_master_id IS NULL THEN 1 END) as null_home,
                COUNT(CASE WHEN away_team_master_id IS NULL THEN 1 END) as null_away
            FROM games
        """
    }).execute()

    if result.data:
        stats = result.data[0] if isinstance(result.data, list) else result.data

        table = Table(title="Game Matching Statistics", box=box.SIMPLE)
        table.add_column("Metric", style="cyan")
        table.add_column("Count", justify="right", style="green")

        table.add_row("Total Games", str(stats.get('total_games', 0)))
        table.add_row("Home Teams Matched", str(stats.get('home_matched', 0)))
        table.add_row("Away Teams Matched", str(stats.get('away_matched', 0)))
        table.add_row("❌ NULL Home Teams", f"[red]{stats.get('null_home', 0)}[/red]")
        table.add_row("❌ NULL Away Teams", f"[red]{stats.get('null_away', 0)}[/red]")

        console.print(table)

        if stats.get('null_home', 0) > 0 or stats.get('null_away', 0) > 0:
            console.print("\n[bold red]⚠️  Found games with unmatched teams![/bold red]")

    # 2. Check for pending aliases
    console.print("\n[bold yellow]2. Checking for pending team aliases...[/bold yellow]")
    result = supabase.table('team_alias_map').select(
        'provider_team_id, review_status, match_confidence, match_method'
    ).neq('review_status', 'approved').execute()

    if result.data and len(result.data) > 0:
        table = Table(title="Pending/Unapproved Aliases", box=box.SIMPLE)
        table.add_column("Provider Team ID", style="cyan")
        table.add_column("Status", style="yellow")
        table.add_column("Confidence", justify="right")
        table.add_column("Method")

        for alias in result.data[:10]:  # Show first 10
            table.add_row(
                alias['provider_team_id'],
                alias['review_status'],
                f"{alias['match_confidence']:.2f}",
                alias['match_method']
            )

        console.print(table)
        console.print(f"\n[bold yellow]Found {len(result.data)} unapproved aliases[/bold yellow]")
        console.print("[dim]These won't be used for matching until approved[/dim]")
    else:
        console.print("[green]✓ All aliases are approved[/green]")

    # 3. Check for orphaned team_id_master references
    console.print("\n[bold yellow]3. Checking for orphaned team references...[/bold yellow]")

    # This would need a custom SQL query - simplified version
    result = supabase.table('team_alias_map').select(
        'team_id_master, provider_team_id'
    ).limit(1000).execute()

    if result.data:
        orphaned = []
        for alias in result.data:
            team_check = supabase.table('teams').select('team_id_master').eq(
                'team_id_master', alias['team_id_master']
            ).execute()

            if not team_check.data or len(team_check.data) == 0:
                orphaned.append(alias)

        if orphaned:
            table = Table(title="Orphaned Alias References", box=box.SIMPLE)
            table.add_column("Provider Team ID", style="cyan")
            table.add_column("Missing Master ID", style="red")

            for alias in orphaned[:10]:
                table.add_row(
                    alias['provider_team_id'],
                    alias['team_id_master']
                )

            console.print(table)
            console.print(f"\n[bold red]Found {len(orphaned)} aliases pointing to non-existent teams[/bold red]")
        else:
            console.print("[green]✓ All aliases reference valid teams[/green]")

    # 4. Show sample of unmatched games
    console.print("\n[bold yellow]4. Sample of unmatched games...[/bold yellow]")
    result = supabase.table('games').select(
        'game_uid, game_date, home_provider_id, away_provider_id, home_team_master_id, away_team_master_id'
    ).or_(
        'home_team_master_id.is.null,away_team_master_id.is.null'
    ).limit(5).execute()

    if result.data and len(result.data) > 0:
        table = Table(title="Sample Unmatched Games", box=box.SIMPLE)
        table.add_column("Date", style="cyan")
        table.add_column("Home Provider ID")
        table.add_column("Away Provider ID")
        table.add_column("Home Matched?", justify="center")
        table.add_column("Away Matched?", justify="center")

        for game in result.data:
            table.add_row(
                game['game_date'] or 'N/A',
                game['home_provider_id'] or 'N/A',
                game['away_provider_id'] or 'N/A',
                "✓" if game['home_team_master_id'] else "[red]✗[/red]",
                "✓" if game['away_team_master_id'] else "[red]✗[/red]"
            )

        console.print(table)
    else:
        console.print("[green]✓ No unmatched games found[/green]")

    # 5. Recommendations
    console.print("\n[bold cyan]Recommendations:[/bold cyan]")
    console.print("""
[yellow]To approve pending aliases:[/yellow]
    python scripts/review_aliases.py

[yellow]To manually approve all high-confidence aliases:[/yellow]
    UPDATE team_alias_map
    SET review_status = 'approved'
    WHERE review_status = 'pending' AND match_confidence >= 0.85;

[yellow]To re-import games after approving aliases:[/yellow]
    python scripts/import_games_enhanced.py <your_games_file.csv> <provider>

[yellow]To create a manual alias for a specific team:[/yellow]
    See: /home/user/PitchRank/UNKNOWN_TEAMS_ANALYSIS.md (Option 3)
    """)

if __name__ == "__main__":
    main()
