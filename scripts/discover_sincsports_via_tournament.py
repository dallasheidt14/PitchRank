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

CLI examples:

    python scripts/discover_sincsports_via_tournament.py --tid TZ2565 --dry-run
    python scripts/discover_sincsports_via_tournament.py --tid TZ2565
"""

from __future__ import annotations

import argparse
import csv
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

sys.path.append(str(Path(__file__).parent.parent))

from dotenv import load_dotenv  # noqa: E402
from rich.console import Console  # noqa: E402
from rich.panel import Panel  # noqa: E402
from rich.progress import track  # noqa: E402
from rich.table import Table  # noqa: E402

from src.models.sincsports_matcher import SincSportsGameMatcher  # noqa: E402
from src.scrapers.sincsports_events import SincSportsEventsScraper  # noqa: E402
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


def ensure_provider_exists(supabase) -> Optional[str]:
    """Resolve the SincSports provider UUID (sync copy of import_sincsports_teams.py)."""
    result = supabase.table("providers").select("id").eq("code", "sincsports").execute()
    if result.data:
        return result.data[0]["id"]
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
    p.add_argument("--tid", required=True, help="SincSports tournament ID (e.g., TZ2565)")
    p.add_argument("--dry-run", action="store_true", help="Scrape + CSV only; no DB writes")
    p.add_argument(
        "--include-u8-u9",
        action="store_true",
        help="Include u8/u9 divisions (default: filter to u10..u17, u19)",
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()

    EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
    run_ts = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    tid_safe = "".join(c if c.isalnum() else "_" for c in args.tid)
    csv_path = EXPORTS_DIR / f"sincsports_tournament_{tid_safe}_{run_ts}.csv"
    low_conf_path = EXPORTS_DIR / f"sincsports_tournament_{tid_safe}_low_confidence_{run_ts}.csv"

    # Scrape phase — no Supabase required.
    scraper = SincSportsEventsScraper()
    include_ages = None
    if args.include_u8_u9:
        from src.scrapers.sincsports_events import CANONICAL_AGE_GROUPS

        include_ages = frozenset({"u8", "u9", *CANONICAL_AGE_GROUPS})
    try:
        records = scraper.fetch_teamlist(args.tid, include_ages=include_ages)
    except Exception as e:
        console.print(f"[red]Failed to fetch teamlist for tid={args.tid}: {e}[/red]")
        return 1

    from collections import Counter

    by_cohort = Counter((r.age_group, r.gender) for r in records)
    by_state = Counter(r.state_code or "?" for r in records)
    console.print(
        Panel.fit(
            f"[bold cyan]SincSports Tournament Discovery[/bold cyan]\n"
            f"tid: {args.tid} | Teams parsed: {len(records)} | "
            f"Cohorts: {len(by_cohort)} | States: {len(by_state)} | Dry run: {args.dry_run}",
            style="cyan",
        )
    )

    write_csv(csv_path, records)
    console.print(f"[green]CSV: {csv_path}[/green]")

    if args.dry_run:
        console.print(f"\n[bold]By cohort:[/bold] {dict(sorted(by_cohort.items()))}")
        console.print(f"[bold]By state:[/bold] {dict(by_state.most_common())}")
        return 0

    # Match phase — requires Supabase.
    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY")
    if not supabase_url or not supabase_key:
        console.print("[red]Error: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY (or SUPABASE_KEY) must be set[/red]")
        return 1
    supabase = create_client(supabase_url, supabase_key)
    provider_id = ensure_provider_exists(supabase)
    if not provider_id:
        console.print("[red]Cannot proceed without SincSports provider.[/red]")
        return 1

    matcher = SincSportsGameMatcher(supabase, provider_id=provider_id, discovery_mode=True)
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

    summary = Table(title=f"SincSports Tournament Discovery Summary (tid={args.tid})")
    summary.add_column("Bucket")
    summary.add_column("Count", justify="right")
    summary.add_row("Teams parsed", str(len(records)))
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
