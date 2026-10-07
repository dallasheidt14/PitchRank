#!/usr/bin/env python3
"""Report which EA teams of one age match teams PitchRank already holds. Read-only.

A link is proposed only when the club, the club's state, the age and the EA tier all agree: an
EA team never matches an EA2 name, and HD/AD/MLS NEXT names and modular11 rows are never
candidates. This is its own same-tier rule; it does not loosen ``has_protected_division``.

A club branch, a candidate with no state, a squad qualifier in the name, or a team two EA teams
claim can be reviewed but never linked with confidence. A team already linked to another EA team
this season is not a candidate at all.

Usage:
    python scripts/match_modular11_ea_teams.py --age u11
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.scrape_modular11_ea import season_bounds  # noqa: E402
from src.models.modular11_ea_keys import club_state, ea_key, refuse_raw_keys, split_ea_key  # noqa: E402
from src.models.modular11_ea_matcher import PROVIDER_CODE  # noqa: E402
from supabase import create_client  # noqa: E402

EA2_RE = re.compile(r"\bEA2\b", re.IGNORECASE)
EA_RE = re.compile(r"\bEA1?\b", re.IGNORECASE)
PROTECTED_RE = re.compile(r"\b(?:HD|AD|MLS\s*NEXT)\b", re.IGNORECASE)
NON_WORD_RE = re.compile(r"[^a-z0-9/]+")
AGE_TOKEN_RE = re.compile(r"^(?:[bg]?u?[0-9]{2,4}(?:/[0-9]{2,4})?[bg]?|ea[12]?)$")
CLUB_WORD_RE = re.compile(r"[^a-z0-9]+")
GENERIC = frozenset(
    {"sc", "fc", "soccer", "club", "futbol", "football", "academy", "youth", "the", "de", "cf", "ac", "sa", "united"}
)
TIER_TOKENS = frozenset({"ea", "ea1", "ea2"})
PLAIN_AFTER_TIER = frozenset({"boys", "b", "premier", "academy", "elite"})
COLOURS = frozenset({"red", "blue", "white", "black", "gold", "silver", "orange", "navy", "green", "grey", "purple"})
BRANCH = "different branch"
LINEAGE = "last season's age-below team"
MIN_CLASH_DATES = 2
PAGE_SIZE = 1000
REPORT_COLUMNS = [
    "provider_team_id",
    "club_name",
    "display_name",
    "tiers",
    "bucket",
    "reason",
    "candidate_ids",
    "candidate_names",
    "candidate_clubs",
    "candidate_providers",
    "candidate_states",
]
CANDIDATE_FIELDS = (
    ("candidate_ids", "team_id_master"),
    ("candidate_names", "team_name"),
    ("candidate_clubs", "club_name"),
    ("candidate_providers", "provider_code"),
    ("candidate_states", "state_code"),
)


def tier_marker(name: str) -> str | None:
    if EA2_RE.search(name):
        return "EA2"
    if EA_RE.search(name):
        return "EA"
    return None


def is_protected(name: str) -> bool:
    return bool(PROTECTED_RE.search(name))


@dataclass(frozen=True)
class EaTeam:
    provider_team_id: str
    club_name: str
    display_name: str
    age_group: str
    tiers: frozenset[str]
    state: str
    season: int

    @property
    def key(self) -> str:
        return ea_key(self.provider_team_id, self.season)


@dataclass(frozen=True)
class ReportRow:
    ea: EaTeam
    bucket: str
    reason: str
    candidates: tuple[dict, ...]


def _name_tokens(name: str) -> tuple[str, ...]:
    return tuple(NON_WORD_RE.sub(" ", name.lower()).split())


@lru_cache(maxsize=None)
def _name_led_by_club(ea_club: str, team_name: str) -> bool:
    """The team's own name opens with the EA club and goes straight on to an age or tier.

    Requiring the age right after the club keeps a branch out: "ALBION SC Atlanta Metro B10"
    does not open with club "ALBION SC Atlanta" followed by an age.
    """
    club, team = _name_tokens(ea_club), _name_tokens(team_name)
    return len(team) > len(club) and team[: len(club)] == club and bool(AGE_TOKEN_RE.match(team[len(club)]))


def _club_words(club: str) -> list[str]:
    return [w for w in CLUB_WORD_RE.sub(" ", club.lower()).split() if w not in GENERIC]


@lru_cache(maxsize=None)
def club_relation(ea_club: str, candidate_club: str | None, candidate_name: str) -> str:
    """Is the candidate the EA club ("same"), a sibling site of it ("branch"), or neither ("other")?

    A branch differs from the club by a place or sub-site word, never by a generic one, so the
    test reads the difference between the names rather than any list of branch words:
    Santa Ana vs Santa Monica, TFA OC vs TFA SGV, Atlanta vs Atlanta Metro.
    """
    ea_words = _club_words(ea_club)
    cand_words = _club_words(candidate_club or candidate_name)
    if set(ea_words) == set(cand_words) or _name_led_by_club(ea_club, candidate_name):
        return "same"
    ea_set, cand_set = set(ea_words), set(cand_words)
    if ea_set < cand_set or cand_set < ea_set:
        return "branch"
    if ea_words and cand_words and ea_words[0] == cand_words[0]:
        return "branch"
    return "other"


def squad_words(ea: EaTeam, team_name: str) -> list[str]:
    """Words in the candidate's name that mark a different squad, unless the EA team's own name has them.

    Three places carry one: a colour anywhere ("B09/10 Red EA"), a word between the club and the
    age ("San Diego EC B10"), and a word after the tier marker ("B10 EA Mora").
    """
    own = set(_name_tokens(ea.display_name)) | set(_name_tokens(ea.club_name))
    tokens = _name_tokens(team_name)
    words = [token for token in tokens if token in COLOURS and token not in own]
    club = _name_tokens(ea.club_name)
    if tokens[: len(club)] == club:
        for token in tokens[len(club) :]:
            if AGE_TOKEN_RE.match(token):
                break
            if token not in own and token not in GENERIC:
                words.append(token)
    markers = [i for i, token in enumerate(tokens) if token in TIER_TOKENS]
    if markers:
        words += [
            token
            for token in tokens[markers[-1] + 1 :]
            if not AGE_TOKEN_RE.match(token) and token not in own and token not in PLAIN_AFTER_TIER
        ]
    return words


def squad_qualifier(ea: EaTeam, team_name: str) -> str | None:
    words = squad_words(ea, team_name)
    return words[0] if words else None


def schedule_conflict(ea_games: list[dict], cand_games: list[dict]) -> bool:
    """The candidate was playing another club on dates the EA team played its league games.

    No single game decides: a doubleheader or a mis-dated row can put one game on the wrong
    day, so it takes MIN_CLASH_DATES distinct dates.
    """
    ea_by_date: dict[str, list[dict]] = defaultdict(list)
    for game in ea_games:
        ea_by_date[game["game_date"]].append(game)
    clashes = set()
    for game in cand_games:
        theirs = ea_by_date.get(game["game_date"])
        if theirs and all(
            club_relation(e["opponent_club"] or e["opponent_name"], game["opponent_club"], game["opponent_name"])
            == "other"
            for e in theirs
        ):
            clashes.add(game["game_date"])
    return len(clashes) >= MIN_CLASH_DATES


def lineage_target(age_minus_one_uid: str, season: int, links: dict[str, str]) -> str | None:
    """The team linked last season to the club's slot one age below, which has since moved up."""
    return links.get(ea_key(age_minus_one_uid, season - 1))


