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
import re
import sys
import unicodedata
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

from dotenv import load_dotenv
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from src.tournaments.gotsport_event_roster import (
    WafChallengeError,
    make_zenrows_fetcher,
    scrape_event_roster,
)
from src.tournaments.roster_resolver import make_provider_id_lookup
from src.tournaments.storage._io import write_json
from src.utils.merge_resolver import MergeResolver
from supabase import create_client

console = Console()
_ENV_LOCAL = Path(__file__).resolve().parent.parent / ".env.local"
if _ENV_LOCAL.exists():
    load_dotenv(_ENV_LOCAL, override=True)
else:
    load_dotenv()

# Both patterns refuse a longer token rather than taking a valid prefix of it:
# `/events/1234567890123` must not scrape event 123456789012 and write it under
# that event's path. `\Z` rather than `$`, which would accept a trailing newline.
_EVENT_ID_IN_URL = re.compile(r"/events/([0-9]{1,12})(?![0-9])")
_EVENT_ID = re.compile(r"^[0-9]{1,12}\Z")


_KEPT_CONTROLS = frozenset({chr(9), chr(10)})
# Zl/Zp are the line and paragraph separators: legal JSON under
# ensure_ascii=False, and a break in every JavaScript consumer that reads it.
_STRIPPED_CATEGORIES = frozenset({"Cc", "Cf", "Co", "Cs", "Zl", "Zp"})


def _printable(text: str) -> str:
    """Strip terminal control sequences out of provider-authored text.

    ``rich.markup.escape`` neutralises ``[`` but not ESC, and rich's own
    control-code filter does not cover it either, so a division or team name
    carrying ``&#x1B;`` reaches the operator's terminal live — and is written
    into a roster under ``reports/``, which this repository does not gitignore,
    where a later ``cat`` fires it again. Bidi and zero-width formats matter
    for the same reason one step further out: they survive into the JSON and
    reverse or hide a name in every viewer that renders it.

    Decided by Unicode category rather than by a list of ranges, because a list
    is what let U+061C, U+FEFF and the Tags block through while naming exactly
    the class they belong to. Letters, marks, punctuation, symbols and spaces
    all pass, so accented names, emoji and combining marks are untouched; tab
    and newline are kept deliberately.
    """
    return "".join(
        ch
        for ch in str(text or "")
        if ch in _KEPT_CONTROLS or unicodedata.category(ch) not in _STRIPPED_CATEGORIES
    )


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


def _redact(exc: Exception, secret: str) -> str:
    """Never let a credential reach the roster file through an error message.

    Replaces the whole value and each of its whitespace-separated runs. A key
    soft-wrapped in ``.env.local`` comes back carrying an internal newline, and
    ``h11`` formats the offending header with ``{!r}`` — so the value never
    appears whole, but a 41-character run of it does, and deleting the escape
    recovers the key exactly. That shape is self-triggering: the wrapped key is
    both what leaks and what caused the request to fail.

    ``SUPABASE_URL`` is deliberately not redacted. It is public by construction
    — the same value ships to browsers as ``NEXT_PUBLIC_SUPABASE_URL`` — and
    hiding it removes the one detail telling an operator which project failed.
    """
    text = str(exc)
    runs = sorted((run for run in secret.split() if len(run) >= 8), key=len, reverse=True)
    for form in (secret, secret.strip(), *runs):
        if form:
            text = text.replace(form, "REDACTED")
    return text


def _event_id_from(args: argparse.Namespace) -> str:
    """Read the event id, refusing anything that is not a bare number.

    The id becomes a path segment under ``reports/``, so an unvalidated value
    lets ``../`` escape the directory the roster is meant to live in.
    """
    if args.event_id:
        if not _EVENT_ID.match(args.event_id):
            raise SystemExit(f"Not a GotSport event id: {args.event_id}")
        return args.event_id

    match = _EVENT_ID_IN_URL.search(args.event_url or "")
    if not match:
        raise SystemExit(f"Could not read an event id from: {args.event_url}")
    return match.group(1)


