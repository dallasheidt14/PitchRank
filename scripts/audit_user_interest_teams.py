#!/usr/bin/env python3
"""
User-interest audit: grade the data behind every team a real user has shown
interest in, and report the ones that are genuinely wrong.

Reads the same three interest signals as enqueue_user_interest_teams.py and
grades each team on whether its record looks broken rather than merely quiet.
Read-only.

Staleness is judged against the season, not the calendar. A youth soccer season
runs Aug 1 - Jul 31, and league play restarts in September, so a team whose last
game is in June is in its normal off-season, not missing data. Only a record
that stops for longer than a full season is evidence of a problem.

Usage:
    python scripts/audit_user_interest_teams.py
    python scripts/audit_user_interest_teams.py --out .turbo/reports/user-interest-audit.md
"""

import argparse
import logging
import os
import sys
from datetime import date

try:
    import truststore

    truststore.inject_into_ssl()
except ImportError:
    pass

from dotenv import load_dotenv  # noqa: E402

from supabase import create_client  # noqa: E402

load_dotenv(".env.local")
load_dotenv(".env")

# The scripts directory for the sibling import below, and the repo root for the
# packaged one. enqueue_helpers has to be imported packaged: enqueue_user_interest_teams
# already holds it as scripts.enqueue_helpers, and a bare import here would give one
# file two module identities in the same process.
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from enqueue_user_interest_teams import (  # noqa: E402
    REQUEST_TYPE,
    collect_report_card_teams,
    collect_user_requested_teams,
    collect_watchlisted_teams,
)

