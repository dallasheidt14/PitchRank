#!/usr/bin/env python3
"""Investigate each "find missing game" request and email what may be wrong with the team.

A click on "find missing game" queues a GotSport scrape of the team
(frontend/app/api/scrape-missing-game). The scrape is often not the fix: the game can sit on
another row of the same squad, the team can be filed on the wrong age board, or the game can
come from a provider the GotSport scrape never reads. For every team with a click no email has
covered yet (or, with --end, a click in one window) this reports:

  1. the scrape: how each request ended, and what it brought in that was not on record before:
     games first saved while it ran, and games already on record that it gave a score
  2. possible duplicates: live rows of the same gender, in the team's state or with none, in its
     age group or the one either side, whose names read as the same squad, with their game evidence
  3. the profile: the stored age group against the age the name states and the ages this
     season's opponents' names state, the gender against the name, and a missing state
  4. providers: whether the team has a GotSport link the scrape can use, and, while the requested
     game is still missing, the other providers it is linked to, with how each is refreshed

Report only: it changes no team or game. It sends at most one email to ALERT_EMAIL and then stamps
reported_at on the clicks it covered. Each finding names a next step. A live run logs counts only,
because Actions logs are public and the report names the teams subscribers asked about.

Clicks come from missing_game_clicks; scrape_requests cannot say which teams were clicked. Without
--end, a run takes every click with no reported_at from windows that closed at least REPORT_DELAY
ago, so a skipped run delays its clicks rather than losing them.

Usage:
    python scripts/investigate_missing_game_requests.py                    # every click not yet reported
    python scripts/investigate_missing_game_requests.py --end 2026-11-16T11:00   # re-send one window
    python scripts/investigate_missing_game_requests.py --dry-run          # print, send and stamp nothing
"""

from __future__ import annotations

import argparse
import html
import logging
import os
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.decide_team_merges import FUSED_REGISTRATION_THRESHOLD, MIN_SHARED_OPPONENTS  # noqa: E402
from scripts.enqueue_helpers import load_team_rows  # noqa: E402
from scripts.find_cross_provider_duplicates import (  # noqa: E402
    TEAM_COLS,
    batched,
    fetch_aliases,
    fetch_games,
    get_client,
    load_keep_separate,
    load_merge_map,
    merged_into,
    page,
    registered_name,
    resolver,
    stated_gender,
)
from scripts.find_fuzzy_duplicate_teams import score_team_pair  # noqa: E402
from scripts.find_squad_key_duplicates import (  # noqa: E402
    ages_contradict,
    name_refusal,
    normalize,
    pairing_key,
    read_name,
)
from scripts.fix_band_cohorts import SEASON_START  # noqa: E402
from scripts.team_cleanup.decisions import DecisionsUnavailable, keep_separate_index, kept_apart_reason  # noqa: E402
from src.utils.provider_ids import is_blank_provider_id  # noqa: E402
from src.utils.resend_email import send_email  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

ALERT_EMAIL = os.environ.get("ALERT_EMAIL", "pitchrankio@gmail.com")
SITE_URL = "https://www.pitchrank.io"

# Arizona keeps standard time all year, and the owner reads the report in it.
ARIZONA = timezone(timedelta(hours=-7))

# Windows end on the UTC hours divisible by this.
WINDOW_HOURS = 3
# How long the queue gets to scrape a window's last clicks before the window is reported. The
# workflow's cron minute must be at least this.
REPORT_DELAY = timedelta(minutes=50)

CLICK_COLS = "id,team_id_master,game_date,clicked_at,scrape_request_id"
REQUEST_COLS = "id,status,processed_at,completed_at,error_message"
GAME_COLS = (
    "id,home_team_master_id,away_team_master_id,game_date,home_score,away_score,is_excluded,created_at,scraped_at"
)
OPPONENT_COLS = "team_id_master,team_name"

GENDER_WORDS = {"Male": "boys", "Female": "girls"}

# The drainer stamps completed_at from the runner's clock just after the import commits, and
# games.created_at comes from the database's clock.
CLOCK_SLACK = timedelta(minutes=1)

# A first scrape of a team can bring in a season of games; the email lists the newest.
MAX_GAMES_LISTED = 10

# u18 squads are stored on the u19 board, so u17 and u19 are neighbours.
AGE_ORDER = ["u7", "u8", "u9", "u10", "u11", "u12", "u13", "u14", "u15", "u16", "u17", "u19"]

