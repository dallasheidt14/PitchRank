#!/usr/bin/env python3
"""
Backfill point-in-time prediction_feature_history snapshots.

This replays historical ranking dates using the current ranking pipeline with
an as-of date, then persists only predictor feature snapshots. It does not
rewrite rankings_full/current_rankings, and it deliberately skips persisting
historical game residuals back onto the live games table.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table
from supabase.lib.client_options import SyncClientOptions

from supabase import create_client

sys.path.append(str(Path(__file__).parent.parent))

from src.rankings.calculator import compute_all_cohorts
from src.rankings.layer13_predictive_adjustment import Layer13Config
from src.rankings.prediction_feature_history import save_prediction_feature_snapshot
from src.utils.merge_resolver import MergeResolver

logging.basicConfig(level=logging.INFO, format="%(message)s", handlers=[logging.StreamHandler()])
logger = logging.getLogger(__name__)

logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

console = Console()

WEEKDAY_LOOKUP = {
    "mon": 0,
    "monday": 0,
    "tue": 1,
    "tues": 1,
    "tuesday": 1,
    "wed": 2,
    "wednesday": 2,
    "thu": 3,
    "thur": 3,
    "thurs": 3,
    "thursday": 3,
    "fri": 4,
    "friday": 4,
    "sat": 5,
    "saturday": 5,
    "sun": 6,
    "sunday": 6,
}


def parse_iso_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(f"Invalid date '{value}'. Expected YYYY-MM-DD.") from error


def parse_weekday(value: str) -> int:
    normalized = value.strip().lower()
    if normalized.isdigit():
        weekday = int(normalized)
        if 0 <= weekday <= 6:
            return weekday
        raise argparse.ArgumentTypeError("Weekday integer must be between 0 (Mon) and 6 (Sun).")

    if normalized in WEEKDAY_LOOKUP:
        return WEEKDAY_LOOKUP[normalized]

    raise argparse.ArgumentTypeError(f"Unsupported weekday '{value}'. Use Mon..Sun or 0..6.")


def generate_snapshot_dates(start_date: date, end_date: date, cadence: str, weekday: int) -> list[date]:
    if end_date < start_date:
        raise ValueError("end_date must be on or after start_date")

    if cadence == "daily":
        dates: list[date] = []
        current = start_date
        while current <= end_date:
            dates.append(current)
            current += timedelta(days=1)
        return dates

    days_until_weekday = (weekday - start_date.weekday()) % 7
    current = start_date + timedelta(days=days_until_weekday)
    dates = []
    while current <= end_date:
        dates.append(current)
        current += timedelta(days=7)
    return dates


async def prediction_snapshot_exists(supabase_client, snapshot_date: date) -> bool:
    response = (
        supabase_client.table("prediction_feature_history")
        .select("snapshot_date")
        .eq("snapshot_date", snapshot_date.isoformat())
        .limit(1)
        .execute()
    )
    return bool(response.data)


async def replay_prediction_snapshot(
    supabase_client,
    merge_resolver: MergeResolver,
    snapshot_date: date,
    lookback_days: int,
    provider_filter: str | None,
    use_glicko: bool,
    ml_enabled: bool,
    force_rebuild: bool,
    dry_run: bool,
) -> tuple[int, int]:
    snapshot_ts = pd.Timestamp(snapshot_date)
    layer13_cfg = None if ml_enabled else Layer13Config(enabled=False)

    result = await compute_all_cohorts(
        supabase_client=supabase_client,
        today=snapshot_ts,
        layer13_cfg=layer13_cfg,
        fetch_from_supabase=True,
        lookback_days=lookback_days,
        provider_filter=provider_filter,
        force_rebuild=force_rebuild,
        merge_resolver=merge_resolver,
        use_glicko=use_glicko,
        persist_game_residuals=False,
        calculate_rank_changes=False,
        save_snapshot=False,
    )

    teams_df = result["teams"]
    if teams_df.empty:
        return 0, 0

    if dry_run:
        return len(teams_df), len(teams_df)

    saved = await save_prediction_feature_snapshot(
        supabase_client=supabase_client,
        rankings_df=teams_df,
        snapshot_date=snapshot_date,
    )
    return len(teams_df), saved


async def main() -> None:
    parser = argparse.ArgumentParser(description="Replay historical prediction feature snapshots")
    parser.add_argument("--start-date", type=parse_iso_date, required=True, help="Inclusive start date (YYYY-MM-DD)")
    parser.add_argument("--end-date", type=parse_iso_date, required=True, help="Inclusive end date (YYYY-MM-DD)")
    parser.add_argument(
        "--cadence",
        choices=["weekly", "daily"],
        default="weekly",
        help="Replay cadence. Weekly is the practical default.",
    )
    parser.add_argument(
        "--weekday",
        type=parse_weekday,
        default=0,
        help="Weekday for weekly cadence. Accepts Mon..Sun or 0..6 where 0=Mon.",
    )
    parser.add_argument("--lookback-days", type=int, default=365, help="Ranking lookback window (default: 365)")
    parser.add_argument("--provider", type=str, default=None, help="Optional provider filter")
    parser.add_argument("--engine", choices=["glicko", "v53e"], default="glicko", help="Ranking engine")
    parser.add_argument("--disable-ml", action="store_true", help="Disable Layer 13 during replay")
    parser.add_argument("--force-rebuild", action="store_true", help="Ignore cached cohort results")
    parser.add_argument("--dry-run", action="store_true", help="Compute replay dates without writing snapshots")
    parser.add_argument(
        "--overwrite-existing",
        action="store_true",
        help="Replay dates even if prediction_feature_history already has rows for that date",
    )
    parser.add_argument(
        "--max-snapshots",
        type=int,
        default=None,
        help="Optional cap on how many snapshot dates to process after filtering/skipping",
    )
    parser.add_argument(
        "--stop-on-error",
        action="store_true",
        help="Abort the backfill immediately on the first failed snapshot date",
    )

    args = parser.parse_args()

    env_local = Path(".env.local")
    if env_local.exists():
        load_dotenv(env_local, override=True)
    else:
        load_dotenv()

    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not supabase_url or not supabase_key:
        console.print("[red]Error: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set[/red]")
        sys.exit(1)

    supabase_client = create_client(
        supabase_url,
        supabase_key,
        options=SyncClientOptions(postgrest_client_timeout=360),
    )

    merge_resolver = MergeResolver(supabase_client)
    merge_resolver.load_merge_map()

    candidate_dates = generate_snapshot_dates(
        start_date=args.start_date,
        end_date=args.end_date,
        cadence=args.cadence,
        weekday=args.weekday,
    )

    if args.max_snapshots is not None:
        candidate_dates = candidate_dates[: args.max_snapshots]

    if not candidate_dates:
        console.print("[yellow]No snapshot dates selected[/yellow]")
        return

    summary = Table(title="Replay Plan")
    summary.add_column("Setting")
    summary.add_column("Value")
    summary.add_row("Start", args.start_date.isoformat())
    summary.add_row("End", args.end_date.isoformat())
    summary.add_row("Cadence", args.cadence)
    summary.add_row("Weekday", str(args.weekday))
    summary.add_row("Dates", str(len(candidate_dates)))
    summary.add_row("Lookback", str(args.lookback_days))
    summary.add_row("Engine", args.engine)
    summary.add_row("ML", "disabled" if args.disable_ml else "enabled")
    summary.add_row("Dry run", "yes" if args.dry_run else "no")
    console.print(summary)

    processed = 0
    skipped_existing = 0
    failed_dates: list[str] = []
    total_saved_rows = 0

    for snapshot_date in candidate_dates:
        if not args.overwrite_existing:
            if await prediction_snapshot_exists(supabase_client, snapshot_date):
                skipped_existing += 1
                console.print(f"[dim]Skipping {snapshot_date.isoformat()} (already backfilled)[/dim]")
                continue

        console.print(f"\n[bold]Replaying {snapshot_date.isoformat()}[/bold]")
        try:
            team_count, saved_rows = await replay_prediction_snapshot(
                supabase_client=supabase_client,
                merge_resolver=merge_resolver,
                snapshot_date=snapshot_date,
                lookback_days=args.lookback_days,
                provider_filter=args.provider,
                use_glicko=(args.engine == "glicko"),
                ml_enabled=not args.disable_ml,
                force_rebuild=args.force_rebuild,
                dry_run=args.dry_run,
            )

            if team_count == 0:
                console.print(f"[yellow]No teams produced for {snapshot_date.isoformat()}[/yellow]")
            else:
                mode_label = "would save" if args.dry_run else "saved"
                console.print(
                    f"[green]{snapshot_date.isoformat()} complete:[/green] "
                    f"{team_count:,} teams processed, {mode_label} {saved_rows:,} snapshot rows"
                )
                total_saved_rows += saved_rows
            processed += 1
        except Exception as error:
            failed_dates.append(snapshot_date.isoformat())
            console.print(f"[red]{snapshot_date.isoformat()} failed:[/red] {error}")
            if args.stop_on_error:
                break

    console.print("\n[bold]Replay Summary[/bold]")
    console.print(f"Processed dates: {processed}")
    console.print(f"Skipped existing: {skipped_existing}")
    console.print(f"Failed dates: {len(failed_dates)}")
    console.print(f"Snapshot rows {'planned' if args.dry_run else 'saved'}: {total_saved_rows:,}")
    if failed_dates:
        console.print(f"[yellow]Failed date list:[/yellow] {', '.join(failed_dates)}")

    if failed_dates:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
