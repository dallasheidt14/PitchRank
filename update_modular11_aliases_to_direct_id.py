#!/usr/bin/env python3
"""
Update all Modular11 aliases from 'import' to 'direct_id' where provider_team_id exists.

This script updates aliases that have real provider team IDs (not hash-based) to use
'direct_id' match method for faster Tier 1 matching.
"""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from supabase import create_client
from rich.console import Console
from rich.progress import track
from rich.table import Table

# Load environment variables
env_local = Path('.env.local')
if env_local.exists():
    load_dotenv(env_local, override=True)
else:
    load_dotenv()

supabase_url = os.getenv('SUPABASE_URL') or os.getenv('NEXT_PUBLIC_SUPABASE_URL')
supabase_key = os.getenv('SUPABASE_SERVICE_ROLE_KEY') or os.getenv('SUPABASE_SERVICE_KEY') or os.getenv('SUPABASE_KEY')

if not supabase_url or not supabase_key:
    print("Error: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set")
    sys.exit(1)

supabase = create_client(supabase_url, supabase_key)
console = Console()

# Get Modular11 provider ID
providers_result = supabase.table('providers').select('id').eq('code', 'modular11').execute()
if not providers_result.data:
    console.print("[red]Error: Modular11 provider not found[/red]")
    sys.exit(1)

modular11_provider_id = providers_result.data[0]['id']

def is_hash_based_id(provider_team_id: str) -> bool:
    """
    Check if provider_team_id looks like a hash (system-generated) vs real provider ID.
    
    Real Modular11 IDs are numeric (like "456") or numeric with suffixes (like "456_U14_AD").
    Hash-based IDs are long hex strings (like "a1b2c3d4e5f6...").
    """
    if not provider_team_id:
        return True
    
    # Remove common suffixes to check base ID
    base_id = provider_team_id.split('_')[0]
    
    # Real Modular11 IDs are numeric (club IDs)
    # Hash-based IDs are long hex strings (32+ chars) or contain non-numeric chars
    if len(base_id) > 16:
        return True  # Too long to be a real club ID
    
    # Check if base ID is numeric (real provider ID)
    try:
        int(base_id)
        return False  # Real numeric ID
    except ValueError:
        return True  # Not numeric, probably hash-based