# Below the fuzzy scan's 0.90 auto-merge bar, because a person reads this report.
NAME_SCORE_MIN = 0.80
# A candidate with no game evidence for or against it is shown only at or above this.
NAME_ONLY_SCORE_MIN = 0.90

# Opponents whose names state one age witness the team's cohort. Fewer than this many say
# nothing, and the leading age must hold this share of them: a squad that plays up for a
# few games is labelled correctly.
AGE_WITNESS_MIN = 4
AGE_WITNESS_SHARE = 0.75

# A ZenRows request URL carries the key, and a failed scrape stores the URL in its error text.
_API_KEY = re.compile(r"apikey=[^&\s]+", re.IGNORECASE)

DEFAULT_REFRESH = "not read by the GotSport scrape; check that provider's own import"
PROVIDER_REFRESH = {
    "tgs": "TGS events: the Monday TGS event chain (tgs-event-scrape-import.yml)",
    "sincsports": "SincSports tournaments: imported by hand, a month at a time",
    "playmetrics": "PlayMetrics leagues: Mondays (playmetrics-scrape-import.yml)",
    "playmetrics_tournament": "PlayMetrics tournaments: playmetrics-tournament-scrape-import.yml",
    "mlsnext_kitman": "MLS NEXT: Mondays (mlsnext-kitman-scraper.yml)",
    "modular11": "Modular11: no longer scraped (MLS NEXT moved to Kitman for 2026-27)",
    "modular11_ea": "Elite Academy League: Mondays (ea-scraper.yml)",
    "affinity_wa": "Affinity WA: Mondays, last 7 days only (wa-scraper.yml)",
    "affinity_or": "Affinity OR: Mondays, last 7 days only (or-scraper.yml)",
    "affinity_ut": "Affinity UT: Mondays, last 7 days only (ut-scraper.yml)",
    "affinity_hi": "Affinity HI: Mondays, last 7 days only (hi-scraper.yml)",
    "affinity_ga": "Affinity GA: Mondays, last 7 days only (ga-scraper.yml)",
    "yssl": "YSSL: Mondays (yssl-scraper.yml)",
    "demosphere": "NCSL (Demosphere): Mondays (demosphere-scraper.yml)",
    "heartland": "Heartland: Mondays (heartland-scraper.yml)",
    "athletes2events": "Athletes2Events: per event, by hand (import_athletes2events_event.py)",
    "tourneycentral": "Tourney Central: per tournament, by hand (import_tourneycentral_event.py)",
    "soccereventsgroup": "Soccer Events Group: per event, by hand (import_soccereventsgroup_event.py)",
    "htgsports": "HTG Sports: per event, by hand (import_htgsports_event.py)",
}


@dataclass
class Finding:
    title: str
    details: list[str]
    next_step: str
    teams: list[tuple[dict, str]] = field(default_factory=list)


@dataclass
class Fixture:
    date: str
    opponent: str | None
    game: dict
    home: bool

    @property
    def score(self) -> tuple[int | None, int | None]:
        """(goals for, goals against), from this team's side; either can be missing."""
        g = self.game
        return (g["home_score"], g["away_score"]) if self.home else (g["away_score"], g["home_score"])


@dataclass
class ScrapeResult:
    outcome: str
    added: list[Fixture] = field(default_factory=list)
    scored: list[Fixture] = field(default_factory=list)


@dataclass
class TeamReport:
    team: dict
    clicks: list[dict]
    outcomes: list[str]
    new_games: list[str] = field(default_factory=list)
    scored_games: list[str] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)

    @property
    def game_lists(self) -> list[tuple[str, list[str]]]:
        lists = (("New games", self.new_games), ("Scores filled in", self.scored_games))
        return [(title, games) for title, games in lists if games]


def plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def nice_date(value: str | date) -> str:
    d = date.fromisoformat(value) if isinstance(value, str) else value
    return f"{d:%a %b} {d.day}"


def clock(moment: datetime) -> str:
    minutes = f":{moment.minute:02d}" if moment.minute else ""
    return f"{moment.hour % 12 or 12}{minutes} {'AM' if moment.hour < 12 else 'PM'}"


def window_end(now: datetime) -> datetime:
    now = now.astimezone(timezone.utc)
    return now.replace(hour=now.hour - now.hour % WINDOW_HOURS, minute=0, second=0, microsecond=0)


