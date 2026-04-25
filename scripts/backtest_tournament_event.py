#!/usr/bin/env python3
"""Backtest every runnable cohort in one completed tournament event.

This beta helper turns a saved event structure CSV plus completed `games`
rows into cohort-level backtest requests, then runs the existing
`backtest_tournament_cohort.py` flow for each cohort that has complete team
coverage in the imported game data.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import subprocess
import sys
from collections import defaultdict
from copy import deepcopy
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts.backtest_tournament_cohort import _fetch_rows_by_ids, _get_supabase  # noqa: E402
from src.tournaments.event_team_matcher import EventTeamSearchQuery, search_event_team_in_db  # noqa: E402
from src.tournaments.seeding_optimizer import normalize_age_group, normalize_gender_label  # noqa: E402

MIN_SUPPORTED_AGE = 10
MAX_SUPPORTED_AGE = 19


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _slugify(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", value.strip().lower())
    return normalized.strip("_")


def _parse_group_title(group_title: str) -> tuple[str, str, str]:
    prefix, division_name = group_title.split(" - ", 1)
    parts = prefix.split()
    if len(parts) < 2:
        raise ValueError(f"Unexpected group title format: {group_title}")
    gender = normalize_gender_label(parts[0])
    age_group = normalize_age_group(parts[1])
    return age_group, gender, division_name.strip()


def _age_number(age_group: str) -> int | None:
    normalized = normalize_age_group(age_group)
    if not normalized.startswith("u"):
        return None
    try:
        return int(normalized.removeprefix("u"))
    except ValueError:
        return None


def _derive_pool_sizes(team_count: int, bracket_count: int) -> list[int]:
    if bracket_count <= 1:
        return [team_count]
    base_size, remainder = divmod(team_count, bracket_count)
    sizes = [base_size] * bracket_count
    for index in range(remainder):
        sizes[index] += 1
    return sizes


def _load_group_rows(group_structure_csv: Path) -> list[dict[str, Any]]:
    with group_structure_csv.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _load_event_team_registry_rows(event_team_registry_csv: Path | None) -> list[dict[str, Any]]:
    if event_team_registry_csv is None or not event_team_registry_csv.exists():
        return []
    with event_team_registry_csv.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys()) if rows else []
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _fetch_event_games(client, event_name: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    offset = 0
    page_size = 1000
    while True:
        batch = (
            client.table("games")
            .select(
                "id,division_name,game_date,home_team_master_id,away_team_master_id,home_score,away_score"
            )
            .eq("event_name", event_name)
            .eq("is_excluded", False)
            .not_.is_("home_score", "null")
            .not_.is_("away_score", "null")
            .range(offset, offset + page_size - 1)
            .execute()
            .data
            or []
        )
        if not batch:
            break
        rows.extend(batch)
        if len(batch) < page_size:
            break
        offset += page_size
    return rows


def _fetch_rows_by_provider_ids(client, provider_ids: list[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    normalized_ids = [str(provider_id) for provider_id in provider_ids if str(provider_id or "").strip()]
    for start in range(0, len(normalized_ids), 200):
        batch = normalized_ids[start : start + 200]
        if not batch:
            continue
        rows.extend(
            (
                client.table("teams")
                .select("team_id_master,team_name,provider_team_id")
                .in_("provider_team_id", batch)
                .execute()
                .data
            )
            or []
        )
    return rows


def _matcher_query_from_registry_row(row: dict[str, Any]) -> EventTeamSearchQuery:
    return EventTeamSearchQuery(
        event_team_name=str(row.get("event_team_name") or "").strip(),
        event_age_group=str(row.get("event_age_group") or row.get("display_age_group") or "").strip(),
        event_gender=str(row.get("event_gender") or row.get("display_gender") or "").strip(),
        event_club_name=str(row.get("event_club_name") or "").strip() or None,
        search_age_group=str(row.get("search_age_group") or "").strip() or None,
        provider_team_id=str(row.get("resolved_gotsport_provider_team_id") or "").strip() or None,
    )


def _enrich_registry_rows_with_matcher(
    client,
    registry_rows: list[dict[str, Any]],
    *,
    accepted_statuses: set[str] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    accepted_statuses = accepted_statuses or {"direct_provider_id", "strict_exact", "high_confidence"}
    enriched_rows = deepcopy(registry_rows)
    cache: dict[tuple[tuple[str, ...], str, bool], list[dict[str, Any]]] = {}
    status_counts: dict[str, int] = defaultdict(int)

    for row in enriched_rows:
        row.setdefault("matcher_status", "")
        row.setdefault("matcher_best_score", "")
        row.setdefault("matcher_second_score", "")
        row.setdefault("matcher_score_gap", "")
        row.setdefault("matcher_resolved_team_id_master", "")
        row.setdefault("matcher_resolved_team_name", "")
        row.setdefault("matcher_resolved_club_name", "")
        row.setdefault("matcher_resolved_provider_team_id", "")

        if row.get("in_scope_u10_u19") != "True":
            continue

        existing_provider_id = str(row.get("resolved_gotsport_provider_team_id") or "").strip()
        existing_status = str(row.get("canonical_resolution_status") or "").strip()
        if existing_provider_id and existing_status not in {"", "none", "review"}:
            continue

        result = search_event_team_in_db(
            client,
            _matcher_query_from_registry_row(row),
            limit=5,
            cache=cache,
        )
        status_counts[result.resolved_status] += 1
        row["matcher_status"] = result.resolved_status
        row["matcher_best_score"] = "" if result.best_score is None else result.best_score
        row["matcher_second_score"] = "" if result.second_score is None else result.second_score
        row["matcher_score_gap"] = "" if result.score_gap is None else result.score_gap

        if not result.matches:
            continue

        best = result.matches[0]
        row["matcher_resolved_team_id_master"] = best.get("team_id_master", "")
        row["matcher_resolved_team_name"] = best.get("team_name", "")
        row["matcher_resolved_club_name"] = best.get("club_name", "")
        row["matcher_resolved_provider_team_id"] = best.get("provider_team_id", "")

        if result.resolved_status not in accepted_statuses:
            continue

        if not existing_provider_id:
            row["resolved_gotsport_provider_team_id"] = best.get("provider_team_id", "") or existing_provider_id
        if not row.get("resolved_team_id_master"):
            row["resolved_team_id_master"] = best.get("team_id_master", "")
        if not row.get("resolved_team_name"):
            row["resolved_team_name"] = best.get("team_name", "")
        if not row.get("resolved_club_name"):
            row["resolved_club_name"] = best.get("club_name", "")
        row["canonical_resolution_status"] = result.resolved_status

    return enriched_rows, dict(status_counts)


def _cohort_key(age_group: str, gender: str) -> tuple[str, str]:
    return normalize_age_group(age_group), normalize_gender_label(gender)


def _build_event_structure(group_rows: list[dict[str, Any]]) -> dict[tuple[str, str], list[dict[str, Any]]]:
    cohorts: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in group_rows:
        age_group, gender, division_name = _parse_group_title(str(row["group_title"]))
        age_number = _age_number(age_group)
        if age_number is None or age_number < MIN_SUPPORTED_AGE or age_number > MAX_SUPPORTED_AGE:
            continue
        cohorts[_cohort_key(age_group, gender)].append(
            {
                "group_title": str(row["group_title"]),
                "division_name": division_name,
                "team_count": int(row["team_count"]),
                "bracket_count": int(row["bracket_count"]),
                "pool_sizes": _derive_pool_sizes(int(row["team_count"]), int(row["bracket_count"])),
                "group_url": row.get("group_url"),
            }
        )
    for cohort_rows in cohorts.values():
        cohort_rows.sort(key=lambda item: item["group_title"])
    return cohorts


def _build_registry_division_team_map(
    client,
    registry_rows: list[dict[str, Any]],
) -> tuple[dict[str, set[str]], dict[str, int]]:
    provider_ids = sorted(
        {
            str(row.get("resolved_gotsport_provider_team_id") or "").strip()
            for row in registry_rows
            if str(row.get("resolved_gotsport_provider_team_id") or "").strip()
        }
    )
    teams_by_provider_id = {
        str(row["provider_team_id"]): str(row["team_id_master"])
        for row in _fetch_rows_by_provider_ids(client, provider_ids)
        if row.get("provider_team_id") and row.get("team_id_master")
    }
    team_ids_by_division: dict[str, set[str]] = defaultdict(set)
    unresolved_entries_by_division: dict[str, int] = defaultdict(int)
    for row in registry_rows:
        if row.get("in_scope_u10_u19") != "True":
            continue
        group_titles = [item.strip() for item in str(row.get("group_titles") or "").split("|") if item.strip()]
        provider_id = str(row.get("resolved_gotsport_provider_team_id") or "").strip()
        team_id_master = teams_by_provider_id.get(provider_id)
        for group_title in group_titles:
            _, _, division_name = _parse_group_title(group_title)
            if team_id_master:
                team_ids_by_division[division_name].add(team_id_master)
            else:
                unresolved_entries_by_division[division_name] += 1
    return team_ids_by_division, unresolved_entries_by_division


def _build_division_team_map(event_games: list[dict[str, Any]]) -> dict[str, set[str]]:
    teams_by_division: dict[str, set[str]] = defaultdict(set)
    for row in event_games:
        division_name = str(row.get("division_name") or "")
        home_team_id = row.get("home_team_master_id")
        away_team_id = row.get("away_team_master_id")
        if home_team_id:
            teams_by_division[division_name].add(str(home_team_id))
        if away_team_id:
            teams_by_division[division_name].add(str(away_team_id))
    return teams_by_division


def _build_division_game_map(event_games: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    games_by_division: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in event_games:
        division_name = str(row.get("division_name") or "")
        if not division_name:
            continue
        games_by_division[division_name].append(row)
    return games_by_division


def _fetch_orphaned_games_for_team_ids(
    client,
    team_ids: list[str],
    *,
    start_date: str,
    end_date: str,
) -> list[dict[str, Any]]:
    if not team_ids:
        return []
    seen_game_ids: set[str] = set()
    rows: list[dict[str, Any]] = []
    page_size = 1000
    for start in range(0, len(team_ids), 10):
        batch = team_ids[start : start + 10]
        or_filter = ",".join(
            [f"home_team_master_id.eq.{team_id}" for team_id in batch]
            + [f"away_team_master_id.eq.{team_id}" for team_id in batch]
        )
        offset = 0
        while True:
            response = (
                client.table("games")
                .select("id,event_name,division_name,game_date,home_team_master_id,away_team_master_id,home_score,away_score")
                .is_("event_name", "null")
                .gte("game_date", start_date)
                .lte("game_date", end_date)
                .eq("is_excluded", False)
                .not_.is_("home_score", "null")
                .not_.is_("away_score", "null")
                .or_(or_filter)
                .range(offset, offset + page_size - 1)
                .execute()
            )
            batch_rows = response.data or []
            if not batch_rows:
                break
            for row in batch_rows:
                game_id = str(row["id"])
                if game_id in seen_game_ids:
                    continue
                seen_game_ids.add(game_id)
                rows.append(row)
            if len(batch_rows) < page_size:
                break
            offset += page_size
    return rows


def _recover_orphaned_games_by_division(
    orphaned_games: list[dict[str, Any]],
    expected_team_ids_by_division: dict[str, set[str]],
    *,
    event_name: str,
) -> dict[str, list[dict[str, Any]]]:
    recovered: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in orphaned_games:
        home_team_id = str(row.get("home_team_master_id") or "")
        away_team_id = str(row.get("away_team_master_id") or "")
        candidate_divisions = [
            division_name
            for division_name, team_ids in expected_team_ids_by_division.items()
            if home_team_id in team_ids and away_team_id in team_ids
        ]
        if len(candidate_divisions) != 1:
            continue
        division_name = candidate_divisions[0]
        recovered[division_name].append(
            {
                **row,
                "event_name": event_name,
                "division_name": division_name,
            }
        )
    return recovered


def _build_request_payload(
    *,
    age_group: str,
    gender: str,
    event_name: str,
    divisions: list[dict[str, Any]],
    teams_by_division: dict[str, set[str]],
    teams_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    entrants: list[dict[str, Any]] = []
    for division in divisions:
        actual_division_name = str(division["division_name"])
        for team_id in sorted(teams_by_division[actual_division_name]):
            team_row = teams_by_id.get(team_id) or {}
            event_team_name = str(team_row.get("team_name") or team_id)
            entrants.append(
                {
                    "entrant_id": f"{_slugify(actual_division_name)}_{_slugify(event_team_name)}",
                    "canonical_team_id": team_id,
                    "provider_team_id": str(team_row.get("provider_team_id") or ""),
                    "event_team_name": event_team_name,
                    "event_age_group": age_group,
                    "event_gender": gender,
                    "actual_division_name": actual_division_name.removeprefix(f"BU{age_group.removeprefix('u')} ").strip()  # noqa: E501
                    if actual_division_name.startswith("BU")
                    else actual_division_name,
                }
            )
    return {
        "event_name": event_name,
        "age_group": age_group,
        "gender": gender.lower(),
        "divisions": [
            {
                "name": division["division_name"].removeprefix(f"BU{age_group.removeprefix('u')} ").strip()
                if division["division_name"].startswith("BU")
                else division["division_name"],
                "actual_division_name": division["division_name"],
                "team_count": division["team_count"],
                "pool_sizes": division["pool_sizes"],
            }
            for division in divisions
        ],
        "entrants": entrants,
    }


def _cohort_status_rows(
    event_structure: dict[tuple[str, str], list[dict[str, Any]]],
    teams_by_division: dict[str, set[str]],
) -> list[dict[str, Any]]:
    statuses: list[dict[str, Any]] = []
    for (age_group, gender), divisions in sorted(event_structure.items()):
        division_statuses: list[dict[str, Any]] = []
        runnable = True
        for division in divisions:
            actual_count = len(teams_by_division.get(str(division["division_name"]), set()))
            complete = actual_count == int(division["team_count"])
            if not complete:
                runnable = False
            division_statuses.append(
                {
                    "division_name": division["division_name"],
                    "expected_team_count": int(division["team_count"]),
                    "actual_team_count": actual_count,
                    "complete": complete,
                }
            )
        statuses.append(
            {
                "age_group": age_group,
                "gender": gender,
                "divisions": division_statuses,
                "runnable": runnable,
            }
        )
    return statuses


def main() -> int:
    load_dotenv(Path(__file__).parent.parent / ".env.local")
    load_dotenv(Path(__file__).parent.parent / ".env")

    parser = argparse.ArgumentParser(description="Backtest every runnable cohort in one completed event")
    parser.add_argument("--event-name", required=True, help="Canonical event_name stored on games rows")
    parser.add_argument("--group-structure-csv", required=True, help="Path to saved group_structure_summary.csv")
    parser.add_argument(
        "--event-team-registry-csv",
        default=None,
        help="Optional saved event_team_registry.csv to recover games whose event/division tags were lost",
    )
    parser.add_argument(
        "--output-dir",
        default="reports/tournament_event_backtest",
        help="Directory for generated cohort requests and event summary outputs",
    )
    parser.add_argument(
        "--predictor-source",
        default="point_in_time",
        choices=["python", "point_in_time"],
        help="Prediction engine to use for each cohort replay",
    )
    parser.add_argument(
        "--point-in-time-model-artifact",
        default=None,
        help="Required when predictor-source is point_in_time",
    )
    parser.add_argument("--history-lookback-days", type=int, default=365)
    parser.add_argument("--snapshot-buffer-days", type=int, default=30)
    args = parser.parse_args()

    group_structure_csv = Path(args.group_structure_csv)
    if not group_structure_csv.exists():
        raise FileNotFoundError(f"Group structure CSV not found: {group_structure_csv}")

    output_dir = Path(args.output_dir)
    requests_dir = output_dir / "requests"
    runs_dir = output_dir / "cohorts"
    requests_dir.mkdir(parents=True, exist_ok=True)
    runs_dir.mkdir(parents=True, exist_ok=True)

    client = _get_supabase()
    group_rows = _load_group_rows(group_structure_csv)
    event_structure = _build_event_structure(group_rows)
    event_games = _fetch_event_games(client, args.event_name)
    if not event_games:
        raise ValueError(f"No completed games found for event_name={args.event_name}")
    division_games_by_division = _build_division_game_map(event_games)
    recovered_orphaned_counts: dict[str, int] = {}
    unresolved_registry_entries_by_division: dict[str, int] = {}
    matcher_status_counts: dict[str, int] = {}
    event_team_registry_csv = Path(args.event_team_registry_csv) if args.event_team_registry_csv else None
    registry_rows = _load_event_team_registry_rows(event_team_registry_csv)
    if registry_rows:
        registry_rows, matcher_status_counts = _enrich_registry_rows_with_matcher(client, registry_rows)
        _write_csv(output_dir / "event_team_registry_with_matcher.csv", registry_rows)
        registry_team_ids_by_division, unresolved_registry_entries_by_division = _build_registry_division_team_map(
            client,
            registry_rows,
        )
        expected_team_ids_by_division: dict[str, set[str]] = defaultdict(set)
        for division_name, team_ids in _build_division_team_map(event_games).items():
            expected_team_ids_by_division[division_name].update(team_ids)
        for division_name, team_ids in registry_team_ids_by_division.items():
            expected_team_ids_by_division[division_name].update(team_ids)
        all_expected_team_ids = sorted({team_id for team_ids in expected_team_ids_by_division.values() for team_id in team_ids})  # noqa: E501
        event_dates = sorted({str(row["game_date"]) for row in event_games if row.get("game_date")})
        if all_expected_team_ids and event_dates:
            orphaned_games = _fetch_orphaned_games_for_team_ids(
                client,
                all_expected_team_ids,
                start_date=event_dates[0],
                end_date=event_dates[-1],
            )
            recovered_games_by_division = _recover_orphaned_games_by_division(
                orphaned_games,
                expected_team_ids_by_division,
                event_name=args.event_name,
            )
            for division_name, recovered_games in recovered_games_by_division.items():
                existing_ids = {str(row["id"]) for row in division_games_by_division.get(division_name, [])}
                for row in recovered_games:
                    if str(row["id"]) in existing_ids:
                        continue
                    division_games_by_division[division_name].append(row)
                recovered_orphaned_counts[division_name] = len(recovered_games)

    merged_event_games = [
        row
        for division_rows in division_games_by_division.values()
        for row in division_rows
    ]
    teams_by_division = _build_division_team_map(merged_event_games)
    statuses = _cohort_status_rows(event_structure, teams_by_division)

    runnable_team_ids = sorted(
        {
            team_id
            for status in statuses
            if status["runnable"]
            for division in status["divisions"]
            for team_id in teams_by_division.get(str(division["division_name"]), set())
        }
    )
    team_rows = _fetch_rows_by_ids(
        client,
        "teams",
        "team_id_master,team_name,provider_team_id",
        "team_id_master",
        runnable_team_ids,
    )
    teams_by_id = {str(row["team_id_master"]): row for row in team_rows}

    cohort_results: list[dict[str, Any]] = []
    for status in statuses:
        age_group = str(status["age_group"])
        gender = str(status["gender"])
        cohort_slug = f"{_slugify(age_group)}_{_slugify(gender)}"
        request_path = requests_dir / f"{cohort_slug}.json"

        if not status["runnable"]:
            cohort_results.append(
                {
                    "age_group": age_group,
                    "gender": gender,
                    "status": "skipped_incomplete_division_coverage",
                    "request_path": str(request_path),
                    "run_dir": str(runs_dir / cohort_slug),
                    "divisions": status["divisions"],
                }
            )
            continue

        divisions = event_structure[_cohort_key(age_group, gender)]
        request_payload = _build_request_payload(
            age_group=age_group,
            gender=gender,
            event_name=args.event_name,
            divisions=divisions,
            teams_by_division=teams_by_division,
            teams_by_id=teams_by_id,
        )
        request_payload["actual_games_override"] = [
            row
            for division in divisions
            for row in division_games_by_division.get(str(division["division_name"]), [])
        ]
        _write_json(request_path, request_payload)

        run_dir = runs_dir / cohort_slug
        command = [
            sys.executable,
            str(Path(__file__).parent / "backtest_tournament_cohort.py"),
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
                raise ValueError("--point-in-time-model-artifact is required for predictor-source point_in_time")
            command.extend(["--point-in-time-model-artifact", str(args.point_in_time_model_artifact)])

        completed = subprocess.run(command, capture_output=True, text=True, check=False)
        summary_path = run_dir / "summary.json"
        result_payload = {
            "age_group": age_group,
            "gender": gender,
            "status": "completed" if completed.returncode == 0 and summary_path.exists() else "failed",
            "request_path": str(request_path),
            "run_dir": str(run_dir),
            "returncode": completed.returncode,
            "stdout_tail": completed.stdout[-1000:],
            "stderr_tail": completed.stderr[-1000:],
            "divisions": status["divisions"],
        }
        if summary_path.exists():
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            result_payload["actual_average_goal_differential"] = summary["actual_results"]["average_goal_differential"]
            result_payload["optimized_average_goal_differential"] = summary["optimized_projection"]["simulated_schedule"][  # noqa: E501
                "average_goal_differential"
            ]
            result_payload["close_game_rate_delta"] = summary["comparison_to_actual"]["close_game_rate_delta"]
            result_payload["blowout_3plus_rate_improvement"] = summary["comparison_to_actual"][
                "blowout_3plus_rate_improvement"
            ]
        cohort_results.append(result_payload)

    summary_payload = {
        "event_name": args.event_name,
        "group_structure_csv": str(group_structure_csv),
        "event_team_registry_csv": str(event_team_registry_csv) if event_team_registry_csv else None,
        "predictor_source": args.predictor_source,
        "point_in_time_model_artifact": args.point_in_time_model_artifact,
        "recovered_orphaned_games_by_division": recovered_orphaned_counts,
        "unresolved_registry_entries_by_division": unresolved_registry_entries_by_division,
        "matcher_status_counts": matcher_status_counts,
        "cohorts": cohort_results,
    }
    _write_json(output_dir / "summary.json", summary_payload)
    print(f"Saved event backtest summary to {output_dir / 'summary.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
