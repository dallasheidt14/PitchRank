#!/usr/bin/env python3
"""Build one age group's EA import CSV and report what it would do to the rankings.

Reads step 1's ``games.csv`` and ``teams.csv``. A played game whose two teams are both
linked to PitchRank becomes two importer rows (one per side); every other played game is
written to ``held_games.csv`` and waits for its teams to be linked. Links come from the
live ``modular11_ea`` aliases, or with ``--planned`` from ``link_plan.csv`` (a team the
plan would create counts as linked), so the impact can be read before anything is written.
A live link whose team the importer would reject (another age or gender, or deprecated)
is dropped, so its games are held rather than imported with one side missing.

Read-only against the database. Import the result of a live run with:
    python scripts/import_games_enhanced.py data/modular11_ea/<age>/import.csv modular11_ea
A ``--planned`` run writes ``import_planned.csv`` instead: a preview, never imported,
because the teams it would create do not exist yet.

Usage:
    python scripts/build_modular11_ea_games_csv.py --age u17 [--planned]
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.find_cross_provider_duplicates import load_merge_map, merged_into, page, resolver  # noqa: E402
from scripts.scrape_modular11_ea import MATCHES_URL  # noqa: E402
from src.etl.glicko_config import GlickoConfig  # noqa: E402
from src.models.modular11_ea_keys import refuse_raw_keys  # noqa: E402
from src.models.modular11_ea_matcher import PROVIDER_CODE  # noqa: E402
from supabase import create_client  # noqa: E402

PROVISIONAL_GAMES = GlickoConfig.MIN_GAMES_PROVISIONAL
RANKING_WINDOW_DAYS = 365
PAGE_SIZE = 1000
IMPORT_COLUMNS = [
    "provider",
    "team_id",
    "team_id_source",
    "team_name",
    "club_name",
    "opponent_id",
    "opponent_id_source",
    "opponent_name",
    "opponent_club_name",
    "age_group",
    "gender",
    "competition",
    "division_name",
    "event_name",
    "game_date",
    "home_away",
    "goals_for",
    "goals_against",
    "result",
    "source_url",
    "scraped_at",
]


def _result(goals_for: int, goals_against: int) -> str:
    if goals_for > goals_against:
        return "W"
    if goals_for < goals_against:
        return "L"
    return "D"


def build_rows(games: list[dict], teams: dict[str, dict], links: dict[str, str]) -> tuple[list[dict], list[dict]]:
    scraped_at = datetime.now(timezone.utc).isoformat()
    rows: list[dict] = []
    held: list[dict] = []
    for game in games:
        if game["status"] != "played":
            continue
        home, away = game["home_key"], game["away_key"]
        if not (home in links and away in links):
            held.append(game)
            continue
        home_score, away_score = int(game["home_score"]), int(game["away_score"])
        home_uid, away_uid = game["home_team_id"], game["away_team_id"]
        for team_id, opponent_id, team_uid, opponent_uid, goals_for, goals_against, home_away, name, opponent_name in (
            (home, away, home_uid, away_uid, home_score, away_score, "H", game["home_name"], game["away_name"]),
            (away, home, away_uid, home_uid, away_score, home_score, "A", game["away_name"], game["home_name"]),
        ):
            team, opponent = teams.get(team_uid, {}), teams.get(opponent_uid, {})
            rows.append(
                {
                    "provider": PROVIDER_CODE,
                    "team_id": team_id,
                    "team_id_source": team_id,
                    "team_name": team.get("display_name") or name,
                    "club_name": team.get("club_name", ""),
                    "opponent_id": opponent_id,
                    "opponent_id_source": opponent_id,
                    "opponent_name": opponent.get("display_name") or opponent_name,
                    "opponent_club_name": opponent.get("club_name", ""),
                    "age_group": game["age_group"],
                    "gender": "Boys",
                    "competition": game["bracket"],
                    "division_name": game["region"],
                    "event_name": f"Elite Academy League - {game['bracket']}",
                    "game_date": game["game_date"],
                    "home_away": home_away,
                    "goals_for": goals_for,
                    "goals_against": goals_against,
                    "result": _result(goals_for, goals_against),
                    "source_url": MATCHES_URL,
                    "scraped_at": scraped_at,
                }
            )
    return rows, held


def _stored_games(sb, team_id_master: str, since: str) -> int:
    total = 0
    for column in ("home_team_master_id", "away_team_master_id"):
        result = (
            sb.table("games")
            .select("id", count="exact")
            .eq(column, team_id_master)
            .gte("game_date", since)
            .limit(1)
            .execute()
        )
        total += result.count or 0
    return total


def _fixture(day: str, team_a: str | None, team_b: str | None) -> tuple:
    """One match whichever side recorded it, keyed as the importer's game uid is: date and teams.

    A stored game can lack a team on one side; it then matches no importer row.
    """
    return (day, frozenset((team_a, team_b)))


def unstored_rows(sb, rows: list[dict], links: dict[str, str]) -> list[dict]:
    """The importer rows whose match PitchRank does not already hold, under any provider.

    The importer drops a match it already has, so the impact is read only from what would
    survive. Stored games are compared as the importer's game uid compares them, by date and
    teams and not by score, so a result the provider corrected still counts as stored. Both teams
    are followed through their whole merge chain, since a match imported before a merge names the
    deprecated row.
    """
    masters = sorted({links[r["team_id"]] for r in rows if not links[r["team_id"]].startswith("new:")})
    if not masters:
        return list(rows)
    merge_map = load_merge_map(sb)
    canonical = resolver(merge_map)
    ids = sorted(merged_into(masters, merge_map, canonical))
    days = [r["game_date"][:10] for r in rows]
    start, end = min(days), max(days)
    stored = set()
    for side in ("home_team_master_id", "away_team_master_id"):
        for offset in range(0, len(ids), 100):
            batch = ids[offset : offset + 100]
            games = page(
                lambda b=batch, s=side: (
                    sb.table("games")
                    .select("id, game_date, home_team_master_id, away_team_master_id")
                    .in_(s, b)
                    .gte("game_date", start)
                    .lte("game_date", end)
                ),
                "id",
            )
            stored.update(
                _fixture(g["game_date"][:10], canonical(g["home_team_master_id"]), canonical(g["away_team_master_id"]))
                for g in games
            )
    return [
        r
        for r in rows
        if _fixture(r["game_date"][:10], canonical(links[r["team_id"]]), canonical(links[r["opponent_id"]]))
        not in stored
    ]


def impact(sb, rows: list[dict], links: dict[str, str]) -> dict:
    """Games added, teams touched, and teams that reach the provisional game count."""
    added = Counter(links[row["team_id"]] for row in rows)
    since = (date.today() - timedelta(days=RANKING_WINDOW_DAYS)).isoformat()
    crossing = []
    for team_id_master, new_games in sorted(added.items()):
        stored = 0 if team_id_master.startswith("new:") else _stored_games(sb, team_id_master, since)
        if stored < PROVISIONAL_GAMES <= stored + new_games:
            crossing.append(team_id_master)
    return {
        "games_added": len(rows) // 2,
        "teams_touched": len(added),
        "crossing_up": len(crossing),
        "crossing_teams": crossing,
    }


def planned_links(plan_path: Path) -> dict[str, str]:
    links = {}
    with plan_path.open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row["action"] == "link":
                links[row["key"]] = row["team_id_master"]
            elif row["action"] == "create":
                links[row["key"]] = f"new:{row['key']}"
    return links


def live_links(sb) -> dict[str, str]:
    provider_id = sb.table("providers").select("id").eq("code", PROVIDER_CODE).single().execute().data["id"]
    links, offset = {}, 0
    while True:
        page = (
            sb.table("team_alias_map")
            .select("provider_team_id, team_id_master")
            .eq("provider_id", provider_id)
            .eq("review_status", "approved")
            .order("id")
            .range(offset, offset + PAGE_SIZE - 1)
            .execute()
            .data
        )
        links.update({row["provider_team_id"]: row["team_id_master"] for row in page})
        if len(page) < PAGE_SIZE:
            break
        offset += PAGE_SIZE
    refuse_raw_keys(links)
    return links


def usable_links(sb, links: dict[str, str], age_group: str) -> dict[str, str]:
    """Keeps the links whose team the importer's age/gender check would accept."""
    masters = sorted(set(links.values()))
    usable = set()
    for start in range(0, len(masters), 100):
        rows = (
            sb.table("teams")
            .select("team_id_master, age_group, gender, is_deprecated")
            .in_("team_id_master", masters[start : start + 100])
            .execute()
            .data
        )
        usable.update(
            row["team_id_master"]
            for row in rows
            if (row.get("age_group") or "").lower() == age_group.lower()
            and row.get("gender") == "Male"
            and row.get("is_deprecated") is not True
        )
    return {tid: master for tid, master in links.items() if master in usable}


