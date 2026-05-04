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


# -----------------------------
# COMPETITION DISCOVERY
# -----------------------------


def filter_competitions(
    competitions: List[Dict[str, Any]],
    name_blocklist: Tuple[str, ...] = DEFAULT_COMP_NAME_BLOCKLIST,
) -> List[Dict[str, Any]]:
    """Filter raw /competitions/list output by status, deletion, and name.

    Keep: statusRefId == 2 (active/published), deleted_at is null, name does
    not contain any blocklist substring (case-insensitive).
    """
    out: List[Dict[str, Any]] = []
    for comp in competitions:
        if comp.get("statusRefId") != 2:
            continue
        if comp.get("deleted_at") is not None:
            continue
        name = str(comp.get("name") or "").lower()
        if any(bl.lower() in name for bl in name_blocklist):
            continue
        out.append(comp)
    return out


def discover_competitions(
    client: SquadiClient,
    org_uuid: str,
    year_ref_id: Optional[int] = None,
    name_blocklist: Tuple[str, ...] = DEFAULT_COMP_NAME_BLOCKLIST,
) -> List[Dict[str, Any]]:
    """List + filter competitions for an org.

    When year_ref_id is None, walks every yearRefId in YEAR_REF_TO_CALENDAR.
    """
    year_ids = [year_ref_id] if year_ref_id is not None else list(YEAR_REF_TO_CALENDAR.keys())
    all_comps: List[Dict[str, Any]] = []
    for yri in year_ids:
        try:
            raw = client.list_competitions(org_uuid, yri)
        except RuntimeError as e:
            logger.warning(f"Skipping yearRefId={yri}: {e}")
            continue
        all_comps.extend(filter_competitions(raw, name_blocklist=name_blocklist))
    return all_comps


# -----------------------------
# MATCH NORMALIZATION
# -----------------------------

# matchSubstatusRefId values that indicate a forfeit/abandonment outcome.
# Discovered empirically; expand as more substatus codes are observed.
FORFEIT_SUBSTATUS_IDS = {11, 12, 13, 14}  # Working hypothesis; verify in production


def _build_venue(venue_court: Optional[Dict[str, Any]]) -> str:
    """Compose 'Venue Name - Field N' from venueCourt."""
    if not venue_court:
        return ""
    venue = venue_court.get("venue") or {}
    venue_name = str(venue.get("name") or "").strip()
    field_name = str(venue_court.get("name") or "").strip()
    if venue_name and field_name:
        return f"{venue_name} - {field_name}"
    return venue_name or field_name


def _build_source_url(org_uuid: str, comp_uuid: str, year_ref_id: Optional[int], division_uuid: str) -> str:
    year_part = f"&yearId={year_ref_id}" if year_ref_id is not None else ""
    div_part = f"&divisionId={division_uuid}" if division_uuid else ""
    return (
        f"{SQUADI_SPA_BASE}/livescoreSeasonFixture"
        f"?organisationKey={org_uuid}"
        f"&competitionUniqueKey={comp_uuid}"
        f"{year_part}{div_part}"
    )


def _compute_age_year(age_group: str, comp_calendar_year: Optional[int]) -> str:
    """Birth year heuristic: comp_year - U_age - 1."""
    if not age_group or not comp_calendar_year:
        return ""
    try:
        n = int(age_group.lstrip("uU"))
        return str(comp_calendar_year - n - 1)
    except (ValueError, TypeError):
        return ""