def window_label(start: datetime, end: datetime) -> str:
    start, end = start.astimezone(ARIZONA), end.astimezone(ARIZONA)
    last = clock(end) if end.date() == start.date() else f"{nice_date(end.date())}, {clock(end)}"
    return f"{nice_date(start.date())}, {clock(start)} to {last} Arizona time"


def fetch_clicks(sb, start: datetime, end: datetime) -> list[dict]:
    clicks = page(
        lambda: (
            sb.table("missing_game_clicks")
            .select(CLICK_COLS)
            .gte("clicked_at", start.isoformat())
            .lt("clicked_at", end.isoformat())
        ),
        "id",
    )
    return attach_requests(sb, clicks)


def fetch_unreported_clicks(sb, end: datetime) -> list[dict]:
    clicks = page(
        lambda: (
            sb.table("missing_game_clicks")
            .select(CLICK_COLS)
            .is_("reported_at", "null")
            .lt("clicked_at", end.isoformat())
        ),
        "id",
    )
    return attach_requests(sb, clicks)


def attach_requests(sb, clicks: list[dict]) -> list[dict]:
    """The clicks oldest first, each with the queue request it landed on under `request` (None
    when the queue refused the click, or the request is gone)."""
    found = {}
    for batch in batched(sorted({c["scrape_request_id"] for c in clicks if c["scrape_request_id"]})):
        for r in sb.table("scrape_requests").select(REQUEST_COLS).in_("id", batch).execute().data or []:
            found[r["id"]] = r
    for c in clicks:
        c["request"] = found.get(c["scrape_request_id"])
    return sorted(clicks, key=lambda c: c["clicked_at"])


def neighbour_ages(age_group: str) -> list[str]:
    if age_group not in AGE_ORDER:
        return [age_group]
    i = AGE_ORDER.index(age_group)
    return AGE_ORDER[max(i - 1, 0) : i + 2]


def fetch_pool(sb, team: dict) -> list[dict]:
    """Live rows a duplicate of `team` could be: same gender, its age group or a neighbour,
    and its state or no state at all."""

    def build(state):
        q = (
            sb.table("teams")
            .select(TEAM_COLS)
            .eq("is_deprecated", False)
            .eq("gender", team["gender"])
            .in_("age_group", neighbour_ages(team["age_group"]))
        )
        return q.eq("state_code", state) if state else q.is_("state_code", "null")

    states = [team["state_code"], None] if team["state_code"] else [None]
    rows = [r for state in states for r in page(lambda s=state: build(s), "team_id_master")]
    return [r for r in rows if r["team_id_master"] != team["team_id_master"]]


def name_match(team: dict, other: dict) -> float | None:
    """How strongly two names read as one squad, or None when they do not.

    Refusals come first: the fuzzy score applies only some of them, the squad-word match none.
    """
    if name_refusal(team, other):
        return None
    score = score_team_pair(team, other)
    if score is not None and score >= NAME_SCORE_MIN:
        return score
    club = normalize(team["club_name"])
    key = pairing_key(team["team_name"], team["club_name"], team["state_code"])
    if (
        club
        and club == normalize(other["club_name"])
        and key
        and key == pairing_key(other["team_name"], other["club_name"], other["state_code"])
    ):
        return 1.0
    return None


def schedules(game_rows: list[dict], canonical, tracked: set[str]) -> tuple[dict[str, list[Fixture]], set[str]]:
    """Each tracked team's fixtures, read under its surviving row, and the tracked rows that
    hold a game against themselves: such a row is already two squads, as the merge scans
    read it."""
    out, self_play = defaultdict(list), set()
    for g in game_rows:
        home, away = canonical(g["home_team_master_id"]), canonical(g["away_team_master_id"])
        if home and home == away:
            self_play.add(home)
            continue
        for mine, them, is_home in ((home, away, True), (away, home, False)):
            if mine in tracked:
                out[mine].append(Fixture(g["game_date"], them, g, is_home))
    return out, self_play


def visible(fixtures: list[Fixture]) -> list[Fixture]:
    return [f for f in fixtures if not f.game["is_excluded"]]


def one_game(mine: Fixture, theirs: Fixture) -> bool:
    """Whether two rows' fixtures are one game stored twice: the same opponent and day, and the
    same score, or no score at all on one side (a blank fixture beside its scored copy)."""
    if mine.opponent is None or (mine.date, mine.opponent) != (theirs.date, theirs.opponent):
        return False
    return (None, None) in (mine.score, theirs.score) or mine.score == theirs.score


