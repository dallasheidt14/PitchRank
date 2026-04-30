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

Example:
    python scripts/scrape_sincsports_tournament_schedule.py --tid TZ2565
    python scripts/scrape_sincsports_tournament_schedule.py --tid TZ2565 --auto-import
    python scripts/scrape_sincsports_tournament_schedule.py --tid TZ2565 --year 2025 --dry-run
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

# Sub-U10 division codes (e.g. U08M01, U09F02). PitchRank rankings are u10+
# (config/settings.py:_BIRTH_YEARS), so sub-u10 records would only inflate the
# scraper output and the importer's failed-match counter without ever
# contributing to a ranking. Filtered before JSONL emit by default;
# --include-sub-u10 opts in for future use.
_SUB_U10_CODE_RE = re.compile(r"^U0[89]", re.IGNORECASE)

sys.path.append(str(Path(__file__).parent.parent))

from dotenv import load_dotenv  # noqa: E402
from rich.console import Console  # noqa: E402

from src.scrapers.sincsports_schedule import (  # noqa: E402
    SincSportsScheduleScraper,
    TournamentGame,
)

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


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--tid", required=True, help="Tournament ID (e.g., TZ2565)")
    p.add_argument("--year", type=int, default=2026, help="Tournament year (default: 2026)")
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
    p.add_argument("--dry-run", action="store_true", help="Print summary only; no JSONL or import")
    return p.parse_args()


def main() -> int:
    args = parse_args()

    scraper = SincSportsScheduleScraper()
    try:
        all_games = scraper.fetch_tournament(args.tid, year=args.year)
    except Exception as e:
        console.print(f"[red]Failed to scrape tournament {args.tid}: {e}[/red]")
        return 1

    from collections import Counter

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

    if args.dry_run:
        return 0

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    out = RAW_DIR / f"sincsports_games_tournament_{args.tid}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl"
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
