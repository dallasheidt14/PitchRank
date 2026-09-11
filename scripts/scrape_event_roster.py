#!/usr/bin/env python3
"""Scrape one GotSport event's accepted teams and resolve them to our team ids.

Operator-run, not scheduled. Every page goes through ZenRows at 25 credits
(~$0.004), and a full event is roughly 1 + one-per-division + one-per-team
requests — about 405 for a 57-division event, so ~$1.68. Use ``--limit-groups``
to price a new event against a couple of divisions before paying for all of it.

Usage::

    python scripts/scrape_event_roster.py --event-url https://system.gotsport.com/org_event/events/52975
    python scripts/scrape_event_roster.py --event-id 52975 --limit-groups 2 --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

from dotenv import load_dotenv
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from src.tournaments.event_roster_intake import resolve_master_ids
from src.tournaments.gotsport_event_roster import (
    EVENT_ID,
    EVENT_ID_IN_URL,
    WafChallengeError,
    event_roster_from_dict,
    event_roster_to_dict,
    make_zenrows_fetcher,
    printable_text,
    scrape_event_roster,
)
from src.tournaments.storage._io import write_json

console = Console()
_ENV_LOCAL = Path(__file__).resolve().parent.parent / ".env.local"
if _ENV_LOCAL.exists():
    load_dotenv(_ENV_LOCAL, override=True)
else:
    load_dotenv()


def _positive_int(value: str) -> int:
    """Reject a negative count before it becomes a slice.

    ``--limit-groups -1`` slices from the end, walking every division but one —
    near-full spend from the flag whose whole purpose is to cap it.
    """
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError(f"must be 1 or more, got {number}")
    return number


def _non_negative_float(value: str) -> float:
    """Reject a negative delay before ``time.sleep`` raises on a paid page."""
    number = float(value)
    if number < 0:
        raise argparse.ArgumentTypeError(f"must be 0 or more, got {number}")
    return number


def _event_id_from(args: argparse.Namespace) -> str:
    """Read the event id, refusing anything that is not a bare number.

    The id becomes a path segment under ``reports/``, so an unvalidated value
    lets ``../`` escape the directory the roster is meant to live in.
    """
    if args.event_id:
        if not EVENT_ID.match(args.event_id):
            raise SystemExit(f"Not a GotSport event id: {args.event_id}")
        return args.event_id

    match = EVENT_ID_IN_URL.search(args.event_url or "")
    if not match:
        raise SystemExit(f"Could not read an event id from: {args.event_url}")
    return match.group(1)


def _summary_table(teams, master_ids: dict[str, str]) -> Table:
    table = Table(title="Roster by division")
    for column in ("Division", "Cohort", "Teams", "With provider id", "Resolved"):
        table.add_column(column)

    by_division: dict[str, list] = {}
    for team in teams:
        by_division.setdefault(team.division_label, []).append(team)

    for label, rows in by_division.items():
        with_id = [row for row in rows if row.provider_team_id]
        resolved = [row for row in with_id if row.provider_team_id in master_ids]
        cohort = " ".join(part for part in (rows[0].age_group, rows[0].gender) if part) or "—"
        table.add_row(
            escape(printable_text(label) or "—"),
            cohort,
            str(len(rows)),
            str(len(with_id)),
            str(len(resolved)),
        )
    return table


def _completed_summary(roster) -> None:
    """Report entries by the tournament's cohorts, independently of registry ages."""
    from src.tournaments.backtest_intake_state import tournament_totals

    totals = tournament_totals(roster)
    console.print(f"[bold cyan]{escape(printable_text(totals['event_name']))}[/bold cyan]")
    console.print(
        f"[bold]{totals['total_teams']}[/bold] unique teams, "
        f"[bold]{totals['division_entries']}[/bold] division entries"
    )
    table = Table(title="Teams by tournament cohort")
    for heading in ("Tournament cohort", "Gender", "Teams"):
        table.add_column(heading)
    for row in totals["cohorts"]:
        table.add_row(row["Tournament cohort"], row["Gender"], str(row["Teams"]))
    console.print(table)
    if totals["unidentified_teams"]:
        console.print(
            f"[yellow]{totals['unidentified_teams']} published team entries have no registration ID; "
            "they remain separate local entries for review.[/yellow]"
        )


def _default_output_path(event_id: str, *, completed_event: bool) -> Path:
    if completed_event:
        from src.tournaments.storage.event_key import existing_event_key, intake_dir

        return intake_dir(existing_event_key("gotsport", event_id)) / "last_walk.json"
    return Path(f"reports/seeding/gotsport_{event_id}/roster.json")


def _write_completed_roster(out_path: Path, payload: dict, *, force: bool) -> None:
    """Share the Backtest recovery lock and preserve a richer existing capture."""
    from src.tournaments.backtest_intake_state import IntakeOverwriteRefused, assert_capture_preserved
    from src.tournaments.storage._file_lock import _acquire_file_lock

    fresh = event_roster_from_dict(payload)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with _acquire_file_lock(out_path.with_suffix(".lock"), timeout=1.0):
        if out_path.exists() and not force:
            previous = event_roster_from_dict(json.loads(out_path.read_text(encoding="utf-8")))
            try:
                assert_capture_preserved(previous, fresh)
            except IntakeOverwriteRefused as exc:
                raise SystemExit(
                    f"{out_path} already holds a different or more complete capture. "
                    "Pass --force to replace it, or --out to write elsewhere."
                ) from exc
        write_json(out_path, payload)


