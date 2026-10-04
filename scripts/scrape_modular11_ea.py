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

import json
from dataclasses import dataclass

from bs4 import BeautifulSoup

EA_PAGE_URL = "https://www.modular11.com/league-schedule/elite-academy-league"
MATCHES_URL = "https://www.modular11.com/public_schedule/league/get_matches"
TOURNAMENT_ID = "27"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; PitchRank/1.0)"}
MIN_ROSTER_TEAMS = 1000
AGE_CODES = {"20": "u11", "17": "u12", "21": "u13", "22": "u14", "33": "u15", "14": "u16", "15": "u17", "26": "u19"}
NAME_TIERS = ("EA", "EA2")


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