def main():
    console.print("\n[bold cyan]=" * 80)
    console.print("[bold cyan]UPDATE MODULAR11 ALIASES: import → direct_id[/bold cyan]")
    console.print("[bold cyan]=" * 80)
    
    # Step 1: Find all aliases with match_method='import'
    console.print("\n[bold]Step 1:[/bold] Finding aliases with match_method='import'...")
    
    all_import_aliases = []
    offset = 0
    batch_size = 1000
    
    while True:
        result = supabase.table('team_alias_map').select(
            'id, provider_team_id, team_id_master, match_method, match_confidence'
        ).eq('provider_id', modular11_provider_id).eq(
            'match_method', 'import'
        ).eq('review_status', 'approved').range(offset, offset + batch_size - 1).execute()
        
        if not result.data:
            break
        
        all_import_aliases.extend(result.data)
        
        if len(result.data) < batch_size:
            break
        
        offset += batch_size
    
    console.print(f"[green]Found {len(all_import_aliases)} aliases with match_method='import'[/green]")
    
    # Step 2: Filter to only those with real provider IDs (not hash-based)
    console.print("\n[bold]Step 2:[/bold] Filtering to aliases with real provider IDs...")
    
    aliases_to_update = []
    hash_based_count = 0
    
    for alias in all_import_aliases:
        provider_team_id = str(alias['provider_team_id'])
        
        if is_hash_based_id(provider_team_id):
            hash_based_count += 1
        else:
            aliases_to_update.append(alias)
    
    console.print(f"[green]Aliases to update: {len(aliases_to_update)}[/green]")
    console.print(f"[yellow]Hash-based (skipping): {hash_based_count}[/yellow]")
    
    if not aliases_to_update:
        console.print("\n[yellow]No aliases to update![/yellow]")
        return
    
    # Step 3: Show sample of what will be updated
    console.print("\n[bold]Step 3:[/bold] Sample of aliases to update (first 10):")
    
    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("Provider Team ID", style="cyan")
    table.add_column("Team Name", style="green")
    table.add_column("Confidence", style="yellow")
    
    for alias in aliases_to_update[:10]:
        # Get team name
        team_result = supabase.table('teams').select('team_name').eq(
            'team_id_master', alias['team_id_master']
        ).single().execute()
        
        team_name = team_result.data['team_name'] if team_result.data else 'Unknown'
        
        table.add_row(
            alias['provider_team_id'],
            team_name[:50],  # Truncate long names
            str(alias['match_confidence'])
        )
    
    console.print(table)
    
    if len(aliases_to_update) > 10:
        console.print(f"[dim]... and {len(aliases_to_update) - 10} more[/dim]")
    
    # Step 4: Confirm update
    console.print(f"\n[bold yellow]Ready to update {len(aliases_to_update)} aliases[/bold yellow]")
    console.print("[yellow]This will change match_method from 'import' to 'direct_id'[/yellow]")
    
    # Check for flags
    dry_run = '--dry-run' in sys.argv
    auto_yes = '--yes' in sys.argv or '-y' in sys.argv
    
    if dry_run:
        console.print("\n[bold cyan]DRY RUN MODE - No changes will be made[/bold cyan]")
    elif auto_yes:
        console.print("\n[bold green]Auto-confirming update (--yes flag)[/bold green]")
    else:
        response = input("\nProceed with update? (yes/no): ")
        if response.lower() != 'yes':
            console.print("[yellow]Cancelled.[/yellow]")
            return
    
    # Step 5: Update aliases
    console.print("\n[bold]Step 4:[/bold] Updating aliases...")
    
    updated_count = 0
    failed_count = 0
    errors = []
    
    for alias in track(aliases_to_update, description="Updating..."):
        if dry_run:
            updated_count += 1
            continue
        
        try:
            result = supabase.table('team_alias_map').update({
                'match_method': 'direct_id'
            }).eq('id', alias['id']).execute()
            
            if result.data:
                updated_count += 1
            else:
                failed_count += 1
                errors.append(f"{alias['provider_team_id']}: No data returned")
        except Exception as e:
            failed_count += 1
            errors.append(f"{alias['provider_team_id']}: {str(e)}")
    
    # Step 6: Report results
    console.print("\n[bold cyan]=" * 80)
    console.print("[bold cyan]RESULTS[/bold cyan]")
    console.print("[bold cyan]=" * 80)
    
    if dry_run:
        console.print(f"\n[green]Would update: {updated_count} aliases[/green]")
    else:
        console.print(f"\n[green]✅ Updated: {updated_count} aliases[/green]")
        if failed_count > 0:
            console.print(f"[red]❌ Failed: {failed_count} aliases[/red]")
            if errors:
                console.print("\n[yellow]Errors (first 5):[/yellow]")
                for error in errors[:5]:
                    console.print(f"  - {error}")
                if len(errors) > 5:
                    console.print(f"  ... and {len(errors) - 5} more")
    
    # Step 7: Verify a few updates
    if not dry_run and updated_count > 0:
        console.print("\n[bold]Step 5:[/bold] Verifying updates...")
        
        # Check a few random aliases
        sample_ids = [alias['id'] for alias in aliases_to_update[:5]]
        
        for alias_id in sample_ids:
            verify_result = supabase.table('team_alias_map').select(
                'provider_team_id, match_method'
            ).eq('id', alias_id).execute()
            
            if verify_result.data:
                alias = verify_result.data[0]
                if alias['match_method'] == 'direct_id':
                    console.print(f"  [green]✅[/green] {alias['provider_team_id']}: {alias['match_method']}")
                else:
                    console.print(f"  [red]❌[/red] {alias['provider_team_id']}: {alias['match_method']} (should be direct_id)")
    
    console.print("\n[bold cyan]=" * 80)
    console.print("[bold cyan]DONE![/bold cyan]")
    console.print("[bold cyan]=" * 80)
    
    if not dry_run:
        console.print("\n[yellow]Note:[/yellow] Future imports will now use Tier 1 (fast) matching for these teams!")
        console.print("[yellow]Note:[/yellow] Games that were already incorrectly matched will need to be fixed separately.")

if __name__ == '__main__':
    main()

