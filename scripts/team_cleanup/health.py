#!/usr/bin/env python3
"""The weekly team-data health report: per-state counts, the change since the previous report, and
what keeps rising.

Never writes to the database. Writes <store>/health/<date>.md and puts that date's rows into
<store>/health/health_history.csv, replacing any already filed under that date, so re-running a date
never doubles it.

A team's bucket is its state code; "(no state)" when blank, "(non-US)" for a Canadian province, and
"(malformed)" for anything else. Counted per bucket:

  live teams
  blank club        a live team whose club_name is null, or empty after trimming
  placeholder club  a live team whose club_name is not blank but names no club
                    (src/utils/placeholder_clubs)
  merged but live   a live team still listed as deprecated in team_merge_map (should be 0)
  self-play games   games whose two sides resolve, through merges, to one team; an excluded game
                    still counts, because the row stays fused
  new this week     teams created in the seven days before the report date (UTC)
  open problems     the four problem counts above, plus every live team in (no state) or (malformed)

and, nationally and by source, the week's new teams and how many have no state, no club (blank or
placeholder), or an unknown_<id> name.

Only which teams count as the week's new teams follows --date; everything else, including those
teams' state, club and name, is read as of the run, so a past --date files today's figures under
the old date.

Usage:
    python scripts/team_cleanup/health.py
    python scripts/team_cleanup/health.py --store <dir> --date 2026-10-14 --dry-run
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.find_cross_provider_duplicates import get_client, load_merge_map, page, resolver  # noqa: E402
from scripts.team_cleanup.run_store import store_dir  # noqa: E402
from src.tournaments.storage._io import read_csv, write_csv  # noqa: E402
from src.utils.canadian_provinces import CANADIAN_PROVINCES  # noqa: E402
from src.utils.placeholder_clubs import is_placeholder_club  # noqa: E402
from src.utils.us_states import STATE_CODE_TO_NAME  # noqa: E402

HEALTH_DIR = "health"
HISTORY_FILE = "health_history.csv"
HISTORY_FIELDS = ("date", "bucket", "metric", "value")
NATIONAL = "ALL"
SOURCE_PREFIX = "source:"
GAMES_PAGE = 50000

NO_STATE, NON_US, MALFORMED = "(no state)", "(non-US)", "(malformed)"
# Always written, so a bucket the cleanup empties shows 0 rather than vanishing from the table.
SPECIAL_BUCKETS = (NO_STATE, NON_US, MALFORMED)
UNKNOWN_NAME = re.compile(r"unknown_\d+", re.IGNORECASE)

STATE_METRICS = {
    "live_teams": "Live",
    "blank_club": "Blank club",
    "placeholder_club": "Placeholder club",
    "merged_but_live": "Merged but live",
    "self_play_games": "Self-play games",
    "new_teams": "New this week",
}
PROBLEM_METRICS = ("blank_club", "placeholder_club", "merged_but_live", "self_play_games")
INFLOW_METRICS = {
    "new_teams": "Created",
    "new_no_state": "No state",
    "new_no_club": "No club",
    "new_unknown_name": "unknown_ name",
}
OPEN_PROBLEMS = "open_problems"
# Growth in live or new teams is not a warning; these are the counts whose rise is.
RISING_METRICS = (*PROBLEM_METRICS, OPEN_PROBLEMS, "new_no_state", "new_no_club", "new_unknown_name")


def state_bucket(code: str | None) -> str:
    code = (code or "").strip()
    if not code:
        return NO_STATE
    if code in STATE_CODE_TO_NAME:
        return code
    return NON_US if code in CANADIAN_PROVINCES else MALFORMED


def is_blank_club(club: str | None) -> bool:
    return club is None or not club.strip()


def is_unknown_name(name: str | None) -> bool:
    return bool(UNKNOWN_NAME.fullmatch((name or "").strip()))


def is_bucket(scope: str) -> bool:
    return scope != NATIONAL and not scope.startswith(SOURCE_PREFIX)


def open_problems(bucket: str, values: dict) -> int:
    """The listed defects, plus, where the bucket has no usable state, each live team in it."""
    stateless = values.get("live_teams", 0) if bucket in (NO_STATE, MALFORMED) else 0
    return stateless + sum(values.get(metric, 0) for metric in PROBLEM_METRICS)


def measure(teams, merge_map, games, providers, since: datetime, until: datetime) -> Counter:
    """Counts keyed (bucket, metric), with national totals under ALL and the inflow created in
    [since, until) under source:<provider code>."""
    counts: Counter = Counter()
    canonical = resolver(merge_map)
    by_id = {}
    for team in teams:
        by_id[team["team_id_master"]] = team
        bucket = state_bucket(team["state_code"])
        blank = is_blank_club(team["club_name"])
        created = datetime.fromisoformat(team["created_at"]) if team.get("created_at") else None
        if created and since <= created < until:
            source = SOURCE_PREFIX + (providers.get(team["provider_id"]) or "(none)")
            for scope in (bucket, NATIONAL, source):
                counts[(scope, "new_teams")] += 1
            for scope in (NATIONAL, source):
                counts[(scope, "new_no_state")] += bucket == NO_STATE
                counts[(scope, "new_no_club")] += blank or is_placeholder_club(team["club_name"])
                counts[(scope, "new_unknown_name")] += is_unknown_name(team["team_name"])
        if team["is_deprecated"]:
            continue
        for scope in (bucket, NATIONAL):
            counts[(scope, "live_teams")] += 1
            counts[(scope, "blank_club")] += blank
            # The placeholder list holds "" too; a blank club is counted once, as blank.
            counts[(scope, "placeholder_club")] += not blank and is_placeholder_club(team["club_name"])
            counts[(scope, "merged_but_live")] += team["team_id_master"] in merge_map
    for game in games:
        home, away = canonical(game["home_team_master_id"]), canonical(game["away_team_master_id"])
        if home and home == away:
            bucket = state_bucket(by_id.get(home, {}).get("state_code"))
            for scope in (bucket, NATIONAL):
                counts[(scope, "self_play_games")] += 1
    return counts


def fetch_teams(sb) -> list[dict]:
    columns = "team_id_master,team_name,club_name,state_code,provider_id,created_at,is_deprecated"
    return page(lambda: sb.table("teams").select(columns), "team_id_master")


def fetch_games(sb):
    """Every game's two sides, a page at a time by id: an offset read slows as it goes deeper."""
    last = None
    while True:
        query = sb.table("games").select("id,home_team_master_id,away_team_master_id").order("id")
        if last is not None:
            query = query.gt("id", last)
        rows = query.limit(GAMES_PAGE).execute().data
        if not rows:
            return
        yield from rows
        last = rows[-1]["id"]


