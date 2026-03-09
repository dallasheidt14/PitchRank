#!/usr/bin/env python3
"""
Auto-match unknown opponents exported from partial-linked games.

Pipeline:
1) Read aggregate CSV from export_unknown_opponents.py
2) Build unknown team profile (optionally resolve GotSport team details)
3) Score candidates using Step-3-style logic (score_team_pair)
4) Classify into auto/review/no_match buckets
5) Optional --execute:
   - upsert team_alias_map
   - backfill missing home/away team_master_id in games

Examples:
    python3 scripts/auto_match_unknown_opponents.py --input data/exports/unknown_opponents_*.csv
    python3 scripts/auto_match_unknown_opponents.py --input ... --provider gotsport --limit 500
    python3 scripts/auto_match_unknown_opponents.py --input ... --execute --auto-threshold 0.97
"""

from __future__ import annotations

import argparse
import csv
import os
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import sys
from pathlib import Path

import requests
from dotenv import load_dotenv
from supabase import create_client

# Ensure sibling scripts are importable when invoked from repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent))

# Reuse existing queue/step-3 matching logic
from find_fuzzy_duplicate_teams import score_team_pair
from find_queue_matches import extract_age_group, extract_gender, has_protected_division


def _execute_with_retry(query_func, max_retries: int = 3, base_delay: float = 1.0):
    """Execute a Supabase query with exponential backoff on transient HTTP errors."""
    last_exception = None
    for attempt in range(max_retries + 1):
        try:
            return query_func()
        except Exception as e:
            last_exception = e
            err_msg = str(e).lower()
            is_transient = (
                "remoteprotocolerror" in type(e).__name__.lower()
                or "connectionterminated" in err_msg
                or "remoteprotocolerror" in err_msg
                or ("connection" in err_msg and "closed" in err_msg)
            )
            if not is_transient or attempt >= max_retries:
                raise
            delay = base_delay * (2 ** attempt)
            print(f"  [retry {attempt + 1}/{max_retries}] Transient HTTP error, retrying in {delay:.1f}s: {e}")
            time.sleep(delay)
    raise last_exception  # unreachable, but satisfies type checkers


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


def _to_gender_full(v: Optional[str]) -> Optional[str]:
    if not v:
        return None
    s = str(v).strip().lower()
    if s in {"male", "m", "boys", "boy", "b"}:
        return "Male"
    if s in {"female", "f", "girls", "girl", "g"}:
        return "Female"
    return None


def _to_age_group(v: Optional[str]) -> Optional[str]:
    if not v:
        return None
    s = str(v).strip().lower()
    if s.startswith("u") and s[1:].isdigit():
        return s
    if s.isdigit():
        return f"u{s}"
    # unknown_age from gotsport may be "12", already handled above
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


@dataclass
class UnknownProfile:
    team_name: str
    club_name: str
    age_group: Optional[str]
    gender: Optional[str]
    state_code: Optional[str]


def build_unknown_profile(row: Dict[str, str], resolver: Optional[GotSportResolver]) -> UnknownProfile:
    provider_code = (row.get("provider_code") or "").strip().lower()
    unknown_provider_team_id = (row.get("unknown_provider_team_id") or "").strip()

    # Start with CSV fields
    full_name = (row.get("unknown_team_full_name") or "").strip()
    short_name = (row.get("unknown_team_name") or "").strip()
    club_name = (row.get("unknown_club_name") or "").strip()
    state = (row.get("unknown_state") or "").strip()
    age_group = _to_age_group(row.get("unknown_age"))
    gender = _to_gender_full(row.get("unknown_gender"))

    # Optional resolver backfill
    if resolver and provider_code == "gotsport":
        if not full_name and unknown_provider_team_id:
            resolved = resolver.resolve(unknown_provider_team_id)
            full_name = full_name or resolved.get("unknown_team_full_name", "")
            short_name = short_name or resolved.get("unknown_team_name", "")
            club_name = club_name or resolved.get("unknown_club_name", "")
            state = state or resolved.get("unknown_state", "")
            age_group = age_group or _to_age_group(resolved.get("unknown_age"))
            gender = gender or _to_gender_full(resolved.get("unknown_gender"))

    # Prefer full_name for fuzzy matching, then short_name
    name = full_name or short_name or f"unknown_{unknown_provider_team_id}"

    # Fallback age/gender/state from known-side context in export row
    if not age_group:
        age_group = _to_age_group(row.get("top_known_team_age_group"))
    if not gender:
        gender = _to_gender_full(row.get("top_known_team_gender"))
    if not state:
        state = (row.get("top_known_team_state") or "").strip()

    # Parse from name if still missing
    details = {"age_group": age_group, "gender": gender}
    parsed_age = extract_age_group(name, details)
    parsed_gender = extract_gender(name, details)
    if not age_group and parsed_age:
        age_group = parsed_age.lower()
    if not gender and parsed_gender:
        gender = _to_gender_full(parsed_gender)

    return UnknownProfile(
        team_name=name,
        club_name=club_name,
        age_group=age_group,
        gender=gender,
        state_code=state.upper() if state else None,
    )


