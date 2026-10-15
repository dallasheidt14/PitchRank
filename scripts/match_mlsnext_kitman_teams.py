#!/usr/bin/env python3
"""Report which MLS NEXT squads from Kitman match teams PitchRank already holds. Read-only.

A squad is bridged to a live boys team already holding MLS NEXT, by club name, age and division.
That team carries an approved ``modular11`` alias (``{club}_U{age}_{HD|AD}``) or, for a team this
pipeline created in an earlier season, a Kitman alias. Only an exact club name makes a link confident; a
near spelling or a club branch goes to review, because near spellings include different clubs
(Los Angeles Sports Club vs Los Angeles Soccer Club, GFI Academy North vs South).

A squad already linked this season is reported as linked. A squad with no candidate is ``new``,
and the same club's teams at that age under another provider are listed as its candidates.

Usage:
    python scripts/match_mlsnext_kitman_teams.py
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.find_cross_provider_duplicates import load_merge_map, normalize, page, resolver  # noqa: E402
from scripts.match_modular11_ea_teams import _club_words, club_relation  # noqa: E402
from src.models.mlsnext_kitman_keys import club_state_or_blank, refuse_raw_keys, split_kitman_key  # noqa: E402
from src.models.mlsnext_kitman_matcher import PROVIDER_CODE  # noqa: E402
from supabase import create_client  # noqa: E402

BRIDGE_PROVIDER = "modular11"
ALIAS_RE = re.compile(r"[0-9]{1,9}_U[0-9]{1,2}_(HD|AD)", re.IGNORECASE)
DIVISIONS = ("HD", "AD")
BATCH = 100
REPORT_COLUMNS = [
    "provider_team_id",
    "key",
    "club_name",
    "display_name",
    "age_group",
    "division",
    "bucket",
    "reason",
    "state",
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


@dataclass(frozen=True)
class ReportRow:
    squad: dict
    bucket: str
    reason: str
    state: str
    candidates: tuple[dict, ...]


def _near_club(squad_club: str, team: dict) -> bool:
    """A sibling or spelling variant of the club. A club of only generic words ("SA United SC") has none."""
    shared = set(_club_words(squad_club)) & set(_club_words(team.get("club_name") or team["team_name"]))
    return bool(shared) and club_relation(squad_club, team.get("club_name"), team["team_name"]) in ("same", "branch")


def classify(
    squads: list[dict],
    bridge: list[dict],
    links: dict[str, str],
    other_provider_teams: list[dict] | None = None,
) -> list[ReportRow]:
    """``bridge``: the existing MLS NEXT teams, each with ``age_group`` and ``divisions``.

    ``links``: approved Kitman links by season key, every season. A team's link from an earlier
    season does not make it taken for this one.
    """
    other_provider_teams = other_provider_teams or []
    team_by_id = {t["team_id_master"]: t for t in bridge}
    keys_by_team: dict[str, set[str]] = defaultdict(set)
    for linked_key, team_id in links.items():
        keys_by_team[team_id].add(linked_key)
    tagged: dict[str, tuple[str, list[dict], str]] = {}
    for squad in squads:
        key, state = squad["key"], club_state_or_blank(squad["club_name"])
        if key in links:
            linked = team_by_id.get(links[key], {"team_id_master": links[key]})
            tagged[key] = ("linked", [linked], "already linked")
            continue
        season = split_kitman_key(key)[1]
        pool = [t for t in bridge if t["age_group"] == squad["age_group"] and squad["division"] in t["divisions"]]
        exact = [t for t in pool if normalize(t["club_name"]) == normalize(squad["club_name"])]
        free = [
            t
            for t in exact
            if not any(k != key and split_kitman_key(k)[1] == season for k in keys_by_team[t["team_id_master"]])
        ]
        if exact and not free:
            tagged[key] = ("review", exact, "its candidate is already linked to another squad this season")
        elif len(free) > 1:
            tagged[key] = ("review", free, f"{len(free)} candidates")
        elif free:
            candidate_state = (free[0].get("state_code") or "").strip()
            if state and candidate_state and state != candidate_state:
                tagged[key] = ("review", free, f"club table says {state}, candidate is in {candidate_state}")
            else:
                tagged[key] = ("confident", free, "exact club, age and division")
        else:
            near = [t for t in pool if _near_club(squad["club_name"], t)]
            if near:
                tagged[key] = ("review", near, "near club name, not exact")
            else:
                same_club = [
                    t
                    for t in other_provider_teams
                    if t["age_group"] == squad["age_group"]
                    and normalize(t["club_name"]) == normalize(squad["club_name"])
                ]
                known = any(normalize(t["club_name"]) == normalize(squad["club_name"]) for t in bridge)
                reason = "club has no team at this age and division" if known else "club not in our MLS NEXT data"
                tagged[key] = ("new", same_club, reason)
    claims: dict[str, set[str]] = defaultdict(set)
    for key, (bucket, candidates, _) in tagged.items():
        if bucket == "confident":
            for team in candidates:
                claims[team["team_id_master"]].add(key)
    rows = []
    for squad in squads:
        bucket, candidates, reason = tagged[squad["key"]]
        if bucket == "confident":
            shared = sorted(claims[candidates[0]["team_id_master"]] - {squad["key"]})
            if shared:
                bucket, reason = "review", f"claimed by another squad: {', '.join(shared)}"
        rows.append(ReportRow(squad, bucket, reason, club_state_or_blank(squad["club_name"]), tuple(candidates)))
    return rows


def _provider_ids(sb) -> dict[str, str]:
    return {r["code"]: r["id"] for r in sb.table("providers").select("id, code").execute().data}


def _approved_aliases(sb, provider_id: str) -> list[dict]:
    return page(
        lambda: sb.table("team_alias_map")
        .select("id, provider_team_id, team_id_master, division")
        .eq("provider_id", provider_id)
        .eq("review_status", "approved"),
        "id",
        size=1000,
    )


def fetch_bridge(sb, provider_ids: dict[str, str]) -> list[dict]:
    """Live boys teams that already hold MLS NEXT, merges resolved, with their divisions.

    A team holds MLS NEXT through a ``modular11`` alias (division in the id) or, from a
    previous season's run, a Kitman alias (division on the row). Without the second, a team this
    pipeline created would never be a candidate and the next season would create it again.
    """
    canonical = resolver(load_merge_map(sb))
    divisions: dict[str, set[str]] = defaultdict(set)
    via: dict[str, str] = {}
    for alias in _approved_aliases(sb, provider_ids[BRIDGE_PROVIDER]):
        if ALIAS_RE.fullmatch(alias["provider_team_id"]):
            team_id = canonical(alias["team_id_master"])
            divisions[team_id].add(alias["provider_team_id"][-2:].upper())
            via[team_id] = BRIDGE_PROVIDER
    kitman_id = provider_ids.get(PROVIDER_CODE)
    for alias in _approved_aliases(sb, kitman_id) if kitman_id else []:
        if alias.get("division") in DIVISIONS:
            team_id = canonical(alias["team_id_master"])
            divisions[team_id].add(alias["division"])
            via.setdefault(team_id, PROVIDER_CODE)
    ids = sorted(divisions)
    teams = []
    for start in range(0, len(ids), BATCH):
        teams += (
            sb.table("teams")
            .select("team_id_master, team_name, club_name, state_code, age_group, gender, is_deprecated")
            .in_("team_id_master", ids[start : start + BATCH])
            .execute()
            .data
        )
    return [
        {
            **t,
            "age_group": (t["age_group"] or "").lower(),
            "divisions": divisions[t["team_id_master"]],
            "provider_code": via[t["team_id_master"]],
        }
        for t in teams
        if t.get("gender") == "Male" and t.get("is_deprecated") is not True
    ]


def fetch_kitman_links(sb, provider_ids: dict[str, str]) -> dict[str, str]:
    provider_id = provider_ids.get(PROVIDER_CODE)
    aliases = _approved_aliases(sb, provider_id) if provider_id else []
    refuse_raw_keys(a["provider_team_id"] for a in aliases)
    return {a["provider_team_id"]: a["team_id_master"] for a in aliases}


def fetch_other_provider_teams(sb, provider_ids: dict[str, str], age_groups: set[str], clubs: set[str]) -> list[dict]:
    """Live boys teams of those ages at those clubs under any provider except the bridge and this one."""
    codes = {pid: code for code, pid in provider_ids.items()}
    found = []
    for age in sorted(age_groups):
        rows = page(
            lambda age=age: sb.table("teams")
            .select("team_id_master, team_name, club_name, state_code, provider_id, age_group")
            .eq("age_group", age)
            .eq("gender", "Male")
            .or_("is_deprecated.is.null,is_deprecated.eq.false"),
            "team_id_master",
            size=1000,
        )
        for row in rows:
            code = codes.get(row.get("provider_id"), "")
            if code not in (BRIDGE_PROVIDER, PROVIDER_CODE) and normalize(row["club_name"]) in clubs:
                found.append({**row, "provider_code": code})
    return found


def _read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def run(in_dir: Path, sb) -> dict[str, int]:
    squads = _read_csv(in_dir / "squads.csv")
    provider_ids = _provider_ids(sb)
    bridge = fetch_bridge(sb, provider_ids)
    links = fetch_kitman_links(sb, provider_ids)
    first = classify(squads, bridge, links)
    unplaced = [r.squad for r in first if r.bucket == "new"]
    others = (
        fetch_other_provider_teams(
            sb, provider_ids, {s["age_group"] for s in unplaced}, {normalize(s["club_name"]) for s in unplaced}
        )
        if unplaced
        else []
    )
    report = classify(squads, bridge, links, others) if others else first
    with (in_dir / "match_report.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=REPORT_COLUMNS)
        writer.writeheader()
        for row in report:
            writer.writerow(
                {
                    "provider_team_id": row.squad["provider_team_id"],
                    "key": row.squad["key"],
                    "club_name": row.squad["club_name"],
                    "display_name": row.squad["display_name"],
                    "age_group": row.squad["age_group"],
                    "division": row.squad["division"],
                    "bucket": row.bucket,
                    "reason": row.reason,
                    "state": row.state,
                    **{
                        column: "|".join(str(c.get(field) or "") for c in row.candidates)
                        for column, field in CANDIDATE_FIELDS
                    },
                }
            )
    counts = {bucket: sum(r.bucket == bucket for r in report) for bucket in ("linked", "confident", "review", "new")}
    counts["new_without_state"] = sum(r.bucket == "new" and not r.state for r in report)
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--in-dir", type=Path, default=Path("data/mlsnext_kitman"))
    args = parser.parse_args(argv)
    load_dotenv()
    url = os.environ.get("SUPABASE_URL") or os.environ.get("NEXT_PUBLIC_SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_KEY")
    if not url or not key:
        print("ERROR: missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY", file=sys.stderr)
        return 1
    counts = run(args.in_dir, create_client(url, key))
    print(" ".join(f"{name}={value}" for name, value in counts.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
