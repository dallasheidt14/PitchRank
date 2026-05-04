"""SQUADI competition scraper.

Public JSON API at https://api.us.squadi.com requires an anonymous auth token
harvested from the SPA bundle at https://registration.us.squadi.com. v1 scope:
NJYS State Cup competitions; the same code handles any US state on Squadi by
swapping the organisation UUID.

Outputs:
- data/raw/squadi/<scrape_run_id>/games.csv  (28-col canonical)
- data/raw/squadi/<scrape_run_id>/teams.csv  (matcher seed)
- data/raw/squadi/<scrape_run_id>/manifest.json
- data/raw/squadi/<scrape_run_id>/raw/<comp_uuid>/  (optional, --keep-raw)

Dry-run mode (--dry-run, default) validates token harvest + extraction without
writing any output to disk; use --no-dry-run to write CSVs.
"""

import argparse
import csv
import json
import logging
import os
import re
import sys
import time
import urllib.parse
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

import requests

sys.path.append(str(Path(__file__).parent.parent))

logger = logging.getLogger(__name__)

# -----------------------------
# CONSTANTS
# -----------------------------

SQUADI_SPA_BASE = "https://registration.us.squadi.com"
SQUADI_API_BASE = "https://api.us.squadi.com"
OUTPUT_DIR = "data/raw/squadi"
TOKEN_CACHE_PATH = Path.home() / ".cache" / "squadi" / "token.json"
TOKEN_TTL_SECONDS = 24 * 60 * 60  # 24h

# organisation_unique_key → metadata. Add entries as states are onboarded.
ORG_REGISTRY: Dict[str, Dict[str, str]] = {
    "7cfab077-e619-47e4-ab36-0febc29501a2": {
        "state": "New Jersey",
        "state_code": "NJ",
        "timezone": "America/New_York",
    },
}

# Squadi yearRefId → calendar year (from /common/common/reference/year, 2026-05-04)
YEAR_REF_TO_CALENDAR: Dict[int, int] = {
    1: 2020, 2: 2019, 3: 2021, 4: 2022, 5: 2023,
    6: 2024, 7: 2025, 8: 2026,
}

# Default name-blocklist for discovery (overridable via SQUADI_COMP_BLOCKLIST env).
DEFAULT_COMP_NAME_BLOCKLIST: Tuple[str, ...] = ("Demo Comp",)

REQUIRED_COLUMNS = [
    "provider",
    "scrape_run_id",
    "event_id",
    "event_name",
    "schedule_id",
    "age_year",
    "age_group",
    "gender",
    "team_id",
    "team_id_source",
    "team_name",
    "club_name",
    "opponent_id",
    "opponent_id_source",
    "opponent_name",
    "opponent_club_name",
    "state",
    "state_code",
    "game_date",
    "game_time",
    "home_away",
    "goals_for",
    "goals_against",
    "result",
    "venue",
    "source_url",
    "scraped_at",
    "division_name",
]

TEAMS_COLUMNS = [
    "provider",
    "provider_team_id",
    "provider_team_id_source",
    "team_name",
    "club_name",
    "age_group",
    "gender",
    "state",
    "state_code",
    "division_name",
    "tier",
    "external_org_id",
    "meta",
]

# -----------------------------
# PURE HELPERS
# -----------------------------


def compute_result(goals_for: Optional[int], goals_against: Optional[int]) -> str:
    """Compute result from a team's perspective: W / L / D / U."""
    if goals_for is None or goals_against is None:
        return "U"
    if goals_for > goals_against:
        return "W"
    if goals_for < goals_against:
        return "L"
    return "D"


def parse_int_or_none(v: Any) -> Optional[int]:
    """Parse a game score. Only whole integers in 0..50 are accepted; else None.

    Filters malformed scores at scrape time so they don't surface as bogus W/L/D
    rows. Matches the importer validation window (src/utils/enhanced_validators.py).
    """
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v if 0 <= v <= 50 else None
    s = str(v).strip()
    if not s or s.lower() in ("none", "null"):
        return None
    try:
        f = float(s)
    except (ValueError, TypeError):
        return None
    if not f.is_integer():
        return None
    i = int(f)
    return i if 0 <= i <= 50 else None


