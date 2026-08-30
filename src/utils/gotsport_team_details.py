"""One reader for GotSport's ``team_details`` endpoint.

Seven scripts grew their own copy of this, and every one read `full_name`, `state`,
`age` and `gender` -- keys the endpoint has never returned. Each empty result then
fell through to a different fallback, so the same bug produced a different wrong
answer per script and took four separate incidents to find. New callers import this;
the existing copies are tracked for migration in the improvements backlog.

Dependency-free on purpose. The hygiene and backfill workflows install only supabase,
python-dotenv and requests, so this cannot reach for `config.settings` or
`src.scrapers.gotsport` (which pulls in bs4). `src/scrapers/gotsport.py` has the
hardened probe with retry and a WAF breaker; this is the minimal reader for jobs that
cannot import it.
"""

from __future__ import annotations

from typing import Dict, Optional

import requests

from src.utils.age_group import normalize_age_group
from src.utils.team_association_map import to_state_code

BASE_URL = "https://system.gotsport.com/api/v1/team_ranking_data/team_details"


class TeamDetailsResolver:
    """Resolve a GotSport provider team id to the fields PitchRank stores.

    ``resolve`` returns ``{}`` when the team cannot be read, which is falsy so a
    caller skips enrichment rather than persisting empty strings as answers.
    """

    def __init__(self, timeout: int = 15):
        self.timeout = timeout
        self.session = requests.Session()
        self.cache: Dict[str, Dict[str, Optional[str]]] = {}

    def resolve(self, provider_team_id: str) -> Dict[str, Optional[str]]:
        key = str(provider_team_id).strip()
        if not key:
            return {}
        if key in self.cache:
            return self.cache[key]

        try:
            response = self.session.get(BASE_URL, params={"team_id": key}, timeout=self.timeout)
            if response.status_code == 404:
                # "Can not find team" is a permanent answer, so cache it.
                self.cache[key] = {}
                return {}
            response.raise_for_status()
            payload = response.json() if response.content else {}
            if not isinstance(payload, dict):
                payload = {}
        except Exception:
            # A WAF block, timeout or 429 says nothing about this team, so it is
            # not cached -- a later call retries.
            return {}

        # team_details has no full_name, state, age or gender key; the real fields
        # are team_association, display_age_group and display_gender.
        resolved = {
            "name": str(payload.get("name") or "").strip(),
            "club_name": str(payload.get("club_name") or "").strip(),
            "city_state_country": str(payload.get("city_state_country") or "").strip(),
            "state_code": to_state_code(payload.get("team_association")),
            "age_group": normalize_age_group(payload.get("display_age_group")),
            "gender": _gender(payload.get("display_gender")),
            "raw_age_group": str(payload.get("display_age_group") or "").strip(),
        }
        self.cache[key] = resolved
        return resolved


def _gender(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    s = str(value).strip().lower()
    if s in {"male", "m", "boys", "boy", "b"}:
        return "Male"
    if s in {"female", "f", "girls", "girl", "g"}:
        return "Female"
    return None
