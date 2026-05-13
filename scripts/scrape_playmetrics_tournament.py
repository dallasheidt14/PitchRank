"""PlayMetrics tournament scraper.

Mirrors ``scrape_playmetrics_league.py`` but flips three tournament-shape
behaviors that distinguish a tournament event from a season-long league:

  1. **No ``GB_STATE_MAP`` requirement.** Tournaments cross state lines
     (e.g. 2026 Race City has both NC and SC venues). State assignment is
     deferred — every row writes ``state`` and ``state_code`` as empty
     strings; the matcher resolves team state via club lookup at import.
     Game-date timezone conversion uses the venue's state when available
     (since the *game* really did happen there), falling back to UTC slice.

  2. **Age group derives from division name first.** PlayMetrics tournament
     divisions report ``min_age=0``/``None`` (vs. real cohort numbers in
     leagues), so the league-style ``min_age``-fallback skips every division.
     Tournaments use unambiguous U-tokens in the division name itself
     (``"U19 Boys Blue"``) — parse those directly, then fall back to the
     team's own name (existing ``derive_team_age_group``), then to
     ``min_age`` if nothing else.

  3. **Provider code + event identity.** Rows are tagged
     ``provider="playmetrics_tournament"`` with
     ``event_id="pm_tourney_{gb}_{league_id}"`` so they don't collide with
     SECL-style rows during import or matching. ``event_name`` carries the
     PlayMetrics league name (the tournament name, e.g. "2026 Race City").

The matcher refactor in ``src/models/playmetrics_matcher.py`` activates the
no-state path automatically when constructed with ``default_state_code=None``,
which the importer does for ``provider_code="playmetrics_tournament"``.
"""
from __future__ import annotations

import argparse
import csv
import os
import re
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

# Add parent for imports.
sys.path.append(str(Path(__file__).parent.parent))

from scripts.scrape_playmetrics_league import (  # noqa: E402
    REQUIRED_COLUMNS,
    STATE_CODE_TO_TIMEZONE,
    _build_venue,
    _parse_league_url,
    compute_result,
    derive_team_age_group,
    get_division,
    get_league,
    map_min_age_to_age_group,
    parse_int_or_none,
)

OUTPUT_DIR = "data/raw/playmetrics_tournament"

# Global scrape identifiers (set in main()).
SCRAPE_TS: Optional[str] = None
SCRAPE_RUN_ID: Optional[str] = None

# Division name → cohort token. Tournament divisions almost always carry an
# unambiguous ``U{N}`` somewhere in the name (``"U19 Boys Blue"``,
# ``"U15/16 Boys Tan (2)"``). PitchRank tracks u10..u17 + u19 (u18 merges
# into u19); ``min_age``-style numerical edge cases are out of band.
# Slash form ``U15/16`` matches both numbers (the second number lacks its
# own U prefix); single ``U13`` matches just one.
_DIV_U_SLASH_RE = re.compile(r"\b[Uu](\d{1,2})/(\d{1,2})\b")
_DIV_U_TOKEN_RE = re.compile(r"\b[Uu](\d{1,2})\b")
# Per-game venue state extraction. PM venue addresses are formatted as
# ``"... City, ST 28115, USA"`` — pull the 2-letter state.
_VENUE_STATE_RE = re.compile(r",\s*([A-Z]{2})\s+\d{5}")


def derive_division_age_group(division_name: str) -> Optional[str]:
    """Pull a u-cohort out of a tournament division name.

    Returns ``"u11"``..``"u17"`` or ``"u19"``; ``None`` if no recognizable
    U-token is present (caller falls back to team-name derivation, then
    ``min_age``).

    Dual-age cohorts (``"U15/16 Boys Tan (2)"``) → take the **higher** U-age,
    which is the OLDER cohort per the unified PitchRank rule (see
    ``memory/gotcha_slash_age_tokens.md``: older players play up; team is
    classified as their primary tier).
    """
    if not division_name:
        return None
    nums: List[int] = []
    slash = _DIV_U_SLASH_RE.search(division_name)
    if slash:
        nums.extend([int(slash.group(1)), int(slash.group(2))])
    else:
        nums.extend(int(m) for m in _DIV_U_TOKEN_RE.findall(division_name))
    if not nums:
        return None
    older = max(nums)
    if 10 <= older <= 17:
        return f"u{older}"
    if older in (18, 19):
        return "u19"
    return None