def duplicate_reason(
    team_id: str, other_id: str, sched: dict, self_play: set[str], requested: set[str], score: float
) -> str | None:
    """Why `other_id` may be the same squad as `team_id`, or None when the games say it is not
    or only a weak name match supports it.

    Two rows that each hold a game the other does not on the same day (which includes playing
    each other), or either of which plays itself, are two squads. A game both rows hold
    (one_game) is one game stored twice, the strongest sign of one squad.
    """
    if {team_id, other_id} & self_play:
        return None
    mine, theirs = visible(sched[team_id]), visible(sched[other_id])
    doubled = [f for f in mine if any(one_game(f, g) for g in theirs)]
    extra_mine = {f.date for f in mine if f not in doubled}
    extra_theirs = {g.date for g in theirs if not any(one_game(f, g) for f in mine)}
    if extra_mine & extra_theirs:
        return None
    if doubled:
        return f"{plural(len(doubled), 'game')} saved on both teams (same opponent, same day)"
    holds = sorted({f.date for f in theirs} & requested)
    if holds:
        return f"has a game on the date asked about ({', '.join(nice_date(d) for d in holds)})"
    shared = {f.opponent for f in mine if f.date >= SEASON_START and f.opponent} & {
        f.opponent for f in theirs if f.date >= SEASON_START and f.opponent
    }
    if len(shared) >= MIN_SHARED_OPPONENTS:
        return f"{len(shared)} of the same opponents this season, never on the same day"
    if score >= NAME_ONLY_SCORE_MIN:
        return "same name; their games don't say either way"
    return None


def describe(row: dict, fixtures: list[Fixture], providers: dict) -> str:
    shown = visible(fixtures)
    last = max((f.date for f in shown if f.date), default=None)
    # A duplicate's last game can be seasons old, so it carries its year.
    when = f"{nice_date(last)}, {last[:4]}" if last else "never"
    return (
        f"({row['age_group']}, {row['club_name'] or 'no club'}, {providers.get(row['provider_id'], '?')}, "
        f"{plural(len(shown), 'game')}, last {when})"
    )


def duplicate_finding(team, candidates, sched, self_play, requested, providers, kept_apart) -> Finding | None:
    teams = []
    for row, score in candidates:
        reason = duplicate_reason(team["team_id_master"], row["team_id_master"], sched, self_play, requested, score)
        if reason:
            teams.append((row, f"{describe(row, sched[row['team_id_master']], providers)}: {reason}"))
    if not teams:
        return None
    details = [f"Left out {plural(kept_apart, 'similar team')} you already marked Keep separate"] if kept_apart else []
    return Finding(
        "Possible duplicate team",
        details,
        "Ask Claude to check whether they are the same team before merging. If the other one is in "
        "another age group, this team may be on the wrong age board.",
        teams,
    )


def self_play_finding(team: dict, self_play: set[str]) -> Finding | None:
    if team["team_id_master"] not in self_play:
        return None
    return Finding(
        "Has a game against itself",
        ["A team that plays itself is usually two squads saved as one, so no duplicate is suggested."],
        "Ask Claude to split the team.",
    )


def age_label(ages: set[int]) -> str:
    return " or ".join(f"u{a}" for a in sorted(ages))


def name_age_findings(team: dict) -> list[Finding]:
    for name in dict.fromkeys(filter(None, (team["team_name"], team["team_name_original"]))):
        ages = read_name(name).ages
        if ages and ages_contradict(ages, team["age_group"]):
            return [
                Finding(
                    f"Name says {age_label(ages)}, but it's on the {team['age_group']} board",
                    [f'"{name}"'],
                    "Ask Claude to check the age group. A two-year band in the name (like 2015/16) "
                    "settles it; a single birth year can mean either of two age groups.",
                )
            ]
    return []