def _hold(ea: EaTeam, team: dict, ea_games: dict[str, list[dict]], cand_games: dict[str, list[dict]]) -> str | None:
    """None when the team cannot be this EA team; else why it cannot be confident ("" when it can)."""
    relation = club_relation(ea.club_name, team.get("club_name"), team["team_name"])
    if relation == "other":
        return None
    state = (team.get("state_code") or "").strip()
    if state and state != ea.state:
        return None
    if any(key != ea.key and split_ea_key(key)[1] == ea.season for key in team.get("ea_keys", ())):
        return None
    if schedule_conflict(ea_games.get(ea.provider_team_id, []), cand_games.get(team["team_id_master"], [])):
        return None
    if relation == "branch":
        return BRANCH
    if not state:
        return "no state"
    qualifier = squad_qualifier(ea, team["team_name"])
    return f"squad qualifier: {qualifier}" if qualifier else ""


def classify(
    ea_teams: list[EaTeam],
    db_teams: list[dict],
    ea_games: dict[str, list[dict]] | None = None,
    cand_games: dict[str, list[dict]] | None = None,
    lineage: dict[str, str] | None = None,
) -> list[ReportRow]:
    """``lineage`` maps an EA team to last season's link of its club's age-below slot (see lineage_target)."""
    ea_games, cand_games, lineage = ea_games or {}, cand_games or {}, lineage or {}
    hits = {
        ea.provider_team_id: [(d, why) for d in db_teams if (why := _hold(ea, d, ea_games, cand_games)) is not None]
        for ea in ea_teams
    }
    tagged = {}
    for ea in ea_teams:
        found = hits[ea.provider_team_id]
        mine = [(d, why) for d, why in found if tier_marker(d["team_name"]) in ea.tiers]
        lineal = [(d, why) for d, why in mine if d["team_id_master"] == lineage.get(ea.provider_team_id)]
        tagged[ea.provider_team_id] = lineal or mine
    claims: dict[str, set[str]] = defaultdict(set)
    for ea_id, candidates in tagged.items():
        for candidate, why in candidates:
            if why != BRANCH:
                claims[candidate["team_id_master"]].add(ea_id)
    rows = []
    for ea in ea_teams:
        mine = tagged[ea.provider_team_id]
        shared = sorted(
            {other for d, why in mine if why != BRANCH for other in claims[d["team_id_master"]]} - {ea.provider_team_id}
        )
        holds = sorted({why for _, why in mine if why})
        teams = tuple(d for d, _ in mine)
        if len(mine) == 1 and not shared and not holds:
            lineal = mine[0][0]["team_id_master"] == lineage.get(ea.provider_team_id)
            reason = LINEAGE if lineal else "one same-club, same-age, same-tier team"
            rows.append(ReportRow(ea, "confident", reason, teams))
        elif mine:
            reasons = ([f"{len(mine)} candidates"] if len(mine) > 1 else []) + holds
            if shared:
                reasons.append(f"claimed by another EA team: {', '.join(shared)}")
            rows.append(ReportRow(ea, "review", "; ".join(reasons), teams))
        else:
            untagged = tuple(d for d, _ in hits[ea.provider_team_id] if tier_marker(d["team_name"]) is None)
            if untagged:
                rows.append(ReportRow(ea, "review", "club and age match, no EA tier in name", untagged))
            else:
                rows.append(ReportRow(ea, "no_match", "", ()))
    return rows