def fetch_providers(sb) -> dict[str, str]:
    return {p["id"]: p["code"] for p in sb.table("providers").select("id,code").execute().data}


def history_rows(day: str, counts: Counter) -> list[dict]:
    values: dict[str, dict] = defaultdict(dict)
    for (scope, metric), value in counts.items():
        values[scope][metric] = value
    buckets = {scope for scope in values if is_bucket(scope)} | set(SPECIAL_BUCKETS)
    for bucket in buckets:
        values[bucket] = {**dict.fromkeys(STATE_METRICS, 0), **values[bucket]}
        values[bucket][OPEN_PROBLEMS] = open_problems(bucket, values[bucket])
    values[NATIONAL] = {**dict.fromkeys((*STATE_METRICS, *INFLOW_METRICS), 0), **values[NATIONAL]}
    values[NATIONAL][OPEN_PROBLEMS] = sum(values[bucket][OPEN_PROBLEMS] for bucket in buckets)
    return [
        {"date": day, "bucket": scope, "metric": metric, "value": value}
        for scope, metrics in values.items()
        for metric, value in sorted(metrics.items())
    ]


def _series(history: list[dict]) -> dict:
    """{(bucket, metric): {date: value}} from history rows, whose values may be text."""
    series: dict = defaultdict(dict)
    for row in history:
        series[(row["bucket"], row["metric"])][row["date"]] = int(row["value"])
    return series


def _delta(points: dict, day: str, earlier: str | None) -> int | None:
    """The change since the earlier report; a value it did not record was 0."""
    return None if earlier is None else points.get(day, 0) - points.get(earlier, 0)


def _cell(delta: int | None) -> str:
    return "" if delta is None else f"{delta:+,}" if delta else "0"


def _trend(points: dict, dates: list[str]) -> str:
    window = [points.get(d, 0) for d in dates[-4:]]
    if len(window) < 2:
        return ""
    return "↑" if window[-1] > window[0] else "↓" if window[-1] < window[0] else "→"


