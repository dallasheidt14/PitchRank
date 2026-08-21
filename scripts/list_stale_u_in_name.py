#!/usr/bin/env python3
"""
List teams whose name states a U-age that disagrees with teams.age_group.

A birth year in a name re-maps itself every Aug 1 — "2013" is U14 this season
and U15 the next, with no edit. A U-age does not: it is frozen text, true only
for the season someone typed it. So a U in a name is the one age form that goes
stale, and this is the list of the ones that have.

Unlike audit_name_age_disagreements.py, this does not ask what the normalizer
would rewrite. It asks only what the name says versus what the database says, so
a team appears here whether or not any job would currently touch it.

Reads only. Makes no DB writes.
"""

from __future__ import annotations

import argparse
import collections
import csv
import os
import re
import sys
from datetime import datetime

import psycopg2

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)
sys.path.insert(0, os.path.join(_REPO, "scripts"))

from audit_name_age_disagreements import (  # noqa: E402
    _age_tokens,
    _cohort_label,
    _has_band,
    _token_cohort,
    attach_game_evidence,
    attach_rankings,
    attach_rollover,
    load_teams,
    normalize_team_name,
)

# A U-age as it is actually written: U13, U-13, u12, 13U, BU14, U14B, 14UG.
# Bounded on both sides so the U in a club name cannot start a match.
_U_TOKEN = re.compile(
    r"(?<![A-Za-z0-9])(?:[BbGgMmFf]?[Uu]-?(\d{1,2})[BbGgMmFf]?|(\d{1,2})[Uu][BbGgMmFf]?)(?![A-Za-z0-9])"
)

# A four-digit birth year sitting elsewhere in the same name. Worth carrying,
# because a name holding both a U-age and a year answers the question by itself:
# the year is self-rolling, so where the two disagree the U is the stale half.
_YEAR = re.compile(r"(?<![A-Za-z0-9])(20[0-2]\d)(?![A-Za-z0-9])")

COLUMNS = [
    "delta",
    "u_in_name",
    "age_group_column",
    "year_in_name",
    "year_implies",
    "year_agrees_with_column",
    "current_name",
    "would_become",
    "opp_clean_cohort",
    "opp_clean_share",
    "opp_clean_games",
    "age_group_pre_rollover",
    "rolled_once",
    "is_ranked",
    "rank_status",
    "games_in_window",
    "last_game",
    "name_is_band",
    "club_name",
    "league",
    "distinction",
    "state_code",
    "gender",
    "provider",
    "team_id",
    "team_id_master",
    "created_at",
    "updated_at",
]


def u_ages_in(name: str) -> list:
    """Every U-age the name states, in order, as integers."""
    out = []
    for first, second in _U_TOKEN.findall(name):
        age = int(first or second)
        if 6 <= age <= 19:
            out.append(age)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", help="CSV path (default: logs/stale_u_in_name_<date>.csv)")
    parser.add_argument("--window-days", type=int, default=365, help="Game window for opponent evidence")
    args = parser.parse_args()

    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        sys.exit("DATABASE_URL is not set — this reads the full teams table and needs a direct connection.")

    out = args.out or os.path.join(_REPO, "logs", f"stale_u_in_name_{datetime.now().strftime('%Y%m%d')}.csv")
    os.makedirs(os.path.dirname(out), exist_ok=True)

    conn = psycopg2.connect(database_url)
    with conn, conn.cursor() as cur:
        print("Loading teams...")
        teams = load_teams(cur, include_deprecated=False)
        print(f"  {len(teams):,} live teams")

        rows = []
        with_u = 0
        for (
            tid, master, name, club, _original, age_group, _birth_year, gender,
            state, league, distinction, _deprecated, created, updated, provider,
        ) in teams:
            if not name:
                continue
            ages = u_ages_in(name)
            if not ages:
                continue
            with_u += 1

            column = _cohort_label(age_group)
            if not column:
                continue
            # The first U-age is the one every downstream parser reads.
            stated = ages[0]
            if stated == int(column[1:]):
                continue

            years = _YEAR.findall(name)
            year = years[0] if len(years) == 1 else ""
            year_cohort = _token_cohort(year) if year else ""

            rows.append({
                "team_id": str(tid),
                "team_id_master": str(master) if master else "",
                "current_name": name,
                "would_become": normalize_team_name(name, club, age_group),
                "u_in_name": f"U{stated}",
                "age_group_column": age_group or "",
                "column_label": column,
                "delta": int(column[1:]) - stated,
                "year_in_name": year,
                "year_implies": year_cohort or "",
                "year_agrees_with_column": "" if not year_cohort else str(year_cohort == column),
                "name_is_band": _has_band(name),
                "club_name": club or "",
                "state_code": state or "",
                "gender": gender or "",
                "league": league or "",
                "distinction": distinction or "",
                "provider": provider or "",
                "created_at": created.date().isoformat() if created else "",
                "updated_at": updated.date().isoformat() if updated else "",
            })

        print(f"  {with_u:,} names state a U-age; {len(rows):,} of those disagree with the column")

        print("Loading cohorts for opponent lookup...")
        all_cohorts = {}
        for t in load_teams(cur, include_deprecated=True):
            master, name, club, age_group = t[1], t[2], t[3], t[5]
            if not (master and name):
                continue
            tokens = _age_tokens(normalize_team_name(name, club))
            cohort = _token_cohort(tokens[0]) if tokens else None
            clean = tokens and not tokens[0].startswith("U") and not _has_band(name)
            all_cohorts[str(master)] = (cohort, _cohort_label(age_group), cohort if clean else None)

        print("Attaching rollover history...")
        attach_rollover(cur, rows)
        print("Attaching game evidence...")
        attach_game_evidence(cur, rows, all_cohorts, args.window_days)
        print("Attaching ranking status...")
        attach_rankings(cur, rows)

    conn.close()

    rows.sort(key=lambda r: (-int(r["is_ranked"] == "True"), -abs(r["delta"]), -int(r["games_in_window"] or 0)))

    with open(out, "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    print(f"\nWrote {len(rows):,} rows to {out}\n")

    deltas = collections.Counter(r["delta"] for r in rows)
    ranked = sum(1 for r in rows if r["is_ranked"] == "True")
    print(f"{'name vs column':<20}{'teams':>9}{'ranked':>9}")
    print("-" * 38)
    for delta, n in sorted(deltas.items(), key=lambda kv: -kv[1])[:10]:
        label = f"column is {delta:+d}"
        print(f"{label:<20}{n:>9,}{sum(1 for r in rows if r['delta'] == delta and r['is_ranked'] == 'True'):>9,}")
    print("-" * 38)
    print(f"{'TOTAL':<20}{len(rows):>9,}{ranked:>9,}")

    corroborated = [r for r in rows if r["opp_clean_cohort"] and int(r["opp_clean_games"] or 0) >= 3]
    backs_column = sum(1 for r in corroborated if r["opp_clean_cohort"] == r["column_label"])
    backs_name = sum(1 for r in corroborated if r["opp_clean_cohort"] == r["u_in_name"])
    print(
        f"\nOf {len(corroborated):,} with 3+ games against single-birth-year opponents: "
        f"{backs_column:,} back the column, {backs_name:,} back the name."
    )

    both = [r for r in rows if r["year_agrees_with_column"]]
    agree = sum(1 for r in both if r["year_agrees_with_column"] == "True")
    print(
        f"{len(both):,} names carry a birth year as well; the year agrees with the column on "
        f"{agree:,} of them ({agree / len(both):.0%})."
    )


if __name__ == "__main__":
    main()
