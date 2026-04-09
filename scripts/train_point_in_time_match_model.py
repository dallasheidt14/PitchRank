"""
Train the offline point-in-time match model from prediction_feature_history.

This harness is the first step toward replacing the live heuristic predictor.
It only reads historical games plus point-in-time feature snapshots and writes
model artifacts; it does not change production compare behavior.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

env_local = Path(".env.local")
if env_local.exists():
    load_dotenv(env_local, override=True)
else:
    load_dotenv()

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts.backtest_predictor import (  # noqa: E402
    build_snapshot_index,
    fetch_historical_games,
    fetch_prediction_feature_snapshots,
    fetch_team_names,
)
from src.predictions.point_in_time_match_model import (  # noqa: E402
    DatasetBuildResult,
    PointInTimeMatchModel,
    build_point_in_time_dataset,
)
from supabase import create_client  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def _write_json(path: Path, payload: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


async def main():
    parser = argparse.ArgumentParser(description="Train point-in-time match model from predictor snapshots")
    parser.add_argument("--lookback-days", type=int, default=365, help="Historical game window to fetch")
    parser.add_argument(
        "--limit",
        type=lambda value: None if str(value).lower() == "none" else int(value),
        default=None,
        help='Maximum number of games to fetch (default: all, use "None" for no limit)',
    )
    parser.add_argument(
        "--test-slice",
        nargs=2,
        metavar=("STATE", "AGE_GROUP"),
        help="Optional slice for smoke tests, e.g. --test-slice AZ u12",
    )
    parser.add_argument("--test-ratio", type=float, default=0.2, help="Chronological holdout ratio")
    parser.add_argument("--min-examples", type=int, default=100, help="Minimum dataset size required to train")
    parser.add_argument(
        "--probability-strategy",
        choices=["auto", "hybrid", "poisson_primary", "poisson_draw_gate"],
        default="auto",
        help="Outcome probability composition strategy to use or select",
    )
    parser.add_argument(
        "--min-draw-recall",
        type=float,
        default=0.08,
        help="Minimum draw recall for auto strategy selection",
    )
    parser.add_argument(
        "--max-draw-rate-gap",
        type=float,
        default=0.08,
        help="Maximum absolute gap between predicted and actual draw rate for auto strategy selection",
    )
    parser.add_argument(
        "--winner-accuracy-tolerance",
        type=float,
        default=0.015,
        help="Maximum winner-accuracy drop allowed from the best candidate during auto selection",
    )
    parser.add_argument(
        "--log-loss-tolerance",
        type=float,
        default=0.003,
        help="Maximum log-loss regression allowed from the best candidate during auto selection",
    )
    parser.add_argument(
        "--model-dir",
        default="models/point_in_time_match_predictor",
        help="Directory to write model artifacts and reports",
    )
    parser.add_argument(
        "--save-dataset",
        action="store_true",
        help="Persist the built training frame to CSV for inspection",
    )
    args = parser.parse_args()

    supabase_url = os.getenv("SUPABASE_URL") or os.getenv("NEXT_PUBLIC_SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_SERVICE_KEY")
    if not supabase_url or not supabase_key:
        logger.error("Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY environment variables")
        sys.exit(1)

    supabase = create_client(supabase_url, supabase_key)
    logger.info("Connected to Supabase")

    test_slice = tuple(args.test_slice) if args.test_slice else None
    games_df = await fetch_historical_games(
        supabase,
        lookback_days=args.lookback_days,
        limit=args.limit,
        test_slice=test_slice,
    )
    if games_df.empty:
        logger.error("No historical games found")
        sys.exit(1)

    team_ids = sorted(
        set(games_df["home_team_master_id"].dropna().astype(str)).union(
            set(games_df["away_team_master_id"].dropna().astype(str))
        )
    )
    snapshot_start = (pd.Timestamp(games_df["game_date"].min()) - pd.Timedelta(days=30)).strftime("%Y-%m-%d")
    snapshot_end = pd.Timestamp(games_df["game_date"].max()).strftime("%Y-%m-%d")
    snapshots_df = await fetch_prediction_feature_snapshots(supabase, team_ids, snapshot_start, snapshot_end)
    if snapshots_df.empty:
        logger.error("No point-in-time snapshots found in prediction_feature_history")
        sys.exit(1)

    snapshot_index = build_snapshot_index(snapshots_df)
    team_names = await fetch_team_names(supabase, team_ids)

    logger.info(
        "Building point-in-time dataset from %s games, %s snapshots, and %s teams",
        f"{len(games_df):,}",
        f"{len(snapshots_df):,}",
        f"{len(team_ids):,}",
    )
    dataset_result: DatasetBuildResult = build_point_in_time_dataset(
        games_df,
        snapshot_index=snapshot_index,
        team_names=team_names,
        include_mirrored_examples=True,
    )

    model_dir = Path(args.model_dir)
    model_dir.mkdir(parents=True, exist_ok=True)

    summary_path = model_dir / "dataset_summary.json"
    _write_json(summary_path, dataset_result.summary)
    logger.info("Dataset summary saved to %s", summary_path)
    logger.info("Dataset summary: %s", dataset_result.summary)

    if args.save_dataset and not dataset_result.dataset.empty:
        dataset_path = model_dir / "training_dataset.csv"
        dataset_result.dataset.to_csv(dataset_path, index=False)
        logger.info("Training dataset saved to %s", dataset_path)

    if dataset_result.dataset.empty:
        logger.warning("Dataset builder produced zero examples. Nothing to train yet.")
        return

    if len(dataset_result.dataset) < args.min_examples:
        logger.warning(
            "Built only %s examples, below the training threshold of %s. "
            "Harness is ready, but the backfill needs more coverage before this model is meaningful.",
            f"{len(dataset_result.dataset):,}",
            f"{args.min_examples:,}",
        )
        return

    model = PointInTimeMatchModel(model_dir=str(model_dir))
    metrics = model.train(
        dataset_result.dataset,
        test_ratio=args.test_ratio,
        min_examples=args.min_examples,
        probability_strategy=args.probability_strategy,
        strategy_constraints={
            "min_draw_recall": args.min_draw_recall,
            "max_draw_rate_gap": args.max_draw_rate_gap,
            "winner_accuracy_tolerance": args.winner_accuracy_tolerance,
            "log_loss_tolerance": args.log_loss_tolerance,
        },
    )
    artifact_paths = model.save()
    evaluation_report = model.write_evaluation_report(str(model_dir), prefix="point_in_time_model")

    metrics_path = model_dir / "training_metrics.json"
    _write_json(metrics_path, metrics)
    logger.info("Training metrics saved to %s", metrics_path)
    logger.info("Saved model artifacts: %s", artifact_paths)
    logger.info("Saved evaluation report: %s", evaluation_report)


if __name__ == "__main__":
    asyncio.run(main())