def opponent_age_findings(team: dict, sched: dict, opponents: dict) -> list[Finding]:
    """The age this season's opponents' names state, when most of them disagree with ours.

    Skipped when the name states a band or U-age: that decides the age (a squad that plays up
    is labelled correctly), and name_age_findings reports any disagreement. Opponents' stored
    age groups are not read, because the import that mislabels a team mislabels its opponents too.
    """
    if read_name(team["team_name"]).exact:
        return []
    witnesses = Counter()
    for opponent in {f.opponent for f in visible(sched[team["team_id_master"]]) if f.date >= SEASON_START}:
        reading = read_name((opponents.get(opponent) or {}).get("team_name"))
        if reading.exact and reading.ages and len(reading.ages) == 1:
            age = next(iter(reading.ages))
            witnesses[f"u{19 if age == 18 else age}"] += 1
    total = sum(witnesses.values())
    if total < AGE_WITNESS_MIN:
        return []
    leading, count = witnesses.most_common(1)[0]
    if leading == team["age_group"] or count / total < AGE_WITNESS_SHARE:
        return []
    return [
        Finding(
            f"This season's opponents are mostly {leading}, but it's on the {team['age_group']} board",
            [f"{count} of {total} opponents whose names give an age are {leading}"],
            "Ask Claude to check the age group. A team that plays up all season is labelled correctly.",
        )
    ]


def gender_word(gender: str) -> str:
    return GENDER_WORDS.get(gender, gender)


def gender_and_state_findings(team: dict) -> list[Finding]:
    findings = []
    said = stated_gender(registered_name(team))
    if said and said != team["gender"]:
        findings.append(
            Finding(
                f"Name says {gender_word(said)}, but it's saved as {gender_word(team['gender'])}",
                [f'"{registered_name(team)}"'],
                "Ask Claude to fix the gender. The name settles it.",
            )
        )
    if not team["state_code"]:
        findings.append(
            Finding(
                "No state",
                ["It isn't on any state ranking."],
                "Ask Claude to fill in the state.",
            )
        )
    return findings


def provider_findings(team: dict, aliases: list[dict], providers: dict, still_missing: bool) -> list[Finding]:
    links = defaultdict(set)
    for a in [*aliases, team]:
        if not is_blank_provider_id(a["provider_team_id"]):
            links[providers.get(a["provider_id"], "?")].add(a["provider_team_id"])
    findings = []
    gotsport = links.pop("gotsport", set())
    if not gotsport:
        findings.append(
            Finding(
                "No GotSport link, so the scrape can't reach this team",
                [f"Linked only to: {', '.join(sorted(links)) or 'nothing'}"],
                "Find the team on GotSport and link it, then ask for the scrape again.",
            )
        )
    elif len(gotsport) >= FUSED_REGISTRATION_THRESHOLD:
        findings.append(
            Finding(
                f"{len(gotsport)} GotSport registrations on one team",
                [f"GotSport ids: {', '.join(sorted(gotsport))}"],
                "Ask Claude to check whether this team is really several squads saved as one.",
            )
        )
    if links and still_missing:
        findings.append(
            Finding(
                "Also gets games from sources this scrape doesn't read",
                [PROVIDER_REFRESH.get(code, f"{code}: {DEFAULT_REFRESH}") for code in sorted(links)],
                "If the missing game was played there, it comes in with that source's own import.",
            )
        )
    return findings


def failure_reason(message: str | None) -> str:
    message = _API_KEY.sub("apikey=<redacted>", message or "no reason given")
    if "not found on gotsport (404)" in message:
        return "GotSport has no page for this team's id any more"
    if message.startswith("No scraper available"):
        return "not a GotSport team, and it has no GotSport link to scrape instead"
    if message.startswith("WAF blocked"):
        return "GotSport blocked the request"
    return message[:160]


def saved_between(value: str | None, began: datetime, ended: datetime) -> bool:
    return value is not None and began <= datetime.fromisoformat(value) <= ended


def saved_before(value: str | None, moment: datetime) -> bool:
    return value is not None and datetime.fromisoformat(value) < moment


