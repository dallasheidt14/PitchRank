#!/usr/bin/env python3
"""
Verify team ID mappings after import
"""
import logging
from pathlib import Path
import sys
import argparse

sys.path.append(str(Path(__file__).parent.parent))

from supabase import create_client
import os
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

logger = logging.getLogger(__name__)
console = Console()
load_dotenv()


def verify_mappings(provider_code: str):
    """Verify team mappings by type"""
    
    supabase_url = os.getenv('SUPABASE_URL')
    supabase_key = os.getenv('SUPABASE_SERVICE_ROLE_KEY')
    
    if not supabase_url or not supabase_key:
        console.print("[red]Error: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set in .env[/red]")
        sys.exit(1)
    
    supabase = create_client(supabase_url, supabase_key)
    
    # Get provider UUID
    try:
        provider_result = supabase.table('providers').select('id, name').eq(
            'code', provider_code
        ).single().execute()
        provider_id = provider_result.data['id']
        provider_name = provider_result.data['name']
    except Exception as e:
        console.print(f"[red]Error: Provider '{provider_code}' not found: {e}[/red]")
        sys.exit(1)
    
    # Get mapping statistics by match type
    try:
        # Get all mappings for this provider
        all_mappings = supabase.table('team_alias_map').select(
            'match_method, match_confidence'
        ).eq(
            'provider_id', provider_id
        ).execute()
        
        # Count by match type
        stats = {}
        for mapping in all_mappings.data:
            match_type = mapping.get('match_method', 'unknown')
            if match_type not in stats:
                stats[match_type] = {
                    'count': 0,
                    'confidences': []
                }
            stats[match_type]['count'] += 1
            stats[match_type]['confidences'].append(mapping.get('match_confidence', 0.0))
        
        # Display statistics
        console.print(f"\n[bold]Mapping Statistics for {provider_name} ({provider_code}):[/bold]")
        table = Table(title="Match Type Statistics")
        table.add_column("Match Type", style="cyan")
        table.add_column("Count", style="green", justify="right")
        table.add_column("Avg Confidence", style="yellow", justify="right")
        
        total = 0
        for match_type, data in sorted(stats.items()):
            count = data['count']
            total += count
            avg_conf = sum(data['confidences']) / len(data['confidences']) if data['confidences'] else 0.0
            table.add_row(
                match_type,
                f"{count:,}",
                f"{avg_conf:.3f}"
            )
        
        table.add_row("", "-" * 10, "-" * 10)
        table.add_row("[bold]TOTAL[/bold]", f"[bold]{total:,}[/bold]", "")
        console.print(table)
        
        # Show sample direct ID mappings
        console.print("\n[bold]Sample Direct ID Mappings (first 10):[/bold]")
        direct_mappings = supabase.table('team_alias_map').select(
            'provider_team_id, team_id_master, match_confidence'
        ).eq(
            'provider_id', provider_id
        ).eq(
            'match_method', 'direct_id'
        ).limit(10).execute()
        
        if direct_mappings.data:
            mapping_table = Table()
            mapping_table.add_column("Provider Team ID", style="cyan")
            mapping_table.add_column("Master Team ID", style="green")
            mapping_table.add_column("Confidence", style="yellow", justify="right")
            
            # Get team names for display
            for mapping in direct_mappings.data:
                team_result = supabase.table('teams').select(
                    'team_name, age_group, gender'
                ).eq(
                    'team_id_master', mapping['team_id_master']
                ).maybe_single().execute()
                
                if team_result.data:
                    team = team_result.data
                    team_display = f"{team['team_name']} ({team['age_group']} {team['gender']})"
                else:
                    team_display = mapping['team_id_master']
                
                mapping_table.add_row(
                    mapping['provider_team_id'],
                    team_display,
                    f"{mapping['match_confidence']:.2f}"
                )
            
            console.print(mapping_table)
        else:
            console.print("[yellow]No direct ID mappings found[/yellow]")
        
        # Check for teams in games without mappings
        console.print("\n[bold]Checking for unmapped teams in games...[/bold]")
        console.print("[yellow]Note: This requires a database query. Run the SQL below manually.[/yellow]")
        console.print("\n[dim]SQL Query to find unmapped teams:[/dim]")
        
        unmapped_query = f"""
SELECT DISTINCT team_id, COUNT(*) as game_count
FROM (
    SELECT home_provider_id as team_id FROM games WHERE provider_id = '{provider_id}'
    UNION ALL
    SELECT away_provider_id as team_id FROM games WHERE provider_id = '{provider_id}'
) t
WHERE NOT EXISTS (
    SELECT 1 FROM team_alias_map tam 
    WHERE tam.provider_id = '{provider_id}' 
    AND tam.provider_team_id = t.team_id
)
GROUP BY team_id
ORDER BY game_count DESC
LIMIT 20;
"""
        console.print(f"[dim]{unmapped_query}[/dim]")
        
    except Exception as e:
        logger.error(f"Error verifying mappings: {e}")
        console.print(f"[red]Error: {e}[/red]")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description='Verify team mappings')
    parser.add_argument('provider', help='Provider code (e.g., gotsport)')
    
    args = parser.parse_args()
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(message)s'
    )
    
    verify_mappings(args.provider)


if __name__ == '__main__':
    main()

