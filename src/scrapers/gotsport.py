"""GotSport scraper implementation using API, plus event/tournament scraper.

Shell 01 Step 3 Commit B consolidated the former ``src.scrapers.gotsport_event``
module into this file. The old file remains as a back-compat shim re-exporting
``GotsportScraper as GotSportEventScraper`` so the 8 external importer scripts
continue to work with zero changes.
"""

import json
import logging
import os
import random
import re
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from requests.exceptions import SSLError as RequestsSSLError
from urllib3.exceptions import SSLError as Urllib3SSLError
from urllib3.util.retry import Retry

try:
    import certifi

    CERTIFI_AVAILABLE = True
except ImportError:
    CERTIFI_AVAILABLE = False
    certifi = None

from src.base import GameData
from src.scrapers.base import BaseScraper
from src.scrapers.event_team import EventTeam
from src.scrapers.intake_journal import DURABLE_ACTIONS, IntakeJournal, compute_skip_set
from src.scrapers.provider import (
    CanonicalResolution,
    EventMetadata,
    ProviderScraper,
    ScrapedTeam,
    UnsupportedProviderError,
)
from src.tournaments.alias_writer import enqueue_match_review, upsert_team_alias
from src.utils.team_utils import CURRENT_YEAR

__all__ = [
    "CERTIFI_AVAILABLE",
    "EventCaptchaGatedError",
    "EventTeam",
    "GotSportScraper",
    "GotsportScraper",
    "TeamNotFoundError",
]

logger = logging.getLogger(__name__)


class TeamNotFoundError(Exception):
    """Raised when a team ID returns 404 from the provider API"""

    def __init__(self, team_id, provider="gotsport"):
        self.team_id = team_id
        self.provider = provider
        super().__init__(f"Team {team_id} not found on {provider} (404)")


class GotSportScraper(BaseScraper):
    """Scraper for GotSport using their API endpoint"""

    BASE_URL = "https://system.gotsport.com/api/v1"
    RANKINGS_BASE = "https://rankings.gotsport.com"

    def __init__(self, supabase_client, provider_code: str = "gotsport"):
        super().__init__(supabase_client, provider_code)

        # Configuration
        self.delay_min = float(os.getenv("GOTSPORT_DELAY_MIN", "1.5"))
        self.delay_max = float(os.getenv("GOTSPORT_DELAY_MAX", "2.5"))
        self.max_retries = int(os.getenv("GOTSPORT_MAX_RETRIES", "3"))
        self.timeout = int(os.getenv("GOTSPORT_TIMEOUT", "30"))
        self.retry_delay = float(os.getenv("GOTSPORT_RETRY_DELAY", "2.0"))

        # ZenRows configuration (optional)
        self.zenrows_api_key = os.getenv("ZENROWS_API_KEY")
        self.use_zenrows = bool(self.zenrows_api_key)

        # Session setup
        self.session = self._init_http_session()

        # Club name cache
        self.club_cache: Dict[str, str] = {}

        logger.info(f"Initialized GotSportScraper (ZenRows: {'enabled' if self.use_zenrows else 'disabled'})")

    def _init_http_session(self) -> requests.Session:
        """
        Initialize HTTP session with optimized connection pool for concurrent scraping

        SSL improvements:
        - Uses certifi for up-to-date certificates
        - Configures urllib3 SSL context for better stability
        - Connection pool recycling to avoid stale SSL connections

        Returns:
            Configured requests.Session with HTTPAdapter supporting up to 100 concurrent connections
        """
        session = requests.Session()

        # SSL configuration: use certifi if available for better certificate handling
        verify_ssl = True
        if CERTIFI_AVAILABLE:
            verify_ssl = certifi.where()
            logger.debug(f"Using certifi certificates: {verify_ssl}")

        # Configure HTTPAdapter with larger connection pool and SSL improvements.
        # 429 is in status_forcelist so urllib3 transparently retries rate-limit
        # responses. backoff_factor=1.0 → waits of 1s, 2s, 4s between the 3 tries.
        adapter = HTTPAdapter(
            pool_connections=100,  # number of connection pools
            pool_maxsize=100,  # total concurrent connections
            max_retries=Retry(
                total=3,
                backoff_factor=1.0,
                status_forcelist=[429, 500, 502, 503, 504],  # Retry on rate limit + server errors
                respect_retry_after_header=True,  # Honor Retry-After from GotSport
                # Retry on SSL errors (will be caught and retried)
                allowed_methods=["GET", "HEAD"],
            ),
        )

        # Mount adapter for both HTTPS and HTTP
        session.mount("https://", adapter)
        session.mount("http://", adapter)

        # Set SSL verification (use certifi if available)
        session.verify = verify_ssl

        # Set headers
        session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",  # noqa: E501
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "en-US,en;q=0.9",
                "Origin": self.RANKINGS_BASE,
                "Referer": f"{self.RANKINGS_BASE}/",
                "Connection": "keep-alive",
            }
        )

        return session

    def scrape_team_games(self, team_id: str, since_date: Optional[datetime] = None) -> List[GameData]:
        """
        Scrape games for a specific GotSport team using API

        Args:
            team_id: GotSport team ID
            since_date: Only scrape games after this date (for incremental updates)

        Returns:
            List of GameData objects
        """
        # Normalize team ID (handle "126693.0" -> 126693)
        try:
            normalized_team_id = int(float(str(team_id)))
        except (ValueError, TypeError):
            logger.error(f"Invalid team_id: {team_id}")
            return []

        # For incremental scraping: use last scrape date if available
        # For first-time scraping: use October 17, 2025 baseline
        # If since_date is explicitly None, get all games
        if since_date is None:
            # Explicitly None means get all games (no date filter)
            since_date_obj = None
            logger.debug("Fetching all games (no date filter)")
        elif since_date:
            # Use the last scrape date (incremental update)
            since_date_obj = since_date.date() if isinstance(since_date, datetime) else since_date
            logger.debug(f"Incremental scrape: fetching games since {since_date_obj}")
        else:
            # First-time scrape: use October 17, 2025 baseline
            since_date_obj = date(2025, 10, 17)
            logger.debug(f"First-time scrape: fetching games since {since_date_obj} (Oct 17, 2025 baseline)")

        # API endpoint
        api_url = f"{self.BASE_URL}/teams/{normalized_team_id}/matches"
        params = {"past": "true"}

        # Try to add date filtering at API level (if supported)
        # Common parameter names: since_date, from_date, date_from, since
        # Format: YYYY-MM-DD or ISO format
        if since_date_obj:
            since_date_str = since_date_obj.strftime("%Y-%m-%d")
            # Try common date parameter names (API may ignore if not supported)
            params["since_date"] = since_date_str
            params["from_date"] = since_date_str

        # Fetch club name first
        club_name = self._extract_club_name(normalized_team_id)

        games = []

        # Retry logic
        for attempt in range(self.max_retries):
            try:
                # Use ZenRows if configured
                if self.use_zenrows:
                    response = self._make_zenrows_request(api_url, params)
                else:
                    response = self.session.get(api_url, params=params, timeout=self.timeout)

                # Surface transparent urllib3 retries. response.raw.retries may be
                # None on responses that never triggered the retry machinery.
                retries_obj = getattr(response.raw, "retries", None)
                history = getattr(retries_obj, "history", ()) or ()
                n429 = sum(1 for h in history if getattr(h, "status", None) == 429)
                if n429:
                    logger.warning(
                        "gotsport 429 retries: team=%s count=%d url=%s",
                        normalized_team_id,
                        n429,
                        api_url,
                    )

                response.raise_for_status()
                data = response.json()

                # API returns a list directly
                if isinstance(data, list) and data:
                    matches = data
                    # Sort by date (newest first) and cap to most recent 30
                    try:
                        matches.sort(key=lambda m: m.get("match_date") or "", reverse=True)
                    except Exception:
                        pass

                    logger.info(f"API returned {len(matches)} matches for team {normalized_team_id}")

                    # OPTIMIZATION: Parse matches with early exit
                    # Since matches are sorted newest first, we can stop parsing once we hit a date before our cutoff
                    for match in matches[:30]:  # Cap to 30 most recent
                        # Quick date check before full parsing (early exit optimization)
                        match_date_str = match.get("match_date", "")
                        if match_date_str:
                            try:
                                # Parse date in UTC to avoid timezone conversion issues
                                if "T" in match_date_str:
                                    dt = datetime.fromisoformat(match_date_str.replace("Z", "+00:00"))
                                    if dt.tzinfo is not None:
                                        game_date = dt.astimezone(timezone.utc).date()
                                    else:
                                        game_date = dt.date()
                                else:
                                    game_date = datetime.strptime(match_date_str, "%Y-%m-%d").date()
                                # If this game is before our cutoff, stop parsing (all remaining will be older)
                                if since_date_obj is not None and game_date < since_date_obj:
                                    logger.debug(
                                        f"Reached date cutoff at {game_date}, "
                                        f"stopping parse for team {normalized_team_id}"
                                    )
                                    break
                            except (ValueError, TypeError):
                                # If date parsing fails, continue to full parse (will be filtered there)
                                pass

                        # Full parse (includes date filtering as backup)
                        game = self._parse_api_match(match, normalized_team_id, since_date_obj, club_name)
                        if game:
                            games.append(game)

                    break  # Success, exit retry loop
                else:
                    logger.info(f"No matches found for team {normalized_team_id}")
                    break

            except requests.exceptions.HTTPError as e:
                # Raise TeamNotFoundError on 404 so callers can handle it
                if e.response is not None and e.response.status_code == 404:
                    logger.warning(f"Team {normalized_team_id} not found (404)")
                    raise TeamNotFoundError(normalized_team_id)

                # Retry for other HTTP errors
                if attempt < self.max_retries - 1:
                    logger.warning(f"API attempt {attempt + 1} failed: {e}, retrying...")
                    time.sleep(self.retry_delay)
                    continue
                else:
                    logger.error(f"API failed after {self.max_retries} attempts: {e}")
                    raise

            except (RequestsSSLError, Urllib3SSLError) as e:
                # SSL-specific error handling with exponential backoff
                ssl_error_msg = str(e).lower()
                if "bad record mac" in ssl_error_msg or "sslv3_alert" in ssl_error_msg:
                    # Common SSL errors that can be retried
                    if attempt < self.max_retries - 1:
                        # Exponential backoff for SSL errors (longer wait)
                        wait_time = self.retry_delay * (2**attempt) + random.uniform(0, 1.0)
                        logger.warning(
                            f"SSL error (attempt {attempt + 1}/{self.max_retries}): "
                            f"{e}, retrying in {wait_time:.1f}s..."
                        )
                        time.sleep(wait_time)
                        # Close the session to force new connection
                        self.session.close()
                        self.session = self._init_http_session()
                        continue
                    else:
                        logger.error(f"SSL error persisted after {self.max_retries} attempts: {e}")
                        raise
                else:
                    # Other SSL errors - still retry but log differently
                    if attempt < self.max_retries - 1:
                        wait_time = self.retry_delay * (1.5**attempt)
                        logger.warning(
                            f"SSL error (attempt {attempt + 1}/{self.max_retries}): "
                            f"{e}, retrying in {wait_time:.1f}s..."
                        )
                        time.sleep(wait_time)
                        continue
                    else:
                        logger.error(f"SSL error failed after {self.max_retries} attempts: {e}")
                        raise

            except requests.exceptions.RetryError as e:
                # urllib3 exhausted its per-call retry budget (total=3) on 429
                # or 5xx. Emit the verification-grep marker here, then fall
                # through to the outer retry loop to preserve the pre-change
                # behavior (where the generic RequestException handler did the
                # same thing). Must precede the RequestException handler below
                # because RetryError is a RequestException subclass.
                logger.error(
                    "gotsport 429 retry-exhausted: team=%s url=%s err=%s",
                    normalized_team_id,
                    api_url,
                    e,
                )
                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_delay)
                    continue
                raise

            except requests.exceptions.RequestException as e:
                if attempt < self.max_retries - 1:
                    logger.warning(f"Request attempt {attempt + 1} failed: {e}, retrying...")
                    time.sleep(self.retry_delay)
                    continue
                else:
                    logger.error(f"Request failed after {self.max_retries} attempts: {e}")
                    raise

        # Rate limiting
        if self.delay_min > 0 or self.delay_max > 0:
            time.sleep(random.uniform(self.delay_min, self.delay_max))

        logger.info(f"Found {len(games)} games for team {normalized_team_id}")
        return games

    def _make_zenrows_request(self, url: str, params: Dict) -> requests.Response:
        """Make request through ZenRows proxy"""
        zenrows_url = "https://api.zenrows.com/v1/"
        zenrows_params = {
            "apikey": self.zenrows_api_key,
            "url": url,
            "js_render": "false",
            "premium_proxy": "true",
            "proxy_country": "us",
        }
        # Merge original params into URL
        if params:
            from urllib.parse import urlencode

            url_with_params = f"{url}?{urlencode(params)}"
            zenrows_params["url"] = url_with_params

        return self.session.get(zenrows_url, params=zenrows_params, timeout=self.timeout)

    def _extract_club_name(self, team_id: int) -> str:
        """Extract club name from team details API"""
        try:
            api_url = f"{self.BASE_URL}/team_ranking_data/team_details"
            params = {"team_id": team_id}

            response = self.session.get(api_url, params=params, timeout=15)
            response.raise_for_status()

            data = response.json()
            club_name = data.get("club_name", "")

            if club_name:
                self.club_cache[str(team_id)] = club_name
                logger.debug(f"Extracted club name for team {team_id}: '{club_name}'")

            return club_name

        except Exception as e:
            logger.debug(f"Failed to extract club name for team {team_id}: {e}")
            return self.club_cache.get(str(team_id), "")

    def _parse_api_match(self, match: Dict, team_id: int, since_date: date, club_name: str = "") -> Optional[GameData]:
        """Parse a match from the GotSport API response"""
        try:
            # Extract team info
            home_team = match.get("homeTeam", {})
            away_team = match.get("awayTeam", {})

            # Determine if our team is home or away
            is_home = False
            opponent = {}

            if home_team.get("team_id") == team_id:
                is_home = True
                opponent = away_team
            elif away_team.get("team_id") == team_id:
                is_home = False
                opponent = home_team
            else:
                logger.debug(f"Team {team_id} not found in match")
                return None

            # Filter out U20+ games (PitchRank supports U10-U19)
            # Check age_group field in match or team objects
            for team_obj in [home_team, away_team]:
                age_group = team_obj.get("age_group", "").upper().strip()
                birth_year = team_obj.get("birth_year")

                # Skip if age_group indicates U20+
                if age_group in ["U20", "U-20", "20U", "U21", "U-21", "21U"]:
                    logger.debug(f"Skipping U20+ game (age_group={age_group})")
                    return None

                # Skip if birth_year is 2006 or earlier (U20+ for 2026)
                if birth_year and isinstance(birth_year, (int, str)):
                    try:
                        birth_year_int = int(birth_year)
                        if birth_year_int <= (CURRENT_YEAR - 19):
                            logger.debug(f"Skipping U20+ game (birth_year={birth_year_int})")
                            return None
                    except (ValueError, TypeError):
                        pass

            # Parse date
            match_date = match.get("match_date", "")
            if not match_date:
                return None

            try:
                # Parse the date string - handle both ISO format with timezone and date-only format
                # IMPORTANT: Extract date in UTC to avoid timezone conversion issues
                if "T" in match_date:
                    # ISO format with time: "2025-11-07T00:00:00Z" or "2025-11-07T00:00:00+00:00"
                    # Parse as UTC and extract date without timezone conversion
                    dt = datetime.fromisoformat(match_date.replace("Z", "+00:00"))
                    # Use UTC date directly (don't convert to local timezone)
                    # If timezone-aware, convert to UTC first, then get date
                    if dt.tzinfo is not None:
                        game_date = dt.astimezone(timezone.utc).date()
                    else:
                        game_date = dt.date()
                else:
                    # Date-only format: "2025-11-07"
                    game_date = datetime.strptime(match_date, "%Y-%m-%d").date()
            except (ValueError, TypeError) as e:
                logger.warning(f"Invalid date format: {match_date}, error: {e}")
                return None

            # Apply date filter
            if since_date is not None and game_date < since_date:
                return None

            # Extract scores
            home_score = match.get("home_score")
            away_score = match.get("away_score")

            # Determine goals for/against
            if is_home:
                goals_for = home_score
                goals_against = away_score
            else:
                goals_for = away_score
                goals_against = home_score

            # Extract opponent info
            opponent_name = opponent.get("full_name", "Unknown")
            opponent_id = str(opponent.get("team_id", ""))

            # Extract opponent club
            opponent_club_name = ""
            try:
                club_obj = opponent.get("club")
                if isinstance(club_obj, dict):
                    opponent_club_name = str(club_obj.get("name", "")).strip()
            except Exception:
                pass

            # If missing, try to fetch
            if not opponent_club_name and opponent_id:
                opponent_club_name = self._fetch_club_name_for_team_id(opponent_id)

            # Extract venue
            venue = match.get("venue", {})
            venue_name = venue.get("name", "") if isinstance(venue, dict) else ""

            # Extract competition info
            competition_name = match.get("competition_name", "")
            division_name = match.get("division_name", "")
            event_name = match.get("event_name", "")

            # Determine result
            result = self._determine_result(goals_for, goals_against)

            return GameData(
                provider_id=self.provider_code,
                team_id=str(team_id),
                opponent_id=opponent_id,
                team_name="",  # Will be filled from team data
                opponent_name=opponent_name,
                game_date=game_date.strftime("%Y-%m-%d"),
                home_away="H" if is_home else "A",
                goals_for=goals_for,
                goals_against=goals_against,
                result=result,
                competition=competition_name or division_name or event_name,
                venue=venue_name,
                meta={
                    "source_url": f"{self.RANKINGS_BASE}/teams/{team_id}/game-history",
                    "scraped_at": datetime.now().isoformat(),
                    "club_name": club_name,
                    "opponent_club_name": opponent_club_name,
                },
            )

        except Exception as e:
            logger.warning(f"Error parsing API match: {e}")
            return None

    def _fetch_club_name_for_team_id(self, team_id: str) -> str:
        """Fetch club name for a given team ID via team details API"""
        try:
            tid = int(float(str(team_id)))
        except Exception:
            return ""

        # Check cache first
        if team_id in self.club_cache:
            return self.club_cache[team_id]

        try:
            api_url = f"{self.BASE_URL}/team_ranking_data/team_details"
            params = {"team_id": tid}

            response = self.session.get(api_url, params=params, timeout=15)
            response.raise_for_status()

            data = response.json()
            club_name = str(data.get("club_name", "")).strip()

            if club_name:
                self.club_cache[team_id] = club_name

            return club_name
        except Exception:
            return ""

    def _determine_result(self, goals_for: Optional[int], goals_against: Optional[int]) -> str:
        """Determine game result based on scores"""
        if goals_for is None or goals_against is None:
            return "U"  # Unknown

        if goals_for > goals_against:
            return "W"  # Win
        elif goals_for < goals_against:
            return "L"  # Loss
        else:
            return "D"  # Draw

    def _game_data_to_dict(self, game: GameData, team_id: str) -> Dict:
        """Convert GameData to import format dictionary, including club names"""
        meta = game.meta or {}
        base_dict = super()._game_data_to_dict(game, team_id)
        # Add club names from meta
        base_dict["club_name"] = meta.get("club_name", "")
        base_dict["opponent_club_name"] = meta.get("opponent_club_name", "")
        return base_dict

    def validate_team_id(self, team_id: str) -> bool:
        """Validate if team ID exists in GotSport"""
        try:
            normalized_team_id = int(float(str(team_id)))
            api_url = f"{self.BASE_URL}/teams/{normalized_team_id}/matches"
            params = {"past": "true"}

            response = self.session.get(api_url, params=params, timeout=10)
            return response.status_code == 200
        except Exception:
            return False


