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

import hashlib
import logging
import random
import re
import time
import unicodedata
from collections.abc import Callable, Collection, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, fields, replace
from datetime import date
from threading import Lock
from urllib.parse import quote_plus

import requests
from bs4 import BeautifulSoup

from config.settings import AGE_GROUPS
from src.scrapers._age_normalization import normalize_age
from src.tournaments.gotsport_event_structure import ScrapedDivision, parse_division_structure
from src.utils.team_utils import calculate_age_group_from_birth_year

logger = logging.getLogger(__name__)

__all__ = [
    "EVENT_BASE",
    "EVENT_ID",
    "EVENT_ID_IN_URL",
    "ZENROWS_ENDPOINT",
    "EventRoster",
    "EventRosterTeam",
    "WafChallengeError",
    "event_id_from",
    "event_roster_from_dict",
    "event_roster_to_dict",
    "make_zenrows_fetcher",
    "names_cohort_outside",
    "names_no_gender",
    "parse_division_label",
    "parse_group_ids",
    "parse_group_teams",
    "parse_header_gender",
    "parse_provider_team_id",
    "printable_text",
    "redact_secret",
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
# Both refuse a longer token rather than taking a valid prefix of it: `/events/
# 1234567890123` must not resolve to event 123456789012 and write under that
# event's path. `\Z` rather than `$`, which would accept a trailing newline.
EVENT_ID_IN_URL = re.compile(r"/events/([0-9]{1,12})(?![0-9])")
EVENT_ID = re.compile(r"^[0-9]{1,12}\Z")

_KEPT_CONTROLS = frozenset({chr(9), chr(10)})
# Zl/Zp are the line and paragraph separators: legal JSON under
# ensure_ascii=False, and a break in every JavaScript consumer that reads it.
_STRIPPED_CATEGORIES = frozenset({"Cc", "Cf", "Co", "Cs", "Zl", "Zp"})

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
# Two-digit birth years are read as 2000s; every board sits well inside that.
_COMPACT_YEAR_CENTURY = 2000

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
_STANDINGS_HEADING = "Team"

_BLOCK_MARKERS = re.compile(
    r"gokuProps|awswaf|verify_captchas|g-recaptcha|Please verify to continue", re.IGNORECASE
)
_ZENROWS_SIDE_STATUSES = frozenset({408, 422, 425, 429, 500, 502, 503, 504})
_EVENT_PAGE_READY = 'a[href*="group="]'
_SCHEDULE_READY = "table"
# The landing page is read this many times and the division ids unioned, because
# one read can arrive before the list has finished rendering.
_LANDING_READS = 2


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
    published_age_group: str = ""
    """Tournament cohort; ``age_group`` separately scopes current identity lookup."""
    published_cohort_label: str = ""
    source_entry_key: str = ""
    """Local occurrence key when a published standings row carries no provider ID."""


@dataclass(frozen=True)
class EventRoster:
    event_id: str
    teams: tuple[EventRosterTeam, ...]
    warnings: tuple[str, ...]
    divisions_found: int = 0
    divisions_walked: int = 0
    divisions_unreadable: int = 0
    divisions_skipped: int = 0
    divisions_stable: bool = True
    teams_unreadable: int = 0
    divisions: tuple[ScrapedDivision, ...] = ()
    """Per-division structure. Seeding's existing completeness ignores it;
    completed-event intake additionally requires every division to be readable."""

    completed_event: bool = False
    event_name: str = ""
    event_start_date: str | None = None
    event_end_date: str | None = None
    event_season_year: int | None = None
    event_dates_source: str = ""

    @property
    def is_complete(self) -> bool:
        """Did this walk read everything it set out to read?

        Every division must have been reached, every schedule table
        recognized, and every team page read.

        A list of divisions the page gave differently on two reads counts as
        incomplete however well the rest of the walk went: the roster may be
        missing whole divisions nobody saw, and the caller reads this flag to
        decide an event is finished with.

        A division with no fixtures posted is complete. That is the normal
        state of an event being seeded before its schedule goes up, and
        counting it as incomplete would disarm the caller's overwrite guard
        for that event permanently — a later `--limit-groups` probe could then
        replace a paid full roster with two divisions. Only a table this
        module could not *recognize* counts, because that is the one meaning
        teams were lost rather than absent.
        """
        complete = (
            self.divisions_found > 0
            and self.divisions_stable
            and self.divisions_found == self.divisions_walked
            and self.divisions_unreadable == 0
            and self.teams_unreadable == 0
        )
        if self.completed_event:
            # A completed-event intake promises the published structure as well
            # as its roster. A visited page with unreadable pools is not a full
            # capture, and neither is a placeholder for an unvisited division.
            complete = complete and self.divisions_skipped == 0 and len(self.divisions) == self.divisions_found
            complete = complete and all(d.pools_readable and d.fixtures_readable for d in self.divisions)
        return complete


def event_roster_to_dict(roster: EventRoster) -> dict:
    """Canonical JSON shape shared by recovery, intake snapshots and the CLI."""
    return {**asdict(roster), "schema_version": 1, "is_complete": roster.is_complete}


def event_roster_from_dict(payload: Mapping) -> EventRoster:
    """Read current and older roster files without silently discarding fields.

    Unknown metadata is ignored because the CLI and recovery envelope also hold
    timestamps and resolved IDs. Typed roster fields are checked, and a stored
    completeness claim must agree with the reconstructed data.
    """
    from src.tournaments.storage.event_structure import division_from_dict
    from src.tournaments.storage.schema_version import assert_supported_version

    if not isinstance(payload, Mapping):
        raise TypeError("event roster must be an object")
    assert_supported_version(payload, source="event roster")
    for name in ("teams", "warnings", "divisions"):
        if not isinstance(payload.get(name, []), (list, tuple)):
            raise TypeError(f"{name} must be a list")
    values = {field.name: payload[field.name] for field in fields(EventRoster) if field.name in payload}
    for name in ("event_id", "event_name", "event_dates_source"):
        if name in values and not isinstance(values[name], str):
            raise TypeError(f"{name} must be text")
    for name in (
        "divisions_found", "divisions_walked", "divisions_unreadable", "divisions_skipped", "teams_unreadable"
    ):
        if name in values and (type(values[name]) is not int or values[name] < 0):
            raise ValueError(f"{name} must be a nonnegative integer")
    for name in ("completed_event", "divisions_stable"):
        if name in values and type(values[name]) is not bool:
            raise TypeError(f"{name} must be a boolean")
    for name in ("event_start_date", "event_end_date"):
        if values.get(name) is not None:
            date.fromisoformat(values[name])
    if values.get("event_season_year") is not None and type(values["event_season_year"]) is not int:
        raise TypeError("event_season_year must be an integer or null")
    if any(not isinstance(warning, str) for warning in payload.get("warnings", ())):
        raise TypeError("warnings must contain text")
    team_fields = {field.name for field in fields(EventRosterTeam)}
    teams = []
    for item in payload.get("teams", ()):
        if not isinstance(item, Mapping):
            raise TypeError("team must be an object")
        team = EventRosterTeam(**{name: value for name, value in item.items() if name in team_fields})
        if type(team.source_index) is not int or team.source_index < 0:
            raise ValueError("source_index must be a nonnegative integer")
        for field in fields(EventRosterTeam):
            value = getattr(team, field.name)
            if field.name == "source_index" or (field.name == "provider_team_id" and value is None):
                continue
            if not isinstance(value, str):
                raise TypeError(f"team {field.name} must be text")
        teams.append(replace(
            team,
            age_group=team.age_group if team.age_group in AGE_GROUPS else "",
            gender=team.gender if team.gender in ("Male", "Female") else "",
        ))
    if len({team.source_index for team in teams}) != len(teams):
        raise ValueError("duplicate roster source_index")
    values = {
        **values,
        "teams": tuple(teams),
        "warnings": tuple(payload.get("warnings", ())),
        "divisions": tuple(division_from_dict(item) for item in payload.get("divisions", ())),
    }
    roster = EventRoster(**values)
    if "is_complete" in payload and (
        type(payload["is_complete"]) is not bool or payload["is_complete"] != roster.is_complete
    ):
        raise ValueError("is_complete disagrees with the saved roster")
    return roster


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
    named = _named_cohort(label)
    return (named if named in AGE_GROUPS else ""), _gender_of(label, runs)


def names_cohort_outside(label: str, wanted: Collection[str]) -> bool:
    """Does this label plainly name one cohort, and is that cohort unwanted?

    ``resolve_cohort`` withholds a cohort outside the boards, which makes
    ``U9 Boys Gold`` and a label nobody can parse arrive as the same empty
    string. To a caller deciding what to pay for they are not the same thing:
    the first is a division known to be unwanted, the second is one that cannot
    be judged and must therefore be kept.

    False whenever the label names nothing, or names more than one cohort. Both
    mean the same thing here — no single claim to act on — and a division is
    only ever dropped on a claim this module would make.
    """
    named = _named_cohort(label)
    return bool(named) and named not in wanted


def _named_cohort(label: str) -> str:
    """The one cohort this label names, in whatever form names it.

    A boarded cohort comes back as itself. An age the boards exclude comes back
    as the label's own literal (``u20``) and an unboarded birth year as its year
    (``by2005``), which are deliberately not cohort ids: nothing may match them
    against a board, and their only job is to be distinguishable from the empty
    string an unreadable label yields.
    """
    runs = [_read_run(match) for match in _AGE_RUN.finditer(_ascii_dashes(label))]
    cohorts = _cohorts_of(runs, "u_age") or _cohorts_of(runs, "birth_year")
    return cohorts.pop() if len(cohorts) == 1 else ""


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
    if not has_u and letters and numbers and all(number < 100 for number in numbers):
        # `14B` names a birth year, not an age: 2014 is U13, not U14. The `U`
        # is the only thing separating the two forms, so this branch sits after
        # the `has_u` test below can no longer claim the label. A gender letter
        # is required, which keeps `Flight 14` from becoming a cohort, and a
        # year off the boards resolves to "" like any other.
        return _AgeRun(
            "birth_year",
            frozenset(_birth_year_cohorts([_COMPACT_YEAR_CENTURY + n for n in numbers])),
            genders,
        )
    if has_u:
        # `normalize_age` owns the U18->U19 merge and the boardable band, and
        # answers None outside it. An age it will not board keeps the label's own
        # literal — `u20`, `u5` — rather than collapsing to "". Both forms stay
        # out of `AGE_GROUPS`, so `resolve_cohort` still withholds them and a
        # label naming one boardable age and one unboardable one (`U18/U19/20`)
        # still reads as two cohorts. What the literal buys is a caller being
        # able to tell "an age we do not board" from "an age nobody can read".
        return _AgeRun(
            "u_age", frozenset(normalize_age(number) or f"u{number}" for number in numbers), genders
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
        cohorts.add(calculate_age_group_from_birth_year(year) or f"by{year}")
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
    named = _genders_named(label, runs)
    return named.pop() if len(named) == 1 else ""


def _genders_named(label: str, runs: list[_AgeRun]) -> set[str]:
    named = {_GENDER_WORDS[word.group(1).lower()] for word in _GENDER_WORD.finditer(label or "")}
    return named | {gender for run in runs for gender in run.genders}


def printable_text(text: str) -> str:
    """Strip terminal control sequences out of provider-authored text.

    Everything this module returns was written by a tournament organizer or a
    club, and lands in an operator's terminal, in JSON under ``reports/`` which
    this repository does not gitignore, and in the seeding UI. ``rich.markup``
    escaping neutralises ``[`` but not ESC, and rich's own control-code filter
    does not cover it either, so a division or team name carrying ``&#x1B;``
    reaches the terminal live and fires again on a later ``cat``. Bidi and
    zero-width formats matter one step further out: they survive into the JSON
    and reverse or hide a name in every viewer that renders it.

    Decided by Unicode category rather than by a list of ranges, because a list
    is what let U+061C, U+FEFF and the Tags block through while naming exactly
    the class they belong to. Letters, marks, punctuation, symbols and spaces
    all pass, so accented names, emoji and combining marks are untouched; tab
    and newline are kept deliberately.

    Punctuation surviving is what this does not solve: a name is still free to
    carry Markdown or a spreadsheet formula, so a renderer that interprets
    either needs its own escaping at that boundary.
    """
    return "".join(
        ch
        for ch in str(text or "")
        if ch in _KEPT_CONTROLS or unicodedata.category(ch) not in _STRIPPED_CATEGORIES
    )


def event_id_from(url_or_id: str) -> str | None:
    """Read an event id out of a full event URL or a bare id, or return ``None``.

    Permissive about which of the two it was handed, because an operator pasting
    into one box has no second box to be wrong about. The CLI stays strict — it
    has a flag per form and says which one disagreed.

    The id becomes a path segment under ``reports/``, so an unvalidated value
    lets ``../`` escape the directory the run is meant to live in.
    """
    candidate = str(url_or_id or "").strip()
    if EVENT_ID.match(candidate):
        return candidate
    match = EVENT_ID_IN_URL.search(candidate)
    return match.group(1) if match else None


def parse_group_ids(html: str) -> tuple[str, ...]:
    """Return each division's group id once, in the order the page lists them."""
    return tuple(dict.fromkeys(_GROUP_ID.findall(html or "")))


def parse_division_label(html: str) -> str:
    """Read the division name from the column the schedule table labels ``Division``.

    Located by its own heading rather than by column count, so a neighbouring
    standings table that happens to be the same width cannot supply a ``PTS``
    cell in its place.

    Falls back to the page header, which names the division whether or not any
    fixture exists — the state of an event being seeded, where the fixture
    table is absent and every division would otherwise go unnamed. The header
    is a fallback and not the preferred source: it leads with a U-age stamped
    in the season the event ran, and on three of the captured B2015/B2014
    divisions that stale age disagrees with the durable birth year the table's
    own label carries.
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
    return _header_division(soup)


def _header_division(soup) -> str:
    """The division as the page header states it, or empty.

    Read by class rather than by tag: the same text ships twice, in a
    ``div.lead`` for wide viewports and an ``h5`` for narrow ones, and every
    one of the 39 captured group pages carries the ``lead`` form.
    """
    header = soup.find(class_="lead")
    return " ".join(header.get_text(" ").split()) if header else ""


def names_no_gender(label: str) -> bool:
    """Did this label decline to name a gender, as opposed to naming several?

    ``resolve_cohort`` answers ``""`` for both, and to a caller looking for a
    second opinion they are opposites. ``U14 Gold`` says nothing and leaves the
    page's header free to say it; ``Boys/Girls U10`` has already said the
    division holds both, and letting a header overrule that files every girl in
    it as a boy.
    """
    runs = [_read_run(match) for match in _AGE_RUN.finditer(_ascii_dashes(label))]
    return not _genders_named(label, runs)


def parse_header_gender(html: str) -> str:
    """The gender the page header states, for a Division cell that omits one.

    The header is demoted as a source of the division's *age* because it leads
    with a U-age written in the season the event ran, which disagrees with the
    durable birth year on three of the captured divisions. That argument does
    not reach the gender: across the captured corpus the two sources never
    disagree about it, and five pages state it only here.

    A blank gender is not a neutral omission downstream. ``resolve_unlinked``
    gives a row the free name passes only when it carries both an age and a
    gender, and the exact-name lookup filters a column holding nothing but
    ``Male`` and ``Female`` — so a division left blank costs every team in it
    both, and the operator recovers them one manual paste at a time.

    Empty whenever the header names no gender or names several, so ``Coed U10``
    still resolves to nothing rather than to a guess.
    """
    return resolve_cohort(_header_division(BeautifulSoup(html or "", "html.parser")))[1]


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


def _team_columns(headings: list[str]) -> tuple[int, ...] | None:
    """Which columns of this heading row name a team, if any.

    Two shapes carry teams. A fixture table names both sides, and a standings
    table names each team once under a bare "Team" column. The standings table
    is the one that matters while an event is being seeded, because it lists
    every accepted team before any fixture exists.
    """
    home = _squashed(_HOME_HEADING)
    away = _squashed(_AWAY_HEADING)
    if home in headings and away in headings:
        return headings.index(home), headings.index(away)
    standings = _squashed(_STANDINGS_HEADING)
    if standings in headings:
        return (headings.index(standings),)
    return None


def team_table_found(html: str) -> bool:
    """Did any table carry headings this module reads teams from?

    This separates a division whose tables are simply empty from one whose
    markup this module no longer understands. Only the second means teams
    were lost.
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
                    redact_secret(exc, api_key),
                )
                if attempt + 1 < attempts and backoff_seconds:
                    time.sleep(backoff_seconds * (attempt + 1))
        raise RuntimeError(
            f"ZenRows gave up on {url} after {attempts} attempts: "
            f"{redact_secret(last_error, api_key)}"
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

    # GotSport sends `text/html` with no charset on every captured page, and
    # `requests` then falls back to ISO-8859-1, which turns an accented or
    # non-Latin team name into mojibake. Those names are exactly what an
    # unlinked team is matched on later, so the loss lands where the provider
    # id could not help. Set before `.text` is read anywhere below.
    if "charset" not in str(response.headers.get("content-type", "")).lower():
        response.encoding = "utf-8"

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


def redact_secret(value: object, secret: str) -> str:
    """Keep a credential out of anything a caller may log, write or render.

    Two shapes leak a key, and neither catches the other:

    - **Percent-encoded.** ``requests`` puts query parameters in the URL it
      names in an ``HTTPError``, so a key containing ``+``, ``/`` or ``=`` never
      appears literally and a plain replace misses it.
    - **Split across whitespace.** A key soft-wrapped in ``.env.local`` comes
      back carrying an internal newline, and ``h11`` formats the offending
      header with ``{!r}`` — so the value never appears whole, but a
      41-character run of it does, and deleting the escape recovers it exactly.
      That shape is self-triggering: the wrapped key is both what leaks and what
      caused the request to fail.

    ``SUPABASE_URL`` is deliberately not redacted anywhere. It is public by
    construction — the same value ships to browsers as
    ``NEXT_PUBLIC_SUPABASE_URL`` — and hiding it removes the one detail telling
    an operator which project failed.

    That text reaches a file under ``reports/``, which this repository does not
    gitignore, in a public repo.
    """
    text = str(value)
    if not secret:
        return text
    runs = sorted((run for run in secret.split() if len(run) >= 8), key=len, reverse=True)
    for form in (secret, secret.strip(), quote_plus(secret), *runs):
        if form:
            text = text.replace(form, "REDACTED")
    return text


_MONTHS = {name: index for index, name in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1
)}
_NAMED_DATE = re.compile(r"\b([A-Za-z]+)\.?\s+([0-9]{1,2})(?:st|nd|rd|th)?[,]?\s+([0-9]{4})\b", re.IGNORECASE)
_EVENT_DATE_RANGE = re.compile(
    r"^(?:(?:when|dates|event dates)\s*:\s*)?"
    r"([A-Za-z]+)\.?\s+([0-9]{1,2})(?:st|nd|rd|th)?\s*[-–]\s*"
    r"(?:([A-Za-z]+)\.?\s+)?([0-9]{1,2})(?:st|nd|rd|th)?[,]?\s+([0-9]{4})[.]?$",
    re.IGNORECASE,
)


def _iso_named_date(text: str) -> str | None:
    match = _NAMED_DATE.search(text)
    if not match:
        iso = re.search(r"\b[0-9]{4}-[0-9]{2}-[0-9]{2}\b", text)
        american = re.search(r"\b([0-9]{1,2})/([0-9]{1,2})/([0-9]{4})\b", text)
        try:
            if iso:
                return date.fromisoformat(iso[0]).isoformat()
            if american:
                return date(int(american[3]), int(american[1]), int(american[2])).isoformat()
        except ValueError:
            pass
        return None
    month = _MONTHS.get(match[1][:3].lower())
    try:
        return date(int(match[3]), month, int(match[2])).isoformat() if month else None
    except ValueError:
        return None


def _soccer_season(day: date) -> int:
    return day.year if day.month >= 8 else day.year - 1


def _completed_event_metadata(pages: list[str], divisions: list, fully_visited: bool, warnings: list[str]) -> dict:
    """Read event metadata from fetched pages; a partial schedule is not its date range."""
    names: set[str] = set()
    announced_dates: set[tuple[str, str]] = set()
    for page in pages:
        soup = BeautifulSoup(page, "html.parser")
        for heading in soup.select(".navbar-brand"):
            name = printable_text(heading.get_text(" ", strip=True))
            if name and name.casefold() != "gotsport":
                names.add(name)
        for paragraph in soup.select("p"):
            match = _EVENT_DATE_RANGE.fullmatch(" ".join(paragraph.get_text(" ").split()))
            if not match:
                continue
            start_month = _MONTHS.get(match[1][:3].lower())
            end_month = _MONTHS.get((match[3] or match[1])[:3].lower())
            if not start_month or not end_month:
                continue
            try:
                start = date(int(match[5]), start_month, int(match[2]))
                end = date(int(match[5]), end_month, int(match[4]))
            except ValueError:
                continue
            if start <= end:
                announced_dates.add((start.isoformat(), end.isoformat()))
    start_date = end_date = None
    source = ""
    if len(announced_dates) == 1:
        start_date, end_date = next(iter(announced_dates))
        source = "published_event_page"
    elif len(announced_dates) > 1:
        warnings.append("Published event date ranges disagree; event dates and season were left unset")
    elif fully_visited and divisions and all(division.structure.fixtures_readable for division in divisions):
        fixtures = [fixture for division in divisions for fixture in division.structure.fixtures]
        dates = [_iso_named_date(getattr(fixture, "date_label", "") or fixture.kickoff) for fixture in fixtures]
        if dates and all(dates):
            start_date, end_date = min(dates), max(dates)
            source = "complete_schedule"
    season = None
    if start_date and end_date:
        seasons = {_soccer_season(date.fromisoformat(day)) for day in (start_date, end_date)}
        if len(seasons) == 1:
            season = seasons.pop()
    return {
        "event_name": next(iter(names)) if len(names) == 1 else "",
        "event_start_date": start_date,
        "event_end_date": end_date,
        "event_season_year": season,
        "event_dates_source": source,
    }


def _published_u_age(label: str) -> str:
    """Literal published U-age, including ages outside our ranking boards."""
    ages = set()
    for match in _AGE_RUN.finditer(_ascii_dashes(label)):
        if match.group("tail_u") or "u" in match.group("body").lower():
            ages = ages | {int(number) for number in _RUN_NUMBER.findall(match.group("body"))}
    return f"u{next(iter(ages))}" if len(ages) == 1 and 0 < next(iter(ages)) < 100 else ""


def _published_age(division, season: int | None) -> str:
    if division.published_age_group:
        return division.published_age_group
    # A mixed U-age is not an invitation to derive one from an incidental year.
    matches = list(_AGE_RUN.finditer(_ascii_dashes(division.label)))
    if any(match.group("tail_u") or "u" in match.group("body").lower() for match in matches):
        return ""
    if season is None:
        return ""
    years = set()
    for match in matches:
        numbers = [int(number) for number in _RUN_NUMBER.findall(match.group("body"))]
        if len(numbers) != 1:
            return ""
        number = numbers[0]
        if number >= _EARLIEST_BIRTH_YEAR:
            years.add(number)
        elif match.group("lead") or match.group("tail"):
            years.add(_COMPACT_YEAR_CENTURY + number)
    if len(years) != 1:
        return ""
    age = season - years.pop() + 1
    return f"u{age}" if 0 < age < 100 else ""


def _historical_lookup_age(label: str, event_season: int | None) -> str:
    """Do not reuse an earlier season's U-age against the current registry.

    Birth-year labels retain their existing current-board conversion. Literal
    U-ages are only usable when the event demonstrably belongs to this season;
    the 2026 eligibility change makes shifting an earlier U-age a guess.
    Name matches are still operator review in completed-event mode.
    """
    runs = [_read_run(match) for match in _AGE_RUN.finditer(_ascii_dashes(label))]
    if _cohorts_of(runs, "u_age") and event_season != _soccer_season(date.today()):
        return ""
    return resolve_cohort(label)[0]


def _with_historical_cohort(division, event_season: int | None):
    published_age = _published_age(division, event_season)
    return replace(
        division,
        age_group=_historical_lookup_age(division.label, event_season),
        published_age_group=published_age,
        structure=replace(
            division.structure,
            age_group=published_age,
            published_age_group=published_age,
            published_cohort_label=division.published_cohort_label,
        ),
    )


_ADVANCEMENT_SLOT = re.compile(
    r"^(?:tbd|tba|bye|to be determined|winner|loser|"
    r"(?:winner|loser)(?:\s+of)?\s+(?:[a-z]|\#?[0-9]+|"
    r"(?:match|game|semi[ -]?finals?|quarter[ -]?finals?|sf|qf|pool|group|bracket)\s*.*)|"
    r"(?:[1-9][0-9]?(?:st|nd|rd|th)?|first|second|third|fourth)\s*(?:place\s*)?"
    r"(?:(?:in|of)\s*)?(?:(?:pool|group|bracket)\s*)?[a-z]|[a-z][1-9])$",
    re.IGNORECASE,
)


def _source_only_participants(division) -> tuple[list[tuple[str, str]], tuple[str, ...]]:
    """Keep named participants without IDs; advancement slots remain fixture evidence.

    Every ID-less standings row keeps its own pool/position identity. Only
    repeated fixture appearances use unambiguous exact published labels; this
    does not invent a provider registration or a database ID.
    """
    labels: dict[str, set[str]] = {}
    for registration_id, name in division.teams:
        labels.setdefault(printable_text(name).strip(), set()).add(f"registration:{registration_id}")
    entries: list[tuple[str, str]] = []

    def add(name: str, key: str, *, dedupe_label: bool = True) -> None:
        label = printable_text(name).strip()
        if not label or (dedupe_label and len(labels.get(label, ())) == 1):
            return
        entries.append((label, key))
        labels.setdefault(label, set()).add(key)

    for pool_index, pool in enumerate(division.structure.pools):
        for member in pool.members:
            if not member.registration_id:
                key = f"pool:{division.group_id}:{pool.pool_id or pool_index}:{member.standings_position}"
                add(member.team_name, key, dedupe_label=False)
    slots: set[str] = set()
    for fixture_index, fixture in enumerate(division.structure.fixtures):
        for side in ("home", "away"):
            if getattr(fixture, f"{side}_registration_id"):
                continue
            label = printable_text(getattr(fixture, f"{side}_label", "")).strip()
            if not label:
                continue
            if _ADVANCEMENT_SLOT.fullmatch(label):
                slots.add(label)
                continue
            digest = hashlib.sha256(label.encode("utf-8")).hexdigest()[:16]
            # For a name with no competing identity, this key survives fixture
            # reordering. Ambiguous repeated labels stay distinct occurrences.
            key = f"fixture:{division.group_id}:name:{digest}"
            if len(labels.get(label, ())) > 1:
                key += f":{fixture.match_number or fixture_index}:{side}"
            add(label, key)
    notes = ()
    if slots:
        notes = (
            f"Division {division.label}: advancement or undecided slots remain fixture evidence, "
            f"not team entries: {', '.join(sorted(slots))}",
        )
    ambiguous = sorted(label for label, keys in labels.items() if len(keys) > 1)
    if ambiguous:
        notes += (
            f"Division {division.label}: ambiguous repeated team labels retain separate source entries "
            f"for review: {', '.join(ambiguous)}",
        )
    return entries, notes


def scrape_event_roster(
    event_id: str,
    *,
    fetch: HtmlFetcher,
    delay_min: float = 0.0,
    delay_max: float = 0.0,
    limit_groups: int | None = None,
    max_workers: int = 1,
    wanted_cohorts: Collection[str] | None = None,
    on_progress: Callable[[int, int], None] | None = None,
    completed_event: bool = False,
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

    ``wanted_cohorts`` drops a division whose label plainly names a cohort
    outside it, before any of its team pages are fetched. Team pages are most of
    an event's bill, so an event carrying age groups nobody ranks is much cheaper
    to walk with this set. The division's own page is still paid for, because its
    label is the thing being read. A label naming no single cohort is always
    kept: an unreadable label is not evidence a division is unwanted, and
    guessing costs teams.

    ``completed_event=True`` keeps all discovered divisions and all published
    teams, including unranked ages and source-only standings rows. Failed or
    unvisited divisions remain explicit placeholders. It also separates the
    tournament's published cohort from a team's current identity lookup age.
    """
    # completed_event is deliberately opt-in: the upcoming-event Seeding
    # project retains its existing filtering and current-cohort behavior.
    warnings: list[str] = []
    throttled = _throttled(fetch, delay_min, delay_max)

    landing_pages: list[str] = []
    group_ids, stable = _read_group_ids(throttled, event_id, warnings, landing_pages=landing_pages)
    discovered_ids = group_ids
    divisions_found = len(group_ids)
    if not group_ids:
        warnings.append(f"Event {event_id} published no divisions")
    if limit_groups is not None and limit_groups < len(group_ids):
        warnings.append(f"Walked {limit_groups} of {len(group_ids)} divisions; roster is partial")
        group_ids = group_ids[:limit_groups]

    divisions, unreadable_divisions = _read_divisions(
        throttled, event_id, group_ids, max_workers, warnings, completed_event=completed_event
    )
    # Counted before the filter: a division we read and then chose not to pay
    # further for was still walked, and `is_complete` compares this against the
    # number found. Counting only the kept ones would report every filtered walk
    # as partial, which retires the full-walk control and disarms the guard that
    # stops a probe overwriting a complete roster.
    divisions_walked = len(divisions)
    divisions, skipped = _wanted_divisions(divisions, None if completed_event else wanted_cohorts, warnings)
    # A division we chose not to walk cannot have lost us teams, so its
    # unreadable table is not a gap in this roster. Counting it would make
    # `is_complete` false for a walk that got everything it asked for, and the
    # caller reads that flag to decide whether the event is finished — a false
    # one there reopens a paid full walk on an event already bought.
    skipped_ids = {division.group_id for division in skipped}
    unreadable_divisions = [
        group_id for group_id in unreadable_divisions if group_id not in skipped_ids
    ]
    metadata = {}
    if completed_event:
        metadata = _completed_event_metadata(landing_pages, divisions, divisions_walked == divisions_found, warnings)
        divisions = [
            _with_historical_cohort(division, metadata.get("event_season_year"))
            for division in divisions
        ]
        reached = {division.group_id: division for division in divisions}
        for group_id in discovered_ids:
            if group_id not in reached:
                note = (
                    f"Division group {group_id}: not visited in this partial walk"
                    if group_id not in group_ids
                    else f"Division group {group_id}: page could not be fetched"
                )
                reached[group_id] = _Division(
                    group_id, f"group {group_id}", "", "", (),
                    ScrapedDivision(
                        group_id=group_id, division_label=f"group {group_id}",
                        pools=(), fixtures=(), pools_readable=False, fixtures_readable=False,
                        warnings=(note,), source_url=f"{EVENT_BASE}/{event_id}/schedules?group={group_id}",
                    ),
                )
        divisions = [reached[group_id] for group_id in discovered_ids]
    for division in divisions:
        if not division.age_group:
            named = division.label or f"group {division.group_id}"
            warnings.append(f"Division {named} names no single board; teams kept, cohort unset")
    # Structure warnings deliberately stay out of `warnings`. They travel on
    # each division's own `structure.warnings`, and the Backtest view reads them
    # from there. The Seeding tab renders `roster.warnings` as one yellow box
    # per entry under a cap of ten: a not-yet-played event has no standings and
    # no fixture table, so every division would contribute two boxes saying its
    # pools and games could not be read — true, expected, irrelevant to seeding,
    # and read by an operator as "the walk failed". They would also arrive
    # before the per-team fetch failures below and win the cap, inverting the
    # ordering `_warnings` exists to guarantee.
    source_only = {}
    if completed_event:
        source_only = {division.group_id: _source_only_participants(division) for division in divisions}
        divisions = [
            replace(division, structure=replace(
                division.structure, warnings=division.structure.warnings + source_only[division.group_id][1]
            ))
            for division in divisions
        ]
    pending = [(division, entry) for division in divisions for entry in division.teams]
    source_only_keys: dict[str, list[str]] = {}
    if completed_event:
        for division in divisions:
            entries, _ = source_only[division.group_id]
            pending.extend((division, ("", name)) for name, _ in entries)
            source_only_keys[division.group_id] = [key for _, key in entries]
    outcomes = _provider_ids_for(throttled, event_id, pending, max_workers, on_progress)

    teams: list[EventRosterTeam] = []
    unreadable = 0
    for (division, (registration_id, team_name)), (provider_team_id, failure) in zip(
        pending, outcomes
    ):
        if failure:
            warnings.append(failure)
            unreadable += 1
        source_entry_key = ""
        if completed_event:
            source_entry_key = (
                f"registration:{registration_id}" if registration_id
                else source_only_keys[division.group_id].pop(0)
            )
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
                published_age_group=division.published_age_group,
                published_cohort_label=division.published_cohort_label,
                source_entry_key=source_entry_key,
            )
        )

    return EventRoster(
        event_id=event_id,
        teams=tuple(teams),
        warnings=tuple(warnings),
        divisions_found=divisions_found,
        divisions_walked=divisions_walked,
        divisions_unreadable=len(unreadable_divisions),
        divisions_skipped=len(skipped),
        divisions_stable=stable,
        teams_unreadable=unreadable,
        divisions=tuple(division.structure for division in divisions),
        completed_event=completed_event,
        **metadata,
    )


@dataclass(frozen=True)
class _Division:
    group_id: str
    label: str
    age_group: str
    gender: str
    teams: tuple[tuple[str, str], ...]
    structure: ScrapedDivision
    published_age_group: str = ""
    published_cohort_label: str = ""


def _read_group_ids(
    fetch: HtmlFetcher, event_id: str, warnings: list[str], *, landing_pages: list[str] | None = None
) -> tuple[tuple[str, ...], bool]:
    """Read the event's division list, and say whether the page agreed with itself.

    One read cannot be trusted. The fetcher waits for the first
    ``a[href*="group="]`` to appear, which is satisfied while the rest of the
    list is still rendering — event 52975 answered 57 divisions on one read and
    4 on another an hour later, from the same URL.

    So it is read twice and the ids unioned. The union never reports fewer
    divisions than either read saw, and disagreement between the reads is the
    signal that the page had not settled: the caller must not treat a walk built
    on it as the whole event. The second read costs one page against the tens a
    walk spends, and the figure it protects is the one an operator authorises a
    full walk from.
    """
    seen: set[str] = set()
    reads: list[frozenset[str]] = []
    ordered: list[str] = []
    for _ in range(_LANDING_READS):
        html = fetch(f"{EVENT_BASE}/{event_id}")
        if landing_pages is not None:
            landing_pages.append(html)
        found = parse_group_ids(html)
        reads.append(frozenset(found))
        for group_id in found:
            if group_id not in seen:
                seen.add(group_id)
                ordered.append(group_id)

    # Compared as sets, not counts. Two partial renders can be the same length
    # and still name different divisions, and a count test calls that agreement
    # — then the union is walked end to end, `found` equals `walked`, and a
    # roster missing whatever neither read saw is declared the whole event.
    stable = len(set(reads)) == 1
    if not stable:
        warnings.append(
            f"The event page listed different divisions on each read "
            f"({', '.join(str(len(read)) for read in reads)} of them); it had not "
            f"finished loading, so {len(ordered)} is a floor rather than the total"
        )
    return tuple(ordered), stable


def _read_divisions(
    fetch: HtmlFetcher,
    event_id: str,
    group_ids: tuple[str, ...],
    max_workers: int,
    warnings: list[str],
    *,
    completed_event: bool = False,
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
        published_label = _header_division(BeautifulSoup(group_html, "html.parser")) if completed_event else ""
        published_age = _published_u_age(published_label or label) if completed_event else ""
        if names_no_gender(label):
            gender = parse_header_gender(group_html)
        named = label or f"group {group_id}"
        teams = parse_group_teams(group_html)
        if not team_table_found(group_html):
            unreadable.append(group_id)
            warnings.append(
                f"Division {named}: no team table this module recognizes, so its "
                "teams could not be read"
            )
        elif not teams:
            warnings.append(f"Division {named} lists no teams yet")
        divisions.append(
            _Division(
                group_id=group_id,
                label=label,
                age_group=age_group,
                gender=gender,
                teams=teams,
                published_age_group=published_age,
                published_cohort_label=published_label or label if completed_event else "",
                structure=parse_division_structure(
                    group_id=group_id,
                    division_label=label,
                    html=group_html,
                    age_group=age_group,
                    gender=gender,
                    **({
                        "source_url": f"{EVENT_BASE}/{event_id}/schedules?group={group_id}",
                        "published_age_group": published_age,
                        "published_cohort_label": published_label or label,
                    } if completed_event else {}),
                ),
            )
        )
    return divisions, unreadable


def _wanted_divisions(
    divisions: list[_Division],
    wanted_cohorts: Collection[str] | None,
    warnings: list[str],
) -> tuple[list[_Division], list[_Division]]:
    """Split the divisions into the ones worth paying for and the ones that are not.

    Only a division whose label names one cohort can be dropped. A label naming
    none, or naming two, is kept: the caller cannot act on a cohort this module
    would not assert, and dropping on a guess costs real teams.
    """
    if wanted_cohorts is None:
        return divisions, []

    keep: list[_Division] = []
    skipped: list[_Division] = []
    for division in divisions:
        if names_cohort_outside(division.label, wanted_cohorts):
            skipped.append(division)
        else:
            keep.append(division)

    if skipped:
        labels = ", ".join(sorted({division.label or division.group_id for division in skipped}))
        warnings.append(
            f"Skipped {len(skipped)} division(s) outside the ages you rank, "
            f"and did not fetch their team pages: {labels}"
        )
    return keep, skipped


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
        if registration_id:
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
    return [by_id.get(registration_id, (None, None)) for _, (registration_id, _) in pending]


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