def _provider_codes(sb) -> dict[str, str]:
    return {r["id"]: r["code"] for r in sb.table("providers").select("id, code").execute().data}


def _ea_links(sb, codes: dict[str, str]) -> dict[str, set[str]]:
    """Per PitchRank team, the EA keys its approved modular11_ea aliases name."""
    links: dict[str, set[str]] = defaultdict(set)
    for provider_id in (pid for pid, code in codes.items() if code == PROVIDER_CODE):
        offset = 0
        while True:
            page = (
                sb.table("team_alias_map")
                .select("provider_team_id, team_id_master")
                .eq("provider_id", provider_id)
                .eq("review_status", "approved")
                .order("id")
                .range(offset, offset + PAGE_SIZE - 1)
                .execute()
                .data
            )
            for row in page:
                links[row["team_id_master"]].add(row["provider_team_id"])
            if len(page) < PAGE_SIZE:
                break
            offset += PAGE_SIZE
    refuse_raw_keys(key for keys in links.values() for key in keys)
    return links


def fetch_db_teams(sb, age_group: str) -> list[dict]:
    codes = _provider_codes(sb)
    ea_links = _ea_links(sb, codes)
    rows, offset = [], 0
    while True:
        page = (
            sb.table("teams")
            .select("team_id_master, team_name, club_name, state_code, provider_id, age_group, gender")
            .eq("age_group", age_group)
            .eq("gender", "Male")
            .or_("is_deprecated.is.null,is_deprecated.eq.false")
            .order("team_id_master")
            .range(offset, offset + PAGE_SIZE - 1)
            .execute()
            .data
        )
        rows.extend(page)
        if len(page) < PAGE_SIZE:
            break
        offset += PAGE_SIZE
    eligible = []
    for row in rows:
        code = codes.get(row.get("provider_id"), "")
        if code == "modular11" or is_protected(row["team_name"]):
            continue
        eligible.append({**row, "provider_code": code, "ea_keys": frozenset(ea_links.get(row["team_id_master"], ()))})
    return eligible


