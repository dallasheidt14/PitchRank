"""Scrape a GotSport event's accepted teams, with provider ids where published.

Walks three levels, because GotSport publishes no single team list for an event:
the ``/teams`` page exists but organizers switch it off, and it was off on both
events measured (52975, 52980). So the divisions come from the landing page, the
teams from each division's schedule page, and the provider id from each team's
own page.

Two ids are in play and only one of them is ours. ``team=4205984`` on an event
page is a **registration** id, scoped to that one event — the JSON API 404s on
it. ``rankings.gotsport.com/teams/521426`` behind a team page's "View Rankings"
link is the **provider team id** we store, so it resolves by direct lookup
rather than by name. Walking from the first to the second is the whole point of
this module.

That link is published only for teams GotSport itself ranks: 74% of a
competitive event's teams (52975) and none of a recreational one's (52980).
A team without it is returned with ``provider_team_id=None`` rather than
dropped — naming it is the caller's job, not this scraper's.

**An unreadable division label never costs a team.** Linking runs on the
provider id alone, so the cohort is metadata carried alongside it; skipping a
division whose label this module cannot parse would throw away linkable teams
for no gain. Every division is walked, and ``age_group``/``gender`` come back
empty when the label does not say plainly enough to assert one.
"""

from __future__ import annotations

import logging
import random
import re
import time
import unicodedata
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from threading import Lock
from urllib.parse import quote_plus

import requests
from bs4 import BeautifulSoup

from config.settings import AGE_GROUPS
from src.scrapers._age_normalization import normalize_age
from src.utils.team_utils import calculate_age_group_from_birth_year

logger = logging.getLogger(__name__)

__all__ = [
    "EVENT_BASE",
    "ZENROWS_ENDPOINT",
    "EventRoster",
    "EventRosterTeam",
    "WafChallengeError",
    "make_zenrows_fetcher",
    "parse_division_label",
    "parse_group_ids",
    "parse_group_teams",
    "parse_provider_team_id",
    "resolve_cohort",
    "scrape_event_roster",
]

EVENT_BASE = "https://system.gotsport.com/org_event/events"
ZENROWS_ENDPOINT = "https://api.zenrows.com/v1/"

HtmlFetcher = Callable[[str], str]

# Each id pattern ends with a non-digit lookahead so an overlong token is
# refused rather than truncated: `team=1234567890123` must not quietly become
# team 123456789012, which is a different team the rankings lookup would then
# accept at full confidence.
_GROUP_ID = re.compile(r"[?&]group=([0-9]{1,12})(?![0-9])")
_TEAM_ID = re.compile(r"[?&]team=([0-9]{1,12})(?![0-9])")
_RANKINGS_TEAM = re.compile(
    r"rankings\.gotsport\.com/teams/([0-9]{1,12})(?![0-9])"
)

# One grammar reads the whole label. A run is an age expression with an optional
# gender letter at either end: `BU12`, `U-12`, `U12B`, `12U`, `12UB`, `B2015`,
# and any of those continued by `/` or `-` into further numbers (`U15/16`,
# `17/19U`, `B2017/18`, `U13–14`). A single grammar is what keeps `17/19U`
# from reading as one cohort: an age the pattern does not reach is an age the
# multi-cohort check cannot count. Separators include the Unicode dashes,
# because `U13–14` is a two-cohort label that `U13-14` already withholds.
_AGE_RUN = re.compile(
    r"\b(?P<lead>[BG])?"
    r"(?P<body>(?:U-?)?[0-9]{1,4}(?:\s*[/\-‐-―]\s*(?:U-?)?[0-9]{1,4})*)"
    r"(?P<tail_u>U)?(?P<tail>[BG])?\b",
    re.IGNORECASE,
)
_RUN_NUMBER = re.compile(r"[0-9]{1,4}")
_GENDER_WORD = re.compile(r"\b(male|female|boys?|girls?)\b", re.IGNORECASE)

_EARLIEST_BIRTH_YEAR = 1990

