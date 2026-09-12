"""Read-only historical-rating preflight for reviewed Backtest cohorts."""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from scripts.backtest_predictor import build_snapshot_index, fetch_prediction_feature_snapshots
from scripts.backtest_tournament_cohort import (
    TEAM_META_COLS,
    _build_entrant_row,
    _canonicalize_snapshot_index,
    _expand_merged_team_ids,
    _fetch_rows_by_ids,
    _filter_snapshot_index_for_cutoff,
    _historical_ranking_row,
    _resolve_prediction_snapshot,
    _verify_model_training_provenance,
    _verify_snapshot_provenance,
)
from src.predictions.point_in_time_match_model import PointInTimeMatchModel
from src.tournaments.backtest_reviewed_run import model_artifact_sha256, resolve_model_artifact
from src.tournaments.storage._io import read_json, utc_now_iso, write_json
from src.tournaments.storage.event_key import intake_dir
from src.utils.merge_resolver import MergeResolver


class HistoricalPreflightUnavailable(RuntimeError):
    """The read-only data service or model could not be checked."""


@dataclass(frozen=True)
class HistoricalEntrantCheck:
    entrant_id: str
    event_team_name: str
    canonical_team_id: str
    ranking_source_team_id: str
    eligible: bool
    snapshot_date: str = ""
    source_age_group: str = ""
    source_gender: str = ""
    power_score: float | None = None
    reason: str = ""


@dataclass(frozen=True)
class HistoricalCohortCheck:
    age_group: str
    gender: str
    eligible: int
    total: int
    entrants: tuple[HistoricalEntrantCheck, ...]

    @property
    def ready(self) -> bool:
        return self.total > 0 and self.eligible == self.total


@dataclass(frozen=True)
class HistoricalPreflight:
    input_sha256: str
    checked_at: str
    cutoff_exclusive: str
    model_artifact_sha256: str
    model_data_end_date: str
    merge_map_version: str
    cohorts: tuple[HistoricalCohortCheck, ...]

    @property
    def ready(self) -> bool:
        return bool(self.cohorts) and all(cohort.ready for cohort in self.cohorts)

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "ready": self.ready,
            "cohorts": [{**asdict(item), "ready": item.ready} for item in self.cohorts],
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "HistoricalPreflight":
        cohorts = tuple(
            HistoricalCohortCheck(
                age_group=str(item["age_group"]),
                gender=str(item["gender"]),
                eligible=int(item["eligible"]),
                total=int(item["total"]),
                entrants=tuple(HistoricalEntrantCheck(**row) for row in item.get("entrants", ())),
            )
            for item in payload.get("cohorts", ())
        )
        return cls(
            input_sha256=str(payload["input_sha256"]),
            checked_at=str(payload["checked_at"]),
            cutoff_exclusive=str(payload["cutoff_exclusive"]),
            model_artifact_sha256=str(payload["model_artifact_sha256"]),
            model_data_end_date=str(payload["model_data_end_date"]),
            merge_map_version=str(payload["merge_map_version"]),
            cohorts=cohorts,
        )


