"""GotSport scraper implementation using API"""

import logging
import os
import random
import time
from datetime import date, datetime, timezone
from typing import Dict, List, Optional

import requests
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
from src.utils.team_utils import CURRENT_YEAR

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


# ---------------------------------------------------------------------------
# ProviderScraper adapter (Shell 01 Step 3 — Commit A)
# ---------------------------------------------------------------------------
#
# These imports are intentionally placed at module-bottom because
# ``src.scrapers.gotsport_event`` imports ``GotSportScraper`` from this module
# (line 28 there), so eagerly importing ``gotsport_event`` at the top of
# ``gotsport.py`` would create a circular import chain that breaks on the
# partially-loaded ``gotsport`` module. By the time we hit these lines,
# ``GotSportScraper`` is fully defined, so ``gotsport_event`` can complete its
# own load safely.
#
# Commit B of Step 3 moves the class body from ``gotsport_event`` into this
# file and reduces the former to a back-compat shim, at which point these
# bottom-of-file imports go away.
import re as _re  # noqa: E402

from bs4 import BeautifulSoup as _BeautifulSoup  # noqa: E402

from src.scrapers.gotsport_event import (  # noqa: E402
    EventCaptchaGatedError,
    EventTeam,
    GotSportEventScraper,
)
from src.scrapers.provider import (  # noqa: E402
    CanonicalResolution,
    EventMetadata,
    ProviderScraper,
    ScrapedTeam,
    UnsupportedProviderError,
)

__all__ = [
    "CERTIFI_AVAILABLE",
    "EventCaptchaGatedError",
    "EventTeam",
    "GotSportScraper",
    "GotsportScraper",
    "TeamNotFoundError",
]


class GotsportScraper(GotSportEventScraper, ProviderScraper):
    """ProviderScraper adapter over GotSportEventScraper.

    Shell 01 Step 3 — Commit A. Inherits from ``GotSportEventScraper`` so every
    existing public method and attribute (``scrape_event_games``,
    ``scrape_games_from_schedule_pages``, ``extract_event_teams``,
    ``extract_event_dates``, ``extract_event_teams_by_bracket``,
    ``scrape_event_by_url``, ``list_event_teams``, ``session``,
    ``_fetch_event_page``, etc.) is preserved verbatim via MRO. Adds the three
    ``ProviderScraper`` ABC methods and the plan's providers-table assertion.

    Commit B of Step 3 will inline the class body (removing the MRO parent)
    and reduce ``gotsport_event.py`` to a back-compat shim; external callers
    will see no behavior change.
    """

    def __init__(
        self,
        supabase_client,
        provider_code: str = "gotsport",
        skip_team_id_resolution: bool = False,
    ):
        # Delegate session / ZenRows / retry / CAPTCHA wiring to the parent.
        super().__init__(supabase_client, provider_code, skip_team_id_resolution)

        # Providers-table assertion (plan Step 3). ``.single()`` raises on 0
        # rows, so wrap to surface a typed error with an actionable message.
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

    # ----- ProviderScraper ABC methods ---------------------------------------

    def fetch_event_metadata(self, event_url: str) -> EventMetadata:
        """Scrape event-level metadata from the gotsport event page.

        Reuses ``_fetch_event_page`` (inherited) so gated events surface
        ``EventCaptchaGatedError`` here too, not a cryptic parse failure.
        ``event_start_date`` stays None in Shell 01 — Shell 02 owns the
        season-year convention and will parse the date then.
        """
        match = _re.search(r"/events/(\d+)", event_url)
        if not match:
            raise ValueError(f"Cannot extract event id from URL: {event_url}")
        event_id = match.group(1)

        response = self._fetch_event_page(event_id)
        response.raise_for_status()
        soup = _BeautifulSoup(response.text, "html.parser")

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
        """Not yet implemented — lands in Shell 01 Steps 4 + 6.

        Step 4 adds the resumable ``raw_scrape.jsonl`` journal and the
        per-team resume skip flags (``force_teams`` / ``revalidate`` plumb
        through here). Step 6 adds the alias_writer routing. Until then,
        ``scrape_event_games`` / ``scrape_games_from_schedule_pages`` (both
        inherited from ``GotSportEventScraper``) are the working entry
        points for event intake.
        """
        raise NotImplementedError(
            "fetch_teams_by_cohort is scoped for Shell 01 Step 4 (resumable journal) "
            "+ Step 6 (alias_writer routing). Use scrape_event_games or "
            "scrape_games_from_schedule_pages for now."
        )

    def resolve_canonical_team_id(
        self,
        team: ScrapedTeam,
        *,
        provider_uuid: Optional[str] = None,
        provider_code: Optional[str] = None,
    ) -> CanonicalResolution:
        """Not yet implemented — lands alongside ``fetch_teams_by_cohort`` in Shell 01 Step 6.

        Until then, ``src.tournaments.alias_writer.upsert_team_alias`` +
        ``enqueue_match_review`` are the canonical-ID write surface and are
        invoked directly from callers that have already obtained matches via
        ``event_team_matcher.search_event_team_in_db``.
        """
        raise NotImplementedError(
            "resolve_canonical_team_id is scoped for Shell 01 Step 6. Use "
            "src.tournaments.alias_writer + event_team_matcher for now."
        )