def fetch_candidates(
    supabase,
    profile: UnknownProfile,
    strict_club: bool,
    max_candidates: int,
    cache: Dict[Tuple, List[Dict]],
) -> List[Dict]:
    key = (
        profile.club_name.lower(),
        profile.age_group or "",
        profile.gender or "",
        profile.state_code or "",
        strict_club,
        max_candidates,
    )
    if key in cache:
        return cache[key]

    # Base query
    query = supabase.table("teams").select(
        "team_id_master,team_name,club_name,age_group,gender,state_code,is_deprecated"
    ).eq("is_deprecated", False)

    if profile.gender:
        query = query.ilike("gender", profile.gender)
    if profile.age_group:
        age = profile.age_group.upper()
        query = query.or_(f"age_group.eq.{age},age_group.eq.{age.lower()},age_group.eq.{age.upper()}")
    if profile.state_code:
        query = query.eq("state_code", profile.state_code)

    # Club-first narrowing
    candidates: List[Dict] = []
    if profile.club_name:
        club_q = query.ilike("club_name", profile.club_name)
        candidates = _execute_with_retry(
            lambda q=club_q: q.limit(max_candidates).execute()
        ).data or []

    if strict_club and profile.club_name:
        cache[key] = candidates
        return candidates

    # Fallback broader query if strict club off and club-specific results are sparse.
    if not candidates:
        candidates = _execute_with_retry(
            lambda q=query: q.limit(max_candidates).execute()
        ).data or []

    cache[key] = candidates
    return candidates


def match_row(
    row: Dict[str, str],
    supabase,
    resolver: Optional[GotSportResolver],
    strict_club: bool,
    max_candidates: int,
    auto_threshold: float,
    review_threshold: float,
    candidate_cache: Dict[Tuple, List[Dict]],
) -> Dict[str, object]:
    profile = build_unknown_profile(row, resolver)

    if has_protected_division(profile.team_name):
        return {
            "action": "skip_protected_division",
            "best_score": 0.0,
            "best_match": None,
            "profile": profile,
            "candidate_count": 0,
        }

    candidates = fetch_candidates(
        supabase=supabase,
        profile=profile,
        strict_club=strict_club,
        max_candidates=max_candidates,
        cache=candidate_cache,
    )

    best = None
    best_score = 0.0
    unknown_team = {"team_name": profile.team_name, "club_name": profile.club_name}

    for candidate in candidates:
        score = score_team_pair(unknown_team, candidate)
        if score is None:
            continue
        if score > best_score:
            best_score = score
            best = candidate

    if not best:
        action = "no_match"
    elif best_score >= auto_threshold:
        action = "auto_link"
    elif best_score >= review_threshold:
        action = "review"
    else:
        action = "no_match"

    return {
        "action": action,
        "best_score": best_score,
        "best_match": best,
        "profile": profile,
        "candidate_count": len(candidates),
    }


