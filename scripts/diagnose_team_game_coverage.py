#!/usr/bin/env python3
"""
Diagnose why a team's goal-differential chart stops where it does.

The team page's "Goal Differential Trajectory" chart is a pure function of the
games table: frontend/lib/api.ts getTeamTrajectory reads every non-excluded game
for the team (plus every id merged into it), buckets them into 30-day periods
anchored on the first game after each gap, and plots one point per bucket. There
is no date window, no row cap and no premium gate on that read, so a chart that
stops on a date is telling you the games table stops on that date - for the ids
the chart asks about.

This script replays that read and that bucketing, then looks for the games the
chart is missing in the three places they hide:

  1. Nowhere - never scraped. Shows the scrape queue and scrape-log state.
  2. On a duplicate team row - same club, age group and gender, holding the
     later fixtures. Merge candidates for the merging-duplicate-teams skill.
  3. On the row but invisible - is_excluded, or a null score. A null-score game
     is worse than a missing one here: calculatePeriodMetrics counts it as zero
     games, so its whole period plots as an honest-looking 0.00 goal
     differential rather than a gap.

Read-only: issues no writes and takes no --execute.

Usage:
    python scripts/diagnose_team_game_coverage.py <team_id_master>
    python scripts/diagnose_team_game_coverage.py <team_id_master> --period-days 30
"""

import argparse
import logging
import os
import sys
from datetime import date, datetime

try:
    import truststore

    truststore.inject_into_ssl()
except ImportError:
    pass

from dotenv import load_dotenv  # noqa: E402

from supabase import create_client  # noqa: E402

load_dotenv(".env.local")
load_dotenv(".env")

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.enqueue_helpers import _chunks  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

GAMES_PAGE_SIZE = 1000

# frontend/components/TeamTrajectoryChart.tsx passes 30 to useTeamTrajectory.
DEFAULT_PERIOD_DAYS = 30

# A youth season runs Aug 1 - Jul 31, so a record that stops in June is in its
# normal off-season. Only a gap wider than one season is unexplained by the calendar.
SEASON_GAP_DAYS = 365

GAME_COLUMNS = (
    "id,game_date,home_team_master_id,away_team_master_id,"
    "home_score,away_score,is_excluded,provider,scraped_at"
)


def season_start(today):
    """First day of the Aug 1 - Jul 31 season containing today.

    Mirrors src/utils/team_utils._soccer_season_year.
    """
    return date(today.year if today.month >= 8 else today.year - 1, 8, 1)


def fetch_team(supabase, team_id):
    rows = (
        supabase.table("teams")
        .select(
            "team_id_master,team_name,team_name_original,club_name,age_group,gender,"
            "state_code,provider_id,provider_team_id,is_deprecated,last_scraped_at"
        )
        .eq("team_id_master", team_id)
        .execute()
        .data
        or []
    )
    return rows[0] if rows else None


def fetch_merge_ids(supabase, team_id):
    """Every id the chart's read covers, and the survivor if this id is itself deprecated.

    getTeamTrajectory only walks the merge map one way - canonical_team_id -> deprecated -
    so it never resolves a deprecated id forward. The page redirects deprecated teams
    before the chart mounts, so that gap only bites when teams.is_deprecated has drifted
    out of step with team_merge_map. Report both directions so the drift is visible.
    """
    into = (
        supabase.table("team_merge_map")
        .select("deprecated_team_id")
        .eq("canonical_team_id", team_id)
        .execute()
        .data
        or []
    )
    forward = (
        supabase.table("team_merge_map")
        .select("canonical_team_id")
        .eq("deprecated_team_id", team_id)
        .execute()
        .data
        or []
    )
    deprecated_ids = [r["deprecated_team_id"] for r in into if r["deprecated_team_id"]]
    survivor = forward[0]["canonical_team_id"] if forward else None
    return deprecated_ids, survivor


def fetch_games(supabase, team_ids):
    """Every game row touching any of these ids, excluded ones included.

    The chart filters is_excluded server-side; this does not, so an excluded game
    shows up as a cause rather than as a silence.
    """
    seen = {}
    for batch in _chunks(sorted(team_ids), 50):
        for side in ("home_team_master_id", "away_team_master_id"):
            offset = 0
            while True:
                rows = (
                    supabase.table("games")
                    .select(GAME_COLUMNS)
                    .in_(side, batch)
                    .order("id")
                    .range(offset, offset + GAMES_PAGE_SIZE - 1)
                    .execute()
                    .data
                    or []
                )
                for row in rows:
                    seen[row["id"]] = row
                if len(rows) < GAMES_PAGE_SIZE:
                    break
                offset += GAMES_PAGE_SIZE
    return sorted(seen.values(), key=lambda g: (g["game_date"] or "", g["id"]))