# Markers for gotsport's per-event reCAPTCHA v2 challenge page
# (observed 2026-04-24 on events 45224, 40550, 40610 among others).
# Detection is permissive: any of these patterns is enough — the three tend
# to co-occur but gotsport has served the challenge body at the event URL
# directly (no redirect) as well as via 302 to /verify_captchas/new.
_CAPTCHA_URL_MARKER = re.compile(r"/verify_captchas(?:/|$|\?)", re.IGNORECASE)
_CAPTCHA_BODY_MARKER = re.compile(r"Please verify to continue", re.IGNORECASE)
# reCAPTCHA sitekey appears in several shapes on the challenge page:
#   1. <div data-sitekey="KEY">                  — static form variant
#   2. <script src=".../api.js?render=KEY">      — script-include variant (seen
#                                                   on gotsport without JS render)
#   3. <iframe src=".../api2/anchor?k=KEY&...>   — JS-rendered iframe
#   4. grecaptcha.render(..., {sitekey: "KEY"})  — JS init
# Check all four in order; each captures into its own group.
_CAPTCHA_SITEKEY_RE = re.compile(
    r"""(?:"""
    r"""data-sitekey\s*=\s*['"]([^'"]+)['"]"""
    r"""|"""
    r"""recaptcha/api\.js\?[^'"<>\s]*\brender=([A-Za-z0-9_\-]+)"""
    r"""|"""
    r"""recaptcha/api2/anchor\?[^'"]*\bk=([A-Za-z0-9_\-]+)"""
    r"""|"""
    r"""['"]sitekey['"]\s*:\s*['"]([^'"]+)['"]"""
    r""")""",
    re.IGNORECASE,
)
# Last-ditch fallback: every Google reCAPTCHA sitekey starts with `6L` and is
# 40 chars of URL-safe base64. If the structured regex misses all shapes,
# grab the first bare `6L...` token in the body.
_RECAPTCHA_SITEKEY_FALLBACK_RE = re.compile(r"\b(6L[A-Za-z0-9_\-]{38,45})\b")


class EventCaptchaGatedError(Exception):
    """Raised when an event URL is behind gotsport's reCAPTCHA challenge.

    Carries the reCAPTCHA sitekey and the challenge URL so a future CAPTCHA
    solver can pick up where the scraper left off. The scraper surfaces this
    as a retryable state — callers SHOULD NOT mark the event as scraped, so
    it is retried on the next run (gate may clear).
    """

    def __init__(
        self,
        *,
        provider_event_id: str,
        captcha_url: str,
        sitekey: Optional[str],
        artifact_path: Optional[Path] = None,
    ):
        self.provider_event_id = provider_event_id
        self.captcha_url = captcha_url
        self.sitekey = sitekey
        self.artifact_path = artifact_path
        super().__init__(
            f"gotsport event {provider_event_id} is behind a reCAPTCHA challenge "
            f"({captcha_url}); sitekey={sitekey or '?'}"
        )


def _find_sitekey(body: str) -> Optional[str]:
    """Pull a reCAPTCHA sitekey from the challenge body.

    First tries the structured regex (4 shapes); falls back to the bare
    `6L...` token pattern if the structured forms all miss — every Google
    reCAPTCHA sitekey starts with `6L` so this is reliable."""
    match = _CAPTCHA_SITEKEY_RE.search(body)
    if match:
        for group in match.groups():
            if group:
                return group
    fallback = _RECAPTCHA_SITEKEY_FALLBACK_RE.search(body)
    return fallback.group(1) if fallback else None


def _extract_captcha_signals(
    response: requests.Response, fallback_target_url: str
) -> Optional[dict]:
    """Return {'captcha_url', 'sitekey'} if the response looks like gotsport's
    CAPTCHA challenge, else None.

    `fallback_target_url` is the gotsport URL we intended to fetch — it's used
    when the response travelled through a proxy (ZenRows) so the `captcha_url`
    reflects the real origin URL, not the proxy endpoint. ZenRows surfaces the
    origin's final URL in the `Zr-Final-Url` response header; we prefer that
    over `response.url` (which is the ZenRows API URL when routed).

    Checks (in order):
    1. Zr-Final-Url / response.url contains /verify_captchas
    2. Any redirect history Location contains /verify_captchas
    3. Response body contains "Please verify to continue" (server serves the
       challenge page directly with no redirect — observed on 40550/40610)
    """
    body = response.text or ""
    zr_final = response.headers.get("Zr-Final-Url") or ""
    request_url = str(response.url or "")
    effective_final_url = zr_final or request_url

    if _CAPTCHA_URL_MARKER.search(effective_final_url):
        return {
            "captcha_url": effective_final_url,
            "sitekey": _find_sitekey(body),
        }
    for hr in response.history or []:
        loc = hr.headers.get("Location") or ""
        if _CAPTCHA_URL_MARKER.search(loc):
            return {
                "captcha_url": loc if loc.startswith("http") else effective_final_url,
                "sitekey": _find_sitekey(body),
            }
    if _CAPTCHA_BODY_MARKER.search(body):
        # Body signal fires but no redirect was seen — server served challenge
        # at the target URL directly. Report the target URL as challenge URL.
        return {
            "captcha_url": fallback_target_url,
            "sitekey": _find_sitekey(body),
        }
    return None