def execute_auto_link(
    supabase,
    provider_id: str,
    provider_code: str,
    unknown_provider_team_id: str,
    missing_side: str,
    match_team_id: str,
    match_score: float,
) -> Tuple[str, int]:
    # Check existing alias first for safety.
    existing = _execute_with_retry(
        lambda: supabase.table("team_alias_map")
        .select("id,team_id_master")
        .eq("provider_id", provider_id)
        .eq("provider_team_id", unknown_provider_team_id)
        .limit(1)
        .execute()
    ).data or []
    if existing and existing[0].get("team_id_master") != match_team_id:
        return "alias_conflict", 0

    # Upsert alias mapping
    _execute_with_retry(
        lambda: supabase.table("team_alias_map").upsert(
            {
                "provider_id": provider_id,
                "provider_team_id": unknown_provider_team_id,
                "team_id_master": match_team_id,
                "match_method": "fuzzy_auto",
                "match_confidence": float(f"{match_score:.4f}"),
                "review_status": "approved",
            },
            on_conflict="provider_id,provider_team_id",
        ).execute()
    )

    # Backfill missing side only.
    if missing_side == "home":
        update = _execute_with_retry(
            lambda: supabase.table("games")
            .update({"home_team_master_id": match_team_id})
            .eq("provider_id", provider_id)
            .eq("home_provider_id", unknown_provider_team_id)
            .is_("home_team_master_id", "null")
            .select("id")
            .execute()
        )
    else:
        update = _execute_with_retry(
            lambda: supabase.table("games")
            .update({"away_team_master_id": match_team_id})
            .eq("provider_id", provider_id)
            .eq("away_provider_id", unknown_provider_team_id)
            .is_("away_team_master_id", "null")
            .select("id")
            .execute()
        )
    updated_rows = len(update.data or [])
    return "linked", updated_rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Auto-match unknown opponents from export CSV")
    parser.add_argument("--input", required=True, help="Aggregate CSV from export_unknown_opponents.py")
    parser.add_argument("--provider", default=None, help="Optional provider code filter")
    parser.add_argument("--limit", type=int, default=None, help="Limit rows processed from input CSV")
    parser.add_argument("--auto-threshold", type=float, default=0.95, help="Score threshold for auto-link")
    parser.add_argument("--review-threshold", type=float, default=0.90, help="Score threshold for review bucket")
    parser.add_argument("--strict-club", action="store_true", help="Require exact club filtering when club is known")
    parser.add_argument("--max-candidates", type=int, default=120, help="Max team candidates per unknown row")
    parser.add_argument("--resolve-gotsport-details", action="store_true", help="Fetch missing unknown team details from GotSport API")
    parser.add_argument("--execute", action="store_true", help="Apply auto_link rows (alias + backfill)")
    parser.add_argument(
        "--output",
        default=None,
        help="Output report CSV path (default: data/exports/unknown_opponent_match_report_<timestamp>.csv)",
    )
    args = parser.parse_args()

    if args.review_threshold > args.auto_threshold:
        raise ValueError("--review-threshold cannot be greater than --auto-threshold")

    load_env()
    supabase = get_supabase()

    providers = _execute_with_retry(
        lambda: supabase.table("providers").select("id,code,name").execute()
    ).data or []
    code_to_id = {p["code"]: p["id"] for p in providers}

    provider_filter = args.provider.lower() if args.provider else None
    if provider_filter and provider_filter not in code_to_id:
        raise ValueError(f"Unknown provider code: {provider_filter}")

    # Read input rows
    with open(args.input, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = [r for r in reader]

    if provider_filter:
        rows = [r for r in rows if (r.get("provider_code") or "").strip().lower() == provider_filter]
    if args.limit:
        rows = rows[: args.limit]

    resolver = GotSportResolver() if args.resolve_gotsport_details else None
    candidate_cache: Dict[Tuple, List[Dict]] = {}

    report_rows: List[Dict[str, object]] = []
    stats = {
        "total": 0,
        "auto_link": 0,
        "review": 0,
        "no_match": 0,
        "skip_protected_division": 0,
        "executed_linked": 0,
        "executed_conflict": 0,
        "games_backfilled": 0,
    }

    for idx, row in enumerate(rows, start=1):
        provider_code = (row.get("provider_code") or "").strip().lower()
        provider_id = (row.get("provider_id") or "").strip() or code_to_id.get(provider_code, "")
        unknown_pid = (row.get("unknown_provider_team_id") or "").strip()
        missing_side = (row.get("missing_side") or "").strip().lower()

        result = match_row(
            row=row,
            supabase=supabase,
            resolver=resolver,
            strict_club=args.strict_club,
            max_candidates=args.max_candidates,
            auto_threshold=args.auto_threshold,
            review_threshold=args.review_threshold,
            candidate_cache=candidate_cache,
        )

        action = result["action"]
        best_score = float(result["best_score"])
        best_match = result["best_match"]
        profile: UnknownProfile = result["profile"]  # type: ignore[assignment]
        candidate_count = int(result["candidate_count"])

        stats["total"] += 1
        if action in stats:
            stats[action] += 1

        exec_status = "dry_run"
        updated_rows = 0

        if args.execute and action == "auto_link" and best_match and provider_id and unknown_pid and missing_side in {"home", "away"}:
            exec_status, updated_rows = execute_auto_link(
                supabase=supabase,
                provider_id=provider_id,
                provider_code=provider_code,
                unknown_provider_team_id=unknown_pid,
                missing_side=missing_side,
                match_team_id=best_match["team_id_master"],
                match_score=best_score,
            )
            if exec_status == "linked":
                stats["executed_linked"] += 1
                stats["games_backfilled"] += updated_rows
            elif exec_status == "alias_conflict":
                stats["executed_conflict"] += 1

        report_rows.append(
            {
                "provider_code": provider_code,
                "provider_id": provider_id,
                "unknown_provider_team_id": unknown_pid,
                "missing_side": missing_side,
                "games_count": row.get("games_count", ""),
                "unknown_team_name_used": profile.team_name,
                "unknown_club_name_used": profile.club_name,
                "unknown_age_group_used": profile.age_group or "",
                "unknown_gender_used": profile.gender or "",
                "unknown_state_used": profile.state_code or "",
                "candidate_count": candidate_count,
                "action": action,
                "best_score": f"{best_score:.4f}",
                "matched_team_id_master": best_match["team_id_master"] if best_match else "",
                "matched_team_name": best_match["team_name"] if best_match else "",
                "matched_team_club": best_match["club_name"] if best_match else "",
                "matched_team_age_group": best_match["age_group"] if best_match else "",
                "matched_team_gender": best_match["gender"] if best_match else "",
                "matched_team_state": best_match["state_code"] if best_match else "",
                "execute_status": exec_status,
                "games_backfilled": updated_rows,
            }
        )

        if idx % 200 == 0:
            print(f"Processed {idx}/{len(rows)} rows...")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = Path(
        args.output
        or f"data/exports/unknown_opponent_match_report_{timestamp}.csv"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(report_rows[0].keys()) if report_rows else [])
        if report_rows:
            writer.writeheader()
            for report_row in report_rows:
                writer.writerow(report_row)

    print("=== Unknown Opponent Auto-Match ===")
    print(f"Input rows processed: {stats['total']:,}")
    print(f"Auto-link candidates: {stats['auto_link']:,}")
    print(f"Review bucket: {stats['review']:,}")
    print(f"No match: {stats['no_match']:,}")
    print(f"Skipped (protected division): {stats['skip_protected_division']:,}")
    if args.execute:
        print(f"Executed links: {stats['executed_linked']:,}")
        print(f"Alias conflicts: {stats['executed_conflict']:,}")
        print(f"Games backfilled: {stats['games_backfilled']:,}")
    print(f"Report CSV: {output_path}")

    # Print top sample auto-link suggestions
    top = [r for r in report_rows if r["action"] == "auto_link"]
    top.sort(key=lambda r: float(str(r["best_score"])), reverse=True)
    print("\nTop 10 auto-link suggestions:")
    for i, row in enumerate(top[:10], start=1):
        print(
            f"  {i:>2}. [{row['provider_code']}] {row['unknown_provider_team_id']} "
            f"-> {row['matched_team_name']} ({row['matched_team_id_master']}) "
            f"score={row['best_score']}"
        )


if __name__ == "__main__":
    main()
