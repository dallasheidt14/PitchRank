#!/usr/bin/env python3
"""
Validation script for v54 rankings engine changes.
Runs diagnostic queries and exports comparison data.
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

import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

console = Console()

# Load environment variables
env_local = Path('.env.local')
if env_local.exists():
    load_dotenv(env_local, override=True)
else:
    load_dotenv()


async def run_validation_queries(supabase_client):
    """Run the 6 targeted verification queries."""

    console.print("\n[bold cyan]═══════════════════════════════════════════════════════════════[/bold cyan]")
    console.print("[bold cyan]  V54 VALIDATION QUERIES[/bold cyan]")
    console.print("[bold cyan]═══════════════════════════════════════════════════════════════[/bold cyan]\n")

    # Query 1: SOS clustering check
    console.print("[bold yellow]Query #1 - SOS Clustering Check[/bold yellow]")
    console.print("[dim]Expected: Minimal clustering after v54 (smooth distribution)[/dim]\n")

    try:
        # Get all rankings and analyze sos_norm distribution
        result = supabase_client.table('rankings_full').select('sos_norm').execute()
        if result.data:
            df = pd.DataFrame(result.data)
            sos_counts = df['sos_norm'].round(4).value_counts()
            top_clusters = sos_counts[sos_counts > 1].head(10)

            if len(top_clusters) > 0:
                console.print(f"  Top SOS clusters (teams with same sos_norm):")
                for sos_val, count in top_clusters.items():
                    console.print(f"    {sos_val:.4f}: {count} teams")
                console.print(f"  Total unique sos_norm values: {df['sos_norm'].nunique()}")
                console.print(f"  Max teams with same sos_norm: {sos_counts.max()}")
            else:
                console.print("  [green]✓ No significant SOS clustering detected[/green]")
    except Exception as e:
        console.print(f"  [red]Error: {e}[/red]")

    console.print("")

    # Query 2: Low-sample SOS check
    console.print("[bold yellow]Query #2 - Low-Sample SOS Distribution[/bold yellow]")
    console.print("[dim]Expected: Smooth taper toward 0.5 (not hard cap at 0.70)[/dim]\n")

    try:
        result = supabase_client.table('rankings_full').select(
            'team_id, games_played, sos_norm'
        ).lt('games_played', 10).order('games_played').order('sos_norm', desc=True).limit(20).execute()

        if result.data:
            df = pd.DataFrame(result.data)
            console.print(f"  Low-sample teams (gp < 10):")
            for _, row in df.iterrows():
                sos = row['sos_norm'] if row['sos_norm'] is not None else 0
                flag = "[yellow]⚠[/yellow]" if sos > 0.69 else "[green]✓[/green]"
                console.print(f"    {flag} gp={row['games_played']}: sos_norm={sos:.4f}")

            # Check for hard cap violations
            hard_cap_count = len(df[df['sos_norm'] > 0.70]) if 'sos_norm' in df.columns else 0
            if hard_cap_count > 0:
                console.print(f"  [yellow]Warning: {hard_cap_count} low-sample teams have sos_norm > 0.70[/yellow]")
            else:
                console.print(f"  [green]✓ No hard cap violations detected[/green]")
        else:
            console.print("  No low-sample teams found")
    except Exception as e:
        console.print(f"  [red]Error: {e}[/red]")

    console.print("")

    # Query 3: Performance influence check
    console.print("[bold yellow]Query #3 - Performance Influence Distribution[/bold yellow]")
    console.print("[dim]Expected: Smaller impact, no huge spikes near ±0.5[/dim]\n")

    try:
        result = supabase_client.table('rankings_full').select('perf_centered').execute()
        if result.data:
            df = pd.DataFrame(result.data)
            perf = df['perf_centered'].dropna()

            console.print(f"  perf_centered statistics:")
            console.print(f"    Min: {perf.min():.4f}")
            console.print(f"    Max: {perf.max():.4f}")
            console.print(f"    Mean: {perf.mean():.4f}")
            console.print(f"    Std: {perf.std():.4f}")

            # Check for extreme values
            extreme_count = len(perf[perf.abs() > 0.4])
            if extreme_count > len(perf) * 0.01:  # More than 1%
                console.print(f"  [yellow]Warning: {extreme_count} teams ({extreme_count/len(perf)*100:.1f}%) have extreme perf_centered[/yellow]")
            else:
                console.print(f"  [green]✓ Performance distribution looks healthy[/green]")
        else:
            console.print("  No performance data found")
    except Exception as e:
        console.print(f"  [red]Error: {e}[/red]")

    console.print("")

    # Query 4: SOS by age group
    console.print("[bold yellow]Query #4 - SOS Separation by Age Group[/bold yellow]")
    console.print("[dim]Expected: Should follow anchor curve (U10=low → U18=high)[/dim]\n")

    try:
        result = supabase_client.table('rankings_full').select('age_group, sos_norm').execute()
        if result.data:
            df = pd.DataFrame(result.data)
            age_sos = df.groupby('age_group')['sos_norm'].agg(['mean', 'std', 'count'])
            age_sos = age_sos.sort_index()

            console.print(f"  Average SOS by age group:")
            for age, row in age_sos.iterrows():
                console.print(f"    {age}: mean={row['mean']:.4f}, std={row['std']:.4f}, n={int(row['count'])}")
        else:
            console.print("  No data found")
    except Exception as e:
        console.print(f"  [red]Error: {e}[/red]")

    console.print("")

    # Query 5: PowerScore distribution
    console.print("[bold yellow]Query #5 - PowerScore Distribution Check[/bold yellow]")
    console.print("[dim]Expected: Values in [0, 1] with good spread[/dim]\n")

    try:
        result = supabase_client.table('rankings_full').select(
            'age_group, gender, powerscore_adj'
        ).execute()
        if result.data:
            df = pd.DataFrame(result.data)

            # Overall stats
            ps = df['powerscore_adj'].dropna()
            console.print(f"  Overall powerscore_adj statistics:")
            console.print(f"    Min: {ps.min():.4f}")
            console.print(f"    Max: {ps.max():.4f}")
            console.print(f"    Mean: {ps.mean():.4f}")
            console.print(f"    Std: {ps.std():.4f}")

            # Check bounds
            out_of_bounds = len(ps[(ps < 0) | (ps > 1)])
            if out_of_bounds > 0:
                console.print(f"  [red]✗ {out_of_bounds} scores out of [0, 1] bounds[/red]")
            else:
                console.print(f"  [green]✓ All scores within [0, 1] bounds[/green]")

            # Per cohort
            console.print(f"\n  Per cohort (age, gender):")
            cohort_stats = df.groupby(['age_group', 'gender'])['powerscore_adj'].agg(['min', 'max', 'mean'])
            for (age, gender), row in cohort_stats.iterrows():
                console.print(f"    {age} {gender}: min={row['min']:.3f}, max={row['max']:.3f}, mean={row['mean']:.3f}")
        else:
            console.print("  No data found")
    except Exception as e:
        console.print(f"  [red]Error: {e}[/red]")

    console.print("")

    # Query 6: Sample flag distribution
    console.print("[bold yellow]Query #6 - Sample Flag Distribution[/bold yellow]")
    console.print("[dim]Expected: LOW_SAMPLE teams should have sos_norm shrunk toward 0.5[/dim]\n")

    try:
        result = supabase_client.table('rankings_full').select(
            'sample_flag, sos_norm'
        ).execute()
        if result.data:
            df = pd.DataFrame(result.data)
            flag_stats = df.groupby('sample_flag')['sos_norm'].agg(['mean', 'std', 'count'])

            console.print(f"  SOS by sample_flag:")
            for flag, row in flag_stats.iterrows():
                console.print(f"    {flag}: mean_sos={row['mean']:.4f}, std={row['std']:.4f}, n={int(row['count'])}")

            # Check if LOW_SAMPLE has lower variance (more shrunk toward 0.5)
            if 'LOW_SAMPLE' in flag_stats.index and 'OK' in flag_stats.index:
                low_std = flag_stats.loc['LOW_SAMPLE', 'std']
                ok_std = flag_stats.loc['OK', 'std']
                if low_std < ok_std:
                    console.print(f"  [green]✓ LOW_SAMPLE has lower SOS variance ({low_std:.4f} < {ok_std:.4f})[/green]")
                else:
                    console.print(f"  [yellow]Warning: LOW_SAMPLE variance not reduced as expected[/yellow]")
        else:
            console.print("  No data found")
    except Exception as e:
        console.print(f"  [red]Error: {e}[/red]")


async def export_distribution_stats(supabase_client, output_dir):
    """Export distribution statistics to CSV."""

    console.print("\n[bold cyan]═══════════════════════════════════════════════════════════════[/bold cyan]")
    console.print("[bold cyan]  EXPORTING DISTRIBUTION STATISTICS[/bold cyan]")
    console.print("[bold cyan]═══════════════════════════════════════════════════════════════[/bold cyan]\n")

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        # Fetch all rankings
        result = supabase_client.table('rankings_full').select(
            'team_id, age_group, gender, games_played, '
            'sos_norm, powerscore_adj, off_norm, def_norm, perf_centered, sample_flag'
        ).execute()

        if not result.data:
            console.print("[yellow]No data to export[/yellow]")
            return

        df = pd.DataFrame(result.data)

        # Export full rankings
        rankings_file = output_dir / f"rankings_v54_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        df.to_csv(rankings_file, index=False)
        console.print(f"  [green]✓ Exported rankings to {rankings_file}[/green]")

        # Export distribution stats
        numeric_cols = ['sos_norm', 'powerscore_adj', 'off_norm', 'def_norm', 'perf_centered']
        stats_df = df[numeric_cols].describe()
        stats_file = output_dir / f"v54_distribution_stats_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        stats_df.to_csv(stats_file)
        console.print(f"  [green]✓ Exported distribution stats to {stats_file}[/green]")

        # Print stats to console
        console.print(f"\n  [bold]Distribution Summary:[/bold]")
        console.print(stats_df.round(4).to_string())

    except Exception as e:
        console.print(f"[red]Error exporting: {e}[/red]")


async def main():
    parser = argparse.ArgumentParser(description='Validate v54 rankings engine changes')
    parser.add_argument('--export-dir', type=str, default='data/validation',
                       help='Directory for export files (default: data/validation)')
    parser.add_argument('--skip-export', action='store_true',
                       help='Skip CSV export, only run queries')

    args = parser.parse_args()

    # Initialize Supabase client
    supabase_url = os.getenv('SUPABASE_URL')
    supabase_key = os.getenv('SUPABASE_SERVICE_ROLE_KEY')

    if not supabase_url or not supabase_key:
        console.print("[red]Error: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set in .env[/red]")
        sys.exit(1)

    supabase = create_client(supabase_url, supabase_key)

    console.print(Panel(
        "[bold]V54 Rankings Engine Validation[/bold]\n\n"
        "This script validates the v54 changes:\n"
        "• Exponential decay recency weighting\n"
        "• Soft SOS shrinkage (no hard cap)\n"
        "• Split performance scaling\n"
        "• Cohort-based SOS (no national override)",
        title="🔍 Validation Suite",
        border_style="cyan"
    ))

    # Run validation queries
    await run_validation_queries(supabase)

    # Export distribution stats
    if not args.skip_export:
        await export_distribution_stats(supabase, args.export_dir)

    console.print("\n[bold green]✅ Validation complete![/bold green]\n")


if __name__ == '__main__':
    try:
        asyncio.run(main())
        sys.exit(0)
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted by user[/yellow]")
        sys.exit(130)
    except Exception as e:
        console.print(f"\n[red]Fatal error: {e}[/red]")
        import traceback
        traceback.print_exc()
        sys.exit(1)
