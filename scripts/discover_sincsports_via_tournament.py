#!/usr/bin/env python3
"""SincSports tournament-based team discovery driver.

Complementary to ``scripts/discover_sincsports_teams.py`` (which sources
teams from the clubs-directory search at ``sicclubs.aspx?sinc=Y``). This
driver scrapes ``teamlist.aspx?tid=<TID>&tab=6&sub=0`` — the single-page
team roster for a given tournament — and threads each discovered team
through ``SincSportsGameMatcher`` with ``discovery_mode=True``.

Rationale: the clubs search does not surface every registered team.
Against the 2026 Puri Champions Cup, a full-grid clubs-search u14 Female
discovery had surfaced 4 of the 332 teams participating — 99% coverage
gap. Event-based discovery closes that gap from a different angle.

SincSports answers plain HTTP clients with a Cloudflare challenge, so
``--from-bundle`` reads the team list a ``divisions`` capture by
``scripts/sincsports_capture_bundle.js`` saved instead. A bundle also dates the
event, so each team's age is read from its own name against the event's season
(``resolve_team_age``). The division a team is listed under is never used for its
age, since teams play up; a name that states no age is held for review.

CLI examples:

    python scripts/discover_sincsports_via_tournament.py --tid TZ2565 --dry-run
    python scripts/discover_sincsports_via_tournament.py --tid TZ2565
    python scripts/discover_sincsports_via_tournament.py --from-bundle data/raw/x/divisions.json --dry-run
"""

from __future__ import annotations

import argparse
import csv
import dataclasses
import json
import logging
import os
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.path.append(str(Path(__file__).parent.parent))

from dotenv import load_dotenv  # noqa: E402
from rich.console import Console  # noqa: E402
from rich.panel import Panel  # noqa: E402
from rich.progress import track  # noqa: E402
from rich.table import Table  # noqa: E402

from scripts.import_athletes2events_event import (  # noqa: E402
    NO_AGE_IN_NAME,
    ODD_YEAR_SPAN,
    age_from_name,
    board_cohort,
    respell_ages,
)
from scripts.scrape_sincsports_tournament_schedule import load_bundle, parse_date_iso  # noqa: E402
from src.models.sincsports_matcher import SincSportsGameMatcher  # noqa: E402
from src.scrapers.sincsports_clubs import TeamRecord  # noqa: E402
from src.scrapers.sincsports_events import SincSportsEventsScraper  # noqa: E402
from src.utils.team_utils import _soccer_season_year  # noqa: E402
from supabase import create_client  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)
console = Console()

_env_local = Path(".env.local")
if _env_local.exists():
    load_dotenv(_env_local)
else:
    load_dotenv()

EXPORTS_DIR = Path("data/exports")
CSV_COLUMNS = ["provider_team_id", "team_name", "club_name", "age_group", "gender", "state_code"]
LOW_CONFIDENCE_COLUMNS = [
    "provider_team_id",
    "team_name",
    "age_group",
    "gender",
    "state_code",
    "club_name",
    "suppressed_review_method",
    "suppressed_review_confidence",
]

# Every division heading a team list can carry; the u10+ board filter runs only after
# each team's own age is known, since an "Under 9/10" division holds real U10 teams.
ALL_DIVISION_AGES = frozenset(f"u{age}" for age in range(6, 20))
BELOW_BOARDS = "below the u10 boards"

# Shorter wording for the held list: with no division there is nothing to fall back to.
_HELD_REASONS = {NO_AGE_IN_NAME: "no age in name", ODD_YEAR_SPAN: "odd year span"}


def resolve_team_age(record: TeamRecord, event_season: int, board_season: int) -> Tuple[Optional[str], str]:
    """The board a team belongs on, read from its own name only, with how it was read.

    The division a team is listed under plays no part: teams play up, so it says
    nothing about their age. A bare year is a birth year ("14B" is a 2014 squad).
    ``None`` with a reason holds the team for review; ``None`` with ``BELOW_BOARDS``
    means it has no board.
    """
    birth_year, how = age_from_name(respell_ages(record.team_name), None, event_season)
    if birth_year is None:
        return None, _HELD_REASONS.get(how, how)
    board = board_cohort(birth_year, board_season)
    return board, how if board else BELOW_BOARDS


