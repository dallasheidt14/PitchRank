#!/usr/bin/env python3
"""Report which EA teams of one age match teams PitchRank already holds. Read-only.

A link is proposed only when the club, the age and the EA tier all agree: an EA team never
matches an EA2 name, and HD/AD/MLS NEXT names and modular11 rows are never candidates. This is
its own same-tier rule; it does not loosen ``has_protected_division``.

Usage:
    python scripts/match_modular11_ea_teams.py --age u11
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from functools import lru_cache

from src.utils.club_normalizer import are_same_club

EA2_RE = re.compile(r"\bEA2\b", re.IGNORECASE)
EA_RE = re.compile(r"\bEA\b", re.IGNORECASE)
PROTECTED_RE = re.compile(r"\b(?:HD|AD|MLS\s*NEXT)\b", re.IGNORECASE)


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


@dataclass(frozen=True)
class ReportRow:
    ea: EaTeam
    bucket: str
    reason: str
    candidates: tuple[dict, ...]


@lru_cache(maxsize=None)
def _same_club(ea_club: str, db_club: str) -> bool:
    return are_same_club(ea_club, db_club)


def _club_hits(ea: EaTeam, db_teams: list[dict]) -> list[dict]:
    return [d for d in db_teams if _same_club(ea.club_name, d.get("club_name") or d["team_name"])]


def classify(ea_teams: list[EaTeam], db_teams: list[dict]) -> list[ReportRow]:
    hits = {ea.provider_team_id: _club_hits(ea, db_teams) for ea in ea_teams}
    tagged = {
        ea.provider_team_id: [d for d in hits[ea.provider_team_id] if tier_marker(d["team_name"]) in ea.tiers]
        for ea in ea_teams
    }
    claims: dict[str, set[str]] = defaultdict(set)
    for ea_id, candidates in tagged.items():
        for candidate in candidates:
            claims[candidate["team_id_master"]].add(ea_id)
    rows = []
    for ea in ea_teams:
        mine = tagged[ea.provider_team_id]
        shared = sorted({other for c in mine for other in claims[c["team_id_master"]]} - {ea.provider_team_id})
        if len(mine) == 1 and not shared:
            rows.append(ReportRow(ea, "confident", "one same-club, same-age, same-tier team", tuple(mine)))
        elif mine:
            if len(mine) > 1:
                reason = f"{len(mine)} candidates"
            else:
                reason = f"candidate also fits EA team(s) {', '.join(shared)}"
            rows.append(ReportRow(ea, "review", reason, tuple(mine)))
        else:
            untagged = [d for d in hits[ea.provider_team_id] if tier_marker(d["team_name"]) is None]
            if untagged:
                rows.append(ReportRow(ea, "review", "club and age match, no EA tier in name", tuple(untagged)))
            else:
                rows.append(ReportRow(ea, "no_match", "", ()))
    return rows
