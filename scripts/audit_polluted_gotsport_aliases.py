#!/usr/bin/env python3
"""Audit and quarantine GotSport team_alias_map rows polluted with registration IDs.

Some GotSport `team_alias_map` rows with `match_method='fuzzy_auto'` were
created by an earlier scraper bug that shipped per-event registration IDs as
`provider_team_id` when the canonical API team ID could not be resolved.
Registration IDs are not stable cross-event; treating them as canonical lets a
future event recycle the same numeric reg_id for a different team and silently
mis-route via the alias map.

This script validates each fuzzy_auto row's `provider_team_id` against the
GotSport JSON API at `/api/v1/teams/{id}/matches?past=true`:

    - 200 + match list contains row's `provider_team_id` as a `home_team_reg_id`
      or `away_team_reg_id` → `valid_api_id_self_match` (canonical, keep).
    - 200 + non-empty list with NO self-match → `valid_api_id_no_self_match`
      (suspect; default action: quarantine, override with --keep-no-self-match).
    - 200 + empty list → `ambiguous` (don't quarantine, log for manual review).
    - 404 → `registration_id` (quarantine candidate).
    - 5xx / network error / non-list JSON → `unknown_<reason>` (skip).

Quarantine action sets `review_status='pending'`. Rows are not deleted —
the audit trail and the master team mapping are preserved so a future operator
can either re-approve or merge.

Usage:
    python scripts/audit_polluted_gotsport_aliases.py                    # dry-run, all rows
    python scripts/audit_polluted_gotsport_aliases.py --limit 50         # dry-run, sample
    python scripts/audit_polluted_gotsport_aliases.py --apply            # mutate
    python scripts/audit_polluted_gotsport_aliases.py --apply --keep-no-self-match
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

import requests  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

# Module-level helper from the same scraper module so the audit doesn't need
# a full GotsportScraper instance (whose __init__ does a Supabase providers
# round-trip and other heavyweight setup).
from src.scrapers.gotsport import _zenrows_get  # noqa: E402
from supabase import create_client  # noqa: E402

# Load environment variables (mirrors maintain_gotsport_direct_id_aliases.py:30-34)
env_local = Path(".env.local")
if env_local.exists():
    load_dotenv(env_local, override=True)
else:
    load_dotenv()

supabase = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY"))


CSV_COLUMNS = (
    "id",
    "provider_id",
    "provider_team_id",
    "team_id_master",
    "match_method",
    "review_status",
    "api_status_code",
    "api_match_count",
    "self_match_found",
    "verdict",
    "decision_at",
)


def get_gotsport_provider_id() -> str:
    """Look up GotSport provider UUID from providers table."""
    result = supabase.table("providers").select("id").eq("code", "gotsport").execute()
    if not result.data:
        raise ValueError("GotSport provider not found in providers table")
    return result.data[0]["id"]


def fetch_fuzzy_auto_aliases(provider_id: str, limit: int | None) -> list[dict]:
    """Paginate through team_alias_map for the provider's fuzzy_auto + approved rows."""
    rows: list[dict] = []
    page_size = 1000
    offset = 0

    while True:
        result = (
            supabase.table("team_alias_map")
            .select("id,provider_id,provider_team_id,team_id_master,match_method,review_status")
            .eq("provider_id", provider_id)
            .eq("match_method", "fuzzy_auto")
            .eq("review_status", "approved")
            .not_.is_("provider_team_id", "null")
            .range(offset, offset + page_size - 1)
            .execute()
        )

        if not result.data:
            break
        rows.extend(result.data)
        if limit is not None and len(rows) >= limit:
            return rows[:limit]
        if len(result.data) < page_size:
            break
        offset += page_size

    return rows


def classify_alias(
    session: requests.Session,
    api_key: str | None,
    provider_team_id: str,
) -> tuple[int | None, int, bool, str]:
    """Validate a single alias against the GotSport API.

    Returns ``(api_status_code, api_match_count, self_match_found, verdict)``.
    Mirrors the resolver branches in src/scrapers/gotsport.py:_resolve_api_team_id_from_event_page.
    """
    api_url = f"https://system.gotsport.com/api/v1/teams/{provider_team_id}/matches?past=true"

    try:
        response = _zenrows_get(session, api_key, api_url, timeout=10, delay_min=0.1, delay_max=0.3)
    except requests.RequestException as e:
        return (None, 0, False, f"unknown_{type(e).__name__}")

    status = response.status_code
    if status == 404:
        return (status, 0, False, "registration_id")
    if status != 200:
        return (status, 0, False, f"unknown_status_{status}")

    try:
        body = response.json()
    except (ValueError, AttributeError):
        return (status, 0, False, "unknown_non_json_body")

    if not isinstance(body, list):
        return (status, 0, False, "unknown_non_list_body")

    if not body:
        return (status, 0, False, "ambiguous")

    # Self-match is on homeTeam.team_id / awayTeam.team_id (verified live
    # 2026-05-01 — the gotsport API endpoint only accepts api_team_ids and
    # always returns matches where the queried id is one of the teams).
    # Reg_id fields in the response are the per-match registration IDs of
    # both teams, NOT the queried team's reg_id.
    target = str(provider_team_id)
    self_match = False
    for match in body:
        if not isinstance(match, dict):
            continue
        home_tid = str((match.get("homeTeam") or {}).get("team_id"))
        away_tid = str((match.get("awayTeam") or {}).get("team_id"))
        if home_tid == target or away_tid == target:
            self_match = True
            break

    if self_match:
        return (status, len(body), True, "valid_api_id_self_match")
    return (status, len(body), False, "valid_api_id_no_self_match")


