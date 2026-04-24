"""SincSports Clubs & Teams discovery scraper.

Scrapes the structured filter UI at ``sicclubs.aspx?sinc=Y`` to yield
``TeamRecord`` objects ahead of event scraping. Does NOT extend
``BaseScraper`` — discovery writes nothing to the database; the driver
(`scripts/discover_sincsports_teams.py`) owns all DB interactions.

The page submits via the EssentialObjects (EO.Web) callback framework,
not standard ASP.NET ``__doPostBack``. See
``tests/fixtures/sincsports_clubs/README.md`` for the reverse-engineered
wire format: the browser sets ``eo_cb_id`` / ``eo_cb_param`` and the
server returns an ``<Data><Output><![CDATA[<percent-encoded-html>]]></Output></Data>``
envelope.

Reconnaissance (2026-04-24, plan Step 3) confirmed:

- Single-select State field → discovery iterates one combo per
  (state, age, gender). Mode A in the driver's vocabulary.
- No pagination — CA U14 Boys returned 702 teams in one response.
  ``_has_more_results`` always returns ``False``.
- Response envelope always carries ``<h3>Under {age} {Gender} from {State}</h3>``
  on both populated and empty results; block/captcha is un-observed so the
  header presence is the canonical valid-shape gate.
"""

from __future__ import annotations

import logging
import os
import random
import re
import time
from dataclasses import dataclass
from typing import Dict, Iterator, List, Optional, Tuple
from urllib.parse import unquote

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from src.utils.us_states import STATE_CODE_TO_NAME

logger = logging.getLogger(__name__)

BASE_URL = "https://soccer.sincsports.com"
SEARCH_PAGE = "/sicclubs.aspx?sinc=Y"
SEARCH_URL = BASE_URL + SEARCH_PAGE

# Form-field names — locked by Step 3 reconnaissance; see observations.json.
_FIELD_STATE = "ctl00$ContentPlaceHolder1$ddlStates"
_FIELD_AGE = "ctl00$ContentPlaceHolder1$ddlAge"
_FIELD_GENDER = "ctl00$ContentPlaceHolder1$ddlGender"
_FIELD_TYPE_CLUB_TEAM = "ctl00$ContentPlaceHolder1$cblType$0"
_FIELD_RANK_CHECKBOXES = [f"ctl00$ContentPlaceHolder1$cblLevel${i}" for i in range(7)]
_FIELD_MASTER_FILE = "ctl00$ContentPlaceHolder1$ThisPageMasterFile"
_FIELD_ALPHA = "ctl00$ContentPlaceHolder1$tbAlpha"
_FIELD_SEARCH_TYPE = "ctl00$navbar$ddlSearchType"
_FIELD_SEARCH_TEXT = "ctl00$navbar$tbSearch"
_MASTER_FILE_VALUE = "/Sinc26.master"
_EO_CALLBACK_TRIGGER = "ctl00_ContentPlaceHolder1_CBPTeams"
_EO_CALLBACK_PARAM = "teams"

# Canonical age → option-value map (see observations.json).
_AGE_TO_VALUE: Dict[str, str] = {f"u{n}": str(n) for n in range(10, 20)}
_GENDER_TO_VALUE: Dict[str, str] = {"Male": "M", "Female": "F"}
# Raw SincSports filter labels accepted as aliases (normalised to canonical form).
_GENDER_ALIASES: Dict[str, str] = {
    "Male": "Male",
    "Female": "Female",
    "Boys": "Male",
    "Boys / Men": "Male",
    "M": "Male",
    "Girls": "Female",
    "Girls / Women": "Female",
    "F": "Female",
}

# Team-link href pattern on the discovery endpoint — note ``id=`` not ``teamid=``.
_TEAM_HREF_RE = re.compile(r"team/team\.aspx\?id=([A-Z0-9]+)", re.IGNORECASE)
# EO callback envelope payload extractor.
_ENVELOPE_RE = re.compile(r"<Output><!\[CDATA\[(.*?)\]\]></Output>", re.DOTALL)
# Response title header present on every valid response (populated OR empty).
_VALID_TITLE_RE = re.compile(r"<h3>\s*Under\s+\d+\s+(Boys|Girls)\s+from\s+", re.IGNORECASE)


@dataclass
class TeamRecord:
    """Discovery record for a single SincSports club team.

    ``age_group`` / ``gender`` / ``state_code`` are authoritative from the
    submitted filter inputs (NOT parsed from the row) — the filter UI is the
    ground truth for these fields. ``club_name`` comes from the parent cbox's
    header link.
    """

    provider_team_id: str
    team_name: str
    club_name: Optional[str]
    age_group: str  # "u10".."u19"
    gender: str  # "Male" | "Female"
    state_code: Optional[str]


