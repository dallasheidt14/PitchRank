#!/usr/bin/env python3
"""
Investigate two failure modes surfaced by Bucket 4 of the distinction dry-run:

(c) Age-group misclassification — team_name embeds a 4-digit birth year that
    DOES NOT match the team's stored age_group. Likely caused by club names
    containing numbers (e.g., 'Union 10 FC') eating the parse before the
    real birth year token is reached.

(d) Missing league — team_name embeds a recognized league marker (ECNL, NPL,
    GA, DPL, MLS NEXT, etc.) but the `league` column is NULL. Suggests
    backfill_team_leagues.py missed it or the team was created without the
    backfill running.

Outputs:
  - logs/age_misclass_candidates.csv
  - logs/missing_league_candidates.csv
plus per-failure-mode counts and a sample of each pattern.
"""

from __future__ import annotations

import collections
import csv
import os
import re
import sys
from datetime import date

from dotenv import load_dotenv

load_dotenv("C:/PitchRank/.env.local")
load_dotenv("C:/PitchRank/.env")

sys.path.insert(0, "C:/PitchRank")
from src.utils.team_utils import calculate_age_group_from_birth_year  # noqa: E402

from supabase import create_client  # noqa: E402

# Recognized league markers (string patterns). Map to the canonical
# `league` column enum already in use (see league distribution from earlier query).
# Order matters — check more-specific markers first (ECNL_RL before ECNL).
LEAGUE_MARKERS = [
    (re.compile(r"\b(ECNL[- ]?RL|ECRL)\b", re.I), "ECNL_RL"),
    (re.compile(r"\bECNL\b", re.I), "ECNL"),
    (re.compile(r"\bMLS[- ]?NEXT[- ]?AD\b", re.I), "MLS_NEXT_AD"),
    (re.compile(r"\bMLS[- ]?NEXT[- ]?HD\b", re.I), "MLS_NEXT_HD"),
    (re.compile(r"\bMLS[- ]?NEXT\b", re.I), "MLS_NEXT_AD"),  # generic → AD
    (re.compile(r"\bDPLO?\b", re.I), "DPL"),
    (re.compile(r"\bNPL\b", re.I), "NPL"),
    (re.compile(r"\bASPIRE\b", re.I), "ASPIRE"),
    (re.compile(r"\bEA2\b", re.I), "EA2"),
    (re.compile(r"\bEA\b", re.I), "EA"),
    (re.compile(r"\bGA\b", re.I), "GA"),
    (re.compile(r"\bNL\b(?!\w)", re.I), "NL"),  # NL alone, not NLSA etc.
]


def detect_league_markers(name: str) -> set:
    """Return the set of canonical league enums implied by markers in `name`."""
    if not name:
        return set()
    out = set()
    s = name
    for pat, canonical in LEAGUE_MARKERS:
        if pat.search(s):
            out.add(canonical)
    return out


def infer_birth_years(name: str) -> list:
    """Pull all plausible 4-digit birth years from team_name (range 2005-2020)."""
    if not name:
        return []
    years = re.findall(r"\b(20[01][0-9]|2020)\b", name)
    out = []
    for y in years:
        n = int(y)
        if 2005 <= n <= 2020:
            out.append(n)
    return out


