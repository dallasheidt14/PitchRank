"""One-command acceptance validation for a completed Backtest event."""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path

from src.predictions.point_in_time_match_model import PointInTimeMatchModel
from src.tournaments.backtest_event_rollup import build_event_rollup
from src.tournaments.backtest_historical_preflight import (
    load_historical_preflight,
    preflight_input_sha256,
)
from src.tournaments.backtest_intake_state import (
    entrant_key,
    read_snapshot,
    structure_hash,
    tournament_totals,
)
from src.tournaments.backtest_link_store import load_links
from src.tournaments.backtest_reviewed_run import (
    build_reviewed_cohort_readiness,
    capture_verification_blockers,
    list_failed_reviewed_runs,
    list_reviewed_runs,
    model_artifact_sha256,
    resolve_model_artifact,
)


@dataclass(frozen=True)
class AcceptanceProfile:
    name: str
    event_id: str
    event_name: str
    cutoff_exclusive: str
    total_teams: int
    divisions: int
    pools: int
    fixtures: int
    scored_games: int
    total_goal_margin: int
    blowout_games: int


SAN_ANTONIO_51783 = AcceptanceProfile(
    name="san-antonio-51783",
    event_id="51783",
    event_name="SAN ANTONIO LABOR CUP 26",
    cutoff_exclusive="2026-09-05",
    total_teams=332,
    divisions=58,
    pools=88,
    fixtures=614,
    scored_games=613,
    total_goal_margin=1857,
    blowout_games=198,
)

ACCEPTANCE_PROFILES = {SAN_ANTONIO_51783.name: SAN_ANTONIO_51783}


def _check(name: str, expected, actual, *, detail: str = "") -> dict:
    return {
        "name": name,
        "status": "pass" if actual == expected else "fail",
        "expected": expected,
        "actual": actual,
        "detail": detail,
    }


def _model_data_end(model_path: Path) -> str:
    model = PointInTimeMatchModel.load(str(model_path))
    return str((model.training_metadata or {}).get("model_data_end_date") or "")[:10]