_GENDER_WORDS = {
    "male": "Male",
    "boys": "Male",
    "boy": "Male",
    "female": "Female",
    "girls": "Female",
    "girl": "Female",
}
_GENDER_LETTERS = {"B": "Male", "G": "Female"}

_DIVISION_HEADING = "Division"
_RANKINGS_ANCHOR_TEXT = "View Rankings"
_HOME_HEADING = "Home Team"
_AWAY_HEADING = "Away Team"

_BLOCK_MARKERS = re.compile(
    r"gokuProps|awswaf|verify_captchas|g-recaptcha|Please verify to continue", re.IGNORECASE
)
_ZENROWS_SIDE_STATUSES = frozenset({408, 422, 425, 429, 500, 502, 503, 504})
_EVENT_PAGE_READY = 'a[href*="group="]'
_SCHEDULE_READY = "table"


@dataclass(frozen=True)
class EventRosterTeam:
    """One team as the event publishes it, with our provider id where it exists."""

    source_index: int
    group_id: str
    division_label: str
    age_group: str
    gender: str
    team_name: str
    registration_id: str
    provider_team_id: str | None = None


@dataclass(frozen=True)
class EventRoster:
    event_id: str
    teams: tuple[EventRosterTeam, ...]
    warnings: tuple[str, ...]
    divisions_found: int = 0
    divisions_walked: int = 0
    divisions_unreadable: int = 0
    teams_unreadable: int = 0

    @property
    def is_complete(self) -> bool:
        """Did this walk read everything it set out to read?

        Every division must have been reached, every schedule table
        recognized, and every team page read.

        A division with no fixtures posted is complete. That is the normal
        state of an event being seeded before its schedule goes up, and
        counting it as incomplete would disarm the caller's overwrite guard
        for that event permanently — a later `--limit-groups` probe could then
        replace a paid full roster with two divisions. Only a table this
        module could not *recognize* counts, because that is the one meaning
        teams were lost rather than absent.
        """
        return (
            self.divisions_found > 0
            and self.divisions_found == self.divisions_walked
            and self.divisions_unreadable == 0
            and self.teams_unreadable == 0
        )


def resolve_cohort(label: str) -> tuple[str, str]:
    """Read a division label into ``(age_group, gender)``, either possibly empty.

    An empty ``age_group`` means the label did not name one board plainly.
    ``BU12/BU13``, ``U15/16`` and ``17/19U`` each name two cohorts, and filing
    their teams under either age would put half of them on the wrong board; a
    label naming an age PitchRank does not board (``U6``, ``U20``) is withheld
    for the same reason. The teams are still returned — only the claim about
    their cohort is withheld.

    Gender comes back empty rather than guessed, including when a label names
    both (``Boys/Girls U10``); ``seeding_optimizer.normalize_gender_label("")``
    answers ``"Male"``, so a guess is exactly as harmful as the empty string it
    would replace.

    U-ages beat birth years when a label carries both, because
    ``U12G (AUG 1, 2014 - JULY 31, 2015)`` names its own cohort and the years
    are the band it spans.
    """
    runs = [_read_run(match) for match in _AGE_RUN.finditer(_ascii_dashes(label))]
    cohorts = _cohorts_of(runs, "u_age") or _cohorts_of(runs, "birth_year")

    age_group = ""
    if len(cohorts) == 1:
        candidate = cohorts.pop()
        age_group = candidate if candidate in AGE_GROUPS else ""

    return age_group, _gender_of(label, runs)


@dataclass(frozen=True)
class _AgeRun:
    kind: str
    cohorts: frozenset[str]
    genders: frozenset[str]


