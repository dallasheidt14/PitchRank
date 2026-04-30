"""Per-tier bracket reports for the Streamlit cohort UI.

Reads three intake artifacts written by the schedule enricher and joins
them into a structured report mirroring gotsport's per-tier standings
page (the GG.docx layout — pool-play tables of
``Rank | Team | MP | W | L | D | GF | GA | GD | PTS`` per bracket label,
plus a knockout / showcase block of cross-pool matches with a starred
winner score):

- ``intake/pool_assignments.json`` — the bracket A/B (or A/B/C/...) split
  inside each gotsport ``group_id``. The only place ``bracket_label`` is
  recorded; standings rows carry only ``group_id``, so this file is the
  bridge.
- ``intake/standings.jsonl`` — gotsport-reported W/L/D/GF/GA/GD/PTS rows
  per ``(group_id, provider_team_id)``.
- ``intake/game_results.jsonl`` — per-game records with both team IDs,
  score, location, and the gotsport ``division_label`` (used as the tier
  title since ``standings.jsonl`` does not carry the human-facing label).

Cohort routing happens at the call site — ``tournament_intake.py``
already iterates cohorts keyed by ``(age, gender)`` and knows which
gotsport ``group_id`` values belong to each cohort (from
``raw_scrape.jsonl`` records). This module's contract is simpler: given
a list of ``group_id`` values, return one ``TierReport`` per gid.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from src.scrapers.gotsport_pool_parser import PoolAssignment
from src.scrapers.gotsport_results_parser import GameResult, Standing
from src.tournaments.storage.game_results import read_game_results, read_standings
from src.tournaments.storage.pool_assignments import read_pool_assignments

__all__ = [
    "KnockoutMatch",
    "PoolTable",
    "TierReport",
    "build_tier_reports",
]


@dataclass(frozen=True)
class PoolTable:
    """One bracket's standings rows inside a tier (e.g. ``Bracket A``)."""

    bracket_label: str
    rows: tuple[Standing, ...]


@dataclass(frozen=True)
class KnockoutMatch:
    """One cross-pool game (showcase / playoff / consolation / final).

    ``winner`` is ``"home"`` / ``"away"`` for completed games, ``"draw"``
    for level scores (rare in knockout but possible in showcase), and
    ``"tbd"`` when at least one score is ``None`` (unplayed). Renderers
    star the winner in the GG.docx layout.
    """

    match_id: str
    home_team_name: str
    away_team_name: str
    home_score: int | None
    away_score: int | None
    location: str | None
    date_text: str
    time_text: str
    winner: Literal["home", "away", "draw", "tbd"]


@dataclass(frozen=True)
class TierReport:
    """One gotsport tier (group_id) — pool play + knockout."""

    group_id: str
    title: str
    pool_play: tuple[PoolTable, ...]
    knockout: tuple[KnockoutMatch, ...]


def build_tier_reports(
    event_key: str,
    group_ids: Iterable[str | int],
    *,
    base_dir: Path | str = "reports",
) -> list[TierReport]:
    """Return one ``TierReport`` per requested ``group_id``.

    Tiers without a ``pool_assignments.json`` entry are skipped — v1
    requires the pool layout to split standings by bracket label and to
    detect cross-pool (knockout) games. Tiers with pool data but no
    standings still emit empty pool tables; tiers with games but no
    pools still emit knockout entries (every game qualifies because no
    pool can contain it).
    """
    requested = [str(gid) for gid in group_ids]
    if not requested:
        return []

    pools_by_group = read_pool_assignments(event_key, base_dir=base_dir)
    standings_by_group = _index_standings(read_standings(event_key, base_dir=base_dir))
    games_by_group, title_by_group = _index_games_by_group(
        read_game_results(event_key, base_dir=base_dir),
        pools_by_group,
    )

    reports: list[TierReport] = []
    for gid in requested:
        pools = pools_by_group.get(gid)
        if not pools:
            continue
        title = title_by_group.get(gid, "")
        pool_pid_sets = [set(p.provider_team_ids) for p in pools]
        pool_play = tuple(
            PoolTable(
                bracket_label=pool.label,
                rows=tuple(_pool_standings(pool, standings_by_group.get(gid, []))),
            )
            for pool in sorted(pools, key=lambda p: p.label)
        )
        knockout = tuple(
            _to_knockout_match(game)
            for game in games_by_group.get(gid, [])
            if not _is_pool_play(game, pool_pid_sets)
        )
        reports.append(TierReport(group_id=gid, title=title, pool_play=pool_play, knockout=knockout))
    return reports


def _index_standings(rows: list[tuple[str, Standing]]) -> dict[str, list[Standing]]:
    by_group: dict[str, list[Standing]] = defaultdict(list)
    for group_id, standing in rows:
        by_group[group_id].append(standing)
    return by_group


def _index_games_by_group(
    games: list[GameResult],
    pools_by_group: dict[str, list[PoolAssignment]],
) -> tuple[dict[str, list[GameResult]], dict[str, str]]:
    """Bucket games by ``group_id`` via team-id membership in pool rosters.

    A game whose home (or, fallback, away) team appears in any pool of a
    group is bucketed there. Cross-cohort showcase games where neither
    team is in any registered pool are dropped — the renderer has
    nowhere to surface them.
    """
    pid_to_group: dict[str, str] = {}
    for gid, pools in pools_by_group.items():
        for pool in pools:
            for pid in pool.provider_team_ids:
                pid_to_group[pid] = gid
    games_by_group: dict[str, list[GameResult]] = defaultdict(list)
    title_by_group: dict[str, str] = {}
    for game in games:
        gid = pid_to_group.get(game.home_provider_team_id) or pid_to_group.get(game.away_provider_team_id)
        if gid is None:
            continue
        games_by_group[gid].append(game)
        if gid not in title_by_group and game.division_label:
            title_by_group[gid] = game.division_label
    return games_by_group, title_by_group


def _pool_standings(pool: PoolAssignment, group_rows: list[Standing]) -> list[Standing]:
    pool_pids = set(pool.provider_team_ids)
    return sorted(
        (row for row in group_rows if row.provider_team_id in pool_pids),
        key=lambda s: s.rank,
    )


def _is_pool_play(game: GameResult, pool_pid_sets: list[set[str]]) -> bool:
    return any(
        game.home_provider_team_id in pool_pids and game.away_provider_team_id in pool_pids
        for pool_pids in pool_pid_sets
    )


def _to_knockout_match(game: GameResult) -> KnockoutMatch:
    return KnockoutMatch(
        match_id=game.match_id,
        home_team_name=game.home_team_name,
        away_team_name=game.away_team_name,
        home_score=game.home_score,
        away_score=game.away_score,
        location=game.location,
        date_text=game.date_text,
        time_text=game.time_text,
        winner=_winner(game.home_score, game.away_score),
    )


def _winner(home_score: int | None, away_score: int | None) -> Literal["home", "away", "draw", "tbd"]:
    if home_score is None or away_score is None:
        return "tbd"
    if home_score > away_score:
        return "home"
    if away_score > home_score:
        return "away"
    return "draw"