def render(day: str, history: list[dict]) -> str:
    series = _series(history)
    dates = sorted({row["date"] for row in history if row["date"] <= day})
    earlier = dates[-2] if len(dates) > 1 else None
    national = series.get((NATIONAL, OPEN_PROBLEMS), {})
    change = _delta(national, day, earlier)
    since = "." if change is None else f" ({'unchanged' if change == 0 else f'{change:+,}'} since {earlier})."
    lines = [
        f"# Team data health, {day}",
        "",
        f"Live teams: {series.get((NATIONAL, 'live_teams'), {}).get(day, 0):,}. "
        f"Open problems: {national.get(day, 0):,}{since}",
        "",
        "## States by open problems",
        "",
        "| State | Open problems | Change | Trend | " + " | ".join(STATE_METRICS.values()) + " |",
        "|---|---:|---:|:---:|" + "---:|" * len(STATE_METRICS),
    ]
    buckets = {b for (b, m), points in series.items() if m == OPEN_PROBLEMS and is_bucket(b) and day in points}
    for bucket in sorted(buckets, key=lambda b: (-series[(b, OPEN_PROBLEMS)][day], b)):
        problems = series[(bucket, OPEN_PROBLEMS)]
        cells = [f"{series.get((bucket, m), {}).get(day, 0):,}" for m in STATE_METRICS]
        lines.append(
            f"| {bucket} | {problems[day]:,} | {_cell(_delta(problems, day, earlier))} | "
            f"{_trend(problems, dates)} | " + " | ".join(cells) + " |"
        )
    window = dates[-3:] if len(dates) >= 3 and dates[-1] == day else []
    rising = []
    for (scope, metric), points in sorted(series.items()):
        values = [points.get(d, 0) for d in window]
        if metric in RISING_METRICS and window and values[0] < values[1] < values[2]:
            rising.append(f"- {scope}, {metric}: " + " → ".join(f"{v:,}" for v in values))
    lines += [
        "",
        "## Rising two weeks running",
        "",
        *(rising or ["Nothing." if window else "Needs three weeks of history."]),
    ]
    lines += [
        "",
        "## New teams this week by source",
        "",
        "| Source | " + " | ".join(INFLOW_METRICS.values()) + " |",
        "|---|" + "---:|" * len(INFLOW_METRICS),
    ]
    sources = sorted(
        {b for (b, m), points in series.items() if b.startswith(SOURCE_PREFIX) and day in points},
        key=lambda b: (-series.get((b, "new_teams"), {}).get(day, 0), b),
    )
    for source in sources:
        cells = [f"{series.get((source, m), {}).get(day, 0):,}" for m in INFLOW_METRICS]
        lines.append(f"| {source.removeprefix(SOURCE_PREFIX)} | " + " | ".join(cells) + " |")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--store",
        type=Path,
        help="The run store, absolute (default: PITCHRANK_CLEANUP_DIR, else ~/pitchrank-cleanup-runs)",
    )
    parser.add_argument(
        "--date",
        default=datetime.now(timezone.utc).date().isoformat(),
        help="The report date, YYYY-MM-DD (default: today, UTC)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print the report and write nothing")
    args = parser.parse_args()
    try:
        store = store_dir(args.store)
    except ValueError as exc:
        raise SystemExit(str(exc)) from None
    try:
        day = date.fromisoformat(args.date)
    except ValueError as exc:
        raise SystemExit(f"--date: {exc}") from None
    until = datetime.combine(day, time.min, tzinfo=timezone.utc)

    sb = get_client()
    teams = fetch_teams(sb)
    counts = measure(teams, load_merge_map(sb), fetch_games(sb), fetch_providers(sb), until - timedelta(days=7), until)

    folder = store / HEALTH_DIR
    history_path = folder / HISTORY_FILE
    history = read_csv(history_path) if history_path.exists() else []
    history = [row for row in history if row["date"] != day.isoformat()] + history_rows(day.isoformat(), counts)
    report = render(day.isoformat(), history)
    if args.dry_run:
        print(report)
        print("DRY RUN -- nothing written.")
        return 0
    history.sort(key=lambda row: (row["date"], row["bucket"], row["metric"]))
    write_csv(history_path, history, fieldnames=HISTORY_FIELDS)
    report_path = folder / f"{day.isoformat()}.md"
    report_path.write_text(report, encoding="utf-8")
    print(f"Wrote {report_path} and updated {history_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