def parse_utc_to_local_date(iso_utc: Optional[str], tz_name: str) -> Tuple[str, str]:
    """Convert a UTC ISO timestamp to (YYYY-MM-DD, HH:MM) in the given timezone.

    Returns ('', '') on parse failure or empty input.
    """
    if not iso_utc:
        return ("", "")
    try:
        dt_iso = iso_utc.rstrip("Z")
        dt = datetime.fromisoformat(dt_iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        local = dt.astimezone(ZoneInfo(tz_name))
        return (local.strftime("%Y-%m-%d"), local.strftime("%H:%M"))
    except (ValueError, TypeError):
        return ("", "")


# Match all "<n>U" tokens and pick the largest (older cohort wins for dual-age).
_AGE_TOKEN_RE = re.compile(r"\b(\d{1,2})[Uu]\b")
_GENDER_RE = re.compile(r"(?i)\b(boys|girls)\b")


def parse_division_metadata(
    division_name: str,
    fallback_age_int: Optional[int],
) -> Tuple[str, str, str]:
    """Parse division.divisionName into (age_group, gender, tier).

    Rules (locked in spec §A and reinforced by memory):
    - age_group format: "u<n>" lowercase (gotcha_age_group_format).
    - Dual-age divisions take the OLDER cohort, e.g. "15U/16U" → u16
      (gotcha_slash_age_tokens).
    - u18 always remaps to u19 since PitchRank merges u18 into u19
      (gotcha_no_u18_age_group).
    - gender returns "Boys" / "Girls" — never "Male" / "Female"
      (gotcha_format_gender_returns_boys_girls). Empty string when ambiguous.
    - tier is the residual division name with the age and gender tokens stripped.
    - When the regex finds no age token, fall back to fallback_age_int + 1
      (Squadi stores division.age as "min age", so age=10 means 11U).
    - PitchRank tracks u10–u17 and u19; ages outside this range return "".
    """
    name = (division_name or "").strip()
    if not name:
        return ("", "", name)

    # Age — pick the largest U-token (older cohort)
    matches = _AGE_TOKEN_RE.findall(name)
    age_group = ""
    if matches:
        nums = sorted({int(m) for m in matches})
        n = nums[-1]
        if n == 18:
            age_group = "u19"
        elif n == 19 or 10 <= n <= 17:
            age_group = f"u{n}"
    elif fallback_age_int is not None:
        n = fallback_age_int + 1  # Squadi "min age" convention
        if n == 18:
            age_group = "u19"
        elif 10 <= n <= 17 or n == 19:
            age_group = f"u{n}"

    # Gender — word-boundary match avoids false positives like "Girlscout"
    m = _GENDER_RE.search(name)
    gender = m.group(1).capitalize() if m else ""

    # Tier: residual after stripping all age tokens + gender tokens
    tier = _AGE_TOKEN_RE.sub("", name)
    tier = _GENDER_RE.sub("", tier)
    tier = re.sub(r"\s*/\s*", " ", tier)  # collapse "/ " from dual-age splits
    tier = re.sub(r"\s+", " ", tier).strip()

    return (age_group, gender, tier)


_LOGO_ORG_RE = re.compile(r"org_(\d+)")


def parse_club_name(team_name: Optional[str]) -> str:
    """Split team_name on first ' - ' separator; left side = club name.

    Squadi convention is "<Club> - <Team>". Returns full team_name when no
    separator present. Returns "" for None/empty input.
    """
    if not team_name:
        return ""
    s = team_name.strip()
    if " - " in s:
        return s.split(" - ", 1)[0].strip()
    return s


def extract_external_org_id(logo_url: Optional[str]) -> Optional[str]:
    """Pull the Squadi club-org id from a team's logoUrl.

    Squadi stores logos at .../organisation/logo_org_<orgId>_<ts>.blob — the
    org id is a useful matcher tie-breaker when two clubs share a short name.
    Returns None when the URL is missing/blank or has no org_<n> token.
    The "comp_<n>" prefix is for competition logos, not orgs, so it's filtered.
    """
    if not logo_url:
        return None
    m = _LOGO_ORG_RE.search(logo_url)
    return m.group(1) if m else None


def parse_squadi_url(url: Optional[str]) -> Optional[Dict[str, Any]]:
    """Parse a SQUADI livescoreSeasonFixture URL into discovery params.

    Returns {"org_uuid", "competition_uuid", "year_ref_id"} or None when the
    URL is missing the organisationKey query param (the only required field).
    """
    if not url:
        return None
    try:
        parsed = urllib.parse.urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            return None
        qs = urllib.parse.parse_qs(parsed.query)
    except (ValueError, AttributeError):
        return None

    org_uuid = (qs.get("organisationKey") or [None])[0]
    if not org_uuid:
        return None

    comp_uuid = (qs.get("competitionUniqueKey") or [None])[0]
    year_id_raw = (qs.get("yearId") or [None])[0]
    year_ref_id = None
    if year_id_raw is not None:
        try:
            year_ref_id = int(year_id_raw)
        except (ValueError, TypeError):
            year_ref_id = None

    return {
        "org_uuid": org_uuid,
        "competition_uuid": comp_uuid,
        "year_ref_id": year_ref_id,
    }


# Bundle URL: /static/js/main.<hash>.js
_BUNDLE_URL_RE = re.compile(r'(/static/js/main\.[a-f0-9]+\.js)')

# Token: 256+ char lowercase hex string (Squadi's auth token).
# Used as a candidate filter; we then verify proximity to "authorization".
_TOKEN_HEX_RE = re.compile(r'([a-f0-9]{256,1024})')


def extract_bundle_url_from_html(html: Optional[str]) -> Optional[str]:
    """Find the SPA's main JS bundle URL in the served HTML."""
    if not html:
        return None
    m = _BUNDLE_URL_RE.search(html)
    return m.group(1) if m else None


def extract_token_from_bundle(bundle_text: Optional[str]) -> Optional[str]:
    """Pull the anonymous public-read token from the SPA bundle.

    Strategy: find all 256+ char hex strings, return the one closest to (within
    300 chars of) an auth anchor keyword. Anchors checked in priority order:
      1. "AUTH_TOKEN"  — matches REACT_APP_DEFAULT_AUTH_TOKEN env constant
      2. "authorization" — matches Authorization header setter in fetch wrapper

    This two-anchor approach is robust to bundle structure: newer bundles embed
    the token as REACT_APP_DEFAULT_AUTH_TOKEN; if that ever moves the
    "authorization" anchor catches the fetch-wrapper pattern instead.
    """
    if not bundle_text:
        return None
    candidates = list(_TOKEN_HEX_RE.finditer(bundle_text))
    if not candidates:
        return None
    # Build combined anchor positions, preferring AUTH_TOKEN (more specific)
    anchor_positions = [m.start() for m in re.finditer(r'AUTH_TOKEN|authorization', bundle_text, re.IGNORECASE)]
    if not anchor_positions:
        # No anchor found — return the longest hex candidate as a best-effort
        # fallback. Caller will verify by attempting an API call.
        return max(candidates, key=lambda m: len(m.group(1))).group(1)
    # Find the candidate token closest to any anchor mention.
    # Distance is measured from whichever edge of the token is nearer to the
    # keyword (start or end), so long tokens adjacent to the anchor are
    # still captured correctly even when the keyword follows the token value.
    best = None
    best_dist = float("inf")
    for cand in candidates:
        cand_start = cand.start()
        cand_end = cand.end()
        dist = min(
            min(abs(cand_start - a), abs(cand_end - a))
            for a in anchor_positions
        )
        if dist < best_dist and dist <= 300:
            best_dist = dist
            best = cand.group(1)
    return best


# -----------------------------
# TOKEN HARVESTER
# -----------------------------


class SquadiTokenError(RuntimeError):
    """Raised when token harvest fails irrecoverably."""


class SquadiTokenHarvester:
    """Fetches the anonymous auth token from the SPA bundle, with disk cache.

    Cache: ~/.cache/squadi/token.json with TTL 24h. On 401 from any API call,
    callers should invoke .invalidate() and retry once.
    """

    DEFAULT_HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }

    def __init__(self, spa_base: str = SQUADI_SPA_BASE, cache_path: Path = TOKEN_CACHE_PATH):
        self.spa_base = spa_base.rstrip("/")
        self.cache_path = cache_path
        self._token: Optional[str] = None
        self._build_hash: Optional[str] = None

    def _load_cache(self) -> Optional[Dict[str, Any]]:
        if not self.cache_path.exists():
            return None
        try:
            data = json.loads(self.cache_path.read_text())
        except (json.JSONDecodeError, OSError):
            return None
        if not isinstance(data, dict):
            return None
        ts = data.get("fetched_at", 0)
        if (time.time() - ts) > TOKEN_TTL_SECONDS:
            return None
        return data

    def _save_cache(self, token: str, build_hash: str) -> None:
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_text(json.dumps({
                "token": token,
                "build_hash": build_hash,
                "fetched_at": time.time(),
            }))
        except OSError as e:
            logger.warning(f"Failed to write token cache: {e}")

    def get_token(self) -> str:
        """Return a valid token, using cache when fresh."""
        if self._token:
            return self._token
        cached = self._load_cache()
        if cached:
            self._token = cached["token"]
            self._build_hash = cached.get("build_hash")
            logger.debug(f"Loaded cached token (build={self._build_hash})")
            return self._token
        return self._refresh_token()

    def _refresh_token(self) -> str:
        """Fetch SPA, find bundle, regex out the token. Persist to cache."""
        logger.info(f"Harvesting token from {self.spa_base}")
        try:
            r = requests.get(self.spa_base + "/", headers=self.DEFAULT_HEADERS, timeout=15)
            r.raise_for_status()
        except requests.RequestException as e:
            raise SquadiTokenError(f"Failed to fetch SPA index: {e}") from e

        bundle_path = extract_bundle_url_from_html(r.text)
        if not bundle_path:
            raise SquadiTokenError(
                "Could not find main.<hash>.js in SPA HTML — Squadi may have "
                "changed bundle structure. Inspect HTML manually."
            )
        bundle_url = self.spa_base + bundle_path
        try:
            br = requests.get(bundle_url, headers=self.DEFAULT_HEADERS, timeout=30)
            br.raise_for_status()
        except requests.RequestException as e:
            raise SquadiTokenError(f"Failed to fetch bundle {bundle_url}: {e}") from e

        token = extract_token_from_bundle(br.text)
        if not token:
            raise SquadiTokenError(
                f"Could not extract token from bundle {bundle_url} — Squadi may "
                f"have changed token structure. Bundle size: {len(br.text)} bytes."
            )

        # build hash = the <hash> portion of main.<hash>.js
        build_hash = bundle_path.split(".")[1] if "." in bundle_path else "unknown"
        self._token = token
        self._build_hash = build_hash
        self._save_cache(token, build_hash)
        logger.info(f"Harvested token (build={build_hash}, len={len(token)})")
        return token

    def invalidate(self) -> None:
        """Drop in-memory + on-disk cache. Next get_token() refetches."""
        self._token = None
        self._build_hash = None
        try:
            if self.cache_path.exists():
                self.cache_path.unlink()
        except OSError:
            pass

    @property
    def build_hash(self) -> Optional[str]:
        return self._build_hash


