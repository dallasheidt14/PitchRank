#!/usr/bin/env python3
"""Report which EA teams of one age match teams PitchRank already holds. Read-only.

A link is proposed only when the club, the age and the EA tier all agree: an EA team never
matches an EA2 name, and HD/AD/MLS NEXT names and modular11 rows are never candidates. This is
its own same-tier rule; it does not loosen ``has_protected_division``.

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

from src.utils.club_normalizer import are_same_club  # noqa: E402
from supabase import create_client  # noqa: E402

EA2_RE = re.compile(r"\bEA2\b", re.IGNORECASE)
EA_RE = re.compile(r"\bEA\b", re.IGNORECASE)
PROTECTED_RE = re.compile(r"\b(?:HD|AD|MLS\s*NEXT)\b", re.IGNORECASE)
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


def _provider_codes(sb) -> dict[str, str]:
    return {r["id"]: r["code"] for r in sb.table("providers").select("id, code").execute().data}


def fetch_db_teams(sb, age_group: str) -> list[dict]:
    codes = _provider_codes(sb)
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
        eligible.append({**row, "provider_code": code})
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