def _read_run(match: re.Match) -> _AgeRun:
    """Turn one age expression into the cohorts and genders it names."""
    body = match.group("body")
    numbers = [int(number) for number in _RUN_NUMBER.findall(body)]
    letters = {
        letter.upper() for letter in (match.group("lead"), match.group("tail")) if letter
    }
    genders = frozenset(_GENDER_LETTERS[letter] for letter in letters)

    has_u = bool(match.group("tail_u")) or "u" in body.lower()
    if numbers and numbers[0] >= _EARLIEST_BIRTH_YEAR:
        return _AgeRun("birth_year", frozenset(_birth_year_cohorts(numbers)), genders)
    if has_u:
        # `normalize_age` owns the U18->U19 merge and the boardable band, and
        # answers None outside it. That None is kept as "" so a label naming
        # one boardable age and one unboardable one (`U18/U19/20`) reads as two
        # cohorts and is withheld, rather than quietly keeping the valid half.
        return _AgeRun(
            "u_age", frozenset(normalize_age(number) or "" for number in numbers), genders
        )
    return _AgeRun("none", frozenset(), genders)


def _birth_year_cohorts(numbers: list[int]) -> set[str]:
    """Map each year to its board, expanding a two-digit continuation (``2017/18``).

    ``calculate_age_group_from_birth_year`` answers ``None`` for a year no board
    holds, which is every year outside a fourteen-wide window that slides each
    Aug 1 — so a season or graduation year in a division name (``2026 Spring
    U13``) reaches this. Keeping that ``None`` as ``""`` matches the ``normalize_age``
    line above and withholds the cohort, where dereferencing it would abort the
    whole walk after every page had been paid for.
    """
    century = (numbers[0] // 100) * 100
    cohorts = set()
    for number in numbers:
        year = number if number >= _EARLIEST_BIRTH_YEAR else century + number
        cohorts.add(calculate_age_group_from_birth_year(year) or "")
    return {cohort.lower() for cohort in cohorts}


def _ascii_dashes(label: str) -> str:
    """Fold every dash to ASCII so one grammar reads them all.

    Enumerating dashes is how `U13–14` came to resolve as a single cohort while
    `U13-14` withheld: a dash the pattern does not reach leaves the second age
    unattached, and an unattached age is invisible to the multi-cohort check.
    Unicode's own dash category answers this by construction where a list
    cannot.
    """
    return "".join("-" if _is_dash(ch) else ch for ch in str(label or ""))


def _is_dash(ch: str) -> bool:
    """Is this character a dash by Unicode's own account?

    Category ``Pd`` misses three a GotSport label can carry — MINUS SIGN
    (``Sm``, which macOS substitutes for a typed hyphen), SOFT HYPHEN (``Cf``)
    and HYPHEN BULLET (``Po``) — so the character's name decides instead. A
    list of code points is what let ``U13-14`` with an en dash read as one
    cohort while the ASCII form withheld.
    """
    name = unicodedata.name(ch, "")
    return any(word in name for word in ("HYPHEN", "DASH", "MINUS"))


def _cohorts_of(runs: list[_AgeRun], kind: str) -> set[str]:
    return {cohort for run in runs if run.kind == kind for cohort in run.cohorts}


def _gender_of(label: str, runs: list[_AgeRun]) -> str:
    """Every gender the label names, or empty when it names none or several."""
    named = {_GENDER_WORDS[word.group(1).lower()] for word in _GENDER_WORD.finditer(label or "")}
    named |= {gender for run in runs for gender in run.genders}
    return named.pop() if len(named) == 1 else ""


def parse_group_ids(html: str) -> tuple[str, ...]:
    """Return each division's group id once, in the order the page lists them."""
    return tuple(dict.fromkeys(_GROUP_ID.findall(html or "")))


def parse_division_label(html: str) -> str:
    """Read the division name from the column the schedule table labels ``Division``.

    Located by its own heading rather than by column count, so a neighbouring
    standings table that happens to be the same width cannot supply a ``PTS``
    cell in its place.
    """
    soup = BeautifulSoup(html or "", "html.parser")
    for table in soup.find_all("table"):
        column = None
        for row in table.find_all("tr"):
            cells = [cell.get_text(" ", strip=True) for cell in row.find_all(["td", "th"])]
            squashed = [_squashed(cell) for cell in cells]
            if _squashed(_DIVISION_HEADING) in squashed:
                column = squashed.index(_squashed(_DIVISION_HEADING))
            elif column is not None and len(cells) > column and cells[column]:
                return cells[column]
    return ""


def parse_group_teams(html: str) -> tuple[tuple[str, str], ...]:
    """Return ``(registration_id, team_name)`` once per team, in page order.

    Read from the Home and Away cells rather than from any link carrying a
    ``team=`` id, because the page also links ``matches_export?team=<id>``
    under the text "Export", which would otherwise be recorded as a team name.
    Headings are matched case- and space-insensitively so a wording change
    costs nothing; a schedule table this cannot map yields no teams, which the
    caller reports rather than passing off as an empty division.

    Every fixture names both sides, so a team appears as often as it plays; the
    first spelling seen wins.
    """
    soup = BeautifulSoup(html or "", "html.parser")
    teams: dict[str, str] = {}
    for table in soup.find_all("table"):
        columns = None
        for row in table.find_all("tr"):
            cells = row.find_all(["td", "th"])
            headings = [_squashed(cell.get_text(" ")) for cell in cells]
            found = _team_columns(headings)
            if found:
                columns = found
            elif columns is not None:
                for column in columns:
                    if column < len(cells):
                        _record_team(cells[column], teams)
    return tuple(teams.items())


def _squashed(text: str) -> str:
    return " ".join(str(text or "").replace("\xa0", " ").split()).casefold()


def _team_columns(headings: list[str]) -> tuple[int, int] | None:
    home = _squashed(_HOME_HEADING)
    away = _squashed(_AWAY_HEADING)
    if home in headings and away in headings:
        return headings.index(home), headings.index(away)
    return None


def schedule_table_found(html: str) -> bool:
    """Did any table carry the headings a schedule is read from?

    This separates a division whose fixtures are simply not posted yet — normal
    for an event being seeded — from one whose markup this module no longer
    understands. Only the second means teams were lost.
    """
    soup = BeautifulSoup(html or "", "html.parser")
    for table in soup.find_all("table"):
        for row in table.find_all("tr"):
            headings = [_squashed(cell.get_text(" ")) for cell in row.find_all(["td", "th"])]
            if _team_columns(headings):
                return True
    return False


def _record_team(cell, teams: dict[str, str]) -> None:
    for anchor in cell.find_all("a", href=True):
        match = _TEAM_ID.search(anchor["href"])
        name = anchor.get_text(strip=True)
        if match and name:
            teams.setdefault(match.group(1), name)


def parse_provider_team_id(html: str) -> str | None:
    """Return the id behind this team's "View Rankings" link, or ``None``.

    Bound to that anchor and to nothing else. A team page carrying an
    opponent's or a related team's rankings link would otherwise hand back
    another club's id, and because that id resolves by direct lookup the wrong
    answer is accepted at full confidence with no fuzzy score to catch it. A
    missing id is recoverable — the caller is built to tolerate it — so a lone
    unlabelled link is deliberately not trusted.
    """
    labelled = {
        match.group(1)
        for anchor in BeautifulSoup(html or "", "html.parser").find_all("a", href=True)
        for match in [_RANKINGS_TEAM.search(anchor["href"])]
        if match and _rankings_labelled(anchor)
    }
    return labelled.pop() if len(labelled) == 1 else None


def _rankings_labelled(anchor) -> bool:
    """Is this anchor the team's own "View Rankings" link?

    An icon-only link carries its name in ``aria-label`` or ``title`` rather
    than in its text, and rejecting those loses an id the page does publish.
    The comparison stays exact — ``Preview Rankings`` is a different link.
    """
    wanted = _squashed(_RANKINGS_ANCHOR_TEXT)
    names = (anchor.get_text(" "), anchor.get("aria-label", ""), anchor.get("title", ""))
    return any(_squashed(name) == wanted for name in names)


class WafChallengeError(RuntimeError):
    """Raised when GotSport answered with a bot challenge rather than the page.

    The challenge is valid HTML with no divisions and no teams in it, so a
    caller that accepted it would report an empty event instead of a failed
    fetch. Both shapes count: the AWS WAF proof-of-work page and the
    ``/verify_captchas`` reCAPTCHA the event scraper meets elsewhere.
    """


def make_zenrows_fetcher(
    api_key: str,
    *,
    get: Callable[..., requests.Response] | None = None,
    timeout: int = 240,
    attempts: int = 3,
    backoff_seconds: float = 5.0,
) -> HtmlFetcher:
    """Build a fetcher that routes GotSport event pages through ZenRows.

    ``js_render`` and ``premium_proxy`` are both required and neither is
    sufficient: measured 2026-09-04 against event 52975, the proxy alone, JS
    alone, and both together each returned the AWS WAF challenge. The challenge
    completes a proof-of-work in JS and then rebuilds the page, so what makes
    the difference is waiting for an element only the finished page has — a
    fixed wait returned the page half-built, with none of its division links.

    That wait is not reliable on its own. ZenRows answers 422 when the selector
    does not appear inside its own render budget, which the same URL survives on
    a later try, so those get ``attempts`` of them. ``timeout`` sits above that
    budget deliberately: the vendor's ceiling for ``wait_for`` is 180s and
    ``requests`` counts its timeout as silence between bytes, so a client
    timeout of 180 would abort just as the 422 was arriving.

    ``original_status`` makes GotSport's own status visible; without it a 404 or
    403 arrives wrapped as a ZenRows 200 and is read as content. Only
    ZenRows-side statuses are retried — a target 404 is a settled answer, and
    ZenRows bills every attempt.

    This costs 25 credits a request, five times the tier the other GotSport
    scrapers use, so it suits an operator-run event scrape rather than bulk work.
    """
    session = requests.Session() if get is None else None
    getter = get if get is not None else session.get

    def fetch(url: str) -> str:
        last_error: Exception | None = None
        for attempt in range(attempts):
            try:
                return _fetch_once(getter, api_key, url, timeout)
            except WafChallengeError:
                raise
            except _TargetRefused:
                raise
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "ZenRows attempt %s/%s failed for %s: %s",
                    attempt + 1,
                    attempts,
                    url,
                    _redact(str(exc), api_key),
                )
                if attempt + 1 < attempts and backoff_seconds:
                    time.sleep(backoff_seconds * (attempt + 1))
        raise RuntimeError(
            f"ZenRows gave up on {url} after {attempts} attempts: "
            f"{_redact(str(last_error), api_key)}"
        )

    return fetch