# -----------------------------
# API CLIENT
# -----------------------------


class SquadiClient:
    """Thin wrapper around requests.Session with token + retry + delay."""

    def __init__(
        self,
        token_harvester: SquadiTokenHarvester,
        api_base: str = SQUADI_API_BASE,
        delay_sec: float = 0.3,
        max_retries: int = 3,
        timeout: int = 30,
    ):
        self.harvester = token_harvester
        self.api_base = api_base.rstrip("/")
        self.delay_sec = delay_sec
        self.max_retries = max_retries
        self.timeout = timeout
        self.session = requests.Session()
        self.token_refresh_count = 0

    def _headers(self) -> Dict[str, str]:
        return {
            "authorization": self.harvester.get_token(),
            "accept": "application/json",
            "user-agent": SquadiTokenHarvester.DEFAULT_HEADERS["User-Agent"],
        }

    def _get_json(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        """GET with retry + 401-triggered token refresh.

        Raises RuntimeError on persistent failure.
        """
        url = f"{self.api_base}/{path.lstrip('/')}"
        last_error: Optional[str] = None
        token_already_refreshed = False

        for attempt in range(self.max_retries):
            try:
                r = self.session.get(
                    url, params=params, headers=self._headers(), timeout=self.timeout
                )
                if r.status_code == 200:
                    if attempt > 0:
                        time.sleep(self.delay_sec)
                    return r.json()
                if r.status_code == 401 and not token_already_refreshed:
                    logger.warning(f"401 on {path} — refreshing token and retrying once")
                    self.harvester.invalidate()
                    self.token_refresh_count += 1
                    token_already_refreshed = True
                    continue  # retry without consuming an attempt
                last_error = f"HTTP {r.status_code}"
                logger.warning(f"⚠️ {last_error} for {path} (attempt {attempt+1}/{self.max_retries})")
            except requests.RequestException as e:
                last_error = str(e)
                logger.warning(f"⚠️ Request error for {path}: {e}")

            if attempt < self.max_retries - 1:
                time.sleep(0.5 * (2 ** attempt))  # exponential backoff: 0.5, 1, 2

        raise RuntimeError(
            f"SQUADI API call failed after {self.max_retries} attempts: {path} "
            f"({last_error}, build={self.harvester.build_hash})"
        )

    def list_years(self, org_uuid: str) -> List[Dict[str, Any]]:
        time.sleep(self.delay_sec)
        return self._get_json(
            "common/common/reference/year",
            params={"organisationUniqueKey": org_uuid, "scope": 1},
        )

    def list_competitions(self, org_uuid: str, year_ref_id: int) -> List[Dict[str, Any]]:
        time.sleep(self.delay_sec)
        return self._get_json(
            "livescores/competitions/list",
            params={"organisationUniqueKey": org_uuid, "yearRefId": year_ref_id},
        )

    def list_divisions(self, competition_uuid: str) -> List[Dict[str, Any]]:
        time.sleep(self.delay_sec)
        return self._get_json(
            "livescores/division",
            params={"competitionKey": competition_uuid},
        )

    def get_round_matches(self, competition_int_id: int) -> Dict[str, Any]:
        time.sleep(self.delay_sec)
        return self._get_json(
            "livescores/round/matches",
            params={
                "competitionId": competition_int_id,
                "divisionId": "",
                "teamIds": "",
                "ignoreStatuses": "[1]",
            },
        )


# Globals set in main()
SCRAPE_TS = None
SCRAPE_RUN_ID = None
