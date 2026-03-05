#!/usr/bin/env python3
"""
Run due diligence checks for unknown-opponent auto-match recommendations.

Input: match report CSV from scripts/auto_match_unknown_opponents.py
Output:
  - due diligence full CSV
  - approved-only CSV
  - needs-review CSV

Checks per auto_link row:
  1) alias conflict (provider_team_id already mapped to another master team?)
  2) metadata agreement with provider API (club/state/age/gender)
  3) cohort agreement from known linked opponents in those games (age/gender)

Typical usage:
  python3 scripts/due_diligence_unknown_opponents.py \\
    --match-report data/exports/unknown_opponent_match_report_weekly.csv \\
    --output-prefix data/exports/unknown_opponent_due_diligence_weekly
"""

from __future__ import annotations

import argparse
import csv
import os
import re
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


def _normalize_gender(g: Optional[str]) -> Optional[str]:
    if not g:
        return None
    s = str(g).strip().lower()
    if s in {"m", "male", "boy", "boys", "b"}:
        return "male"
    if s in {"f", "female", "girl", "girls", "g"}:
        return "female"
    return None


def _normalize_age_group(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    s = str(value).strip().lower()
    if not s:
        return None
    if s.startswith("u") and s[1:].isdigit():
        return s
    if s.isdigit():
        return f"u{s}"
    return None


def _normalize_text(s: Optional[str]) -> str:
    if not s:
        return ""
    out = str(s).lower().strip()
    out = re.sub(r"[^a-z0-9 ]+", " ", out)
    out = " ".join(out.split())
    return out


def _club_compare(unknown_club: str, matched_club: str) -> str:
    u = _normalize_text(unknown_club)
    m = _normalize_text(matched_club)
    if not u or not m:
        return "unknown"
    if u == m:
        return "exact"
    if u in m or m in u:
        return "partial"
    ut = set(u.split())
    mt = set(m.split())
    if not ut or not mt:
        return "unknown"
    overlap = len(ut & mt) / max(1, len(ut | mt))
    return "partial" if overlap >= 0.5 else "mismatch"


class GotSportResolver:
    BASE_URL = "https://system.gotsport.com/api/v1/team_ranking_data/team_details"

    def __init__(self, timeout: int = 20):
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
            "full_name": str(payload.get("full_name") or "").strip(),
            "name": str(payload.get("name") or "").strip(),
            "club_name": str(payload.get("club_name") or "").strip(),
            "state": str(payload.get("state") or "").strip().upper(),
            "age_group": _normalize_age_group(payload.get("age")),
            "gender": _normalize_gender(payload.get("gender")),
        }
        self.cache[key] = resolved
        return resolved


