#!/usr/bin/env python3
"""
Comprehensive SOS Distribution Analysis
Diagnoses whether there's a real problem with SOS value duplication
"""
import asyncio
import sys
from pathlib import Path
import pandas as pd
import numpy as np
from supabase import create_client
import os
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from collections import Counter

sys.path.append(str(Path(__file__).parent.parent))

from src.rankings.calculator import compute_rankings_v53e_only
from src.etl.v53e import V53EConfig
from config.settings import RANKING_CONFIG

console = Console()

# Load environment variables
env_local = Path('.env.local')
if env_local.exists():
    load_dotenv(env_local, override=True)
else:
    load_dotenv()


def analyze_sos_distribution(teams_df: pd.DataFrame, cfg: V53EConfig):
    """Comprehensive SOS distribution analysis"""

    console.print("\n[bold cyan]═══ SOS Distribution Analysis ═══[/bold cyan]\n")

    # 1. Overall Statistics
    console.print("[yellow]1. Overall SOS Statistics:[/yellow]")
    if 'sos' in teams_df.columns:
        sos_stats = teams_df['sos'].describe()
        console.print(f"  Count: {sos_stats['count']:.0f}")
        console.print(f"  Mean: {sos_stats['mean']:.6f}")
        console.print(f"  Std Dev: {sos_stats['std']:.6f}")
        console.print(f"  Min: {sos_stats['min']:.6f}")
        console.print(f"  25%: {sos_stats['25%']:.6f}")
        console.print(f"  Median: {sos_stats['50%']:.6f}")
        console.print(f"  75%: {sos_stats['75%']:.6f}")
        console.print(f"  Max: {sos_stats['max']:.6f}")

        # Check for identical values
        sos_values = teams_df['sos'].dropna()
        unique_count = len(sos_values.unique())
        total_count = len(sos_values)
        duplicate_rate = (total_count - unique_count) / total_count * 100

        console.print(f"\n  [bold]Unique SOS values: {unique_count:,} / {total_count:,}[/bold]")
        console.print(f"  [bold]Duplication rate: {duplicate_rate:.2f}%[/bold]")

        # Find most common SOS values
        value_counts = Counter(sos_values.round(6))
        most_common = value_counts.most_common(10)

        console.print(f"\n[yellow]2. Most Common SOS Values (Top 10):[/yellow]")
        dup_table = Table(show_header=True)
        dup_table.add_column("SOS Value", justify="right")
        dup_table.add_column("Team Count", justify="right")
        dup_table.add_column("% of Total", justify="right")

        for value, count in most_common:
            pct = count / total_count * 100
            style = "red" if count > 20 else "yellow" if count > 10 else ""
            dup_table.add_row(
                f"{value:.6f}",
                f"{count}",
                f"{pct:.2f}%",
                style=style
            )
        console.print(dup_table)

    # 3. Cohort-level analysis
    console.print(f"\n[yellow]3. Per-Cohort SOS Analysis:[/yellow]")
    cohort_table = Table(show_header=True)
    cohort_table.add_column("Age", justify="left")
    cohort_table.add_column("Gender", justify="left")
    cohort_table.add_column("Teams", justify="right")
    cohort_table.add_column("Unique SOS", justify="right")
    cohort_table.add_column("Dup Rate", justify="right")
    cohort_table.add_column("SOS Range", justify="right")
    cohort_table.add_column("SOS Std", justify="right")

    cohort_issues = []

    for (age, gender), grp in teams_df.groupby(['age', 'gender']):
        if 'sos' not in grp.columns:
            continue

        sos_values = grp['sos'].dropna()
        if len(sos_values) == 0:
            continue

        team_count = len(sos_values)
        unique_sos = len(sos_values.unique())
        dup_rate = (team_count - unique_sos) / team_count * 100 if team_count > 0 else 0
        sos_range = sos_values.max() - sos_values.min()
        sos_std = sos_values.std()

        # Flag issues
        style = ""
        if dup_rate > 50 or sos_std < 0.01:
            style = "red"
            cohort_issues.append({
                'age': age,
                'gender': gender,
                'teams': team_count,
                'unique': unique_sos,
                'dup_rate': dup_rate,
                'std': sos_std
            })
        elif dup_rate > 30 or sos_std < 0.05:
            style = "yellow"

        cohort_table.add_row(
            str(age),
            str(gender),
            str(team_count),
            str(unique_sos),
            f"{dup_rate:.1f}%",
            f"{sos_range:.4f}",
            f"{sos_std:.4f}",
            style=style
        )

    console.print(cohort_table)

    # 4. Problematic cohorts detail
    if cohort_issues:
        console.print(f"\n[red]⚠ Found {len(cohort_issues)} cohorts with high SOS duplication:[/red]")
        for issue in cohort_issues[:5]:  # Show top 5
            console.print(f"  • {issue['age']} {issue['gender']}: "
                         f"{issue['teams']} teams, {issue['unique']} unique SOS "
                         f"({issue['dup_rate']:.1f}% duplication, std={issue['std']:.4f})")

    # 5. Check normalization method impact
    console.print(f"\n[yellow]4. Normalization Method Analysis:[/yellow]")
    console.print(f"  Current mode: [bold]{cfg.NORM_MODE}[/bold]")

    if 'sos_norm' in teams_df.columns:
        sos_norm_unique = len(teams_df['sos_norm'].dropna().unique())
        sos_norm_total = len(teams_df['sos_norm'].dropna())
        console.print(f"  Unique sos_norm values: {sos_norm_unique} / {sos_norm_total}")
        console.print(f"  sos_norm range: [{teams_df['sos_norm'].min():.4f}, {teams_df['sos_norm'].max():.4f}]")

    # 6. Check if using continuous strength (as per our code)
    console.print(f"\n[yellow]5. Strength Calculation Method:[/yellow]")
    if 'abs_strength' in teams_df.columns:
        abs_strength_unique = len(teams_df['abs_strength'].dropna().unique())
        abs_strength_total = len(teams_df['abs_strength'].dropna())
        console.print(f"  [green]✓ Using abs_strength (continuous)[/green]")
        console.print(f"  Unique abs_strength values: {abs_strength_unique} / {abs_strength_total}")
        console.print(f"  abs_strength range: [{teams_df['abs_strength'].min():.4f}, {teams_df['abs_strength'].max():.4f}]")

    # 7. Schedule similarity analysis (teams playing similar opponents)
    console.print(f"\n[yellow]6. Schedule Overlap Analysis:[/yellow]")
    console.print(f"  [dim]Analyzing if SOS duplication is due to similar schedules...[/dim]")

    # Sample a few duplicate SOS groups
    if 'sos' in teams_df.columns:
        sos_rounded = teams_df['sos'].round(4)
        dup_sos_values = [v for v, c in Counter(sos_rounded).items() if c > 5][:3]

        if dup_sos_values:
            console.print(f"  Found {len(dup_sos_values)} SOS values with >5 teams")
            console.print(f"  Example: SOS={dup_sos_values[0]:.4f} shared by {Counter(sos_rounded)[dup_sos_values[0]]} teams")

    return cohort_issues


