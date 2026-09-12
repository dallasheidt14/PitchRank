#!/usr/bin/env python3
"""Run exact-format cohort backtests from one reviewed local intake JSON."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.tournaments.backtest_intake_state import BacktestSnapshot
from src.tournaments.backtest_link_store import CollisionAcknowledgement, EventLinks, TeamLink, load_links
from src.tournaments.backtest_request import build_cohort_backtest_requests


def _slug(value: str) -> str:
    return "_".join(part for part in "".join(c.lower() if c.isalnum() else " " for c in value).split())


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _embedded_links(payload: dict[str, Any], *, event_id: str) -> EventLinks:
    raw = payload.get("links") or {}
    if not isinstance(raw, dict) or str(raw.get("event_id") or "") != event_id:
        return EventLinks()
    return EventLinks(
        event_id=event_id,
        links=tuple(TeamLink(**item) for item in raw.get("links") or ()),
        saved_at=str(raw.get("saved_at") or ""),
        removed_registration_ids=tuple(str(item) for item in raw.get("removed_registration_ids") or ()),
        not_found_registration_ids=tuple(str(item) for item in raw.get("not_found_registration_ids") or ()),
        collision_acknowledgements=tuple(
            CollisionAcknowledgement(
                team_id_master=str(item["team_id_master"]),
                registration_ids=tuple(str(value) for value in item.get("registration_ids") or ()),
                note=str(item["note"]),
                acknowledged_at=str(item["acknowledged_at"]),
            )
            for item in raw.get("collision_acknowledgements") or ()
        ),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--intake-json", required=True, help="Reviewed Backtest event_intake.json or download")
    parser.add_argument("--output-dir", default="reports/reviewed_tournament_backtest")
    parser.add_argument("--predictor-source", choices=("python", "point_in_time"), default="point_in_time")
    parser.add_argument("--point-in-time-model-artifact", default=None)
    parser.add_argument("--history-lookback-days", type=int, default=365)
    parser.add_argument("--snapshot-buffer-days", type=int, default=30)
    args = parser.parse_args()

    intake_path = Path(args.intake_json)
    if not intake_path.exists():
        raise FileNotFoundError(f"Intake JSON not found: {intake_path}")
    intake_payload = json.loads(intake_path.read_text(encoding="utf-8"))
    snapshot = BacktestSnapshot.from_dict(intake_payload)
    links = _embedded_links(intake_payload, event_id=snapshot.roster.event_id)
    if intake_path.name == "event_intake.json" and intake_path.parent.name == "intake":
        event_key = intake_path.parent.parent.name
        links = load_links(event_key, base_dir=intake_path.parent.parent.parent)
    requests = build_cohort_backtest_requests(
        snapshot,
        event_links=links,
    )
    output_dir = Path(args.output_dir)
    request_dir = output_dir / "requests"
    cohort_dir = output_dir / "cohorts"
    results: list[dict[str, Any]] = []

    for request in requests:
        cohort_name = f"{_slug(str(request['age_group']))}_{_slug(str(request['gender']))}"
        request_path = request_dir / f"{cohort_name}.json"
        run_dir = cohort_dir / cohort_name
        _write_json(request_path, request)
        command = [
            sys.executable,
            str(Path(__file__).with_name("backtest_tournament_cohort.py")),
            "--input",
            str(request_path),
            "--output-dir",
            str(run_dir),
            "--predictor-source",
            args.predictor_source,
            "--history-lookback-days",
            str(args.history_lookback_days),
            "--snapshot-buffer-days",
            str(args.snapshot_buffer_days),
        ]
        if args.predictor_source == "point_in_time":
            if not args.point_in_time_model_artifact:
                raise ValueError("--point-in-time-model-artifact is required for point_in_time")
            command.extend(["--point-in-time-model-artifact", str(args.point_in_time_model_artifact)])
        completed = subprocess.run(command, check=False)
        results.append(
            {
                "age_group": request["age_group"],
                "gender": request["gender"],
                "request_path": str(request_path),
                "output_dir": str(run_dir),
                "status": "completed" if completed.returncode == 0 else "failed",
                "return_code": completed.returncode,
            }
        )
        if completed.returncode != 0:
            break

    summary = {
        "event_name": snapshot.roster.event_name,
        "event_id": snapshot.roster.event_id,
        "source_capture_generation": snapshot.generation,
        "cohorts": results,
    }
    _write_json(output_dir / "event_backtest.json", summary)
    return 0 if results and all(item["status"] == "completed" for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