def _write_roster(out_path: Path, payload: dict, *, force: bool) -> None:
    """Write the roster, refusing to replace a complete one with a partial one.

    A limited or blocked run targets the same filename as a full one, so
    without this an operator pricing an event with ``--limit-groups`` — or a
    walk that hit a bot challenge — silently overwrites the provider ids a
    full walk already paid for. An unreadable existing file is treated as
    absent rather than aborting, because the run's own result is the thing
    that cost money.
    """
    if payload.get("completed_event") is True:
        _write_completed_roster(out_path, payload, force=force)
        return
    if not payload["is_complete"] and not force:
        try:
            existing = json.loads(out_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            existing = None
        # Only a dict whose flag is literally True blocks the write. A JSON array
        # or scalar would raise on .get, and the string "false" is truthy — either
        # way the run that cost money is the one thrown away.
        if isinstance(existing, dict) and existing.get("is_complete") is True:
            raise SystemExit(
                f"{out_path} holds a complete roster and this walk was not. "
                "Pass --force to replace it, or --out to write elsewhere."
            )

    write_json(out_path, payload)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--event-url", help="Full event URL")
    source.add_argument("--event-id", help="GotSport event id, e.g. 52975")
    parser.add_argument("--out", help="Where to write the roster JSON")
    parser.add_argument(
        "--limit-groups",
        type=_positive_int,
        help="Only walk this many divisions (cheap smoke test)",
    )
    parser.add_argument(
        "--concurrency", type=_positive_int, default=8, help="Pages fetched in parallel"
    )
    parser.add_argument("--delay-min", type=_non_negative_float, default=0.0)
    parser.add_argument("--delay-max", type=_non_negative_float, default=0.0)
    parser.add_argument("--no-resolve", action="store_true", help="Skip the master-id lookup")
    parser.add_argument(
        "--completed-event", action="store_true",
        help="Capture every division of a played event, its published cohorts and exact structure",
    )
    parser.add_argument("--force", action="store_true", help="Replace a complete roster anyway")
    parser.add_argument("--dry-run", action="store_true", help="Scrape and report, write nothing")
    args = parser.parse_args()

    api_key = os.getenv("ZENROWS_API_KEY")
    if not api_key:
        raise SystemExit("ZENROWS_API_KEY is required — these pages are WAF-gated.")

    event_id = _event_id_from(args)
    out_path = Path(args.out) if args.out else _default_output_path(event_id, completed_event=args.completed_event)

    console.print(f"[bold cyan]Scraping event {event_id}[/bold cyan]")
    try:
        roster = scrape_event_roster(
            event_id,
            fetch=make_zenrows_fetcher(api_key),
            delay_min=args.delay_min,
            delay_max=args.delay_max,
            limit_groups=args.limit_groups,
            max_workers=args.concurrency,
            on_progress=lambda done, total: console.print(f"  team {done}/{total}", end="\r"),
            completed_event=args.completed_event,
        )
    except WafChallengeError as exc:
        raise SystemExit(f"Blocked: {exc}") from exc
    except RuntimeError as exc:
        # Only the landing-page fetch can end the walk; division and team pages
        # degrade to warnings. Exit like the missing-key check, not with a traceback.
        raise SystemExit(f"Could not read event {event_id}: {exc}") from exc

    master_ids, resolve_warnings = resolve_master_ids(roster.teams, enabled=not args.no_resolve)
    warnings = list(roster.warnings) + resolve_warnings
    with_id = [team for team in roster.teams if team.provider_team_id]
    resolved = [team for team in with_id if team.provider_team_id in master_ids]

    console.print()
    if args.completed_event:
        _completed_summary(roster)
    else:
        console.print(_summary_table(roster.teams, master_ids))
        console.print(
            f"[bold]{len(roster.teams)}[/bold] teams, "
            f"[bold]{len(with_id)}[/bold] with a provider id, "
            f"[bold]{len(resolved)}[/bold] resolved to a PitchRank team"
        )
    if not roster.is_complete:
        console.print("[yellow]Partial walk — this roster is not the whole event[/yellow]")
    for warning in warnings:
        console.print(f"[yellow]{escape(printable_text(warning))}[/yellow]")

    payload = {
        **event_roster_to_dict(replace(roster, warnings=tuple(printable_text(warning) for warning in warnings))),
        "scraped_at": datetime.now(timezone.utc).isoformat(),
    }
    if args.completed_event:
        payload = {**payload, "walked_at": payload["scraped_at"], "limit_groups": args.limit_groups}
    payload["teams"] = [
        item | {
            "division_label": printable_text(item["division_label"]),
            "team_name": printable_text(item["team_name"]),
            "team_id_master": master_ids.get(item.get("provider_team_id") or ""),
        }
        for item in payload["teams"]
    ]

    if args.dry_run:
        console.print(f"[yellow]DRY RUN — would write {escape(str(out_path))}[/yellow]")
        return 0

    _write_roster(out_path, payload, force=args.force)
    console.print(f"[green]Wrote {escape(str(out_path))}[/green]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
