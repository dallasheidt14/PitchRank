#!/usr/bin/env python3
"""Search or batch-resolve tournament event teams against DB teams."""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from supabase import create_client

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.tournaments.event_team_matcher import EventTeamSearchQuery, search_event_team_in_db  # noqa: E402


def _get_supabase():
    supabase_url = os.getenv("SUPABASE_URL") or os.getenv("NEXT_PUBLIC_SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_SERVICE_KEY") or os.getenv(
        "SUPABASE_KEY"
    )
    if not supabase_url or not supabase_key:
        raise RuntimeError("Missing SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY/SUPABASE_KEY")
    return create_client(supabase_url, supabase_key)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _read_csv(path: Path) -> list[dict[str, Any]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys()) if rows else []
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _query_from_registry_row(row: dict[str, Any]) -> EventTeamSearchQuery:
    return EventTeamSearchQuery(
        event_team_name=str(row.get("event_team_name") or "").strip(),
        event_age_group=str(row.get("event_age_group") or row.get("display_age_group") or "").strip(),
        event_gender=str(row.get("event_gender") or row.get("display_gender") or "").strip(),
        event_club_name=str(row.get("event_club_name") or "").strip() or None,
        search_age_group=str(row.get("search_age_group") or "").strip() or None,
        provider_team_id=str(row.get("resolved_gotsport_provider_team_id") or "").strip() or None,
    )


def _format_registry_row(row: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    matches = result["matches"]
    best = matches[0] if matches else {}
    second = matches[1] if len(matches) > 1 else {}
    return {
        **row,
        "matcher_status": result["resolved_status"],
        "matcher_best_score": result["best_score"] if result["best_score"] is not None else "",
        "matcher_second_score": result["second_score"] if result["second_score"] is not None else "",
        "matcher_score_gap": result["score_gap"] if result["score_gap"] is not None else "",
        "matcher_candidate_age_groups": "|".join(result["candidate_age_groups"]),
        "matcher_resolved_team_id_master": best.get("team_id_master", ""),
        "matcher_resolved_team_name": best.get("team_name", ""),
        "matcher_resolved_club_name": best.get("club_name", ""),
        "matcher_resolved_provider_team_id": best.get("provider_team_id", ""),
        "matcher_resolved_age_group": best.get("age_group", ""),
        "matcher_resolved_score_reason": best.get("score_reason", ""),
        "matcher_alt_team_name": second.get("team_name", ""),
        "matcher_alt_score": second.get("score", ""),
    }


def _single_search(args: argparse.Namespace) -> int:
    client = _get_supabase()
    query = EventTeamSearchQuery(
        event_team_name=args.name,
        event_age_group=args.event_age_group,
        event_gender=args.gender,
        event_club_name=args.club_name,
        search_age_group=args.search_age_group,
        provider_team_id=args.provider_team_id,
        allow_play_up_years=args.allow_play_up_years,
    )
    result = search_event_team_in_db(
        client,
        query,
        limit=args.limit,
        include_deprecated=args.include_deprecated,
    )
    print(json.dumps(result.__dict__, indent=2))
    return 0


def _batch_search(args: argparse.Namespace) -> int:
    input_csv = Path(args.registry_csv)
    output_csv = Path(args.output_csv)
    output_json = Path(args.output_json) if args.output_json else output_csv.with_suffix(".summary.json")

    rows = _read_csv(input_csv)
    if args.only_unresolved:
        rows_to_search = [row for row in rows if str(row.get("canonical_resolution_status") or "").strip() in {"", "none", "review"}]  # noqa: E501
    else:
        rows_to_search = rows

    client = _get_supabase()
    cache: dict[tuple[tuple[str, ...], str, bool], list[dict[str, Any]]] = {}
    formatted_rows: list[dict[str, Any]] = []
    summary_counts: dict[str, int] = {}

    for row in rows_to_search:
        result = search_event_team_in_db(
            client,
            _query_from_registry_row(row),
            limit=args.limit,
            include_deprecated=args.include_deprecated,
            cache=cache,
        )
        formatted_rows.append(_format_registry_row(row, result.__dict__))
        summary_counts[result.resolved_status] = summary_counts.get(result.resolved_status, 0) + 1

    _write_csv(output_csv, formatted_rows)
    _write_json(
        output_json,
        {
            "input_csv": str(input_csv),
            "output_csv": str(output_csv),
            "searched_rows": len(rows_to_search),
            "status_counts": summary_counts,
        },
    )
    print(f"Saved matcher CSV to {output_csv}")
    print(f"Saved matcher summary to {output_json}")
    return 0


def main() -> int:
    load_dotenv(Path(__file__).parent.parent / ".env.local")
    load_dotenv(Path(__file__).parent.parent / ".env")

    parser = argparse.ArgumentParser(description="Search event teams in DB using weekly hygiene matching logic")
    parser.add_argument("--name", help="Single event team name to search")
    parser.add_argument("--event-age-group", help="Event bracket age group for single search")
    parser.add_argument("--search-age-group", default=None, help="Optional actual team age group override")
    parser.add_argument("--gender", help="Event bracket gender for single search")
    parser.add_argument("--club-name", default=None, help="Optional event club name for single search")
    parser.add_argument("--provider-team-id", default=None, help="Optional provider_team_id for single search")
    parser.add_argument("--registry-csv", default=None, help="Batch mode input: saved event_team_registry.csv")
    parser.add_argument("--output-csv", default=None, help="Batch mode output CSV path")
    parser.add_argument("--output-json", default=None, help="Batch mode summary JSON path")
    parser.add_argument("--limit", type=int, default=8, help="Maximum matches to return per team")
    parser.add_argument("--allow-play-up-years", type=int, default=1)
    parser.add_argument("--include-deprecated", action="store_true")
    parser.add_argument("--only-unresolved", action="store_true")
    args = parser.parse_args()

    if args.registry_csv:
        if not args.output_csv:
            raise ValueError("--output-csv is required when using --registry-csv")
        return _batch_search(args)

    if not args.name or not args.event_age_group or not args.gender:
        raise ValueError("Single search requires --name, --event-age-group, and --gender")

    return _single_search(args)


if __name__ == "__main__":
    raise SystemExit(main())