def _read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: Path, columns: list[str], rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def _new_client():
    load_dotenv()
    url = os.environ.get("SUPABASE_URL") or os.environ.get("NEXT_PUBLIC_SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_KEY")
    if not url or not key:
        raise SystemExit("ERROR: missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY")
    return create_client(url, key)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--age", required=True)
    parser.add_argument("--in-dir", type=Path, default=Path("data/modular11_ea"))
    parser.add_argument("--planned", action="store_true", help="read links from link_plan.csv, not the database")
    args = parser.parse_args(argv)
    age_dir = args.in_dir / args.age

    games = _read_csv(age_dir / "games.csv")
    teams = {t["provider_team_id"]: t for t in _read_csv(age_dir / "teams.csv")}
    sb = _new_client()
    if args.planned:
        links = planned_links(age_dir / "link_plan.csv")
    else:
        linked = live_links(sb)
        links = usable_links(sb, linked, args.age)
        if len(links) < len(linked):
            print(f"Dropped {len(linked) - len(links)} links whose team is another age/gender or deprecated")
    rows, held = build_rows(games, teams, links)
    _write_csv(age_dir / ("import_planned.csv" if args.planned else "import.csv"), IMPORT_COLUMNS, rows)
    _write_csv(age_dir / "held_games.csv", list(games[0]) if games else [], held)
    new_rows = unstored_rows(sb, rows, links)
    result = impact(sb, new_rows, links)
    print(
        f"games_added={result['games_added']} already_stored={(len(rows) - len(new_rows)) // 2} "
        f"held={len(held)} teams_touched={result['teams_touched']} "
        f"crossing_{PROVISIONAL_GAMES}_games={result['crossing_up']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
