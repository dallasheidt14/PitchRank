#!/usr/bin/env python3
"""
Export unresolved ("unknown opponent") game links from partial-linked games.

This script finds games where exactly one side is linked to a team_id_master
and the other side is still NULL, then exports:

1) Aggregate CSV (one row per unresolved provider team ID + side)
2) Detail CSV (one row per game)

Optional:
- Resolve GotSport team details (full_name, club_name, age, state) for unknown IDs.

Examples:
    python3 scripts/export_unknown_opponents.py
    python3 scripts/export_unknown_opponents.py --provider gotsport --resolve-gotsport-details
    python3 scripts/export_unknown_opponents.py --include-excluded --max-rows 50000
"""

from __future__ import annotations

import argparse
import csv
import os
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests
from dotenv import load_dotenv
from supabase import create_client


def load_env() -> None:
    env_local = Path(".env.local")
    if env_local.exists():
        load_dotenv(env_local, override=True)
    else:
        load_dotenv()


def get_supabase():
    supabase_url = os.getenv("SUPABASE_URL") or os.getenv("NEXT_PUBLIC_SUPABASE_URL")
    supabase_key = (
        os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        or os.getenv("SUPABASE_SERVICE_KEY")
        or os.getenv("SUPABASE_KEY")
    )
    if not supabase_url or not supabase_key:
        raise ValueError(
            "Missing Supabase credentials. Need SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY/SUPABASE_SERVICE_KEY/SUPABASE_KEY."
        )
    return create_client(supabase_url, supabase_key)


def _is_nullish(value: object) -> bool:
    if value is None:
        return True
    s = str(value).strip().lower()
    return s in {"", "none", "null", "nan"}


@dataclass
class UnknownSide:
    missing_side: str  # "home" or "away"
    unknown_provider_team_id: str
    known_team_id: Optional[str]


def classify_unknown_side(game: Dict) -> Optional[UnknownSide]:
    home_master = game.get("home_team_master_id")
    away_master = game.get("away_team_master_id")

    home_missing = home_master is None
    away_missing = away_master is None

    if home_missing and not away_missing:
        unknown_provider_id = game.get("home_provider_id")
        if _is_nullish(unknown_provider_id):
            return None
        return UnknownSide(
            missing_side="home",
            unknown_provider_team_id=str(unknown_provider_id).strip(),
            known_team_id=away_master,
        )

    if away_missing and not home_missing:
        unknown_provider_id = game.get("away_provider_id")
        if _is_nullish(unknown_provider_id):
            return None
        return UnknownSide(
            missing_side="away",
            unknown_provider_team_id=str(unknown_provider_id).strip(),
            known_team_id=home_master,
        )

    # Skip fully linked and fully unlinked rows.
    return None


class GotSportResolver:
    BASE_URL = "https://system.gotsport.com/api/v1/team_ranking_data/team_details"

    def __init__(self, timeout: int = 15):
        self.timeout = timeout
        self.session = requests.Session()
        self.cache: Dict[str, Dict[str, str]] = {}

    def resolve(self, provider_team_id: str) -> Dict[str, str]:
        key = str(provider_team_id).strip()
        if not key:
            return {}
        if key in self.cache:
            return self.cache[key]

        try:
            response = self.session.get(
                self.BASE_URL,
                params={"team_id": key},
                timeout=self.timeout,
            )
            response.raise_for_status()
            payload = response.json() if response.content else {}
            if not isinstance(payload, dict):
                payload = {}
        except Exception:
            payload = {}

        resolved = {
            "unknown_team_name": str(payload.get("name") or "").strip(),
            "unknown_team_full_name": str(payload.get("full_name") or "").strip(),
            "unknown_club_name": str(payload.get("club_name") or "").strip(),
            "unknown_state": str(payload.get("state") or "").strip(),
            "unknown_age": str(payload.get("age") or "").strip(),
            "unknown_gender": str(payload.get("gender") or "").strip(),
        }
        self.cache[key] = resolved
        return resolved


def fetch_partial_games(
    supabase,
    provider_id: Optional[str],
    include_excluded: bool,
    max_rows: Optional[int],
) -> List[Dict]:
    select_cols = (
        "id,provider_id,game_date,competition,is_excluded,"
        "home_provider_id,away_provider_id,"
        "home_team_master_id,away_team_master_id,"
        "home_score,away_score"
    )
    page_size = 1000
    offset = 0
    rows: List[Dict] = []

    while True:
        query = supabase.table("games").select(select_cols).or_(
            "home_team_master_id.is.null,away_team_master_id.is.null"
        )

        if provider_id:
            query = query.eq("provider_id", provider_id)
        if not include_excluded:
            query = query.eq("is_excluded", False)

        batch = query.range(offset, offset + page_size - 1).execute().data or []
        if not batch:
            break

        rows.extend(batch)
        if max_rows and len(rows) >= max_rows:
            rows = rows[:max_rows]
            break

        if len(batch) < page_size:
            break
        offset += page_size

    return rows