def scrape_result(click: dict, fixtures: list[Fixture]) -> ScrapeResult:
    """How the click's scrape ended, and what it brought in: games first saved while it ran,
    and games already on record before it began that it gave a score."""
    r = click["request"]
    if r is None:
        if click["scrape_request_id"]:
            return ScrapeResult("Scrape record no longer on file")
        return ScrapeResult(
            "Not scraped for this date: the team already had a scrape waiting for another date or GotSport id"
        )
    if r["status"] == "failed":
        return ScrapeResult(f"Scrape failed: {failure_reason(r['error_message'])}")
    if r["status"] == "processing":
        return ScrapeResult("Scrape is still running")
    if r["status"] != "completed":
        return ScrapeResult("Scrape hasn't run yet")
    if r["processed_at"] is None:
        return ScrapeResult("Scrape finished, but its start time wasn't saved, so new games can't be counted")
    began = datetime.fromisoformat(r["processed_at"])
    ended = datetime.fromisoformat(r["completed_at"]) + CLOCK_SLACK
    added, scored = [], []
    for f in fixtures:
        if saved_between(f.game["created_at"], began, ended):
            added.append(f)
        # A score filled onto a stored fixture takes the scrape's scraped_at, which the scraper writes
        # from its naive local clock: UTC on the Actions runners that drain the queue.
        elif (
            None not in f.score
            and saved_before(f.game["created_at"], began)
            and saved_between(f.game["scraped_at"], began, ended)
        ):
            scored.append(f)
    parts = [plural(len(games), word) for games, word in ((added, "new game"), (scored, "missing score")) if games]
    return ScrapeResult(f"Added {' and '.join(parts)}" if parts else "Nothing new", added, scored)


def game_lines(fixtures, opponents: dict) -> list[str]:
    lines = []
    for f in sorted(fixtures, key=lambda f: f.date or "", reverse=True):
        opponent = (opponents.get(f.opponent) or {}).get("team_name", "unknown opponent")
        mine, theirs = f.score
        if mine is None or theirs is None:
            result = "no score yet"
        else:
            result = f"{'won' if mine > theirs else 'lost' if mine < theirs else 'tied'} {mine}-{theirs}"
        hidden = " (hidden)" if f.game["is_excluded"] else ""
        lines.append(f"{nice_date(f.date) if f.date else 'no date'} vs {opponent}: {result}{hidden}")
    return lines


def hidden_game_finding(requested: set[str], fixtures: list[Fixture]) -> Finding | None:
    dates = sorted((requested & {f.date for f in fixtures}) - {f.date for f in visible(fixtures)})
    if not dates:
        return None
    return Finding(
        "The game on that date is hidden",
        [f"Hidden game on {nice_date(d)}" for d in dates],
        "Ask Claude why it was hidden before un-hiding it.",
    )


def investigate_team(sb, team, clicks, *, canonical, merge_map, keep_index, providers) -> TeamReport:
    team_id = team["team_id_master"]
    candidates, kept_apart = [], 0
    for row in fetch_pool(sb, team):
        if canonical(row["team_id_master"]) != row["team_id_master"]:
            continue
        score = name_match(team, row)
        if score is None:
            continue
        if kept_apart_reason(keep_index, canonical, team_id, row["team_id_master"]):
            kept_apart += 1
            continue
        candidates.append((row, score))

    tracked = {team_id} | {row["team_id_master"] for row, _ in candidates}
    game_rows = fetch_games(sb, sorted(merged_into(tracked, merge_map, canonical)), columns=GAME_COLS)
    sched, self_play = schedules(game_rows, canonical, tracked)
    fixtures = sched[team_id]
    opponents = load_team_rows(sb, {f.opponent for f in fixtures if f.opponent}, columns=OPPONENT_COLS)
    aliases = fetch_aliases(sb, sorted(merged_into({team_id}, merge_map, canonical)))

    requested = {c["game_date"] for c in clicks}
    still_missing = not requested <= {f.date for f in visible(fixtures)}
    findings = [
        duplicate_finding(team, candidates, sched, self_play, requested, providers, kept_apart),
        self_play_finding(team, self_play),
        hidden_game_finding(requested, fixtures),
        *name_age_findings(team),
        *opponent_age_findings(team, sched, opponents),
        *gender_and_state_findings(team),
        *provider_findings(team, aliases, providers, still_missing),
    ]
    # Refused clicks have no request id, so they share the None key and one outcome.
    by_request = {}
    for c in clicks:
        by_request.setdefault(c["scrape_request_id"], scrape_result(c, fixtures))
    results = list(by_request.values())
    added = {f.game["id"]: f for r in results for f in r.added}
    scored = {f.game["id"]: f for r in results for f in r.scored if f.game["id"] not in added}
    return TeamReport(
        team,
        clicks,
        [r.outcome for r in results],
        game_lines(added.values(), opponents),
        game_lines(scored.values(), opponents),
        [f for f in findings if f],
    )


