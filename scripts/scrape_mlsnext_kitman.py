#!/usr/bin/env python3
"""Scrape MLS NEXT (Homegrown and Academy Divisions) from Kitman's public schedule files.

From 2026-27 MLS NEXT publishes through Kitman Labs; the mlssoccer.com schedule pages embed these
JSON files. Each file is ``{events, linked_competition_seasons, synced_at}`` and one GET fetches a
whole season. Writes ``<out-dir>/squads.csv``, ``games.csv`` and ``unreadable_squads.csv`` and never touches the
database.

A squad is one club at one age in one division. The file decides the division (the league and flex
files are Homegrown, the academy file is Academy); the squad label ("U16", "U16 AD") only has to
agree with it. MLS NEXT is boys-only and the files carry no gender field.

Usage:
    python scripts/scrape_mlsnext_kitman.py
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.models.mlsnext_kitman_keys import kitman_key, season_start_year  # noqa: E402

BASE_URL = "https://mls-assist.theintelligenceplatform.com/data/schedule"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; PitchRank/1.0)"}
FEEDS = (("mls-next-league", "HD", 3000), ("mls-next-flex", "HD", 1000), ("mls-next-2-academy-division", "AD", 5000))
SQUAD_RE = re.compile(r"U(13|14|15|16|17|19)( AD)?")
IN_SEASON_FROM = (9, 20)
SQUAD_COLUMNS = [
    "provider_team_id",
    "key",
    "club_id",
    "club_name",
    "display_name",
    "age_group",
    "division",
    "gender",
    "season",
]
GAME_COLUMNS = [
    "event_id",
    "game_date",
    "status",
    "division",
    "competition",
    "age_group",
    "home_squad_id",
    "away_squad_id",
    "home_key",
    "away_key",
    "home_score",
    "away_score",
]


class ScrapeError(RuntimeError):
    """A feed no longer has the shape this scraper reads, or is not the season it should be."""


@dataclass(frozen=True)
class Squad:
    squad_id: str
    club_id: str
    club_name: str
    age_group: str
    division: str

    @property
    def display_name(self) -> str:
        return f"{self.club_name} U{self.age_group[1:]} {self.division}"


def season_suffix(season: int) -> str:
    return f"{season % 100:02d}-{(season + 1) % 100:02d}"


def feed_url(stem: str, season: int) -> str:
    return f"{BASE_URL}/{stem}-{season_suffix(season)}.json"


def parse_feed(content: bytes, stem: str, season: int, floor: int) -> list[dict]:
    """The events of one feed. The host answers an unknown file with the site's HTML at status 200."""
    try:
        data = json.loads(content)
    except ValueError as exc:
        raise ScrapeError(f"{stem}: response is not JSON ({exc})") from exc
    if not isinstance(data, dict) or not isinstance(data.get("events"), list):
        raise ScrapeError(f"{stem}: no events array")
    key = f"{stem}-{season_suffix(season)}"
    linked = {s.get("key") for s in data.get("linked_competition_seasons") or []}
    if linked and key not in linked:
        raise ScrapeError(f"{stem}: feed lists seasons {sorted(map(str, linked))}, not {key}")
    if len(data["events"]) < floor:
        raise ScrapeError(f"{stem}: {len(data['events'])} events is below the floor of {floor}")
    return data["events"]


def local_date(event: dict) -> str:
    zone = event.get("local_timezone")
    try:
        stamp = datetime.fromisoformat(str(event["start_time"]).replace("Z", "+00:00"))
        return stamp.astimezone(ZoneInfo(zone)).date().isoformat()
    except (KeyError, ValueError, TypeError) as exc:
        raise ScrapeError(f"event {event.get('id')}: unreadable start_time/local_timezone ({exc})") from exc