class _TargetRefused(RuntimeError):
    """A settled error status. Retrying would re-buy the same answer.

    Deliberately does not name GotSport: with ``original_status`` the status
    may be the target's, but ZenRows answers 401, 402 and 403 for its own auth
    and billing failures, so an expired subscription would otherwise send the
    operator to investigate the wrong service.
    """


def _fetch_once(getter, api_key: str, url: str, timeout: int) -> str:
    response = getter(
        ZENROWS_ENDPOINT,
        params={
            "apikey": api_key,
            "url": url,
            "js_render": "true",
            "premium_proxy": "true",
            "proxy_country": "us",
            "original_status": "true",
            "wait_for": _wait_for(url),
        },
        timeout=timeout,
    )

    # Before raise_for_status: with original_status the challenge arrives under
    # the target's own code (AWS WAF's CAPTCHA action answers 405), so raising
    # first would classify a block as an ordinary failure and let the walk
    # finish with a confident, empty-looking roster.
    if _looks_like_a_challenge(response.text or ""):
        raise WafChallengeError(f"GotSport returned a bot challenge for {url}")

    status = response.status_code
    if status >= 400 and status not in _ZENROWS_SIDE_STATUSES:
        raise _TargetRefused(f"Fetching {url} answered {status}; not retried")
    response.raise_for_status()
    return response.text