def build_periods(games, team_ids, period_days):
    """Replay getTeamTrajectory's bucketing so the output is the chart's own points.

    The frontend anchors each period on the first game that sits period_days or more
    past the current anchor, so periods track gaps in play rather than the calendar.
    calculatePeriodMetrics then skips any game missing a score, which is why
    games_played can be 0 for a period that still plots a point.
    """
    playable = [g for g in games if not g["is_excluded"] and g["game_date"]]
    if not playable:
        return []

    id_set = set(team_ids)
    periods = []

    def flush(anchor, bucket):
        scored = 0
        goals_for = goals_against = 0
        for g in bucket:
            is_home = g["home_team_master_id"] in id_set
            team_score = g["home_score"] if is_home else g["away_score"]
            opp_score = g["away_score"] if is_home else g["home_score"]
            if team_score is None or opp_score is None:
                continue
            scored += 1
            goals_for += team_score
            goals_against += opp_score
        gd = (goals_for - goals_against) / scored if scored else 0.0
        periods.append(
            {
                "period_start": anchor,
                "rows": len(bucket),
                "games_played": scored,
                "goal_differential": gd,
            }
        )

    anchor = datetime.strptime(playable[0]["game_date"][:10], "%Y-%m-%d").date()
    bucket = []
    for g in playable:
        game_date = datetime.strptime(g["game_date"][:10], "%Y-%m-%d").date()
        if (game_date - anchor).days >= period_days and bucket:
            flush(anchor, bucket)
            anchor = game_date
            bucket = [g]
        else:
            bucket.append(g)
    if bucket:
        flush(anchor, bucket)
    return periods


def find_duplicate_rows(supabase, team):
    """Other live team rows in the same cohort at the same club.

    A provider that renames a team mid-season creates a second row, and the later
    fixtures import against that row rather than this one - which reads on the team
    page as a record that simply stops.
    """
    if not team.get("club_name"):
        return []
    rows = (
        supabase.table("teams")
        .select("team_id_master,team_name,age_group,gender,state_code,provider_id,provider_team_id,last_scraped_at")
        .eq("club_name", team["club_name"])
        .eq("age_group", team["age_group"])
        .eq("gender", team["gender"])
        .eq("is_deprecated", False)
        .execute()
        .data
        or []
    )
    return [r for r in rows if r["team_id_master"] != team["team_id_master"]]


def last_game_dates(supabase, team_ids):
    """Most recent non-excluded game date per team id, for the duplicate table."""
    latest = {}
    for team_id in team_ids:
        for side in ("home_team_master_id", "away_team_master_id"):
            rows = (
                supabase.table("games")
                .select("game_date")
                .eq(side, team_id)
                .eq("is_excluded", False)
                .order("game_date", desc=True)
                .limit(1)
                .execute()
                .data
                or []
            )
            if rows and rows[0]["game_date"]:
                current = latest.get(team_id)
                if current is None or rows[0]["game_date"] > current:
                    latest[team_id] = rows[0]["game_date"]
    return latest


def fetch_queue_state(supabase, team_ids):
    rows = []
    for batch in _chunks(sorted(team_ids), 50):
        rows.extend(
            supabase.table("scrape_requests")
            .select("team_id_master,status,priority,request_type,requested_at,games_found,error_message")
            .in_("team_id_master", batch)
            .order("requested_at", desc=True)
            .limit(10)
            .execute()
            .data
            or []
        )
    return rows


def fetch_scrape_log(supabase, team_ids):
    rows = []
    for batch in _chunks(sorted(team_ids), 50):
        rows.extend(
            supabase.table("team_scrape_log")
            .select("team_id_master,status,games_found,scraped_at,error_message")
            .in_("team_id_master", batch)
            .order("scraped_at", desc=True)
            .limit(10)
            .execute()
            .data
            or []
        )
    return rows