from scripts.enqueue_helpers import (  # noqa: E402
    _chunks,
    load_team_rows,
    resolve_merges,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# A record that stops for longer than one full Aug-Jul season has skipped a
# whole year of play, which no off-season explains.
DORMANT_AFTER_DAYS = 365

GAMES_PAGE_SIZE = 1000
REQUEST_PAGE_SIZE = 1000

# Long tails of one-or-two-missing-score teams add rows without adding signal.
REPORT_TABLE_LIMIT = 20


def _cell(value):
    """Make a value safe to drop into a markdown table cell."""
    if value is None:
        return "-"
    return str(value).replace("|", "\\|").replace("\n", " ").strip()


def season_start(today):
    """First day of the Aug 1 - Jul 31 season containing today.

    Mirrors src/utils/team_utils._soccer_season_year, which the ranking side uses.
    """
    return date(today.year if today.month >= 8 else today.year - 1, 8, 1)


def expand_to_aliases(supabase, canonical):
    """Extend a raw-id -> canonical map to cover every deprecated alias of each target.

    A merge leaves games on the pre-merge id, and the interest signals usually name
    the survivor rather than the id its games are filed under. Resolving only the
    ids we started with therefore misses the predecessors' games entirely, so look
    the merge map up a second time by canonical_team_id.
    """
    full = dict(canonical)
    targets = sorted(set(canonical.values()))
    for batch in _chunks(targets):
        rows = (
            supabase.table("team_merge_map")
            .select("deprecated_team_id,canonical_team_id")
            .in_("canonical_team_id", batch)
            .execute()
            .data
            or []
        )
        for r in rows:
            full[r["deprecated_team_id"]] = r["canonical_team_id"]
    for target in targets:
        full.setdefault(target, target)
    return full


def fetch_game_facts(supabase, alias_map, today):
    """Per canonical team: total games, last played date, unplayed fixtures, missing scores.

    Counts only games a user would see: every frontend read path filters is_excluded.
    """
    facts = {c: {"games": 0, "last_game": None, "future": 0, "null_scores": 0} for c in set(alias_map.values())}
    iso_today = today.isoformat()
    for batch in _chunks(sorted(alias_map), 50):
        for side in ("home_team_master_id", "away_team_master_id"):
            offset = 0
            while True:
                rows = (
                    supabase.table("games")
                    .select("id,home_team_master_id,away_team_master_id,game_date,home_score,away_score")
                    .in_(side, batch)
                    .eq("is_excluded", False)
                    .order("id")
                    .range(offset, offset + GAMES_PAGE_SIZE - 1)
                    .execute()
                    .data
                    or []
                )
                for row in rows:
                    f = facts[alias_map[row[side]]]
                    f["games"] += 1
                    game_date = row["game_date"]
                    if not game_date:
                        continue
                    if game_date > iso_today:
                        f["future"] += 1
                        continue
                    if f["last_game"] is None or game_date > f["last_game"]:
                        f["last_game"] = game_date
                    if row["home_score"] is None or row["away_score"] is None:
                        f["null_scores"] += 1
                if len(rows) < GAMES_PAGE_SIZE:
                    break
                offset += GAMES_PAGE_SIZE
    return facts


def fetch_ranked_ids(supabase, team_ids):
    ranked = set()
    for batch in _chunks(sorted(team_ids)):
        rows = supabase.table("rankings_full").select("team_id").in_("team_id", batch).execute().data or []
        ranked.update(r["team_id"] for r in rows)
    return ranked


def fetch_last_batch_outcome(supabase):
    """Outcome of the rows the most recent enqueue run wrote.

    Rows survive completion, so bound the read to the newest run's own day.
    Without that the tally silently blends every run once a second one exists.
    """
    newest = (
        supabase.table("scrape_requests")
        .select("requested_at")
        .eq("request_type", REQUEST_TYPE)
        .order("requested_at", desc=True)
        .limit(1)
        .execute()
        .data
        or []
    )
    if not newest:
        return {}
    day = newest[0]["requested_at"][:10]
    rows, offset = [], 0
    while True:
        page = (
            supabase.table("scrape_requests")
            .select("status,error_message,team_name,games_found")
            .eq("request_type", REQUEST_TYPE)
            .gte("requested_at", day)
            .order("id")
            .range(offset, offset + REQUEST_PAGE_SIZE - 1)
            .execute()
            .data
            or []
        )
        rows.extend(page)
        if len(page) < REQUEST_PAGE_SIZE:
            break
        offset += REQUEST_PAGE_SIZE
    outcome = {}
    for r in rows:
        outcome.setdefault(r["status"], []).append(r)
    return outcome


def grade(team, facts, ranked, today):
    """Classify a team's record. Only 'dormant' and 'no games' are real defects."""
    if facts["games"] == 0:
        return "no games"
    if facts["last_game"] is None:
        return "no games played"
    days = (today - date.fromisoformat(facts["last_game"])).days
    if days > DORMANT_AFTER_DAYS:
        return "dormant"
    if facts["last_game"] >= season_start(today).isoformat():
        # Absent from rankings_full only counts against a team that is playing now.
        # A team between seasons has no current-season games to be rated on.
        return "active this season" if team["team_id_master"] in ranked else "unranked"
    return "between seasons"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", help="Write a markdown report to this path")
    args = parser.parse_args()

    url = os.environ.get("SUPABASE_URL") or os.environ.get("NEXT_PUBLIC_SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_KEY")
    if not url or not key:
        logger.error("Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY")
        sys.exit(1)

    supabase = create_client(url, key)
    today = date.today()

    watchlisted = collect_watchlisted_teams(supabase)
    report_card = collect_report_card_teams(supabase)
    requested = collect_user_requested_teams(supabase)
    raw_ids = watchlisted | report_card | requested
    canonical = resolve_merges(supabase, raw_ids)
    team_rows = load_team_rows(supabase, set(canonical.values()))

    alias_map = expand_to_aliases(supabase, canonical)
    facts = fetch_game_facts(supabase, alias_map, today)
    ranked = fetch_ranked_ids(supabase, set(team_rows))
    outcome = fetch_last_batch_outcome(supabase)

    graded = {}
    for team_id, team in team_rows.items():
        graded[team_id] = grade(team, facts[team_id], ranked, today)

    counts = {}
    for verdict in graded.values():
        counts[verdict] = counts.get(verdict, 0) + 1

    logger.info(
        f"Interest signals: {len(watchlisted)} watchlisted, {len(report_card)} report-card leads, "
        f"{len(requested)} user-requested -> {len(team_rows)} teams"
    )
    recovered = sum(r["games_found"] or 0 for rows in outcome.values() for r in rows)
    logger.info(f"Last enqueue batch: { {k: len(v) for k, v in outcome.items()} } | games found: {recovered}")
    for verdict in sorted(counts, key=lambda v: -counts[v]):
        logger.info(f"  {verdict}: {counts[verdict]}")

    needs_review = sorted(
        (t for t, v in graded.items() if v in ("no games", "no games played", "dormant", "unranked")),
        key=lambda t: facts[t]["last_game"] or "",
    )
    missing_scores = sorted(
        (t for t in team_rows if facts[t]["null_scores"]), key=lambda t: -facts[t]["null_scores"]
    )

    logger.info(f"Needs review: {len(needs_review)} | teams with missing scores: {len(missing_scores)}")
    for team_id in needs_review:
        f = facts[team_id]
        logger.info(
            f"  {team_rows[team_id]['team_name'][:44]:46s} {graded[team_id]:10s} "
            f"games={f['games']:<4d} last={f['last_game'] or 'never'}"
        )

    if not args.out:
        return

    lines = [
        "# User activity retention hygiene",
        "",
        f"{today.isoformat()}. {len(team_rows)} teams with a real user-interest signal: "
        f"{len(watchlisted)} watchlisted, {len(report_card)} report-card leads, "
        f"{len(requested)} user-requested.",
        "",
        "Staleness is graded against the Aug 1 - Jul 31 season. A record ending in June or",
        f"July is a normal off-season. Only a gap longer than {DORMANT_AFTER_DAYS} days counts as dormant.",
        "",
        "| Verdict | Teams |",
        "|---|---|",
    ]
    for verdict in sorted(counts, key=lambda v: -counts[v]):
        lines.append(f"| {verdict} | {counts[verdict]} |")

    lines += ["", f"## Needs review ({len(needs_review)})", ""]
    if needs_review:
        lines += ["| Team | Verdict | Games | Last game | Upcoming |", "|---|---|---|---|---|"]
        for team_id in needs_review:
            f = facts[team_id]
            lines.append(
                f"| {_cell(team_rows[team_id]['team_name'])} | {graded[team_id]} | {f['games']} | "
                f"{f['last_game'] or 'never'} | {f['future']} |"
            )
    else:
        lines.append("Nothing. Every interest team has a record consistent with its season.")

    total_missing = sum(facts[t]["null_scores"] for t in missing_scores)
    lines += [
        "",
        f"## Games on record with no score ({len(missing_scores)} teams, {total_missing} games)",
        "",
        "Re-scraping does not recover these; the provider has not posted the result.",
        "Anything from the last two weeks may still post normally.",
        "",
    ]
    if missing_scores:
        lines += ["| Team | Missing | Last game |", "|---|---|---|"]
        for team_id in missing_scores[:REPORT_TABLE_LIMIT]:
            f = facts[team_id]
            lines.append(f"| {_cell(team_rows[team_id]['team_name'])} | {f['null_scores']} | {f['last_game']} |")
        if len(missing_scores) > REPORT_TABLE_LIMIT:
            lines.append("")
            lines.append(f"...and {len(missing_scores) - REPORT_TABLE_LIMIT} more teams with fewer missing scores.")

    lines += [
        "",
        "## Previous batch",
        "",
        f"Enqueued {sum(len(v) for v in outcome.values())} teams; "
        f"{recovered} games found across the batch.",
        "",
    ]
    failed = outcome.get("failed", [])
    lines += [f"### Failures ({len(failed)})", ""]
    if failed:
        by_reason = {}
        for r in failed:
            by_reason.setdefault(r["error_message"] or "unknown", []).append(r["team_name"])
        lines += ["| Reason | Teams |", "|---|---|"]
        for reason, teams in sorted(by_reason.items(), key=lambda kv: -len(kv[1])):
            lines.append(f"| {_cell(reason)} | {len(teams)}: {_cell(', '.join(teams))} |")
    else:
        lines.append("None.")

    out_dir = os.path.dirname(os.path.abspath(args.out))
    os.makedirs(out_dir, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    logger.info(f"Wrote report to {args.out}")


if __name__ == "__main__":
    main()
