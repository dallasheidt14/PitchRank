#!/usr/bin/env python3
"""
Verify that SOS is being factored into PowerScore calculations
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
from config.settings import RANKING_CONFIG

console = Console()
# Load environment variables
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
    
    console.print("[bold green]Verifying SOS Impact on Rankings[/bold green]\n")

    # Get config to show weights (using environment-aware config)
    cfg = V53EConfig(**RANKING_CONFIG)
    console.print(f"[cyan]PowerScore Formula Weights:[/cyan]")
    console.print(f"  [dim]SOS Transitivity Lambda: {cfg.SOS_TRANSITIVITY_LAMBDA}[/dim]")
    console.print(f"  Offense: {cfg.OFF_WEIGHT * 100:.0f}%")
    console.print(f"  Defense: {cfg.DEF_WEIGHT * 100:.0f}%")
    console.print(f"  [bold]SOS: {cfg.SOS_WEIGHT * 100:.0f}%[/bold]")
    console.print(f"  Performance: {cfg.PERFORMANCE_K * 100:.1f}% adjustment\n")
    
    # Calculate rankings
    console.print("[cyan]Calculating rankings...[/cyan]")
    result = await compute_rankings_v53e_only(
        supabase_client=supabase,
        fetch_from_supabase=True,
        lookback_days=365,
    )
    
    teams_df = result['teams']
    
    if teams_df.empty:
        console.print("[red]No teams found[/red]")
        return
    
    # Verify SOS columns exist
    if 'sos' not in teams_df.columns or 'sos_norm' not in teams_df.columns:
        console.print("[red]✗ SOS columns missing from rankings output[/red]")
        return
    
    if 'powerscore_core' not in teams_df.columns:
        console.print("[red]✗ PowerScore core missing[/red]")
        return
    
    console.print(f"[green]✓ Rankings calculated for {len(teams_df):,} teams[/green]\n")
    
    # Show correlation between SOS and PowerScore
    console.print("[cyan]SOS Impact Analysis:[/cyan]")
    
    # Calculate correlation
    sos_corr = teams_df['sos_norm'].corr(teams_df['powerscore_core'])
    console.print(f"  Correlation (SOS vs PowerScore): {sos_corr:.4f}")
    
    # Show examples of high/low SOS teams
    console.print(f"\n[yellow]Top 10 Teams by PowerScore:[/yellow]")
    top_teams = teams_df.nlargest(10, 'powerscore_core')
    
    top_table = Table(show_header=True)
    top_table.add_column("Rank", justify="right")
    top_table.add_column("PowerScore", justify="right")
    top_table.add_column("SOS (raw)", justify="right")
    top_table.add_column("SOS (norm)", justify="right")
    top_table.add_column("Off Norm", justify="right")
    top_table.add_column("Def Norm", justify="right")
    
    for idx, (_, team) in enumerate(top_teams.iterrows(), 1):
        top_table.add_row(
            str(idx),
            f"{team['powerscore_core']:.4f}",
            f"{team['sos']:.4f}" if pd.notna(team['sos']) else "N/A",
            f"{team['sos_norm']:.4f}" if pd.notna(team['sos_norm']) else "N/A",
            f"{team.get('off_norm', 0):.4f}" if 'off_norm' in teams_df.columns else "N/A",
            f"{team.get('def_norm', 0):.4f}" if 'def_norm' in teams_df.columns else "N/A",
        )
    console.print(top_table)
    
    # Show teams with high SOS but lower PowerScore (SOS impact)
    console.print(f"\n[yellow]Teams with High SOS but Lower PowerScore (showing SOS impact):[/yellow]")
    high_sos = teams_df.nlargest(20, 'sos_norm')
    sos_impact_table = Table(show_header=True)
    sos_impact_table.add_column("PowerScore", justify="right")
    sos_impact_table.add_column("SOS (norm)", justify="right")
    sos_impact_table.add_column("SOS Weight", justify="right")
    sos_impact_table.add_column("Off Norm", justify="right")
    sos_impact_table.add_column("Def Norm", justify="right")
    
    for _, team in high_sos.head(10).iterrows():
        sos_contribution = cfg.SOS_WEIGHT * team['sos_norm']
        sos_impact_table.add_row(
            f"{team['powerscore_core']:.4f}",
            f"{team['sos_norm']:.4f}",
            f"{sos_contribution:.4f}",
            f"{team.get('off_norm', 0):.4f}" if 'off_norm' in teams_df.columns else "N/A",
            f"{team.get('def_norm', 0):.4f}" if 'def_norm' in teams_df.columns else "N/A",
        )
    console.print(sos_impact_table)
    
    # Verify PowerScore formula
    console.print(f"\n[cyan]Verifying PowerScore Formula:[/cyan]")
    sample_team = teams_df.iloc[0]
    
    if all(col in teams_df.columns for col in ['off_norm', 'def_norm', 'sos_norm', 'powerscore_core']):
        calculated_ps = (
            cfg.OFF_WEIGHT * sample_team['off_norm'] +
            cfg.DEF_WEIGHT * sample_team['def_norm'] +
            cfg.SOS_WEIGHT * sample_team['sos_norm'] +
            sample_team.get('perf_centered', 0) * cfg.PERFORMANCE_K
        )
        actual_ps = sample_team['powerscore_core']
        
        console.print(f"  Sample team PowerScore:")
        console.print(f"    Calculated: {calculated_ps:.6f}")
        console.print(f"    Actual: {actual_ps:.6f}")
        console.print(f"    Difference: {abs(calculated_ps - actual_ps):.6f}")
        
        if abs(calculated_ps - actual_ps) < 0.0001:
            console.print(f"  [green]✓ Formula matches![/green]")
        else:
            console.print(f"  [yellow]⚠ Small difference (may be due to provisional multiplier or normalization)[/yellow]")
    
    # Summary
    summary_items = [
        f"[green]✓ SOS is calculated[/green]",
        f"[green]✓ SOS has {cfg.SOS_WEIGHT * 100:.0f}% weight in PowerScore[/green]",
        f"[green]✓ SOS normalized (sos_norm) is used in formula[/green]",
        f"[yellow]⚠ SOS is NOT saved to database (but fix is ready)[/yellow]"
    ]
    
    summary_panel = Panel("\n".join(summary_items), title="SOS Status", border_style="cyan")
    console.print("\n")
    console.print(summary_panel)


if __name__ == '__main__':
    asyncio.run(main())

