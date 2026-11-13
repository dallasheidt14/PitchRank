#!/usr/bin/env python3
"""
Match the TGS teams in scraped games CSVs to existing teams, or create them.
Run this BEFORE importing games, once over every shard's CSV: the import finds
a TGS team only by its TGS id and never creates one.

A TGS id with no alias links by name to an existing team only when that team
carries no TGS id yet, so two TGS squads never share a team. Otherwise it gets
its own team, at the age its own name states, or at the youngest division it
played when the name states none.

Usage:
    python3 scripts/extract_and_import_tgs_teams.py data/raw/tgs/a.csv [b.csv ...] tgs [--dry-run]
"""

import argparse
import csv
import logging
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set, TextIO

# Add parent directory to path
sys.path.append(str(Path(__file__).parent.parent))

import os

from dotenv import load_dotenv
from rich.console import Console
from rich.markup import escape
from rich.progress import track

from scripts.enqueue_helpers import _paged  # noqa: E402
from scripts.scrape_tgs_event import lone_birth_year_groups  # noqa: E402
from src.etl.enhanced_pipeline import EnhancedETLPipeline  # noqa: E402
from src.models.tgs_matcher import ReuseRefused, TGSGameMatcher  # noqa: E402
from src.rankings.data_adapter import MERGE_MAP_LOAD_FAILED  # noqa: E402
from src.tournaments.reports.render_csv import csv_safe  # noqa: E402
from src.utils.merge_resolver import MergeResolver  # noqa: E402
from src.utils.placeholder_clubs import is_placeholder_club  # noqa: E402
from src.utils.provider_ids import is_blank_provider_id  # noqa: E402
from supabase import create_client

# Set up logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)
console = Console()

# Load environment (check .env.local first, then .env)
env_local = Path(".env.local")
if env_local.exists():
    load_dotenv(env_local)
else:
    load_dotenv()

LOGS_DIR = Path("logs")

# Each games row names two teams, in these columns.
SIDES = (
    ("team_id", "team_name", "club_name", "team_name_age"),
    ("opponent_id", "opponent_name", "opponent_club_name", "opponent_name_age"),
)


def _is_meaningful_club(club_name: str) -> bool:
    return not is_placeholder_club(club_name)


def normalize_gender(gender: str) -> Optional[str]:
    """
    Normalize gender to DB format, or None when it cannot be determined.

    Boys/B/Male → Male
    Girls/G/Female → Female

    Returns None rather than guessing. Defaulting to "Male" turned every
    unreadable label into a confidently wrong team: created at confidence 1.0
    with review_status approved, so nothing surfaced it for a human.
    """
    if not gender:
        return None

    g = gender.strip().lower()
    if g in ("boys", "b", "male", "m"):
        return "Male"
    elif g in ("girls", "g", "female", "f"):
        return "Female"
    else:
        return None


def _age_number(age_group: str) -> int:
    match = re.fullmatch(r"u([0-9]{1,2})", age_group)
    return int(match.group(1)) if match else 99


def _game_id(value: Optional[str]) -> str:
    """A team id as the game import reads it: its CSV loaders turn `501.0` into `501`."""
    value = (value or "").strip()
    try:
        return str(int(float(value))) if value else ""
    except (ValueError, TypeError, OverflowError):
        return value


@dataclass
class ScrapedTeam:
    """One TGS team as the scrape saw it, across every row that names it."""

    provider_team_id: str
    team_name: str = ""
    club_name: str = ""
    last_date: str = ""
    genders: Set[str] = field(default_factory=set)
    name_ages: Set[str] = field(default_factory=set)
    division_ages: Set[str] = field(default_factory=set)
    scored: bool = False

    @property
    def gender(self) -> Optional[str]:
        return next(iter(self.genders)) if len(self.genders) == 1 else None

    @property
    def age_group(self) -> str:
        """The age its own name states, or "" when its rows read the name two ways. A lone birth
        year is the exception when both readings are groups it fits: the younger is the one the
        team was seen playing in. A name stating no age takes the youngest division it played,
        since a team plays up and never down."""
        if len(self.name_ages) == 1:
            return next(iter(self.name_ages))
        if self.name_ages:
            fits = lone_birth_year_groups(self.team_name)
            return min(self.name_ages, key=_age_number) if self.name_ages <= fits else ""
        return min(self.division_ages, key=_age_number, default="")

    def skip_reason(self) -> Optional[str]:
        if is_blank_provider_id(self.provider_team_id):
            return "blank TGS id"
        if not self.team_name:
            return "no team name"
        if not self.scored:
            return "no scored game"
        if not self.genders:
            return "gender unknown"
        if len(self.genders) > 1:
            return "rows disagree on gender"
        if not self.age_group:
            return "name ages disagree" if self.name_ages else "no age group"
        return None


