#!/usr/bin/env python3
"""Scrape one age group of the Modular11 Elite Academy League (EA): roster and games.

EA is Modular11 tournament 27, separate from the MLS NEXT spider. The public league page embeds
the whole roster as a ``dependencies:`` array; each team's season comes from ``get_matches``
filtered by ``team=<id>``. Writes ``<out-dir>/<age>/teams.csv`` and ``games.csv`` and never
touches the database.

Usage:
    python scripts/scrape_modular11_ea.py --age u11
"""

from __future__ import annotations

import html as htmllib
import json
import re
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date

from bs4 import BeautifulSoup

EA_PAGE_URL = "https://www.modular11.com/league-schedule/elite-academy-league"
MATCHES_URL = "https://www.modular11.com/public_schedule/league/get_matches"
TOURNAMENT_ID = "27"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; PitchRank/1.0)"}
MIN_ROSTER_TEAMS = 1000
AGE_CODES = {"20": "u11", "17": "u12", "21": "u13", "22": "u14", "33": "u15", "14": "u16", "15": "u17", "26": "u19"}
NAME_TIERS = ("EA", "EA2")
PAGE_RE = re.compile(r"(\d+)\s*page\s*out\s*of\s*(\d+)")
SCORE_RE = re.compile(r"^(\d+)\s*:\s*(\d+)$")
DATE_RE = re.compile(r"(\d{2})/(\d{2})/(\d{2})")
CREST_RE = re.compile(r"/academy/(\d+)/")
NO_DATA = "No data available."


class ScrapeError(RuntimeError):
    """The page or an API response no longer has the shape this scraper reads."""


@dataclass(frozen=True)
class RosterTeam:
    provider_team_id: str
    academy_id: str
    club_name: str
    age_group: str
    tiers: tuple[str, ...]
    regions: tuple[str, ...]

    @property
    def name_tier(self) -> str:
        return next(t for t in NAME_TIERS if t in self.tiers)


def _select_options(soup: BeautifulSoup, marker: str) -> dict[str, str]:
    select = soup.find("select", attrs={marker: True})
    if select is None:
        raise ScrapeError(f"page has no <select {marker}>")
    return {
        option["value"]: option.get_text(strip=True)
        for option in select.find_all("option")
        if option.get("value") not in (None, "0")
    }


def _dependencies(html: str) -> list[dict]:
    start = html.find("dependencies:")
    if start < 0:
        raise ScrapeError("page has no dependencies: array")
    try:
        rows, _ = json.JSONDecoder().raw_decode(html, html.index("[", start))
    except ValueError as exc:
        raise ScrapeError(f"dependencies: array does not parse: {exc}") from exc
    return rows


def parse_roster(html: str, min_teams: int = MIN_ROSTER_TEAMS) -> list[RosterTeam]:
    soup = BeautifulSoup(html, "html.parser")
    tables = {
        "UID_bracket": _select_options(soup, "js-brackets"),
        "UID_academy": _select_options(soup, "js-academy"),
        "UID_group": _select_options(soup, "js-groups"),
    }
    age_labels = _select_options(soup, "js-age")
    merged: dict[str, dict] = {}
    for row in _dependencies(html):
        team_id = str(row.get("UID_team"))
        for key, table in tables.items():
            if str(row.get(key)) not in table:
                raise ScrapeError(f"unknown {key} {row.get(key)!r} for team {team_id}")
        age_code = str(row.get("UID_age"))
        age = AGE_CODES.get(age_code)
        if age is None or age_labels.get(age_code) != age.upper():
            label = age_labels.get(age_code)
            raise ScrapeError(f"unknown UID_age {age_code!r} (page label {label!r}) for team {team_id}")
        academy = str(row["UID_academy"])
        entry = merged.setdefault(team_id, {"academy": academy, "age": age, "tiers": set(), "regions": set()})
        if (entry["academy"], entry["age"]) != (academy, age):
            raise ScrapeError(f"team {team_id} listed under two clubs or ages")
        entry["tiers"].add(tables["UID_bracket"][str(row["UID_bracket"])])
        entry["regions"].add(tables["UID_group"][str(row["UID_group"])])
    if len(merged) < min_teams:
        raise ScrapeError(f"{len(merged)} teams is below the floor of {min_teams}")
    teams = []
    for team_id, entry in merged.items():
        if not entry["tiers"] & set(NAME_TIERS):
            raise ScrapeError(f"team {team_id} plays in neither EA nor EA2: {sorted(entry['tiers'])}")
        teams.append(
            RosterTeam(
                provider_team_id=team_id,
                academy_id=entry["academy"],
                club_name=tables["UID_academy"][entry["academy"]],
                age_group=entry["age"],
                tiers=tuple(sorted(entry["tiers"])),
                regions=tuple(sorted(entry["regions"])),
            )
        )
    return sorted(teams, key=lambda t: (t.age_group, t.club_name, t.provider_team_id))


@dataclass(frozen=True)
class ScheduleRow:
    match_no: str
    gender: str
    game_date: str
    bracket: str
    region: str
    age_label: str
    home_name: str
    home_academy: str | None
    away_name: str
    away_academy: str | None
    home_score: int | None
    away_score: int | None


def _crest_academy(node) -> str | None:
    match = CREST_RE.search(node.get("style", ""))
    return match.group(1) if match else None


