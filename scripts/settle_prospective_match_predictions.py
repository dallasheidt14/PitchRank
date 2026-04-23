"""
Settle prospective match predictions against actual game results.

This script matches rows in prospective_match_predictions to scored games in the
main games table and records the actual result in fixture orientation.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from dotenv import load_dotenv

env_local = Path(".env.local")
if env_local.exists():
    load_dotenv(env_local, override=True)
else:
    load_dotenv()

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from supabase import Client, create_client  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def _supabase_client() -> Client:
    supabase_url = os.getenv("SUPABASE_URL") or os.getenv("NEXT_PUBLIC_SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_SERVICE_KEY")
    if not supabase_url or not supabase_key:
        raise RuntimeError("Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY/SUPABASE_SERVICE_KEY")
    return create_client(supabase_url, supabase_key)


def _normalize_text(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _safe_json(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


def _build_actual_outcome(home_score: Optional[int], away_score: Optional[int]) -> Optional[str]:
    if home_score is None or away_score is None:
        return None
    if home_score > away_score:
        return "team_a"
    if away_score > home_score:
        return "team_b"
    return "draw"


def _chunked(values: Iterable[str], size: int) -> Iterable[List[str]]:
    batch: List[str] = []
    for value in values:
        batch.append(value)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch


def _is_missing_table(error: Exception, table_name: str) -> bool:
    message = str(error).lower()
    return ("could not find the table" in message or "schema cache" in message) and table_name.lower() in message


def _fetch_rows(supabase: Client, status: str, limit: int) -> List[Dict[str, Any]]:
    try:
        response = (
            supabase.table("prospective_match_predictions")
            .select(
                "id, fixture_key, game_date, competition, division_name, home_provider_team_id, away_provider_team_id, "
                "home_team_master_id, away_team_master_id, evaluation_notes"
            )
            .eq("evaluation_status", status)
            .lte("game_date", date.today().isoformat())
            .order("game_date", desc=False)
            .limit(limit)
            .execute()
        )
    except Exception as error:
        if _is_missing_table(error, "prospective_match_predictions"):
            raise RuntimeError(
                "prospective_match_predictions table is missing. "
                "Apply the new Supabase migration before running settlement."
            ) from error
        raise
    return list(response.data or [])


def _fetch_games(
    supabase: Client,
    *,
    game_date: str,
    home_team_master_id: Optional[str],
    away_team_master_id: Optional[str],
    home_provider_team_id: Optional[str],
    away_provider_team_id: Optional[str],
) -> List[Tuple[Dict[str, Any], bool, str]]:
    candidates: Dict[str, Tuple[Dict[str, Any], bool, str]] = {}
    select_fields = (
        "id, game_date, home_team_master_id, away_team_master_id, home_provider_id, away_provider_id, "
        "home_score, away_score, competition, division_name, event_name"
    )

    def add_rows(rows: List[Dict[str, Any]], reversed_orientation: bool, source: str) -> None:
        for row in rows:
            game_id = str(row.get("id") or "")
            if game_id and row.get("home_score") is not None and row.get("away_score") is not None:
                candidates.setdefault(game_id, (row, reversed_orientation, source))

    if home_team_master_id and away_team_master_id:
        direct = (
            supabase.table("games")
            .select(select_fields)
            .eq("game_date", game_date)
            .eq("home_team_master_id", home_team_master_id)
            .eq("away_team_master_id", away_team_master_id)
            .execute()
        )
        add_rows(list(direct.data or []), False, "team_ids_direct")

        reverse = (
            supabase.table("games")
            .select(select_fields)
            .eq("game_date", game_date)
            .eq("home_team_master_id", away_team_master_id)
            .eq("away_team_master_id", home_team_master_id)
            .execute()
        )
        add_rows(list(reverse.data or []), True, "team_ids_reverse")

    if home_provider_team_id and away_provider_team_id:
        direct = (
            supabase.table("games")
            .select(select_fields)
            .eq("game_date", game_date)
            .eq("home_provider_id", home_provider_team_id)
            .eq("away_provider_id", away_provider_team_id)
            .execute()
        )
        add_rows(list(direct.data or []), False, "provider_ids_direct")

        reverse = (
            supabase.table("games")
            .select(select_fields)
            .eq("game_date", game_date)
            .eq("home_provider_id", away_provider_team_id)
            .eq("away_provider_id", home_provider_team_id)
            .execute()
        )
        add_rows(list(reverse.data or []), True, "provider_ids_reverse")

    return list(candidates.values())


def _candidate_score(fixture: Dict[str, Any], candidate: Dict[str, Any], source: str) -> int:
    score = 0
    if source.startswith("team_ids_"):
        score += 6
    elif source.startswith("provider_ids_"):
        score += 4

    if _normalize_text(candidate.get("competition")) == _normalize_text(fixture.get("competition")):
        score += 2
    if _normalize_text(candidate.get("event_name")) == _normalize_text(fixture.get("competition")):
        score += 1
    if _normalize_text(candidate.get("division_name")) == _normalize_text(fixture.get("division_name")):
        score += 2
    return score


def _pick_candidate(
    fixture: Dict[str, Any],
    candidates: List[Tuple[Dict[str, Any], bool, str]],
) -> Tuple[Optional[Dict[str, Any]], Optional[bool], Optional[str], List[Dict[str, Any]]]:
    if not candidates:
        return None, None, None, []

    scored = []
    for candidate, reversed_orientation, source in candidates:
        scored.append(
            {
                "candidate": candidate,
                "reversed_orientation": reversed_orientation,
                "source": source,
                "score": _candidate_score(fixture, candidate, source),
            }
        )
    scored.sort(key=lambda item: (item["score"], item["source"]), reverse=True)

    if len(scored) > 1 and scored[0]["score"] == scored[1]["score"]:
        return None, None, None, scored

    best = scored[0]
    return best["candidate"], bool(best["reversed_orientation"]), str(best["source"]), scored


def _update_row(
    supabase: Client,
    row_id: str,
    payload: Dict[str, Any],
) -> None:
    supabase.table("prospective_match_predictions").update(payload).eq("id", row_id).execute()


def settle_rows(
    *,
    supabase: Client,
    status: str,
    limit: int,
) -> Dict[str, Any]:
    rows = _fetch_rows(supabase, status, limit)
    summary = {
        "requested_status": status,
        "requested_limit": limit,
        "fetched_rows": len(rows),
        "processed": 0,
        "settled": 0,
        "not_found": 0,
        "ambiguous": 0,
        "row_ids": [],
    }

    for row in rows:
        row_id = str(row["id"])
        summary["processed"] += 1
        summary["row_ids"].append(row_id)

        candidates = _fetch_games(
            supabase,
            game_date=str(row.get("game_date") or ""),
            home_team_master_id=row.get("home_team_master_id"),
            away_team_master_id=row.get("away_team_master_id"),
            home_provider_team_id=row.get("home_provider_team_id"),
            away_provider_team_id=row.get("away_provider_team_id"),
        )
        candidate, reversed_orientation, source, scored_candidates = _pick_candidate(row, candidates)
        existing_notes = _safe_json(row.get("evaluation_notes"))

        if candidate is None and scored_candidates:
            _update_row(
                supabase,
                row_id,
                {
                    "evaluation_status": "ambiguous_result",
                    "evaluation_notes": {
                        **existing_notes,
                        "settlement": {
                            "status": "ambiguous",
                            "candidates": [
                                {
                                    "game_id": entry["candidate"].get("id"),
                                    "score": entry["score"],
                                    "source": entry["source"],
                                    "reversed_orientation": entry["reversed_orientation"],
                                }
                                for entry in scored_candidates[:5]
                            ],
                        },
                    },
                },
            )
            summary["ambiguous"] += 1
            continue

        if candidate is None:
            _update_row(
                supabase,
                row_id,
                {
                    "evaluation_status": "result_not_found",
                    "evaluation_notes": {
                        **existing_notes,
                        "settlement": {
                            "status": "not_found",
                            "checked_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                        },
                    },
                },
            )
            summary["not_found"] += 1
            continue

        home_score = int(candidate["away_score"]) if reversed_orientation else int(candidate["home_score"])
        away_score = int(candidate["home_score"]) if reversed_orientation else int(candidate["away_score"])
        _update_row(
            supabase,
            row_id,
            {
                "actual_game_id": candidate.get("id"),
                "actual_home_score": home_score,
                "actual_away_score": away_score,
                "actual_outcome": _build_actual_outcome(home_score, away_score),
                "actual_recorded_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "evaluation_status": "settled",
                "evaluation_notes": {
                    **existing_notes,
                    "settlement": {
                        "status": "settled",
                        "source": source,
                        "reversed_orientation": bool(reversed_orientation),
                        "matched_game_id": candidate.get("id"),
                    },
                },
            },
        )
        summary["settled"] += 1

    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Settle prospective match predictions against actual results")
    parser.add_argument("--status", default="pending_result", help="evaluation_status to pull")
    parser.add_argument("--limit", type=int, default=200, help="maximum number of rows to process")
    parser.add_argument("--summary-path", default=None, help="Optional path to write JSON summary")
    args = parser.parse_args()

    summary = settle_rows(
        supabase=_supabase_client(),
        status=args.status,
        limit=args.limit,
    )
    if args.summary_path:
        summary_path = Path(args.summary_path)
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