def _resolve_master_ids(
    teams,
    *,
    enabled: bool,
    client_factory=create_client,
    resolver_factory=MergeResolver,
    lookup_factory=make_provider_id_lookup,
) -> tuple[dict[str, str], list[str]]:
    """Map each scraped provider id to our canonical team id.

    Returns the mapping and any warnings. A database failure here must not cost
    the walk: the roster is the paid artifact, and re-running resolution is free
    where re-running the scrape is not.

    The three collaborators are injectable so each arm — including the one that
    redacts a credential out of a failure message — can be driven without a
    database. A redactor tested only as a pure function does not prove it is
    actually called here.
    """
    provider_ids = [team.provider_team_id for team in teams if team.provider_team_id]
    if not enabled or not provider_ids:
        return {}, []

    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY")
    if not (url and key):
        return {}, ["No Supabase credentials; provider ids were not resolved to PitchRank teams"]

    warnings: list[str] = []
    try:
        supabase = client_factory(url, key)
        merge_resolver = resolver_factory(supabase)
        merge_resolver.load_merge_map()
        if getattr(merge_resolver, "version", None) == "error":
            # load_merge_map catches its own exceptions and returns normally, so
            # this is the only signal that merges were not applied. Without it a
            # team_id_master that was merged away is reported as resolved.
            warnings.append(
                "Merge map failed to load; ids were resolved without merge resolution "
                "and may name deprecated teams"
            )
        lookup = lookup_factory(supabase, merge_resolver)

        resolved = {}
        for provider_id in dict.fromkeys(provider_ids):
            master_id = lookup(provider_id)
            if master_id:
                resolved[provider_id] = master_id
        return resolved, warnings
    except Exception as exc:
        # This message is written into reports/, which is not gitignored, in a
        # public repo — and a key with a stray newline makes httpx raise
        # `Illegal header value b'<the key>'`, putting the key in the text.
        return {}, [
            f"Master-id resolution failed, roster kept without it: {_redact(exc, key)}"
        ]


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
            escape(_printable(label) or "—"),
            cohort,
            str(len(rows)),
            str(len(with_id)),
            str(len(resolved)),
        )
    return table


def _write_roster(out_path: Path, payload: dict, *, force: bool) -> None:
    """Write the roster, refusing to replace a complete one with a partial one.

    A limited or blocked run targets the same filename as a full one, so
    without this an operator pricing an event with ``--limit-groups`` — or a
    walk that hit a bot challenge — silently overwrites the provider ids a
    full walk already paid for. An unreadable existing file is treated as
    absent rather than aborting, because the run's own result is the thing
    that cost money.
    """
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
    parser.add_argument("--force", action="store_true", help="Replace a complete roster anyway")
    parser.add_argument("--dry-run", action="store_true", help="Scrape and report, write nothing")
    args = parser.parse_args()

    api_key = os.getenv("ZENROWS_API_KEY")
    if not api_key:
        raise SystemExit("ZENROWS_API_KEY is required — these pages are WAF-gated.")

    event_id = _event_id_from(args)
    out_path = Path(args.out or f"reports/seeding/gotsport_{event_id}/roster.json")

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
        )
    except WafChallengeError as exc:
        raise SystemExit(f"Blocked: {exc}") from exc
    except RuntimeError as exc:
        # Only the landing-page fetch can end the walk; division and team pages
        # degrade to warnings. Exit like the missing-key check, not with a traceback.
        raise SystemExit(f"Could not read event {event_id}: {exc}") from exc

    master_ids, resolve_warnings = _resolve_master_ids(roster.teams, enabled=not args.no_resolve)
    warnings = list(roster.warnings) + resolve_warnings
    with_id = [team for team in roster.teams if team.provider_team_id]
    resolved = [team for team in with_id if team.provider_team_id in master_ids]

    console.print()
    console.print(_summary_table(roster.teams, master_ids))
    console.print(
        f"[bold]{len(roster.teams)}[/bold] teams, "
        f"[bold]{len(with_id)}[/bold] with a provider id, "
        f"[bold]{len(resolved)}[/bold] resolved to a PitchRank team"
    )
    if not roster.is_complete:
        console.print("[yellow]Partial walk — this roster is not the whole event[/yellow]")
    for warning in warnings:
        console.print(f"[yellow]{escape(_printable(warning))}[/yellow]")

    payload = {
        "event_id": roster.event_id,
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "is_complete": roster.is_complete,
        "divisions_found": roster.divisions_found,
        "divisions_walked": roster.divisions_walked,
        "divisions_unreadable": roster.divisions_unreadable,
        "teams_unreadable": roster.teams_unreadable,
        "warnings": [_printable(warning) for warning in warnings],
        "teams": [
            asdict(team)
            | {
                "division_label": _printable(team.division_label),
                "team_name": _printable(team.team_name),
                "team_id_master": master_ids.get(team.provider_team_id or ""),
            }
            for team in roster.teams
        ],
    }

    if args.dry_run:
        console.print(f"[yellow]DRY RUN — would write {escape(str(out_path))}[/yellow]")
        return 0

    _write_roster(out_path, payload, force=args.force)
    console.print(f"[green]Wrote {escape(str(out_path))}[/green]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
