#!/usr/bin/env python3
"""Scrape MLS NEXT (Homegrown and Academy Divisions) from Kitman's public standings files.

From 2026-27 MLS NEXT publishes through Kitman Labs. Each file is ``{version, competition_season, synced_at}``
and one GET fetches a whole season: ``competition_season`` holds the events and the clubs and competitions they
name by id. Do not go back to Kitman's ``/data/schedule`` files, which stopped updating in October 2026 and lost
Flex. Writes ``<out-dir>/squads.csv``, ``games.csv`` and ``unreadable_squads.csv`` and never touches the database.

A squad is one club's team at one age in one division. A club can field a second Homegrown squad at
an age, labelled with a B ("U17B"): it plays on the base age's board and is named with a "II". The file
decides the division (the league file is Homegrown, Flex included; the academy file is Academy); the
squad label ("U16", "U17B", "U16 AD") only has to agree with it. MLS NEXT is boys-only and the events
carry no gender field.

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

BASE_URL = "https://mls-assist.theintelligenceplatform.com/data/standings"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; PitchRank/1.0)"}
FEEDS = (
    ("mls-next-league", "HD", {"League": 3000, "League (Pro Player Pathway)": 200, "MLS NEXT Flex": 1000}),
    ("mls-next-2-academy-division", "AD", {"Academy Division": 5000}),
)
SQUAD_RE = re.compile(r"U(?P<age>13|14|15|16|17|19)(?P<suffix>B(?! AD))?(?P<ad> AD)?")
SUFFIX_NUMERALS = {"B": "II"}
IN_SEASON_FROM = (9, 20)
MAX_SYNC_AGE_DAYS = 8
SQUAD_COLUMNS = [
    "provider_team_id",
    "key",
    "club_id",
    "club_name",
    "display_name",
    "age_group",
    "division",
    "suffix",
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
    """A feed this scraper cannot trust; the run stops before writing anything."""


@dataclass(frozen=True)
class Squad:
    squad_id: str
    club_id: str
    club_name: str
    age_group: str
    division: str
    suffix: str = ""

    @property
    def display_name(self) -> str:
        name = f"{self.club_name} U{self.age_group[1:]} {self.division}"
        return f"{name} {SUFFIX_NUMERALS[self.suffix]}" if self.suffix else name


def season_suffix(season: int) -> str:
    return f"{season % 100:02d}-{(season + 1) % 100:02d}"


def feed_url(stem: str, season: int) -> str:
    return f"{BASE_URL}/{stem}-{season_suffix(season)}.json"


def _check_synced(synced_at: object, stem: str, today: date) -> None:
    try:
        synced = datetime.fromisoformat(str(synced_at).replace("Z", "+00:00")).date()
    except ValueError as exc:
        raise ScrapeError(f"{stem}: unreadable synced_at ({exc})") from exc
    if (today - synced).days > MAX_SYNC_AGE_DAYS:
        raise ScrapeError(f"{stem}: last synced {synced}, over {MAX_SYNC_AGE_DAYS} days ago")


def parse_feed(content: bytes, stem: str, season: int, floors: dict[str, int], today: date) -> list[dict]:
    """The events of one feed, each given the club and competition records it names by id.

    The host answers an unknown file with the site's HTML at status 200. A floor counts only events whose clubs and
    competition were all found, so a file that lost a competition or whose ids stopped matching is refused.
    """
    try:
        data = json.loads(content)
    except ValueError as exc:
        raise ScrapeError(f"{stem}: response is not JSON ({exc})") from exc
    body = data.get("competition_season") if isinstance(data, dict) else None
    if not isinstance(body, dict) or not isinstance(body.get("events"), list):
        raise ScrapeError(f"{stem}: no events array")
    key = f"{stem}-{season_suffix(season)}"
    if body.get("key") != key:
        raise ScrapeError(f"{stem}: feed is season {body.get('key')!r}, not {key}")
    _check_synced(data.get("synced_at"), stem, today)
    clubs = {club.get("id"): club for club in body.get("organisations") or []}
    competitions = {competition.get("id"): competition for competition in body.get("competitions") or []}
    events = [
        {
            **event,
            "home_organisation": clubs.get(event.get("home_organisation_id")),
            "away_organisation": clubs.get(event.get("away_organisation_id")),
            "competition": competitions.get(event.get("competition_id")),
        }
        for event in body["events"]
    ]
    for name, floor in floors.items():
        found = sum(
            bool(event["home_organisation"] and event["away_organisation"])
            and (event["competition"] or {}).get("name") == name
            for event in events
        )
        if found < floor:
            raise ScrapeError(f"{stem}: {found} readable {name} events is below the floor of {floor}")
    return events


def local_date(event: dict) -> str:
    zone = event.get("local_timezone")
    try:
        stamp = datetime.fromisoformat(str(event["start_time"]).replace("Z", "+00:00"))
        return stamp.astimezone(ZoneInfo(zone)).date().isoformat()
    except (KeyError, ValueError, TypeError) as exc:
        raise ScrapeError(f"event {event.get('id')}: unreadable start_time/local_timezone ({exc})") from exc


def _side(event: dict, side: str, division: str) -> tuple[Squad | None, str]:
    """The squad on one side, or None with the reason it cannot be read."""
    org = event.get(f"{side}_organisation") or {}
    label = str(event.get(f"{side}_squad_name") or "")
    match = SQUAD_RE.fullmatch(label)
    if match is None:
        return None, f"squad label {label!r} is not a board age"
    if bool(match.group("ad")) != (division == "AD"):
        return None, f"squad label {label!r} disagrees with the {division} feed"
    squad_id, club_id = event.get(f"{side}_squad_id"), org.get("id")
    if squad_id is None or club_id is None or not org.get("name"):
        return None, "squad id missing or club not found"
    age_group, suffix = f"u{match.group('age')}", match.group("suffix") or ""
    return Squad(str(squad_id), str(club_id), str(org["name"]).strip(), age_group, division, suffix), ""


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
    for stem, division, floors in FEEDS:
        response = session.get(feed_url(stem, season), headers=HEADERS, timeout=60)
        response.raise_for_status()
        feeds.append((division, parse_feed(response.content, stem, season, floors, today)))
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
                "suffix": s.suffix,
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
