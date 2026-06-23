#!/usr/bin/env python3
"""State-of-<State> youth soccer report generator.

Pulls first-party ranking and match stats for one state from Supabase and emits a
committed TS data module that the static "State of <State> Youth Soccer" report
post imports. A credibility gate hard-fails before anything is written if the
state's data is below the defensibility floor, so a published report can never
carry one state's title over another state's (or thin) data.

Run: python scripts/generate_state_report.py --state TX --year 2026 --window-days 30
"""

import argparse
import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path

import psycopg2
from dotenv import load_dotenv
from psycopg2.extras import RealDictCursor

env_local = Path(".env.local")
if env_local.exists():
    load_dotenv(env_local, override=True)
else:
    load_dotenv()

REPORTS_DIR = Path("frontend/content/reports")

# The full ranking window the engine considers, used for the "matches analyzed"
# claim — distinct from the 7/30-day movers bucket.
RANKING_WINDOW_DAYS = 365

# Movers are capped to teams currently inside the top of their state cohort so the
# report highlights climbs into contention, not developmental teams swinging deep
# in the standings.
MOVERS_MAX_STATE_RANK = 100

# Credibility floor — a report is only published for a state whose data is
# statistically defensible. Below either bar the generator writes nothing.
MIN_RANKED_TEAMS = 2000
REQUIRED_LEAGUES = ("ECNL", "NL", "EA")
MIN_PER_REQUIRED_LEAGUE = 5

STATE_NAMES = {
    "AL": "Alabama",
    "AK": "Alaska",
    "AZ": "Arizona",
    "AR": "Arkansas",
    "CA": "California",
    "CO": "Colorado",
    "CT": "Connecticut",
    "DE": "Delaware",
    "DC": "District of Columbia",
    "FL": "Florida",
    "GA": "Georgia",
    "HI": "Hawaii",
    "ID": "Idaho",
    "IL": "Illinois",
    "IN": "Indiana",
    "IA": "Iowa",
    "KS": "Kansas",
    "KY": "Kentucky",
    "LA": "Louisiana",
    "ME": "Maine",
    "MD": "Maryland",
    "MA": "Massachusetts",
    "MI": "Michigan",
    "MN": "Minnesota",
    "MS": "Mississippi",
    "MO": "Missouri",
    "MT": "Montana",
    "NE": "Nebraska",
    "NV": "Nevada",
    "NH": "New Hampshire",
    "NJ": "New Jersey",
    "NM": "New Mexico",
    "NY": "New York",
    "NC": "North Carolina",
    "ND": "North Dakota",
    "OH": "Ohio",
    "OK": "Oklahoma",
    "OR": "Oregon",
    "PA": "Pennsylvania",
    "RI": "Rhode Island",
    "SC": "South Carolina",
    "SD": "South Dakota",
    "TN": "Tennessee",
    "TX": "Texas",
    "UT": "Utah",
    "VT": "Vermont",
    "VA": "Virginia",
    "WA": "Washington",
    "WV": "West Virginia",
    "WI": "Wisconsin",
    "WY": "Wyoming",
}


def _open_connection():
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        print("ERROR: DATABASE_URL not set in environment (.env / .env.local)")
        sys.exit(1)
    return psycopg2.connect(database_url)


def fetch_headline(cur, state: str) -> dict:
    cur.execute(
        """
        SELECT count(*) AS ranked_teams,
               count(*) FILTER (WHERE gender IN ('Male', 'M', 'Boys')) AS male,
               count(*) FILTER (WHERE gender IN ('Female', 'F', 'Girls')) AS female,
               count(DISTINCT (age_group, gender)) AS groups
        FROM rankings_full
        WHERE state_code = %(state)s AND status <> 'Not Enough Ranked Games'
        """,
        {"state": state},
    )
    return cur.fetchone()