class GotsportScraper(ProviderScraper):
    """ProviderScraper implementation for gotsport.com event/tournament intake.

    Shell 01 Step 3 — Commit B. Physical move of the former
    ``GotSportEventScraper`` class body into this module. The
    ``gotsport_event.py`` file is now a ≤30-line back-compat shim that
    re-exports this class under its old name, so the 8 external importer
    scripts continue to work with zero changes.

    Implements the ``ProviderScraper`` ABC:

    - ``fetch_event_metadata(event_url)`` — scrapes event-level metadata;
      reuses ``_fetch_event_page`` so CAPTCHA-gated events surface
      ``EventCaptchaGatedError`` rather than a cryptic parse failure.
    - ``fetch_teams_by_cohort`` — stub until Shell 01 Step 4 + 6 land
      (resumable journal + alias_writer routing).
    - ``resolve_canonical_team_id`` — stub until Shell 01 Step 6 lands.

    The existing public methods inherited from the old class
    (``scrape_event_games``, ``scrape_games_from_schedule_pages``,
    ``extract_event_teams``, ``extract_event_teams_by_bracket``,
    ``extract_event_dates``, ``scrape_event_by_url``, ``list_event_teams``,
    and the CAPTCHA-aware ``_fetch_event_page``) remain the working event
    intake surface.
    """

    """
    Scraper for GotSport events/tournaments

    This scraper:
    1. Extracts team IDs from an event page
    2. Uses the existing GotSportScraper to get games for those teams
    3. Filters games to only include those from the specified event
    """

    BASE_URL = "https://system.gotsport.com"
    EVENT_BASE = "https://system.gotsport.com/org_event/events"

    def __init__(self, supabase_client, provider_code: str = "gotsport", skip_team_id_resolution: bool = False):
        """
        Initialize the event scraper

        Args:
            supabase_client: Supabase client instance
            provider_code: Provider code (default: 'gotsport')
            skip_team_id_resolution: If True, skip expensive API team ID resolution
                                    and use registration IDs directly (default: False)
        """
        self.supabase_client = supabase_client
        self.provider_code = provider_code
        self.skip_team_id_resolution = skip_team_id_resolution

        # Use the existing team scraper for actual game scraping. Lazy import
        # — see comment at top of file for the circular-import rationale.
        from src.scrapers.gotsport import GotSportScraper

        self.team_scraper = GotSportScraper(supabase_client, provider_code)

        # Configuration - aggressive defaults for speed
        self.delay_min = float(os.getenv("GOTSPORT_DELAY_MIN", "0.1"))
        self.delay_max = float(os.getenv("GOTSPORT_DELAY_MAX", "0.3"))
        self.max_retries = int(os.getenv("GOTSPORT_MAX_RETRIES", "2"))
        self.timeout = int(os.getenv("GOTSPORT_TIMEOUT", "15"))
        self.retry_delay = float(os.getenv("GOTSPORT_RETRY_DELAY", "0.5"))

        # ZenRows configuration (optional). Mirrors src/scrapers/gotsport.py:56.
        # When ZENROWS_API_KEY is set, event-URL fetches route through ZenRows'
        # residential proxy to sidestep gotsport's domain-level UA/IP detection.
        # Does NOT solve gotsport's per-event reCAPTCHA challenges — those are
        # detected and surfaced via EventCaptchaGatedError.
        self.zenrows_api_key = os.getenv("ZENROWS_API_KEY")
        self.use_zenrows = bool(self.zenrows_api_key)

        # Session setup
        self.session = self._init_http_session()

        # Providers-table assertion (plan Step 3). ``.single()`` raises
        # on 0 rows; wrap to surface a typed error with an actionable
        # message instead of a raw postgrest APIError.
        try:
            result = (
                supabase_client.table("providers")
                .select("id, code")
                .eq("code", "gotsport")
                .single()
                .execute()
            )
        except Exception as e:
            raise UnsupportedProviderError(
                f"'gotsport' not registered in providers table — run migrations. Inner: {e}"
            ) from e
        if not getattr(result, "data", None) or "id" not in result.data:
            raise UnsupportedProviderError("'gotsport' provider row returned empty")
        self._provider_uuid = result.data["id"]

        # Matcher candidate cache — populated during fetch_teams_by_cohort so
        # every team's search_event_team_in_db call reuses the per-cohort
        # candidate list. Cold calls take ~5s (scan of age×gender partition);
        # warm calls take ~700ms. Live smoke 2026-04-24 on 42434 showed this
        # drops total run time from ~27 min to ~5 min. Reset per scrape so
        # stale candidates from a prior run don't leak.
        self._matcher_cache: dict[tuple, list[dict[str, Any]]] = {}

        logger.info(
            f"Initialized GotsportScraper "
            f"(skip_team_id_resolution={skip_team_id_resolution}, "
            f"ZenRows: {'enabled' if self.use_zenrows else 'disabled'})"
        )

    def _init_http_session(self) -> requests.Session:
        """Initialize HTTP session with retry logic"""
        session = requests.Session()

        verify_ssl = True
        if CERTIFI_AVAILABLE:
            verify_ssl = certifi.where()

        adapter = HTTPAdapter(
            pool_connections=10,
            pool_maxsize=10,
            max_retries=Retry(
                total=3, backoff_factor=0.3, status_forcelist=[500, 502, 503, 504], allowed_methods=["GET", "HEAD"]
            ),
        )

        session.mount("https://", adapter)
        session.mount("http://", adapter)
        session.verify = verify_ssl

        # Browser-realistic header bundle for gotsport's bot detection. Phase A
        # on event 45224 (2026-04-24) showed the prior minimal header set
        # hitting a 403 on the root domain and a 302 → /verify_captchas/new on
        # event URLs. Sec-Fetch-*, Sec-Ch-Ua-*, Upgrade-Insecure-Requests, and
        # a current Chrome UA avoid the CAPTCHA challenge. Only advertise
        # Accept-Encoding values we can actually decode (brotli installed;
        # zstandard is not, so `zstd` is omitted).
        session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",  # noqa: E501
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",  # noqa: E501
                "Accept-Language": "en-US,en;q=0.9",
                "Accept-Encoding": "gzip, deflate, br",
                "Upgrade-Insecure-Requests": "1",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none",
                "Sec-Fetch-User": "?1",
                "Sec-Ch-Ua": '"Chromium";v="133", "Not(A:Brand";v="24", "Google Chrome";v="133"',
                "Sec-Ch-Ua-Mobile": "?0",
                "Sec-Ch-Ua-Platform": '"Windows"',
                "Priority": "u=0, i",
            }
        )

        return session

    def _make_zenrows_request(self, url: str) -> requests.Response:
        """Route a GET through ZenRows' residential proxy.

        Mirrors src/scrapers/gotsport.py:333-350. `js_render=false` +
        `premium_proxy=true` is the cheapest mode that bypasses gotsport's
        domain-level IP/UA reputation checks. CAPTCHA'd events still come
        back as CAPTCHA pages — detection happens in _fetch_event_page.
        """
        zenrows_url = "https://api.zenrows.com/v1/"
        zenrows_params = {
            "apikey": self.zenrows_api_key,
            "url": url,
            "js_render": "false",
            "premium_proxy": "true",
            "proxy_country": "us",
        }
        return self.session.get(zenrows_url, params=zenrows_params, timeout=self.timeout)

    def _fetch_event_page(self, event_id: str) -> requests.Response:
        """Fetch the top-level event URL with unified CAPTCHA detection.

        Routes through ZenRows when configured, else via direct session. On
        a CAPTCHA response, writes reports/gotsport__<id>__unknown/intake/
        captcha_challenge.json and raises EventCaptchaGatedError so callers
        can surface the skip cleanly without marking the event scraped.
        """
        event_url = f"{self.EVENT_BASE}/{event_id}"
        if self.use_zenrows:
            response = self._make_zenrows_request(event_url)
        else:
            response = self.session.get(event_url, timeout=self.timeout)

        captcha = _extract_captcha_signals(response, fallback_target_url=event_url)
        if captcha is not None:
            artifact_path = self._write_captcha_artifact(event_id, captcha, event_url)
            raise EventCaptchaGatedError(
                provider_event_id=event_id,
                captcha_url=captcha["captcha_url"],
                sitekey=captcha["sitekey"],
                artifact_path=artifact_path,
            )
        return response

    def _write_captcha_artifact(
        self, event_id: str, captcha: dict, event_url: str
    ) -> Path:
        """Persist a captcha_challenge.json artifact alongside intake logs.

        Path matches the `reports/<event_key>/intake/` convention set by the
        Shell 01 foundation (_derive_event_key returns
        `gotsport__<id>__unknown` until Shell 02 owns the season suffix).
        """
        event_key = f"gotsport__{event_id}__unknown"
        artifact_dir = Path("reports") / event_key / "intake"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        artifact_path = artifact_dir / "captcha_challenge.json"
        payload = {
            "provider_code": self.provider_code,
            "provider_event_id": event_id,
            "event_url": event_url,
            "captcha_url": captcha["captcha_url"],
            "captcha_provider": "recaptcha_v2",
            "sitekey": captcha["sitekey"],
            "detected_at": datetime.now(timezone.utc).isoformat(),
            "via_zenrows": self.use_zenrows,
        }
        artifact_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        logger.warning(
            "[captcha_detected] event_id=%s sitekey=%s artifact=%s",
            event_id, captcha["sitekey"], artifact_path,
        )
        return artifact_path

    def extract_event_teams(self, event_id: str) -> List[str]:
        """
        Extract team IDs from an event page

        Args:
            event_id: GotSport event ID (e.g., "40550")

        Returns:
            List of team IDs found in the event
        """
        event_url = f"{self.EVENT_BASE}/{event_id}"
        team_ids: Set[str] = set()

        logger.info(f"Extracting teams from event {event_id}: {event_url}")

        for attempt in range(self.max_retries):
            try:
                response = self.session.get(event_url, timeout=self.timeout)
                response.raise_for_status()

                soup = BeautifulSoup(response.text, "html.parser")

                # Method 1: Look for team links in the HTML
                # GotSport typically uses links like /teams/{team_id} or /team/{team_id}
                team_links = soup.find_all("a", href=re.compile(r"/teams?/\d+"))
                for link in team_links:
                    href = link.get("href", "")
                    match = re.search(r"/teams?/(\d+)", href)
                    if match:
                        team_ids.add(match.group(1))

                # Method 2: Look for team IDs in data attributes
                elements_with_team_id = soup.find_all(attrs={"data-team-id": True})
                for elem in elements_with_team_id:
                    team_id = elem.get("data-team-id")
                    if team_id and team_id.isdigit():
                        team_ids.add(team_id)

                # Method 3: Look for jsonTeamRegs JSON data (primary method for GotSport events)
                scripts = soup.find_all("script")
                for script in scripts:
                    if script.string:
                        # Look for jsonTeamRegs = [...] pattern
                        # Use proper bracket matching to handle large/nested JSON arrays
                        json_match = re.search(r"jsonTeamRegs\s*=\s*(\[)", script.string, re.DOTALL)
                        if json_match:
                            try:
                                import json

                                # Find the start position
                                start_pos = json_match.start(1)
                                # Find the matching closing bracket
                                bracket_count = 0
                                in_string = False
                                escape_next = False
                                end_pos = start_pos

                                for i in range(start_pos, len(script.string)):
                                    char = script.string[i]

                                    if escape_next:
                                        escape_next = False
                                        continue

                                    if char == "\\":
                                        escape_next = True
                                        continue

                                    if char == '"' and not escape_next:
                                        in_string = not in_string
                                        continue

                                    if not in_string:
                                        if char == "[":
                                            bracket_count += 1
                                        elif char == "]":
                                            bracket_count -= 1
                                            if bracket_count == 0:
                                                end_pos = i + 1
                                                break

                                # Extract the full JSON array
                                json_str = script.string[start_pos:end_pos]
                                teams_json = json.loads(json_str)
                                for team in teams_json:
                                    team_id = str(team.get("id", ""))
                                    if team_id and team_id.isdigit():
                                        team_ids.add(team_id)
                                logger.debug(f"Extracted {len(teams_json)} teams from jsonTeamRegs")
                            except (json.JSONDecodeError, Exception) as e:
                                logger.warning(f"Failed to parse jsonTeamRegs: {e}")

                        # Also look for patterns like "team_id": 123456 or team_id: 123456
                        matches = re.findall(r'["\']?team_id["\']?\s*[:=]\s*(\d+)', script.string, re.IGNORECASE)
                        team_ids.update(matches)

                        # Also look for URLs with team IDs
                        url_matches = re.findall(r"teams?/(\d+)", script.string)
                        team_ids.update(url_matches)

                # Method 4: Look for team IDs in class names or IDs
                team_elements = soup.find_all(class_=re.compile(r"team", re.I))
                for elem in team_elements:
                    # Check if element has an ID that looks like a team ID
                    elem_id = elem.get("id", "")
                    if elem_id and elem_id.isdigit() and len(elem_id) >= 4:
                        team_ids.add(elem_id)

                if team_ids:
                    logger.info(f"Found {len(team_ids)} unique team IDs in event {event_id}")
                    break
                else:
                    logger.warning(f"No team IDs found in event {event_id} (attempt {attempt + 1})")
                    if attempt < self.max_retries - 1:
                        time.sleep(self.retry_delay)

            except requests.exceptions.HTTPError as e:
                if e.response.status_code == 404:
                    logger.error(f"Event {event_id} not found (404)")
                    return []
                if attempt < self.max_retries - 1:
                    logger.warning(f"HTTP error (attempt {attempt + 1}): {e}, retrying...")
                    time.sleep(self.retry_delay)
                    continue
                else:
                    logger.error(f"HTTP error after {self.max_retries} attempts: {e}")
                    raise

            except (RequestsSSLError, Urllib3SSLError) as e:
                if attempt < self.max_retries - 1:
                    wait_time = self.retry_delay * (2**attempt)
                    logger.warning(f"SSL error (attempt {attempt + 1}): {e}, retrying in {wait_time:.1f}s...")
                    time.sleep(wait_time)
                    self.session.close()
                    self.session = self._init_http_session()
                    continue
                else:
                    logger.error(f"SSL error after {self.max_retries} attempts: {e}")
                    raise

            except Exception as e:
                if attempt < self.max_retries - 1:
                    logger.warning(f"Error (attempt {attempt + 1}): {e}, retrying...")
                    time.sleep(self.retry_delay)
                    continue
                else:
                    logger.error(f"Error after {self.max_retries} attempts: {e}")
                    raise

        # Rate limiting
        if self.delay_min > 0 or self.delay_max > 0:
            time.sleep(random.uniform(self.delay_min, self.delay_max))

        return list(team_ids)

    def extract_event_teams_by_bracket(self, event_id: str) -> Dict[str, List[EventTeam]]:
        """
        Extract teams from an event page, organized by bracket/group

        Args:
            event_id: GotSport event ID (e.g., "40550")

        Returns:
            Dictionary mapping bracket/group names to lists of EventTeam objects
            Format: { "SUPER PRO - U9B": [EventTeam(...), ...], ... }
        """
        event_url = f"{self.EVENT_BASE}/{event_id}"
        brackets: Dict[str, List[EventTeam]] = {}

        logger.info(f"Extracting teams by bracket from event {event_id}: {event_url}")

        for attempt in range(self.max_retries):
            try:
                response = self.session.get(event_url, timeout=self.timeout)
                response.raise_for_status()

                soup = BeautifulSoup(response.text, "html.parser")

                # Look for bracket/division sections
                # GotSport typically organizes by age group and division (e.g., "SUPER PRO - U9B")

                # Method 1: Look for schedule/division headers
                # Common patterns: h3, h4, h5 with bracket names,
                # or divs with class containing "bracket", "division", "group"
                soup.find_all(
                    ["h2", "h3", "h4", "h5", "h6"],
                    string=re.compile(
                        r"(SUPER|ELITE|PRO|BLACK|GOLD|SILVER|BRONZE|PREMIER|CHAMPIONSHIP|DIVISION|GROUP|BRACKET)",
                        re.IGNORECASE,
                    ),
                )

                # Method 2: Look for age group headers (U7, U8, U9, etc.)
                soup.find_all(["h2", "h3", "h4"], string=re.compile(r"U\d+\s+(Schedule|Boys|Girls|B|G)", re.IGNORECASE))

                # Method 3: Look for division/bracket containers
                # Common class names: bracket, division, group, pool, flight
                soup.find_all(class_=re.compile(r"(bracket|division|group|pool|flight|schedule)", re.I))

                # Method 4: Parse the structure - look for sections that contain team lists
                # GotSport often has structure like:
                # <div class="schedule-section">
                #   <h3>SUPER PRO - U9B</h3>
                #   <div>...teams...</div>
                # </div>

                # Primary method: Extract from jsonTeamRegs and organize by bracket
                # Look for jsonTeamRegs JSON data
                scripts = soup.find_all("script")
                teams_data = []

                for script in scripts:
                    if script.string:
                        # Look for jsonTeamRegs = [...] pattern
                        # Use proper bracket matching to handle large/nested JSON arrays
                        json_match = re.search(r"jsonTeamRegs\s*=\s*(\[)", script.string, re.DOTALL)
                        if json_match:
                            try:
                                import json

                                # Find the start position
                                start_pos = json_match.start(1)
                                # Find the matching closing bracket
                                bracket_count = 0
                                in_string = False
                                escape_next = False
                                end_pos = start_pos

                                for i in range(start_pos, len(script.string)):
                                    char = script.string[i]

                                    if escape_next:
                                        escape_next = False
                                        continue

                                    if char == "\\":
                                        escape_next = True
                                        continue

                                    if char == '"' and not escape_next:
                                        in_string = not in_string
                                        continue

                                    if not in_string:
                                        if char == "[":
                                            bracket_count += 1
                                        elif char == "]":
                                            bracket_count -= 1
                                            if bracket_count == 0:
                                                end_pos = i + 1
                                                break

                                # Extract the full JSON array
                                json_str = script.string[start_pos:end_pos]
                                teams_json = json.loads(json_str)
                                teams_data = teams_json
                                logger.debug(f"Found {len(teams_json)} teams in jsonTeamRegs")
                                break
                            except (json.JSONDecodeError, Exception) as e:
                                logger.warning(f"Failed to parse jsonTeamRegs: {e}")

                # If we found teams in jsonTeamRegs, organize them
                if teams_data:
                    # Look for bracket/division information in the HTML structure
                    # GotSport typically shows brackets like "SUPER PRO - U9B" in headers
                    all_headers = soup.find_all(["h2", "h3", "h4", "h5", "h6", "b", "strong"])
                    bracket_map = {}  # Map team IDs to bracket names

                    # Try to find bracket names and associate with teams
                    # Look for headers that contain bracket information
                    for header in all_headers:
                        header_text = header.get_text(strip=True)
                        # Look for bracket patterns like "SUPER PRO - U9B", "GOLD - U8B", etc.
                        if re.search(
                            r"(SUPER|ELITE|PRO|BLACK|GOLD|SILVER|BRONZE|PREMIER|CHAMPIONSHIP)", header_text, re.I
                        ):
                            # This looks like a bracket header
                            # Look for team links or data near this header
                            parent = header.find_parent()
                            if parent:
                                # Look for team IDs in nearby elements (within the same section)
                                # Check siblings and children
                                team_links = parent.find_all("a", href=re.compile(r"/teams?/\d+"))
                                for link in team_links:
                                    href = link.get("href", "")
                                    match = re.search(r"/teams?/(\d+)", href)
                                    if match:
                                        bracket_map[match.group(1)] = header_text

                                # Also check in the same container for any team references
                                # Look for data attributes or IDs that might reference teams
                                team_refs = parent.find_all(attrs={"data-team-id": True})
                                for ref in team_refs:
                                    team_id = ref.get("data-team-id")
                                    if team_id and team_id.isdigit():
                                        bracket_map[team_id] = header_text

                    # Also look for bracket names in button text or schedule links
                    # GotSport often uses buttons for bracket selection
                    bracket_buttons = soup.find_all(
                        ["button", "a"], string=re.compile(r"(SUPER|ELITE|PRO|BLACK|GOLD|SILVER|BRONZE).*U\d+", re.I)
                    )
                    for button in bracket_buttons:
                        bracket_text = button.get_text(strip=True)
                        if bracket_text:
                            # Find teams associated with this bracket button
                            # Look in the same section or following content
                            parent = button.find_parent()
                            if parent:
                                team_links = parent.find_all("a", href=re.compile(r"/teams?/\d+"))
                                for link in team_links:
                                    href = link.get("href", "")
                                    match = re.search(r"/teams?/(\d+)", href)
                                    if match:
                                        if match.group(1) not in bracket_map:
                                            bracket_map[match.group(1)] = bracket_text

                    # Organize teams by bracket
                    for team in teams_data:
                        team_id = str(team.get("id", ""))
                        if not team_id or not team_id.isdigit():
                            continue

                        # Try to find bracket name
                        bracket_name = bracket_map.get(team_id)
                        if not bracket_name:
                            # Try to infer from team data
                            age_group = team.get("display_age_group", "")
                            gender = team.get("display_gender", "")
                            if age_group and gender:
                                # Try to find matching bracket
                                for header_text in bracket_map.values():
                                    if age_group in header_text and (
                                        gender[0].upper() in header_text or "B" in header_text or "G" in header_text
                                    ):
                                        bracket_name = header_text
                                        break

                        if not bracket_name:
                            # Create bracket name from team data
                            age_group = team.get("display_age_group", "Unknown")
                            gender_code = (
                                "B"
                                if "Male" in team.get("display_gender", "") or team.get("gender", "").lower() == "m"
                                else "G"
                            )
                            bracket_name = f"{age_group}{gender_code}"

                        if bracket_name not in brackets:
                            brackets[bracket_name] = []

                        # Extract team info
                        team_name = team.get("full_name", f"Team {team_id}")
                        gender_display = team.get("display_gender", "")
                        gender_code = "M" if "Male" in gender_display or team.get("gender", "").lower() == "m" else "F"

                        # Determine ACTUAL age group (not bracket age)
                        # Method 1: Try to infer from team name (look for birth year)
                        actual_age_group = None
                        birth_year_match = re.search(r"\b(20\d{2})\b", team_name)
                        if birth_year_match:
                            birth_year = int(birth_year_match.group(1))
                            # Calculate age group: U11 = 2015, U12 = 2014, etc.
                            # Age group is the year they turn that age, not current age
                            current_year = CURRENT_YEAR
                            # For 2025: U11 = 2015 birth year, U12 = 2014 birth year
                            # Formula: age_group = current_year - birth_year + 1
                            age_group_number = current_year - birth_year + 1
                            if 7 <= age_group_number <= 19:  # Valid age range
                                actual_age_group = f"U{age_group_number}"

                        # Method 2: Use display_age_group if it seems reasonable
                        # But be careful - it might be the bracket age, not actual age
                        if not actual_age_group:
                            display_age = team.get("display_age_group", "")
                            # Only trust it if team name doesn't contradict it
                            if display_age and not birth_year_match:
                                actual_age_group = display_age

                        # Method 3: Use numeric age field if available (might be actual age)
                        if not actual_age_group:
                            numeric_age = team.get("age")
                            if numeric_age and isinstance(numeric_age, int) and 7 <= numeric_age <= 19:
                                actual_age_group = f"U{numeric_age}"

                        # Fallback: Use bracket age (not ideal, but better than nothing)
                        if not actual_age_group:
                            bracket_age_match = re.search(r"U(\d+)", bracket_name, re.I)
                            if bracket_age_match:
                                actual_age_group = f"U{bracket_age_match.group(1)}"
                            else:
                                actual_age_group = "Unknown"

                        # Determine if team is playing up
                        playing_up = False
                        if actual_age_group and bracket_name:
                            # Extract age number from bracket name (e.g., "U12B" -> 12)
                            bracket_age_match = re.search(r"U(\d+)", bracket_name, re.I)
                            actual_age_match = re.search(r"U(\d+)", actual_age_group, re.I)

                            if bracket_age_match and actual_age_match:
                                bracket_age = int(bracket_age_match.group(1))
                                actual_age = int(actual_age_match.group(1))
                                # Playing up if bracket age > actual age
                                playing_up = bracket_age > actual_age

                        brackets[bracket_name].append(
                            EventTeam(
                                team_id=team_id,
                                team_name=team_name,
                                bracket_name=bracket_name,
                                age_group=actual_age_group,  # Use actual age group, not bracket age
                                gender=gender_code,
                                division=bracket_name,
                                playing_up=playing_up,
                            )
                        )

                # Fallback: Try to find bracket structure by looking for headers followed by team lists
                if not brackets:
                    current_bracket = None
                    all_headers = soup.find_all(["h2", "h3", "h4", "h5", "h6"])
                    for header in all_headers:
                        header_text = header.get_text(strip=True)

                        # Check if this looks like a bracket/division name
                        if re.search(r"(SUPER|ELITE|PRO|BLACK|GOLD|SILVER|BRONZE|U\d+)", header_text, re.I):
                            current_bracket = header_text
                            if current_bracket not in brackets:
                                brackets[current_bracket] = []

                            # Look for teams in the following siblings or parent container
                            parent = header.find_parent()
                            if parent:
                                # Look for team links in this section
                                team_links = parent.find_all("a", href=re.compile(r"/teams?/\d+"))
                                for link in team_links:
                                    href = link.get("href", "")
                                    match = re.search(r"/teams?/(\d+)", href)
                                    if match:
                                        team_id = match.group(1)
                                        team_name = (
                                            link.get_text(strip=True) or link.get("title", "") or f"Team {team_id}"
                                        )

                                        # Extract age_group - prioritize birth year in team name
                                        age_group = None
                                        gender = None

                                        # Method 1: Extract birth year from team name (priority)
                                        birth_year_match = re.search(r"\b(20\d{2})\b", team_name)
                                        if birth_year_match:
                                            birth_year = int(birth_year_match.group(1))
                                            current_year = CURRENT_YEAR
                                            age_group_number = current_year - birth_year + 1
                                            if 7 <= age_group_number <= 19:
                                                age_group = f"U{age_group_number}"

                                        # Method 2: Fall back to bracket/header age
                                        if not age_group and re.search(r"U(\d+)", header_text, re.I):
                                            age_match = re.search(r"U(\d+)", header_text, re.I)
                                            age_group = f"U{age_match.group(1)}"

                                        if re.search(r"\b(B|Boys|M|Male)\b", header_text, re.I):
                                            gender = "M"
                                        elif re.search(r"\b(G|Girls|F|Female)\b", header_text, re.I):
                                            gender = "F"

                                        brackets[current_bracket].append(
                                            EventTeam(
                                                team_id=team_id,
                                                team_name=team_name,
                                                bracket_name=current_bracket,
                                                age_group=age_group,
                                                gender=gender,
                                                division=current_bracket,
                                            )
                                        )

                # If we didn't find organized brackets, try a simpler approach:
                # Extract all teams and try to infer brackets from the page structure
                if not brackets:
                    logger.debug("No bracket structure found, extracting all teams...")
                    self.extract_event_teams(event_id)

                    # Try to find any bracket/division context for teams
                    # Look for team links and their surrounding context
                    team_links = soup.find_all("a", href=re.compile(r"/teams?/\d+"))
                    for link in team_links:
                        href = link.get("href", "")
                        match = re.search(r"/teams?/(\d+)", href)
                        if match:
                            team_id = match.group(1)
                            team_name = link.get_text(strip=True) or f"Team {team_id}"

                            # Try to find the nearest bracket/division header
                            bracket_name = "Unknown Bracket"
                            parent = link.find_parent()
                            if parent:
                                # Look for headers in parent chain
                                for ancestor in parent.parents:
                                    header = ancestor.find(["h2", "h3", "h4", "h5", "h6"])
                                    if header:
                                        header_text = header.get_text(strip=True)
                                        if header_text and len(header_text) < 100:  # Reasonable header length
                                            bracket_name = header_text
                                            break

                            if bracket_name not in brackets:
                                brackets[bracket_name] = []

                            # Extract age_group from team name's birth year (priority)
                            age_group = None
                            gender = None
                            birth_year_match = re.search(r"\b(20\d{2})\b", team_name)
                            if birth_year_match:
                                birth_year = int(birth_year_match.group(1))
                                current_year = CURRENT_YEAR
                                age_group_number = current_year - birth_year + 1
                                if 7 <= age_group_number <= 19:
                                    age_group = f"U{age_group_number}"

                            # Fall back to bracket name for age/gender
                            if not age_group and re.search(r"U(\d+)", bracket_name, re.I):
                                age_match = re.search(r"U(\d+)", bracket_name, re.I)
                                age_group = f"U{age_match.group(1)}"
                            if re.search(r"\b(B|Boys|M|Male)\b", bracket_name, re.I):
                                gender = "M"
                            elif re.search(r"\b(G|Girls|F|Female)\b", bracket_name, re.I):
                                gender = "F"

                            brackets[bracket_name].append(
                                EventTeam(
                                    team_id=team_id,
                                    team_name=team_name,
                                    bracket_name=bracket_name,
                                    age_group=age_group,
                                    gender=gender,
                                    division=bracket_name,
                                )
                            )

                if brackets:
                    total_teams = sum(len(teams) for teams in brackets.values())
                    logger.info(f"Found {total_teams} teams in {len(brackets)} brackets for event {event_id}")
                    break
                else:
                    logger.warning(f"No teams found in event {event_id} (attempt {attempt + 1})")
                    if attempt < self.max_retries - 1:
                        time.sleep(self.retry_delay)

            except requests.exceptions.HTTPError as e:
                if e.response.status_code == 404:
                    logger.error(f"Event {event_id} not found (404)")
                    return {}
                if attempt < self.max_retries - 1:
                    logger.warning(f"HTTP error (attempt {attempt + 1}): {e}, retrying...")
                    time.sleep(self.retry_delay)
                    continue
                else:
                    logger.error(f"HTTP error after {self.max_retries} attempts: {e}")
                    raise

            except (RequestsSSLError, Urllib3SSLError) as e:
                if attempt < self.max_retries - 1:
                    wait_time = self.retry_delay * (2**attempt)
                    logger.warning(f"SSL error (attempt {attempt + 1}): {e}, retrying in {wait_time:.1f}s...")
                    time.sleep(wait_time)
                    self.session.close()
                    self.session = self._init_http_session()
                    continue
                else:
                    logger.error(f"SSL error after {self.max_retries} attempts: {e}")
                    raise

            except Exception as e:
                if attempt < self.max_retries - 1:
                    logger.warning(f"Error (attempt {attempt + 1}): {e}, retrying...")
                    time.sleep(self.retry_delay)
                    continue
                else:
                    logger.error(f"Error after {self.max_retries} attempts: {e}")
                    raise

        # Rate limiting
        if self.delay_min > 0 or self.delay_max > 0:
            time.sleep(random.uniform(self.delay_min, self.delay_max))

        return brackets

    def extract_team_ids_from_schedules(self, event_id: str) -> Set[str]:
        """
        Extract team IDs from schedule pages (more reliable than event registration page)

        Args:
            event_id: GotSport event ID

        Returns:
            Set of team IDs found in schedule pages
        """
        team_ids: Set[str] = set()
        event_url = f"{self.EVENT_BASE}/{event_id}"

        try:
            response = self.session.get(event_url, timeout=self.timeout)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")

            # Find all schedule links
            schedule_links = soup.find_all("a", href=re.compile(r"/schedules\?.*"))

            for link in schedule_links:
                href = link.get("href", "")
                # Schedule URLs can be:
                # /org_event/events/{event_id}/schedules?age=12&gender=m
                # /org_event/events/{event_id}/schedules?group=366834
                if "schedules?" in href:
                    # Make absolute URL if needed
                    if href.startswith("/"):
                        schedule_url = f"{self.BASE_URL}{href}"
                    else:
                        schedule_url = href

                    try:
                        schedule_response = self.session.get(schedule_url, timeout=self.timeout)
                        schedule_response.raise_for_status()
                        schedule_soup = BeautifulSoup(schedule_response.text, "html.parser")

                        # Extract team IDs from schedule page URLs
                        # Look for links like: schedules?team=3616623
                        team_urls = schedule_soup.find_all("a", href=re.compile(r"schedules\?team=\d+"))
                        for team_link in team_urls:
                            match = re.search(r"team=(\d+)", team_link.get("href", ""))
                            if match:
                                team_ids.add(match.group(1))

                        # Also look in the HTML content for team IDs
                        # Some pages have team IDs in data attributes or other places
                        all_links = schedule_soup.find_all("a", href=True)
                        for link in all_links:
                            href = link.get("href", "")
                            # Look for any URL pattern with team ID
                            match = re.search(r"team[=_](\d+)", href, re.I)
                            if match:
                                team_ids.add(match.group(1))

                        time.sleep(0.5)  # Rate limiting between schedule pages
                    except Exception as e:
                        logger.debug(f"Error fetching schedule page {schedule_url}: {e}")
                        continue

            logger.info(f"Extracted {len(team_ids)} team IDs from schedule pages")
        except Exception as e:
            logger.warning(f"Error extracting team IDs from schedules: {e}")

        return team_ids

    def extract_event_dates(self, event_id: str) -> Optional[Tuple[date, date]]:
        """
        Extract actual event start and end dates from event page or schedule pages

        Args:
            event_id: GotSport event ID

        Returns:
            Tuple of (start_date, end_date) or None if not found
        """
        event_url = f"{self.EVENT_BASE}/{event_id}"
        dates_found = []

        try:
            response = self.session.get(event_url, timeout=self.timeout)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")

            # Method 1: Look for date text in the event description/header
            # Common patterns: "December 5-7, 2025", "Dec 5-7, 2025", "12/5/2025 - 12/7/2025"
            date_patterns = [
                r"([A-Za-z]+)\s+(\d+)[-–]\s*(\d+),\s*(\d{4})",  # "December 5-7, 2025"
                r"([A-Za-z]+)\s+(\d+)\s+through\s+([A-Za-z]+)?\s*(\d+),\s*(\d{4})",  # "December 5 through 7, 2025"
                r"(\d{1,2})/(\d{1,2})/(\d{4})\s*[-–]\s*(\d{1,2})/(\d{1,2})/(\d{4})",  # "12/5/2025 - 12/7/2025"
            ]

            # Search in main content area
            main_content = soup.find("main") or soup.find("body")
            if main_content:
                text = main_content.get_text()
                for pattern in date_patterns:
                    match = re.search(pattern, text, re.IGNORECASE)
                    if match:
                        # Try to parse the dates
                        try:
                            if len(match.groups()) == 4:  # "December 5-7, 2025"
                                month_name = match.group(1)
                                start_day = int(match.group(2))
                                end_day = int(match.group(3))
                                year = int(match.group(4))

                                month_map = {
                                    "january": 1,
                                    "february": 2,
                                    "march": 3,
                                    "april": 4,
                                    "may": 5,
                                    "june": 6,
                                    "july": 7,
                                    "august": 8,
                                    "september": 9,
                                    "october": 10,
                                    "november": 11,
                                    "december": 12,
                                    "jan": 1,
                                    "feb": 2,
                                    "mar": 3,
                                    "apr": 4,
                                    "jun": 6,
                                    "jul": 7,
                                    "aug": 8,
                                    "sep": 9,
                                    "oct": 10,
                                    "nov": 11,
                                    "dec": 12,
                                }
                                month = month_map.get(month_name.lower()[:3])
                                if month:
                                    start_date = date(year, month, start_day)
                                    end_date = date(year, month, end_day)
                                    return (start_date, end_date)
                            elif len(match.groups()) == 6:  # "12/5/2025 - 12/7/2025"
                                start_month = int(match.group(1))
                                start_day = int(match.group(2))
                                start_year = int(match.group(3))
                                end_month = int(match.group(4))
                                end_day = int(match.group(5))
                                end_year = int(match.group(6))
                                start_date = date(start_year, start_month, start_day)
                                end_date = date(end_year, end_month, end_day)
                                return (start_date, end_date)
                        except (ValueError, KeyError):
                            continue

            # Method 2: Extract dates from schedule pages (more reliable)
            # Get dates from actual game schedules
            schedule_links = soup.find_all("a", href=re.compile(r"/schedules\?.*"))
            schedule_urls = set()

            for link in schedule_links:
                href = link.get("href", "")
                if "schedules?" in href:
                    if href.startswith("/"):
                        schedule_url = f"{self.BASE_URL}{href}"
                    else:
                        schedule_url = href
                    schedule_urls.add(schedule_url)

            # Sample a few schedule pages to find date range
            for schedule_url in list(schedule_urls)[:3]:  # Check first 3 schedule pages
                try:
                    schedule_response = self.session.get(schedule_url, timeout=self.timeout)
                    schedule_response.raise_for_status()
                    schedule_soup = BeautifulSoup(schedule_response.text, "html.parser")

                    # Look for date headers or date cells in tables
                    # Dates appear in format "Nov 28, 2025" or "Friday, Nov 28, 2025"
                    date_elements = schedule_soup.find_all(string=re.compile(r"[A-Za-z]+\s+\d+,\s+\d{4}"))
                    for date_text in date_elements:
                        date_match = re.search(r"([A-Za-z]+)\s+(\d+),\s+(\d{4})", date_text)
                        if date_match:
                            month_name = date_match.group(1)
                            day = int(date_match.group(2))
                            year = int(date_match.group(3))

                            month_map = {
                                "jan": 1,
                                "feb": 2,
                                "mar": 3,
                                "apr": 4,
                                "may": 5,
                                "jun": 6,
                                "jul": 7,
                                "aug": 8,
                                "sep": 9,
                                "oct": 10,
                                "nov": 11,
                                "dec": 12,
                            }
                            month = month_map.get(month_name.lower()[:3])
                            if month:
                                try:
                                    game_date = date(year, month, day)
                                    dates_found.append(game_date)
                                except ValueError:
                                    continue

                    time.sleep(0.3)  # Rate limiting
                except Exception as e:
                    logger.debug(f"Error checking schedule page for dates: {e}")
                    continue

            # If we found dates from schedule pages, return the range
            if dates_found:
                start_date = min(dates_found)
                end_date = max(dates_found)
                return (start_date, end_date)

        except Exception as e:
            logger.debug(f"Error extracting event dates: {e}")

        return None

    def _resolve_api_team_id_from_event_page(
        self, event_id: str, registration_id: str, team_name: Optional[str] = None
    ) -> Optional[str]:
        """
        Resolve GotSport API team ID from event registration ID by following the team's event page.

        Uses multiple strategies:
        1. Look for rankings link on team's event schedule page
        2. Look for direct /teams/{id} links (API team IDs)
        3. Look for team_id in JavaScript/JSON data on the page
        4. Try the GotSport API directly with the registration ID (it might work)

        Args:
            event_id: GotSport event ID
            registration_id: Event registration ID (from schedule page links)
            team_name: Optional team name for logging

        Returns:
            API team ID if found, None otherwise
        """
        try:
            # Step 1: Go to team's event page
            team_event_url = f"{self.EVENT_BASE}/{event_id}/schedules?team={registration_id}"
            response = self.session.get(team_event_url, timeout=self.timeout)
            response.raise_for_status()

            soup = BeautifulSoup(response.text, "html.parser")

            # Strategy 1: Find "view rankings" link (most reliable)
            rankings_links = soup.find_all("a", href=re.compile(r"rankings\.gotsport\.com/teams/\d+", re.I))

            if not rankings_links:
                # Try alternative patterns - might be in text like "View Rankings"
                all_links = soup.find_all("a", href=True)
                for link in all_links:
                    href = link.get("href", "")
                    if "rankings" in href.lower() and "/teams/" in href:
                        rankings_links.append(link)
                        break

            for link in rankings_links:
                href = link.get("href", "")
                # Extract team ID from rankings URL: rankings.gotsport.com/teams/{id}
                match = re.search(r"rankings\.gotsport\.com/teams/(\d+)", href, re.I)
                if match:
                    api_team_id = match.group(1)
                    logger.debug(
                        f"Resolved API team ID {api_team_id} from rankings link for {team_name or registration_id}"
                    )
                    return api_team_id

            # Strategy 2: Look for direct /teams/{id} links (API team IDs, not event registration)
            # These are links to the team's main page, not event-specific pages
            team_links = soup.find_all("a", href=re.compile(r"system\.gotsport\.com/teams/\d+", re.I))
            for link in team_links:
                href = link.get("href", "")
                match = re.search(r"/teams/(\d+)", href)
                if match:
                    api_team_id = match.group(1)
                    # Validate this is an API team ID (not the same as registration_id)
                    if api_team_id != registration_id:
                        logger.debug(
                            f"Resolved API team ID {api_team_id} from system.gotsport.com "
                            f"link for {team_name or registration_id}"
                        )
                        return api_team_id

            # Strategy 3: Look for team_id in JavaScript/JSON data on the page
            scripts = soup.find_all("script")
            for script in scripts:
                if script.string:
                    # Look for patterns like "team_id": 123456 or team_id = 123456
                    patterns = [
                        r'"team_id"\s*:\s*(\d+)',
                        r"'team_id'\s*:\s*(\d+)",
                        r"team_id\s*=\s*(\d+)",
                        r'"rankings_team_id"\s*:\s*(\d+)',
                        r'"api_team_id"\s*:\s*(\d+)',
                    ]
                    for pattern in patterns:
                        matches = re.findall(pattern, script.string, re.IGNORECASE)
                        for api_team_id in matches:
                            # Validate it's different from registration_id (likely the API team ID)
                            if api_team_id != registration_id and len(api_team_id) >= 5:
                                logger.debug(
                                    f"Resolved API team ID {api_team_id} from script data "
                                    f"for {team_name or registration_id}"
                                )
                                return api_team_id

            # Strategy 4: Try the GotSport API directly with the registration ID
            # Some registration IDs might actually be valid API team IDs
            try:
                api_url = f"https://system.gotsport.com/api/v1/teams/{registration_id}/matches"
                api_response = self.session.get(api_url, params={"past": "true"}, timeout=10)
                if api_response.status_code == 200:
                    # The registration ID is also a valid API team ID!
                    logger.debug(
                        f"Registration ID {registration_id} is a valid API team ID for {team_name or registration_id}"
                    )
                    return registration_id
            except Exception:
                pass  # API call failed, continue

            logger.debug(
                f"No API team ID found for team {team_name or registration_id} (registration_id={registration_id})"
            )
            return None

        except Exception as e:
            logger.debug(f"Error resolving API team ID from event page for {team_name or registration_id}: {e}")
            return None

    def scrape_games_from_schedule_pages(
        self, event_id: str, event_name: Optional[str] = None, since_date: Optional[datetime] = None
    ) -> List[GameData]:
        """
        Scrape games directly from schedule pages (bypasses API team IDs)

        Args:
            event_id: GotSport event ID
            event_name: Optional event name for metadata
            since_date: Only scrape games after this date

        Returns:
            List of GameData objects from schedule pages
        """
        games: List[GameData] = []

        logger.info(f"Scraping games from schedule pages for event {event_id}")

        try:
            # Get the main event page to find all schedule links. Routes
            # through ZenRows when configured and detects CAPTCHA; raises
            # EventCaptchaGatedError on a gated event.
            response = self._fetch_event_page(event_id)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")

            # Find all schedule links (age/gender combinations and group-specific)
            schedule_links = soup.find_all("a", href=re.compile(r"/schedules\?.*"))
            schedule_urls = set()

            for link in schedule_links:
                href = link.get("href", "")
                if "schedules?" in href:
                    if href.startswith("/"):
                        schedule_url = f"{self.BASE_URL}{href}"
                    else:
                        schedule_url = href
                    schedule_urls.add(schedule_url)

            # Limit schedule pages to prevent timeout on large events
            # Default of 25 captures most tournaments (U9-U19 both genders = ~22 brackets)
            max_schedule_pages = int(os.getenv("GOTSPORT_MAX_SCHEDULE_PAGES", "25"))
            if len(schedule_urls) > max_schedule_pages:
                logger.warning(f"Event has {len(schedule_urls)} schedule pages, limiting to {max_schedule_pages}")
                schedule_urls = list(schedule_urls)[:max_schedule_pages]
            else:
                schedule_urls = list(schedule_urls)

            logger.info(f"Scraping {len(schedule_urls)} schedule pages")

            # Cache for resolved API team IDs (registration_id -> api_team_id)
            # This avoids hitting the same team's event page multiple times
            api_team_id_cache: Dict[str, Optional[str]] = {}

            # Extract API team IDs and team name mapping from event page
            # IMPORTANT: jsonTeamRegs contains 'id' (event registration ID) and may contain
            # 'team_id' (API team ID). We prefer 'team_id' when available.
            teams_by_name: Dict[str, str] = {}  # team_name -> api_team_id
            registration_to_api: Dict[str, str] = {}  # registration_id -> api_team_id (if different)
            try:
                scripts = soup.find_all("script")
                for script in scripts:
                    if script.string:
                        json_match = re.search(r"jsonTeamRegs\s*=\s*(\[)", script.string, re.DOTALL)
                        if json_match:
                            import json

                            start_pos = json_match.start(1)
                            bracket_count = 0
                            in_string = False
                            escape_next = False
                            end_pos = start_pos

                            for i in range(start_pos, len(script.string)):
                                char = script.string[i]
                                if escape_next:
                                    escape_next = False
                                    continue
                                if char == "\\":
                                    escape_next = True
                                    continue
                                if char == '"' and not escape_next:
                                    in_string = not in_string
                                    continue
                                if not in_string:
                                    if char == "[":
                                        bracket_count += 1
                                    elif char == "]":
                                        bracket_count -= 1
                                        if bracket_count == 0:
                                            end_pos = i + 1
                                            break

                            json_str = script.string[start_pos:end_pos]
                            teams_json = json.loads(json_str)
                            for team in teams_json:
                                # 'id' is the event registration ID
                                registration_id = str(team.get("id", ""))
                                # Look for API team ID fields (preferred)
                                api_team_id = None
                                for field in ["team_id", "rankings_team_id", "api_team_id", "gotsport_team_id"]:
                                    if team.get(field):
                                        api_team_id = str(team.get(field))
                                        break

                                team_name = team.get("full_name", "") or team.get("name", "")

                                if team_name:
                                    normalized_name = " ".join(team_name.split()).lower()
                                    # Prefer API team ID if available, otherwise use registration ID
                                    if api_team_id and api_team_id.isdigit():
                                        teams_by_name[normalized_name] = api_team_id
                                        if registration_id and registration_id != api_team_id:
                                            registration_to_api[registration_id] = api_team_id
                                    elif registration_id and registration_id.isdigit():
                                        teams_by_name[normalized_name] = registration_id

                            # Log what we found
                            api_ids_found = len(registration_to_api)
                            logger.debug(
                                f"Extracted {len(teams_by_name)} teams from jsonTeamRegs "
                                f"({api_ids_found} with distinct API team IDs)"
                            )
            except Exception as e:
                logger.warning(f"Error extracting teams from jsonTeamRegs: {e}")

            # Scrape games from each schedule page
            # Delay between pages from environment (default: 0.1s for aggressive scraping)
            page_delay = float(os.getenv("GOTSPORT_PAGE_DELAY", "0.1"))

            for idx, schedule_url in enumerate(schedule_urls):
                try:
                    schedule_games = self._parse_games_from_schedule_page(
                        schedule_url,
                        event_id,
                        event_name,
                        since_date,
                        teams_by_name,
                        api_team_id_cache,
                        registration_to_api,
                    )
                    games.extend(schedule_games)
                    logger.debug(
                        f"Found {len(schedule_games)} games from {schedule_url} ({idx + 1}/{len(schedule_urls)})"
                    )
                    if page_delay > 0:
                        time.sleep(page_delay)
                except Exception as e:
                    logger.warning(f"Error parsing schedule page {schedule_url}: {e}")
                    continue

            # Log resolution summary
            resolved_count = sum(1 for v in api_team_id_cache.values() if v is not None)
            unresolved_count = sum(1 for v in api_team_id_cache.values() if v is None)
            logger.info(f"Total games scraped from schedule pages: {len(games)}")
            logger.info(
                f"Team ID resolution: {resolved_count} resolved, {unresolved_count} unresolved (using registration IDs)"
            )
            if unresolved_count > 0:
                logger.warning(
                    "Some teams used registration IDs instead of API team IDs - these may not match in the database"
                )
        except EventCaptchaGatedError:
            # CAPTCHA is a retryable state — surface to caller so the event
            # is not marked scraped and the artifact is preserved.
            raise
        except Exception as e:
            logger.error(f"Error scraping games from schedule pages: {e}")

        return games

    def _parse_games_from_schedule_page(
        self,
        schedule_url: str,
        event_id: str,
        event_name: Optional[str],
        since_date: Optional[datetime],
        teams_by_name: Optional[Dict[str, str]] = None,
        api_team_id_cache: Optional[Dict[str, Optional[str]]] = None,
        registration_to_api: Optional[Dict[str, str]] = None,
    ) -> List[GameData]:
        """Parse games from a single schedule page"""
        if api_team_id_cache is None:
            api_team_id_cache = {}
        if teams_by_name is None:
            teams_by_name = {}
        if registration_to_api is None:
            registration_to_api = {}

        games: List[GameData] = []

        try:
            response = self.session.get(schedule_url, timeout=self.timeout)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")

            # Find all game tables (there may be multiple tables for different dates/brackets)
            tables = soup.find_all("table")

            for table in tables:
                # Find table headers to identify columns
                header_row = table.find("thead")
                if not header_row:
                    header_row = table.find("tr")

                if not header_row:
                    continue

                # Get column indices
                headers = [th.get_text(strip=True).lower() for th in header_row.find_all(["th", "td"])]

                # Find column indices
                try:
                    headers.index("match #")
                except ValueError:
                    pass

                try:
                    time_col = headers.index("time")
                except ValueError:
                    time_col = None

                try:
                    home_col = headers.index("home team")
                except ValueError:
                    home_col = None

                try:
                    results_col = headers.index("results")
                except ValueError:
                    results_col = None

                try:
                    away_col = headers.index("away team")
                except ValueError:
                    away_col = None

                try:
                    location_col = headers.index("location")
                except ValueError:
                    location_col = None

                try:
                    division_col = headers.index("division")
                except ValueError:
                    division_col = None

                # If we don't have the required columns, skip this table
                if home_col is None or away_col is None:
                    continue

                # Parse game rows
                rows = table.find_all("tr")[1:]  # Skip header row

                for row in rows:
                    cells = row.find_all(["td", "th"])
                    if len(cells) < max(filter(None, [home_col, away_col, results_col])):
                        continue

                    try:
                        # Extract home team
                        home_cell = cells[home_col] if home_col is not None and home_col < len(cells) else None
                        home_team_name = home_cell.get_text(strip=True) if home_cell else None
                        home_team_id = None
                        if home_cell:
                            # Try to get API team ID from link (might be /teams/{id} or team={id})
                            home_link = home_cell.find("a")
                            if home_link:
                                href = home_link.get("href", "")
                                # Check for /teams/{id} pattern (API team ID) - this is the actual API team ID
                                api_match = re.search(r"/teams?/(\d+)", href)
                                if api_match:
                                    home_team_id = api_match.group(1)
                                else:
                                    # Check for team={id} pattern (event registration ID)
                                    reg_match = re.search(r"team=(\d+)", href)
                                    if reg_match:
                                        reg_id = reg_match.group(1)
                                        # Priority 1: Check registration_to_api mapping (from jsonTeamRegs)
                                        if reg_id in registration_to_api:
                                            home_team_id = registration_to_api[reg_id]
                                            api_team_id_cache[reg_id] = home_team_id
                                        # Priority 2: Check cache
                                        elif reg_id in api_team_id_cache:
                                            home_team_id = api_team_id_cache[reg_id]
                                        # Priority 3: Skip expensive resolution if configured (MAJOR PERFORMANCE FIX)
                                        elif self.skip_team_id_resolution:
                                            # Use registration ID directly - faster but may not match DB
                                            home_team_id = reg_id
                                            api_team_id_cache[reg_id] = reg_id
                                        else:
                                            # Priority 4: Resolve API team ID by following the team's event page (SLOW!)
                                            home_team_id = self._resolve_api_team_id_from_event_page(
                                                event_id, reg_id, home_team_name
                                            )
                                            api_team_id_cache[reg_id] = home_team_id

                                        if not home_team_id:
                                            # Priority 5: Fallback to name-based mapping
                                            if teams_by_name and home_team_name:
                                                normalized_name = " ".join(home_team_name.split()).lower()
                                                home_team_id = teams_by_name.get(normalized_name)
                                            # Last resort: use registration ID
                                            if not home_team_id:
                                                home_team_id = reg_id

                        # Extract away team
                        away_cell = cells[away_col] if away_col is not None and away_col < len(cells) else None
                        away_team_name = away_cell.get_text(strip=True) if away_cell else None
                        away_team_id = None
                        if away_cell:
                            # Try to get API team ID from link (might be /teams/{id} or team={id})
                            away_link = away_cell.find("a")
                            if away_link:
                                href = away_link.get("href", "")
                                # Check for /teams/{id} pattern (API team ID) - this is the actual API team ID
                                api_match = re.search(r"/teams?/(\d+)", href)
                                if api_match:
                                    away_team_id = api_match.group(1)
                                else:
                                    # Check for team={id} pattern (event registration ID)
                                    reg_match = re.search(r"team=(\d+)", href)
                                    if reg_match:
                                        reg_id = reg_match.group(1)
                                        # Priority 1: Check registration_to_api mapping (from jsonTeamRegs)
                                        if reg_id in registration_to_api:
                                            away_team_id = registration_to_api[reg_id]
                                            api_team_id_cache[reg_id] = away_team_id
                                        # Priority 2: Check cache
                                        elif reg_id in api_team_id_cache:
                                            away_team_id = api_team_id_cache[reg_id]
                                        # Priority 3: Skip expensive resolution if configured (MAJOR PERFORMANCE FIX)
                                        elif self.skip_team_id_resolution:
                                            # Use registration ID directly - faster but may not match DB
                                            away_team_id = reg_id
                                            api_team_id_cache[reg_id] = reg_id
                                        else:
                                            # Priority 4: Resolve API team ID by following the team's event page (SLOW!)
                                            away_team_id = self._resolve_api_team_id_from_event_page(
                                                event_id, reg_id, away_team_name
                                            )
                                            api_team_id_cache[reg_id] = away_team_id

                                        if not away_team_id:
                                            # Priority 5: Fallback to name-based mapping
                                            if teams_by_name and away_team_name:
                                                normalized_name = " ".join(away_team_name.split()).lower()
                                                away_team_id = teams_by_name.get(normalized_name)
                                            # Last resort: use registration ID
                                            if not away_team_id:
                                                away_team_id = reg_id

                        if not home_team_name or not away_team_name:
                            continue

                        # Extract score
                        goals_for = None
                        goals_against = None
                        if results_col is not None and results_col < len(cells):
                            score_cell = cells[results_col]
                            score_text = score_cell.get_text(strip=True)
                            # Parse score like "4 - 6" or "4-6"
                            score_match = re.search(r"(\d+)\s*[-–]\s*(\d+)", score_text)
                            if score_match:
                                goals_for = int(score_match.group(1))
                                goals_against = int(score_match.group(2))

                        # Extract date/time
                        game_date_str = None
                        if time_col is not None and time_col < len(cells):
                            time_cell = cells[time_col]
                            time_text = time_cell.get_text(strip=True)
                            # Parse date/time like "Nov 28, 2025 4:00 PM HST"
                            # Try to parse the date
                            date_match = re.search(r"([A-Za-z]+)\s+(\d+),\s+(\d{4})", time_text)
                            if date_match:
                                month_name = date_match.group(1)
                                day = int(date_match.group(2))
                                year = int(date_match.group(3))

                                month_map = {
                                    "Jan": 1,
                                    "Feb": 2,
                                    "Mar": 3,
                                    "Apr": 4,
                                    "May": 5,
                                    "Jun": 6,
                                    "Jul": 7,
                                    "Aug": 8,
                                    "Sep": 9,
                                    "Oct": 10,
                                    "Nov": 11,
                                    "Dec": 12,
                                }
                                month = month_map.get(month_name[:3], None)

                                if month:
                                    game_date_str = f"{year}-{month:02d}-{day:02d}"

                                    # Check if we should filter by date
                                    if since_date:
                                        game_date_obj = datetime.strptime(game_date_str, "%Y-%m-%d")
                                        if game_date_obj < since_date:
                                            continue

                        # Extract venue
                        venue = None
                        if location_col is not None and location_col < len(cells):
                            location_cell = cells[location_col]
                            venue = location_cell.get_text(strip=True)

                        # Extract division/competition
                        # The schedule page's "division" column contains the bracket name
                        # (e.g., "2014 Chapman Auto Group"). Use the event name as the
                        # competition (tournament) and preserve division separately.
                        division = None
                        competition = None
                        if division_col is not None and division_col < len(cells):
                            division_cell = cells[division_col]
                            division = division_cell.get_text(strip=True)
                        competition = event_name or division

                        # Extract age_group and gender from division/competition name
                        # Format examples: "SUPER PRO - U12B", "U14G", "U12 Boys", etc.
                        age_group = None
                        gender = None
                        if division:
                            # Try to extract U12, U14, etc.
                            age_match = re.search(r"U(\d+)", division, re.I)
                            if age_match:
                                age_group = f"U{age_match.group(1)}"

                            # Try to extract gender (B=Boys/Male, G=Girls/Female)
                            # Validator expects: 'Male', 'Female', 'Boys', 'Girls', 'Coed'
                            if re.search(r"\b([BG])\b", division, re.I):
                                gender_code = re.search(r"\b([BG])\b", division, re.I).group(1).upper()
                                gender = "Boys" if gender_code == "B" else "Girls"
                            elif re.search(r"\b(Boys?|Male)\b", division, re.I):
                                gender = "Boys"
                            elif re.search(r"\b(Girls?|Female)\b", division, re.I):
                                gender = "Girls"

                        # FILTER: Skip games for U9 and younger age groups
                        # PitchRank only tracks U10 and older
                        if age_group:
                            age_number_match = re.search(r"U0*(\d+)", age_group, re.I)
                            if age_number_match:
                                age_number = int(age_number_match.group(1))
                                if age_number < 10:
                                    # Skip U9, U8, U7, U6, etc.
                                    logger.debug(f"Skipping {age_group} game: {home_team_name} vs {away_team_name}")
                                    continue

                        # FILTER: Skip U20+ games (PitchRank supports U10-U19)
                        # Check age_group for U20+ indicators
                        if age_group:
                            age_group_upper = age_group.upper().strip()
                            if age_group_upper in ["U20", "U-20", "20U", "U21", "U-21", "21U"]:
                                logger.debug(
                                    f"Skipping U20+ event game (age_group={age_group}): "
                                    f"{home_team_name} vs {away_team_name}"
                                )
                                continue

                        # Also check if division/competition text contains U19/U20 indicators
                        # Match patterns like "U19", "U19B", "U-19", "19U", etc.
                        if division:
                            division_upper = division.upper()
                            if re.search(r"\b(U-?19|19U|U-?20|20U)([BG]|\b)", division_upper):
                                logger.debug(
                                    f"Skipping U19/U20 event game (division={division}): "
                                    f"{home_team_name} vs {away_team_name}"
                                )
                                continue

                        # Determine result
                        result = None
                        if goals_for is not None and goals_against is not None:
                            if goals_for > goals_against:
                                result = "W"  # Home team wins
                            elif goals_for < goals_against:
                                result = "L"  # Home team loses
                            else:
                                result = "D"  # Draw

                        # Create GameData for home team perspective
                        if game_date_str:
                            meta = {
                                "source_url": schedule_url,
                                "scraped_at": datetime.now().isoformat(),
                                "event_name": event_name or f"Event {event_id}",
                                "division_name": division,
                                "match_id": f"{event_id}_{home_team_id}_{away_team_id}_{game_date_str}"
                                if home_team_id and away_team_id
                                else None,
                                "age_group": age_group,
                                "gender": gender,
                            }

                            game = GameData(
                                provider_id=self.provider_code,
                                team_id=home_team_id or home_team_name,
                                opponent_id=away_team_id or away_team_name,
                                team_name=home_team_name,
                                opponent_name=away_team_name,
                                game_date=game_date_str,
                                home_away="H",
                                goals_for=goals_for,
                                goals_against=goals_against,
                                result=result,
                                competition=competition,
                                venue=venue,
                                meta=meta,
                            )
                            games.append(game)

                            # Also create GameData for away team perspective
                            away_meta = meta.copy()
                            away_meta["match_id"] = (
                                f"{event_id}_{away_team_id}_{home_team_id}_{game_date_str}"
                                if home_team_id and away_team_id
                                else None
                            )

                            away_game = GameData(
                                provider_id=self.provider_code,
                                team_id=away_team_id or away_team_name,
                                opponent_id=home_team_id or home_team_name,
                                team_name=away_team_name,
                                opponent_name=home_team_name,
                                game_date=game_date_str,
                                home_away="A",
                                goals_for=goals_against,  # Swapped for away team
                                goals_against=goals_for,  # Swapped for away team
                                result="L" if result == "W" else ("W" if result == "L" else result),  # Inverted result
                                competition=competition,
                                venue=venue,
                                meta=away_meta,
                            )
                            games.append(away_game)

                    except Exception as e:
                        logger.debug(f"Error parsing game row: {e}")
                        continue

        except Exception as e:
            logger.warning(f"Error parsing schedule page {schedule_url}: {e}")

        return games

    def scrape_event_games(
        self, event_id: str, event_name: Optional[str] = None, since_date: Optional[datetime] = None
    ) -> List[GameData]:
        """
        Scrape all games from a specific event

        This method now scrapes games directly from schedule pages, which is more reliable
        than trying to use API team IDs (which often return 404s for event registration IDs).

        Args:
            event_id: GotSport event ID
            event_name: Optional event name to filter games (if None, will try to extract from page)
            since_date: Only scrape games after this date

        Returns:
            List of GameData objects from the event
        """
        logger.info(f"Scraping games for event {event_id}")

        # Try to get event name from page if not provided. This path also
        # performs the earliest CAPTCHA detection — a gated event raises
        # EventCaptchaGatedError here and bypasses the downstream scrape.
        if not event_name:
            try:
                response = self._fetch_event_page(event_id)
                response.raise_for_status()
                soup = BeautifulSoup(response.text, "html.parser")
                # Try to find event name in page title or headers
                title = soup.find("title")
                if title:
                    event_name = title.get_text(strip=True)
                if not event_name:
                    h1 = soup.find("h1")
                    if h1:
                        event_name = h1.get_text(strip=True)
            except EventCaptchaGatedError:
                raise
            except Exception as e:
                logger.debug(f"Could not extract event name: {e}")

        # Scrape games directly from schedule pages
        games = self.scrape_games_from_schedule_pages(event_id, event_name, since_date)

        logger.info(f"Found {len(games)} games from event {event_id}")
        return games

    def scrape_event_by_url(
        self, event_url: str, event_name: Optional[str] = None, since_date: Optional[datetime] = None
    ) -> List[GameData]:
        """
        Scrape games from an event using its URL

        Args:
            event_url: Full URL to the event page (e.g., "https://system.gotsport.com/org_event/events/40550")
            event_name: Optional event name to filter games
            since_date: Only scrape games after this date

        Returns:
            List of GameData objects from the event
        """
        # Extract event ID from URL
        match = re.search(r"/events/(\d+)", event_url)
        if not match:
            raise ValueError(f"Could not extract event ID from URL: {event_url}")

        event_id = match.group(1)
        return self.scrape_event_games(event_id, event_name, since_date)

    def extract_teams_from_schedule_page(self, bracket_name: str, schedule_url: str) -> List[EventTeam]:
        """
        Extract teams from a bracket's schedule page

        Args:
            bracket_name: Name of the bracket (e.g., "SUPER PRO - U12B")
            schedule_url: URL to the schedule page

        Returns:
            List of EventTeam objects
        """
        teams = []
        try:
            response = self.session.get(schedule_url, timeout=self.timeout)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")

            # Look for team links in the schedule
            team_links = soup.find_all("a", href=re.compile(r"/teams?/\d+"))
            seen_team_ids = set()

            for link in team_links:
                href = link.get("href", "")
                match = re.search(r"/teams?/(\d+)", href)
                if match:
                    team_id = match.group(1)
                    if team_id not in seen_team_ids:
                        team_name = link.get_text(strip=True) or link.get("title", "") or f"Team {team_id}"
                        teams.append(EventTeam(team_id=team_id, team_name=team_name, bracket_name=bracket_name))
                        seen_team_ids.add(team_id)
        except Exception as e:
            logger.warning(f"Error extracting teams from schedule page {schedule_url}: {e}")

        return teams

    def extract_teams_by_group_from_schedule_page(
        self, bracket_name: str, schedule_url: str
    ) -> Dict[str, List[EventTeam]]:
        """Extract teams from a schedule page, organized by group"""
        groups: Dict[str, List[EventTeam]] = {}

        try:
            response = self.session.get(schedule_url, timeout=self.timeout)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")

            # Look for "Bracket A", "Bracket B", "Group A", "Pool A", etc.
            bracket_pattern = re.compile(r"(Bracket|Group|Pool|Flight)\s+([A-Z])", re.I)

            # Strategy: Find all tables and match them to their nearest preceding bracket header
            all_tables = soup.find_all("table")
            seen_team_ids = set()

            for table in all_tables:
                # Find the nearest bracket header before this table
                prev_header = table.find_previous(["h2", "h3", "h4", "h5", "h6", "b", "strong"])

                if prev_header:
                    prev_text = prev_header.get_text(strip=True)
                    prev_match = bracket_pattern.search(prev_text)

                    if prev_match:
                        group_letter = prev_match.group(2).upper()
                        group_name = f"Group {group_letter}"

                        if group_name not in groups:
                            groups[group_name] = []

                        # Extract teams from this table
                        # Extract team links from this table
                        team_links = table.find_all("a", href=re.compile(r"team=\d+"))
                        for link in team_links:
                            href = link.get("href", "")
                            match = re.search(r"team=(\d+)", href)
                            if match:
                                team_id = match.group(1)
                                if team_id not in seen_team_ids:
                                    # Get team name from link text or nearby text
                                    team_name = link.get_text(strip=True)
                                    if not team_name:
                                        # Try to get from parent row
                                        parent_row = link.find_parent("tr")
                                        if parent_row:
                                            cells = parent_row.find_all("td")
                                            if len(cells) > 1:
                                                # Usually team name is in the second cell
                                                team_name = cells[1].get_text(strip=True) or f"Team {team_id}"
                                            else:
                                                team_name = link.get("title", "") or f"Team {team_id}"
                                        else:
                                            team_name = link.get("title", "") or f"Team {team_id}"

                                    # Clean up team name - remove duplicate club names
                                    # Handle cases like "Dynamos SC Dynamos SC 14B SC" -> "Dynamos SC 14B SC"
                                    if team_name:
                                        parts = team_name.split()
                                        # Remove consecutive duplicate words
                                        cleaned_parts = []
                                        prev = None
                                        for part in parts:
                                            if part != prev:
                                                cleaned_parts.append(part)
                                            prev = part
                                        team_name = " ".join(cleaned_parts)

                                    groups[group_name].append(
                                        EventTeam(
                                            team_id=team_id,
                                            team_name=team_name,
                                            bracket_name=bracket_name,
                                            group_name=group_name,
                                        )
                                    )
                                    seen_team_ids.add(team_id)

            # If no groups found, try alternative parsing by finding tables near bracket headers
            if not groups:
                # Find all bracket headers first
                bracket_headers = []
                for header in soup.find_all(["h2", "h3", "h4", "h5", "h6", "b", "strong"]):
                    header_text = header.get_text(strip=True)
                    bracket_match = bracket_pattern.search(header_text)
                    if bracket_match:
                        group_letter = bracket_match.group(2).upper()
                        bracket_headers.append((header, group_letter))

                # For each bracket header, find the nearest table
                for header, group_letter in bracket_headers:
                    group_name = f"Group {group_letter}"
                    if group_name not in groups:
                        groups[group_name] = []

                    # Find table - look in next siblings or following elements
                    table = None
                    # Try next sibling
                    for sibling in header.next_siblings:
                        if hasattr(sibling, "name") and sibling.name == "table":
                            table = sibling
                            break

                    # If not found, try find_next
                    if not table:
                        table = header.find_next("table")

                    if table:
                        team_links = table.find_all("a", href=re.compile(r"team=\d+"))
                        for link in team_links:
                            href = link.get("href", "")
                            match = re.search(r"team=(\d+)", href)
                            if match:
                                team_id = match.group(1)
                                if team_id not in seen_team_ids:
                                    team_name = link.get_text(strip=True)
                                    if not team_name:
                                        parent_row = link.find_parent("tr")
                                        if parent_row:
                                            cells = parent_row.find_all("td")
                                            if len(cells) > 1:
                                                team_name = cells[1].get_text(strip=True) or f"Team {team_id}"
                                            else:
                                                team_name = link.get("title", "") or f"Team {team_id}"
                                        else:
                                            team_name = link.get("title", "") or f"Team {team_id}"

                                    # Clean duplicate words
                                    if team_name:
                                        parts = team_name.split()
                                        cleaned_parts = []
                                        prev = None
                                        for part in parts:
                                            if part != prev:
                                                cleaned_parts.append(part)
                                            prev = part
                                        team_name = " ".join(cleaned_parts)

                                    groups[group_name].append(
                                        EventTeam(
                                            team_id=team_id,
                                            team_name=team_name,
                                            bracket_name=bracket_name,
                                            group_name=group_name,
                                        )
                                    )
                                    seen_team_ids.add(team_id)

            # Final fallback: extract all teams and put them in Group A
            if not groups:
                team_links = soup.find_all("a", href=re.compile(r"team=\d+"))
                seen_team_ids = set()
                groups["Group A"] = []

                for link in team_links:
                    href = link.get("href", "")
                    match = re.search(r"team=(\d+)", href)
                    if match:
                        team_id = match.group(1)
                        if team_id not in seen_team_ids:
                            team_name = link.get_text(strip=True) or link.get("title", "") or f"Team {team_id}"
                            groups["Group A"].append(
                                EventTeam(
                                    team_id=team_id,
                                    team_name=team_name,
                                    bracket_name=bracket_name,
                                    group_name="Group A",
                                )
                            )
                            seen_team_ids.add(team_id)

            # If we only found one group but have multiple teams, try to split them
            # This handles cases where the HTML structure doesn't clearly separate groups
            if len(groups) == 1 and len(groups.get("Group A", [])) > 4:
                all_teams = groups["Group A"]
                total_teams = len(all_teams)

                # Split based on expected structure:
                # Super Pro: 2 groups of 4 (8 teams total)
                # Super Elite/Super Black: 2 groups of 3 (6 teams total)
                if total_teams == 8:
                    # Super Pro: split into 2 groups of 4
                    groups["Group A"] = all_teams[:4]
                    groups["Group B"] = all_teams[4:]
                elif total_teams == 6:
                    # Super Elite/Super Black: split into 2 groups of 3
                    groups["Group A"] = all_teams[:3]
                    groups["Group B"] = all_teams[3:]
                # Update group_name for each team
                for group_name, team_list in groups.items():
                    for team in team_list:
                        team.group_name = group_name

        except Exception as e:
            logger.warning(f"Error extracting teams by group from schedule page {schedule_url}: {e}")

        return groups

    def list_event_teams(self, event_id: str = None, event_url: str = None) -> Dict[str, List[EventTeam]]:
        """
        List all teams in an event, organized by bracket/group

        Args:
            event_id: GotSport event ID (e.g., "40550")
            event_url: Full URL to event page (alternative to event_id)

        Returns:
            Dictionary mapping bracket/group names to lists of EventTeam objects
        """
        if event_url:
            match = re.search(r"/events/(\d+)", event_url)
            if not match:
                raise ValueError(f"Could not extract event ID from URL: {event_url}")
            event_id = match.group(1)

        if not event_id:
            raise ValueError("Must provide either event_id or event_url")

        return self.extract_event_teams_by_bracket(event_id)

    def list_event_teams_with_groups(
        self, event_id: str = None, event_url: str = None
    ) -> Dict[str, Dict[str, List[EventTeam]]]:
        """
        List all teams in an event, organized by bracket and group (from schedule pages)

        Args:
            event_id: GotSport event ID (e.g., "40550")
            event_url: Full URL to event page (alternative to event_id)

        Returns:
            Dictionary mapping bracket names to groups, which map to lists of EventTeam objects
            Format: { "SUPER PRO - U12B": { "Group A": [EventTeam(...), ...], ... }, ... }
        """
        if event_url:
            match = re.search(r"/events/(\d+)", event_url)
            if not match:
                raise ValueError(f"Could not extract event ID from URL: {event_url}")
            event_id = match.group(1)

        if not event_id:
            raise ValueError("Must provide either event_id or event_url")

        event_url = f"{self.EVENT_BASE}/{event_id}"
        result: Dict[str, Dict[str, List[EventTeam]]] = {}

        logger.info(f"Extracting teams from schedule pages for event {event_id}: {event_url}")

        try:
            response = self.session.get(event_url, timeout=self.timeout)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")

            # Find all bracket headers with schedule links
            bracket_pattern = re.compile(r"(SUPER\s+(PRO|ELITE|BLACK|PLATINUM)|GOLD|SILVER|BRONZE).*?U\d+[BG]?", re.I)

            # Find bracket headers and their associated schedule links
            for element in soup.find_all(["strong", "b", "h3", "h4", "h5"]):
                text = element.get_text(strip=True)
                if bracket_pattern.search(text):
                    bracket_name = text

                    # Look for Schedule link near this bracket header
                    parent = element.find_parent()
                    if parent:
                        schedule_link = parent.find("a", href=re.compile(r"schedule", re.I))
                        if schedule_link:
                            schedule_href = schedule_link.get("href", "")
                            if not schedule_href.startswith("http"):
                                schedule_href = (
                                    f"https://system.gotsport.com{schedule_href}"
                                    if schedule_href.startswith("/")
                                    else f"{event_url}/{schedule_href}"
                                )

                            # Extract teams by group from schedule page
                            groups = self.extract_teams_by_group_from_schedule_page(bracket_name, schedule_href)
                            if groups:
                                result[bracket_name] = groups
                                total_teams = sum(len(teams) for teams in groups.values())
                                logger.info(
                                    f"Found {total_teams} teams in {len(groups)} groups for bracket {bracket_name}"
                                )

                            # Rate limiting
                            if self.delay_min > 0 or self.delay_max > 0:
                                time.sleep(random.uniform(self.delay_min, self.delay_max))

        except Exception as e:
            logger.warning(f"Error extracting teams by group from schedule pages: {e}")

        return result

    # ----- ProviderScraper ABC methods ---------------------------------------

    def fetch_event_metadata(self, event_url: str) -> EventMetadata:
        """Scrape event-level metadata from the gotsport event page.

        Reuses ``_fetch_event_page`` so gated events surface
        ``EventCaptchaGatedError`` rather than a cryptic parse failure.
        ``event_start_date`` stays None in Shell 01 — Shell 02 owns the
        season-year convention and will parse the date then.
        """
        match = re.search(r"/events/(\d+)", event_url)
        if not match:
            raise ValueError(f"Cannot extract event id from URL: {event_url}")
        event_id = match.group(1)

        response = self._fetch_event_page(event_id)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        title = soup.find("title")
        h1 = soup.find("h1")
        event_name = (
            (title.get_text(strip=True) if title else None)
            or (h1.get_text(strip=True) if h1 else None)
            or f"Event {event_id}"
        )

        return EventMetadata(
            provider_code="gotsport",
            provider_event_id=event_id,
            event_name=event_name,
            event_slug=f"events/{event_id}",
            event_start_date=None,
            scrape_ts=datetime.now(timezone.utc).isoformat(),
        )

    def fetch_teams_by_cohort(
        self,
        event_url: str,
        *,
        force_teams: bool = False,
        revalidate: bool = False,
    ) -> Dict[str, List[ScrapedTeam]]:
        """Walk every cohort/bracket in the event and resolve canonical team
        IDs with deferred alias-writer routing.

        Shell 01 Step 4 + 6 integration. Multi-bracket teams get one
        ``alias_writer`` call per ``provider_team_id`` (not per bracket) with
        ``match_details.also_appears_in_brackets`` spanning all brackets the
        team appears in. Writes are gated on ``DURABLE_ACTIONS`` so
        ``db_error`` teams are retried on the next run.

        Skip-set semantics:

        - Default: skip every ``provider_team_id`` whose prior journal entry
          has a durable ``alias_writer_action``.
        - ``force_teams=True``: bypass the skip — every team re-resolved.
        - ``revalidate=True``: re-resolve teams whose stored alias is
          machine-written (``review_status != 'approved'`` OR ``match_method``
          not in the curated allowlist ``{direct_id, manual, manual_review,
          manual_queue, import}``). Human-curated rows remain protected.

        Returns ``{bracket_name: [ScrapedTeam, ...]}`` mirroring the event
        page structure (useful for downstream cohort-summary consumers in
        Shell 03+).

        Raises ``EventCaptchaGatedError`` (via ``_fetch_event_page``) when
        the event URL is gated — caller should catch and surface as a
        retryable skip, not a hard failure.
        """
        match = re.search(r"/events/(\d+)", event_url)
        if not match:
            raise ValueError(f"Cannot extract event id from URL: {event_url}")
        event_id = match.group(1)
        source_url = f"{self.EVENT_BASE}/{event_id}"
        event_key = f"gotsport__{event_id}__unknown"

        journal = IntakeJournal(event_key=event_key)
        journal.startup_cleanup()

        # Reset the matcher candidate cache for this scrape so stale entries
        # from a prior event don't leak into this one.
        self._matcher_cache = {}

        # Surface a CAPTCHA gate before doing any further parse work.
        self._fetch_event_page(event_id)

        teams_by_bracket = self.extract_event_teams_by_bracket(event_id)

        # --- First pass: skip-set + classification ---------------------------
        prior_store = journal.read()
        skip_set = compute_skip_set(prior_store, force_teams=force_teams)
        if revalidate and skip_set:
            curated = self._find_curated_alias_pids(skip_set)
            # Keep only curated pids in the skip set — the rest are
            # re-resolved on this run.
            skip_set = skip_set & curated

        scraped_by_bracket: Dict[str, List[ScrapedTeam]] = {}
        all_resolutions: Dict[str, tuple[ScrapedTeam, CanonicalResolution]] = {}
        bracket_occurrences: Dict[str, List[str]] = {}
        live_pids: Set[str] = set()

        for bracket_name, event_teams in teams_by_bracket.items():
            bracket_scraped: List[ScrapedTeam] = []
            for event_team in event_teams:
                scraped = _event_team_to_scraped_team(event_team, bracket_name)
                bracket_scraped.append(scraped)
                pid = scraped.provider_team_id
                if not pid:
                    # No provider_team_id → can't dedupe or resolve; keep it
                    # in the output but don't touch alias_writer.
                    continue
                live_pids.add(pid)
                bracket_occurrences.setdefault(pid, []).append(bracket_name)
                if pid in skip_set:
                    continue
                if pid in all_resolutions:
                    # Multi-bracket occurrence — resolution already computed on
                    # first-seen ScrapedTeam; just record the bracket.
                    continue
                resolution = self.resolve_canonical_team_id(scraped)
                all_resolutions[pid] = (scraped, resolution)
            scraped_by_bracket[bracket_name] = bracket_scraped

        # --- Second pass: route + journal -----------------------------------
        run_id = datetime.now(timezone.utc).isoformat()
        stats: Dict[str, int] = {}

        journal.open_for_append()
        try:
            for pid, (scraped, resolution) in all_resolutions.items():
                brackets_for_team = bracket_occurrences.get(pid, [])
                action_dict = self._route_to_writer(
                    scraped, resolution, brackets_for_team, event_id, source_url
                )
                action = action_dict.get("action", "none")
                stats[action] = stats.get(action, 0) + 1
                if action in DURABLE_ACTIONS:
                    record = _build_jsonl_record(
                        scraped=scraped,
                        resolution=resolution,
                        action_dict=action_dict,
                        brackets=brackets_for_team,
                        run_id=run_id,
                        source_url=source_url,
                        provider_event_id=event_id,
                    )
                    journal.append(record)
                else:
                    logger.info(
                        "[journal_skip] provider_team_id=%s action=%s — will retry on next run",
                        pid, action,
                    )
        finally:
            journal.close()

        # --- End-of-scrape: compact + removed-teams diff --------------------
        kept, dropped = journal.compact()
        diff = journal.compute_removed_teams(live_pids, run_id)
        if diff.removed_provider_team_ids:
            journal.write_removed_teams_artifact(diff)

        logger.info(
            "[fetch_teams_by_cohort] event_id=%s brackets=%d unique_teams=%d "
            "resolved=%d skipped=%d compact_kept=%d compact_dropped=%d stats=%s",
            event_id,
            len(teams_by_bracket),
            len(live_pids),
            len(all_resolutions),
            len(skip_set),
            kept,
            dropped,
            stats,
        )
        return scraped_by_bracket

    # ----- internal routing + DB helpers -------------------------------------

    def _route_to_writer(
        self,
        scraped: ScrapedTeam,
        resolution: CanonicalResolution,
        brackets: List[str],
        event_id: str,
        source_url: str,
    ) -> dict[str, Any]:
        """Dispatch one resolved team to ``alias_writer`` per plan routing table.

        Returns the action dict the writer produced (or ``{"action":"none"}``
        for the unresolved case). Callers use the dict's ``action`` field to
        gate JSONL writes and to build ``canonical.scraper_state`` in the
        record.
        """
        confidence = resolution.confidence or 0.0

        if resolution.match_method in ("direct_id", "fuzzy_auto") and resolution.team_id_master:
            return upsert_team_alias(
                self.supabase_client,
                provider_uuid=self._provider_uuid,
                provider_code=self.provider_code,
                provider_team_id=scraped.provider_team_id,
                team_id_master=resolution.team_id_master,
                provider_team_name=scraped.team_name,
                confidence=confidence,
                match_method=resolution.match_method,
                priority_score=confidence,
            )

        if resolution.resolved_status in ("direct_provider_id", "review"):
            suggested_master = (
                resolution.candidates[0].get("team_id_master")
                if resolution.candidates
                else None
            )
            match_details = {
                "age_group": scraped.cohort_age_group,
                "gender": scraped.cohort_gender,
                "division": scraped.division,
                "provider_event_id": event_id,
                "source_url": source_url,
                "true_confidence": confidence,
                "candidates": resolution.candidates,
                "also_appears_in_brackets": brackets,
            }
            if resolution.resolved_status == "direct_provider_id":
                match_details["reason"] = "provider_id_match_with_low_name_similarity"
            return enqueue_match_review(
                self.supabase_client,
                provider_uuid=self._provider_uuid,
                provider_code=self.provider_code,
                provider_team_id=scraped.provider_team_id,
                provider_team_name=scraped.team_name,
                suggested_master_team_id=suggested_master,
                confidence=confidence,
                priority_score=confidence,
                match_details=match_details,
            )

        # resolved_status == "none" (or anything else we can't route)
        logger.warning(
            "[unresolved] provider_team_id=%s team_name=%r cohort=%s/%s",
            scraped.provider_team_id,
            scraped.team_name,
            scraped.cohort_age_group,
            scraped.cohort_gender,
        )
        return {"action": "none"}

    def _find_curated_alias_pids(self, provider_team_ids: Set[str]) -> Set[str]:
        """Query ``team_alias_map`` for pids whose stored alias is curated.

        "Curated" = ``review_status='approved'`` AND ``match_method`` in
        ``{direct_id, manual, manual_review, manual_queue, import}``. These
        rows are protected from ``--revalidate`` (machine-written rows like
        ``fuzzy_auto`` are NOT protected and will be re-resolved).

        Returns the subset of ``provider_team_ids`` that ARE curated — the
        caller uses this to narrow the skip set.
        """
        if not provider_team_ids:
            return set()
        curated_methods = {"direct_id", "manual", "manual_review", "manual_queue", "import"}
        try:
            result = (
                self.supabase_client.table("team_alias_map")
                .select("provider_team_id, review_status, match_method")
                .eq("provider_id", self._provider_uuid)
                .in_("provider_team_id", list(provider_team_ids))
                .execute()
            )
        except Exception as e:
            logger.warning(
                "[revalidate_query_failed] falling back to full revalidation: %s", e
            )
            return set()
        curated: Set[str] = set()
        for row in getattr(result, "data", None) or []:
            if (
                row.get("review_status") == "approved"
                and row.get("match_method") in curated_methods
            ):
                curated.add(row["provider_team_id"])
        return curated

    def resolve_canonical_team_id(
        self,
        team: ScrapedTeam,
        *,
        provider_uuid: Optional[str] = None,
        provider_code: Optional[str] = None,
    ) -> CanonicalResolution:
        """Classify a scraped team against ``team_alias_map`` via the
        tournament matcher. Pure classification — no DB writes.

        Sink routing (alias vs review queue) lives in
        ``fetch_teams_by_cohort`` so multi-bracket occurrences can be
        aggregated into a single alias_writer call per ``provider_team_id``.
        This method supplies the ``CanonicalResolution`` the caller needs
        to decide which sink to route to:

        | resolved_status     | best_score | team_id_master | match_method |
        |---------------------|------------|----------------|--------------|
        | direct_provider_id  | >= 0.97    | matches[0]     | direct_id    |
        | direct_provider_id  | <  0.97    | None (→ queue) | None         |
        | strict_exact        | any        | matches[0]     | fuzzy_auto   |
        | high_confidence     | any        | matches[0]     | fuzzy_auto   |
        | review              | any (>=0.9)| None (→ queue) | None         |
        | none                | any        | None           | None         |

        ``confidence`` is returned unclamped — alias_writer applies the
        ``fuzzy_confidence_ceiling`` clamp on insert.

        ``provider_uuid`` / ``provider_code`` are accepted for the
        ABC signature but not used here; the matcher doesn't need them.
        They're relevant in the queue-routing step (Step 4+6 integration).
        """
        from src.tournaments.event_team_matcher import (
            EventTeamSearchQuery,
            search_event_team_in_db,
        )

        provider_id_status = _provider_id_resolution_status(team)

        query = EventTeamSearchQuery(
            event_team_name=team.team_name,
            event_age_group=team.cohort_age_group,
            event_gender=team.cohort_gender,
            event_club_name=team.club_name,
            provider_team_id=(
                team.provider_team_id if provider_id_status == "resolved" else None
            ),
        )
        result = search_event_team_in_db(
            self.supabase_client, query, cache=self._matcher_cache
        )

        team_id_master, match_method = _route_resolution(result.resolved_status, result.best_score)

        return CanonicalResolution(
            team_id_master=(
                (result.matches[0].get("team_id_master") if result.matches else None)
                if team_id_master is not None  # signal: alias path, pick from matches
                else None
            ),
            confidence=result.best_score,
            resolved_status=result.resolved_status,
            match_method=match_method,
            candidates=result.matches[:3],
            provider_id_resolution_status=provider_id_status,
        )