def write_csv(report_rows: list[dict], output_path: Path) -> None:
    """Write report to CSV with explicit column ordering."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for row in report_rows:
            writer.writerow({col: row.get(col, "") for col in CSV_COLUMNS})


def main(args: argparse.Namespace) -> None:
    print("=" * 80)
    print("GotSport Polluted Alias Audit")
    print("=" * 80)

    if not args.apply:
        print("\nDRY RUN MODE - No DB changes will be made (use --apply to mutate)\n")

    api_key = os.getenv("ZENROWS_API_KEY")
    if not api_key:
        print("WARNING: ZENROWS_API_KEY not set; calls will go direct to gotsport (risk of IP blocking)")

    provider_id = get_gotsport_provider_id()
    print(f"GotSport provider_id: {provider_id}")

    print("Fetching fuzzy_auto + approved aliases...")
    aliases = fetch_fuzzy_auto_aliases(provider_id, args.limit)
    print(f"Retrieved {len(aliases)} aliases for validation")

    if not aliases:
        print("\nNothing to audit.")
        write_csv([], Path(args.output or _default_output_path()))
        return

    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
            )
        }
    )

    decision_at = datetime.utcnow().isoformat() + "Z"
    report_rows: list[dict] = []
    for idx, alias in enumerate(aliases, start=1):
        provider_team_id = alias["provider_team_id"]
        status, match_count, self_match, verdict = classify_alias(session, api_key, provider_team_id)

        report_rows.append(
            {
                "id": alias["id"],
                "provider_id": alias["provider_id"],
                "provider_team_id": provider_team_id,
                "team_id_master": alias.get("team_id_master") or "",
                "match_method": alias["match_method"],
                "review_status": alias["review_status"],
                "api_status_code": status if status is not None else "",
                "api_match_count": match_count,
                "self_match_found": self_match,
                "verdict": verdict,
                "decision_at": decision_at,
            }
        )

        if idx % 50 == 0 or idx == len(aliases):
            print(f"  Validated {idx}/{len(aliases)}...")

    output_path = Path(args.output or _default_output_path())
    write_csv(report_rows, output_path)

    verdict_counts = Counter(row["verdict"] for row in report_rows)

    quarantine_verdicts = {"registration_id"}
    if not args.keep_no_self_match:
        quarantine_verdicts.add("valid_api_id_no_self_match")

    quarantine_candidates = [r for r in report_rows if r["verdict"] in quarantine_verdicts]

    print("\nVerdict counts:")
    for verdict, count in sorted(verdict_counts.items()):
        print(f"  {verdict:<35s} {count:>6d}")
    print(f"\nQuarantine candidates: {len(quarantine_candidates)}")
    print(f"Report CSV: {output_path}")

    if not args.apply:
        print("\nDRY RUN — no DB changes made. Re-run with --apply to mutate.")
        return

    if not quarantine_candidates:
        print("\nNothing to quarantine.")
        return

    print(f"\nUpdating {len(quarantine_candidates)} aliases to review_status='pending'...")
    updated_count = 0
    error_count = 0
    for row in quarantine_candidates:
        try:
            supabase.table("team_alias_map").update({"review_status": "pending"}).eq("id", row["id"]).execute()
            updated_count += 1
            if updated_count % 100 == 0:
                print(f"  Updated {updated_count}/{len(quarantine_candidates)}...")
        except Exception as e:
            print(f"  Error updating alias {row['id']}: {e}")
            error_count += 1

    print(f"\nUpdated {updated_count} aliases")
    if error_count:
        print(f"Errors: {error_count}")

    # Verification re-read (mirrors maintain_gotsport_direct_id_aliases.py:132-152)
    print("\nVerifying updates...")
    quarantined_ids = [row["id"] for row in quarantine_candidates]
    verified_review = 0
    for i in range(0, len(quarantined_ids), 100):
        batch = quarantined_ids[i : i + 100]
        verify_result = (
            supabase.table("team_alias_map").select("id,review_status").in_("id", batch).execute()
        )
        for record in verify_result.data or []:
            if record.get("review_status") == "pending":
                verified_review += 1

    print(f"Verified {verified_review}/{len(quarantine_candidates)} now have review_status='pending'")


def _default_output_path() -> str:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"data/exports/audit_polluted_gotsport_aliases_{timestamp}.csv"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Audit and quarantine polluted GotSport team_alias_map rows")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Mutate DB: set review_status='needs_review' on quarantine candidates. Default is dry-run.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Max rows to validate (for testing on a subset).",
    )
    parser.add_argument(
        "--keep-no-self-match",
        action="store_true",
        help=(
            "Do NOT quarantine rows with verdict='valid_api_id_no_self_match' (the suspect "
            "bucket). Default behavior quarantines them. Off-by-default flag for the "
            "operator who has independent evidence the no-self-match bucket is safe."
        ),
    )
    parser.add_argument(
        "--output",
        default=None,
        help=f"CSV output path. Default: {_default_output_path()}",
    )
    main(parser.parse_args())
