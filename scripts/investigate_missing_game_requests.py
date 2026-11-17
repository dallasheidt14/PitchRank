#!/usr/bin/env python3
"""Investigate each "find missing game" request and email what may be wrong with the team.

A click on "find missing game" queues a GotSport scrape of the team
(frontend/app/api/scrape-missing-game). The scrape is often not the fix: the game can sit on
another row of the same squad, the team can be filed on the wrong age board, or the game can
come from a provider the GotSport scrape never reads. For every team clicked in one 3-hour
window this reports:

  1. the scrape: how each request ended, and the team's games on and beside the requested date
  2. possible duplicates: live rows of the same gender, in the team's state or with none, in its
     age group or the one either side, whose names read as the same squad, with their game evidence
  3. the profile: the stored age group against the age the name states and the ages this
     season's opponents' names state, the gender against the name, and a missing state
  4. providers: whether the team has a GotSport link the scrape can use, and every other
     provider it is linked to, with how that provider is refreshed

Report only: it reads the database and sends at most one email to ALERT_EMAIL. Each finding names a
next step; the skills it points at make the decisions and the writes. A live run logs counts
only, because Actions logs are public and the report names the teams subscribers asked about.

Clicks come from missing_game_clicks; scrape_requests cannot say which teams were clicked.

Usage:
    python scripts/investigate_missing_game_requests.py                    # the latest 3-hour window
    python scripts/investigate_missing_game_requests.py --end 2026-11-16T11:00
    python scripts/investigate_missing_game_requests.py --dry-run          # print, send nothing
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

CLICK_COLS = "id,team_id_master,game_date,clicked_at,scrape_request_id"
REQUEST_COLS = "id,status,games_found,error_message"
GAME_COLS = "id,home_team_master_id,away_team_master_id,game_date,home_score,away_score,is_excluded,provider_id"
OPPONENT_COLS = "team_id_master,team_name"

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

# Games this many days either side of a requested date are listed beside it, because a
# provider's date and the date a parent remembers can differ by a day.
DATE_SLACK_DAYS = 1

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
    problem: bool = True


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
class TeamReport:
    team: dict
    clicks: list[dict]
    scrape: list[str]
    findings: list[Finding] = field(default_factory=list)

    @property
    def problems(self) -> list[Finding]:
        return [f for f in self.findings if f.problem]


def window_end(now: datetime) -> datetime:
    now = now.astimezone(timezone.utc)
    return now.replace(hour=now.hour - now.hour % WINDOW_HOURS, minute=0, second=0, microsecond=0)


def window_label(start: datetime, end: datetime) -> str:
    return f"{start.astimezone(ARIZONA):%Y-%m-%d %H:%M} to {end.astimezone(ARIZONA):%Y-%m-%d %H:%M} Arizona time"


def fetch_clicks(sb, start: datetime, end: datetime) -> list[dict]:
    """The window's clicks, oldest first, each with the queue request it landed on under
    `request` (None when the queue refused the click, or the request is gone)."""
    clicks = page(
        lambda: (
            sb.table("missing_game_clicks")
            .select(CLICK_COLS)
            .gte("clicked_at", start.isoformat())
            .lt("clicked_at", end.isoformat())
        ),
        "id",
    )
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
        return f"{len(doubled)} game(s) stored on both rows (same opponent, same day)"
    holds = sorted({f.date for f in theirs} & requested)
    if holds:
        return f"holds a game on the requested date ({', '.join(holds)})"
    shared = {f.opponent for f in mine if f.date >= SEASON_START and f.opponent} & {
        f.opponent for f in theirs if f.date >= SEASON_START and f.opponent
    }
    if len(shared) >= MIN_SHARED_OPPONENTS:
        return f"schedule split across both rows: {len(shared)} shared opponents this season, never the same day"
    if score >= NAME_ONLY_SCORE_MIN:
        return "same squad by name; no game evidence either way"
    return None


def describe(row: dict, fixtures: list[Fixture], providers: dict) -> str:
    shown = visible(fixtures)
    last = max((f.date for f in shown if f.date), default="never")
    return (
        f"{row['team_name']} ({row['age_group']}, {row['club_name'] or 'no club'}, "
        f"{providers.get(row['provider_id'], '?')}, {len(shown)} games, last {last}) "
        f"{SITE_URL}/teams/{row['team_id_master']}"
    )


def duplicate_finding(team, candidates, sched, self_play, requested, providers, kept_apart) -> Finding | None:
    lines = []
    for row, score in candidates:
        reason = duplicate_reason(team["team_id_master"], row["team_id_master"], sched, self_play, requested, score)
        if reason:
            lines.append(f"{describe(row, sched[row['team_id_master']], providers)}: {reason}")
    if not lines:
        return None
    if kept_apart:
        lines.append(f"{kept_apart} similar row(s) left out: already decided Keep separate")
    return Finding(
        "Possible duplicate rows",
        lines,
        "Check each pair with the merging-duplicate-teams skill before merging; "
        "a row in another age group may also mean this one is on the wrong board.",
    )


def self_play_finding(team: dict, self_play: set[str]) -> Finding | None:
    if team["team_id_master"] not in self_play:
        return None
    return Finding(
        "This row has a game against itself",
        ["A row that plays itself holds two squads, so no duplicate is suggested for it."],
        "Split the row (merging-duplicate-teams skill, fused rows).",
    )


def age_label(ages: set[int]) -> str:
    return " or ".join(f"u{a}" for a in sorted(ages))


def name_age_findings(team: dict) -> list[Finding]:
    for name in dict.fromkeys(filter(None, (team["team_name"], team["team_name_original"]))):
        ages = read_name(name).ages
        if ages and ages_contradict(ages, team["age_group"]):
            return [
                Finding(
                    f"Name says {age_label(ages)}, stored {team['age_group']}",
                    [f'"{name}"'],
                    "Check with the correcting-team-age-groups skill. A two-year band in the "
                    "name decides; a bare birth year can mean either of two age groups.",
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
            f"This season's opponents point to {leading}, stored {team['age_group']}",
            [f"{count} of {total} opponents whose names state an age are {leading}"],
            "Check with the correcting-team-age-groups skill. A squad that plays up all season is labelled correctly.",
        )
    ]


def gender_and_state_findings(team: dict) -> list[Finding]:
    findings = []
    said = stated_gender(registered_name(team))
    if said and said != team["gender"]:
        findings.append(
            Finding(
                f"Name says {said}, stored {team['gender']}",
                [f'"{registered_name(team)}"'],
                "Fix the gender; the name settles it.",
            )
        )
    if not team["state_code"]:
        findings.append(
            Finding(
                "No state",
                ["The team is on no state board."],
                "Fill it with the assigning-team-states skill.",
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
                "No GotSport link, so the scrape cannot reach this team",
                [f"Linked only to: {', '.join(sorted(links)) or 'nothing'}"],
                "Find the squad's GotSport team and link it to this row, then request the scrape again.",
            )
        )
    elif len(gotsport) >= FUSED_REGISTRATION_THRESHOLD:
        findings.append(
            Finding(
                f"{len(gotsport)} GotSport registrations on one row",
                [f"GotSport ids: {', '.join(sorted(gotsport))}"],
                "Check whether the row fuses several squads (merging-duplicate-teams skill).",
            )
        )
    if links:
        findings.append(
            Finding(
                "Also linked to providers the GotSport scrape never reads",
                [f"{code}: {PROVIDER_REFRESH.get(code, DEFAULT_REFRESH)}" for code in sorted(links)],
                "If the missing game was played there, it arrives through that provider's import, not this click.",
                problem=still_missing,
            )
        )
    return findings


def scrape_outcome(click: dict) -> str:
    r = click["request"]
    if r is None:
        if click["scrape_request_id"]:
            return "queue request no longer on record"
        return "not scraped for this date: the team's queued request is for another date or registration"
    if r["status"] == "completed":
        return f"scraped, {r['games_found'] or 0} games found"
    if r["status"] == "failed":
        message = _API_KEY.sub("apikey=<redacted>", r["error_message"] or "no message")
        return f"failed: {message[:160]}"
    return f"not scraped yet ({r['status']})"


def scrape_lines(clicks: list[dict], fixtures: list[Fixture], opponents: dict, providers: dict) -> list[str]:
    lines = []
    for click in clicks:
        lines.append(f"Requested {click['game_date']}: {scrape_outcome(click)}")
        asked = date.fromisoformat(click["game_date"])
        near = sorted(
            (f for f in fixtures if f.date and abs((date.fromisoformat(f.date) - asked).days) <= DATE_SLACK_DAYS),
            key=lambda f: f.date,
        )
        for f in near:
            score = "no score" if None in f.score else f"{f.score[0]}-{f.score[1]}"
            opponent = (opponents.get(f.opponent) or {}).get("team_name", "unknown opponent")
            hidden = " [hidden]" if f.game["is_excluded"] else ""
            lines.append(f"  {f.date} vs {opponent}, {score}, {providers.get(f.game['provider_id'], '?')}{hidden}")
        if not any(f.date == click["game_date"] for f in near):
            lines.append(f"  no game on record for {click['game_date']}")
    return lines


def hidden_game_finding(requested: set[str], fixtures: list[Fixture]) -> Finding | None:
    dates = sorted((requested & {f.date for f in fixtures}) - {f.date for f in visible(fixtures)})
    if not dates:
        return None
    return Finding(
        "The requested game is on record but hidden",
        [f"Hidden game on {d}" for d in dates],
        "Find why it was hidden before un-hiding it; the exclude scripts keep a rollback log.",
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
    return TeamReport(team, clicks, scrape_lines(clicks, fixtures, opponents, providers), [f for f in findings if f])


def investigate(sb, start: datetime, end: datetime) -> tuple[list[TeamReport], list[str]]:
    clicks = fetch_clicks(sb, start, end)
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
            caveats.append(f"A clicked team's row was not found ({team_id})")
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
    reports.sort(key=lambda r: (-len(r.problems), r.team["team_name"]))
    return reports, caveats


def heading(team: dict) -> str:
    return f"{team['team_name']} ({team['age_group']} {team['gender']}, {team['state_code'] or 'no state'})"


def subject(reports: list[TeamReport], label: str) -> str:
    flagged = sum(1 for r in reports if r.problems)
    return f"PitchRank: {len(reports)} missing-game request team(s), {flagged} need a look ({label})"


def render_text(reports: list[TeamReport], caveats: list[str], label: str) -> str:
    lines = [f"Missing-game requests, {label}: {len(reports)} team(s). Report only; nothing was changed."]
    lines += caveats
    for r in reports:
        lines += ["", heading(r.team), f"{SITE_URL}/teams/{r.team['team_id_master']}", *r.scrape]
        if not r.findings:
            lines.append("Nothing else found.")
        for f in r.findings:
            lines += [f"* {f.title}" + ("" if f.problem else " (for context)")]
            lines += [f"    {d}" for d in f.details]
            lines.append(f"    Next step: {f.next_step}")
    return "\n".join(lines)


def render_html(reports: list[TeamReport], caveats: list[str], label: str) -> str:
    def esc(value) -> str:
        return html.escape(str(value), quote=True)

    def link(team: dict) -> str:
        return f"<a href='{esc(SITE_URL)}/teams/{esc(team['team_id_master'])}'>{esc(team['team_name'])}</a>"

    def scrape_item(line: str) -> str:
        indent = " style='margin-left:20px'" if line.startswith("  ") else ""
        return f"<li{indent}>{esc(line.strip())}</li>"

    rows = "".join(
        f"<tr><td style='padding:6px 12px'>{link(r.team)}</td>"
        f"<td style='padding:6px 12px'>{esc(', '.join(sorted({c['game_date'] for c in r.clicks})))}</td>"
        f"<td style='padding:6px 12px'>{esc('; '.join(f.title for f in r.problems) or 'nothing found')}</td></tr>"
        for r in reports
    )
    parts = [
        f"<h2>Missing-game requests, {esc(label)}</h2>",
        f"<p>{len(reports)} team(s). Report only: nothing was changed.</p>",
        *(f"<p><b>{esc(c)}</b></p>" for c in caveats),
        "<table border='1' cellpadding='0' cellspacing='0' "
        "style='border-collapse:collapse; font-family:sans-serif; font-size:14px'>"
        "<tr style='background:#f5f5f5'><th style='padding:8px 12px; text-align:left'>Team</th>"
        "<th style='padding:8px 12px; text-align:left'>Requested</th>"
        f"<th style='padding:8px 12px; text-align:left'>Needs a look</th></tr>{rows}</table>",
    ]
    for r in reports:
        parts.append(f"<h3>{esc(heading(r.team))}</h3><p>{link(r.team)}</p>")
        parts.append("<ul>" + "".join(scrape_item(line) for line in r.scrape) + "</ul>")
        for f in r.findings:
            parts.append(f"<p><b>{esc(f.title)}</b>{'' if f.problem else ' (for context)'}</p>")
            parts.append("<ul>" + "".join(f"<li>{esc(d)}</li>" for d in f.details) + "</ul>")
            parts.append(f"<p>Next step: {esc(f.next_step)}</p>")
    parts.append("<p style='color:#666; font-size:12px'>Sent by the investigate-missing-game-requests workflow.</p>")
    return "\n".join(parts)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument(
        "--end",
        type=datetime.fromisoformat,
        help="end of the 3-hour window, Arizona time unless an offset is given (default: the latest boundary)",
    )
    ap.add_argument("--dry-run", action="store_true", help="print the report and send no email")
    args = ap.parse_args()

    if args.end is None:
        end = window_end(datetime.now(timezone.utc))
    else:
        end = args.end if args.end.tzinfo else args.end.replace(tzinfo=ARIZONA)
    start = end - timedelta(hours=WINDOW_HOURS)
    label = window_label(start, end)
    reports, caveats = investigate(get_client(), start, end)
    if args.dry_run:
        print(render_text(reports, caveats, label))
        logger.info(f"Dry run: no email sent ({subject(reports, label)})")
        return 0
    if not reports:
        logger.info(f"No clicks in {label}, so no email was sent.")
        return 0
    if not send_email(ALERT_EMAIL, subject(reports, label), render_html(reports, caveats, label)):
        logger.error("The report could not be emailed")
        return 1
    logger.info(f"Report on {len(reports)} team(s) from {label} emailed to {ALERT_EMAIL}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
