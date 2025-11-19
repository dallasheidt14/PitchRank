#!/usr/bin/env python3
"""
Quick fix script for unknown team issues
"""
import sys
import argparse
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

from supabase import create_client
import os
from dotenv import load_dotenv
from rich.console import Console
from rich.prompt import Confirm
from datetime import datetime

load_dotenv()
console = Console()

def approve_pending_aliases(supabase, min_confidence: float = 0.85, dry_run: bool = False):
    """Approve pending aliases above a confidence threshold"""

    # Get pending aliases
    result = supabase.table('team_alias_map').select('*').eq(
        'review_status', 'pending'
    ).gte('match_confidence', min_confidence).execute()

    if not result.data or len(result.data) == 0:
        console.print(f"[yellow]No pending aliases found with confidence >= {min_confidence}[/yellow]")
        return 0

    console.print(f"\n[cyan]Found {len(result.data)} pending aliases with confidence >= {min_confidence}:[/cyan]")

    for alias in result.data[:5]:  # Show first 5
        console.print(f"  • {alias['provider_team_id']} → confidence: {alias['match_confidence']:.2f}")

    if len(result.data) > 5:
        console.print(f"  ... and {len(result.data) - 5} more")

    if dry_run:
        console.print("\n[yellow]DRY RUN - No changes made[/yellow]")
        return len(result.data)

    if not Confirm.ask(f"\nApprove all {len(result.data)} aliases?"):
        console.print("[yellow]Cancelled[/yellow]")
        return 0

    # Approve all
    approved_count = 0
    for alias in result.data:
        try:
            supabase.table('team_alias_map').update({
                'review_status': 'approved',
                'reviewed_at': datetime.now().isoformat()
            }).eq('id', alias['id']).execute()
            approved_count += 1
        except Exception as e:
            console.print(f"[red]Error approving {alias['provider_team_id']}: {e}[/red]")

    console.print(f"\n[green]✓ Approved {approved_count} aliases[/green]")
    return approved_count


def show_unknown_team_details(supabase, provider_team_id: str = None):
    """Show details about a specific unknown team"""

    if provider_team_id:
        # Check if this team ID exists in aliases
        result = supabase.table('team_alias_map').select('*').eq(
            'provider_team_id', provider_team_id
        ).execute()

        if result.data and len(result.data) > 0:
            alias = result.data[0]
            console.print(f"\n[cyan]Team Alias Found:[/cyan]")
            console.print(f"  Provider Team ID: {alias['provider_team_id']}")
            console.print(f"  Master Team ID: {alias['team_id_master']}")
            console.print(f"  Review Status: [yellow]{alias['review_status']}[/yellow]")
            console.print(f"  Confidence: {alias['match_confidence']:.2f}")
            console.print(f"  Method: {alias['match_method']}")

            if alias['review_status'] == 'pending':
                console.print("\n[yellow]⚠️  This alias is PENDING approval![/yellow]")
                console.print("[dim]Games won't match until it's approved[/dim]")

                if Confirm.ask("\nApprove this alias now?"):
                    supabase.table('team_alias_map').update({
                        'review_status': 'approved',
                        'reviewed_at': datetime.now().isoformat()
                    }).eq('id', alias['id']).execute()
                    console.print("[green]✓ Approved![/green]")
            else:
                console.print(f"\n[green]✓ Alias is already approved[/green]")

                # Check if team exists
                team_result = supabase.table('teams').select('*').eq(
                    'team_id_master', alias['team_id_master']
                ).execute()

                if not team_result.data or len(team_result.data) == 0:
                    console.print(f"\n[red]⚠️  Problem: Master team {alias['team_id_master']} doesn't exist![/red]")
                    console.print("[yellow]The alias points to a non-existent team[/yellow]")
                else:
                    team = team_result.data[0]
                    console.print(f"\n[green]✓ Master team found:[/green]")
                    console.print(f"  Team Name: {team['team_name']}")
                    console.print(f"  Club: {team.get('club_name', 'N/A')}")
                    console.print(f"  Age Group: {team.get('age_group', 'N/A')}")
                    console.print(f"  Gender: {team.get('gender', 'N/A')}")
        else:
            console.print(f"\n[yellow]No alias found for provider team ID: {provider_team_id}[/yellow]")
            console.print("\n[cyan]This team needs to be:[/cyan]")
            console.print("  1. Imported as a master team (scripts/import_teams_enhanced.py)")
            console.print("  2. OR manually aliased to an existing team")


def list_all_unknown_teams(supabase):
    """List all teams that are causing 'Unknown' to appear"""

    console.print("\n[cyan]Finding all unmatched teams...[/cyan]")

    # Get games with NULL team IDs
    result = supabase.table('games').select(
        'home_provider_id, away_provider_id, home_team_master_id, away_team_master_id, game_date'
    ).or_(
        'home_team_master_id.is.null,away_team_master_id.is.null'
    ).order('game_date', desc=True).limit(100).execute()

    if not result.data or len(result.data) == 0:
        console.print("[green]✓ No unmatched games found![/green]")
        return

    # Collect unique provider IDs that are unmatched
    unmatched_provider_ids = set()
    for game in result.data:
        if not game['home_team_master_id'] and game['home_provider_id']:
            unmatched_provider_ids.add(game['home_provider_id'])
        if not game['away_team_master_id'] and game['away_provider_id']:
            unmatched_provider_ids.add(game['away_provider_id'])

    console.print(f"\n[yellow]Found {len(unmatched_provider_ids)} unique unmatched provider team IDs:[/yellow]")

    for idx, provider_id in enumerate(list(unmatched_provider_ids)[:20], 1):
        # Check if alias exists
        alias_result = supabase.table('team_alias_map').select('review_status').eq(
            'provider_team_id', provider_id
        ).execute()

        if alias_result.data and len(alias_result.data) > 0:
            status = alias_result.data[0]['review_status']
            console.print(f"  {idx}. {provider_id} - [yellow]Alias: {status}[/yellow]")
        else:
            console.print(f"  {idx}. {provider_id} - [red]No alias[/red]")

    if len(unmatched_provider_ids) > 20:
        console.print(f"  ... and {len(unmatched_provider_ids) - 20} more")


def main():
    parser = argparse.ArgumentParser(description='Fix unknown team issues')
    parser.add_argument('--approve-pending', action='store_true',
                        help='Approve all pending aliases above confidence threshold')
    parser.add_argument('--min-confidence', type=float, default=0.85,
                        help='Minimum confidence for auto-approval (default: 0.85)')
    parser.add_argument('--dry-run', action='store_true',
                        help='Show what would be done without making changes')
    parser.add_argument('--team-id', type=str,
                        help='Show details for a specific provider team ID')
    parser.add_argument('--list-all', action='store_true',
                        help='List all unknown/unmatched teams')

    args = parser.parse_args()

    supabase = create_client(
        os.getenv('SUPABASE_URL'),
        os.getenv('SUPABASE_SERVICE_ROLE_KEY')
    )

    if args.approve_pending:
        approve_pending_aliases(supabase, args.min_confidence, args.dry_run)
    elif args.team_id:
        show_unknown_team_details(supabase, args.team_id)
    elif args.list_all:
        list_all_unknown_teams(supabase)
    else:
        # Default: show help
        parser.print_help()
        console.print("\n[cyan]Quick actions:[/cyan]")
        console.print("  --list-all              Show all unmatched teams")
        console.print("  --approve-pending       Approve high-confidence aliases")
        console.print("  --team-id <ID>          Check specific team")


if __name__ == "__main__":
    main()