def validate_backtest_acceptance(
    event_key: str,
    profile: AcceptanceProfile,
    *,
    model_artifact: str | Path,
    base_dir: str | Path = "reports",
    merge_map_version: str = "",
) -> dict:
    snapshot = read_snapshot(event_key, base_dir=base_dir)
    links = load_links(event_key, base_dir=base_dir)
    totals = tournament_totals(snapshot.roster)
    actual = totals["results"]
    checks = [
        _check("event id", profile.event_id, snapshot.roster.event_id),
        _check("event name", profile.event_name, totals["event_name"]),
        _check("teams", profile.total_teams, totals["total_teams"]),
        _check("divisions", profile.divisions, totals["divisions"]),
        _check("pools", profile.pools, totals["pools"]),
        _check("fixtures", profile.fixtures, totals["fixtures"]),
        _check("scored games", profile.scored_games, actual["scored_games"]),
        _check("total goal margin", profile.total_goal_margin, actual["total_goal_margin"]),
        _check("4+ blowouts", profile.blowout_games, actual["blowout_games"]),
    ]
    checks.append(
        _check(
            "capture verification",
            [],
            list(capture_verification_blockers(snapshot)),
        )
    )
    reviews = {review.group_id: review for review in snapshot.reviews}
    invalid_reviews = [
        division.group_id
        for division in snapshot.roster.divisions
        if division.group_id not in reviews
        or not reviews[division.group_id].checked
        or reviews[division.group_id].structure_hash != structure_hash(division)
    ]
    checks.append(_check("division reviews", [], invalid_reviews))

    registrations = {entrant_key(team) for team in snapshot.roster.teams}
    accepted_links = {
        link.registration_id: link
        for link in links.links
        if link.matched_by in {"gotsport_id", "operator"}
        and link.registration_id not in links.removed_registration_ids
        and link.registration_id not in links.not_found_registration_ids
    }
    unmatched = sorted(registrations - set(accepted_links))
    checks.append(
        _check(
            "matched teams",
            profile.total_teams,
            len(registrations) - len(unmatched),
            detail="; ".join(unmatched[:10]),
        )
    )
    by_team: dict[str, set[str]] = defaultdict(set)
    for registration_id, link in accepted_links.items():
        by_team[link.team_id_master].add(registration_id)
    acknowledged = {
        item.team_id_master: (set(item.registration_ids), bool(item.note.strip()))
        for item in links.collision_acknowledgements
    }
    unresolved_collisions = sorted(
        team_id
        for team_id, registration_ids in by_team.items()
        if len(registration_ids) > 1
        and acknowledged.get(team_id) != (registration_ids, True)
    )
    checks.append(_check("duplicate mapping acknowledgements", [], unresolved_collisions))

    readiness = build_reviewed_cohort_readiness(snapshot, links)
    readiness_blockers = {
        f"{item.gender} {item.age_group}": list(item.blockers)
        for item in readiness
        if not item.ready
    }
    checks.append(_check("cohort intake readiness", {}, readiness_blockers))
    requests = [item.request for item in readiness if item.request is not None]
    artifact = resolve_model_artifact(model_artifact)
    artifact_exists = artifact.is_file()
    checks.append(_check("historical model artifact", True, artifact_exists, detail=str(artifact)))
    model_sha = model_artifact_sha256(artifact) if artifact_exists else ""
    model_data_end = ""
    if artifact_exists:
        try:
            model_data_end = _model_data_end(artifact)
        except Exception as exc:
            checks.append(_check("historical model readable", True, False, detail=str(exc)))
        else:
            checks.append(_check("historical model readable", True, True))
    checks.append(
        _check(
            "historical model cutoff",
            True,
            bool(model_data_end and model_data_end < profile.cutoff_exclusive),
            detail=f"model data ends {model_data_end or 'unknown'}; event cutoff {profile.cutoff_exclusive}",
        )
    )
    preflight = load_historical_preflight(event_key, base_dir=base_dir)
    expected_preflight_sha = (
        preflight_input_sha256(
            requests,
            artifact,
            merge_map_version=merge_map_version,
        )
        if artifact_exists and len(requests) == len(readiness) and requests
        else ""
    )
    preflight_current = bool(
        preflight
        and bool(merge_map_version)
        and preflight.merge_map_version == merge_map_version
        and preflight.input_sha256 == expected_preflight_sha
        and preflight.cutoff_exclusive == profile.cutoff_exclusive
        and preflight.ready
    )
    checks.append(
        _check(
            "historical rating preflight",
            True,
            preflight_current,
            detail=(
                f"{sum(item.eligible for item in preflight.cohorts)} of "
                f"{sum(item.total for item in preflight.cohorts)} eligible"
                if preflight else "No saved preflight"
            ),
        )
    )

    attempts = (
        *list_reviewed_runs(event_key, base_dir=base_dir),
        *list_failed_reviewed_runs(event_key, base_dir=base_dir),
    )
    rollup = build_event_rollup(
        snapshot,
        readiness,
        attempts,
        model_sha256=model_sha or None,
    )
    coverage = rollup["coverage"]
    checks.append(_check("completed cohort outputs", coverage["total_cohorts"], coverage["completed"]))
    movements = rollup["team_movements"]
    movement_rows_complete = bool(
        movements["evaluated"] == profile.total_teams
        and not movements["duplicate_entry_ids_skipped"]
    )
    checks.append(
        _check(
            "tournament team movements",
            True,
            movement_rows_complete,
            detail=f"{movements['evaluated']} unique movement rows",
        )
    )
    modelled = rollup["modelled_pool_matchups"]
    rollup_reconciled = bool(
        coverage["completed"] == coverage["total_cohorts"]
        and modelled["original_count"] == modelled["matchbalance_count"]
        and modelled["original_count"] > 0
        and modelled["original_blowout_4plus_rate"] is not None
        and modelled["matchbalance_blowout_4plus_rate"] is not None
    )
    checks.append(_check("tournament rollup reconciliation", True, rollup_reconciled))
    failed = Counter(check["status"] for check in checks)["fail"]
    payload = {
        "profile": asdict(profile),
        "event_key": event_key,
        "status": "pass" if failed == 0 else "incomplete",
        "passed": len(checks) - failed,
        "failed": failed,
        "checks": checks,
        "rollup": rollup,
    }
    digest_source = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    payload["report_sha256"] = hashlib.sha256(digest_source.encode("utf-8")).hexdigest()
    return payload
