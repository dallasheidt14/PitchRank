#!/usr/bin/env python3
"""Read-only lookups for the weekly duplicate review's reviewers (review_merges.py).

A reviewer may run this and no other program, so each lookup is a fixed read:

  team <team id>                       the row (a merged-away id is read as the row it went into), the
                                       rows merged into it, and its games (merge-resolved), newest
                                       first, each with the registration that played it
  club <text> <age group> <gender>     live rows of that cohort whose club name holds the text, any state
  name <text> <age group> <gender>     live rows of that cohort whose name or registered name holds it

A list longer than it shows says so. Each read is a SELECT, made with the public key alone, whatever else the
checkout's .env holds. That key cannot read team_alias_map, so no lookup lists aliases, and the team lookup says
so; the slice's evidence, built with the full key, lists each pair's.

    python scripts/team_cleanup/review_lookup.py team 602b9dba-a36e-422d-94b7-0809049ef928
    python scripts/team_cleanup/review_lookup.py club "Kraze" u11 Male
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.find_cross_provider_duplicates import batched, load_merge_map, page, resolver  # noqa: E402
from supabase import create_client  # noqa: E402

TEAM_COLS = (
    "team_id_master,team_name,team_name_original,club_name,age_group,gender,state_code,"
    "provider_id,provider_team_id,is_deprecated,last_played_at"
)
GAME_COLS = (
    "id,game_date,home_team_master_id,away_team_master_id,home_score,away_score,home_provider_id,"
    "away_provider_id,event_name,competition,division_name,is_excluded"
)
UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
AGE = re.compile(r"^u[0-9]{1,2}$")
GENDERS = ("Male", "Female")
# A search text is a plain fragment of a name: wildcards and PostgREST's list syntax are not part of one.
SEARCH = re.compile(r"^[^%*,()\\]{3,60}$")
ROWS_SHOWN = 60
ALIASES_UNREAD = "not readable with the public key; the slice's evidence lists each pair's"
GAMES_SHOWN = 200


def event_of(game: dict) -> str:
    return game["event_name"] or game["competition"] or game["division_name"] or ""


def label(team: dict | None) -> str:
    """A team as a game line names it: its name and stored cohort."""
    return f"{team['team_name']} [{team['age_group']} {(team['gender'] or '?')[:1]}]" if team else "?"


def team_line(t: dict, providers: dict) -> str:
    return (
        f"{t['team_id_master']} | {t['team_name']} | registered: {t['team_name_original'] or '-'} | club: "
        f"{t['club_name']} | {providers.get(t['provider_id'], '?')}:{t['provider_team_id']} | {t['age_group']} "
        f"{t['gender']} {t['state_code']} | last played {str(t['last_played_at'])[:10]}"
        + (" | DEPRECATED" if t["is_deprecated"] else "")
    )


def show_team(sb, asked: str, providers: dict) -> None:
    merge_map = load_merge_map(sb)
    canonical = resolver(merge_map)
    team_id = canonical(asked)
    if team_id != asked:
        print(f"{asked} was merged into {team_id}; showing that row")
    rows = sb.table("teams").select(TEAM_COLS).eq("team_id_master", team_id).execute().data
    if not rows:
        print("no such team")
        return
    print(team_line(rows[0], providers))
    print(f"  aliases: {ALIASES_UNREAD}")
    absorbed = [d for d in merge_map if d != team_id and canonical(d) == team_id]
    for batch in batched(absorbed):
        for t in sb.table("teams").select(TEAM_COLS).in_("team_id_master", batch).execute().data:
            print(f"  merged into it: {team_line(t, providers)}")
    games = {}
    for side in ("home_team_master_id", "away_team_master_id"):
        for batch in batched([team_id, *absorbed]):
            for g in page(lambda b=batch, s=side: sb.table("games").select(GAME_COLS).in_(s, b), "id"):
                games[g["id"]] = g
    opponents = {canonical(g[f"{s}_team_master_id"]) for g in games.values() for s in ("home", "away")}
    names = {}
    for batch in batched(sorted(opponents - {team_id, None})):
        for t in sb.table("teams").select(TEAM_COLS).in_("team_id_master", batch).execute().data:
            names[t["team_id_master"]] = label(t)
    newest = sorted(games.values(), key=lambda g: (g["game_date"], g["id"]), reverse=True)
    hidden = len(newest) - GAMES_SHOWN
    print(f"  games: {len(newest)}, newest first" + (f"; the oldest {hidden} are not shown" if hidden > 0 else ""))
    for g in newest[:GAMES_SHOWN]:
        home = canonical(g["home_team_master_id"]) == team_id
        them = canonical(g["away_team_master_id" if home else "home_team_master_id"])
        mine, theirs = (g["home_score"], g["away_score"]) if home else (g["away_score"], g["home_score"])
        registration = g["home_provider_id" if home else "away_provider_id"]
        excluded = " (excluded)" if g["is_excluded"] else ""
        played = f"{g['game_date']} as {registration} vs {names.get(them, '?')} {mine}-{theirs}"
        print(f"    {played} {event_of(g)}{excluded}")


def show_search(sb, column: str, text: str, age: str, gender: str, providers: dict) -> None:
    columns = ("team_name", "team_name_original") if column == "name" else ("club_name",)
    found, more = {}, False
    for col in columns:
        rows = (
            sb.table("teams").select(TEAM_COLS).ilike(col, f"%{text}%").eq("age_group", age).eq("gender", gender)
            .eq("is_deprecated", False).order("club_name").order("team_name").limit(ROWS_SHOWN + 1).execute().data
        )
        more = more or len(rows) > ROWS_SHOWN
        found.update({t["team_id_master"]: t for t in rows[:ROWS_SHOWN]})
    # A blank club last, as Postgres sorts it, so the rows shown are the rows each query kept.
    shown = sorted(found.values(), key=lambda t: (t["club_name"] is None, t["club_name"] or "", t["team_name"]))
    shown = shown[:ROWS_SHOWN]
    for t in shown:
        print(team_line(t, providers))
    if more or len(found) > ROWS_SHOWN:
        print(f"more than {ROWS_SHOWN} rows hold the text; the first {len(shown)} by club and name are shown")
    else:
        print(f"{len(shown)} row(s)")


def public_client():
    """A client on the public key: importing the scan loads the checkout's .env, private key included."""
    url, key = os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY")
    if not url or not key:
        raise SystemExit("SUPABASE_URL and SUPABASE_KEY must be set")
    return create_client(url, key)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("what", choices=("team", "club", "name"))
    ap.add_argument("text", help="A team id, or the text to search for")
    ap.add_argument("age_group", nargs="?")
    ap.add_argument("gender", nargs="?", choices=GENDERS)
    args = ap.parse_args()
    if args.what == "team" and not UUID.match(args.text):
        ap.error("team takes a team id")
    if args.what != "team" and not (
        SEARCH.match(args.text) and args.age_group and AGE.match(args.age_group) and args.gender
    ):
        ap.error(f"{args.what} takes a text of 3 to 60 plain characters, an age group like u12, and Male or Female")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    sb = public_client()
    providers = {p["id"]: p["code"] for p in sb.table("providers").select("id,code").execute().data}
    if args.what == "team":
        show_team(sb, args.text, providers)
    else:
        show_search(sb, args.what, args.text, args.age_group, args.gender, providers)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