def extract_teams(csv_files: List[str]) -> Dict[str, ScrapedTeam]:
    """Every team the CSVs name, keyed by TGS id. Its name and club come from its latest game."""
    teams: Dict[str, ScrapedTeam] = {}
    for csv_file in csv_files:
        with open(csv_file, "r", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                scored = not (
                    EnhancedETLPipeline._is_empty_score(row.get("goals_for"))
                    and EnhancedETLPipeline._is_empty_score(row.get("goals_against"))
                )
                game_date = (row.get("game_date") or "").strip()
                gender = normalize_gender(row.get("gender") or "")
                division_age = (row.get("age_group") or "").strip().lower()
                for id_column, name_column, club_column, age_column in SIDES:
                    team_id = _game_id(row.get(id_column))
                    team = teams.setdefault(team_id, ScrapedTeam(team_id))
                    if game_date >= team.last_date:
                        team.last_date = game_date
                        team.team_name = (row.get(name_column) or "").strip() or team.team_name
                        team.club_name = (row.get(club_column) or "").strip() or team.club_name
                    if gender:
                        team.genders.add(gender)
                    if division_age:
                        team.division_ages.add(division_age)
                    if name_age := (row.get(age_column) or "").strip():
                        team.name_ages.add(name_age)
                    team.scored = team.scored or scored
    return teams


def fill_missing_clubs(
    supabase, teams: Dict[str, ScrapedTeam], aliases: Dict[str, Dict], dry_run: bool = False
) -> None:
    """Fill a blank or placeholder club_name on the teams the CSVs' already-aliased TGS ids name,
    from the club their games list. A real club name is never overwritten."""
    club_by_master: Dict[str, str] = {}
    for pid, alias in aliases.items():
        club = teams[pid].club_name if pid in teams else ""
        if alias.get("review_status") == "approved" and _is_meaningful_club(club):
            club_by_master[alias["team_id_master"]] = club

    if not club_by_master:
        console.print("[dim]No existing teams to fill a club on.[/dim]")
        return

    console.print(f"\n[bold]Checking the club on {len(club_by_master)} existing teams...[/bold]")
    masters = sorted(club_by_master)
    current_by_master: Dict[str, Dict] = {}
    unread = 0
    for i in range(0, len(masters), 100):  # Batch to avoid URI length limits
        batch = masters[i : i + 100]
        try:
            rows = (
                supabase.table("teams")
                .select("team_id_master, club_name, is_deprecated")
                .in_("team_id_master", batch)
                .execute()
                .data
                or []
            )
        except Exception as e:
            unread += len(batch)
            logger.warning(f"Error fetching teams (batch {i // 100 + 1}): {e}")
            continue
        current_by_master.update((row["team_id_master"], row) for row in rows)

    updates = []
    for master, club in club_by_master.items():
        current = current_by_master.get(master)
        stored = (current or {}).get("club_name") or ""
        if current and not current.get("is_deprecated") and not _is_meaningful_club(stored.strip()):
            updates.append((master, club))

    if dry_run:
        console.print(f"[yellow]DRY RUN — would fill the club on {len(updates)} teams ({unread} unread)[/yellow]")
        for master, club in updates[:10]:
            console.print(f"  {master[:8]}…: {escape(club)}")
        return

    failed = 0
    for master, club in track(updates, description="Filling clubs"):
        try:
            supabase.table("teams").update({"club_name": club}).eq("team_id_master", master).execute()
        except Exception as e:
            failed += 1
            logger.warning(f"Error updating {master}: {e}")
    style = "red" if failed or unread else "dim"
    console.print(
        f"[{style}]Filled the club on {len(updates) - failed} teams; {failed} updates failed, "
        f"{unread} teams unread[/{style}]"
    )


def alias_rows(supabase, provider_id: str, provider_team_ids: List[str]) -> Dict[str, Dict]:
    """The alias each of these TGS ids already has, whatever its review status."""
    found: Dict[str, Dict] = {}
    for i in range(0, len(provider_team_ids), 100):  # Batch to avoid URI length limits
        rows = (
            supabase.table("team_alias_map")
            .select("provider_team_id, team_id_master, match_method, review_status")
            .eq("provider_id", provider_id)
            .in_("provider_team_id", provider_team_ids[i : i + 100])
            .execute()
            .data
            or []
        )
        found.update((str(row["provider_team_id"]), row) for row in rows)
    return found


def tgs_linked_teams(supabase, provider_id: str) -> Set[str]:
    """Live teams that already carry a TGS id: an approved TGS alias names them, or they began as
    a TGS row. Either may since have been merged into another team, which then carries it."""
    merges = MergeResolver(supabase)
    merges.load_merge_map()
    if merges.version == MERGE_MAP_LOAD_FAILED:
        raise SystemExit("Merge map failed to load; re-run rather than matching against unresolved ids")
    aliases = _paged(
        lambda: (
            supabase.table("team_alias_map")
            .select("team_id_master")
            .eq("provider_id", provider_id)
            .eq("review_status", "approved")
        )
    )
    tgs_rows = _paged(lambda: supabase.table("teams").select("team_id_master").eq("provider_id", provider_id))
    return {merges.resolve(row["team_id_master"]) for row in [*aliases, *tgs_rows]}


def match_or_create(matcher: TGSGameMatcher, provider_id: str, teams: List[ScrapedTeam]) -> List[Dict]:
    """Link each team to the team its name matches, or create it; one outcome row per team.

    Every match is found before anything is written, so which teams link never depends on the
    order they are visited. A match already carrying a TGS id, or wanted by two of these teams,
    links to neither: each gets its own team, which the weekly merges can fold if they are one.
    A team whose search fails gets nothing this run, since creating it then could duplicate the
    team the search would have found.
    """
    candidates: Dict[str, Optional[Dict]] = {}
    for team in track(teams, description="Matching teams"):
        try:
            candidates[team.provider_team_id] = matcher.link_candidate(
                team.team_name, team.age_group, team.gender, team.club_name or None
            )
        except Exception as e:
            logger.error(f"Error searching for a match for {team.team_name} ({team.provider_team_id}): {e}")
    wanted = Counter(candidate["team_id"] for candidate in candidates.values() if candidate)
    outcomes = []
    for team in teams:
        if team.provider_team_id not in candidates:
            outcomes.append(_outcome(team, "error: search failed", None, None))
            continue
        candidate = candidates[team.provider_team_id]
        if candidate and candidate["team_id"] not in matcher.claimed_team_ids and wanted[candidate["team_id"]] == 1:
            matcher._create_alias(
                provider_id=provider_id,
                provider_team_id=team.provider_team_id,
                team_name=team.team_name,
                team_id_master=candidate["team_id"],
                match_method="fuzzy_auto",
                confidence=candidate["confidence"],
                age_group=team.age_group,
                gender=team.gender,
                review_status="approved",
            )
            outcomes.append(_outcome(team, "linked", candidate["team_id"], candidate))
            continue
        if not candidate:
            outcome = "created"
        elif candidate["team_id"] in matcher.claimed_team_ids:
            outcome = "created: match carries a TGS id"
        else:
            outcome = "created: match wanted by another TGS id"
        try:
            team_id = matcher.create_team(
                provider_id, team.provider_team_id, team.team_name, team.club_name or None, team.age_group, team.gender
            )
        except ReuseRefused as e:
            logger.info(f"[TGS] {e}; holding {team.provider_team_id}, so its games import without it")
            outcomes.append(_outcome(team, "held: gender guard", None, candidate))
            continue
        except Exception as e:
            logger.error(f"Error creating team {team.team_name} ({team.provider_team_id}): {e}")
            outcomes.append(_outcome(team, "error: not created", None, candidate))
            continue
        outcomes.append(_outcome(team, outcome, team_id, candidate))
    return outcomes


def _outcome(team: ScrapedTeam, outcome: str, team_id: Optional[str], candidate: Optional[Dict]) -> Dict:
    return {
        "provider_team_id": team.provider_team_id,
        "team_name": team.team_name,
        "club_name": team.club_name,
        "age_group": team.age_group,
        "gender": team.gender,
        "outcome": outcome,
        "team_id_master": team_id or "",
        "match_team_id": candidate["team_id"] if candidate else "",
        "match_team_name": candidate["team_name"] if candidate else "",
        "match_confidence": candidate["confidence"] if candidate else "",
    }


def write_outcomes(outcomes: List[Dict], out: TextIO) -> None:
    writer = csv.DictWriter(out, fieldnames=list(_outcome(ScrapedTeam(""), "", None, None)), lineterminator="\n")
    writer.writeheader()
    writer.writerows({column: csv_safe(value) for column, value in row.items()} for row in outcomes)


def misaliased(supabase, provider_id: str, outcomes: List[Dict]) -> List[str]:
    """TGS ids this run linked or created whose alias, read back, is not the one it wrote.
    _create_alias logs a failed write and returns."""
    intended = {
        row["provider_team_id"]: (
            row["team_id_master"],
            "fuzzy_auto" if row["outcome"] == "linked" else "direct_id",
            "approved",
        )
        for row in outcomes
        if row["team_id_master"]
    }
    stored = alias_rows(supabase, provider_id, sorted(intended))
    return sorted(
        pid
        for pid, written in intended.items()
        if tuple(stored.get(pid, {}).get(key) for key in ("team_id_master", "match_method", "review_status")) != written
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Match or create the TGS teams in scraped games CSVs (run BEFORE game import)"
    )
    parser.add_argument("csv_files", nargs="+", help="Games CSV files, one per shard")
    parser.add_argument("provider", help='Provider code (e.g., "tgs")')
    parser.add_argument("--dry-run", action="store_true", help="Show what would be matched or created without writing")
    args = parser.parse_args()

    missing_files = [path for path in args.csv_files if not Path(path).exists()]
    if missing_files:
        console.print(f"[red]Error: File not found: {escape(', '.join(missing_files))}[/red]")
        return 1

    # Initialize Supabase
    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY")

    if not supabase_url or not supabase_key:
        console.print("[red]Error: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set[/red]")
        return 1

    supabase = create_client(supabase_url, supabase_key)

    # Get provider ID
    try:
        result = supabase.table("providers").select("id").eq("code", args.provider).single().execute()
        provider_id = result.data["id"]
        console.print(f"[green]✓ Provider ID: {provider_id}[/green]")
    except Exception as e:
        console.print(f"[red]Error: Provider '{escape(args.provider)}' not found: {escape(str(e))}[/red]")
        return 1

    teams = extract_teams(args.csv_files)
    skipped = Counter(reason for team in teams.values() if (reason := team.skip_reason()))
    claimed = tgs_linked_teams(supabase, provider_id)
    aliases = alias_rows(supabase, provider_id, sorted(pid for pid in teams if not is_blank_provider_id(pid)))
    fill_missing_clubs(supabase, teams, aliases, dry_run=args.dry_run)
    new_teams = sorted(
        (team for pid, team in teams.items() if pid not in aliases and not team.skip_reason()),
        key=lambda team: team.provider_team_id,
    )
    console.print(
        f"\n[bold]{len(teams):,} TGS teams in {len(args.csv_files)} CSV(s): {len(aliases):,} already aliased, "
        f"{len(new_teams):,} to match or create[/bold]"
    )

    matcher = TGSGameMatcher(supabase, provider_id=provider_id, dry_run=args.dry_run)
    matcher.claimed_team_ids = claimed
    outcomes = match_or_create(matcher, provider_id, new_teams)

    console.print("\n[bold green]═══════════════════════════════════════════[/bold green]")
    console.print("[bold green]          MATCH SUMMARY[/bold green]")
    console.print("[bold green]═══════════════════════════════════════════[/bold green]")
    for outcome, count in sorted(Counter(row["outcome"] for row in outcomes).items()):
        console.print(f"  {outcome:42s} {count:6,}")
    for reason, count in sorted(skipped.items()):
        console.print(f"  [dim]skipped, {reason:33s} {count:6,}[/dim]")
    for row in outcomes:
        if row["outcome"] == "linked":
            console.print(
                escape(
                    f"  linked {row['provider_team_id']} {row['team_name']!r} ({row['age_group']}) -> "
                    f"{row['match_team_name']!r} {row['team_id_master']} at {row['match_confidence']}"
                )
            )

    failed = sorted(row["provider_team_id"] for row in outcomes if row["outcome"].startswith("error"))
    if failed:
        console.print(f"[red]{len(failed)} TGS ids could not be given a team: {escape(str(failed[:20]))}[/red]")

    if args.dry_run:
        write_outcomes(outcomes, sys.stdout)
        console.print("[yellow]Dry run completed - no changes made[/yellow]")
        return 1 if failed else 0

    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOGS_DIR / f"tgs_team_matches_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    with open(log_path, "w", newline="", encoding="utf-8") as f:
        write_outcomes(outcomes, f)
    console.print(f"  Outcomes written to {log_path}")

    wrong = misaliased(supabase, provider_id, outcomes)
    if wrong:
        console.print(
            f"[red]{len(wrong)} TGS ids linked or created this run lack the alias written for them: "
            f"{escape(str(wrong[:20]))}[/red]"
        )
    return 1 if failed or wrong else 0


if __name__ == "__main__":
    sys.exit(main())