def _looks_like_a_challenge(html: str) -> bool:
    """A challenge marker, on a page carrying none of the event's own links.

    The markers alone are not enough: they are matched against the whole body,
    which includes team and division names their authors chose, so a team
    registered as `awswaf United` would otherwise abort a paid walk and every
    retry of it. A real challenge page carries no division or team link, and
    every page this module fetches carries at least one, so requiring both
    keeps the block signal while taking the word away from the provider's users.
    """
    if not _BLOCK_MARKERS.search(html):
        return False
    return not (_GROUP_ID.search(html) or _TEAM_ID.search(html))


def _wait_for(url: str) -> str:
    return _SCHEDULE_READY if "/schedules" in url else _EVENT_PAGE_READY


def _redact(text: str, api_key: str) -> str:
    """Keep the key out of anything a caller may log.

    ``requests`` puts query parameters in the URL it names in an ``HTTPError``,
    percent-encoded, so a key containing ``+``, ``/`` or ``=`` does not appear
    literally and a plain replace would silently miss it. That text reaches the
    roster's warnings and from there a file under ``reports/``, which is not
    gitignored, in a public repository.
    """
    if not api_key:
        return text
    return text.replace(api_key, "REDACTED").replace(quote_plus(api_key), "REDACTED")


def scrape_event_roster(
    event_id: str,
    *,
    fetch: HtmlFetcher,
    delay_min: float = 0.0,
    delay_max: float = 0.0,
    limit_groups: int | None = None,
    max_workers: int = 1,
    on_progress: Callable[[int, int], None] | None = None,
) -> EventRoster:
    """Walk one event and return every team it publishes.

    ``fetch`` takes a URL and returns HTML, so the caller owns proxying and
    rate-limit policy.

    ``max_workers`` fans the pages out. Concurrency is safe here in a way it is
    not for direct scraping: a proxied fetch leaves from a different residential
    IP each time, where the per-IP limiter that answers bursts with empty 202s
    is what a single-IP client trips.

    The two phases are what make that concurrency pay. Rendering one page costs
    tens of seconds, so resolving each division's teams before reading the next
    leaves the pool idle while a handful of pages finish — measured at roughly
    five minutes a division, hours for a whole event. Reading every division
    first puts all several-hundred team pages through one pool instead.

    ``limit_groups`` stops after that many divisions, which is how a new event
    gets priced against a couple of them before paying for all of it. The result
    reports ``is_complete`` so a truncated or blocked walk cannot be mistaken
    for a whole one.
    """
    warnings: list[str] = []
    throttled = _throttled(fetch, delay_min, delay_max)

    group_ids = parse_group_ids(throttled(f"{EVENT_BASE}/{event_id}"))
    divisions_found = len(group_ids)
    if not group_ids:
        warnings.append(f"Event {event_id} published no divisions")
    if limit_groups is not None and limit_groups < len(group_ids):
        warnings.append(f"Walked {limit_groups} of {len(group_ids)} divisions; roster is partial")
        group_ids = group_ids[:limit_groups]

    divisions, unreadable_divisions = _read_divisions(
        throttled, event_id, group_ids, max_workers, warnings
    )
    pending = [(division, entry) for division in divisions for entry in division.teams]
    outcomes = _provider_ids_for(throttled, event_id, pending, max_workers, on_progress)

    teams: list[EventRosterTeam] = []
    unreadable = 0
    for (division, (registration_id, team_name)), (provider_team_id, failure) in zip(
        pending, outcomes
    ):
        if failure:
            warnings.append(failure)
            unreadable += 1
        teams.append(
            EventRosterTeam(
                source_index=len(teams),
                group_id=division.group_id,
                division_label=division.label,
                age_group=division.age_group,
                gender=division.gender,
                team_name=team_name,
                registration_id=registration_id,
                provider_team_id=provider_team_id,
            )
        )

    return EventRoster(
        event_id=event_id,
        teams=tuple(teams),
        warnings=tuple(warnings),
        divisions_found=divisions_found,
        divisions_walked=len(divisions),
        divisions_unreadable=len(unreadable_divisions),
        teams_unreadable=unreadable,
    )