def _parse_row(row) -> ScheduleRow:
    cols = row.find_all("div", recursive=False)
    head = cols[0].get_text(" ", strip=True).split()
    date_match = DATE_RE.search(cols[1].get_text(" ", strip=True))
    names = [p.get("data-title", "").strip() for p in row.select(".container-first-team p, .container-second-team p")]
    crests = [_crest_academy(node) for node in row.select(".club-photo")]
    if len(head) < 2 or date_match is None or len(names) != 2 or len(crests) != 2:
        raise ScrapeError(f"unreadable match row: {row.get_text(' ', strip=True)[:120]}")
    mm, dd, yy = date_match.groups()
    score_node = row.select_one(".score-match-table")
    score_text = htmllib.unescape(score_node.get_text()).replace("\xa0", " ").strip() if score_node else ""
    score = SCORE_RE.match(score_text)
    return ScheduleRow(
        match_no=head[0],
        gender=head[1],
        game_date=date(2000 + int(yy), int(mm), int(dd)).isoformat(),
        bracket=row.get("js-match-bracket", ""),
        region=row.get("js-match-group", ""),
        age_label=cols[2].get_text(strip=True),
        home_name=names[0],
        home_academy=crests[0],
        away_name=names[1],
        away_academy=crests[1],
        home_score=int(score.group(1)) if score else None,
        away_score=int(score.group(2)) if score else None,
    )


def parse_schedule_page(html: str, expected_page: int) -> tuple[list[ScheduleRow], int]:
    marker = PAGE_RE.search(html)
    if marker is None:
        if NO_DATA in html:
            return [], 0
        raise ScrapeError("schedule response has no 'page out of' marker and no 'No data available.'")
    current, total = int(marker.group(1)), int(marker.group(2))
    if current != expected_page:
        raise ScrapeError(f"asked for page {expected_page}, got page {current} of {total}")
    soup = BeautifulSoup(html, "html.parser")
    return [_parse_row(r) for r in soup.select("div.table-content-row.hidden-xs")], total


def _match_params(team_id: str, page: int, start: str, end: str) -> dict:
    return {
        "open_page": page,
        "academy": 0,
        "tournament": TOURNAMENT_ID,
        "gender": 0,
        "age": 0,
        "brackets": "",
        "groups": "",
        "group": "",
        "match_number": 0,
        "status": "all",
        "match_type": 2,
        "schedule": 0,
        "team": team_id,
        "teamPlayer": 0,
        "location": 0,
        "as_referee": 0,
        "start_date": start,
        "end_date": end,
    }


def fetch_team_schedule(
    session, team_id: str, start: str, end: str, delay: float = 1.0, sleep=time.sleep
) -> list[ScheduleRow]:
    """Every row of one team's season. Pages are 1-indexed: open_page=0 aliases page 1."""
    rows: list[ScheduleRow] = []
    page, total = 1, 1
    while page <= total:
        response = session.get(
            MATCHES_URL, params=_match_params(team_id, page, start, end), headers=HEADERS, timeout=30
        )
        response.raise_for_status()
        page_rows, total = parse_schedule_page(response.content.decode("utf-8"), expected_page=page)
        rows.extend(page_rows)
        page += 1
        sleep(delay)
    return rows


@dataclass(frozen=True)
class GameRow:
    match_no: str
    game_date: str
    age_group: str
    bracket: str
    region: str
    home_team_id: str
    away_team_id: str
    home_name: str
    away_name: str
    home_academy: str
    away_academy: str
    home_score: int | None
    away_score: int | None
    status: str
    pairing: str


def _sides(row: ScheduleRow):
    return (("home", row.home_name, row.home_academy), ("away", row.away_name, row.away_academy))


def team_display_name(team: RosterTeam, rows: list[ScheduleRow]) -> str:
    """The name this team plays under: its side in games against other clubs."""
    names = Counter()
    for row in rows:
        own = [name for _, name, academy in _sides(row) if academy == team.academy_id]
        if len(own) == 1:
            names[own[0]] += 1
    if names:
        return names.most_common(1)[0][0]
    return f"{team.club_name} {team.age_group.upper()} {team.name_tier}"


def _side_of(team: RosterTeam, display: str, row: ScheduleRow) -> str | None:
    by_academy = [side for side, _, academy in _sides(row) if academy == team.academy_id]
    if len(by_academy) == 1:
        return by_academy[0]
    pool = by_academy or [side for side, _, _ in _sides(row)]
    by_name = [side for side, name, _ in _sides(row) if side in pool and name == display]
    return by_name[0] if len(by_name) == 1 else None


def pair_games(teams: list[RosterTeam], schedules: dict[str, list[ScheduleRow]], age_group: str) -> list[GameRow]:
    by_id = {t.provider_team_id: t for t in teams}
    display = {tid: team_display_name(by_id[tid], rows) for tid, rows in schedules.items()}
    first_seen: dict[str, ScheduleRow] = {}
    claims: dict[str, dict[str, set[str]]] = defaultdict(lambda: {"home": set(), "away": set()})
    for tid, rows in schedules.items():
        for row in rows:
            first_seen.setdefault(row.match_no, row)
            side = _side_of(by_id[tid], display[tid], row)
            if side:
                claims[row.match_no][side].add(tid)
    games = []
    for match_no, row in sorted(first_seen.items()):
        home, away = claims[match_no]["home"], claims[match_no]["away"]
        home_id = next(iter(home)) if len(home) == 1 else ""
        away_id = next(iter(away)) if len(away) == 1 else ""
        if len(home) > 1 or len(away) > 1 or not (home_id or away_id):
            pairing = "unresolved"
        else:
            pairing = "both" if home_id and away_id else "one_sided"
        games.append(
            GameRow(
                match_no=match_no,
                game_date=row.game_date,
                age_group=age_group,
                bracket=row.bracket,
                region=row.region,
                home_team_id=home_id,
                away_team_id=away_id,
                home_name=row.home_name,
                away_name=row.away_name,
                home_academy=row.home_academy or "",
                away_academy=row.away_academy or "",
                home_score=row.home_score,
                away_score=row.away_score,
                status="played" if row.home_score is not None else "scheduled",
                pairing=pairing,
            )
        )
    return games