def investigate(sb, clicks: list[dict]) -> tuple[list[TeamReport], list[str]]:
    if not clicks:
        return [], []
    merge_map = load_merge_map(sb)
    canonical = resolver(merge_map)
    caveats = []
    try:
        keep_index = keep_separate_index(load_keep_separate(sb), canonical)
    except DecisionsUnavailable as exc:
        logger.warning(str(exc))
        keep_index = {}
        caveats.append("Keep-separate decisions could not be read, so pairs already kept apart may be listed.")
    providers = {p["id"]: p["code"] for p in sb.table("providers").select("id,code").execute().data}

    by_team = defaultdict(list)
    for c in clicks:
        by_team[canonical(c["team_id_master"])].append(c)
    teams = load_team_rows(sb, set(by_team), columns=TEAM_COLS)
    reports = []
    for team_id, team_clicks in by_team.items():
        if team_id not in teams:
            caveats.append(f"A clicked team could not be found ({team_id})")
            continue
        reports.append(
            investigate_team(
                sb,
                teams[team_id],
                team_clicks,
                canonical=canonical,
                merge_map=merge_map,
                keep_index=keep_index,
                providers=providers,
            )
        )
    reports.sort(key=lambda r: (-len(r.findings), r.team["team_name"]))
    return reports, caveats


FOOTER = "This email only reports: it changes nothing. It comes every 3 hours when someone asked for a missing game."


def team_url(team: dict) -> str:
    return f"{SITE_URL}/teams/{team['team_id_master']}"


def team_label(team: dict) -> str:
    return f"{team['age_group']} {gender_word(team['gender']).capitalize()}, {team['state_code'] or 'no state'}"


def asked_about(report: TeamReport) -> str:
    return ", ".join(nice_date(d) for d in sorted({c["game_date"] for c in report.clicks}))


def listed(lines: list[str]) -> list[str]:
    extra = len(lines) - MAX_GAMES_LISTED
    return lines[:MAX_GAMES_LISTED] + ([f"and {extra} more"] if extra > 0 else [])


def tally(reports: list[TeamReport]) -> str:
    with_new = sum(1 for r in reports if r.game_lists)
    flagged = sum(1 for r in reports if r.findings)
    need = "needs" if flagged == 1 else "need"
    return f"{plural(len(reports), 'team')}, {with_new} with new games or scores, {flagged} {need} a look"


def subject(reports: list[TeamReport], label: str) -> str:
    return f"PitchRank missing games: {tally(reports)} ({label})"


def render_text(reports: list[TeamReport], caveats: list[str], label: str) -> str:
    lines = [f"Missing-game requests, {label}", tally(reports), *caveats]
    for r in reports:
        lines += [
            "",
            f"{r.team['team_name']} ({team_label(r.team)})",
            team_url(r.team),
            f"Asked about: {asked_about(r)}",
            f"Scrape: {'; '.join(r.outcomes)}",
        ]
        for title, games in r.game_lists:
            lines += [f"{title} ({len(games)}):", *(f"  {g}" for g in listed(games))]
        for f in r.findings:
            lines.append(f"Needs a look: {f.title}")
            lines += [f"  {row['team_name']} {text} {team_url(row)}" for row, text in f.teams]
            lines += [f"  {d}" for d in f.details]
            lines.append(f"  What to do: {f.next_step}")
    return "\n".join([*lines, "", FOOTER])