# ---------------------------------------------------------------------------
# Classification helpers for resolve_canonical_team_id. Kept module-level so
# unit tests can pin the routing-table logic without instantiating the scraper.
# ---------------------------------------------------------------------------


def _provider_id_resolution_status(team: ScrapedTeam) -> str:
    """Classify a ``ScrapedTeam`` against the plan's three provider-id states.

    - ``"no_link"``   — scraper found no "View Rankings" link for this team
      row; there's no canonical provider id to look up.
    - ``"link_no_id"`` — link was present but the scraper couldn't extract
      a numeric canonical id from it (format drift or transient fetch).
    - ``"resolved"``   — link present AND ``provider_team_id`` populated.
    """
    if not team.has_view_rankings_link:
        return "no_link"
    if not team.provider_team_id:
        return "link_no_id"
    return "resolved"


def _route_resolution(
    resolved_status: str, best_score: Optional[float]
) -> tuple[Optional[str], Optional[str]]:
    """Apply the plan's routing table. Returns ``(sentinel, match_method)``.

    ``sentinel`` is a truthy placeholder when the resolution routes to
    ``team_alias_map`` (caller pulls the real ``team_id_master`` from
    ``matches[0]``), None when it routes to the review queue or is
    unresolved. This split keeps the match-selection logic separate from
    the routing logic.
    """
    if resolved_status == "direct_provider_id":
        if best_score is not None and best_score >= 0.97:
            return ("alias", "direct_id")
        return (None, None)  # routes to review queue
    if resolved_status in ("strict_exact", "high_confidence"):
        return ("alias", "fuzzy_auto")
    if resolved_status == "review":
        return (None, None)
    return (None, None)  # "none" or unknown