def derive_state_from_address(address: str) -> Optional[str]:
    """Pull the 2-letter state from a venue address. Returns ``None`` on miss."""
    if not address:
        return None
    m = _VENUE_STATE_RE.search(address)
    return m.group(1) if m else None


def parse_utc_to_local_date(iso_utc: str, venue_state: Optional[str]) -> str:
    """Convert UTC ISO timestamp to local YYYY-MM-DD using the venue's tz.

    Tournament rows leave the ``state`` column blank, but the *game* itself
    happens at a specific venue, and that venue's local date is what people
    expect to see. Use the venue address's state to pick the IANA tz; fall
    back to a UTC slice when the venue address is unparseable or its state
    isn't in ``STATE_CODE_TO_TIMEZONE``.
    """
    if not iso_utc:
        return ""
    tz_name = STATE_CODE_TO_TIMEZONE.get(venue_state or "")
    if not tz_name:
        return iso_utc[:10]
    try:
        dt_iso = iso_utc.rstrip("Z")
        dt = datetime.fromisoformat(dt_iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(ZoneInfo(tz_name)).strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return iso_utc[:10]


# Extra timezone entries needed for tournaments (the league scraper only had
# WI). Add common youth-soccer states; missing entries fall back to UTC slice
# which is wrong by ~12 hours but won't break.
_TOURNAMENT_TIMEZONES: Dict[str, str] = {
    "NC": "America/New_York",
    "SC": "America/New_York",
    "VA": "America/New_York",
    "WV": "America/New_York",
    "GA": "America/New_York",
    "TN": "America/Chicago",
    "KY": "America/New_York",
    "OH": "America/New_York",
    "FL": "America/New_York",
    "AL": "America/Chicago",
    "MS": "America/Chicago",
    "TX": "America/Chicago",
    "OK": "America/Chicago",
    "AR": "America/Chicago",
    "LA": "America/Chicago",
    "IL": "America/Chicago",
    "IN": "America/New_York",
    "MI": "America/New_York",
    "MN": "America/Chicago",
    "WI": "America/Chicago",
    "IA": "America/Chicago",
    "MO": "America/Chicago",
    "KS": "America/Chicago",
    "NE": "America/Chicago",
    "ND": "America/Chicago",
    "SD": "America/Chicago",
    "CO": "America/Denver",
    "WY": "America/Denver",
    "MT": "America/Denver",
    "ID": "America/Denver",
    "UT": "America/Denver",
    "NM": "America/Denver",
    "AZ": "America/Phoenix",
    "NV": "America/Los_Angeles",
    "CA": "America/Los_Angeles",
    "OR": "America/Los_Angeles",
    "WA": "America/Los_Angeles",
    "AK": "America/Anchorage",
    "HI": "Pacific/Honolulu",
    "PA": "America/New_York",
    "NY": "America/New_York",
    "NJ": "America/New_York",
    "MD": "America/New_York",
    "DE": "America/New_York",
    "DC": "America/New_York",
    "MA": "America/New_York",
    "CT": "America/New_York",
    "RI": "America/New_York",
    "NH": "America/New_York",
    "VT": "America/New_York",
    "ME": "America/New_York",
}
# Merge into the shared map without overwriting existing entries (so SECL's
# WI mapping wins if a future contributor adds something there).
for _code, _tz in _TOURNAMENT_TIMEZONES.items():
    STATE_CODE_TO_TIMEZONE.setdefault(_code, _tz)


def resolve_config() -> Dict:
    parser = argparse.ArgumentParser(description="PlayMetrics Tournament Scraper")
    parser.add_argument("--tournament-url", type=str, help="Full tournament URL")
    parser.add_argument("--governing-body-id", type=int, help="Governing body ID")
    parser.add_argument("--league-id", type=int, help="League ID (PM uses this for tournaments too)")
    parser.add_argument("--key", type=str, help="League key token")
    parser.add_argument("--output-dir", type=str, help="Output directory")
    parser.add_argument("--dry-run", action="store_true", help="Validate without writing output")
    args = parser.parse_args()

    tournament_url = args.tournament_url or os.getenv("PLAYMETRICS_TOURNAMENT_URL")
    gb_id = args.governing_body_id
    league_id = args.league_id
    key = args.key

    if tournament_url and not (gb_id and league_id and key):
        parsed = _parse_league_url(tournament_url)
        if not parsed:
            print(f"❌ Could not parse tournament URL: {tournament_url}")
            sys.exit(1)
        gb_id, league_id, key = parsed

    if not (gb_id and league_id and key):
        print("❌ Must provide --tournament-url OR all three of --governing-body-id/--league-id/--key")
        sys.exit(1)

    output_dir = args.output_dir or os.getenv("PLAYMETRICS_TOURNAMENT_OUTPUT_DIR", OUTPUT_DIR)
    delay_sec = float(os.getenv("PLAYMETRICS_DELAY_SEC", "0.3"))

    return {
        "governing_body_id": gb_id,
        "league_id": league_id,
        "key": key,
        "output_dir": output_dir,
        "dry_run": args.dry_run,
        "delay_sec": delay_sec,
    }


def _build_source_url(gb_id: int, league_id: int, key: str, division_id: int) -> str:
    return (
        f"https://playmetricssports.com/g/leagues/{gb_id}-{league_id}-{key}/divisions/{division_id}/division_view.html"
    )


def normalize_game(
    game: Dict,
    team_lookup: Dict[str, Dict],
    division: Dict,
    league_name: str,
    gb_id: int,
    league_id: int,
    key: str,
    division_age_group: str,
    gender: str,
    event_id: str,
) -> Optional[List[Dict]]:
    """Map a PlayMetrics tournament schedule game to canonical CSV rows.

    Per-team ``age_group`` is derived first from the team's own name (catches
    play-up teams whose name carries an explicit cohort), falling back to the
    division-name-derived ``division_age_group``. Per-row ``state`` and
    ``state_code`` are blank — the matcher resolves team state at import via
    the club lookup. ``game_date`` is converted to local using the venue's
    state when parseable.
    """
    home_key = str(game.get("home_team_id"))
    away_key = str(game.get("away_team_id"))
    home_entry = team_lookup[home_key]
    away_entry = team_lookup[away_key]

    home_score = parse_int_or_none(game.get("home_team_score"))
    away_score = parse_int_or_none(game.get("away_team_score"))

    field = game.get("field") or {}
    venue_state = derive_state_from_address(str(field.get("address") or ""))
    start_dt_raw = str(game.get("start_datetime") or "").strip()
    game_date = parse_utc_to_local_date(start_dt_raw, venue_state)
    game_time = str(game.get("time") or "").strip()
    venue = _build_venue(field)

    division_id = division.get("id")
    division_name = str(division.get("name") or "").strip()
    source_url = _build_source_url(gb_id, league_id, key, division_id) if division_id is not None else ""

    home_team_name = home_entry.get("team_name", "")
    away_team_name = away_entry.get("team_name", "")
    home_age_group = derive_team_age_group(home_team_name, division_age_group)
    away_age_group = derive_team_age_group(away_team_name, division_age_group)

    base = {
        "provider": "playmetrics_tournament",
        "scrape_run_id": SCRAPE_RUN_ID,
        "event_id": event_id,
        "event_name": league_name,
        "schedule_id": str(game.get("id") or ""),
        "age_year": "",
        "gender": gender,
        # State columns deliberately blank for tournament rows — matcher
        # resolves team state at import via club lookup.
        "state": "",
        "state_code": "",
        "game_date": game_date,
        "game_time": game_time,
        "venue": venue,
        "source_url": source_url,
        "scraped_at": SCRAPE_TS,
        "division_name": division_name,
    }

    home_row = {
        **base,
        "age_group": home_age_group,
        "team_id": home_key,
        "team_id_source": home_key,
        "team_name": home_team_name,
        "club_name": home_entry.get("club_name", ""),
        "opponent_id": away_key,
        "opponent_id_source": away_key,
        "opponent_name": away_team_name,
        "opponent_club_name": away_entry.get("club_name", ""),
        "home_away": "H",
        "goals_for": home_score if home_score is not None else "",
        "goals_against": away_score if away_score is not None else "",
        "result": compute_result(home_score, away_score),
    }
    away_row = {
        **base,
        "age_group": away_age_group,
        "team_id": away_key,
        "team_id_source": away_key,
        "team_name": away_team_name,
        "club_name": away_entry.get("club_name", ""),
        "opponent_id": home_key,
        "opponent_id_source": home_key,
        "opponent_name": home_team_name,
        "opponent_club_name": home_entry.get("club_name", ""),
        "home_away": "A",
        "goals_for": away_score if away_score is not None else "",
        "goals_against": home_score if home_score is not None else "",
        "result": compute_result(away_score, home_score),
    }
    return [home_row, away_row]


def scrape_division(
    division: Dict,
    league_name: str,
    config: Dict,
    event_id: str,
) -> Tuple[List[Dict], Dict[str, int]]:
    counts = {
        "games_emitted": 0,
        "skipped_non_played": 0,
        "skipped_forfeit": 0,
        "skipped_other_status": 0,
        "skipped_orphan": 0,
        "skipped_no_age": 0,
        "futsal": 0,
    }

    division_id = division.get("id")
    division_name = str(division.get("name") or "").strip()
    if division_id is None:
        print(f"  ⚠️ Division missing id: {division_name}")
        return [], counts

    # Tournament-specific age derivation: division name first, then min_age fallback.
    division_age_group = derive_division_age_group(division_name) or map_min_age_to_age_group(division.get("min_age"))
    if not division_age_group:
        print(f"  ⏭️  {division_name}: skipping (no recognizable U-token in division name)")
        counts["skipped_no_age"] = 1
        return [], counts

    gender_raw = str(division.get("gender") or "").strip().upper()
    gender = "Male" if gender_raw == "M" else "Female"

    gb_id = config["governing_body_id"]
    league_id = config["league_id"]
    key = config["key"]

    div_data = get_division(gb_id, league_id, key, division_id)

    sport_config = div_data.get("sport_configuration")
    sport_name = ""
    if isinstance(sport_config, dict):
        sport_name = str(sport_config.get("name") or "").strip()
    if not sport_name:
        print(f"  ⚠️ {division_name}: sport_configuration missing or unnamed (not skipped)")
    elif "futsal" in sport_name.lower():
        print(f"  ⏭️  {division_name}: skipping (futsal)")
        counts["futsal"] = 1
        return [], counts

    teams = div_data.get("teams") or []
    schedule = div_data.get("schedule") or []

    team_lookup: Dict[str, Dict] = {}
    for entry in teams:
        team = entry.get("team") or {}
        club = entry.get("club") or {}
        team_id = team.get("id")
        if team_id is None:
            continue
        team_lookup[str(team_id)] = {
            "team_name": str(team.get("name") or "").strip(),
            "club_id": club.get("id"),
            "club_name": str(club.get("name") or "").strip(),
        }

    records: List[Dict] = []
    for game in schedule:
        status = str(game.get("status") or "").strip()
        if status != "Played":
            counts["skipped_non_played"] += 1
            if status.lower() == "forfeit":
                counts["skipped_forfeit"] += 1
            else:
                counts["skipped_other_status"] += 1
            continue

        home_id = game.get("home_team_id")
        away_id = game.get("away_team_id")
        if home_id is None or away_id is None or str(home_id) not in team_lookup or str(away_id) not in team_lookup:
            counts["skipped_orphan"] += 1
            print(f"  ⚠️ {division_name}: orphan game id={game.get('id')} home={home_id} away={away_id}")
            continue

        rows = normalize_game(
            game,
            team_lookup,
            division,
            league_name,
            gb_id,
            league_id,
            key,
            division_age_group,
            gender,
            event_id,
        )
        if rows:
            records.extend(rows)
            counts["games_emitted"] += 1

    print(
        f"  ✅ {division_name} ({division_age_group}, {gender}): {counts['games_emitted']} games "
        f"({counts['skipped_non_played']} non-played, {counts['skipped_orphan']} orphan)"
    )
    return records, counts


def scrape_tournament(config: Dict) -> Tuple[List[Dict], Dict]:
    gb_id = config["governing_body_id"]
    league_id = config["league_id"]
    key = config["key"]
    event_id = f"pm_tourney_{gb_id}_{league_id}"

    summary = {
        "league_name": "",
        "event_id": event_id,
        "division_total": 0,
        "division_processed": 0,
        "futsal_dropped": 0,
        "no_age_skipped": 0,
        "games_emitted": 0,
        "skipped_non_played": 0,
        "skipped_forfeit": 0,
        "skipped_other_status": 0,
        "skipped_orphan": 0,
    }

    league_data = get_league(gb_id, league_id, key)
    league_name = str(league_data.get("name") or f"Tournament {league_id}").strip()
    divisions = league_data.get("divisions") or []
    summary["league_name"] = league_name
    summary["division_total"] = len(divisions)

    print(f"\n📌 TOURNAMENT: {league_name}")
    print(f"   event_id: {event_id}")
    print(f"   Divisions: {len(divisions)}")

    all_records: List[Dict] = []
    for division in divisions:
        records, counts = scrape_division(division, league_name, config, event_id)
        time.sleep(config["delay_sec"])
        if counts["futsal"]:
            summary["futsal_dropped"] += 1
            continue
        if counts["skipped_no_age"]:
            summary["no_age_skipped"] += 1
            continue
        all_records.extend(records)
        summary["division_processed"] += 1
        summary["games_emitted"] += counts["games_emitted"]
        summary["skipped_non_played"] += counts["skipped_non_played"]
        summary["skipped_forfeit"] += counts["skipped_forfeit"]
        summary["skipped_other_status"] += counts["skipped_other_status"]
        summary["skipped_orphan"] += counts["skipped_orphan"]

    return all_records, summary


def validate_records(records: List[Dict]) -> None:
    if not records:
        return
    for i, r in enumerate(records):
        missing = [col for col in REQUIRED_COLUMNS if col not in r]
        if missing:
            raise ValueError(f"Record {i} missing columns: {missing}")


def write_output(records: List[Dict], config: Dict) -> Path:
    output_dir = Path(config["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = SCRAPE_TS.replace(":", "-").replace(".", "-")
    fname = (
        f"playmetrics_tournament_{config['governing_body_id']}_{config['league_id']}_"
        f"{config['key']}_{timestamp}.csv"
    )
    path = output_dir / fname

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=REQUIRED_COLUMNS)
        writer.writeheader()
        writer.writerows(records)

    print(f"\n✅ OUTPUT: {path}")
    return path


def main() -> None:
    global SCRAPE_TS, SCRAPE_RUN_ID

    SCRAPE_TS = datetime.now(timezone.utc).isoformat()
    SCRAPE_RUN_ID = f"{SCRAPE_TS}_{uuid.uuid4().hex[:6]}"

    config = resolve_config()

    print("🚀 PlayMetrics Tournament Scraper")
    print(f"🏛️  Governing body: {config['governing_body_id']}")
    print(f"🆔 Tournament: {config['league_id']}-{config['key']}")
    print(f"🆔 Scrape run ID: {SCRAPE_RUN_ID}")

    scrape_start = time.time()
    records, summary = scrape_tournament(config)
    scrape_duration = time.time() - scrape_start

    if records:
        validate_records(records)

    if not config["dry_run"]:
        write_output(records, config)
        if not records:
            print("⚠️  No games scraped — empty CSV written (headers only)")
    else:
        print(f"\n🔍 DRY RUN — {len(records)} rows validated (not written)")

    print(
        f"\n📊 Scraped {summary['games_emitted']} games across {summary['division_processed']} divisions; "
        f"{summary['skipped_non_played']} non-played games dropped "
        f"({summary['skipped_forfeit']} forfeits, {summary['skipped_other_status']} other statuses); "
        f"{summary['futsal_dropped']} futsal divisions skipped, "
        f"{summary['no_age_skipped']} divisions skipped (no U-token)."
    )
    print(f"⏱️  Total time: {scrape_duration:.1f}s")


if __name__ == "__main__":
    main()