def render_html(reports: list[TeamReport], caveats: list[str], label: str) -> str:
    def esc(value) -> str:
        return html.escape(str(value), quote=True)

    def link(team: dict) -> str:
        return f"<a href='{esc(team_url(team))}' style='color:#0B5345'>{esc(team['team_name'])}</a>"

    def bullets(items: list[str]) -> str:
        return "<ul style='margin:4px 0 0; padding-left:20px'>" + "".join(f"<li>{i}</li>" for i in items) + "</ul>"

    muted = "color:#666; font-size:13px"
    cell = "padding:8px 10px; border-bottom:1px solid #e3e3e3; vertical-align:top; text-align:left"
    added = f"{cell}; font-weight:bold; color:#0B5345"

    def needs(r: TeamReport) -> str:
        titles = "".join(f"<p style='margin:0 0 6px'>{esc(f.title)}</p>" for f in r.findings)
        return titles or f"<span style='{muted}'>None</span>"

    rows = "".join(
        f"<tr><td style='{cell}'>{link(r.team)}<br><span style='{muted}'>{esc(team_label(r.team))}</span></td>"
        f"<td style='{cell}'>{esc(asked_about(r))}</td>"
        f"<td style='{added if r.game_lists else cell}'>{esc('; '.join(r.outcomes))}</td>"
        f"<td style='{cell}'>{needs(r)}</td></tr>"
        for r in reports
    )
    parts = [
        "<div style='font-family:Arial,Helvetica,sans-serif; font-size:15px; line-height:1.45; "
        "color:#1a1a1a; max-width:720px'>",
        "<h2 style='margin:0; color:#0B5345'>Missing-game requests</h2>",
        f"<p style='margin:2px 0 12px; {muted}'>{esc(label)}</p>",
        f"<p style='margin:0 0 12px'><b>{esc(tally(reports))}</b></p>",
        *(f"<p style='margin:0 0 12px; padding:8px 10px; background:#fff4d6'>{esc(c)}</p>" for c in caveats),
        "<table cellpadding='0' cellspacing='0' style='border-collapse:collapse; width:100%; font-size:14px'>"
        f"<tr style='background:#eef3f1'><th style='{cell}'>Team</th><th style='{cell}'>Asked about</th>"
        f"<th style='{cell}'>What the scrape added</th><th style='{cell}'>Needs a look</th></tr>{rows}</table>",
    ]
    for r in reports:
        if not (r.game_lists or r.findings):
            continue
        parts.append(
            f"<h3 style='margin:28px 0 0; font-size:17px'>{link(r.team)}</h3>"
            f"<p style='margin:0 0 6px; {muted}'>{esc(team_label(r.team))}, asked about {esc(asked_about(r))}</p>"
        )
        for title, games in r.game_lists:
            parts.append(f"<p style='margin:10px 0 0'><b>{title} ({len(games)})</b></p>")
            parts.append(bullets([esc(g) for g in listed(games)]))
        for f in r.findings:
            parts.append(f"<p style='margin:14px 0 0'><b style='color:#9a3412'>{esc(f.title)}</b></p>")
            items = [f"{link(row)} {esc(text)}" for row, text in f.teams] + [esc(d) for d in f.details]
            if items:
                parts.append(bullets(items))
            parts.append(f"<p style='margin:4px 0 0'>What to do: {esc(f.next_step)}</p>")
    parts.append(f"<p style='margin:28px 0 0; {muted}'>{esc(FOOTER)}</p></div>")
    return "\n".join(parts)


def mark_reported(sb, clicks: list[dict]) -> int:
    """Stamp the emailed clicks so no later scheduled run emails them again; a click already
    stamped keeps the time it was first reported. Returns how many were stamped."""
    now = datetime.now(timezone.utc).isoformat()
    stamped = 0
    for batch in batched(sorted(c["id"] for c in clicks)):
        rows = (
            sb.table("missing_game_clicks")
            .update({"reported_at": now})
            .in_("id", batch)
            .is_("reported_at", "null")
            .execute()
            .data
        )
        stamped += len(rows or [])
    return stamped


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument(
        "--end",
        type=datetime.fromisoformat,
        help="re-send the 3-hour window ending here, Arizona time unless an offset is given "
        "(default: every click not yet reported)",
    )
    ap.add_argument("--dry-run", action="store_true", help="print the report; send no email and stamp no click")
    args = ap.parse_args()

    sb = get_client()
    if args.end is None:
        end = window_end(datetime.now(timezone.utc) - REPORT_DELAY)
        clicks = fetch_unreported_clicks(sb, end)
        oldest = datetime.fromisoformat(clicks[0]["clicked_at"]) if clicks else end - timedelta(hours=WINDOW_HOURS)
        # The start of the oldest click's window.
        start = window_end(oldest)
    else:
        end = args.end if args.end.tzinfo else args.end.replace(tzinfo=ARIZONA)
        start = end - timedelta(hours=WINDOW_HOURS)
        clicks = fetch_clicks(sb, start, end)
    label = window_label(start, end)
    reports, caveats = investigate(sb, clicks)
    if args.dry_run:
        print(render_text(reports, caveats, label))
        logger.info(f"Dry run: no email sent ({subject(reports, label)})")
        return 0
    if not clicks:
        logger.info(f"No clicks in {label}, so no email was sent.")
        return 0
    if not send_email(ALERT_EMAIL, subject(reports, label), render_html(reports, caveats, label)):
        logger.error("The report could not be emailed")
        return 1
    stamped = mark_reported(sb, clicks)
    logger.info(f"Report on {len(reports)} team(s) from {label} emailed to {ALERT_EMAIL}; {stamped} click(s) stamped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
