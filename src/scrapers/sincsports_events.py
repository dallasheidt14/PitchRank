"""SincSports tournament/event team discovery scraper.

Parses `teamlist.aspx?tid=X&tab=6&sub=0` — a single HTML page listing every
team participating in a tournament, grouped into per-division tables with
``Team | Club | State`` columns. Complementary to
``src/scrapers/sincsports_clubs.py`` (which uses the clubs directory search);
empirically the teamlist page surfaces teams the clubs search misses.

**Coverage motivation** — spot-check against the 2026 Puri Champions Cup
(``TZ2565``) done 2026-04-24 found 332 teams listed, of which only 4 were
already in our DB after a full-grid u14 Female clubs-discovery run. The
clubs search is missing 99% of teams registered for this one tournament.

**Wire format** — a regular HTML page, not the EO callback envelope the
clubs search uses. The ``provider_team_id`` is embedded in the anchor's
``onclick="eo_Callback('cpTeamSummary', 'ILF17086'); return false;"``
attribute (second callback argument). Age + gender come from the division
heading text immediately preceding each table:

- ``"Under 14 Girls First Division"`` → ``u14``, ``"Female"``
- ``"Under 18 Boys Second Division"`` → ``u19``, ``"Male"``  *(u18 merges
  into u19 per repo convention)*
"""

from __future__ import annotations

import logging
import random
import re
import time
from typing import FrozenSet, List, Optional

import requests
from bs4 import BeautifulSoup

from src.scrapers.sincsports_clubs import SincSportsClubsScraper, TeamRecord

logger = logging.getLogger(__name__)

BASE_URL = "https://soccer.sincsports.com"
TEAMLIST_PATH = "/teamlist.aspx"

# `onclick="eo_Callback('cpTeamSummary', 'ILF17086'); return false;"` → "ILF17086"
_TEAMID_RE = re.compile(
    r"eo_Callback\(\s*['\"]cpTeamSummary['\"]\s*,\s*['\"]([A-Z0-9]+)['\"]",
    re.IGNORECASE,
)

# "Under 14 Girls First Division" → (14, "Girls"). Handles dual-age "Under 9/10"
# by taking the lower age (younger primary cohort, matches SincSports convention).
_DIV_HEADING_RE = re.compile(
    r"\bUnder\s+(\d{1,2})(?:/\d{1,2})?\s+(Boys|Girls)\b",
    re.IGNORECASE,
)

# Canonical PitchRank age groups — `config/settings.py::AGE_GROUPS` keyset.
# Kept inline to avoid dragging the rankings stack into the scraper import chain
# (see the equivalent inline list in `scripts/discover_sincsports_teams.py`).
CANONICAL_AGE_GROUPS: FrozenSet[str] = frozenset({"u10", "u11", "u12", "u13", "u14", "u15", "u16", "u17", "u19"})


# Re-export shim — the shared helper now lives in ``_age_normalization`` so the
# Gotsport tier parser can consume it without dragging the SincSports import
# chain. SincSports' ``parse_teamlist`` still filters via ``effective_ages``
# (``CANONICAL_AGE_GROUPS`` by default), so the helper's widened ``[6, 19]``
# band is invisible here — ``u6``/``u7`` produced by the helper get filtered
# out at line 157.
from src.scrapers._age_normalization import normalize_age as _normalize_age  # noqa: E402


class SincSportsEventsScraper:
    """Scraper for tournament team lists (``teamlist.aspx``).

    Reuses ``SincSportsClubsScraper``'s HTTP session (UA, retry adapter,
    throttle env vars) so both scrapers share the SINCSPORTS_* knobs and
    behave identically against the server. Exposes a pure-function parser
    (``parse_teamlist``) that unit tests can hit against the committed
    fixture without any network.
    """

    def __init__(
        self,
        delay_min: Optional[float] = None,
        delay_max: Optional[float] = None,
        timeout: Optional[int] = None,
    ):
        self._http = SincSportsClubsScraper(
            delay_min=delay_min,
            delay_max=delay_max,
            timeout=timeout,
        )
        self.session: requests.Session = self._http.session
        self.delay_min: float = self._http.delay_min
        self.delay_max: float = self._http.delay_max
        self.timeout: int = self._http.timeout
        self.errors: List[dict] = []

    def fetch_teamlist(
        self,
        tid: str,
        include_ages: Optional[FrozenSet[str]] = None,
    ) -> List[TeamRecord]:
        """Fetch one tournament's ``teamlist.aspx`` page and return parsed teams.

        ``include_ages`` defaults to ``CANONICAL_AGE_GROUPS`` — teams in
        u8/u9/adult divisions are filtered out because the downstream matcher
        would reject them anyway. Callers who want everything can pass
        ``include_ages=frozenset({"u8","u9",*CANONICAL_AGE_GROUPS})`` etc.
        """
        url = f"{BASE_URL}{TEAMLIST_PATH}?tid={tid}&tab=6&sub=0"
        logger.info(f"Fetching tournament teamlist: {url}")
        resp = self.session.get(url, timeout=self.timeout)
        resp.raise_for_status()
        # Mirror the clubs scraper's between-request throttle.
        time.sleep(random.uniform(self.delay_min, self.delay_max))
        return self.parse_teamlist(resp.text, include_ages=include_ages)

    @staticmethod
    def parse_teamlist(
        html: str,
        include_ages: Optional[FrozenSet[str]] = None,
    ) -> List[TeamRecord]:
        """Parse teamlist.aspx HTML → deduped list of ``TeamRecord``.

        Pure function — no network, safe to call on fixture content. Dedupes
        by ``provider_team_id`` (a team can technically appear in multiple
        divisions of the same tournament; the first occurrence wins, which
        is deterministic given BeautifulSoup's document order).
        """
        effective_ages = include_ages if include_ages is not None else CANONICAL_AGE_GROUPS
        soup = BeautifulSoup(html, "html.parser")
        seen: dict[str, TeamRecord] = {}

        for table in soup.find_all("table"):
            first_row = table.find("tr")
            if not first_row:
                continue
            header_cells = [c.get_text(strip=True) for c in first_row.find_all(["th", "td"])]
            if header_cells != ["Team", "Club", "State"]:
                continue

            heading_el = table.find_previous(["h1", "h2", "h3", "h4"])
            if not heading_el:
                continue
            heading_text = heading_el.get_text(strip=True)
            heading_match = _DIV_HEADING_RE.search(heading_text)
            if not heading_match:
                continue

            age_int = int(heading_match.group(1))
            age_key = _normalize_age(age_int)
            if age_key is None or age_key not in effective_ages:
                continue
            gender = "Male" if heading_match.group(2).lower().startswith("b") else "Female"

            for tr in table.find_all("tr")[1:]:
                cells = tr.find_all(["th", "td"])
                if len(cells) < 3:
                    continue
                anchor = cells[0].find("a")
                if not anchor:
                    continue
                team_name = anchor.get_text(strip=True)
                if not team_name:
                    continue
                onclick = anchor.get("onclick", "") or ""
                id_match = _TEAMID_RE.search(onclick)
                if not id_match:
                    continue
                provider_team_id = id_match.group(1).upper()
                if provider_team_id in seen:
                    continue
                club_name = cells[1].get_text(strip=True) or None
                state_code = cells[2].get_text(strip=True) or None
                seen[provider_team_id] = TeamRecord(
                    provider_team_id=provider_team_id,
                    team_name=team_name,
                    club_name=club_name,
                    age_group=age_key,
                    gender=gender,
                    state_code=state_code,
                )

        return list(seen.values())