def main():
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_SERVICE_KEY")
    c = create_client(url, key)

    teams = []
    page = 0
    while True:
        r = (
            c.table("teams")
            .select("id,team_name,team_name_original,club_name,age_group,gender,state_code,league,is_deprecated")
            .range(page * 1000, page * 1000 + 999)
            .execute()
        )
        if not r.data:
            break
        teams.extend(r.data)
        page += 1
        if page > 200:
            break
    print(f"Scanned {len(teams):,} teams")

    live = [t for t in teams if not t.get("is_deprecated")]
    print(f"Live teams: {len(live):,}")

    # ─────────────────────────────────────────────────────────────
    # (c) Age-group misclassification
    # ─────────────────────────────────────────────────────────────
    age_misclass = []
    age_misclass_by_club = collections.Counter()

    def _norm_age(ag: str | None) -> str:
        """Apply PitchRank's U18→U19 remap and U20+ cap.

        Per memory: U18 merges into U19. U20+ caps at U19 (no older cohort).
        Without this, every 2008/2007 dual-year team flags as misclassified.
        """
        if not ag:
            return ""
        ag = ag.lower()
        m = re.match(r"u(\d+)", ag)
        if not m:
            return ag
        n = int(m.group(1))
        if n == 18:
            n = 19
        if n > 19:
            n = 19
        return f"u{n}"

    for t in live:
        stored_age = _norm_age(t.get("age_group"))
        if not stored_age:
            continue
        name = t.get("team_name") or ""
        years = infer_birth_years(name)
        if not years:
            continue
        # Try ALL years — if any (after remap) matches stored, no misclass.
        # Out-of-range years (2005, 2006 → None from calculator) should be
        # treated as "compatible with u19" since u19 is the cap (older players
        # play up into the oldest cohort). Otherwise every 2006 team flags.
        any_match = False
        suggested = None
        for y in years:
            raw_ag = calculate_age_group_from_birth_year(y)
            if raw_ag is None:
                # Pre-2007 birth year → caps at u19 in our schema
                if 2005 <= y <= 2006 and stored_age == "u19":
                    any_match = True
                    break
                continue
            ag = _norm_age(raw_ag)
            if ag == stored_age:
                any_match = True
                break
            if not suggested:
                suggested = ag or None
        if any_match:
            continue
        # No year in the name matches stored age → candidate misclass
        age_misclass.append({
            "id": t["id"],
            "club_name": t.get("club_name"),
            "stored_age": stored_age,
            "team_name": name,
            "team_name_original": t.get("team_name_original") or "",
            "years_in_name": ",".join(str(y) for y in years),
            "suggested_age": suggested or "",
            "state_code": t.get("state_code"),
            "gender": t.get("gender"),
            "league": t.get("league"),
        })
        age_misclass_by_club[t.get("club_name") or "(none)"] += 1

    out_path = "C:/PitchRank/logs/age_misclass_candidates.csv"
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(age_misclass[0].keys()) if age_misclass else [
            "id", "club_name", "stored_age", "team_name", "team_name_original",
            "years_in_name", "suggested_age", "state_code", "gender", "league",
        ])
        w.writeheader()
        for row in age_misclass:
            w.writerow(row)

    print(f"\n=== (c) AGE-GROUP MISCLASSIFICATION ===")
    print(f"  Live teams with year-in-name not matching stored age: {len(age_misclass):,}")
    print(f"  → CSV: {out_path}")
    print(f"\n  Top 15 clubs by misclass count:")
    for club, n in age_misclass_by_club.most_common(15):
        print(f"    {n:>4}  {club}")
    print(f"\n  Sample 12 misclassified teams:")
    for row in age_misclass[:12]:
        print(f"    [{row['stored_age']!s:>4} → {row['suggested_age']!s:>4}]  "
              f"club={row['club_name']!r:30.30}  name={row['team_name']!r}")

    # ─────────────────────────────────────────────────────────────
    # (d) Missing league
    # ─────────────────────────────────────────────────────────────
    missing_league = []
    by_league = collections.Counter()
    by_club = collections.Counter()
    league_mismatch = []  # league IS set but team_name implies a different one

    # League column is only populated for u13+ (per ranking-engine scope).
    # u10/u11/u12 NULLs are by design, not bugs.
    _LEAGUE_AGE_GROUPS = {"u13", "u14", "u15", "u16", "u17", "u18", "u19"}

    for t in live:
        ag = (t.get("age_group") or "").lower()
        if ag not in _LEAGUE_AGE_GROUPS:
            continue
        name = t.get("team_name") or ""
        markers = detect_league_markers(name)
        stored_league = t.get("league")

        if not markers:
            continue

        if stored_league is None:
            # Pick the most "specific" marker as the suggestion
            order = ["ECNL_RL", "ECNL", "MLS_NEXT_AD", "MLS_NEXT_HD", "DPL",
                     "NPL", "ASPIRE", "EA2", "EA", "GA", "NL"]
            suggestion = next((m for m in order if m in markers), next(iter(markers)))
            missing_league.append({
                "id": t["id"],
                "club_name": t.get("club_name"),
                "team_name": name,
                "team_name_original": t.get("team_name_original") or "",
                "markers_in_name": "|".join(sorted(markers)),
                "suggested_league": suggestion,
                "age_group": t.get("age_group"),
                "state_code": t.get("state_code"),
                "gender": t.get("gender"),
            })
            by_league[suggestion] += 1
            by_club[t.get("club_name") or "(none)"] += 1
        else:
            if stored_league not in markers:
                league_mismatch.append({
                    "id": t["id"],
                    "club_name": t.get("club_name"),
                    "team_name": name,
                    "stored_league": stored_league,
                    "markers_in_name": "|".join(sorted(markers)),
                })

    out_path2 = "C:/PitchRank/logs/missing_league_candidates.csv"
    with open(out_path2, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(missing_league[0].keys()) if missing_league else [
            "id", "club_name", "team_name", "team_name_original",
            "markers_in_name", "suggested_league", "age_group", "state_code", "gender",
        ])
        w.writeheader()
        for row in missing_league:
            w.writerow(row)

    print(f"\n=== (d) MISSING LEAGUE ===")
    print(f"  Live teams with league marker in name but `league` IS NULL: {len(missing_league):,}")
    print(f"  → CSV: {out_path2}")
    print(f"\n  Suggested league distribution:")
    for lg, n in by_league.most_common():
        print(f"    {lg:>15}  {n:>6,}")
    print(f"\n  Top 15 clubs by missing-league count:")
    for club, n in by_club.most_common(15):
        print(f"    {n:>4}  {club}")
    print(f"\n  Sample 12 missing-league teams:")
    for row in missing_league[:12]:
        print(f"    [→ {row['suggested_league']:>11}]  "
              f"club={row['club_name']!r:30.30}  name={row['team_name']!r}")

    print(f"\n=== (d-extra) LEAGUE MISMATCH (stored vs name) ===")
    print(f"  Live teams where stored league differs from name marker: {len(league_mismatch):,}")
    if league_mismatch[:8]:
        print(f"  Sample 8:")
        for row in league_mismatch[:8]:
            print(f"    stored={row['stored_league']:>11}  markers={row['markers_in_name']:<25}  "
                  f"name={row['team_name']!r}")


if __name__ == "__main__":
    main()
