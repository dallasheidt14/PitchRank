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
from rich.panel import Panel

from src.rankings.calculator import compute_rankings_with_ml, compute_rankings_v53e_only
from src.etl.v53e import V53EConfig
from src.rankings.layer13_predictive_adjustment import Layer13Config
from src.rankings.data_adapter import v53e_to_supabase_format
import logging

# Configure logging for progress visibility
logging.basicConfig(
    level=logging.INFO,
    format='%(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

console = Console()
# Load environment variables - prioritize .env.local if it exists
env_local = Path('.env.local')
if env_local.exists():
    load_dotenv(env_local, override=True)
else:
    load_dotenv()


async def save_rankings_to_supabase(supabase_client, teams_df):
    """Save rankings to current_rankings table
    
    Returns:
        int: Number of records saved (0 if empty or error)
    """
    if teams_df.empty:
        console.print("[yellow]No rankings to save[/yellow]")
        return 0
    
    # Convert to Supabase format
    rankings_df = v53e_to_supabase_format(teams_df)
    
    if rankings_df.empty:
        console.print("[yellow]No rankings to save after conversion[/yellow]")
        return 0
    
    # Merge SOS from original teams_df (v53e_to_supabase_format may not preserve it)
    if 'sos' in teams_df.columns:
        # Create a mapping of team_id to sos
        sos_map = dict(zip(teams_df['team_id'].astype(str), teams_df['sos']))
        rankings_df['sos'] = rankings_df['team_id'].astype(str).map(sos_map)
    
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
            
            # Add Strength of Schedule (SOS)
            if 'sos' in row and pd.notna(row.get('sos')):
                record['strength_of_schedule'] = float(row['sos'])
            else:
                record['strength_of_schedule'] = None
            
            records.append(record)
        except Exception as e:
            console.print(f"[yellow]Warning: Skipping row due to error: {e}[/yellow]")
            continue
    
    # Upsert to current_rankings
    if records:
        import time
        max_retries = 3
        retry_delay = 2  # seconds
        
        try:
            # Use upsert (insert with conflict resolution)
            # First, try to delete all existing rankings
            try:
                supabase_client.table('current_rankings').delete().neq('team_id', '00000000-0000-0000-0000-000000000000').execute()
            except:
                pass  # If delete fails, continue with insert
            
            # Insert new rankings in batches with retry logic
            batch_size = 1000
            total_inserted = 0
            for i in range(0, len(records), batch_size):
                batch = records[i:i + batch_size]
                batch_num = (i // batch_size) + 1
                total_batches = (len(records) + batch_size - 1) // batch_size
                
                # Retry logic for SSL/network errors
                for attempt in range(max_retries):
                    try:
                        result = supabase_client.table('current_rankings').insert(batch).execute()
                        if result.data:
                            total_inserted += len(result.data)
                        console.print(f"[dim]Batch {batch_num}/{total_batches}: {len(batch)} records saved[/dim]")
                        break  # Success, exit retry loop
                    except Exception as e:
                        if attempt < max_retries - 1:
                            error_msg = str(e)
                            if 'SSL' in error_msg or 'bad record' in error_msg or 'ReadError' in error_msg:
                                console.print(f"[yellow]SSL/Network error on batch {batch_num}, attempt {attempt + 1}/{max_retries}. Retrying in {retry_delay}s...[/yellow]")
                                time.sleep(retry_delay)
                                retry_delay *= 2  # Exponential backoff
                            else:
                                # Non-retryable error
                                raise
                        else:
                            # Last attempt failed
                            console.print(f"[red]Failed to save batch {batch_num} after {max_retries} attempts: {e}[/red]")
                            raise
            
            console.print(f"[green]Saved {total_inserted} rankings to current_rankings table[/green]")
            return total_inserted
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
    parser.add_argument(
        '--force-rebuild',
        action='store_true',
        help='Ignore cached v53e rankings and rebuild from raw data'
    )
    
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
        console.print(f"\n[bold green]Calculating {mode_text} Rankings[/bold green]")
        console.print(f"  Lookback days: {args.lookback_days}")
        if args.provider:
            console.print(f"  Provider filter: {args.provider}")
        if args.dry_run:
            console.print(f"  [yellow]Mode: DRY RUN (no database writes)[/yellow]")
        console.print("")  # Blank line for spacing
        
        if args.ml:
            result = await compute_rankings_with_ml(
                supabase_client=supabase,
                today=None,
                fetch_from_supabase=True,
                lookback_days=args.lookback_days,
                provider_filter=args.provider,
                force_rebuild=args.force_rebuild,
            )
        else:
            result = await compute_rankings_v53e_only(
                supabase_client=supabase,
                today=None,
                fetch_from_supabase=True,
                lookback_days=args.lookback_days,
                provider_filter=args.provider,
                force_rebuild=args.force_rebuild,
            )
        
        teams_df = result["teams"]
        
        if teams_df.empty:
            console.print("[yellow]No teams found for ranking[/yellow]")
            return
        
        # Track total teams before filtering
        total_teams = len(teams_df)
        
        # Filter by age group and gender if specified
        if args.age_group:
            # Convert 'u10' to '10' format and handle string/int conversion
            age_filter_str = args.age_group.replace('u', '').replace('U', '')
            try:
                age_filter_int = int(age_filter_str)
                # Normalize age column for comparison (remove 'u' prefix if present)
                age_normalized = teams_df['age'].astype(str).str.replace('u', '').str.replace('U', '')
                teams_df = teams_df[age_normalized.astype(int) == age_filter_int]
            except (ValueError, TypeError):
                # Fallback to string comparison with normalized age
                age_normalized = teams_df['age'].astype(str).str.replace('u', '').str.replace('U', '')
                teams_df = teams_df[age_normalized == age_filter_str]
        
        if args.gender:
            # Case-insensitive gender filter
            gender_filter = args.gender.lower()
            teams_df = teams_df[teams_df['gender'].str.lower() == gender_filter]
        
        # Track filtered teams count
        filtered_teams = len(teams_df)
        
        # Fetch team names and club names for display
        team_ids = teams_df['team_id'].astype(str).unique().tolist()
        if team_ids:
            # Fetch in smaller batches (150) to avoid Supabase URL length limits (~8KB)
            teams_meta = {}
            batch_size = 150  # Reduced to avoid Supabase URL length limits
            for i in range(0, len(team_ids), batch_size):
                batch = team_ids[i:i+batch_size]
                try:
                    teams_meta_result = supabase.table('teams').select(
                        'team_id_master, team_name, club_name'
                    ).in_('team_id_master', batch).execute()
                    
                    if teams_meta_result.data:
                        for t in teams_meta_result.data:
                            teams_meta[str(t['team_id_master'])] = t
                except Exception as e:
                    logger.warning(f"Metadata batch failed ({i}-{i+batch_size}): {e}")
                    continue
            
            # Add to teams_df
            teams_df['team_name'] = teams_df['team_id'].astype(str).map(
                lambda tid: teams_meta.get(tid, {}).get('team_name', 'Unknown')
            )
            teams_df['club_name'] = teams_df['team_id'].astype(str).map(
                lambda tid: teams_meta.get(tid, {}).get('club_name', '') or ''
            )
        
        # Display summary
        console.print(f"\n[bold green]Rankings Calculated Successfully![/bold green]")
        console.print(f"\n[bold]Summary:[/bold]")
        console.print(f"  Total teams: {filtered_teams:,}")
        
        # Determine PowerScore column and validate bounds
        out_of_bounds_count = 0
        if 'powerscore_ml' in teams_df.columns:
            console.print(f"  Using ML-enhanced PowerScore")
            power_col = 'powerscore_ml'
            rank_col = 'rank_in_cohort_ml'
            
            # Validate PowerScore bounds
            if not teams_df.empty:
                min_score = teams_df[power_col].min()
                max_score = teams_df[power_col].max()
                violations = teams_df[~teams_df[power_col].between(0.0, 1.0, inclusive="both")]
                out_of_bounds_count = len(violations)
                
                console.print(f"\n[bold]PowerScore Validation:[/bold]")
                console.print(f"  Min: {min_score:.6f}")
                console.print(f"  Max: {max_score:.6f}")
                if out_of_bounds_count == 0:
                    console.print(f"  [green]✓ All PowerScores within [0.0, 1.0] bounds[/green]")
                else:
                    console.print(f"  [red]✗ {out_of_bounds_count} PowerScores out of bounds[/red]")
                
                # PowerScore Distribution Analysis
                unique_scores = teams_df[power_col].nunique()
                duplicate_count = len(teams_df) - unique_scores
                value_counts = teams_df[power_col].value_counts()
                
                console.print(f"\n[bold]PowerScore Distribution:[/bold]")
                console.print(f"  Unique PowerScores: {unique_scores:,}")
                console.print(f"  Teams with duplicate scores: {duplicate_count:,}")
                console.print(f"  Percentage with unique scores: {unique_scores / len(teams_df) * 100:.2f}%")
                console.print(f"  Mean teams per unique score: {value_counts.mean():.2f}")
                console.print(f"  Max teams with same score: {value_counts.max()}")
                
                if value_counts.max() > 10:
                    console.print(f"\n  [yellow]Top 5 most common PowerScore values:[/yellow]")
                    for score, count in value_counts.head(5).items():
                        console.print(f"    {score:.6f}: {count} teams")
        elif 'powerscore_adj' in teams_df.columns:
            console.print(f"  Using adjusted PowerScore")
            power_col = 'powerscore_adj'
            rank_col = 'rank_in_cohort'
            
            # Validate PowerScore bounds
            if not teams_df.empty:
                min_score = teams_df[power_col].min()
                max_score = teams_df[power_col].max()
                violations = teams_df[~teams_df[power_col].between(0.0, 1.0, inclusive="both")]
                out_of_bounds_count = len(violations)
                
                console.print(f"\n[bold]PowerScore Validation:[/bold]")
                console.print(f"  Min: {min_score:.6f}")
                console.print(f"  Max: {max_score:.6f}")
                if out_of_bounds_count == 0:
                    console.print(f"  [green]✓ All PowerScores within [0.0, 1.0] bounds[/green]")
                else:
                    console.print(f"  [red]✗ {out_of_bounds_count} PowerScores out of bounds[/red]")
                
                # PowerScore Distribution Analysis
                unique_scores = teams_df[power_col].nunique()
                duplicate_count = len(teams_df) - unique_scores
                value_counts = teams_df[power_col].value_counts()
                
                console.print(f"\n[bold]PowerScore Distribution:[/bold]")
                console.print(f"  Unique PowerScores: {unique_scores:,}")
                console.print(f"  Teams with duplicate scores: {duplicate_count:,}")
                console.print(f"  Percentage with unique scores: {unique_scores / len(teams_df) * 100:.2f}%")
                console.print(f"  Mean teams per unique score: {value_counts.mean():.2f}")
                console.print(f"  Max teams with same score: {value_counts.max()}")
                
                if value_counts.max() > 10:
                    console.print(f"\n  [yellow]Top 5 most common PowerScore values:[/yellow]")
                    for score, count in value_counts.head(5).items():
                        console.print(f"    {score:.6f}: {count} teams")
        else:
            power_col = 'powerscore_core'
            rank_col = 'rank_in_cohort'
            
            # Validate PowerScore bounds
            if not teams_df.empty and power_col in teams_df.columns:
                violations = teams_df[~teams_df[power_col].between(0.0, 1.0, inclusive="both")]
                out_of_bounds_count = len(violations)
        
        # Show top 10 teams
        if not teams_df.empty:
            top_teams = teams_df.nlargest(10, power_col)
            table = Table(title="Top 10 Teams")
            table.add_column("Rank", style="cyan")
            table.add_column("Team Name", style="cyan")
            table.add_column("Club", style="blue")
            table.add_column("Age", style="yellow")
            table.add_column("Gender", style="yellow")
            table.add_column("PowerScore", style="green", justify="right")
            
            for _, team in top_teams.iterrows():
                table.add_row(
                    str(int(team[rank_col])),
                    str(team.get('team_name', 'Unknown'))[:40],
                    str(team.get('club_name', ''))[:25],
                    str(team['age']),
                    str(team['gender']),
                    f"{team[power_col]:.4f}"
                )
            
            console.print("\n")
            console.print(table)
        
        # Save to database
        saved_count = 0
        if not args.dry_run:
            saved_count = await save_rankings_to_supabase(supabase, teams_df)
        else:
            console.print("\n[yellow]Dry run - rankings not saved to database[/yellow]")
            saved_count = filtered_teams  # Would-be saved count
        
        # ----------------------------------------------------------------
        #  Summary Banner
        # ----------------------------------------------------------------
        summary_text = (
            f"[bold]🏁 RANKINGS SUMMARY[/bold]\n"
            f"• Total teams processed: [cyan]{total_teams:,}[/cyan]\n"
            f"• After filters: [cyan]{filtered_teams:,}[/cyan]\n"
            f"• PowerScores out of bounds: [cyan]{out_of_bounds_count}[/cyan]\n"
            f"• Saved to Supabase: [green]{saved_count:,}[/green]\n"
            f"• Dry run mode: [yellow]{args.dry_run}[/yellow]\n"
            f"• ML Layer: [yellow]{args.ml}[/yellow]"
        )
        console.print("\n")
        console.print(Panel(summary_text, title="📊 Run Summary", border_style="bright_blue"))
        
    except Exception as e:
        console.print(f"\n[red]Rankings calculation failed: {e}[/red]")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    asyncio.run(main())

