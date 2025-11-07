#!/usr/bin/env python3
"""
Show detailed rankings results with team names and statistics
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

console = Console()
load_dotenv()

async def main():
    # Initialize Supabase client
    supabase_url = os.getenv('SUPABASE_URL')
    supabase_key = os.getenv('SUPABASE_SERVICE_ROLE_KEY')
    
    if not supabase_url or not supabase_key:
        console.print("[red]Error: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set in .env[/red]")
        sys.exit(1)
    
    supabase = create_client(supabase_url, supabase_key)
    
    # Fetch team names for display
    teams_result = supabase.table('teams').select('team_id_master, team_name, club_name, age_group, gender, state_code').execute()
    # Create lookup with normalized string keys (handle UUID objects from Supabase)
    teams_lookup = {}
    if teams_result.data:
        for t in teams_result.data:
            # Normalize team_id_master to string (handles UUID objects)
            team_id_key = str(t['team_id_master']).strip()
            teams_lookup[team_id_key] = t
            # Also store lowercase version for case-insensitive matching
            teams_lookup[team_id_key.lower()] = t
    
    console.print(f"[dim]Loaded {len(teams_lookup)} teams for lookup[/dim]")
    
    console.print("[bold green]Calculating Rankings...[/bold green]")
    result = await compute_rankings_v53e_only(
        supabase_client=supabase,
        fetch_from_supabase=True,
        lookback_days=365,
    )
    
    teams_df = result['teams']
    games_used_df = result.get('games_used', pd.DataFrame())
    
    if teams_df.empty:
        console.print("[yellow]No teams found[/yellow]")
        return
    
    # Determine power score column
    if 'powerscore_ml' in teams_df.columns:
        power_col = 'powerscore_ml'
        rank_col = 'rank_in_cohort_ml'
    elif 'powerscore_adj' in teams_df.columns:
        power_col = 'powerscore_adj'
        rank_col = 'rank_in_cohort'
    else:
        power_col = 'powerscore_core'
        rank_col = 'rank_in_cohort'
    
    # Overall Statistics
    console.print("\n")
    console.print(Panel.fit("[bold]Overall Statistics[/bold]", style="cyan"))
    stats_table = Table(show_header=False, box=None)
    stats_table.add_row("Total Teams", f"{len(teams_df):,}")
    stats_table.add_row("Total Games Used", f"{len(games_used_df):,}" if not games_used_df.empty else "N/A")
    stats_table.add_row("PowerScore Range", f"{teams_df[power_col].min():.4f} - {teams_df[power_col].max():.4f}")
    stats_table.add_row("PowerScore Mean", f"{teams_df[power_col].mean():.4f}")
    stats_table.add_row("PowerScore Median", f"{teams_df[power_col].median():.4f}")
    if 'gp' in teams_df.columns:
        stats_table.add_row("Avg Games Played", f"{teams_df['gp'].mean():.1f}")
        stats_table.add_row("Max Games Played", f"{int(teams_df['gp'].max())}")
    console.print(stats_table)
    
    # Breakdown by Age Group
    console.print("\n")
    console.print(Panel.fit("[bold]Breakdown by Age Group[/bold]", style="cyan"))
    age_table = Table()
    age_table.add_column("Age", style="yellow")
    age_table.add_column("Teams", justify="right")
    age_table.add_column("Top PowerScore", justify="right")
    age_table.add_column("Avg PowerScore", justify="right")
    if 'gp' in teams_df.columns:
        age_table.add_column("Avg Games", justify="right")
    
    for age in sorted(teams_df['age'].unique()):
        age_teams = teams_df[teams_df['age'] == age]
        age_table.add_row(
            str(age),
            f"{len(age_teams):,}",
            f"{age_teams[power_col].max():.4f}",
            f"{age_teams[power_col].mean():.4f}",
            f"{age_teams['gp'].mean():.1f}" if 'gp' in teams_df.columns else "N/A"
        )
    console.print(age_table)
    
    # Breakdown by Gender
    console.print("\n")
    console.print(Panel.fit("[bold]Breakdown by Gender[/bold]", style="cyan"))
    gender_table = Table()
    gender_table.add_column("Gender", style="yellow")
    gender_table.add_column("Teams", justify="right")
    gender_table.add_column("Top PowerScore", justify="right")
    gender_table.add_column("Avg PowerScore", justify="right")
    if 'gp' in teams_df.columns:
        gender_table.add_column("Avg Games", justify="right")
    
    for gender in sorted(teams_df['gender'].unique()):
        gender_teams = teams_df[teams_df['gender'] == gender]
        gender_table.add_row(
            str(gender).title(),
            f"{len(gender_teams):,}",
            f"{gender_teams[power_col].max():.4f}",
            f"{gender_teams[power_col].mean():.4f}",
            f"{gender_teams['gp'].mean():.1f}" if 'gp' in teams_df.columns else "N/A"
        )
    console.print(gender_table)
    
    # Top 30 Teams
    console.print("\n")
    console.print(Panel.fit("[bold]Top 30 Teams (All Ages/Genders)[/bold]", style="cyan"))
    top_teams = teams_df.nlargest(30, power_col)
    top_table = Table()
    top_table.add_column("Rank", style="cyan", justify="right")
    top_table.add_column("Team Name", style="magenta", max_width=40)
    top_table.add_column("Club", style="blue", max_width=25)
    top_table.add_column("Age", style="yellow")
    top_table.add_column("Gender", style="yellow")
    top_table.add_column("PowerScore", style="green", justify="right")
    top_table.add_column("Rank in Cohort", justify="right")
    if 'gp' in teams_df.columns:
        top_table.add_column("Games", justify="right")
    if 'sos' in teams_df.columns:
        top_table.add_column("SOS", justify="right")
    
    for idx, (_, team) in enumerate(top_teams.iterrows(), 1):
        # Normalize team_id to lowercase string for lookup
        team_id_str = str(team['team_id']).strip().lower()
        team_info = teams_lookup.get(team_id_str, {})
        
        # If still not found, try original case
        if not team_info:
            team_id_orig = str(team['team_id']).strip()
            team_info = teams_lookup.get(team_id_orig, {})
        
        team_name = team_info.get('team_name', 'Unknown')[:40] if team_info else 'Unknown'
        club_name = team_info.get('club_name', '')[:25] if team_info.get('club_name') else ''
        
        top_table.add_row(
            str(idx),
            team_name,
            club_name,
            str(team['age']),
            str(team['gender']).title(),
            f"{team[power_col]:.4f}",
            str(int(team[rank_col])) if pd.notna(team[rank_col]) else "N/A",
            f"{int(team['gp'])}" if 'gp' in teams_df.columns and pd.notna(team['gp']) else "N/A",
            f"{team['sos']:.3f}" if 'sos' in teams_df.columns and pd.notna(team['sos']) else "N/A"
        )
    console.print(top_table)
    
    # Top 10 by Age/Gender Cohort
    console.print("\n")
    console.print(Panel.fit("[bold]Top 10 Teams by Age/Gender Cohort[/bold]", style="cyan"))
    for age in sorted(teams_df['age'].unique()):
        for gender in sorted(teams_df['gender'].unique()):
            cohort_teams = teams_df[(teams_df['age'] == age) & (teams_df['gender'] == gender)]
            if cohort_teams.empty:
                continue
            
            top_cohort = cohort_teams.nlargest(10, power_col)
            if top_cohort.empty:
                continue
            
            console.print(f"\n[bold]Age {age} - {str(gender).title()}[/bold] ({len(cohort_teams)} teams)")
            cohort_table = Table()
            cohort_table.add_column("Rank", style="cyan", justify="right")
            cohort_table.add_column("Team Name", style="magenta", max_width=35)
            cohort_table.add_column("Club", style="blue", max_width=20)
            cohort_table.add_column("PowerScore", style="green", justify="right")
            if 'gp' in teams_df.columns:
                cohort_table.add_column("Games", justify="right")
            
            for _, team in top_cohort.iterrows():
                # Normalize team_id to string for lookup
                team_id_str = str(team['team_id']).strip()
                team_info = teams_lookup.get(team_id_str, teams_lookup.get(team_id_str.lower(), {}))
                team_name = team_info.get('team_name', 'Unknown')[:35]
                club_name = team_info.get('club_name', '')[:20] if team_info.get('club_name') else ''
                
                cohort_table.add_row(
                    str(int(team[rank_col])) if pd.notna(team[rank_col]) else "N/A",
                    team_name,
                    club_name,
                    f"{team[power_col]:.4f}",
                    f"{int(team['gp'])}" if 'gp' in teams_df.columns and pd.notna(team['gp']) else "N/A"
                )
            console.print(cohort_table)

if __name__ == '__main__':
    asyncio.run(main())

