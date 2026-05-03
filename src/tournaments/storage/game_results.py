"""Game results + standings persistence for backtest mode.

Local source-of-truth artifacts that replace the Supabase ``games`` table
dependency for backtest analysis. Both files live in the intake tier
(scenario-shared) because the data is a property of the scraped event,
not of any seeding scenario:

- ``intake/game_results.jsonl`` — one row per game, keyed by gotsport
  ``match_id``. Re-scrapes upsert by ``match_id`` (latest wins).
- ``intake/standings.jsonl`` — one row per (group_id, provider_team_id)
  pair with the gotsport-reported W/L/D/GF/GA/GD/PTS. Useful for
  backtest seeding diagnostics (computed standings vs. ranking-implied).

Both files are JSONL (line-delimited JSON) so they're append-friendly
and stream-readable without a schema-stamped JSON wrapper. The schema
version stamp lives in ``intake/results_metadata.json`` next to them.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path

from src.scrapers.gotsport_results_parser import GameResult, Standing
from src.tournaments.storage._io import read_json, write_json
from src.tournaments.storage.event_key import intake_dir
from src.tournaments.storage.schema_version import (
    assert_supported_version,
    stamp_schema_version,
)

__all__ = [
    "check_local_results_coverage",
    "read_game_results",
    "read_standings",
    "write_game_results",
    "write_standings",
]


def check_local_results_coverage(
    event_key: str,
    registered_provider_team_ids: Iterable[str],
    *,
    base_dir: Path | str = "reports",
) -> str:
    """Local replacement for the Supabase-backed
    ``check_games_import_status``.

    Reads ``intake/game_results.jsonl`` (written by the schedule enricher)
    and bins coverage:

    - File missing OR empty → ``"not_imported"``.
    - Every registered ``provider_team_id`` appears in at least one game
      (as home OR away) → ``"complete"``.
    - Otherwise → ``"partial"``.

    Backtest mode treats gotsport's schedule pages as the source of truth,
    so this check has no Supabase / database dependency.
    """
    games = read_game_results(event_key, base_dir=base_dir)
    if not games:
        return "not_imported"
    teams_with_games: set[str] = set()
    for game in games:
        if game.home_provider_team_id:
            teams_with_games.add(game.home_provider_team_id)
        if game.away_provider_team_id:
            teams_with_games.add(game.away_provider_team_id)
    registered = {str(pid) for pid in registered_provider_team_ids if pid}
    if registered and registered.issubset(teams_with_games):
        return "complete"
    return "partial"


def _game_results_path(event_key: str, *, base_dir: Path | str) -> Path:
    return intake_dir(event_key, base_dir=base_dir) / "game_results.jsonl"


def _standings_path(event_key: str, *, base_dir: Path | str) -> Path:
    return intake_dir(event_key, base_dir=base_dir) / "standings.jsonl"


def _metadata_path(event_key: str, *, base_dir: Path | str) -> Path:
    return intake_dir(event_key, base_dir=base_dir) / "results_metadata.json"


def read_game_results(
    event_key: str,
    *,
    base_dir: Path | str = "reports",
) -> list[GameResult]:
    """Return all ``GameResult`` rows for the event; empty list if absent."""
    path = _game_results_path(event_key, base_dir=base_dir)
    if not path.exists():
        return []
    _check_schema(event_key, base_dir=base_dir)
    games: list[GameResult] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            payload = json.loads(line)
            games.append(
                GameResult(
                    match_id=str(payload["match_id"]),
                    home_provider_team_id=str(payload["home_provider_team_id"]),
                    home_team_name=str(payload.get("home_team_name") or ""),
                    away_provider_team_id=str(payload["away_provider_team_id"]),
                    away_team_name=str(payload.get("away_team_name") or ""),
                    home_score=_nullable_int(payload.get("home_score")),
                    away_score=_nullable_int(payload.get("away_score")),
                    date_text=str(payload.get("date_text") or ""),
                    time_text=str(payload.get("time_text") or ""),
                    location=payload.get("location"),
                    division_label=payload.get("division_label"),
                    stage_label=payload.get("stage_label"),
                )
            )
    return games


def read_standings(
    event_key: str,
    *,
    base_dir: Path | str = "reports",
) -> list[tuple[str, Standing]]:
    """Return ``[(group_id, Standing), ...]`` rows; empty list if absent.

    The group_id pairing is preserved on disk so callers can correlate
    each standings row back to its tier (gotsport ``group_id`` is the
    join key against ``raw_scrape.jsonl`` records and
    ``pool_assignments.json``).
    """
    path = _standings_path(event_key, base_dir=base_dir)
    if not path.exists():
        return []
    _check_schema(event_key, base_dir=base_dir)
    rows: list[tuple[str, Standing]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            payload = json.loads(line)
            rows.append(
                (
                    str(payload["group_id"]),
                    Standing(
                        rank=int(payload["rank"]),
                        provider_team_id=str(payload["provider_team_id"]),
                        team_name=str(payload.get("team_name") or ""),
                        matches_played=_nullable_int(payload.get("matches_played")),
                        wins=_nullable_int(payload.get("wins")),
                        losses=_nullable_int(payload.get("losses")),
                        draws=_nullable_int(payload.get("draws")),
                        goals_for=_nullable_int(payload.get("goals_for")),
                        goals_against=_nullable_int(payload.get("goals_against")),
                        goal_diff=_nullable_int(payload.get("goal_diff")),
                        points=_nullable_int(payload.get("points")),
                    ),
                )
            )
    return rows


def write_game_results(
    event_key: str,
    games: Iterable[GameResult],
    *,
    base_dir: Path | str = "reports",
) -> None:
    """Persist ``game_results.jsonl`` (latest-wins by ``match_id``).

    Re-scrapes overwrite the file outright. Dedup by ``match_id`` is the
    caller's responsibility — pass the deduped list. The companion
    ``results_metadata.json`` is stamped with the schema version so
    ``read_game_results`` can reject incompatible future formats.
    """
    path = _game_results_path(event_key, base_dir=base_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for game in games:
            handle.write(
                json.dumps(
                    {
                        "match_id": game.match_id,
                        "home_provider_team_id": game.home_provider_team_id,
                        "home_team_name": game.home_team_name,
                        "away_provider_team_id": game.away_provider_team_id,
                        "away_team_name": game.away_team_name,
                        "home_score": game.home_score,
                        "away_score": game.away_score,
                        "date_text": game.date_text,
                        "time_text": game.time_text,
                        "location": game.location,
                        "division_label": game.division_label,
                        "stage_label": game.stage_label,
                    }
                )
                + "\n"
            )
    _stamp_schema(event_key, base_dir=base_dir)


def write_standings(
    event_key: str,
    standings_by_group: Iterable[tuple[str, Standing]],
    *,
    base_dir: Path | str = "reports",
) -> None:
    """Persist ``standings.jsonl`` keyed by ``(group_id, provider_team_id)``."""
    path = _standings_path(event_key, base_dir=base_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for group_id, standing in standings_by_group:
            handle.write(
                json.dumps(
                    {
                        "group_id": str(group_id),
                        "rank": standing.rank,
                        "provider_team_id": standing.provider_team_id,
                        "team_name": standing.team_name,
                        "matches_played": standing.matches_played,
                        "wins": standing.wins,
                        "losses": standing.losses,
                        "draws": standing.draws,
                        "goals_for": standing.goals_for,
                        "goals_against": standing.goals_against,
                        "goal_diff": standing.goal_diff,
                        "points": standing.points,
                    }
                )
                + "\n"
            )
    _stamp_schema(event_key, base_dir=base_dir)


def _stamp_schema(event_key: str, *, base_dir: Path | str) -> None:
    write_json(_metadata_path(event_key, base_dir=base_dir), stamp_schema_version({}))


def _check_schema(event_key: str, *, base_dir: Path | str) -> None:
    path = _metadata_path(event_key, base_dir=base_dir)
    if path.exists():
        assert_supported_version(read_json(path), source=str(path))


def _nullable_int(value) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