def load_bundle_teams(path: Path) -> List[Tuple[TeamRecord, int]]:
    """Each team a capture names, with the season of the event that lists it.

    A team list's Team | Club | State rows come first; the team pages captured for
    the scheduled teams those rows miss fill in the rest. A capture can hold several
    events, so each is dated from its own games.
    """
    bundle = json.loads(path.read_text(encoding="utf-8"))
    pages = bundle.get("teamlists") or []
    if not pages:
        raise SystemExit(f"{path.name} holds no team list; re-capture it with scripts/sincsports_capture_bundle.js")
    games, problems = load_bundle(path)
    for problem in problems:
        console.print(f"[yellow]Capture problem: {problem}[/yellow]")
    first_day: Dict[str, date] = {}
    for g in games:
        if iso := parse_date_iso(g.date):
            day = date.fromisoformat(iso)
            first_day[g.tournament_id] = min(first_day.get(g.tournament_id, day), day)
    records: Dict[str, Tuple[TeamRecord, int]] = {}
    found = [
        (page["tid"], record)
        for page in pages
        for record in SincSportsEventsScraper.parse_teamlist(page["html"], include_ages=ALL_DIVISION_AGES)
    ]
    for team_page in bundle.get("teampages") or []:
        if record := SincSportsEventsScraper.parse_team_page(team_page["teamid"], team_page["html"]):
            found.append((team_page["tid"], record))
    for tid, record in found:
        if tid not in first_day:
            raise SystemExit(f"{path.name} holds no dated games for {tid}, so that event's season is unknown")
        records.setdefault(record.provider_team_id, (record, _soccer_season_year(first_day[tid])))
    scheduled = {team_id for g in games for team_id in (g.home_id, g.away_id) if team_id}
    if not records:
        raise SystemExit(f"{path.name} names none of its {len(scheduled)} scheduled teams; re-capture it")
    if missing := sorted(scheduled - records.keys()):
        console.print(f"[yellow]{len(missing)} scheduled teams have no club or state in {path.name}[/yellow]")
    return list(records.values())


def ensure_provider_exists(supabase, dry_run: bool = False) -> Optional[str]:
    """Resolve the SincSports provider UUID (sync copy of import_sincsports_teams.py)."""
    result = supabase.table("providers").select("id").eq("code", "sincsports").execute()
    if result.data:
        return result.data[0]["id"]
    if dry_run:
        return None
    console.print("  [yellow]⚠[/yellow] Provider not found, creating...")
    new_provider = {"code": "sincsports", "name": "SincSports", "base_url": "https://soccer.sincsports.com"}
    result = supabase.table("providers").insert(new_provider).execute()
    if result.data:
        return result.data[0]["id"]
    return None


def bulk_existing_aliases(supabase, provider_id: str, provider_team_ids: List[str]) -> Dict[str, str]:
    """100-ID chunked `.in_()` pre-check against team_alias_map."""
    existing: Dict[str, str] = {}
    for i in range(0, len(provider_team_ids), 100):
        batch = provider_team_ids[i : i + 100]
        try:
            result = (
                supabase.table("team_alias_map")
                .select("provider_team_id, team_id_master")
                .eq("provider_id", provider_id)
                .in_("provider_team_id", batch)
                .execute()
            )
            for row in result.data or []:
                existing[str(row["provider_team_id"])] = row["team_id_master"]
        except Exception as e:
            logger.warning(f"Error checking existing aliases (batch {i // 100 + 1}): {e}")
    return existing


