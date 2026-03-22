#!/usr/bin/env python3
"""Profile the ranking calculation pipeline.

Instruments the full v53e + ML Layer 13 pipeline with CPU, memory, timing,
and database query profiling. Generates a comprehensive report.

Usage:
    # Full profile (CPU + memory + timing + DB)
    python scripts/profile_rankings.py

    # CPU only (lighter weight)
    python scripts/profile_rankings.py --cpu-only

    # Memory only (with leak detection)
    python scripts/profile_rankings.py --memory-only

    # Timing only (minimal overhead)
    python scripts/profile_rankings.py --timing-only

    # Dry run (no DB writes, profile computation only)
    python scripts/profile_rankings.py --dry-run

    # Custom lookback
    python scripts/profile_rankings.py --lookback-days 180

    # Output to specific file
    python scripts/profile_rankings.py --output data/profiles/custom_report.json
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from src.profiling.cpu_profiler import CpuProfiler
from src.profiling.memory_profiler import MemoryProfiler
from src.profiling.timer import TimingReport
from src.profiling.db_profiler import QueryProfiler
from src.profiling.reporter import ProfileReport

console = Console()
logger = logging.getLogger(__name__)


def parse_args():
    parser = argparse.ArgumentParser(description="Profile PitchRank ranking pipeline")
    parser.add_argument("--cpu-only", action="store_true", help="CPU profiling only")
    parser.add_argument("--memory-only", action="store_true", help="Memory profiling only")
    parser.add_argument("--timing-only", action="store_true", help="Timing only (minimal overhead)")
    parser.add_argument("--dry-run", action="store_true", help="Don't write to database")
    parser.add_argument("--lookback-days", type=int, default=365, help="Lookback window (days)")
    parser.add_argument("--ml", action="store_true", default=True, help="Include ML Layer 13")
    parser.add_argument("--no-ml", action="store_true", help="Skip ML Layer 13")
    parser.add_argument("--output", type=str, help="Output file path")
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Verbose logging"
    )
    return parser.parse_args()


async def run_profiled_ranking(args):
    """Run the ranking pipeline with full instrumentation."""

    # Determine which profilers to enable
    profile_all = not (args.cpu_only or args.memory_only or args.timing_only)
    enable_cpu = profile_all or args.cpu_only
    enable_memory = profile_all or args.memory_only
    enable_timing = True  # Always enable timing
    enable_db = profile_all

    use_ml = args.ml and not args.no_ml

    console.print(Panel(
        f"[bold]PitchRank Performance Profiler[/bold]\n\n"
        f"  CPU:      {'ON' if enable_cpu else 'OFF'}\n"
        f"  Memory:   {'ON' if enable_memory else 'OFF'}\n"
        f"  Timing:   {'ON' if enable_timing else 'OFF'}\n"
        f"  DB:       {'ON' if enable_db else 'OFF'}\n"
        f"  ML:       {'ON' if use_ml else 'OFF'}\n"
        f"  Lookback: {args.lookback_days} days\n"
        f"  Dry run:  {args.dry_run}",
        title="Configuration",
        border_style="green",
    ))

    # Initialize profilers
    timing = TimingReport("Ranking Pipeline")
    cpu = CpuProfiler("ranking_pipeline", enabled=enable_cpu)
    memory = MemoryProfiler("ranking_pipeline", enabled=enable_memory)
    db = QueryProfiler() if enable_db else None

    report = ProfileReport("Ranking Pipeline Profile")

    # ── Step 1: Initialize client ──────────────────────────────────
    with timing.section("initialize"):
        try:
            from dotenv import load_dotenv
            load_dotenv()

            from supabase import create_client
            import os

            supabase_url = os.getenv("SUPABASE_URL")
            supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY")

            if not supabase_url or not supabase_key:
                console.print("[red]Missing SUPABASE_URL or SUPABASE_KEY in environment[/red]")
                console.print("Set them in .env or export them.")
                console.print("\n[yellow]Running in dry-run mode with synthetic data...[/yellow]")
                return await run_synthetic_profile(args, timing, cpu, memory, report)

            client = create_client(supabase_url, supabase_key)
            if db:
                client = db.wrap(client)

        except ImportError as e:
            console.print(f"[yellow]Import error: {e}[/yellow]")
            console.print("[yellow]Running in dry-run mode with synthetic data...[/yellow]")
            return await run_synthetic_profile(args, timing, cpu, memory, report)

    # ── Step 2: Fetch games ────────────────────────────────────────
    console.print("\n[bold]Fetching games...[/bold]")
    with timing.section("fetch_games"):
        try:
            from src.rankings.data_adapter import fetch_games_for_rankings
            from src.utils.merge_resolver import MergeResolver

            merge_resolver = MergeResolver(client)
            games_df = await fetch_games_for_rankings(
                client,
                lookback_days=args.lookback_days,
                merge_resolver=merge_resolver,
            )
            game_count = len(games_df) if games_df is not None else 0
            console.print(f"  Fetched {game_count:,} games")
            report.add_custom("game_count", game_count)
        except Exception as e:
            console.print(f"[red]Error fetching games: {e}[/red]")
            return

    # ── Step 3: Compute rankings (profiled) ────────────────────────
    console.print("\n[bold]Computing rankings (v53e)...[/bold]")
    with cpu, memory:
        with timing.section("v53e_computation"):
            try:
                from src.etl.v53e import compute_rankings, V53EConfig
                cfg = V53EConfig()
                rankings = compute_rankings(games_df, cfg=cfg)
                teams_df = rankings["teams"] if rankings else None
                team_count = len(teams_df) if teams_df is not None else 0
                console.print(f"  Computed rankings for {team_count:,} teams")
                report.add_custom("team_count", team_count)
            except Exception as e:
                console.print(f"[red]Error computing rankings: {e}[/red]")
                return

    # ── Step 4: ML Layer 13 ────────────────────────────────────────
    if use_ml and teams_df is not None and not teams_df.empty:
        console.print("\n[bold]Applying ML Layer 13...[/bold]")
        with timing.section("ml_layer_13"):
            try:
                from src.rankings.layer13_predictive_adjustment import (
                    apply_predictive_adjustment, Layer13Config,
                )
                ml_config = Layer13Config()
                ml_result = await apply_predictive_adjustment(
                    supabase_client=client,
                    teams_df=teams_df,
                    games_used_df=games_df,
                    cfg=ml_config,
                )
                console.print("  ML Layer 13 applied")
            except Exception as e:
                console.print(f"[yellow]ML Layer 13 error: {e}[/yellow]")

    # ── Step 5: Assemble report ────────────────────────────────────
    report.add_timing(timing)
    report.add_cpu(cpu)
    report.add_memory(memory)
    if db:
        report.add_db(db)

    # Print summary
    summary = report.print_summary()
    console.print(summary)

    # Save
    output_path = args.output or None
    saved = report.save(output_path)
    console.print(f"\n[green]Report saved: {saved}[/green]")

    return report


async def run_synthetic_profile(args, timing, cpu, memory, report):
    """Run profiling with synthetic data when DB is unavailable."""
    import numpy as np
    import pandas as pd

    console.print("\n[bold cyan]Generating synthetic game data...[/bold cyan]")

    num_teams = 500
    num_games = 5000

    with timing.section("generate_synthetic_data"):
        np.random.seed(42)
        team_ids = [f"team_{i:04d}" for i in range(num_teams)]
        games = []
        for _ in range(num_games):
            home = np.random.choice(team_ids)
            away = np.random.choice([t for t in team_ids if t != home])
            games.append({
                "home_team_id": home,
                "away_team_id": away,
                "home_score": int(np.random.poisson(1.5)),
                "away_score": int(np.random.poisson(1.2)),
                "game_date": pd.Timestamp("2025-06-01") + pd.Timedelta(
                    days=int(np.random.uniform(0, 365))
                ),
                "age_group": str(np.random.choice([10, 11, 12, 13, 14, 15, 16, 17])),
                "gender": np.random.choice(["Male", "Female"]),
            })
        games_df = pd.DataFrame(games)
        report.add_custom("game_count", len(games_df))
        report.add_custom("team_count", num_teams)
        report.add_custom("mode", "synthetic")

    console.print(f"  Generated {num_games:,} games for {num_teams} teams")

    console.print("\n[bold]Computing rankings (v53e) on synthetic data...[/bold]")
    with cpu, memory:
        with timing.section("v53e_computation"):
            try:
                from src.etl.v53e import compute_rankings, V53EConfig
                cfg = V53EConfig()
                rankings = compute_rankings(games_df, cfg=cfg)
                teams_df = rankings["teams"] if rankings else None
                team_count = len(teams_df) if teams_df is not None else 0
                console.print(f"  Computed rankings for {team_count:,} teams")
            except Exception as e:
                console.print(f"[yellow]v53e computation error (expected without full env): {e}[/yellow]")
                console.print("  Profiling timing data captured")

    report.add_timing(timing)
    report.add_cpu(cpu)
    report.add_memory(memory)

    summary = report.print_summary()
    console.print(summary)

    output_path = args.output or None
    saved = report.save(output_path)
    console.print(f"\n[green]Report saved: {saved}[/green]")

    return report


def main():
    args = parse_args()

    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    console.print("\n[bold green]PitchRank Performance Profiler[/bold green]\n")

    try:
        asyncio.run(run_profiled_ranking(args))
    except KeyboardInterrupt:
        console.print("\n[yellow]Profiling interrupted[/yellow]")
    except Exception as e:
        console.print(f"\n[red]Profiling error: {e}[/red]")
        if args.verbose:
            import traceback
            traceback.print_exc()


if __name__ == "__main__":
    main()