def preflight_input_sha256(requests: Iterable[dict[str, Any]], model_artifact: str | Path) -> str:
    payload = {
        "requests": list(requests),
        "model_artifact_sha256": model_artifact_sha256(model_artifact),
        "policy": "strict-pre-event-snapshot-v1",
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def historical_preflight_path(event_key: str, *, base_dir: Path | str = "reports") -> Path:
    return intake_dir(event_key, base_dir=base_dir) / "historical_preflight.json"


def load_historical_preflight(
    event_key: str,
    *,
    base_dir: Path | str = "reports",
) -> HistoricalPreflight | None:
    path = historical_preflight_path(event_key, base_dir=base_dir)
    if not path.is_file():
        return None
    return HistoricalPreflight.from_dict(read_json(path))


def write_historical_preflight(
    event_key: str,
    result: HistoricalPreflight,
    *,
    base_dir: Path | str = "reports",
) -> Path:
    path = historical_preflight_path(event_key, base_dir=base_dir)
    write_json(path, result.to_dict())
    return path


def run_historical_preflight(
    requests: Iterable[dict[str, Any]],
    client: Any,
    *,
    model_artifact: str | Path,
) -> HistoricalPreflight:
    """Check the exact entrant snapshots the strict cohort runner will require."""

    request_list = list(requests)
    if not request_list:
        raise ValueError("Historical preflight needs at least one cohort request")
    cutoffs = {str(request.get("prediction_date") or "") for request in request_list}
    if "" in cutoffs or len(cutoffs) != 1:
        raise ValueError("All preflight cohorts need one explicit event cutoff")
    cutoff = next(iter(cutoffs))
    artifact = resolve_model_artifact(model_artifact)
    try:
        model = PointInTimeMatchModel.load(str(artifact))
        model_data_end = _verify_model_training_provenance(
            dict(model.training_metadata or {}), prediction_date=cutoff
        )
        resolver = MergeResolver(client)
        resolver.load_merge_map()
        if resolver.version == "error":
            raise RuntimeError("Team merge information could not be loaded")
    except Exception as exc:
        raise HistoricalPreflightUnavailable(str(exc)) from exc

    prepared: list[tuple[dict[str, Any], list[dict[str, Any]]]] = []
    canonical_ids: set[str] = set()
    ranking_ids: set[str] = set()
    for request in request_list:
        entrants = []
        for source in request.get("entrants") or ():
            canonical = str(
                resolver.resolve(str(source["canonical_team_id"])) or source["canonical_team_id"]
            )
            ranking_source = str(
                resolver.resolve(str(source.get("ranking_source_team_id") or canonical))
                or source.get("ranking_source_team_id")
                or canonical
            )
            entrant = {
                **source,
                "canonical_team_id": canonical,
                "ranking_source_team_id": ranking_source,
            }
            entrants.append(entrant)
            canonical_ids.add(canonical)
            ranking_ids.add(ranking_source)
        prepared.append((request, entrants))

    snapshot_start = (pd.Timestamp(cutoff).normalize() - pd.Timedelta(days=365)).strftime("%Y-%m-%d")
    try:
        team_rows = _fetch_rows_by_ids(
            client, "teams", TEAM_META_COLS, "team_id_master", sorted(canonical_ids)
        )
        snapshot_ids = _expand_merged_team_ids(resolver, sorted(ranking_ids))
        snapshots_df = asyncio.run(
            fetch_prediction_feature_snapshots(
                client,
                snapshot_ids,
                snapshot_start,
                cutoff,
                availability_cutoff=cutoff,
            )
        )
    except Exception as exc:
        raise HistoricalPreflightUnavailable(
            f"Historical data service could not be read: {exc}"
        ) from exc
    snapshot_index = _canonicalize_snapshot_index(
        resolver,
        _filter_snapshot_index_for_cutoff(build_snapshot_index(snapshots_df), cutoff),
    )
    team_by_id = {str(row["team_id_master"]): row for row in team_rows}
    cohort_results: list[HistoricalCohortCheck] = []
    for request, entrants in prepared:
        checks: list[HistoricalEntrantCheck] = []
        for entrant in entrants:
            canonical = str(entrant["canonical_team_id"])
            ranking_source = str(entrant["ranking_source_team_id"])
            name = str(entrant.get("event_team_name") or ranking_source)
            try:
                snapshot, _mode = _resolve_prediction_snapshot(
                    {"event_team_name": name, "ranking_source_team_id": ranking_source},
                    snapshot_index.get(ranking_source),
                    cutoff,
                )
                _verify_snapshot_provenance(snapshot, prediction_date=cutoff, team_name=name)
                row = _build_entrant_row(
                    entrant,
                    team_by_id.get(canonical),
                    _historical_ranking_row(snapshot),
                    cohort_age_group=str(request["age_group"]),
                    cohort_gender=str(request["gender"]),
                )
            except (KeyError, TypeError, ValueError) as exc:
                checks.append(
                    HistoricalEntrantCheck(
                        str(entrant["entrant_id"]),
                        name,
                        canonical,
                        ranking_source,
                        False,
                        reason=str(exc),
                    )
                )
                continue
            checks.append(
                HistoricalEntrantCheck(
                    str(entrant["entrant_id"]),
                    name,
                    canonical,
                    ranking_source,
                    True,
                    snapshot_date=str(snapshot["snapshot_date"]),
                    source_age_group=str(row["source_age_group"]),
                    source_gender=str(row["source_gender"]),
                    power_score=float(row["power_score"]),
                )
            )
        cohort_results.append(
            HistoricalCohortCheck(
                str(request["age_group"]),
                str(request["gender"]),
                sum(check.eligible for check in checks),
                len(checks),
                tuple(checks),
            )
        )
    return HistoricalPreflight(
        input_sha256=preflight_input_sha256(request_list, artifact),
        checked_at=utc_now_iso(),
        cutoff_exclusive=cutoff,
        model_artifact_sha256=model_artifact_sha256(artifact),
        model_data_end_date=model_data_end,
        merge_map_version=str(resolver.version),
        cohorts=tuple(cohort_results),
    )