def report(supabase, team_id, period_days):
    team = fetch_team(supabase, team_id)
    if not team:
        logger.error("No team row for %s", team_id)
        return 1

    today = date.today()
    deprecated_ids, survivor = fetch_merge_ids(supabase, team_id)
    chart_ids = [team_id] + deprecated_ids

    print(f"\n=== TEAM {team_id} ===")
    print(f"  name          : {team['team_name']}")
    print(f"  club          : {team.get('club_name')}")
    print(f"  cohort        : {team['age_group']} {team['gender']}  state={team.get('state_code')}")
    print(f"  provider      : {team.get('provider_id')} / {team.get('provider_team_id')}")
    print(f"  is_deprecated : {team['is_deprecated']}")
    print(f"  last_scraped  : {team.get('last_scraped_at')}")
    if survivor:
        print(f"  !! this id is merged INTO {survivor} - the chart does not resolve that direction")
    print(f"  chart reads   : {len(chart_ids)} id(s) (this one + {len(deprecated_ids)} merged in)")

    games = fetch_games(supabase, chart_ids)
    if not games:
        print("\n  No game rows at all. The chart would render 'No trajectory data available'.")
        return 0

    excluded = [g for g in games if g["is_excluded"]]
    visible = [g for g in games if not g["is_excluded"]]
    dated = [g for g in visible if g["game_date"]]
    past = [g for g in dated if g["game_date"][:10] <= today.isoformat()]
    future = [g for g in dated if g["game_date"][:10] > today.isoformat()]
    unscored = [g for g in past if g["home_score"] is None or g["away_score"] is None]

    print("\n=== GAME ROWS ===")
    print(f"  total rows        : {len(games)}")
    print(f"  is_excluded       : {len(excluded)}")
    print(f"  visible to chart  : {len(visible)}")
    print(f"  played (<= today) : {len(past)}")
    print(f"  future fixtures   : {len(future)}")
    print(f"  played, no score  : {len(unscored)}  <- plot as 0.00 goal differential, not as a gap")
    if past:
        print(f"  first played      : {past[0]['game_date'][:10]}")
        print(f"  last played       : {past[-1]['game_date'][:10]}")
    if future:
        print(f"  next fixture      : {future[0]['game_date'][:10]}")

    periods = build_periods(games, chart_ids, period_days)
    print(f"\n=== CHART POINTS ({period_days}-day periods, {len(periods)} plotted) ===")
    for p in periods:
        flag = "  <- plots 0.00 on no scored games" if p["games_played"] == 0 else ""
        print(
            f"  {p['period_start']}  rows={p['rows']:>3}  scored={p['games_played']:>3}  "
            f"GD={p['goal_differential']:+.2f}{flag}"
        )

    if past:
        last_played = datetime.strptime(past[-1]["game_date"][:10], "%Y-%m-%d").date()
        gap = (today - last_played).days
        print("\n=== VERDICT ===")
        print(f"  Record ends {last_played} ({gap} days ago). Season began {season_start(today)}.")
        if gap > SEASON_GAP_DAYS:
            print("  Longer than a full Aug-Jul season: no off-season explains this.")
        elif last_played < season_start(today):
            print("  The record does not reach the current season at all.")
        else:
            print("  Within the current season - a normal off-season gap may explain it.")
        if unscored:
            print(f"  {len(unscored)} played games carry no score; their periods flatten the line toward 0.")

    dupes = find_duplicate_rows(supabase, team)
    if dupes:
        latest = last_game_dates(supabase, [d["team_id_master"] for d in dupes])
        print(f"\n=== OTHER LIVE ROWS IN THIS COHORT AT THIS CLUB ({len(dupes)}) ===")
        for d in sorted(dupes, key=lambda r: latest.get(r["team_id_master"]) or "", reverse=True):
            print(
                f"  {d['team_id_master']}  last_game={latest.get(d['team_id_master']) or '-':<10}  "
                f"{d['provider_id']}/{d['provider_team_id']}  {d['team_name']}"
            )
        print("  A row here holding the missing dates is a merge candidate - see the")
        print("  merging-duplicate-teams skill; decide it on game evidence, not name similarity.")

    queue = fetch_queue_state(supabase, chart_ids)
    print(f"\n=== SCRAPE QUEUE ({len(queue)}) ===")
    for q in queue[:10]:
        print(
            f"  {q['requested_at'][:19]}  {q['status']:<10} p{q['priority']}  {q['request_type']:<16}"
            f"  found={q.get('games_found')}  {(q.get('error_message') or '')[:60]}"
        )
    if not queue:
        print("  No scrape_requests rows - this team has never been queued.")

    log = fetch_scrape_log(supabase, chart_ids)
    print(f"\n=== RECENT SCRAPE LOG ({len(log)}) ===")
    for entry in log[:10]:
        print(
            f"  {str(entry['scraped_at'])[:19]}  {entry['status']:<10} found={entry.get('games_found')}"
            f"  {(entry.get('error_message') or '')[:60]}"
        )
    if not log:
        print("  No team_scrape_log rows for these ids.")

    print()
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("team_id", help="teams.team_id_master UUID (the id in the /teams/<id> URL)")
    parser.add_argument(
        "--period-days",
        type=int,
        default=DEFAULT_PERIOD_DAYS,
        help=f"Bucket width the chart uses (default {DEFAULT_PERIOD_DAYS}, matching the frontend)",
    )
    args = parser.parse_args()

    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY")
    if not url or not key:
        logger.error("SUPABASE_URL and a Supabase key must be set in .env / .env.local")
        return 1

    return report(create_client(url, key), args.team_id, args.period_days)


if __name__ == "__main__":
    sys.exit(main())