def _write_csv(path: Path, rows: List[Dict], fieldnames: Optional[List[str]] = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    resolved_fieldnames: List[str] = list(fieldnames or [])
    if rows and not resolved_fieldnames:
        resolved_fieldnames = list(rows[0].keys())

    with path.open("w", newline="", encoding="utf-8") as f:
        if not resolved_fieldnames:
            # Nothing to write and no known schema available.
            f.write("")
            return
        writer = csv.DictWriter(f, fieldnames=resolved_fieldnames)
        writer.writeheader()
        if rows:
            writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Due diligence checks for unknown-opponent auto matches")
    parser.add_argument("--match-report", required=True, help="CSV from auto_match_unknown_opponents.py")
    parser.add_argument(
        "--output-prefix",
        default=None,
        help="Output prefix (default: data/exports/unknown_opponent_due_diligence_<timestamp>)",
    )
    parser.add_argument(
        "--strict-name-check",
        action="store_true",
        help="Require literal name check in addition to core identity checks",
    )
    parser.add_argument(
        "--require-all-passing",
        action="store_true",
        help="Exit non-zero unless every auto_link row is approved",
    )
    args = parser.parse_args()

    load_env()
    supabase = get_supabase()
    resolver = GotSportResolver()

    with open(args.match_report, "r", encoding="utf-8") as f:
        all_rows = list(csv.DictReader(f))

    auto_rows = [r for r in all_rows if (r.get("action") or "") == "auto_link"]

    # Collapse by unknown provider team ID to avoid duplicate home/away lines.
    grouped: Dict[Tuple[str, str, str], List[Dict]] = {}
    for row in auto_rows:
        key = (
            (row.get("provider_code") or "").strip().lower(),
            (row.get("provider_id") or "").strip(),
            (row.get("unknown_provider_team_id") or "").strip(),
        )
        grouped.setdefault(key, []).append(row)

    verdict_rows: List[Dict] = []
    approved_rows: List[Dict] = []
    review_rows: List[Dict] = []

    for (provider_code, provider_id, unknown_pid), items in grouped.items():
        # Best row as representative; aggregate side/games.
        best = max(items, key=lambda r: float(r.get("best_score") or 0))
        sides = sorted({(r.get("missing_side") or "").strip().lower() for r in items if r.get("missing_side")})
        total_games = sum(int(r.get("games_count") or 0) for r in items)
        best_score = float(best.get("best_score") or 0)
        matched_team_id = (best.get("matched_team_id_master") or "").strip()

        # Fetch matched team from DB.
        team_data = (
            supabase.table("teams")
            .select("team_id_master,team_name,club_name,age_group,gender,state_code")
            .eq("team_id_master", matched_team_id)
            .limit(1)
            .execute()
            .data
            or []
        )
        team = team_data[0] if team_data else {}

        # Alias conflict check.
        alias_rows = (
            supabase.table("team_alias_map")
            .select("team_id_master")
            .eq("provider_id", provider_id)
            .eq("provider_team_id", unknown_pid)
            .execute()
            .data
            or []
        )
        alias_conflict = bool(alias_rows and alias_rows[0].get("team_id_master") != matched_team_id)

        # Provider metadata check (currently strong coverage for gotsport).
        unknown = resolver.resolve(unknown_pid) if provider_code == "gotsport" else {}

        unknown_age = unknown.get("age_group")
        unknown_gender = unknown.get("gender")
        unknown_state = unknown.get("state")
        unknown_club = unknown.get("club_name", "")
        unknown_full_name = unknown.get("full_name", "") or unknown.get("name", "")

        team_age = _normalize_age_group(team.get("age_group"))
        team_gender = _normalize_gender(team.get("gender"))
        team_state = str(team.get("state_code") or "").upper() or None
        team_club = str(team.get("club_name") or "")

        age_check = "unknown" if not unknown_age or not team_age else ("ok" if unknown_age == team_age else "mismatch")
        gender_check = (
            "unknown" if not unknown_gender or not team_gender else ("ok" if unknown_gender == team_gender else "mismatch")
        )
        state_check = (
            "unknown" if not unknown_state or not team_state else ("ok" if unknown_state == team_state else "mismatch")
        )
        club_check = _club_compare(unknown_club, team_club)

        # Name literal check: relaxed contains/substring matching.
        norm_full = _normalize_text(unknown_full_name)
        norm_team = _normalize_text(str(team.get("team_name") or ""))
        name_literal_check = bool(norm_full and norm_team and (norm_team in norm_full or norm_full in norm_team))

        # Cohort check from already linked opponents in those unresolved games.
        games = (
            supabase.table("games")
            .select("home_provider_id,away_provider_id,home_team_master_id,away_team_master_id")
            .eq("provider_id", provider_id)
            .or_(f"home_provider_id.eq.{unknown_pid},away_provider_id.eq.{unknown_pid}")
            .execute()
            .data
            or []
        )
        known_team_ids = []
        for g in games:
            if str(g.get("home_provider_id")) == unknown_pid and g.get("away_team_master_id"):
                known_team_ids.append(g["away_team_master_id"])
            elif str(g.get("away_provider_id")) == unknown_pid and g.get("home_team_master_id"):
                known_team_ids.append(g["home_team_master_id"])

        cohort_age = None
        cohort_gender = None
        if known_team_ids:
            unique_ids = list(dict.fromkeys(known_team_ids))
            cohort_rows = []
            for i in range(0, len(unique_ids), 500):
                cohort_rows.extend(
                    (
                        supabase.table("teams")
                        .select("team_id_master,age_group,gender")
                        .in_("team_id_master", unique_ids[i : i + 500])
                        .execute()
                        .data
                        or []
                    )
                )
            age_counter = Counter(_normalize_age_group(r.get("age_group")) for r in cohort_rows if r.get("age_group"))
            gen_counter = Counter(_normalize_gender(r.get("gender")) for r in cohort_rows if r.get("gender"))
            cohort_age = age_counter.most_common(1)[0][0] if age_counter else None
            cohort_gender = gen_counter.most_common(1)[0][0] if gen_counter else None

        cohort_age_check = "unknown" if not cohort_age or not team_age else ("ok" if cohort_age == team_age else "mismatch")
        cohort_gender_check = (
            "unknown" if not cohort_gender or not team_gender else ("ok" if cohort_gender == team_gender else "mismatch")
        )

        # Core verdict rule.
        core_ok = all(
            [
                not alias_conflict,
                club_check != "mismatch",
                age_check != "mismatch",
                gender_check != "mismatch",
                state_check != "mismatch",
                cohort_age_check != "mismatch",
                cohort_gender_check != "mismatch",
            ]
        )
        if args.strict_name_check:
            core_ok = core_ok and name_literal_check

        verdict = "approved" if core_ok else "needs_review"

        verdict_row = {
            "provider_code": provider_code,
            "provider_id": provider_id,
            "unknown_provider_team_id": unknown_pid,
            "matched_team_id_master": matched_team_id,
            "matched_team_name": team.get("team_name", ""),
            "matched_team_club": team_club,
            "matched_team_age_group": team_age or "",
            "matched_team_gender": team_gender or "",
            "matched_team_state": team_state or "",
            "rows_collapsed": len(items),
            "sides": "/".join(sides),
            "total_games_impacted": total_games,
            "best_score": f"{best_score:.4f}",
            "alias_conflict": alias_conflict,
            "name_literal_check": name_literal_check,
            "club_check": club_check,
            "age_check": age_check,
            "gender_check": gender_check,
            "state_check": state_check,
            "cohort_age_check": cohort_age_check,
            "cohort_gender_check": cohort_gender_check,
            "unknown_api_full_name": unknown_full_name,
            "unknown_api_club_name": unknown_club,
            "unknown_api_age_group": unknown_age or "",
            "unknown_api_gender": unknown_gender or "",
            "unknown_api_state": unknown_state or "",
            "verdict": verdict,
        }
        verdict_rows.append(verdict_row)
        if verdict == "approved":
            approved_rows.append(verdict_row)
        else:
            review_rows.append(verdict_row)

    # Sort for readability.
    verdict_rows.sort(key=lambda r: (r["verdict"] != "approved", -float(r["best_score"]), -int(r["total_games_impacted"])))
    approved_rows.sort(key=lambda r: (-float(r["best_score"]), -int(r["total_games_impacted"])))
    review_rows.sort(key=lambda r: (-float(r["best_score"]), -int(r["total_games_impacted"])))

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    prefix = args.output_prefix or f"data/exports/unknown_opponent_due_diligence_{timestamp}"
    all_path = Path(f"{prefix}_all.csv")
    approved_path = Path(f"{prefix}_approved.csv")
    review_path = Path(f"{prefix}_needs_review.csv")

    due_diligence_columns = [
        "provider_code",
        "provider_id",
        "unknown_provider_team_id",
        "matched_team_id_master",
        "matched_team_name",
        "matched_team_club",
        "matched_team_age_group",
        "matched_team_gender",
        "matched_team_state",
        "rows_collapsed",
        "sides",
        "total_games_impacted",
        "best_score",
        "alias_conflict",
        "name_literal_check",
        "club_check",
        "age_check",
        "gender_check",
        "state_check",
        "cohort_age_check",
        "cohort_gender_check",
        "unknown_api_full_name",
        "unknown_api_club_name",
        "unknown_api_age_group",
        "unknown_api_gender",
        "unknown_api_state",
        "verdict",
    ]

    _write_csv(all_path, verdict_rows, fieldnames=due_diligence_columns)
    _write_csv(approved_path, approved_rows, fieldnames=due_diligence_columns)
    _write_csv(review_path, review_rows, fieldnames=due_diligence_columns)

    auto_link_count = len(grouped)
    approved_count = len(approved_rows)
    review_count = len(review_rows)
    all_pass = auto_link_count == approved_count

    print("=== Unknown Opponent Due Diligence ===")
    print(f"Auto-link candidates: {auto_link_count}")
    print(f"Approved: {approved_count}")
    print(f"Needs review: {review_count}")
    print(f"All pass: {all_pass}")
    print(f"All CSV: {all_path}")
    print(f"Approved CSV: {approved_path}")
    print(f"Needs-review CSV: {review_path}")

    # CI-friendly key lines
    print(f"DUE_DILIGENCE_AUTO_LINK_COUNT={auto_link_count}")
    print(f"DUE_DILIGENCE_APPROVED_COUNT={approved_count}")
    print(f"DUE_DILIGENCE_REVIEW_COUNT={review_count}")
    print(f"DUE_DILIGENCE_ALL_PASS={'true' if all_pass else 'false'}")
    print(f"DUE_DILIGENCE_ALL_CSV={all_path}")
    print(f"DUE_DILIGENCE_APPROVED_CSV={approved_path}")
    print(f"DUE_DILIGENCE_REVIEW_CSV={review_path}")

    if args.require_all_passing and not all_pass:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