def _side(event: dict, side: str, division: str) -> tuple[Squad | None, str]:
    """The squad on one side, or None with the reason the label cannot be read."""
    org = event.get(f"{side}_organisation") or {}
    label = str(event.get(f"{side}_squad_name") or "")
    match = SQUAD_RE.fullmatch(label)
    if match is None:
        return None, f"squad label {label!r} is not a board age"
    if bool(match.group(2)) != (division == "AD"):
        return None, f"squad label {label!r} disagrees with the {division} feed"
    squad_id, club_id = event.get(f"{side}_squad_id"), org.get("id")
    if squad_id is None or club_id is None or not org.get("name"):
        return None, "squad or club id missing"
    return Squad(str(squad_id), str(club_id), str(org["name"]).strip(), f"u{match.group(1)}", division), ""


def build(feeds: list[tuple[str, list[dict]]], season: int) -> tuple[dict[str, Squad], list[dict], dict[str, str]]:
    """Squads by id, one game row per event, and the reason each unreadable squad id was left out."""
    squads: dict[str, Squad] = {}
    unreadable: dict[str, str] = {}
    games: dict[str, dict] = {}
    for division, events in feeds:
        for event in events:
            sides = {side: _side(event, side, division) for side in ("home", "away")}
            for side, (squad, why) in sides.items():
                sid = event.get(f"{side}_squad_id")
                if squad is None:
                    unreadable.setdefault(str(sid), why)
                    continue
                prior = squads.setdefault(squad.squad_id, squad)
                if prior != squad:
                    raise ScrapeError(f"squad {squad.squad_id} seen as {prior} and as {squad}")
            event_id = str(event["id"])
            if event_id in games:
                continue
            home, away = sides["home"][0], sides["away"][0]
            scored = event.get("home_score") is not None and event.get("away_score") is not None
            games[event_id] = {
                "event_id": event_id,
                "game_date": local_date(event),
                "status": "played" if event.get("completed") and scored else "scheduled",
                "division": division,
                "competition": (event.get("competition") or {}).get("name", ""),
                "age_group": (home or away).age_group if (home or away) else "",
                "home_squad_id": home.squad_id if home else "",
                "away_squad_id": away.squad_id if away else "",
                "home_key": kitman_key(home.squad_id, season) if home else "",
                "away_key": kitman_key(away.squad_id, season) if away else "",
                "home_score": event["home_score"] if scored else "",
                "away_score": event["away_score"] if scored else "",
            }
    return squads, list(games.values()), unreadable


def _write_csv(path: Path, columns: list[str], rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def run(out_dir: Path, session, today: date) -> dict[str, int]:
    season = season_start_year(today)
    feeds = []
    for stem, division, floor in FEEDS:
        response = session.get(feed_url(stem, season), headers=HEADERS, timeout=60)
        response.raise_for_status()
        feeds.append((division, parse_feed(response.content, stem, season, floor)))
    squads, games, unreadable = build(feeds, season)
    played = sum(g["status"] == "played" for g in games)
    if played == 0 and (today.month, today.day) >= IN_SEASON_FROM and today.year == season:
        raise ScrapeError("no scored games in an in-season feed")
    out_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(
        out_dir / "squads.csv",
        SQUAD_COLUMNS,
        [
            {
                "provider_team_id": s.squad_id,
                "key": kitman_key(s.squad_id, season),
                "club_id": s.club_id,
                "club_name": s.club_name,
                "display_name": s.display_name,
                "age_group": s.age_group,
                "division": s.division,
                "gender": "Male",
                "season": season,
            }
            for s in sorted(squads.values(), key=lambda s: (s.division, s.age_group, s.club_name, s.squad_id))
        ],
    )
    _write_csv(out_dir / "games.csv", GAME_COLUMNS, games)
    _write_csv(
        out_dir / "unreadable_squads.csv",
        ["squad_id", "reason"],
        [{"squad_id": sid, "reason": why} for sid, why in sorted(unreadable.items())],
    )
    return {
        "squads": len(squads),
        "unreadable_squads": len(unreadable),
        "games": len(games),
        "played": played,
        "scheduled": len(games) - played,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out-dir", type=Path, default=Path("data/mlsnext_kitman"))
    args = parser.parse_args(argv)
    try:
        counts = run(args.out_dir, requests.Session(), date.today())
    except (ScrapeError, requests.RequestException) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(" ".join(f"{key}={value}" for key, value in counts.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