def fetch_age_groups(cur, state: str) -> list[dict]:
    cur.execute(
        """
        SELECT age_group, count(*) AS cnt
        FROM rankings_full
        WHERE state_code = %(state)s AND status <> 'Not Enough Ranked Games'
        GROUP BY age_group
        ORDER BY cnt DESC, age_group
        """,
        {"state": state},
    )
    return cur.fetchall()


def fetch_league_counts(cur, state: str) -> list[dict]:
    cur.execute(
        """
        SELECT t.league, count(*) AS cnt
        FROM rankings_full rf
        JOIN teams t ON t.team_id_master = rf.team_id
        WHERE rf.state_code = %(state)s
          AND rf.status <> 'Not Enough Ranked Games'
          AND t.league IS NOT NULL
        GROUP BY t.league
        ORDER BY cnt DESC, t.league
        """,
        {"state": state},
    )
    return cur.fetchall()


def fetch_matches_analyzed(cur, state: str) -> int:
    cur.execute(
        """
        SELECT count(*) AS matches
        FROM games g
        WHERE g.is_excluded = false
          AND g.home_score IS NOT NULL AND g.away_score IS NOT NULL
          AND g.game_date >= CURRENT_DATE - make_interval(days => %(days)s)
          AND NOT (COALESCE(g.competition, '') ILIKE '%%futsal%%'
                   OR COALESCE(g.event_name, '') ILIKE '%%futsal%%'
                   OR COALESCE(g.division_name, '') ILIKE '%%futsal%%')
          AND (g.home_team_master_id IN (SELECT team_id_master FROM teams WHERE state_code = %(state)s)
               OR g.away_team_master_id IN (SELECT team_id_master FROM teams WHERE state_code = %(state)s))
        """,
        {"days": RANKING_WINDOW_DAYS, "state": state},
    )
    return cur.fetchone()["matches"]


def fetch_movers(cur, state: str, direction: str, bucket: int, limit: int = 5) -> list[dict]:
    cur.execute(
        """
        SELECT m.rank_change, m.current_rank,
               rf.age_group, rf.gender,
               COALESCE(t.team_name, m.team_name) AS team_name,
               COALESCE(t.club_name, m.club_name) AS club_name,
               t.league, t.distinction
        FROM get_biggest_state_movers(%(state)s, %(limit)s, %(dir)s, %(days)s, NULL, NULL, %(max_rank)s) m
        LEFT JOIN rankings_full rf ON rf.team_id = m.team_id
        LEFT JOIN teams t ON t.team_id_master = m.team_id
        ORDER BY abs(m.rank_change) DESC
        """,
        {"state": state, "limit": limit, "dir": direction, "days": bucket, "max_rank": MOVERS_MAX_STATE_RANK},
    )
    return cur.fetchall()


def fetch_league_callouts(cur, state: str, leagues: tuple[str, ...]) -> list[dict]:
    cur.execute(
        """
        SELECT DISTINCT ON (t.league)
               t.league, t.team_name, t.club_name, t.distinction,
               rf.age_group, rf.gender
        FROM rankings_full rf
        JOIN teams t ON t.team_id_master = rf.team_id
        WHERE rf.state_code = %(state)s
          AND rf.status <> 'Not Enough Ranked Games'
          AND t.league = ANY(%(leagues)s)
        ORDER BY t.league, rf.power_score_final DESC NULLS LAST
        """,
        {"state": state, "leagues": list(leagues)},
    )
    return cur.fetchall()


def _team_fields(row: dict) -> dict:
    return {
        "teamName": row["team_name"],
        "clubName": row["club_name"],
        "league": row["league"],
        "distinction": row["distinction"],
    }


def _mover(row: dict) -> dict:
    return {
        **_team_fields(row),
        "ageGroup": row["age_group"],
        "gender": row["gender"],
        "rankChange": row["rank_change"],
        "currentRank": row["current_rank"],
    }


def _callout(row: dict) -> dict:
    return {**_team_fields(row), "ageGroup": row["age_group"], "gender": row["gender"]}


