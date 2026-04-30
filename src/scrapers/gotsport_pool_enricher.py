"""Walk a scraped event's tier ``group_id`` set and capture schedule data.

Sits between the team-list scrape (which writes ``raw_scrape.jsonl``) and
the registry-persistence step (which derives ``CohortStructure`` and
writes ``group_structure_summary.csv``). Each unique ``group_id`` on the
raw_scrape records is fetched once via ``/schedules?group=<id>``; the
HTML is parsed through three sibling parsers and persisted as three
intake artifacts:

- ``intake/pool_assignments.json`` (pool layout per tier)
- ``intake/game_results.jsonl`` (per-game scores / dates / teams)
- ``intake/standings.jsonl`` (per-team W/L/D/GF/GA/GD/PTS)

The latter two replace the dependency on the Supabase ``games`` table
for backtest mode — gotsport is the source of truth for the tournament
that already happened, so we don't need a downstream join.

Fetcher injection mirrors ``gotsport_tier_parser.enrich_teams_with_tiers``:
the caller wires whatever fetch policy applies (ZenRows, captcha
handling, rate limiting) and this module stays HTTP-free for unit tests.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from src.scrapers.gotsport_pool_parser import (
    PoolAssignment,
    parse_pool_assignments_from_html,
)
from src.scrapers.gotsport_results_parser import (
    GameResult,
    Standing,
    parse_game_results_from_html,
    parse_standings_from_html,
)
from src.tournaments.storage.game_results import write_game_results, write_standings
from src.tournaments.storage.pool_assignments import write_pool_assignments

logger = logging.getLogger(__name__)

__all__ = [
    "enrich_event_with_pools",
    "enrich_event_with_schedule",
    "collect_group_ids",
]


def collect_group_ids(records: list[dict]) -> list[int]:
    """Return the deduped, sorted list of gotsport tier ``group_id`` values."""
    seen: set[int] = set()
    for rec in records:
        gid = rec.get("group_id")
        if gid is None:
            continue
        try:
            seen.add(int(gid))
        except (TypeError, ValueError):
            continue
    return sorted(seen)


def enrich_event_with_pools(
    event_key: str,
    records: list[dict],
    *,
    fetcher: Callable[[int], str],
    base_dir: Path | str = "reports",
) -> dict[str, list[PoolAssignment]]:
    """Fetch each tier's schedule page, parse pool layout, persist artifact.

    ``records`` is the raw_scrape record list (caller owns the load so we
    don't double-read the journal — production passes the same list it
    fed to ``build_registry_entries``). ``fetcher`` is a
    ``(group_id: int) -> html: str`` callable supplied by the caller:
    production wires it to ``GotsportScraper.fetch_schedule_html`` (with
    ZenRows + captcha handling); tests pass a dict-backed stub.

    Tiers whose fetch returns empty HTML, or whose schedule page has no
    recognized pool headings (e.g., a knockout-only tier), are skipped
    silently — they simply don't appear in the output map. Caller logic
    treats absence of pool data per group_id as "no pools captured" and
    leaves ``pool_sizes`` empty downstream.
    """
    group_ids = collect_group_ids(records)
    pools_by_group: dict[str, list[PoolAssignment]] = {}

    for group_id in group_ids:
        try:
            html = fetcher(group_id)
        except Exception:  # noqa: BLE001 — partial-success contract
            logger.exception("pool fetch failed for group_id=%s", group_id)
            continue
        if not html:
            continue
        pools = parse_pool_assignments_from_html(html)
        if pools:
            pools_by_group[str(group_id)] = pools

    write_pool_assignments(event_key, pools_by_group, base_dir=base_dir)
    return pools_by_group


def enrich_event_with_schedule(
    event_key: str,
    records: list[dict],
    *,
    fetcher: Callable[[int], str],
    base_dir: Path | str = "reports",
) -> tuple[dict[str, list[PoolAssignment]], list[GameResult], list[tuple[str, Standing]]]:
    """Fetch each tier's schedule page once; parse pools + games + standings.

    Single fetch pass per ``group_id`` — same pages, three parsers. The
    return triple mirrors the three artifacts written:
    ``(pools_by_group_id, all_games, standings_by_group_id)``.

    Per-tier failures are isolated: if a single fetcher call raises or
    returns empty HTML, that tier is skipped for all three parsers but
    the other tiers still complete. Games are deduped by ``match_id``
    across tiers (cross-bracket matches that appear under multiple
    pages — rare but possible — keep one canonical row).
    """
    group_ids = collect_group_ids(records)
    pools_by_group: dict[str, list[PoolAssignment]] = {}
    games_by_match_id: dict[str, GameResult] = {}
    standings_rows: list[tuple[str, Standing]] = []

    for group_id in group_ids:
        try:
            html = fetcher(group_id)
        except Exception:  # noqa: BLE001 — partial-success contract
            logger.exception("schedule fetch failed for group_id=%s", group_id)
            continue
        if not html:
            continue
        pools = parse_pool_assignments_from_html(html)
        if pools:
            pools_by_group[str(group_id)] = pools
        for game in parse_game_results_from_html(html):
            games_by_match_id[game.match_id] = game
        for standing in parse_standings_from_html(html):
            standings_rows.append((str(group_id), standing))

    games = list(games_by_match_id.values())
    write_pool_assignments(event_key, pools_by_group, base_dir=base_dir)
    write_game_results(event_key, games, base_dir=base_dir)
    write_standings(event_key, standings_rows, base_dir=base_dir)
    return pools_by_group, games, standings_rows