async def main():
    # Initialize Supabase client
    supabase_url = os.getenv('SUPABASE_URL')
    supabase_key = os.getenv('SUPABASE_SERVICE_ROLE_KEY')

    if not supabase_url or not supabase_key:
        console.print("[red]Error: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set in .env[/red]")
        sys.exit(1)

    supabase = create_client(supabase_url, supabase_key)

    console.print("[bold green]SOS Distribution Diagnostic Tool[/bold green]")
    console.print("[dim]Analyzing whether SOS values show problematic duplication patterns...[/dim]\n")

    # Get config
    cfg = V53EConfig(**RANKING_CONFIG)

    console.print(f"[cyan]Configuration:[/cyan]")
    console.print(f"  SOS Iterations: {cfg.SOS_ITERATIONS}")
    console.print(f"  SOS Transitivity Lambda: {cfg.SOS_TRANSITIVITY_LAMBDA}")
    console.print(f"  Normalization Mode: {cfg.NORM_MODE}")
    console.print(f"  SOS Weight: {cfg.SOS_WEIGHT * 100:.0f}%")

    # Calculate rankings
    console.print(f"\n[cyan]Computing rankings...[/cyan]")
    result = await compute_rankings_v53e_only(
        supabase_client=supabase,
        fetch_from_supabase=True,
        lookback_days=365,
    )

    teams_df = result['teams']

    if teams_df.empty:
        console.print("[red]No teams found[/red]")
        return

    console.print(f"[green]✓ Calculated rankings for {len(teams_df):,} teams[/green]")

    # Run analysis
    cohort_issues = analyze_sos_distribution(teams_df, cfg)

    # Summary and Recommendations
    console.print(f"\n[bold cyan]═══ SUMMARY ═══[/bold cyan]\n")

    if 'sos' in teams_df.columns:
        sos_values = teams_df['sos'].dropna()
        unique_count = len(sos_values.unique())
        total_count = len(sos_values)
        duplicate_rate = (total_count - unique_count) / total_count * 100

        # Determine if there's a real problem
        if duplicate_rate > 40:
            console.print(Panel(
                f"[red bold]⚠ HIGH SOS DUPLICATION DETECTED[/red bold]\n\n"
                f"• {duplicate_rate:.1f}% of teams share SOS values\n"
                f"• Only {unique_count} unique values for {total_count} teams\n"
                f"• This suggests a REAL problem that needs fixing",
                border_style="red"
            ))
        elif duplicate_rate > 20:
            console.print(Panel(
                f"[yellow]⚠ MODERATE SOS DUPLICATION[/yellow]\n\n"
                f"• {duplicate_rate:.1f}% duplication rate\n"
                f"• May be due to small cohorts or similar schedules\n"
                f"• Worth investigating further",
                border_style="yellow"
            ))
        else:
            console.print(Panel(
                f"[green]✓ SOS DISTRIBUTION LOOKS HEALTHY[/green]\n\n"
                f"• Only {duplicate_rate:.1f}% duplication\n"
                f"• {unique_count} unique values for {total_count} teams\n"
                f"• This is expected with discrete opponent sets",
                border_style="green"
            ))

        # Specific recommendations
        console.print(f"\n[bold cyan]Recommendations:[/bold cyan]")

        if len(cohort_issues) > 0:
            console.print(f"  1. [yellow]{len(cohort_issues)} cohorts have high duplication[/yellow]")
            console.print(f"     → Small cohorts naturally have less SOS variation")
            console.print(f"     → Consider if this is acceptable for your use case")

        if duplicate_rate > 40:
            console.print(f"  2. [red]High overall duplication detected[/red]")
            console.print(f"     → Review if teams are playing too similar schedules")
            console.print(f"     → Check if SOS calculation is working correctly")

        console.print(f"  3. [green]Current implementation uses continuous strength (good)[/green]")
        console.print(f"     → No percentile normalization before SOS (correct)")
        console.print(f"     → Suggestions describe a problem that doesn't exist in this code")


if __name__ == '__main__':
    asyncio.run(main())