def _event_team_to_scraped_team(event_team: "EventTeam", bracket_name: str) -> ScrapedTeam:
    """Convert the legacy ``EventTeam`` row to the ``ProviderScraper``-shaped
    ``ScrapedTeam``.

    The legacy scraper doesn't populate ``club_name`` or carry
    ``has_view_rankings_link`` as a field — both are derived:

    - ``has_view_rankings_link`` — evidence for the link is a non-empty
      ``team_id`` on the ``EventTeam`` row (the scraper only assigns
      ``team_id`` when it successfully extracts a canonical id from the
      event page's rankings link).
    - ``club_name`` — left as None; downstream extraction in
      ``resolve_canonical_team_id`` is handled by the matcher's
      ``extract_club_from_name`` fallback.
    """
    pid = (event_team.team_id or "").strip()
    return ScrapedTeam(
        provider_team_id=pid,
        team_name=event_team.team_name,
        club_name=None,
        cohort_age_group=event_team.age_group or "",
        cohort_gender=event_team.gender or "",
        division=event_team.division,
        bracket_name=event_team.bracket_name or bracket_name,
        playing_up=event_team.playing_up,
        has_view_rankings_link=bool(pid),
    )


# Mapping from ``alias_writer`` action to ``canonical.scraper_state`` per the
# plan's Step 4 write protocol (item 4). Keep in sync with
# ``IntakeJournal.DURABLE_ACTIONS``.
_SCRAPER_STATE_BY_ACTION = {
    "created": "alias_written",
    "updated": "alias_written",
    "skipped_weaker_metadata": "alias_written",
    "queued": "review_queued",
    "deduped_pending": "review_queued",
    "conflict": "review_queued",
    "skipped_rejected": "review_queued",
    "skipped_already_approved": "review_queued",
    "conflict_skipped_rejected": "review_queued",
    "conflict_loop_detected": "review_queued",
    "none": "unresolved",
}


