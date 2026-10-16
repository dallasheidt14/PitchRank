#!/usr/bin/env python3
"""
Report games stored twice: two active scored rows for the same two teams on the same day.

A pair of rows is a real rematch (a pool game and a final) or one game saved twice, usually
once under a provider-id uid from a partial team match and once under the master-id uid, with
the first score gone stale. Scores alone cannot say which, so this lists the pairs and leaves
the decision to a check against the provider.

Reads only. Nothing here writes to the database.

Usage:
    python scripts/report_double_stored_games.py                 # last 45 days, GotSport
    python scripts/report_double_stored_games.py --days 90
    python scripts/report_double_stored_games.py --summary-file "$GITHUB_STEP_SUMMARY"
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import defaultdict
from datetime import date, timedelta
from itertools import combinations
from pathlib import Path

import truststore
from dotenv import load_dotenv
from rich.console import Console

from supabase import create_client

truststore.inject_into_ssl()

sys.path.append(str(Path(__file__).resolve().parent.parent))

from src.utils.provider_ids import PROVIDER_ID_GAME_UID  # noqa: E402

console = Console()

REPO_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(REPO_ROOT / ".env.local")
load_dotenv(REPO_ROOT / ".env")

PAGE_SIZE = 1000
LISTED_PAIRS = 40
GAME_COLUMNS = "id, game_uid, game_date, home_team_master_id, away_team_master_id, home_score, away_score"


def fetch_day(client, provider_uuid: str, day: str) -> list[dict]:
    """Every active scored game of one provider on one date, paginated."""
    rows: list[dict] = []
    offset = 0
    while True:
        page = (
            client.table("games")
            .select(GAME_COLUMNS)
            .eq("provider_id", provider_uuid)
            .eq("game_date", day)
            .eq("is_excluded", False)
            .order("id")
            .range(offset, offset + PAGE_SIZE - 1)
            .execute()
            .data
        )
        rows.extend(r for r in page if r["home_score"] is not None and r["away_score"] is not None)
        if len(page) < PAGE_SIZE:
            return rows
        offset += PAGE_SIZE


def find_double_stored(rows: list[dict]) -> list[dict]:
    """Every pair of rows sharing a date and a team pair, each with how its scores relate.

    ``reversed`` means one row is the other with home and away flipped, ``identical`` the same
    result twice, ``different`` two scores for the pair. ``provider_id_uid`` marks a pair where
    a row still carries a uid built from provider team ids.
    """
    by_pair: dict[tuple, list[dict]] = defaultdict(list)
    for row in rows:
        home, away = row["home_team_master_id"], row["away_team_master_id"]
        if home and away:
            by_pair[(row["game_date"], *sorted((home, away)))].append(row)

    pairs = []
    for (game_date, first_team, _), group in by_pair.items():
        for left, right in combinations(group, 2):
            left_score = _score_for(left, first_team)
            right_score = _score_for(right, first_team)
            if left_score == right_score:
                kind = "identical"
            elif left_score == right_score[::-1]:
                kind = "reversed"
            else:
                kind = "different"
            pairs.append(
                {
                    "date": game_date,
                    "kind": kind,
                    "provider_id_uid": any(PROVIDER_ID_GAME_UID.match(r["game_uid"] or "") for r in (left, right)),
                    "rows": [left, right],
                }
            )
    return sorted(pairs, key=lambda p: (p["date"], p["rows"][0]["id"]))


def _score_for(row: dict, first_team: str) -> tuple[int, int]:
    """The row's score as (first team's, other team's)."""
    home, away = row["home_score"], row["away_score"]
    return (home, away) if row["home_team_master_id"] == first_team else (away, home)


def scan(client, provider_code: str, days: int, today: date | None = None) -> list[dict]:
    provider = client.table("providers").select("id").eq("code", provider_code).single().execute().data
    today = today or date.today()
    rows: list[dict] = []
    for offset in range(days + 1):
        rows.extend(fetch_day(client, provider["id"], (today - timedelta(days=offset)).isoformat()))
    return find_double_stored(rows)


def summarize(pairs: list[dict], days: int) -> str:
    counts = {kind: sum(p["kind"] == kind for p in pairs) for kind in ("reversed", "different", "identical")}
    lines = [
        f"## Games stored twice, last {days} days",
        "",
        "| Kind | Pairs |",
        "|------|-------|",
        f"| Same result twice | {counts['identical']} |",
        f"| Reversed scores | {counts['reversed']} |",
        f"| Two different scores | {counts['different']} |",
        f"| **Total** | **{len(pairs)}** |",
        "",
        "A pair can be a real same-day rematch. Check each against the provider before excluding either row.",
    ]
    listed = [p for p in pairs if p["provider_id_uid"]][:LISTED_PAIRS]
    if listed:
        lines += ["", f"Pairs where a row carries a provider-id uid (first {LISTED_PAIRS}):", ""]
        for pair in listed:
            left, right = pair["rows"]
            lines.append(
                f"- {pair['date']} {pair['kind']}: {left['home_score']}-{left['away_score']} "
                f"`{left['game_uid']}` / {right['home_score']}-{right['away_score']} `{right['game_uid']}`"
            )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--days", type=int, default=45, help="how far back to look (default 45)")
    parser.add_argument("--provider-code", default="gotsport")
    parser.add_argument("--summary-file", help="append the markdown summary here as well")
    args = parser.parse_args()

    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY")
    if not url or not key:
        console.print("[red]SUPABASE_URL and a key are required[/red]")
        return 1

    pairs = scan(create_client(url, key), args.provider_code, args.days)
    summary = summarize(pairs, args.days)
    console.print(summary, markup=False)
    if args.summary_file:
        with open(args.summary_file, "a", encoding="utf-8") as handle:
            handle.write(summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