def _paged(build) -> list[dict]:
    """Every row of an ordered query; ``build`` returns a fresh query for each page."""
    rows, offset = [], 0
    while True:
        page = build().range(offset, offset + PAGE_SIZE - 1).execute().data
        rows.extend(page)
        if len(page) < PAGE_SIZE:
            return rows
        offset += PAGE_SIZE


def _merge_map(sb, column: str, ids: list[str]) -> list[dict]:
    rows = []
    for start in range(0, len(ids), 100):
        batch = ids[start : start + 100]
        rows += _paged(
            lambda b=batch: (
                sb.table("team_merge_map")
                .select("deprecated_team_id, canonical_team_id")
                .in_(column, b)
                .order("deprecated_team_id")
            )
        )
    return rows


def fetch_candidate_games(sb, ids: list[str], season: int) -> dict[str, list[dict]]:
    """Per candidate, its non-excluded games this season as (date, opponent name, opponent club).

    Merges are resolved both ways: games stored under a team merged into a candidate count as
    the candidate's, and an opponent is named by the team it was merged into.
    """
    start, end = (bound[:10] for bound in season_bounds(date(season, 8, 1)))
    owner = {team_id: team_id for team_id in ids}
    for row in _merge_map(sb, "canonical_team_id", ids):
        owner[row["deprecated_team_id"]] = row["canonical_team_id"]
    played: list[tuple[str, str, str]] = []
    keys = sorted(owner)
    for side, other in (("home", "away"), ("away", "home")):
        for offset in range(0, len(keys), 100):
            batch = keys[offset : offset + 100]
            games = _paged(
                lambda b=batch, s=side: (
                    sb.table("games")
                    .select("id, game_date, home_team_master_id, away_team_master_id")
                    .in_(f"{s}_team_master_id", b)
                    .eq("is_excluded", False)
                    .gte("game_date", start)
                    .lte("game_date", end)
                    .order("id")
                )
            )
            played += [
                (owner[g[f"{side}_team_master_id"]], g["game_date"][:10], g[f"{other}_team_master_id"]) for g in games
            ]
    opponents = sorted({opp for _, _, opp in played if opp})
    canonical = {
        r["deprecated_team_id"]: r["canonical_team_id"] for r in _merge_map(sb, "deprecated_team_id", opponents)
    }
    resolved = sorted({canonical.get(opp, opp) for opp in opponents})
    names = {}
    for offset in range(0, len(resolved), 100):
        batch = resolved[offset : offset + 100]
        for row in (
            sb.table("teams").select("team_id_master, team_name, club_name").in_("team_id_master", batch).execute().data
        ):
            names[row["team_id_master"]] = row
    out: dict[str, list[dict]] = defaultdict(list)
    for team_id, game_date, opp in played:
        team = names.get(canonical.get(opp, opp), {})
        out[team_id].append(
            {
                "game_date": game_date,
                "opponent_name": team.get("team_name") or "",
                "opponent_club": team.get("club_name"),
            }
        )
    return out