class CaptchaOrBlockError(Exception):
    """Raised when the scraper concludes the site is blocking the run.

    Distinct ``message`` values distinguish the two drive-off conditions:
    ``"blocked"`` (consecutive 429/403/shape-fail) vs ``"transport exhausted"``
    (consecutive 5xx/network/retry-exhaustion).
    """


class SincSportsClubsScraper:
    """Scraper for the SincSports Clubs & Teams directory.

    Plain class — no ``BaseScraper`` ancestry, no ``supabase_client``. The
    driver instantiates this and consumes ``discover_teams(...)``.
    """

    def __init__(
        self,
        delay_min: Optional[float] = None,
        delay_max: Optional[float] = None,
        max_retries: Optional[int] = None,
        timeout: Optional[int] = None,
        retry_delay: Optional[float] = None,
    ):
        # Env-var prefix shared with the existing per-team scraper at
        # src/scrapers/sincsports.py; same provider, same throttle knobs.
        self.delay_min = delay_min if delay_min is not None else float(os.getenv("SINCSPORTS_DELAY_MIN", "2.0"))
        self.delay_max = delay_max if delay_max is not None else float(os.getenv("SINCSPORTS_DELAY_MAX", "3.0"))
        self.max_retries = max_retries if max_retries is not None else int(os.getenv("SINCSPORTS_MAX_RETRIES", "3"))
        self.timeout = timeout if timeout is not None else int(os.getenv("SINCSPORTS_TIMEOUT", "30"))
        self.retry_delay = retry_delay if retry_delay is not None else float(os.getenv("SINCSPORTS_RETRY_DELAY", "2.0"))

        self.session = self._init_http_session()
        self.errors: List[Dict] = []
        # Two-counter block classification — see plan Step 4 "Retry and rate-limit
        # handling" for semantics.
        self._consecutive_block_count = 0
        self._transport_error_count = 0

        logger.info(
            "Initialized SincSportsClubsScraper "
            f"(delay={self.delay_min}-{self.delay_max}s, retries={self.max_retries}, timeout={self.timeout}s)"
        )

    # ------------------------------------------------------------------
    # Session bootstrap
    # ------------------------------------------------------------------
    def _init_http_session(self) -> requests.Session:
        """HTTP session with GET/HEAD retries only.

        POST is deliberately excluded from ``allowed_methods`` because EO
        callbacks rotate form state on every response — an HTTP-level POST
        retry would resend a stale body. POST retries happen at the request
        level via ``_submit_search`` with a fresh form-state GET per attempt.
        """
        session = requests.Session()
        adapter = HTTPAdapter(
            pool_connections=10,
            pool_maxsize=10,
            max_retries=Retry(
                total=3,
                backoff_factor=0.5,
                status_forcelist=[500, 502, 503, 504],
                allowed_methods=["GET", "HEAD"],
            ),
        )
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "Accept-Encoding": "gzip, deflate, br",
                "Connection": "keep-alive",
                "Upgrade-Insecure-Requests": "1",
            }
        )
        return session

    # ------------------------------------------------------------------
    # Form-state handling
    # ------------------------------------------------------------------
    def _fetch_initial_page(self) -> Tuple[BeautifulSoup, Dict[str, str]]:
        """GET the search page and extract every hidden input as form state."""
        r = self.session.get(SEARCH_URL, timeout=self.timeout)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        return soup, self._extract_form_state(soup)

    def _extract_form_state(self, soup: BeautifulSoup) -> Dict[str, str]:
        """Return every ``<input type='hidden'>`` name → value in the page.

        EO.Web uses a handful of dynamic hidden fields (``__VIEWSTATE``,
        ``__VIEWSTATEGENERATOR``, ``__EVENTVALIDATION``, ``eo_version``,
        ``eo_style_keys``, ``__eo_sc``, ``__eo_obj_states``, plus per-control
        trigger/param pairs). Grab all of them rather than hardcoding the
        well-known three.
        """
        state: Dict[str, str] = {}
        for h in soup.find_all("input", type="hidden"):
            name = h.get("name")
            if name:
                state[name] = h.get("value", "") or ""
        return state

    # ------------------------------------------------------------------
    # Response validation
    # ------------------------------------------------------------------
    def _decode_envelope(self, raw_body: str) -> Optional[str]:
        """Extract and URL-decode the HTML fragment from the EO envelope.

        Returns ``None`` if the response is not in the expected envelope
        shape. Call sites treat that as a shape-fail.
        """
        m = _ENVELOPE_RE.search(raw_body)
        if not m:
            return None
        return unquote(m.group(1))

    def _validate_response_shape(self, fragment_html: Optional[str]) -> bool:
        """Return ``True`` iff the decoded fragment is a real search response.

        Per Step 3 observations, every valid response (populated OR empty)
        carries ``<h3>Under {age} {Gender} from {State}</h3>``. Missing
        header ⇒ shape-fail ⇒ increment the block counter.
        """
        if not fragment_html:
            return False
        return bool(_VALID_TITLE_RE.search(fragment_html))

    # ------------------------------------------------------------------
    # Request submission
    # ------------------------------------------------------------------
    def _build_post_body(
        self,
        form_state: Dict[str, str],
        state_value: str,
        age_value: str,
        gender_value: str,
    ) -> Dict[str, str]:
        body = dict(form_state)
        # EO callback wire fields
        body["eo_cb_id"] = _EO_CALLBACK_TRIGGER
        body["eo_cb_param"] = _EO_CALLBACK_PARAM
        body[_FIELD_MASTER_FILE] = _MASTER_FILE_VALUE
        # Navbar defaults — mirror the browser body
        body[_FIELD_SEARCH_TYPE] = "people"
        body[_FIELD_SEARCH_TEXT] = ""
        # Filter values
        body[_FIELD_STATE] = state_value
        body[_FIELD_AGE] = age_value
        body[_FIELD_GENDER] = gender_value
        body[_FIELD_ALPHA] = ""
        # Club Team + every USA Rank tier (plan "all 7 checked")
        body[_FIELD_TYPE_CLUB_TEAM] = "on"
        for name in _FIELD_RANK_CHECKBOXES:
            body[name] = "on"
        return body

    def _submit_search(
        self,
        state_value: str,
        age_value: str,
        gender_value: str,
    ) -> str:
        """POST the filter and return the decoded HTML fragment.

        On every attempt the scraper re-GETs the initial page to refresh
        form state before POSTing — viewstate rotates on every callback.
        Retries are classified via ``_consecutive_block_count`` /
        ``_transport_error_count``.
        """
        last_error: Optional[BaseException] = None
        for attempt in range(1, self.max_retries + 1):
            try:
                _, form_state = self._fetch_initial_page()
                body = self._build_post_body(form_state, state_value, age_value, gender_value)
                resp = self.session.post(
                    SEARCH_URL,
                    data=body,
                    headers={
                        "Content-Type": "application/x-www-form-urlencoded",
                        "Referer": SEARCH_URL,
                        "Origin": BASE_URL,
                    },
                    timeout=self.timeout,
                )
            except requests.exceptions.RequestException as e:
                # Catches ConnectionError / Timeout / HTTPError (from
                # _fetch_initial_page's raise_for_status()) — any of these
                # means the request never reached a response we can classify,
                # so account as transport regardless of the HTTP error shape.
                last_error = e
                self._transport_error_count += 1
                logger.warning(
                    f"Transport error on attempt {attempt}/{self.max_retries}: {e}; "
                    f"transport_count={self._transport_error_count}"
                )
                self._maybe_abort()
                if attempt < self.max_retries:
                    time.sleep(self.retry_delay)
                continue

            status = resp.status_code
            # Block-class responses: 429, 403
            if status in (429, 403):
                self._consecutive_block_count += 1
                self._maybe_abort()
                retry_after = self._parse_retry_after(resp.headers.get("Retry-After"))
                sleep_for = retry_after if retry_after is not None else self.delay_max
                logger.warning(
                    f"HTTP {status} on attempt {attempt}/{self.max_retries}; "
                    f"block_count={self._consecutive_block_count}; sleeping {sleep_for:.1f}s"
                )
                if attempt < self.max_retries:
                    time.sleep(sleep_for)
                continue

            # Transport-class responses: 5xx
            if 500 <= status < 600:
                self._transport_error_count += 1
                self._maybe_abort()
                logger.warning(
                    f"HTTP {status} on attempt {attempt}/{self.max_retries}; "
                    f"transport_count={self._transport_error_count}"
                )
                if attempt < self.max_retries:
                    time.sleep(self.retry_delay)
                continue

            # 200s that don't match expected shape → block-class
            fragment = self._decode_envelope(resp.text)
            if not self._validate_response_shape(fragment):
                self._consecutive_block_count += 1
                self._maybe_abort()
                logger.warning(
                    f"Shape-fail on attempt {attempt}/{self.max_retries} "
                    f"(status={status} len={len(resp.text)}); block_count={self._consecutive_block_count}"
                )
                if attempt < self.max_retries:
                    time.sleep(self.retry_delay)
                continue

            # Success — reset both counters.
            self._consecutive_block_count = 0
            self._transport_error_count = 0
            return fragment  # type: ignore[return-value]

        # Exhausted retries for non-block reasons — still a transport failure.
        self._transport_error_count += 1
        self._maybe_abort()
        raise RuntimeError(
            f"Exhausted {self.max_retries} retries for {state_value}/{age_value}/{gender_value}"
            + (f": {last_error}" if last_error else "")
        )

    def _parse_retry_after(self, raw: Optional[str]) -> Optional[float]:
        """Parse ``Retry-After`` as seconds, capped at 5 minutes."""
        if not raw:
            return None
        try:
            return min(float(raw), 300.0)
        except ValueError:
            # HTTP-date — rare in practice; skip rather than pull email.utils.
            return None

    def _maybe_abort(self) -> None:
        """Raise ``CaptchaOrBlockError`` when either threshold is exceeded."""
        if self._consecutive_block_count >= 3:
            raise CaptchaOrBlockError("blocked")
        if self._transport_error_count >= 10:
            raise CaptchaOrBlockError("transport exhausted")

    # ------------------------------------------------------------------
    # Row parsing
    # ------------------------------------------------------------------
    def _parse_result_rows(
        self,
        fragment_html: str,
        age_group: str,
        gender: str,
        state_code: Optional[str],
    ) -> List[TeamRecord]:
        """Parse team links from a decoded results fragment.

        Each club cbox has a ``<h3><a href="sicClub.aspx?id=X">CLUB</a></h3>``
        header followed by zero or more ``<a href="team/team.aspx?id=X">NAME</a>``
        anchors inside ``<div class="teamlist">``. Age / gender / state_code
        come from the submitted filter (the filter is authoritative).
        """
        soup = BeautifulSoup(fragment_html, "html.parser")
        records: List[TeamRecord] = []
        for cbox in soup.select("div.cbox"):
            club_link = cbox.select_one("h3 a[href*='sicClub.aspx?id=']")
            club_name = club_link.get_text(strip=True) if club_link else None
            teamlist = cbox.select_one("div.teamlist")
            if not teamlist:
                continue
            for anchor in teamlist.find_all("a"):
                href = anchor.get("href", "") or ""
                m = _TEAM_HREF_RE.search(href)
                if not m:
                    continue
                provider_team_id = m.group(1).upper()
                team_name = anchor.get_text(strip=True)
                if not team_name:
                    continue
                records.append(
                    TeamRecord(
                        provider_team_id=provider_team_id,
                        team_name=team_name,
                        club_name=club_name,
                        age_group=age_group,
                        gender=gender,
                        state_code=state_code,
                    )
                )
        return records

    # ------------------------------------------------------------------
    # Pagination (no-op for this site — see README observations)
    # ------------------------------------------------------------------
    def _has_more_results(self, fragment_html: str) -> bool:
        """Always ``False``. SincSports returns every match in a single response."""
        return False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def discover_teams(
        self,
        states: List[str],
        ages: List[str],
        genders: List[str],
        usa_ranks: Optional[List[str]] = None,
    ) -> Iterator[TeamRecord]:
        """Yield a ``TeamRecord`` for each team across the (states × ages × genders) grid.

        ``states`` are postal codes (e.g. ``"AZ"``); ages are ``"u10"..."u19"``;
        genders are ``"Male"`` / ``"Female"``. The scraper throttles between
        each request and surfaces per-combo failures via ``self.errors``
        without raising — except for ``CaptchaOrBlockError`` which propagates
        to let the driver halt the run cleanly.

        ``usa_ranks`` is accepted for API-shape parity with the design spec but
        ignored — all 7 tiers are always submitted checked (plan decision).
        """
        del usa_ranks  # All ranks always submitted; filter is accept-list.
        for state_code in states:
            if state_code.upper() not in STATE_CODE_TO_NAME:
                self.errors.append({"combo": (state_code, None, None), "error": f"Unknown state_code {state_code!r}"})
                continue
            for age in ages:
                age_value = _AGE_TO_VALUE.get(age.lower())
                if age_value is None:
                    self.errors.append({"combo": (state_code, age, None), "error": f"Unknown age {age!r}"})
                    continue
                for gender in genders:
                    canonical_gender = _GENDER_ALIASES.get(gender.strip())
                    gender_value = _GENDER_TO_VALUE.get(canonical_gender) if canonical_gender else None
                    if not canonical_gender or not gender_value:
                        self.errors.append({"combo": (state_code, age, gender), "error": f"Unknown gender {gender!r}"})
                        continue
                    try:
                        fragment = self._submit_search(state_code.upper(), age_value, gender_value)
                    except CaptchaOrBlockError:
                        raise
                    except Exception as e:
                        logger.error(f"Combo ({state_code}, {age}, {canonical_gender}) failed: {e}")
                        self.errors.append({"combo": (state_code, age, canonical_gender), "error": str(e)})
                        time.sleep(random.uniform(self.delay_min, self.delay_max))
                        continue

                    for record in self._parse_result_rows(fragment, age, canonical_gender, state_code.upper()):
                        yield record

                    time.sleep(random.uniform(self.delay_min, self.delay_max))
