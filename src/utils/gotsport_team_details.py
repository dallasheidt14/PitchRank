"""One reader for GotSport's ``team_details`` endpoint.

Seven scripts grew their own copy of this, and every one read `full_name`, `state`,
`age` and `gender` -- keys the endpoint has never returned. Each empty result then
fell through to a different fallback, so the same bug produced a different wrong
answer per script and took four separate incidents to find. New callers import this;
the existing copies are tracked for migration in the improvements backlog.

Dependency-free on purpose. The hygiene and backfill workflows install only supabase,
python-dotenv and requests, so this cannot reach for `config.settings` or
`src.scrapers.gotsport` (which pulls in bs4). `src/scrapers/gotsport.py` has the
hardened probe with retry and a WAF breaker; this is the minimal reader and pacer for
jobs that cannot import it.
"""

from __future__ import annotations

import os
import time
from typing import Callable, Dict, Optional

import requests

from src.utils.age_group import normalize_age_group
from src.utils.team_association_map import to_state_code

BASE_URL = "https://system.gotsport.com/api/v1/team_ranking_data/team_details"

REQUEST_SPACING_SEC = 3.0

# GotSport fronted system.gotsport.com/api/v1/* with a per-IP burst rate limiter
# ~2026-05-01; a tripped IP stays locked out for several minutes, and 300 s matches
# the lockout observed on 2026-05-18. Override via GOTSPORT_WAF_COOLDOWN_SEC.
WAF_COOLDOWN_SEC = 300


def is_cloudfront_waf_block(response: requests.Response) -> bool:
    """403 with ``Server: CloudFront`` is GotSport's per-IP burst limiter, not an answer about a team."""
    # Keyed on 403 only; a WAF 503 reads as an ordinary server error.
    return response.status_code == 403 and response.headers.get("Server") == "CloudFront"


class LookupsStopped(RuntimeError):
    """GotSport was still blocking after a cooldown, so the run makes no more lookups."""


class TeamDetailsPacer:
    """Spaces one process's team_details requests and waits out a CloudFront block once.

    A block still in place after the cooldown stops every later request in the run, so
    the walk fails fast instead of prolonging the block.
    """

    def __init__(
        self,
        spacing_sec: float = REQUEST_SPACING_SEC,
        cooldown_sec: Optional[float] = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.spacing_sec = spacing_sec
        if cooldown_sec is None:
            cooldown_sec = int(os.getenv("GOTSPORT_WAF_COOLDOWN_SEC", str(WAF_COOLDOWN_SEC)))
        self.cooldown_sec = cooldown_sec
        self.sleep = sleep
        self.stopped = False

    def get(self, session: requests.Session, url: str, *, params: Dict[str, str], timeout: float) -> requests.Response:
        team_id = params.get("team_id")
        if self.stopped:
            raise LookupsStopped(f"GotSport lookups are stopped for this run; {team_id} was not requested")
        for attempt in range(2):
            self.sleep(self.spacing_sec)
            response = session.get(url, params=params, timeout=timeout)
            if not is_cloudfront_waf_block(response):
                return response
            if attempt == 0:
                wait = f"{self.cooldown_sec:.0f}s"
                print(f"  GotSport blocked the lookup for {team_id}; waiting {wait}, then retrying once", flush=True)
                self.sleep(self.cooldown_sec)
        self.stopped = True
        print("  GotSport is still blocking after the wait; no more lookups this run", flush=True)
        return response


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
