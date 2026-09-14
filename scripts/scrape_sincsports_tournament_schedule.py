#!/usr/bin/env python3
"""Scrape and import every game in a SincSports tournament via schedule.aspx.

Iterates every division in the tournament, parses each fixture (date, time,
team_ids, scores, status), normalizes to the per-team-perspective JSONL shape
the existing ``import_games_enhanced.py`` pipeline consumes, and (with
``--auto-import``) hands off to that pipeline.

Replaces ``scripts/scrape_sincsports_by_tournament_teams.py`` for tournament
game ingestion: that script hits per-team ``games.aspx`` pages which respect
SincSports' VIP blur and silently miss most games. ``schedule.aspx`` is not
gated by the per-team blur, so coverage is roughly 2× and scores are clean.

SincSports blocks plain HTTP clients, so ``--from-bundle`` reads a capture
made in a real browser by ``scripts/sincsports_capture_bundle.js`` instead of
fetching live. That is also how league seasons are imported.

Example:
    python scripts/scrape_sincsports_tournament_schedule.py --tid TZ2565
    python scripts/scrape_sincsports_tournament_schedule.py --tid TZ2565 --auto-import
    python scripts/scrape_sincsports_tournament_schedule.py --tid TZ2565 --year 2025 --dry-run
    python scripts/scrape_sincsports_tournament_schedule.py --from-bundle data/raw/x/divisions.json \
        --since 2026-08-01 --check-aliases --dry-run
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Sub-U10 division codes (e.g. U08M01, U09F02). PitchRank rankings are u10+
# (config/settings.py:_BIRTH_YEARS), so sub-u10 records would only inflate the
# scraper output and the importer's failed-match counter without ever
# contributing to a ranking. Filtered before JSONL emit by default;
# --include-sub-u10 opts in for future use.
_SUB_U10_CODE_RE = re.compile(r"^U0[89]", re.IGNORECASE)

sys.path.append(str(Path(__file__).parent.parent))

from dotenv import load_dotenv  # noqa: E402
from rich.console import Console  # noqa: E402

from src.etl.bulk_ops import RPC_RESULT_LIMIT  # noqa: E402
from src.scrapers.sincsports_schedule import (  # noqa: E402
    SincSportsScheduleScraper,
    TournamentGame,
    parse_division_pages,
    parse_page_count,
)
from src.tournaments.reports.render_csv import csv_safe  # noqa: E402
from supabase import create_client  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)
console = Console()

_env_local = Path(".env.local")
if _env_local.exists():
    load_dotenv(_env_local)
else:
    load_dotenv()

RAW_DIR = Path("data/raw")


def parse_date_iso(mdy: Optional[str]) -> Optional[str]:
    """``"4/18/2026"`` -> ``"2026-04-18"`` (or ``None`` if unparseable)."""
    if not mdy:
        return None
    try:
        return datetime.strptime(mdy, "%m/%d/%Y").strftime("%Y-%m-%d")
    except ValueError:
        return None


def perspective_record(g: TournamentGame, *, perspective: str) -> dict:
    """Build the dict shape that ``import_games_enhanced.py`` expects.

    Mirrors the output of ``SincSportsScraper._game_data_to_dict`` so the
    downstream pipeline doesn't need to learn about a new format. ``perspective``
    is ``"H"`` or ``"A"`` — perspective from which the team_id is the row's
    primary team.
    """
    is_home = perspective == "H"
    team_id = g.home_id if is_home else g.away_id
    team_name = g.home_name if is_home else g.away_name
    opp_id = g.away_id if is_home else g.home_id
    opp_name = g.away_name if is_home else g.home_name
    goals_for = g.home_score if is_home else g.away_score
    goals_against = g.away_score if is_home else g.home_score
    if goals_for is None or goals_against is None:
        result = "U"
    elif goals_for > goals_against:
        result = "W"
    elif goals_for < goals_against:
        result = "L"
    else:
        result = "D"

    return {
        "provider": "sincsports",
        "source": "sincsports_tournament_schedule",
        "team_id": team_id,
        "opponent_id": opp_id,
        "team_name": team_name,
        "opponent_name": opp_name,
        "game_date": parse_date_iso(g.date),
        "home_away": "H" if is_home else "A",
        "goals_for": goals_for,
        "goals_against": goals_against,
        "result": result,
        "competition": (g.division_name or g.division_code or "").strip(),
        "venue": g.venue,
        "club_name": "",
        "opponent_club_name": "",
        "meta": {
            "source_url": (f"https://soccer.sincsports.com/schedule.aspx?tid={g.tournament_id}&div={g.division_code}"),
            "scraped_at": datetime.now().isoformat(),
            "club_name": "",
            "opponent_club_name": "",
            "tournament_id": g.tournament_id,
            "division_code": g.division_code,
            "division_name": g.division_name,
            "game_num": g.game_num,
        },
    }


def load_bundle(path: Path) -> Tuple[List[TournamentGame], List[str]]:
    """Parse a browser capture bundle into games plus the capture problems it shows.

    A division is incomplete when the capture recorded an error for it, or when
    its pager spans pages the bundle does not hold.
    """
    bundle = json.loads(path.read_text(encoding="utf-8"))
    if bundle.get("mode") != "divisions":
        return [], [f"{path.name} is a {bundle.get('mode')!r} capture; --from-bundle needs a 'divisions' capture"]
    event_names = {e["tid"]: e.get("name") or e["tid"] for e in bundle.get("events", [])}
    problems = [f"{e['tid']} {e['div']} page {e['page']}: {e['error']}" for e in bundle.get("errors", [])]

    pages_by_division: Dict[Tuple[str, str], Dict[int, str]] = defaultdict(dict)
    for d in bundle.get("divisions", []):
        pages_by_division[(d["tid"], d["div"])][int(d["page"])] = d["html"]

    games: List[TournamentGame] = []
    for (tid, div), pages in sorted(pages_by_division.items()):
        page_count = parse_page_count(pages.get(1, ""))
        missing = [page for page in range(1, page_count + 1) if page not in pages]
        if missing:
            problems.append(f"{tid} {div}: pager spans {page_count} pages, bundle is missing {missing}")
        for g in parse_division_pages([pages[page] for page in sorted(pages)], tid, div):
            g.division_name = f"{event_names.get(tid, tid)} - {div}"
            games.append(g)
    return games, problems


def find_unlinked_team_ids(team_ids: List[str]) -> set:
    """Return the SincSports team ids the importer cannot resolve by id. Read-only.

    Reads the approved aliases the importer caches (``get_approved_aliases``)
    and splits a merged ``"id1; id2"`` alias into its ids the same way. Only
    the service role sees those rows; another key gets an empty list, which
    would report every team as unlinked.
    """
    url, key = os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        raise SystemExit("--check-aliases needs SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY")
    supabase = create_client(url, key)
    provider_id = supabase.table("providers").select("id").eq("code", "sincsports").execute().data[0]["id"]
    aliases = (
        supabase.rpc("get_approved_aliases", {"p_provider_id": provider_id}).limit(RPC_RESULT_LIMIT).execute().data
    )
    linked = {part.strip() for alias in aliases for part in str(alias["provider_team_id"]).split(";")}
    return set(team_ids) - linked


def write_unlinked_teams_csv(out: Path, games: List[TournamentGame], unlinked: set) -> None:
    appearances: Dict[str, dict] = {}
    for g in games:
        for team_id, name in ((g.home_id, g.home_name), (g.away_id, g.away_name)):
            if team_id in unlinked:
                row = appearances.setdefault(team_id, {"team_id": team_id, "team_name": name, "divisions": set()})
                row["divisions"].add(f"{g.tournament_id}/{g.division_code}")
    with open(out, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["team_id", "team_name", "divisions"])
        writer.writeheader()
        for row in sorted(appearances.values(), key=lambda r: r["team_id"]):
            writer.writerow(
                {
                    "team_id": row["team_id"],
                    "team_name": csv_safe(row["team_name"]),
                    "divisions": csv_safe(";".join(sorted(row["divisions"]))),
                }
            )


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    source = p.add_mutually_exclusive_group(required=True)
    source.add_argument("--tid", help="Tournament ID (e.g., TZ2565)")
    source.add_argument(
        "--from-bundle",
        type=Path,
        help="Read a browser capture from scripts/sincsports_capture_bundle.js instead of fetching live",
    )
    p.add_argument("--year", type=int, default=2026, help="Tournament year (default: 2026)")
    p.add_argument(
        "--since",
        type=lambda value: datetime.strptime(value, "%Y-%m-%d").strftime("%Y-%m-%d"),
        help="Drop games dated before this day (YYYY-MM-DD)",
    )
    p.add_argument(
        "--check-aliases",
        action="store_true",
        help="Hold back games whose team has no approved team_alias_map row and list those teams (read-only)",
    )
    p.add_argument(
        "--include-cancelled",
        action="store_true",
        help="Include Cancelled games in the JSONL output (default: skip)",
    )
    p.add_argument(
        "--include-scheduled",
        action="store_true",
        help="Include Scheduled-but-not-yet-played games in the JSONL output (default: skip)",
    )
    p.add_argument(
        "--include-sub-u10",
        action="store_true",
        help="Include U08/U09 division games (default: skip; PitchRank ranks u10+)",
    )
    p.add_argument("--auto-import", action="store_true", help="Run import_games_enhanced.py after scraping")
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print summary and write any unlinked-teams list; no JSONL or import",
    )
    p.add_argument(
        "--via-proxy",
        action="store_true",
        help="Route fetches through the ZenRows proxy (bypasses SincSports' 403 bot-protection)",
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()

    if args.from_bundle:
        all_games, problems = load_bundle(args.from_bundle)
        output_label = f"bundle_{args.from_bundle.stem}"
        by_status = Counter(g.status for g in all_games)
        console.print(f"[cyan]Bundle {args.from_bundle.name}: {len(all_games)} games ({dict(by_status)})[/cyan]")
        if problems:
            console.print(f"[red]{len(problems)} capture problem(s); re-capture before importing:[/red]")
            for problem in problems:
                console.print(f"  [red]{problem}[/red]")
            return 1
    else:
        scraper = SincSportsScheduleScraper()
        if args.via_proxy:
            from src.scrapers._zenrows import ZenRowsSession

            # SincSports 403s direct requests; js_render must stay OFF (division links
            # collapse into a JS dropdown that exposes only the div=N placeholder).
            scraper.session = ZenRowsSession(js_render=False)
            console.print("[cyan]Routing schedule fetch through ZenRows proxy[/cyan]")
        try:
            all_games = scraper.fetch_tournament(args.tid, year=args.year)
        except Exception as e:
            console.print(f"[red]Failed to scrape tournament {args.tid}: {e}[/red]")
            return 1
        output_label = f"tournament_{args.tid}"

        by_status = Counter(g.status for g in all_games)
        console.print(
            f"[cyan]Tournament {args.tid} ({args.year}): {len(all_games)} games "
            f"({dict(by_status)})  errors: {len(scraper.errors)}[/cyan]"
        )

    keep = [
        g
        for g in all_games
        if g.status == "Played"
        or (args.include_cancelled and g.status == "Cancelled")
        or (args.include_scheduled and g.status == "Scheduled")
    ]
    keep = [g for g in keep if g.date]  # drop unscheduled rows lacking a date
    console.print(f"[cyan]After status/date filter: {len(keep)} games to emit[/cyan]")

    if not args.include_sub_u10:
        before = len(keep)
        keep = [g for g in keep if not _SUB_U10_CODE_RE.match(g.division_code or "")]
        dropped = before - len(keep)
        if dropped:
            console.print(
                f"[cyan]Filtered {dropped} sub-U10 games "
                f"(use --include-sub-u10 to keep them)[/cyan]"
            )

    if args.since:
        before = len(keep)
        keep = [g for g in keep if (parse_date_iso(g.date) or "") >= args.since]
        console.print(f"[cyan]Filtered {before - len(keep)} games dated before {args.since}[/cyan]")

    unlinked: set = set()
    held: List[TournamentGame] = []
    if args.check_aliases and keep:
        unlinked = find_unlinked_team_ids(sorted({g.home_id for g in keep} | {g.away_id for g in keep}))
        held = [g for g in keep if g.home_id in unlinked or g.away_id in unlinked]
        keep = [g for g in keep if g.home_id not in unlinked and g.away_id not in unlinked]
        console.print(
            f"[cyan]Holding back {len(held)} games involving {len(unlinked)} teams with no alias; "
            f"{len(keep)} games to emit[/cyan]"
        )

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    out = RAW_DIR / f"sincsports_games_{output_label}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl"
    if unlinked:
        unlinked_csv = out.with_name(f"{out.stem}_unlinked_teams.csv")
        write_unlinked_teams_csv(unlinked_csv, held, unlinked)
        console.print(f"[yellow]Wrote {len(unlinked)} unlinked teams -> {unlinked_csv}[/yellow]")

    if args.dry_run:
        return 0

    with open(out, "w", encoding="utf-8") as f:
        for g in keep:
            f.write(json.dumps(perspective_record(g, perspective="H")) + "\n")
    console.print(f"[green]Wrote {len(keep)} per-team records -> {out}[/green]")

    if not args.auto_import:
        console.print(f"\nTo import:  python scripts/import_games_enhanced.py {out} sincsports")
        return 0

    console.print("[cyan]Running import_games_enhanced.py ...[/cyan]")
    rc = subprocess.run(
        ["python", "scripts/import_games_enhanced.py", str(out), "sincsports"],
        check=False,
    ).returncode
    if rc != 0:
        console.print(f"[red]Import exited with code {rc}[/red]")
    return rc


if __name__ == "__main__":
    sys.exit(main())