def _scraper_state_from_action(action: str) -> str:
    """Map an alias-writer action to the JSONL ``canonical.scraper_state`` field."""
    return _SCRAPER_STATE_BY_ACTION.get(action, "unresolved")


def _build_jsonl_record(
    *,
    scraped: ScrapedTeam,
    resolution: CanonicalResolution,
    action_dict: dict,
    brackets: List[str],
    run_id: str,
    source_url: str,
    provider_event_id: str,
) -> dict:
    """Produce the plan-shaped JSONL record for one resolved team.

    ``canonical.match_method`` reflects the DB-visible method — when the
    team was queued (not aliased), match_method is ``None``. When aliased,
    it's the method the writer actually stored (read from the action dict
    if present, else fall back to the resolution's classifier hint).
    """
    action = action_dict.get("action", "none")
    scraper_state = _scraper_state_from_action(action)

    if scraper_state == "alias_written":
        canonical_match_method = (
            action_dict.get("match_method") or resolution.match_method
        )
        canonical_team_id_master = (
            action_dict.get("team_id_master") or resolution.team_id_master
        )
    else:
        canonical_match_method = None
        canonical_team_id_master = None

    return {
        "run_id": run_id,
        "provider_team_id": scraped.provider_team_id,
        "team_name": scraped.team_name,
        "club_name": scraped.club_name,
        "cohort_age_group": scraped.cohort_age_group,
        "cohort_gender": scraped.cohort_gender,
        "division": scraped.division,
        "bracket_name": scraped.bracket_name,
        "playing_up": scraped.playing_up,
        "has_view_rankings_link": scraped.has_view_rankings_link,
        "provider_id_resolution_status": resolution.provider_id_resolution_status,
        "also_appears_in_brackets": brackets,
        "canonical": {
            "team_id_master": canonical_team_id_master,
            "confidence": resolution.confidence,
            "resolved_status": resolution.resolved_status,
            "match_method": canonical_match_method,
            "scraper_state": scraper_state,
        },
        "alias_writer_action": action,
        "scrape_ts": run_id,
        "source_url": source_url,
        "provider_event_id": provider_event_id,
    }
