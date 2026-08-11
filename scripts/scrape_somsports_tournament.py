#!/usr/bin/env python3
"""Scrape and import every game in a SOM Sports / athletes2events tournament.

Three-pass flow against ``somsports.athletes2events.com``:

  Pass 1: GET ``/events/{id}/groups`` → flight index. Filter by age range
          (``--age-min`` / ``--age-max``) and tier set (``--tiers``).
  Pass 2: For each in-scope flight, GET
          ``/events/{id}/schedules?flight-id={N}`` → standings + matches.
          Result is atomically written to
          ``reports/somsports/{event_id}/flights/{flight_id}.json``; that
          file's existence is the ``--resume`` marker.
  Pass 3: For each unique team across all flights, GET
          ``/events/{id}/schedules?team-id={N}`` → ``(STATE)`` code. The
          accumulator cache file is
          ``reports/somsports/{event_id}/team_details.json`` and is
          atomically extended after each fetch.

Final JSONL emit (after Pass 3 finishes for ALL in-scope teams) joins the
team-detail enrichment by ``provider_team_id`` and writes one row per
perspective (H + A) to
``data/raw/somsports_tournament_{event_id}_{ts}.jsonl``. ``--auto-import``
then shells to ``scripts/import_games_enhanced.py {out} somsports``.

Example:
    python scripts/scrape_somsports_tournament.py --event-id 72
    python scripts/scrape_somsports_tournament.py --event-id 72 --dry-run
    python scripts/scrape_somsports_tournament.py --event-id 72 --auto-import
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from uuid import uuid4

sys.path.append(str(Path(__file__).parent.parent))

# Windows-only: requests/urllib3 ship with a CA bundle that is missing the
# DigiCert intermediate athletes2events.com presents. ``truststore`` swaps
# requests over to the system trust store so the chain validates. No-op on
# Linux/CI where the default bundle already works.
# See ``memory/gotcha_python_supabase_ssl_truststore.md``.
try:
    import truststore  # noqa: E402

    truststore.inject_into_ssl()
except ImportError:
    pass

from dotenv import load_dotenv  # noqa: E402
from rich.console import Console  # noqa: E402

from src.scrapers.somsports import (  # noqa: E402
    FlightRef,
    ScrapedTeam,
    SomSportsScraper,
    TeamDetail,
    TournamentGame,
)
from src.utils.team_name_utils import extract_club_from_team_name  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)
console = Console()

_env_local = Path(".env.local")
if _env_local.exists():
    load_dotenv(_env_local)
else:
    load_dotenv()

RAW_DIR = Path("data/raw")
REPORTS_DIR = Path("reports/somsports")
DEFAULT_TIERS = ("oro", "plata", "bronce", "champions")


# ── Helpers ───────────────────────────────────────────────────────────────────


def _age_to_int(age: str) -> int:
    """``"u10"`` → ``10``. Raises if unparseable."""
    return int(age.lower().lstrip("u"))


def _atomic_write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, default=_json_default)
    os.replace(tmp, path)


def _json_default(obj):
    """``json.dump`` default callback: serialize ``date`` to ISO string and
    flat dataclass / object instances via their ``__dict__``. Called
    recursively by ``json.dump`` for any value it can't natively encode,
    so a list of dataclasses with nested ``date`` fields round-trips
    correctly in a single ``json.dump`` call.
    """
    if isinstance(obj, date):
        return obj.isoformat()
    if hasattr(obj, "__dict__"):
        return obj.__dict__
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def _flight_cache_path(event_id: int, flight_id: int) -> Path:
    return REPORTS_DIR / str(event_id) / "flights" / f"{flight_id}.json"


def _team_details_cache_path(event_id: int) -> Path:
    return REPORTS_DIR / str(event_id) / "team_details.json"


def _load_flight_cache(event_id: int, flight_id: int) -> Optional[Tuple[List[ScrapedTeam], List[TournamentGame]]]:
    path = _flight_cache_path(event_id, flight_id)
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        # Backward-compat: an earlier version of ScrapedTeam used field
        # name ``l`` for losses; renamed to ``losses`` (E741 lint fix).
        # Translate legacy cache rows so existing ``reports/somsports/.../
        # flights/*.json`` files from the previous version stay loadable
        # via ``--resume`` instead of crashing on the rename.
        for t in raw.get("teams", []):
            if "l" in t and "losses" not in t:
                t["losses"] = t.pop("l")
        teams = [ScrapedTeam(**t) for t in raw.get("teams", [])]
        games = [
            TournamentGame(
                game_id=g["game_id"],
                game_date=date.fromisoformat(g["game_date"]) if g.get("game_date") else None,
                kickoff_time=g.get("kickoff_time"),
                home_provider_team_id=g["home_provider_team_id"],
                home_team_name=g["home_team_name"],
                away_provider_team_id=g["away_provider_team_id"],
                away_team_name=g["away_team_name"],
                home_score=g.get("home_score"),
                away_score=g.get("away_score"),
                field=g.get("field"),
                venue=g.get("venue"),
                flight_id=g["flight_id"],
                group_letter=g.get("group_letter"),
            )
            for g in raw.get("games", [])
        ]
        return teams, games
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        logger.warning("Flight cache %s unreadable, refetching: %s", path, e)
        return None


def _save_flight_cache(event_id: int, flight_id: int, teams: List[ScrapedTeam], games: List[TournamentGame]) -> None:
    _atomic_write_json(
        _flight_cache_path(event_id, flight_id),
        {"teams": teams, "games": games},
    )


def _load_team_details_cache(event_id: int) -> Dict[str, TeamDetail]:
    path = _team_details_cache_path(event_id)
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        return {k: TeamDetail(**v) for k, v in raw.items()}
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        logger.warning("Team details cache %s unreadable, ignoring: %s", path, e)
        return {}


def _save_team_details_cache(event_id: int, details: Dict[str, TeamDetail]) -> None:
    _atomic_write_json(_team_details_cache_path(event_id), details)


def _compute_result(gf: Optional[int], ga: Optional[int]) -> str:
    if gf is None or ga is None:
        return "U"
    if gf > ga:
        return "W"
    if gf < ga:
        return "L"
    return "D"


def perspective_record(
    *,
    game: TournamentGame,
    perspective: str,
    flight: FlightRef,
    team_details: Dict[str, TeamDetail],
    event_id: int,
    event_name: str,
    scrape_run_id: str,
    scraped_at: str,
) -> Dict:
    """Build one canonical JSONL row for ``import_games_enhanced.py``.

    Mirrors ``scrape_affinity_wa_tournament`` / ``scrape_playmetrics_tournament``
    column shape — ``team_id``, ``opponent_id``, ``goals_for``,
    ``goals_against``, ``home_away``, ``state_code``, etc. ``perspective``
    is ``"H"`` or ``"A"``.
    """
    is_home = perspective == "H"
    team_id = game.home_provider_team_id if is_home else game.away_provider_team_id
    team_name = game.home_team_name if is_home else game.away_team_name
    opp_id = game.away_provider_team_id if is_home else game.home_provider_team_id
    opp_name = game.away_team_name if is_home else game.home_team_name
    goals_for = game.home_score if is_home else game.away_score
    goals_against = game.away_score if is_home else game.home_score

    team_state = (team_details.get(team_id).state_code if team_id in team_details else None) or ""
    opp_state = (team_details.get(opp_id).state_code if opp_id in team_details else None) or ""
    club = extract_club_from_team_name(team_name) or ""
    opp_club = extract_club_from_team_name(opp_name) or ""

    division_name = flight.raw_division_name or f"{flight.gender}-{flight.age_group.upper()}"
    source_url = f"https://somsports.athletes2events.com/events/{event_id}/schedules?flight-id={flight.flight_id}"

    return {
        "provider": "somsports",
        "scrape_run_id": scrape_run_id,
        "event_id": str(event_id),
        "event_name": event_name,
        "schedule_id": game.game_id,
        "age_year": "",
        "age_group": flight.age_group,
        "gender": flight.gender,
        "team_id": team_id,
        "team_id_source": team_id,
        "team_name": team_name,
        "club_name": club,
        "opponent_id": opp_id,
        "opponent_id_source": opp_id,
        "opponent_name": opp_name,
        "opponent_club_name": opp_club,
        "state": "",
        "state_code": team_state,
        "game_date": game.game_date.isoformat() if game.game_date else "",
        "game_time": game.kickoff_time or "",
        "home_away": "H" if is_home else "A",
        "goals_for": goals_for if goals_for is not None else "",
        "goals_against": goals_against if goals_against is not None else "",
        "result": _compute_result(goals_for, goals_against),
        "venue": game.venue or "",
        "source_url": source_url,
        "scraped_at": scraped_at,
        "meta": {
            "flight_id": flight.flight_id,
            "tier_label": flight.tier_label,
            "group_letter": game.group_letter,
            "field": game.field,
            "opponent_state_code": opp_state,
            "division_name": division_name,
        },
    }


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--event-id", type=int, required=True, help="SOM Sports event ID (e.g., 72 for Club America Cup)")
    p.add_argument("--age-min", type=str, default="u10", help="Minimum age group (default: u10)")
    p.add_argument("--age-max", type=str, default="u19", help="Maximum age group (default: u19)")
    p.add_argument(
        "--tiers",
        type=str,
        default="all",
        help="Comma-separated tier substrings (oro,plata,bronce,champions) or 'all' (default).",
    )
    p.add_argument("--output-dir", type=Path, default=RAW_DIR, help=f"Output dir for JSONL (default: {RAW_DIR})")
    p.add_argument(
        "--resume", action="store_true", help="Skip flights already cached under reports/somsports/{event_id}/"
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Run Passes 1-3 (network) but skip the final JSONL write. "
            "Per-flight + team_details caches under reports/somsports/{event_id}/ "
            "ARE still written so a follow-up non-dry-run benefits from prefetched state."
        ),
    )
    p.add_argument("--auto-import", action="store_true", help="Run import_games_enhanced.py after writing the JSONL")
    return p.parse_args()


def _tier_matches(tier_label: str, tier_set: Tuple[str, ...]) -> bool:
    label = tier_label.lower()
    return any(t in label for t in tier_set)


def _filter_flights(flights: List[FlightRef], age_min: int, age_max: int, tier_set: Tuple[str, ...]) -> List[FlightRef]:
    # ``f.age_group`` is guaranteed by ``parse_groups_page`` to be one of
    # ``u6``..``u19`` (via ``normalize_age``), so ``_age_to_int`` cannot
    # raise here — no defensive try/except needed.
    kept: List[FlightRef] = []
    for f in flights:
        n = _age_to_int(f.age_group)
        if n < age_min or n > age_max:
            continue
        if tier_set and not _tier_matches(f.tier_label, tier_set):
            continue
        kept.append(f)
    return kept


def main() -> int:
    args = parse_args()
    event_id = args.event_id
    age_min = _age_to_int(args.age_min)
    age_max = _age_to_int(args.age_max)
    tier_arg = args.tiers.strip().lower()
    tier_set: Tuple[str, ...] = () if tier_arg == "all" else tuple(t.strip() for t in tier_arg.split(",") if t.strip())

    scraped_at = datetime.now(timezone.utc).isoformat()
    scrape_run_id = f"{scraped_at}_{uuid4().hex[:6]}"

    scraper = SomSportsScraper()

    # ── Pass 1: groups ────────────────────────────────────────────────────────
    try:
        event_name, all_flights = scraper.fetch_groups(event_id)
    except Exception as e:
        console.print(f"[red]Failed to fetch groups for event {event_id}: {e}[/red]")
        return 1
    event_name = event_name or f"Event {event_id}"
    in_scope = _filter_flights(all_flights, age_min, age_max, tier_set)
    console.print(
        f"[cyan]Event {event_id} '{event_name}': {len(all_flights)} flights total, "
        f"{len(in_scope)} in scope (ages u{age_min}-u{age_max}, "
        f"tiers={list(tier_set) if tier_set else 'all'})[/cyan]"
    )

    # ── Pass 2: per-flight scrape with --resume support ───────────────────────
    teams_by_flight: Dict[int, List[ScrapedTeam]] = {}
    games_by_flight: Dict[int, List[TournamentGame]] = {}
    resumed_count = 0
    fetched_count = 0
    flight_errors: List[Dict] = []

    for flight in in_scope:
        cached = _load_flight_cache(event_id, flight.flight_id) if args.resume else None
        if cached is not None:
            teams, games = cached
            resumed_count += 1
            logger.info("Resumed flight %d from cache (%d teams, %d games)", flight.flight_id, len(teams), len(games))
        else:
            try:
                teams, games = scraper.fetch_flight(event_id, flight.flight_id)
            except Exception as e:
                logger.error("Flight %d fetch failed: %s", flight.flight_id, e)
                flight_errors.append({"flight_id": flight.flight_id, "error": str(e)})
                continue
            _save_flight_cache(event_id, flight.flight_id, teams, games)
            fetched_count += 1
        teams_by_flight[flight.flight_id] = teams
        games_by_flight[flight.flight_id] = games

    # ── Pass 3: team-detail enrichment (deduped across flights) ────────────────
    unique_team_ids: Dict[str, str] = {}  # team_id -> first team_name seen
    for flight_id, teams in teams_by_flight.items():
        for t in teams:
            unique_team_ids.setdefault(t.provider_team_id, t.team_name)
    for games in games_by_flight.values():
        for g in games:
            unique_team_ids.setdefault(g.home_provider_team_id, g.home_team_name)
            unique_team_ids.setdefault(g.away_provider_team_id, g.away_team_name)

    team_details = _load_team_details_cache(event_id)
    missing = [tid for tid in unique_team_ids if tid not in team_details]
    console.print(
        f"[cyan]Pass 3: {len(unique_team_ids)} unique teams; {len(team_details)} cached, {len(missing)} to fetch[/cyan]"
    )
    for tid in missing:
        try:
            detail = scraper.fetch_team_detail(event_id, tid)
        except Exception as e:
            logger.warning("Team detail fetch failed for %s: %s", tid, e)
            detail = TeamDetail(provider_team_id=tid, state_code=None, coach=None, manager=None)
        team_details[tid] = detail
        _save_team_details_cache(event_id, team_details)

    states_seen = sorted({d.state_code for d in team_details.values() if d.state_code})
    console.print(f"[cyan]Pass 3 done: {len(team_details)} team details cached; distinct states: {states_seen}[/cyan]")

    # ── Summary ───────────────────────────────────────────────────────────────
    games_total = sum(len(g) for g in games_by_flight.values())
    played = sum(1 for g_list in games_by_flight.values() for g in g_list if g.home_score is not None)
    console.print(
        f"[cyan]Pass 2 done: {fetched_count} flights fetched, {resumed_count} resumed, "
        f"{len(flight_errors)} errors. {games_total} games total ({played} played).[/cyan]"
    )

    if args.dry_run:
        console.print("[yellow]Dry run — caches written, JSONL skipped.[/yellow]")
        return 0

    # ── Final JSONL emit (H + A per played game) ──────────────────────────────
    flights_by_id = {f.flight_id: f for f in in_scope}
    args.output_dir.mkdir(parents=True, exist_ok=True)
    out = args.output_dir / f"somsports_tournament_{event_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl"
    rows_written = 0
    with open(out, "w", encoding="utf-8") as f:
        for flight_id, games in games_by_flight.items():
            flight = flights_by_id.get(flight_id)
            if not flight:
                continue
            for game in games:
                if game.home_score is None or game.away_score is None:
                    continue  # drop unplayed
                if not game.game_date:
                    continue  # drop rows without a date
                for perspective in ("H", "A"):
                    row = perspective_record(
                        game=game,
                        perspective=perspective,
                        flight=flight,
                        team_details=team_details,
                        event_id=event_id,
                        event_name=event_name,
                        scrape_run_id=scrape_run_id,
                        scraped_at=scraped_at,
                    )
                    f.write(json.dumps(row) + "\n")
                    rows_written += 1
    console.print(f"[green]Wrote {rows_written} JSONL rows -> {out}[/green]")

    if not args.auto_import:
        console.print(f"\nTo import:  python scripts/import_games_enhanced.py {out} somsports")
        return 0

    console.print("[cyan]Running import_games_enhanced.py ...[/cyan]")
    rc = subprocess.run(
        [sys.executable, "scripts/import_games_enhanced.py", str(out), "somsports"],
        check=False,
    ).returncode
    if rc != 0:
        console.print(f"[red]Import exited with code {rc}[/red]")
    return rc


if __name__ == "__main__":
    sys.exit(main())
