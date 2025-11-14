#!/usr/bin/env python3
"""
Backfill rankings_full table from existing current_rankings data
This script migrates existing ranking data to the comprehensive rankings_full table
"""
import asyncio
import sys
from pathlib import Path
from datetime import datetime

sys.path.append(str(Path(__file__).parent.parent))

from supabase import create_client
import os
import pandas as pd
from dotenv import load_dotenv
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

console = Console()

# Load environment variables
env_local = Path('.env.local')
if env_local.exists():
    load_dotenv(env_local, override=True)
else:
    load_dotenv()


async def backfill_rankings_full():
    """Backfill rankings_full table from current_rankings"""
    
    # Initialize Supabase client
    supabase_url = os.getenv('SUPABASE_URL')
    supabase_key = os.getenv('SUPABASE_SERVICE_ROLE_KEY')
    
    if not supabase_url or not supabase_key:
        console.print("[red]Error: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set in .env[/red]")
        sys.exit(1)
    
    supabase = create_client(supabase_url, supabase_key)
    
    console.print("\n[bold green]Backfilling rankings_full from current_rankings[/bold green]\n")
    
    try:
        # Fetch all current_rankings
        console.print("[dim]Fetching current_rankings data...[/dim]")
        current_rankings_result = supabase.table('current_rankings').select('*').execute()
        
        if not current_rankings_result.data:
            console.print("[yellow]No current_rankings data found[/yellow]")
            return
        
        current_rankings_df = pd.DataFrame(current_rankings_result.data)
        console.print(f"[green]Found {len(current_rankings_df)} teams in current_rankings[/green]")
        
        # Fetch team metadata
        team_ids = current_rankings_df['team_id'].tolist()
        console.print(f"[dim]Fetching metadata for {len(team_ids)} teams...[/dim]")
        
        teams_meta_data = []
        batch_size = 150
        for i in range(0, len(team_ids), batch_size):
            batch = team_ids[i:i+batch_size]
            try:
                teams_result = supabase.table('teams').select(
                    'team_id_master, age_group, gender, state_code'
                ).in_('team_id_master', batch).execute()
                if teams_result.data:
                    teams_meta_data.extend(teams_result.data)
            except Exception as e:
                console.print(f"[yellow]Warning: Team metadata batch failed: {e}[/yellow]")
                continue
        
        if not teams_meta_data:
            console.print("[red]Error: Could not fetch team metadata[/red]")
            return
        
        teams_meta_df = pd.DataFrame(teams_meta_data)
        console.print(f"[green]Fetched metadata for {len(teams_meta_df)} teams[/green]")
        
        # Merge team metadata with current_rankings
        rankings_full_df = current_rankings_df.merge(
            teams_meta_df,
            left_on='team_id',
            right_on='team_id_master',
            how='left'
        )
        
        # Prepare records for rankings_full
        # Map existing fields and set missing fields to NULL
        records = []
        for _, row in rankings_full_df.iterrows():
            record = {
                'team_id': str(row['team_id']),
                'age_group': row.get('age_group'),
                'gender': row.get('gender'),
                'state_code': row.get('state_code'),
                'national_power_score': float(row.get('national_power_score', 0.0)),
                'global_power_score': float(row['global_power_score']) if pd.notna(row.get('global_power_score')) else None,
                'games_played': int(row.get('games_played', 0)),
                'wins': int(row.get('wins', 0)),
                'losses': int(row.get('losses', 0)),
                'draws': int(row.get('draws', 0)),
                'goals_for': int(row.get('goals_for', 0)),
                'goals_against': int(row.get('goals_against', 0)),
                'win_percentage': float(row['win_percentage']) if pd.notna(row.get('win_percentage')) else None,
                'strength_of_schedule': float(row['strength_of_schedule']) if pd.notna(row.get('strength_of_schedule')) else None,
                'national_rank': int(row['national_rank']) if pd.notna(row.get('national_rank')) else None,
                'state_rank': int(row['state_rank']) if pd.notna(row.get('state_rank')) else None,
                'last_calculated': row.get('last_calculated'),
                'last_game': pd.to_datetime(row['last_game_date']) if pd.notna(row.get('last_game_date')) else None,
            }
            
            # Set power_score_final (fallback: global > national)
            record['power_score_final'] = (
                record['global_power_score'] 
                if record['global_power_score'] is not None 
                else record['national_power_score']
            )
            
            # All v53E + Layer 13 fields will be NULL (to be populated by next rankings calculation)
            # This is expected - the backfill only migrates what exists in current_rankings
            
            records.append(record)
        
        # Save to rankings_full in batches
        console.print(f"\n[dim]Saving {len(records)} records to rankings_full...[/dim]")
        
        batch_size = 1000
        total_saved = 0
        failed_batches = []
        
        for i in range(0, len(records), batch_size):
            batch = records[i:i + batch_size]
            batch_num = (i // batch_size) + 1
            total_batches = (len(records) + batch_size - 1) // batch_size
            
            try:
                # Use upsert (insert with conflict resolution on team_id)
                result = supabase.table('rankings_full').upsert(
                    batch,
                    on_conflict='team_id'
                ).execute()
                
                if result.data:
                    total_saved += len(result.data)
                
                console.print(f"[dim]Batch {batch_num}/{total_batches}: {len(batch)} records saved[/dim]")
            except Exception as e:
                console.print(f"[red]Error saving batch {batch_num}: {e}[/red]")
                failed_batches.append((batch_num, batch))
        
        # Retry failed batches
        if failed_batches:
            console.print(f"\n[yellow]Retrying {len(failed_batches)} failed batches...[/yellow]")
            for batch_num, batch in failed_batches:
                try:
                    result = supabase.table('rankings_full').upsert(
                        batch,
                        on_conflict='team_id'
                    ).execute()
                    if result.data:
                        total_saved += len(result.data)
                    console.print(f"[green]Batch {batch_num} saved on retry[/green]")
                except Exception as e:
                    console.print(f"[red]Batch {batch_num} failed after retry: {e}[/red]")
        
        console.print(f"\n[green]✅ Backfill complete: {total_saved} records saved to rankings_full[/green]")
        console.print("[yellow]Note: v53E + Layer 13 fields will be NULL until next rankings calculation[/yellow]")
        console.print("[yellow]Run calculate_rankings.py to populate all comprehensive fields[/yellow]")
        
    except Exception as e:
        console.print(f"\n[red]Backfill failed: {e}[/red]")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    asyncio.run(backfill_rankings_full())

