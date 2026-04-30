"""Shared test helpers auto-discovered by pytest."""

from __future__ import annotations

import pandas as pd


class FakeResponse:
    """Minimal ``requests.Response`` stand-in for tests that exercise the
    gotsport scrape path without network. ``fetch_teams_by_cohort`` reads
    ``response.text`` directly to build the landing soup, and the
    tier-orchestrator subpage closure reads ``.url`` / ``.headers`` /
    ``.history`` for ZenRows-aware captcha detection — bare ``MagicMock()``
    does not satisfy that contract."""

    def __init__(self, text: str = "", url: str = ""):
        self.text = text
        self.url = url
        self.headers: dict[str, str] = {}
        self.history: list = []
        self.status_code = 200

    def raise_for_status(self) -> None:
        return None


def trim_landing_to_gids(html: str, keep_gids: list[int]) -> str:
    """Drop landing-page rows whose ``?group=`` anchor isn't in the keep-set.

    Used to keep gotsport tier-parser tests hermetic when only a subset of
    per-tier subpages have been captured as fixtures. Collects rows-to-drop
    FIRST then decomposes — calling ``row.decompose()`` mid-iteration leaves
    stale Tag refs whose ``a.get(...)`` raises.

    ``BeautifulSoup`` is imported lazily so unrelated test modules don't
    pay the bs4 import cost when this helper is unused.
    """
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    rows_to_drop = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "schedules?group=" not in href:
            continue
        if any(f"group={g}" in href for g in keep_gids):
            continue
        parent = a.find_parent()
        row = parent.find_parent() if parent else None
        if row is not None:
            rows_to_drop.append(row)
    for row in rows_to_drop:
        row.decompose()
    return str(soup)


def make_game_pair(
    gid,
    date,
    home,
    away,
    hs,
    as_,
    age="14",
    gender="male",
    opp_age=None,
    opp_gender=None,
):
    """Create home + away perspective rows for a single game.

    Returns a list of two dicts (one per perspective) suitable for building
    a games DataFrame via ``pd.DataFrame(rows)``.
    """
    opp_age = opp_age or age
    opp_gender = opp_gender or gender
    return [
        {
            "game_id": gid,
            "date": pd.Timestamp(date),
            "team_id": home,
            "opp_id": away,
            "age": age,
            "gender": gender,
            "opp_age": opp_age,
            "opp_gender": opp_gender,
            "gf": hs,
            "ga": as_,
        },
        {
            "game_id": gid,
            "date": pd.Timestamp(date),
            "team_id": away,
            "opp_id": home,
            "age": opp_age,
            "gender": opp_gender,
            "opp_age": age,
            "opp_gender": gender,
            "gf": as_,
            "ga": hs,
        },
    ]