def fetch_team_lookup(supabase, team_ids: List[str]) -> Dict[str, Dict]:
    lookup: Dict[str, Dict] = {}
    if not team_ids:
        return lookup

    for i in range(0, len(team_ids), 500):
        batch = team_ids[i : i + 500]
        data = (
            supabase.table("teams")
            .select("team_id_master,team_name,age_group,gender,club_name,state_code")
            .in_("team_id_master", batch)
            .execute()
            .data
            or []
        )
        for row in data:
            lookup[row["team_id_master"]] = row
    return lookup


def write_csv(path: Path, fieldnames: List[str], rows: List[Dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def main() -> None:
    parser = argparse.ArgumentParser(description="Export unknown opponents from partial-linked games")
    parser.add_argument("--provider", default=None, help="Provider code filter (e.g. gotsport, tgs)")
    parser.add_argument("--include-excluded", action="store_true", help="Include games where is_excluded=true")
    parser.add_argument("--max-rows", type=int, default=None, help="Optional cap for fetched game rows")
    parser.add_argument("--resolve-gotsport-details", action="store_true", help="Fetch GotSport team details for unknown provider team IDs")
    parser.add_argument(
        "--output-prefix",
        default=None,
        help="Output file prefix (default: data/exports/unknown_opponents_<timestamp>)",
    )
    args = parser.parse_args()

    load_env()
    supabase = get_supabase()

    providers = supabase.table("providers").select("id,code,name").execute().data or []
    code_to_id = {p["code"]: p["id"] for p in providers}
    id_to_code = {p["id"]: p["code"] for p in providers}

    provider_id = None
    if args.provider:
        provider_id = code_to_id.get(args.provider)
        if not provider_id:
            raise ValueError(f"Unknown provider code: {args.provider}")

    partial_rows = fetch_partial_games(
        supabase=supabase,
        provider_id=provider_id,
        include_excluded=args.include_excluded,
        max_rows=args.max_rows,
    )

    # Build known team lookup
    known_ids = set()
    for game in partial_rows:
        unknown = classify_unknown_side(game)
        if unknown and unknown.known_team_id:
            known_ids.add(unknown.known_team_id)
    team_lookup = fetch_team_lookup(supabase, sorted(known_ids))

    resolver = GotSportResolver() if args.resolve_gotsport_details else None

    # Aggregate
    groups: Dict[Tuple[str, str, str, str], Dict] = {}
    detail_rows: List[Dict] = []

    for game in partial_rows:
        unknown = classify_unknown_side(game)
        if not unknown:
            continue

        pid = game.get("provider_id")
        pcode = id_to_code.get(pid, str(pid))
        key = (pcode, str(pid), unknown.unknown_provider_team_id, unknown.missing_side)

        known_team = team_lookup.get(unknown.known_team_id or "", {})
        got_details: Dict[str, str] = {}
        if resolver and pcode == "gotsport":
            got_details = resolver.resolve(unknown.unknown_provider_team_id)

        if key not in groups:
            groups[key] = {
                "games_count": 0,
                "first_game_date": None,
                "last_game_date": None,
                "known_team_counts": Counter(),
                "competition_counts": Counter(),
                "sample_game_ids": [],
                "resolved_unknown": got_details,
            }

        g = groups[key]
        g["games_count"] += 1
        game_date = game.get("game_date")
        if game_date:
            if not g["first_game_date"] or game_date < g["first_game_date"]:
                g["first_game_date"] = game_date
            if not g["last_game_date"] or game_date > g["last_game_date"]:
                g["last_game_date"] = game_date
        if unknown.known_team_id:
            g["known_team_counts"][unknown.known_team_id] += 1
        if game.get("competition"):
            g["competition_counts"][game["competition"]] += 1
        if len(g["sample_game_ids"]) < 5:
            g["sample_game_ids"].append(game["id"])

        detail_rows.append(
            {
                "game_id": game.get("id", ""),
                "provider_code": pcode,
                "provider_id": pid,
                "game_date": game.get("game_date", ""),
                "competition": game.get("competition", ""),
                "home_provider_id": game.get("home_provider_id", ""),
                "away_provider_id": game.get("away_provider_id", ""),
                "home_team_master_id": game.get("home_team_master_id", ""),
                "away_team_master_id": game.get("away_team_master_id", ""),
                "home_score": game.get("home_score", ""),
                "away_score": game.get("away_score", ""),
                "missing_side": unknown.missing_side,
                "unknown_provider_team_id": unknown.unknown_provider_team_id,
                "known_team_id": unknown.known_team_id or "",
                "known_team_name": known_team.get("team_name", ""),
                "known_team_age_group": known_team.get("age_group", ""),
                "known_team_gender": known_team.get("gender", ""),
                "known_team_club": known_team.get("club_name", ""),
                "known_team_state": known_team.get("state_code", ""),
                "unknown_team_name": got_details.get("unknown_team_name", ""),
                "unknown_team_full_name": got_details.get("unknown_team_full_name", ""),
                "unknown_club_name": got_details.get("unknown_club_name", ""),
                "unknown_state": got_details.get("unknown_state", ""),
                "unknown_age": got_details.get("unknown_age", ""),
                "unknown_gender": got_details.get("unknown_gender", ""),
            }
        )

    aggregate_rows: List[Dict] = []
    for (pcode, pid, unknown_pid, side), data in sorted(
        groups.items(), key=lambda kv: kv[1]["games_count"], reverse=True
    ):
        top_known_id = data["known_team_counts"].most_common(1)[0][0] if data["known_team_counts"] else ""
        top_known = team_lookup.get(top_known_id, {}) if top_known_id else {}
        top_comp = data["competition_counts"].most_common(1)[0][0] if data["competition_counts"] else ""
        resolved_unknown = data.get("resolved_unknown", {}) or {}

        aggregate_rows.append(
            {
                "provider_code": pcode,
                "provider_id": pid,
                "unknown_provider_team_id": unknown_pid,
                "missing_side": side,
                "games_count": data["games_count"],
                "first_game_date": data["first_game_date"] or "",
                "last_game_date": data["last_game_date"] or "",
                "top_known_team_id": top_known_id,
                "top_known_team_name": top_known.get("team_name", ""),
                "top_known_team_age_group": top_known.get("age_group", ""),
                "top_known_team_gender": top_known.get("gender", ""),
                "top_known_team_club": top_known.get("club_name", ""),
                "top_known_team_state": top_known.get("state_code", ""),
                "top_competition": top_comp,
                "sample_game_ids": ";".join(data["sample_game_ids"]),
                "unknown_team_name": resolved_unknown.get("unknown_team_name", ""),
                "unknown_team_full_name": resolved_unknown.get("unknown_team_full_name", ""),
                "unknown_club_name": resolved_unknown.get("unknown_club_name", ""),
                "unknown_state": resolved_unknown.get("unknown_state", ""),
                "unknown_age": resolved_unknown.get("unknown_age", ""),
                "unknown_gender": resolved_unknown.get("unknown_gender", ""),
            }
        )

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    prefix = args.output_prefix or f"data/exports/unknown_opponents_{timestamp}"
    aggregate_path = Path(f"{prefix}_aggregate.csv")
    detail_path = Path(f"{prefix}_games.csv")

    write_csv(
        aggregate_path,
        fieldnames=[
            "provider_code",
            "provider_id",
            "unknown_provider_team_id",
            "missing_side",
            "games_count",
            "first_game_date",
            "last_game_date",
            "top_known_team_id",
            "top_known_team_name",
            "top_known_team_age_group",
            "top_known_team_gender",
            "top_known_team_club",
            "top_known_team_state",
            "top_competition",
            "sample_game_ids",
            "unknown_team_name",
            "unknown_team_full_name",
            "unknown_club_name",
            "unknown_state",
            "unknown_age",
            "unknown_gender",
        ],
        rows=aggregate_rows,
    )

    write_csv(
        detail_path,
        fieldnames=[
            "game_id",
            "provider_code",
            "provider_id",
            "game_date",
            "competition",
            "home_provider_id",
            "away_provider_id",
            "home_team_master_id",
            "away_team_master_id",
            "home_score",
            "away_score",
            "missing_side",
            "unknown_provider_team_id",
            "known_team_id",
            "known_team_name",
            "known_team_age_group",
            "known_team_gender",
            "known_team_club",
            "known_team_state",
            "unknown_team_name",
            "unknown_team_full_name",
            "unknown_club_name",
            "unknown_state",
            "unknown_age",
            "unknown_gender",
        ],
        rows=detail_rows,
    )

    print("=== Unknown Opponent Export ===")
    if args.provider:
        print(f"Provider filter: {args.provider}")
    print(f"Fetched partial rows: {len(partial_rows):,}")
    print(f"Aggregate groups: {len(aggregate_rows):,}")
    print(f"Detail rows: {len(detail_rows):,}")
    print(f"Aggregate CSV: {aggregate_path}")
    print(f"Detail CSV: {detail_path}")

    print("\nTop 10 unresolved provider IDs:")
    for idx, row in enumerate(aggregate_rows[:10], start=1):
        print(
            f"  {idx:>2}. [{row['provider_code']}] {row['unknown_provider_team_id']} "
            f"({row['missing_side']}) games={row['games_count']} "
            f"known={row['top_known_team_name']}"
        )


if __name__ == "__main__":
    main()
