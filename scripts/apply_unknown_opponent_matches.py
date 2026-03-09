#!/usr/bin/env python3
"""
Apply approved unknown-opponent matches to DB.

Reads a CSV from due_diligence_unknown_opponents.py (approved rows) and:
  1) upserts team_alias_map(provider_id, provider_team_id -> team_id_master)
  2) backfills missing home/away team_master links in games

Safety behavior:
  - If alias already exists for another team_id_master, row is skipped (conflict)
  - Never overwrites non-null home_team_master_id / away_team_master_id
"""

from __future__ import annotations

import argparse
import csv
import os
from pathlib import Path
from typing import Dict, List

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


def parse_rows(path: str, require_approved: bool) -> List[Dict]:
    with open(path, "r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if require_approved:
        rows = [r for r in rows if (r.get("verdict") or "").strip().lower() == "approved"]
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply approved unknown-opponent mappings")
    parser.add_argument("--approved-csv", required=True, help="CSV path from due_diligence script")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without DB writes")
    parser.add_argument("--require-approved-rows", action="store_true", help="Only process rows where verdict=approved")
    parser.add_argument(
        "--only-unknown-ids",
        default=None,
        help="Optional comma-separated unknown_provider_team_id allowlist",
    )
    args = parser.parse_args()

    rows = parse_rows(args.approved_csv, require_approved=args.require_approved_rows)
    if args.only_unknown_ids:
        allow = {x.strip() for x in args.only_unknown_ids.split(",") if x.strip()}
        rows = [r for r in rows if (r.get("unknown_provider_team_id") or "").strip() in allow]

    if not rows:
        print("No rows to process.")
        return

    load_env()
    db = get_supabase()

    stats = {
        "rows_total": len(rows),
        "rows_applied": 0,
        "rows_conflict": 0,
        "rows_error": 0,
        "home_backfilled": 0,
        "away_backfilled": 0,
    }

    for row in rows:
        provider_id = (row.get("provider_id") or "").strip()
        unknown_pid = (row.get("unknown_provider_team_id") or "").strip()
        team_id = (row.get("matched_team_id_master") or "").strip()

        if not provider_id or not unknown_pid or not team_id:
            stats["rows_error"] += 1
            print(f"SKIP invalid row: provider_id={provider_id} unknown_pid={unknown_pid} team_id={team_id}")
            continue

        # Alias conflict guard.
        existing_alias = (
            db.table("team_alias_map")
            .select("team_id_master")
            .eq("provider_id", provider_id)
            .eq("provider_team_id", unknown_pid)
            .limit(1)
            .execute()
            .data
            or []
        )
        if existing_alias and existing_alias[0].get("team_id_master") != team_id:
            stats["rows_conflict"] += 1
            print(
                f"CONFLICT unknown_pid={unknown_pid}: existing team_id_master={existing_alias[0].get('team_id_master')} "
                f"!= proposed {team_id}"
            )
            continue

        if args.dry_run:
            stats["rows_applied"] += 1
            print(f"DRY-RUN would link unknown_pid={unknown_pid} -> team_id={team_id}")
            continue

        try:
            # Upsert alias
            db.table("team_alias_map").upsert(
                {
                    "provider_id": provider_id,
                    "provider_team_id": unknown_pid,
                    "team_id_master": team_id,
                    "match_method": "fuzzy_auto",
                    "match_confidence": 1.0,
                    "review_status": "approved",
                },
                on_conflict="provider_id,provider_team_id",
            ).execute()

            # Backfill both sides safely (only NULL fields).
            # Count first, then update without `.select()` to avoid client incompatibility.
            home_count = (
                db.table("games")
                .select("id", count="exact", head=True)
                .eq("provider_id", provider_id)
                .eq("home_provider_id", unknown_pid)
                .is_("home_team_master_id", "null")
                .execute()
                .count
                or 0
            )
            away_count = (
                db.table("games")
                .select("id", count="exact", head=True)
                .eq("provider_id", provider_id)
                .eq("away_provider_id", unknown_pid)
                .is_("away_team_master_id", "null")
                .execute()
                .count
                or 0
            )

            db.table("games").update({"home_team_master_id": team_id}).eq(
                "provider_id", provider_id
            ).eq("home_provider_id", unknown_pid).is_("home_team_master_id", "null").execute()

            db.table("games").update({"away_team_master_id": team_id}).eq(
                "provider_id", provider_id
            ).eq("away_provider_id", unknown_pid).is_("away_team_master_id", "null").execute()
            stats["home_backfilled"] += home_count
            stats["away_backfilled"] += away_count
            stats["rows_applied"] += 1

            print(
                f"APPLIED unknown_pid={unknown_pid} -> team_id={team_id} "
                f"(home_backfilled={home_count}, away_backfilled={away_count})"
            )
        except Exception as exc:
            stats["rows_error"] += 1
            print(f"ERROR unknown_pid={unknown_pid}: {exc}")

    print("\n=== Apply Unknown Opponent Matches Summary ===")
    for k, v in stats.items():
        print(f"{k}={v}")


if __name__ == "__main__":
    main()