@dataclass(frozen=True)
class _Division:
    group_id: str
    label: str
    age_group: str
    gender: str
    teams: tuple[tuple[str, str], ...]


def _read_divisions(
    fetch: HtmlFetcher,
    event_id: str,
    group_ids: tuple[str, ...],
    max_workers: int,
    warnings: list[str],
) -> tuple[list[_Division], list[str]]:
    """Read every division's page, keeping its teams even when the label is unreadable."""

    def read(group_id: str) -> tuple[str, str | None]:
        url = f"{EVENT_BASE}/{event_id}/schedules?group={group_id}"
        try:
            return fetch(url), None
        except WafChallengeError:
            raise
        except Exception as exc:
            return "", f"Could not read division group {group_id}: {exc}"

    pages = _in_pool(read, group_ids, max_workers)

    divisions: list[_Division] = []
    unreadable: list[str] = []
    for group_id, (group_html, failure) in zip(group_ids, pages):
        if failure:
            warnings.append(failure)
            continue

        label = parse_division_label(group_html)
        age_group, gender = resolve_cohort(label)
        named = label or f"group {group_id}"
        if not age_group:
            warnings.append(f"Division {named} names no single board; teams kept, cohort unset")

        teams = parse_group_teams(group_html)
        if not schedule_table_found(group_html):
            unreadable.append(group_id)
            warnings.append(
                f"Division {named}: no schedule table this module recognizes, so its "
                "teams could not be read"
            )
        elif not teams:
            warnings.append(f"Division {named} has no fixtures posted yet")
        divisions.append(
            _Division(
                group_id=group_id,
                label=label,
                age_group=age_group,
                gender=gender,
                teams=teams,
            )
        )
    return divisions, unreadable