def run_credibility_gate(state: str, state_name: str, ranked_teams: int, league_counts: dict) -> None:
    failures = []
    if ranked_teams < MIN_RANKED_TEAMS:
        failures.append(f"{ranked_teams} ranked teams < {MIN_RANKED_TEAMS} minimum")
    below = [
        f"{lg} ({league_counts.get(lg, 0)})"
        for lg in REQUIRED_LEAGUES
        if league_counts.get(lg, 0) < MIN_PER_REQUIRED_LEAGUE
    ]
    if below:
        failures.append(f"required leagues below {MIN_PER_REQUIRED_LEAGUE} ranked teams: {', '.join(below)}")
    if failures:
        raise SystemExit(
            f"Credibility gate FAILED for {state} ({state_name}): " + "; ".join(failures) + ". No report written."
        )


def build_report(state: str, year: int, bucket: int) -> dict:
    state_name = STATE_NAMES.get(state)
    if not state_name:
        raise SystemExit(f"Unknown state code: {state}")
    slug = f"state-of-{state_name.lower().replace(' ', '-')}-youth-soccer-{year}"
    today = date.today()

    conn = _open_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            headline = fetch_headline(cur, state)
            league_rows = fetch_league_counts(cur, state)
            age_rows = fetch_age_groups(cur, state)

            league_counts = {r["league"]: r["cnt"] for r in league_rows}
            run_credibility_gate(state, state_name, headline["ranked_teams"], league_counts)

            matches = fetch_matches_analyzed(cur, state)
            movers_up = fetch_movers(cur, state, "up", bucket)
            movers_down = fetch_movers(cur, state, "down", bucket)
            callouts = fetch_league_callouts(cur, state, REQUIRED_LEAGUES)
    finally:
        conn.close()

    return {
        "state": state,
        "stateName": state_name,
        "year": year,
        "slug": slug,
        "generatedAt": today.isoformat(),
        "windowBucket": bucket,
        "temporalCoverage": f"{(today - timedelta(days=RANKING_WINDOW_DAYS)).isoformat()}/{today.isoformat()}",
        "rankedTeams": headline["ranked_teams"],
        "matchesAnalyzed": matches,
        "totalGroups": headline["groups"],
        "genderSplit": {"male": headline["male"], "female": headline["female"]},
        "deepestAgeGroup": {"ageGroup": age_rows[0]["age_group"], "count": age_rows[0]["cnt"]},
        "ageGroups": [{"ageGroup": r["age_group"], "count": r["cnt"]} for r in age_rows],
        "leagues": [{"league": r["league"], "count": r["cnt"]} for r in league_rows],
        "topMovers": {
            "up": [_mover(r) for r in movers_up],
            "down": [_mover(r) for r in movers_down],
        },
        "leagueCallouts": [_callout(r) for r in callouts],
    }


def write_report(report: dict) -> Path:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = REPORTS_DIR / f"{report['slug']}.ts"
    banner = "// AUTO-GENERATED by scripts/generate_state_report.py — do not edit by hand.\n"
    body = "export const report = " + json.dumps(report, indent=2) + " as const;\n"
    out_path.write_text(banner + body, encoding="utf-8")
    return out_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a State-of-<State> youth soccer report data module")
    parser.add_argument("--state", required=True, type=lambda s: s.upper(), help="Two-letter state code, e.g. TX")
    parser.add_argument("--year", required=True, type=int, help="Report year, e.g. 2026")
    parser.add_argument(
        "--window-days",
        type=int,
        choices=(7, 30),
        default=30,
        help="Movers bucket: 7 uses the 7-day state delta, 30 the 30-day delta",
    )
    args = parser.parse_args()

    report = build_report(args.state, args.year, args.window_days)
    out_path = write_report(report)
    print(
        f"Wrote {out_path} — {report['rankedTeams']} ranked teams, "
        f"{report['matchesAnalyzed']} matches analyzed, {report['totalGroups']} groups"
    )


if __name__ == "__main__":
    main()
