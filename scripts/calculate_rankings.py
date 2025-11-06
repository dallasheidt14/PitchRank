#!/usr/bin/env python3
"""
Calculate team rankings using v53e engine with optional ML layer
"""
import asyncio
import argparse
import sys
from pathlib import Path
from datetime import datetime

sys.path.append(str(Path(__file__).parent.parent))

from supabase import create_client
import os
import pandas as pd
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

from src.rankings.calculator import compute_rankings_with_ml, compute_rankings_v53e_only
from src.etl.v53e import V53EConfig
from src.rankings.layer13_predictive_adjustment import Layer13Config
from src.rankings.data_adapter import v53e_to_supabase_format

console = Console()
load_dotenv()


async def save_rankings_to_supabase(supabase_client, teams_df):
    """Save rankings to current_rankings table"""
    if teams_df.empty:
        console.print("[yellow]No rankings to save[/yellow]")
        return
    
    # Convert to Supabase format
    rankings_df = v53e_to_supabase_format(teams_df)
    
    if rankings_df.empty:
        console.print("[yellow]No rankings to save after conversion[/yellow]")
        return
    
    # Prepare records for upsert
    records = []
    for _, row in rankings_df.iterrows():
        try:
            record = {
                'team_id': str(row['team_id']),
                'national_power_score': float(row.get('national_power_score', 0.0)),
            }
            
            # Handle national_rank (may be None)
            if pd.notna(row.get('national_rank')):
                record['national_rank'] = int(row.get('national_rank'))
            else:
                record['national_rank'] = None
            
            # Optional fields (may not exist in v53e output)
            record['games_played'] = int(row.get('gp', 0)) if pd.notna(row.get('gp')) else 0
            record['wins'] = int(row.get('wins', 0)) if pd.notna(row.get('wins')) else 0
            record['losses'] = int(row.get('losses', 0)) if pd.notna(row.get('losses')) else 0
            record['draws'] = int(row.get('draws', 0)) if pd.notna(row.get('draws')) else 0
            record['goals_for'] = int(row.get('goals_for', 0)) if pd.notna(row.get('goals_for')) else 0
            record['goals_against'] = int(row.get('goals_against', 0)) if pd.notna(row.get('goals_against')) else 0
            
            # Calculate win percentage
            if record['games_played'] > 0:
                record['win_percentage'] = float(record['wins'] / record['games_played'])
            else:
                record['win_percentage'] = None
            
            records.append(record)
        except Exception as e:
            console.print(f"[yellow]Warning: Skipping row due to error: {e}[/yellow]")
            continue
    
    # Upsert to current_rankings
    if records:
        try:
            # Use upsert (insert with conflict resolution)
            # First, try to delete all existing rankings
            try:
                supabase_client.table('current_rankings').delete().neq('team_id', '00000000-0000-0000-0000-000000000000').execute()
            except:
                pass  # If delete fails, continue with insert
            
            # Insert new rankings in batches
            batch_size = 1000
            total_inserted = 0
            for i in range(0, len(records), batch_size):
                batch = records[i:i + batch_size]
                result = supabase_client.table('current_rankings').insert(batch).execute()
                if result.data:
                    total_inserted += len(result.data)
            
            console.print(f"[green]Saved {total_inserted} rankings to current_rankings table[/green]")
        except Exception as e:
            console.print(f"[red]Error saving rankings: {e}[/red]")
            raise


async def main():
    parser = argparse.ArgumentParser(description='Calculate team rankings')
    parser.add_argument('--ml', action='store_true', help='Enable ML predictive adjustment layer')
    parser.add_argument('--provider', type=str, default=None, help='Filter by provider code (gotsport, tgs, usclub)')
    parser.add_argument('--lookback-days', type=int, default=365, help='Days to look back for rankings (default: 365)')
    parser.add_argument('--age-group', type=str, default=None, help='Filter by age group (u10, u11, etc.)')
    parser.add_argument('--gender', type=str, default=None, help='Filter by gender (Male, Female)')
    parser.add_argument('--dry-run', action='store_true', help='Calculate rankings without saving to database')
    
    args = parser.parse_args()
    
    # Initialize Supabase client
    supabase_url = os.getenv('SUPABASE_URL')
    supabase_key = os.getenv('SUPABASE_SERVICE_ROLE_KEY')
    
    if not supabase_url or not supabase_key:
        console.print("[red]Error: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set in .env[/red]")
        sys.exit(1)
    
    supabase = create_client(supabase_url, supabase_key)
    
    # Run rankings calculation
    try:
        mode_text = "ML-Enhanced" if args.ml else "v53e Only"
        console.print(f"[bold green]Calculating {mode_text} Rankings[/bold green]")
        console.print(f"  Lookback days: {args.lookback_days}")
        if args.provider:
            console.print(f"  Provider filter: {args.provider}")
        
        if args.ml:
            result = await compute_rankings_with_ml(
                supabase_client=supabase,
                today=None,
                fetch_from_supabase=True,
                lookback_days=args.lookback_days,
                provider_filter=args.provider,
            )
        else:
            result = await compute_rankings_v53e_only(
                supabase_client=supabase,
                today=None,
                fetch_from_supabase=True,
                lookback_days=args.lookback_days,
                provider_filter=args.provider,
            )
        
        teams_df = result["teams"]
        
        if teams_df.empty:
            console.print("[yellow]No teams found for ranking[/yellow]")
            return
        
        # Filter by age group and gender if specified
        if args.age_group:
            # Convert 'u10' to '10' format
            age_filter = args.age_group.replace('u', '').replace('U', '')
            teams_df = teams_df[teams_df['age'] == age_filter]
        
        if args.gender:
            teams_df = teams_df[teams_df['gender'] == args.gender]
        
        # Display summary
        console.print(f"\n[bold green]Rankings Calculated Successfully![/bold green]")
        console.print(f"\n[bold]Summary:[/bold]")
        console.print(f"  Total teams: {len(teams_df):,}")
        
        if 'powerscore_ml' in teams_df.columns:
            console.print(f"  Using ML-enhanced PowerScore")
            power_col = 'powerscore_ml'
            rank_col = 'rank_in_cohort_ml'
        elif 'powerscore_adj' in teams_df.columns:
            console.print(f"  Using adjusted PowerScore")
            power_col = 'powerscore_adj'
            rank_col = 'rank_in_cohort'
        else:
            power_col = 'powerscore_core'
            rank_col = 'rank_in_cohort'
        
        # Show top 10 teams
        if not teams_df.empty:
            top_teams = teams_df.nlargest(10, power_col)
            table = Table(title="Top 10 Teams")
            table.add_column("Rank", style="cyan")
            table.add_column("Team ID", style="magenta")
            table.add_column("Age", style="yellow")
            table.add_column("Gender", style="yellow")
            table.add_column("PowerScore", style="green", justify="right")
            
            for _, team in top_teams.iterrows():
                table.add_row(
                    str(int(team[rank_col])),
                    str(team['team_id'])[:8] + "...",
                    str(team['age']),
                    str(team['gender']),
                    f"{team[power_col]:.4f}"
                )
            
            console.print("\n")
            console.print(table)
        
        # Save to database
        if not args.dry_run:
            await save_rankings_to_supabase(supabase, teams_df)
        else:
            console.print("\n[yellow]Dry run - rankings not saved to database[/yellow]")
        
    except Exception as e:
        console.print(f"\n[red]Rankings calculation failed: {e}[/red]")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    asyncio.run(main())

