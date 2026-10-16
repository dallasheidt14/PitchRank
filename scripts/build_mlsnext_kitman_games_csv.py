#!/usr/bin/env python3
"""Build the MLS NEXT (Kitman) import CSV and report what it would do to the rankings.

Reads ``games.csv`` and ``squads.csv``. A played game dated from August 1 of the season up to today
whose two squads are both linked to PitchRank, on the same board, becomes two importer rows (one per
side); every other played game is written to ``held_games.csv`` with its reason and waits. A completed,
scored game dated in the future is held until that date, then imports under it. Links come from the
live ``mlsnext_kitman`` aliases, or with ``--planned`` from ``link_plan.csv`` (a team the plan would
create counts as linked), so the impact can be read before anything is written. A live link whose team
the importer would reject (another age or gender, or deprecated) is dropped, so its games are held
rather than imported with one side missing.

Read-only against the database. Import the result of a live run with:
    python scripts/import_games_enhanced.py data/mlsnext_kitman/import.csv mlsnext_kitman
A ``--planned`` run writes ``import_planned.csv`` instead: a preview, never imported, because the
teams it would create do not exist yet.

Usage:
    python scripts/build_mlsnext_kitman_games_csv.py [--planned]
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.build_modular11_ea_games_csv import (  # noqa: E402
    IMPORT_COLUMNS,
    PROVISIONAL_GAMES,
    _result,
    impact,
    unstored_rows,
)
from scripts.scrape_mlsnext_kitman import BASE_URL  # noqa: E402
from src.models.mlsnext_kitman_keys import refuse_raw_keys, season_start_year  # noqa: E402
from src.models.mlsnext_kitman_matcher import PROVIDER_CODE  # noqa: E402
from supabase import create_client  # noqa: E402

PAGE_SIZE = 1000


def hold_reason(game: dict, squads: dict[str, dict], links: dict[str, str], since: str, today: str) -> str:
    if game["game_date"] > today:
        return "completed but dated in the future"
    if game["game_date"] < since:
        return "before the season window"
    home, away = squads.get(game["home_squad_id"]), squads.get(game["away_squad_id"])
    if not (home and away):
        return "a squad label is not a board age"
    if not (game["home_key"] in links and game["away_key"] in links):
        return "a team is not linked"
    if home["age_group"] != away["age_group"]:
        return "the two squads are on different boards"
    return ""


def build_rows(
    games: list[dict], squads: dict[str, dict], links: dict[str, str], since: str, today: str
) -> tuple[list[dict], list[dict]]:
    scraped_at = datetime.now(timezone.utc).isoformat()
    rows: list[dict] = []
    held: list[dict] = []
    for game in games:
        if game["status"] != "played":
            continue
        why = hold_reason(game, squads, links, since, today)
        if why:
            held.append({**game, "hold_reason": why})
            continue
        home, away = squads[game["home_squad_id"]], squads[game["away_squad_id"]]
        home_score, away_score = int(game["home_score"]), int(game["away_score"])
        for side, other, goals_for, goals_against, home_away in (
            (home, away, home_score, away_score, "H"),
            (away, home, away_score, home_score, "A"),
        ):
            rows.append(
                {
                    "provider": PROVIDER_CODE,
                    "team_id": side["key"],
                    "team_id_source": side["key"],
                    "team_name": side["display_name"],
                    "club_name": side["club_name"],
                    "opponent_id": other["key"],
                    "opponent_id_source": other["key"],
                    "opponent_name": other["display_name"],
                    "opponent_club_name": other["club_name"],
                    "age_group": home["age_group"],
                    "gender": "Boys",
                    "competition": game["competition"],
                    "division_name": game["division"],
                    "event_name": f"MLS NEXT {game['division']} - {game['competition']}",
                    "game_date": game["game_date"],
                    "home_away": home_away,
                    "goals_for": goals_for,
                    "goals_against": goals_against,
                    "result": _result(goals_for, goals_against),
                    "source_url": BASE_URL,
                    "scraped_at": scraped_at,
                }
            )
    return rows, held


def planned_links(plan_path: Path) -> dict[str, str]:
    links = {}
    with plan_path.open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row["action"] in ("link", "keep"):
                links[row["key"]] = row["team_id_master"]
            elif row["action"] == "create":
                links[row["key"]] = f"new:{row['key']}"
    return links


def live_links(sb) -> dict[str, str]:
    provider = sb.table("providers").select("id").eq("code", PROVIDER_CODE).execute().data
    if not provider:
        raise SystemExit(f"ERROR: provider {PROVIDER_CODE!r} is missing; apply migration 20261015120000 first")
    links, offset = {}, 0
    while True:
        page = (
            sb.table("team_alias_map")
            .select("provider_team_id, team_id_master")
            .eq("provider_id", provider[0]["id"])
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


def usable_links(sb, links: dict[str, str], ages: dict[str, str]) -> dict[str, str]:
    """Keeps the links whose team the importer's age/gender check would accept for that squad's age."""
    masters = sorted(set(links.values()))
    accepted: dict[str, str] = {}
    for start in range(0, len(masters), 100):
        rows = (
            sb.table("teams")
            .select("team_id_master, age_group, gender, is_deprecated")
            .in_("team_id_master", masters[start : start + 100])
            .execute()
            .data
        )
        accepted.update(
            {
                row["team_id_master"]: (row.get("age_group") or "").lower()
                for row in rows
                if row.get("gender") == "Male" and row.get("is_deprecated") is not True
            }
        )
    return {key: master for key, master in links.items() if accepted.get(master) == ages.get(key)}


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
    parser.add_argument("--in-dir", type=Path, default=Path("data/mlsnext_kitman"))
    parser.add_argument("--planned", action="store_true", help="read links from link_plan.csv, not the database")
    args = parser.parse_args(argv)

    games = _read_csv(args.in_dir / "games.csv")
    squad_rows = _read_csv(args.in_dir / "squads.csv")
    squads = {s["provider_team_id"]: s for s in squad_rows}
    today = date.today()
    since = f"{season_start_year(today)}-08-01"
    sb = _new_client()
    if args.planned:
        links = planned_links(args.in_dir / "link_plan.csv")
    else:
        linked = live_links(sb)
        links = usable_links(sb, linked, {s["key"]: s["age_group"] for s in squad_rows})
        if len(links) < len(linked):
            dropped = len(linked) - len(links)
            print(f"Dropped {dropped} links: not a squad this season, or its team is another age/gender or deprecated")
    rows, held = build_rows(games, squads, links, since, today.isoformat())
    _write_csv(args.in_dir / ("import_planned.csv" if args.planned else "import.csv"), IMPORT_COLUMNS, rows)
    _write_csv(args.in_dir / "held_games.csv", [*(games[0] if games else {}), "hold_reason"], held)
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