def _provider_ids_for(
    fetch: HtmlFetcher,
    event_id: str,
    pending: list[tuple[_Division, tuple[str, str]]],
    max_workers: int,
    on_progress: Callable[[int, int], None] | None = None,
) -> list[tuple[str | None, str | None]]:
    """Read each team's provider id, keeping the results in ``pending`` order.

    One unreadable team page costs that team its id and nothing else — the
    division it sits in is still worth returning, and the caller counts these
    so a blocked run cannot pass for a complete one. A bot challenge is the
    exception: every remaining page will fail the same way, and swallowing it
    would report an event whose teams simply have no ids.

    A registration id appearing in two divisions is fetched once; at 25 credits
    a page, paying twice for the same page buys nothing.
    """
    names: dict[str, str] = {}
    for _, (registration_id, team_name) in pending:
        names.setdefault(registration_id, team_name)

    progress = Lock()
    completed = 0

    def provider_id_for(registration_id: str) -> tuple[str | None, str | None]:
        nonlocal completed
        url = f"{EVENT_BASE}/{event_id}/schedules?team={registration_id}"
        try:
            return parse_provider_team_id(fetch(url)), None
        except WafChallengeError:
            raise
        except Exception as exc:
            return None, f"Could not read {names[registration_id]} ({registration_id}): {exc}"
        finally:
            if on_progress is not None:
                with progress:
                    completed += 1
                    _report_progress(on_progress, completed, len(names))

    by_id = dict(zip(names, _in_pool(provider_id_for, list(names), max_workers)))
    return [by_id[registration_id] for _, (registration_id, _) in pending]


def _report_progress(on_progress: Callable[[int, int], None], done: int, total: int) -> None:
    """Never let a progress line decide how the run reports its failure.

    This runs in a ``finally`` inside the worker, so an exception raised here
    would replace an in-flight ``WafChallengeError`` and the caller would lose
    the one signal telling it the walk was blocked.
    """
    try:
        on_progress(done, total)
    except Exception:
        logger.debug("Progress callback failed", exc_info=True)


def _in_pool(work, entries, max_workers: int) -> list:
    """Run ``work`` over ``entries``, returning results in the order given."""
    if max_workers > 1 and len(entries) > 1:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            return list(executor.map(work, entries))
    return [work(entry) for entry in entries]


def _throttled(fetch: HtmlFetcher, delay_min: float, delay_max: float) -> HtmlFetcher:
    if delay_min <= 0 and delay_max <= 0:
        return fetch

    def throttled_fetch(url: str) -> str:
        html = fetch(url)
        time.sleep(random.uniform(delay_min, delay_max))
        return html

    return throttled_fetch
