#!/usr/bin/env python3
"""
Check if Strength of Schedule (SOS) is being calculated and saved correctly
"""
import asyncio
import sys
from pathlib import Path
import pandas as pd
from supabase import create_client
import os
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

sys.path.append(str(Path(__file__).parent.parent))

from src.rankings.calculator import compute_rankings_v53e_only
from src.etl.v53e import V53EConfig

console = Console()
# Load environment variables - prioritize .env.local if it exists
env_local = Path('.env.local')
if env_local.exists():
    from dotenv import load_dotenv
    load_dotenv(env_local, override=True)
else:
    from dotenv import load_dotenv
    load_dotenv()


async def main():
    # Initialize Supabase client
    supabase_url = os.getenv('SUPABASE_URL')
    supabase_key = os.getenv('SUPABASE_SERVICE_ROLE_KEY')
    
    if not supabase_url or not supabase_key:
        console.print("[red]Error: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set in .env[/red]")
        sys.exit(1)
    
    supabase = create_client(supabase_url, supabase_key)
    
    console.print("[bold green]Checking SOS Calculation and Storage[/bold green]\n")
    
    # 1. Check if SOS is calculated in rankings
    console.print("[cyan]Step 1: Checking if SOS is calculated in rankings engine...[/cyan]")
    result = await compute_rankings_v53e_only(
        supabase_client=supabase,
        fetch_from_supabase=True,
        lookback_days=365,
    )
    
    teams_df = result['teams']
    
    if teams_df.empty:
        console.print("[red]No teams found in rankings calculation[/red]")
        return
    
    # Check for SOS columns
    sos_columns = [col for col in teams_df.columns if 'sos' in col.lower()]
    console.print(f"  Found SOS-related columns: {sos_columns}")
    
    if 'sos' in teams_df.columns:
        sos_stats = teams_df['sos'].describe()
        console.print(f"\n  [green]✓ SOS is calculated[/green]")
        console.print(f"    Min: {sos_stats['min']:.4f}")
        console.print(f"    Max: {sos_stats['max']:.4f}")
        console.print(f"    Mean: {sos_stats['mean']:.4f}")
        console.print(f"    Median: {sos_stats['50%']:.4f}")
        console.print(f"    Non-null count: {teams_df['sos'].notna().sum():,} / {len(teams_df):,}")
        
        # Show some examples
        console.print(f"\n  [yellow]Sample SOS values (top 10 teams):[/yellow]")
        top_teams = teams_df.nlargest(10, 'powerscore_adj' if 'powerscore_adj' in teams_df.columns else 'powerscore_core')
        sample_table = Table(show_header=True)
        sample_table.add_column("Team ID", style="cyan", max_width=40)
        sample_table.add_column("SOS", justify="right")
        sample_table.add_column("SOS Norm", justify="right")
        sample_table.add_column("PowerScore", justify="right")
        
        for _, team in top_teams.head(10).iterrows():
            power_col = 'powerscore_adj' if 'powerscore_adj' in teams_df.columns else 'powerscore_core'
            sample_table.add_row(
                str(team['team_id'])[:40],
                f"{team['sos']:.4f}" if pd.notna(team['sos']) else "N/A",
                f"{team.get('sos_norm', 'N/A'):.4f}" if 'sos_norm' in teams_df.columns and pd.notna(team.get('sos_norm')) else "N/A",
                f"{team[power_col]:.4f}" if power_col in teams_df.columns else "N/A"
            )
        console.print(sample_table)
    else:
        console.print(f"  [red]✗ SOS column not found in rankings output[/red]")
        console.print(f"  Available columns: {list(teams_df.columns)}")
    
    # 2. Check if SOS is stored in database
    console.print(f"\n[cyan]Step 2: Checking if SOS is stored in database...[/cyan]")
    try:
        # Check current_rankings table
        rankings_result = supabase.table('current_rankings').select(
            'team_id, strength_of_schedule, national_power_score, games_played'
        ).limit(100).execute()
        
        if rankings_result.data:
            rankings_df = pd.DataFrame(rankings_result.data)
            
            sos_in_db = rankings_df['strength_of_schedule'].notna().sum()
            total_in_db = len(rankings_df)
            
            console.print(f"  Total records in database: {total_in_db}")
            console.print(f"  Records with SOS: {sos_in_db}")
            console.print(f"  Records without SOS: {total_in_db - sos_in_db}")
            
            if sos_in_db > 0:
                sos_db_stats = rankings_df['strength_of_schedule'].describe()
                console.print(f"\n  [green]✓ SOS is stored in database[/green]")
                console.print(f"    Min: {sos_db_stats['min']:.4f}")
                console.print(f"    Max: {sos_db_stats['max']:.4f}")
                console.print(f"    Mean: {sos_db_stats['mean']:.4f}")
                console.print(f"    Median: {sos_db_stats['50%']:.4f}")
                
                # Show examples
                console.print(f"\n  [yellow]Sample SOS values from database (top 10 by power score):[/yellow]")
                db_sample = rankings_df.nlargest(10, 'national_power_score')
                db_table = Table(show_header=True)
                db_table.add_column("Team ID", style="cyan", max_width=40)
                db_table.add_column("SOS", justify="right")
                db_table.add_column("PowerScore", justify="right")
                db_table.add_column("Games", justify="right")
                
                for _, row in db_sample.iterrows():
                    db_table.add_row(
                        str(row['team_id'])[:40],
                        f"{row['strength_of_schedule']:.4f}" if pd.notna(row['strength_of_schedule']) else "NULL",
                        f"{row['national_power_score']:.4f}",
                        f"{int(row['games_played'])}" if pd.notna(row['games_played']) else "0"
                    )
                console.print(db_table)
            else:
                console.print(f"  [red]✗ SOS is NOT stored in database (all values are NULL)[/red]")
                console.print(f"  [yellow]This means the save function is not including SOS![/yellow]")
        else:
            console.print(f"  [yellow]No rankings found in database[/yellow]")
    except Exception as e:
        console.print(f"  [red]Error checking database: {e}[/red]")
        import traceback
        traceback.print_exc()
    
    # 3. Summary
    console.print(f"\n[bold cyan]Summary:[/bold cyan]")
    summary_items = []
    
    if 'sos' in teams_df.columns:
        summary_items.append("[green]✓ SOS is calculated by rankings engine[/green]")
    else:
        summary_items.append("[red]✗ SOS is NOT calculated by rankings engine[/red]")
    
    try:
        if rankings_result.data:
            rankings_df = pd.DataFrame(rankings_result.data)
            if rankings_df['strength_of_schedule'].notna().sum() > 0:
                summary_items.append("[green]✓ SOS is stored in database[/green]")
            else:
                summary_items.append("[red]✗ SOS is NOT stored in database[/red]")
                summary_items.append("[yellow]→ Need to update save_rankings_to_supabase() function[/yellow]")
    except:
        pass
    
    summary_panel = Panel("\n".join(summary_items), title="SOS Status", border_style="cyan")
    console.print(summary_panel)


if __name__ == '__main__':
    asyncio.run(main())