def _ea_schedules(games: list[dict], clubs: dict[str, str]) -> dict[str, list[dict]]:
    """Per EA team, its played games from its own side, as fetch_candidate_games reports them."""
    out: dict[str, list[dict]] = defaultdict(list)
    for game in games:
        if game["status"] != "played" or not (game["home_team_id"] and game["away_team_id"]):
            continue
        for team, opponent, opponent_name in (
            (game["home_team_id"], game["away_team_id"], game["away_name"]),
            (game["away_team_id"], game["home_team_id"], game["home_name"]),
        ):
            out[team].append(
                {
                    "game_date": game["game_date"][:10],
                    "opponent_name": opponent_name,
                    "opponent_club": clubs.get(opponent),
                }
            )
    return out


def _lineage(below: Path, rows: list[dict], links: dict[str, str]) -> dict[str, str]:
    """Per EA team, last season's link of its club's same-tier slot one age below."""
    if not below.exists():
        return {}
    slots = {(r["academy_id"], r["name_tier"]): r["provider_team_id"] for r in _read_csv(below)}
    out = {}
    for row in rows:
        uid = slots.get((row["academy_id"], row["name_tier"]))
        target = lineage_target(uid, int(row["season"]), links) if uid else None
        if target:
            out[row["provider_team_id"]] = target
    return out


def _read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _load_ea_teams(path: Path) -> list[EaTeam]:
    with path.open(encoding="utf-8") as handle:
        return [
            EaTeam(
                provider_team_id=r["provider_team_id"],
                club_name=r["club_name"],
                display_name=r["display_name"],
                age_group=r["age_group"],
                tiers=frozenset({r["name_tier"]}),
                state=club_state(r["club_name"]),
                season=int(r["season"]),
            )
            for r in csv.DictReader(handle)
        ]


def run(age: str, in_dir: Path, sb) -> dict[str, int]:
    age_dir = in_dir / age
    ea_teams = _load_ea_teams(age_dir / "teams.csv")
    db_teams = fetch_db_teams(sb, age)
    rows = _read_csv(age_dir / "teams.csv")
    games_path = age_dir / "games.csv"
    ea_games = (
        _ea_schedules(_read_csv(games_path), {r["provider_team_id"]: r["club_name"] for r in rows})
        if games_path.exists()
        else {}
    )
    cand_games = {}
    if ea_games and ea_teams:
        related = [
            d["team_id_master"]
            for d in db_teams
            if any(club_relation(ea.club_name, d.get("club_name"), d["team_name"]) != "other" for ea in ea_teams)
        ]
        cand_games = fetch_candidate_games(sb, related, ea_teams[0].season) if related else {}
    links = {key: d["team_id_master"] for d in db_teams for key in d["ea_keys"]}
    lineage = _lineage(in_dir / f"u{int(age[1:]) - 1}" / "teams.csv", rows, links)
    report = classify(ea_teams, db_teams, ea_games, cand_games, lineage)
    with (age_dir / "match_report.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=REPORT_COLUMNS)
        writer.writeheader()
        for row in report:
            writer.writerow(
                {
                    "provider_team_id": row.ea.provider_team_id,
                    "club_name": row.ea.club_name,
                    "display_name": row.ea.display_name,
                    "tiers": ";".join(sorted(row.ea.tiers)),
                    "bucket": row.bucket,
                    "reason": row.reason,
                    **{
                        column: "|".join(str(c.get(field) or "") for c in row.candidates)
                        for column, field in CANDIDATE_FIELDS
                    },
                }
            )
    return {bucket: sum(r.bucket == bucket for r in report) for bucket in ("confident", "review", "no_match")}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--age", required=True)
    parser.add_argument("--in-dir", type=Path, default=Path("data/modular11_ea"))
    args = parser.parse_args(argv)
    load_dotenv()
    url = os.environ.get("SUPABASE_URL") or os.environ.get("NEXT_PUBLIC_SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_KEY")
    if not url or not key:
        print("ERROR: missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY", file=sys.stderr)
        return 1
    counts = run(args.age, args.in_dir, create_client(url, key))
    print(" ".join(f"{name}={value}" for name, value in counts.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
