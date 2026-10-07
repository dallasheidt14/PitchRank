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
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.models.modular11_ea_keys import club_state, ea_key, split_ea_key  # noqa: E402
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


def squad_qualifier(ea: EaTeam, team_name: str) -> str | None:
    """A word in the candidate's name that marks a different squad, unless the EA team's own name has it.

    Three places carry one: a colour anywhere ("B09/10 Red EA"), a word between the club and the
    age ("San Diego EC B10"), and a word after the tier marker ("B10 EA Mora").
    """
    own = set(_name_tokens(ea.display_name)) | set(_name_tokens(ea.club_name))
    tokens = _name_tokens(team_name)
    for token in tokens:
        if token in COLOURS and token not in own:
            return token
    club = _name_tokens(ea.club_name)
    if tokens[: len(club)] == club:
        for token in tokens[len(club) :]:
            if AGE_TOKEN_RE.match(token):
                break
            if token not in own and token not in GENERIC:
                return token
    markers = [i for i, token in enumerate(tokens) if token in TIER_TOKENS]
    if markers:
        for token in tokens[markers[-1] + 1 :]:
            if not AGE_TOKEN_RE.match(token) and token not in own and token not in PLAIN_AFTER_TIER:
                return token
    return None


def _hold(ea: EaTeam, team: dict) -> str | None:
    """None when the team cannot be this EA team; else why it cannot be confident ("" when it can)."""
    relation = club_relation(ea.club_name, team.get("club_name"), team["team_name"])
    if relation == "other":
        return None
    state = (team.get("state_code") or "").strip()
    if state and state != ea.state:
        return None
    if any(key != ea.key and split_ea_key(key)[1] == ea.season for key in team.get("ea_keys", ())):
        return None
    if relation == "branch":
        return BRANCH
    if not state:
        return "no state"
    qualifier = squad_qualifier(ea, team["team_name"])
    return f"squad qualifier: {qualifier}" if qualifier else ""


def classify(ea_teams: list[EaTeam], db_teams: list[dict]) -> list[ReportRow]:
    hits = {ea.provider_team_id: [(d, why) for d in db_teams if (why := _hold(ea, d)) is not None] for ea in ea_teams}
    tagged = {}
    for ea in ea_teams:
        found = hits[ea.provider_team_id]
        tagged[ea.provider_team_id] = [(d, why) for d, why in found if tier_marker(d["team_name"]) in ea.tiers]
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
            rows.append(ReportRow(ea, "confident", "one same-club, same-age, same-tier team", teams))
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
    report = classify(_load_ea_teams(in_dir / age / "teams.csv"), fetch_db_teams(sb, age))
    with (in_dir / age / "match_report.csv").open("w", newline="", encoding="utf-8") as handle:
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