def append_low_confidence_row(path: Path, row: Dict) -> None:
    new_file = not path.exists()
    with open(path, "a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=LOW_CONFIDENCE_COLUMNS)
        if new_file:
            writer.writeheader()
        writer.writerow({k: (row.get(k) if row.get(k) is not None else "") for k in LOW_CONFIDENCE_COLUMNS})


def write_csv(path: Path, records: List) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for r in records:
            writer.writerow(
                {
                    "provider_team_id": r.provider_team_id,
                    "team_name": r.team_name,
                    "club_name": r.club_name or "",
                    "age_group": r.age_group,
                    "gender": r.gender,
                    "state_code": r.state_code or "",
                }
            )
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    source = p.add_mutually_exclusive_group(required=True)
    source.add_argument("--tid", help="SincSports tournament ID (e.g., TZ2565)")
    source.add_argument(
        "--from-bundle",
        type=Path,
        help="Read the team list from a divisions capture by scripts/sincsports_capture_bundle.js",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Match every team without writing: reports what a real run would link, create and hold",
    )
    p.add_argument(
        "--via-proxy",
        action="store_true",
        help="Route the teamlist fetch through the ZenRows proxy (bypasses SincSports' 403 bot-protection)",
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()

    EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
    run_ts = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    label = args.tid or args.from_bundle.stem
    tid_safe = "".join(c if c.isalnum() else "_" for c in label)
    csv_path = EXPORTS_DIR / f"sincsports_tournament_{tid_safe}_{run_ts}.csv"
    low_conf_path = EXPORTS_DIR / f"sincsports_tournament_{tid_safe}_low_confidence_{run_ts}.csv"

    # Scrape phase — no Supabase required.
    board_season = _soccer_season_year()
    if args.from_bundle:
        listed = load_bundle_teams(args.from_bundle)
    else:
        scraper = SincSportsEventsScraper()
        if args.via_proxy:
            from src.scrapers._zenrows import ZenRowsSession

            # SincSports 403s direct requests; js_render must stay OFF (teamlist rows
            # are server-rendered and vanish from the JS-rendered DOM).
            scraper.session = ZenRowsSession(js_render=False)
            console.print("[cyan]Routing teamlist fetch through ZenRows proxy[/cyan]")
        try:
            fetched = scraper.fetch_teamlist(args.tid, include_ages=ALL_DIVISION_AGES)
        except Exception as e:
            console.print(f"[red]Failed to fetch teamlist for tid={args.tid}: {e}[/red]")
            return 1
        # A live fetch carries no game dates, so its labels are read as this season's.
        listed = [(record, board_season) for record in fetched]

    held: List[Tuple[TeamRecord, str]] = []
    records = []
    for record, event_season in listed:
        age_group, how = resolve_team_age(record, event_season, board_season)
        if age_group:
            records.append(dataclasses.replace(record, age_group=age_group))
        elif how != BELOW_BOARDS:
            held.append((record, how))

    from collections import Counter

    by_cohort = Counter((r.age_group, r.gender) for r in records)
    by_state = Counter(r.state_code or "?" for r in records)
    console.print(
        Panel.fit(
            f"[bold cyan]SincSports Tournament Discovery[/bold cyan]\n"
            f"source: {label} | Teams parsed: {len(records)} | Held: {len(held)} | "
            f"Cohorts: {len(by_cohort)} | States: {len(by_state)} | Dry run: {args.dry_run}",
            style="cyan",
        )
    )

    write_csv(csv_path, records)
    console.print(f"[green]CSV: {csv_path}[/green]")
    if held:
        held_table = Table(title="Held for review: the name does not settle the age")
        for column in ("Team id", "Team", "Division", "Reason"):
            held_table.add_column(column)
        for record, how in held:
            held_table.add_row(record.provider_team_id, record.team_name, str(record.division_ages), how)
        console.print(held_table)

    # Match phase — requires Supabase.
    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY")
    if not supabase_url or not supabase_key:
        console.print("[red]Error: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY (or SUPABASE_KEY) must be set[/red]")
        return 1
    supabase = create_client(supabase_url, supabase_key)
    provider_id = ensure_provider_exists(supabase, dry_run=args.dry_run)
    if not provider_id:
        console.print("[red]Cannot proceed without SincSports provider.[/red]")
        return 1

    matcher = SincSportsGameMatcher(supabase, provider_id=provider_id, discovery_mode=True, dry_run=args.dry_run)
    existing = bulk_existing_aliases(supabase, provider_id, [r.provider_team_id for r in records])
    console.print(f"[yellow]{len(existing)} teams already aliased - skipping create path.[/yellow]")

    buckets = {
        "direct_alias_hit": 0,
        "fuzzy_auto_linked": 0,
        "created_new": 0,
        "low_confidence_auto_created": 0,
        "errors": 0,
    }

    to_match = [r for r in records if r.provider_team_id not in existing]
    for record in track(to_match, description="Matching teams"):
        try:
            result = matcher._match_team(
                provider_id=provider_id,
                provider_team_id=record.provider_team_id,
                team_name=record.team_name,
                age_group=record.age_group,
                gender=record.gender,
                club_name=record.club_name,
                state_code=record.state_code,
            )
        except Exception as e:
            logger.error(f"match error for {record.provider_team_id}: {e}")
            buckets["errors"] += 1
            continue

        created = result.get("created", False)
        method = result.get("method")
        suppressed = result.get("suppressed_review_method")

        if created is False and method in ("direct_id", "provider_id", "alias"):
            buckets["direct_alias_hit"] += 1
        elif created is False and method == "fuzzy_auto":
            buckets["fuzzy_auto_linked"] += 1
        elif created is True and suppressed is None:
            buckets["created_new"] += 1
        elif created is True and suppressed in ("fuzzy_review", "fuzzy_review_low"):
            buckets["low_confidence_auto_created"] += 1
            append_low_confidence_row(
                low_conf_path,
                {
                    "provider_team_id": record.provider_team_id,
                    "team_name": record.team_name,
                    "age_group": record.age_group,
                    "gender": record.gender,
                    "state_code": record.state_code or "",
                    "club_name": record.club_name or "",
                    "suppressed_review_method": suppressed,
                    "suppressed_review_confidence": result.get("suppressed_review_confidence"),
                },
            )
        else:
            logger.error(
                f"Unclassified match result for {record.provider_team_id}: "
                f"created={created!r} method={method!r} suppressed={suppressed!r}"
            )
            buckets["errors"] += 1

    dry_label = " - DRY RUN, nothing written" if args.dry_run else ""
    summary = Table(title=f"SincSports Tournament Discovery Summary ({label}){dry_label}")
    summary.add_column("Bucket")
    summary.add_column("Count", justify="right")
    summary.add_row("Teams parsed", str(len(records)))
    summary.add_row("Held for review", str(len(held)))
    summary.add_row("Skipped (existing alias)", str(len(existing)))
    for k, v in buckets.items():
        summary.add_row(k, str(v))
    console.print(summary)

    console.print(f"[green]CSV: {csv_path}[/green]")
    if low_conf_path.exists():
        console.print(f"[yellow]Low-confidence audit CSV: {low_conf_path}[/yellow]")

    return 0


if __name__ == "__main__":
    sys.exit(main())