def normalize_match(
    match: Dict[str, Any],
    division: Dict[str, Any],
    competition: Dict[str, Any],
    org_meta: Dict[str, str],
    *,
    scrape_run_id: str,
    scraped_at: str,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Convert one Squadi match into (game_rows, team_rows).

    Returns ([], []) when the match should be skipped (e.g. SCHEDULED).
    Otherwise returns:
      - 2 game rows (team1-perspective, team2-perspective)
      - 2 team rows (one per team), deduplicatable by (teamUUID, divisionId)
    """
    match_status = str(match.get("matchStatus") or "").upper()
    if match_status != "ENDED":
        return ([], [])

    team1 = match.get("team1") or {}
    team2 = match.get("team2") or {}
    team1_uuid = str(team1.get("teamUniqueKey") or "")
    team2_uuid = str(team2.get("teamUniqueKey") or "")
    team1_int_id = team1.get("id")
    team2_int_id = team2.get("id")
    if not team1_uuid or not team2_uuid:
        logger.warning(f"Match {match.get('id')} missing teamUniqueKey; skipping")
        return ([], [])

    team1_name = str(team1.get("name") or "").strip()
    team2_name = str(team2.get("name") or "").strip()

    raw_t1 = match.get("team1Score")
    raw_t2 = match.get("team2Score")
    t1_score = parse_int_or_none(raw_t1)
    t2_score = parse_int_or_none(raw_t2)

    substatus = match.get("matchSubstatusRefId")
    explicit_forfeit = substatus in FORFEIT_SUBSTATUS_IDS
    null_score_ended = (
        match_status == "ENDED" and (raw_t1 is None or raw_t2 is None)
    )
    is_forfeit = explicit_forfeit or null_score_ended

    # Surface anomalies: ENDED match with exactly one null score is unusual —
    # could be a real forfeit OR an API population lag. Worth logging.
    if null_score_ended and not explicit_forfeit:
        logger.warning(
            f"Match {match.get('id')} matchStatus=ENDED but scores incomplete "
            f"(t1={raw_t1!r}, t2={raw_t2!r}, substatus={substatus}); "
            f"emitting result=U"
        )

    if is_forfeit and (t1_score is None or t2_score is None):
        result_t1 = "U"
        result_t2 = "U"
    else:
        result_t1 = compute_result(t1_score, t2_score)
        result_t2 = compute_result(t2_score, t1_score)

    division_name = str(division.get("divisionName") or division.get("name") or "").strip()
    age_group, gender, tier = parse_division_metadata(division_name, division.get("age"))

    comp_uuid = str(competition.get("uniqueKey") or "")
    comp_name = str(competition.get("name") or "")
    year_ref_id = competition.get("yearRefId")
    comp_calendar_year = YEAR_REF_TO_CALENDAR.get(year_ref_id) if year_ref_id else None
    org_uuid = str((competition.get("organisation") or {}).get("organisationUniqueKey") or "")
    if not org_uuid:
        org_uuid = org_meta.get("org_uuid", "")

    age_year = _compute_age_year(age_group, comp_calendar_year)
    source_url = _build_source_url(
        org_uuid, comp_uuid, year_ref_id, str(division.get("uniqueKey") or "")
    )
    venue = _build_venue(match.get("venueCourt"))

    game_date, game_time = parse_utc_to_local_date(
        match.get("startTime"), org_meta.get("timezone", "America/New_York")
    )

    schedule_id = f"r{match.get('roundId') or ''}-d{match.get('divisionId') or ''}"

    pk_winner = ""
    if match.get("hasPenalty"):
        pk1 = match.get("team1PenaltyScore")
        pk2 = match.get("team2PenaltyScore")
        if isinstance(pk1, int) and isinstance(pk2, int):
            if pk1 > pk2:
                pk_winner = team1_uuid
            elif pk2 > pk1:
                pk_winner = team2_uuid

    base = {
        "provider": "squadi",
        "scrape_run_id": scrape_run_id,
        "event_id": comp_uuid,
        "event_name": comp_name,
        "schedule_id": schedule_id,
        "age_year": age_year,
        "age_group": age_group,
        "gender": gender,
        "state": org_meta.get("state", ""),
        "state_code": org_meta.get("state_code", ""),
        "game_date": game_date,
        "game_time": game_time,
        "venue": venue,
        "source_url": source_url,
        "scraped_at": scraped_at,
        "division_name": division_name,
    }

    team1_club = parse_club_name(team1_name)
    team2_club = parse_club_name(team2_name)

    row_team1 = {
        **base,
        "team_id": team1_uuid,
        "team_id_source": str(team1_int_id) if team1_int_id is not None else "",
        "team_name": team1_name,
        "club_name": team1_club,
        "opponent_id": team2_uuid,
        "opponent_id_source": str(team2_int_id) if team2_int_id is not None else "",
        "opponent_name": team2_name,
        "opponent_club_name": team2_club,
        "home_away": "H",
        "goals_for": t1_score if t1_score is not None else "",
        "goals_against": t2_score if t2_score is not None else "",
        "result": result_t1,
    }
    row_team2 = {
        **base,
        "team_id": team2_uuid,
        "team_id_source": str(team2_int_id) if team2_int_id is not None else "",
        "team_name": team2_name,
        "club_name": team2_club,
        "opponent_id": team1_uuid,
        "opponent_id_source": str(team1_int_id) if team1_int_id is not None else "",
        "opponent_name": team1_name,
        "opponent_club_name": team1_club,
        "home_away": "A",
        "goals_for": t2_score if t2_score is not None else "",
        "goals_against": t1_score if t1_score is not None else "",
        "result": result_t2,
    }

    base_team = {
        "provider": "squadi",
        "age_group": age_group,
        "gender": gender,
        "state": org_meta.get("state", ""),
        "state_code": org_meta.get("state_code", ""),
        "division_name": division_name,
        "tier": tier,
    }
    team_row_1 = {
        **base_team,
        "provider_team_id": team1_uuid,
        "provider_team_id_source": str(team1_int_id) if team1_int_id is not None else "",
        "team_name": team1_name,
        "club_name": team1_club,
        "external_org_id": extract_external_org_id(team1.get("logoUrl")) or "",
        "meta": json.dumps({
            "squadi_team_id_int": team1_int_id,
            "squadi_competition_uuid": comp_uuid,
            "squadi_division_id": division.get("id"),
        }),
    }
    team_row_2 = {
        **base_team,
        "provider_team_id": team2_uuid,
        "provider_team_id_source": str(team2_int_id) if team2_int_id is not None else "",
        "team_name": team2_name,
        "club_name": team2_club,
        "external_org_id": extract_external_org_id(team2.get("logoUrl")) or "",
        "meta": json.dumps({
            "squadi_team_id_int": team2_int_id,
            "squadi_competition_uuid": comp_uuid,
            "squadi_division_id": division.get("id"),
        }),
    }

    if pk_winner:
        for tr in (team_row_1, team_row_2):
            extra_meta = json.loads(tr["meta"])
            extra_meta["last_pk_winner_team_uuid"] = pk_winner
            tr["meta"] = json.dumps(extra_meta)

    return ([row_team1, row_team2], [team_row_1, team_row_2])


# -----------------------------
# COMPETITION SCRAPER
# -----------------------------


@dataclass
class CompScrapeResult:
    competition_uuid: str
    competition_id_int: int
    competition_name: str
    games_emitted: int = 0
    teams_emitted: int = 0
    skipped_scheduled: int = 0
    skipped_orphan_team: int = 0
    parse_warnings: int = 0
    raw_dir: Optional[Path] = None
    error: Optional[str] = None


def scrape_competition(
    client: "SquadiClient",
    competition: Dict[str, Any],
    org_uuid: str,
    org_meta: Dict[str, str],
    *,
    scrape_run_id: str,
    scraped_at: str,
    raw_dir: Optional[Path] = None,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], CompScrapeResult]:
    """Walk one competition. Returns (game_rows, team_rows, result)."""
    comp_uuid = str(competition.get("uniqueKey") or "")
    comp_int_id = competition.get("id")
    comp_name = str(competition.get("name") or "")
    res = CompScrapeResult(
        competition_uuid=comp_uuid,
        competition_id_int=int(comp_int_id) if comp_int_id is not None else 0,
        competition_name=comp_name,
    )

    # Stamp org context onto competition for normalize_match's source_url helper
    competition.setdefault("organisation", {})["organisationUniqueKey"] = org_uuid

    try:
        divisions_raw = client.list_divisions(comp_uuid)
        round_matches = client.get_round_matches(int(comp_int_id))
    except RuntimeError as e:
        logger.error(f"Competition {comp_name} ({comp_uuid}): {e}")
        res.error = str(e)
        return ([], [], res)

    if raw_dir:
        try:
            raw_dir.mkdir(parents=True, exist_ok=True)
            (raw_dir / "competition.json").write_text(json.dumps(competition))
            (raw_dir / "divisions.json").write_text(json.dumps(divisions_raw))
            (raw_dir / "round_matches.json").write_text(json.dumps(round_matches))
            res.raw_dir = raw_dir
        except OSError as e:
            logger.warning(f"Could not persist raw JSON: {e}")

    div_lookup = {d.get("id"): d for d in divisions_raw if d.get("id") is not None}

    games_buf: List[Dict[str, Any]] = []
    teams_buf: Dict[Tuple[str, Any], Dict[str, Any]] = {}

    for rd in round_matches.get("rounds") or []:
        for match in rd.get("matches") or []:
            div = div_lookup.get(match.get("divisionId"))
            if not div:
                res.skipped_orphan_team += 1
                logger.warning(
                    f"Match {match.get('id')} in comp {comp_name} has no matching "
                    f"divisionId={match.get('divisionId')}"
                )
                continue
            try:
                game_rows, team_rows = normalize_match(
                    match, div, competition, org_meta,
                    scrape_run_id=scrape_run_id, scraped_at=scraped_at,
                )
            except Exception as e:
                logger.warning(f"Match {match.get('id')} normalization error: {e}")
                res.parse_warnings += 1
                continue

            if not game_rows:
                res.skipped_scheduled += 1
                continue

            games_buf.extend(game_rows)
            res.games_emitted += 1
            for tr in team_rows:
                key = (tr["provider_team_id"], div.get("id"))
                if key not in teams_buf:
                    teams_buf[key] = tr

    res.teams_emitted = len(teams_buf)
    return (games_buf, list(teams_buf.values()), res)


# -----------------------------
# VALIDATION + OUTPUT
# -----------------------------


def validate_records(records: List[Dict[str, Any]]) -> None:
    """Ensure every game record has all 28 REQUIRED_COLUMNS."""
    for i, r in enumerate(records):
        missing = [c for c in REQUIRED_COLUMNS if c not in r]
        if missing:
            raise ValueError(f"Record {i} missing columns: {missing}")


def write_outputs(
    games: List[Dict[str, Any]],
    teams: List[Dict[str, Any]],
    manifest: Dict[str, Any],
    output_root: Path,
    scrape_run_id: str,
) -> Path:
    """Atomic write: <output_root>/<run_id>.tmp/ → <output_root>/<run_id>/

    Returns the final output directory.
    """
    output_root.mkdir(parents=True, exist_ok=True)
    final_dir = output_root / scrape_run_id
    tmp_dir = output_root / f"{scrape_run_id}.tmp"

    if tmp_dir.exists():
        # Stale tmp from prior crash — wipe it
        for child in tmp_dir.rglob("*"):
            if child.is_file():
                child.unlink()
        for child in sorted(tmp_dir.rglob("*"), reverse=True):
            if child.is_dir():
                child.rmdir()
        tmp_dir.rmdir()

    tmp_dir.mkdir(parents=True, exist_ok=True)

    # games.csv
    with open(tmp_dir / "games.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=REQUIRED_COLUMNS)
        writer.writeheader()
        writer.writerows(games)

    # teams.csv
    with open(tmp_dir / "teams.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=TEAMS_COLUMNS)
        writer.writeheader()
        writer.writerows(teams)

    # manifest.json
    (tmp_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))

    if final_dir.exists():
        # Replace existing run dir
        for child in final_dir.rglob("*"):
            if child.is_file():
                child.unlink()
        for child in sorted(final_dir.rglob("*"), reverse=True):
            if child.is_dir():
                child.rmdir()
        final_dir.rmdir()
    tmp_dir.rename(final_dir)
    return final_dir


# -----------------------------
# CONFIG + ENTRYPOINT
# -----------------------------


def resolve_config() -> Dict[str, Any]:
    parser = argparse.ArgumentParser(description="SQUADI Competition Scraper")
    parser.add_argument("--url", type=str, help="Squadi livescoreSeasonFixture URL (parses org+comp+year)")
    parser.add_argument("--org-key", type=str, help="organisationUniqueKey (UUID)")
    parser.add_argument("--year-ref-id", type=int, help="Squadi yearRefId (e.g. 8 for 2026)")
    parser.add_argument("--competition-key", type=str, help="competitionUniqueKey (UUID); skips discovery")
    parser.add_argument("--output-dir", type=str, help=f"Output root (default {OUTPUT_DIR})")
    parser.add_argument("--keep-raw", action="store_true", help="Persist raw JSON responses for audit")
    parser.add_argument("--verbose", action="store_true", help="DEBUG-level logging")
    parser.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        default=True,
        help="Validate token + scrape, do NOT write CSVs (default: ON)",
    )
    parser.add_argument(
        "--no-dry-run",
        dest="dry_run",
        action="store_false",
        help="Disable dry-run and write CSV outputs to disk",
    )

    args = parser.parse_args()

    org_uuid: Optional[str] = None
    competition_uuid: Optional[str] = None
    year_ref_id: Optional[int] = None

    if args.url:
        parsed = parse_squadi_url(args.url)
        if not parsed:
            print(f"❌ Could not parse --url: {args.url}", file=sys.stderr)
            sys.exit(1)
        org_uuid = parsed["org_uuid"]
        competition_uuid = parsed["competition_uuid"] or args.competition_key
        year_ref_id = parsed["year_ref_id"] if parsed["year_ref_id"] is not None else args.year_ref_id
    else:
        org_uuid = args.org_key
        competition_uuid = args.competition_key
        year_ref_id = args.year_ref_id

    if not org_uuid and not competition_uuid:
        print("❌ Must provide --url, --org-key, or --competition-key", file=sys.stderr)
        sys.exit(1)

    blocklist_env = os.getenv("SQUADI_COMP_BLOCKLIST", "")
    blocklist = tuple(s.strip() for s in blocklist_env.split(",") if s.strip()) or DEFAULT_COMP_NAME_BLOCKLIST

    return {
        "org_uuid": org_uuid,
        "competition_uuid": competition_uuid,
        "year_ref_id": year_ref_id,
        "output_dir": args.output_dir or OUTPUT_DIR,
        "keep_raw": args.keep_raw,
        "verbose": args.verbose,
        "dry_run": args.dry_run,
        "name_blocklist": blocklist,
        "delay_sec": float(os.getenv("SQUADI_DELAY_SEC", "0.3")),
    }


def main() -> int:
    global SCRAPE_TS, SCRAPE_RUN_ID
    config = resolve_config()
    logging.basicConfig(
        level=logging.DEBUG if config["verbose"] else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    SCRAPE_TS = datetime.now(timezone.utc).isoformat()
    SCRAPE_RUN_ID = f"{SCRAPE_TS.replace(':', '-').replace('.', '-')}_{uuid.uuid4().hex[:6]}"

    print("🚀 SQUADI Competition Scraper")
    print(f"🆔 Scrape run ID: {SCRAPE_RUN_ID}")
    print(f"🔧 Mode: {'DRY-RUN' if config['dry_run'] else 'WRITE'}")

    harvester = SquadiTokenHarvester()
    client = SquadiClient(harvester, delay_sec=config["delay_sec"])

    if config["competition_uuid"] and not config["org_uuid"]:
        target_comps = []
        for org_uuid_candidate in ORG_REGISTRY.keys():
            for yri in YEAR_REF_TO_CALENDAR.keys():
                try:
                    comps = client.list_competitions(org_uuid_candidate, yri)
                except RuntimeError:
                    continue
                for comp in comps:
                    if comp.get("uniqueKey") == config["competition_uuid"]:
                        config["org_uuid"] = org_uuid_candidate
                        target_comps = [comp]
                        break
                else:
                    continue
                break
            else:
                continue
            break
        if not config.get("org_uuid"):
            print(f"❌ Could not locate competition {config['competition_uuid']} in any known org", file=sys.stderr)
            return 1
    elif config["competition_uuid"] and config["org_uuid"]:
        target_comps = []
        for yri in (config["year_ref_id"],) if config["year_ref_id"] else YEAR_REF_TO_CALENDAR.keys():
            try:
                comps = client.list_competitions(config["org_uuid"], yri)
            except RuntimeError:
                continue
            for comp in comps:
                if comp.get("uniqueKey") == config["competition_uuid"]:
                    target_comps.append(comp)
        if not target_comps:
            print(f"❌ Competition {config['competition_uuid']} not found under org {config['org_uuid']}", file=sys.stderr)
            return 1
    else:
        target_comps = discover_competitions(
            client, config["org_uuid"],
            year_ref_id=config["year_ref_id"],
            name_blocklist=config["name_blocklist"],
        )

    if not target_comps:
        print(f"⚠️ No active competitions found for org={config['org_uuid']} year={config['year_ref_id']}")
        return 0

    org_meta = ORG_REGISTRY.get(config["org_uuid"])
    if not org_meta:
        print(f"❌ Org {config['org_uuid']} not in ORG_REGISTRY — add it before scraping", file=sys.stderr)
        return 1

    output_root = Path(config["output_dir"])
    raw_root = output_root / SCRAPE_RUN_ID / "raw" if config["keep_raw"] else None

    all_games: List[Dict[str, Any]] = []
    all_teams_map: Dict[Tuple[str, Any], Dict[str, Any]] = {}
    comp_results: List[CompScrapeResult] = []

    scrape_start = time.time()
    for comp in target_comps:
        comp_raw_dir = (raw_root / str(comp.get("uniqueKey"))) if raw_root else None
        games, teams, res = scrape_competition(
            client, comp, config["org_uuid"], org_meta,
            scrape_run_id=SCRAPE_RUN_ID, scraped_at=SCRAPE_TS,
            raw_dir=comp_raw_dir,
        )
        all_games.extend(games)
        for tr in teams:
            key = (tr["provider_team_id"], json.loads(tr["meta"]).get("squadi_division_id"))
            all_teams_map.setdefault(key, tr)
        comp_results.append(res)
        print(
            f"  ✅ {res.competition_name}: games={res.games_emitted} "
            f"teams={res.teams_emitted} skipped_scheduled={res.skipped_scheduled} "
            f"errors={'1' if res.error else '0'}"
        )

    duration = time.time() - scrape_start
    all_teams = list(all_teams_map.values())

    if all_games:
        validate_records(all_games)

    manifest = {
        "run_id": SCRAPE_RUN_ID,
        "scraped_at": SCRAPE_TS,
        "org_uuid": config["org_uuid"],
        "year_ref_id": config["year_ref_id"],
        "comps_total": len(target_comps),
        "comps_ok": sum(1 for r in comp_results if not r.error),
        "comps_failed": sum(1 for r in comp_results if r.error),
        "games_emitted": len(all_games),
        "teams_emitted": len(all_teams),
        "token_refresh_count": client.token_refresh_count,
        "build_hash": harvester.build_hash,
        "duration_sec": round(duration, 2),
        "competitions": [
            {
                "uuid": r.competition_uuid,
                "id_int": r.competition_id_int,
                "name": r.competition_name,
                "games": r.games_emitted,
                "teams": r.teams_emitted,
                "error": r.error,
            }
            for r in comp_results
        ],
        "status": "ok" if all(not r.error for r in comp_results) else "partial",
        "dry_run": config["dry_run"],
    }

    if not config["dry_run"]:
        out_dir = write_outputs(all_games, all_teams, manifest, output_root, SCRAPE_RUN_ID)
        print(f"\n✅ OUTPUT: {out_dir}")
    else:
        print(f"\n🔍 DRY RUN — {len(all_games)} game rows, {len(all_teams)} team rows validated (not written)")

    print(json.dumps({"summary": manifest}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())


# Globals set in main()
SCRAPE_TS = None
SCRAPE_RUN_ID = None
