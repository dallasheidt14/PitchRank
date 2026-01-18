#!/usr/bin/env python3
"""
Diagnostic script to analyze why top teams from different states
might have similar power scores.

This will help identify whether the issue is:
1. Ceiling clipping (powerscore_adj > 1.0 getting clipped)
2. SOS not differentiating states properly
3. Data quality issues
"""
import asyncio
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

import pandas as pd
from dotenv import load_dotenv
import os
from supabase import create_client
from rich.console import Console
from rich.table import Table

load_dotenv(Path('.env.local') if Path('.env.local').exists() else Path('.env'))
console = Console()


async def main():
    supabase_url = os.getenv('SUPABASE_URL')
    supabase_key = os.getenv('SUPABASE_SERVICE_ROLE_KEY')

    if not supabase_url or not supabase_key:
        console.print("[red]Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY[/red]")
        return

    supabase = create_client(supabase_url, supabase_key)

    # Fetch rankings_full data with team metadata
    console.print("[bold]Fetching rankings data...[/bold]")

    result = supabase.table('rankings_full').select(
        'team_id, age_group, gender, state_code, '
        'power_score_final, powerscore_adj, powerscore_core, '
        'sos, sos_norm, sos_raw, '
        'off_norm, def_norm, perf_centered, '
        'rank_in_cohort, status'
    ).eq('status', 'Active').execute()

    if not result.data:
        console.print("[red]No data found[/red]")
        return

    df = pd.DataFrame(result.data)
    console.print(f"[green]Loaded {len(df):,} active teams[/green]\n")

    # =========================================================
    # DIAGNOSTIC 1: Ceiling Clipping Analysis
    # =========================================================
    console.print("[bold cyan]═══ DIAGNOSTIC 1: Ceiling Clipping Analysis ═══[/bold cyan]")

    if 'powerscore_adj' in df.columns:
        ceiling_teams = df[df['powerscore_adj'] >= 0.99]
        console.print(f"Teams with powerscore_adj >= 0.99: {len(ceiling_teams):,}")

        if 'powerscore_core' in df.columns:
            exceeds_1 = df[df['powerscore_core'] > 1.0]
            console.print(f"Teams with powerscore_core > 1.0 (pre-clip): {len(exceeds_1):,}")

            if len(exceeds_1) > 0:
                console.print("\n[yellow]⚠️  CEILING CLIPPING CONFIRMED[/yellow]")
                console.print(f"   Max powerscore_core: {df['powerscore_core'].max():.4f}")

    # =========================================================
    # DIAGNOSTIC 2: Top Teams by State Comparison
    # =========================================================
    console.print("\n[bold cyan]═══ DIAGNOSTIC 2: Top Team Power Scores by State ═══[/bold cyan]")

    # Pick a specific cohort for analysis
    test_cohorts = [('u14', 'Male'), ('u13', 'Male'), ('u12', 'Female')]

    for age_group, gender in test_cohorts:
        cohort_df = df[(df['age_group'] == age_group) & (df['gender'] == gender)]

        if len(cohort_df) < 10:
            continue

        console.print(f"\n[bold]{age_group} {gender}[/bold] ({len(cohort_df):,} teams)")

        # Get top team per state
        top_by_state = cohort_df.loc[
            cohort_df.groupby('state_code')['power_score_final'].idxmax()
        ].sort_values('power_score_final', ascending=False).head(15)

        table = Table(title=f"Top Team per State - {age_group} {gender}")
        table.add_column("State", style="cyan")
        table.add_column("Power Final", justify="right")
        table.add_column("PS Adj", justify="right")
        table.add_column("SOS Norm", justify="right")
        table.add_column("SOS Raw", justify="right")
        table.add_column("Off Norm", justify="right")
        table.add_column("Def Norm", justify="right")

        for _, row in top_by_state.iterrows():
            table.add_row(
                str(row.get('state_code', '?'))[:5],
                f"{row.get('power_score_final', 0):.4f}",
                f"{row.get('powerscore_adj', 0):.4f}",
                f"{row.get('sos_norm', 0):.3f}",
                f"{row.get('sos_raw', row.get('sos', 0)):.3f}",
                f"{row.get('off_norm', 0):.3f}",
                f"{row.get('def_norm', 0):.3f}",
            )

        console.print(table)

        # Check for identical power scores
        top_scores = top_by_state['power_score_final'].round(4)
        duplicates = top_scores.value_counts()
        multi_state_same_score = duplicates[duplicates > 1]

        if len(multi_state_same_score) > 0:
            console.print(f"\n[red]⚠️  IDENTICAL POWER SCORES FOUND:[/red]")
            for score, count in multi_state_same_score.items():
                states = top_by_state[top_by_state['power_score_final'].round(4) == score]['state_code'].tolist()
                console.print(f"   Score {score}: {count} states ({', '.join(str(s) for s in states)})")

    # =========================================================
    # DIAGNOSTIC 3: SOS Distribution Analysis
    # =========================================================
    console.print("\n[bold cyan]═══ DIAGNOSTIC 3: SOS Distribution by State ═══[/bold cyan]")

    for age_group, gender in test_cohorts:
        cohort_df = df[(df['age_group'] == age_group) & (df['gender'] == gender)]

        if len(cohort_df) < 10:
            continue

        console.print(f"\n[bold]{age_group} {gender}[/bold]")

        # SOS stats by state (top 10 states by team count)
        state_counts = cohort_df['state_code'].value_counts().head(10)

        table = Table(title="SOS Stats by State (Top 10 by team count)")
        table.add_column("State")
        table.add_column("Teams", justify="right")
        table.add_column("Avg SOS Norm", justify="right")
        table.add_column("Max SOS Norm", justify="right")
        table.add_column("Avg Raw SOS", justify="right")
        table.add_column("Max Raw SOS", justify="right")

        for state in state_counts.index:
            state_df = cohort_df[cohort_df['state_code'] == state]
            sos_col = 'sos_raw' if 'sos_raw' in state_df.columns else 'sos'

            table.add_row(
                str(state)[:5],
                str(len(state_df)),
                f"{state_df['sos_norm'].mean():.3f}",
                f"{state_df['sos_norm'].max():.3f}",
                f"{state_df[sos_col].mean():.3f}" if sos_col in state_df.columns else "N/A",
                f"{state_df[sos_col].max():.3f}" if sos_col in state_df.columns else "N/A",
            )

        console.print(table)

        # Check if raw SOS differentiates states but sos_norm doesn't
        sos_col = 'sos_raw' if 'sos_raw' in cohort_df.columns else 'sos'
        if sos_col in cohort_df.columns:
            raw_sos_range = cohort_df[sos_col].max() - cohort_df[sos_col].min()
            norm_sos_range = cohort_df['sos_norm'].max() - cohort_df['sos_norm'].min()
            console.print(f"   Raw SOS range: {raw_sos_range:.4f}")
            console.print(f"   Norm SOS range: {norm_sos_range:.4f}")

    # =========================================================
    # DIAGNOSTIC 4: Formula Verification
    # =========================================================
    console.print("\n[bold cyan]═══ DIAGNOSTIC 4: PowerScore Formula Check ═══[/bold cyan]")

    sample = df.dropna(subset=['off_norm', 'def_norm', 'sos_norm']).head(100)

    if len(sample) > 0:
        # Recalculate powerscore_core to verify formula
        sample['calc_core'] = (
            0.25 * sample['off_norm'] +
            0.25 * sample['def_norm'] +
            0.50 * sample['sos_norm'] +
            0.15 * sample.get('perf_centered', 0).fillna(0)
        )

        if 'powerscore_core' in sample.columns:
            diff = (sample['calc_core'] - sample['powerscore_core']).abs()
            console.print(f"Formula verification (calc vs stored):")
            console.print(f"   Max difference: {diff.max():.6f}")
            console.print(f"   Mean difference: {diff.mean():.6f}")

        console.print(f"\nTheoretical max powerscore_core: 1.075")
        console.print(f"Actual max in data: {sample['calc_core'].max():.4f}")

    console.print("\n[bold green]Diagnostic complete![/bold green]")


if __name__ == '__main__':
    asyncio.run(main())
