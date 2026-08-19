#!/usr/bin/env python3
"""
Revert merges executed by the weekly fuzzy auto-merge.

The 2026-08-19 data-hygiene run merged 1,772 pairs of distinct teams:
score_team_pair compares names with SequenceMatcher, and both
"unknown_781631" vs "unknown_781653" (0.929, shared placeholder prefix) and
"EPIC SC 2008 Dash" vs "EPIC SC 2009 Dash" (0.941 + 0.15 club match) clear the
0.90 auto-merge bar without being duplicates.

execute_team_merge records enough to undo itself: a full deprecated_team_snapshot
in team_merge_audit, and reverted_at/reverted_by/revert_reason columns. It leaves
games alone — merges resolve at read time through MergeResolver — so a revert is
three writes per merge:

  1. teams.is_deprecated back to FALSE (the merge set only that column)
  2. team_alias_map rows repointed from the canonical back to the deprecated team
  3. the team_merge_map row dropped, so MergeResolver stops redirecting

Reverts run newest-first. Three of the merges chained (a team absorbed others and
was then absorbed itself), and unwinding in reverse order restores those in the
right sequence.

Aliases are matched on the deprecated team's own (provider_id, provider_team_id)
from the snapshot. That is the alias games route through, and the only one for
the 1,567 merges that moved exactly one. Where the merge moved more than one, the
extras stay on the canonical and are reported as a shortfall rather than guessed.

Examples:
    python3 scripts/revert_fuzzy_auto_merges.py --dry-run
    python3 scripts/revert_fuzzy_auto_merges.py --dry-run --limit 20
    python3 scripts/revert_fuzzy_auto_merges.py --execute
"""

from __future__ import annotations

import argparse
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from dotenv import load_dotenv

from supabase import create_client

RUN_START_DEFAULT = "2026-08-19T02:40:00"
MERGED_BY = "pitchrank-bot"
REVERT_REASON = "fuzzy auto-merge scored distinct teams as duplicates (unknown_ prefix / birth year)"


def log(message: str) -> None:
    print(message, flush=True)


def load_env() -> None:
    env_local = Path(".env.local")
    if env_local.exists():
        load_dotenv(env_local, override=True)
    else:
        load_dotenv()


def get_supabase():
    supabase_url = os.getenv("SUPABASE_URL") or os.getenv("NEXT_PUBLIC_SUPABASE_URL")
    supabase_key = (
        os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_SERVICE_KEY") or os.getenv("SUPABASE_KEY")
    )
    if not supabase_url or not supabase_key:
        raise ValueError("Missing Supabase credentials. Need SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY.")
    return create_client(supabase_url, supabase_key)


def is_placeholder(team_name: Optional[str], provider_team_id: Optional[str]) -> bool:
    """True when the name is the unknown_<provider_team_id> fallback and nothing more."""
    name = (team_name or "").strip()
    pid = str(provider_team_id or "").strip()
    if not name or not pid:
        return False
    return name.lower() == f"unknown_{pid}".lower()


def keep_placeholder_pairs(supabase, rows: List[Dict]) -> List[Dict]:
    """Keep only merges where both sides were unknown_<pid> placeholders.

    Two placeholders carry no identifying information, so a similarity score
    between them only ever reflects their shared prefix and adjacent provider
    IDs — such a pair is never a known duplicate. The canonical side is read
    live rather than from a snapshot (only the deprecated side is snapshotted);
    a canonical since renamed by the backfill therefore drops out, which is the
    conservative direction.
    """
    deprecated_side = [
        r
        for r in rows
        if is_placeholder(
            (r.get("deprecated_team_snapshot") or {}).get("team_name"),
            (r.get("deprecated_team_snapshot") or {}).get("provider_team_id"),
        )
    ]
    if not deprecated_side:
        return []

    canonical_ids = sorted({r["canonical_team_id"] for r in deprecated_side})
    canonical: Dict[str, Dict] = {}
    for i in range(0, len(canonical_ids), 100):
        batch = (
            supabase.table("teams")
            .select("team_id_master,team_name,provider_team_id")
            .in_("team_id_master", canonical_ids[i : i + 100])
            .execute()
            .data
            or []
        )
        for team in batch:
            canonical[team["team_id_master"]] = team

    return [
        r
        for r in deprecated_side
        if is_placeholder(
            (canonical.get(r["canonical_team_id"]) or {}).get("team_name"),
            (canonical.get(r["canonical_team_id"]) or {}).get("provider_team_id"),
        )
    ]


def fetch_merges_to_revert(
    supabase,
    since: Optional[str],
    merged_by: str,
    limit: Optional[int],
    placeholders_only: bool,
) -> List[Dict]:
    """Un-reverted 'merge' audit rows, newest first so chained merges unwind in order."""
    rows: List[Dict] = []
    offset = 0
    page_size = 1000

    while True:
        query = (
            supabase.table("team_merge_audit")
            .select(
                "id,deprecated_team_id,canonical_team_id,aliases_updated,performed_at,deprecated_team_snapshot"
            )
            .eq("action", "merge")
            .eq("performed_by", merged_by)
            .is_("reverted_at", "null")
        )
        if since:
            query = query.gte("performed_at", since)
        batch = query.order("performed_at", desc=True).range(offset, offset + page_size - 1).execute().data or []
        if not batch:
            break
        rows.extend(batch)
        # The placeholder filter runs after paging, so --limit cannot short-circuit here.
        if limit and not placeholders_only and len(rows) >= limit:
            return rows[:limit]
        if len(batch) < page_size:
            break
        offset += page_size

    if placeholders_only:
        rows = keep_placeholder_pairs(supabase, rows)

    return rows[:limit] if limit else rows


def revert_one(supabase, audit: Dict, execute: bool) -> Dict:
    """Undo a single merge. Returns counts for reporting."""
    deprecated_id = audit["deprecated_team_id"]
    canonical_id = audit["canonical_team_id"]
    snapshot = audit.get("deprecated_team_snapshot") or {}
    provider_id = snapshot.get("provider_id")
    provider_team_id = snapshot.get("provider_team_id")
    expected_aliases = audit.get("aliases_updated") or 0

    aliases = []
    if provider_id and provider_team_id:
        aliases = (
            supabase.table("team_alias_map")
            .select("id")
            .eq("team_id_master", canonical_id)
            .eq("provider_id", provider_id)
            .eq("provider_team_id", provider_team_id)
            .execute()
            .data
            or []
        )

    if not execute:
        return {"aliases_found": len(aliases), "expected_aliases": expected_aliases, "ok": True}

    supabase.table("teams").update({"is_deprecated": False}).eq("team_id_master", deprecated_id).execute()

    for alias in aliases:
        supabase.table("team_alias_map").update({"team_id_master": deprecated_id}).eq("id", alias["id"]).execute()

    supabase.table("team_merge_map").delete().eq("deprecated_team_id", deprecated_id).execute()

    supabase.table("team_merge_audit").update(
        {
            "reverted_at": datetime.now(timezone.utc).isoformat(),
            "reverted_by": "revert_fuzzy_auto_merges",
            "revert_reason": REVERT_REASON,
        }
    ).eq("id", audit["id"]).execute()

    return {"aliases_found": len(aliases), "expected_aliases": expected_aliases, "ok": True}


def main() -> None:
    parser = argparse.ArgumentParser(description="Revert the weekly fuzzy auto-merge's bad merges")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing (default unless --execute)")
    parser.add_argument("--execute", action="store_true", help="Apply the reverts")
    parser.add_argument(
        "--since",
        default=RUN_START_DEFAULT,
        help=f"Audit rows at/after this time (default: {RUN_START_DEFAULT}). Pass '' for all history.",
    )
    parser.add_argument(
        "--placeholders-only",
        action="store_true",
        help="Only revert merges where BOTH sides were unknown_<provider_team_id> placeholders",
    )
    parser.add_argument(
        "--merged-by",
        default=MERGED_BY,
        help=f"Only revert merges by this actor (default: {MERGED_BY})",
    )
    parser.add_argument("--limit", type=int, default=None, help="Max merges to revert (default: all)")
    args = parser.parse_args()

    execute = args.execute and not args.dry_run

    load_env()
    supabase = get_supabase()

    merges = fetch_merges_to_revert(supabase, args.since, args.merged_by, args.limit, args.placeholders_only)
    if not merges:
        log("No un-reverted merges match.")
        return

    log(f"=== Revert Fuzzy Auto-Merges ({'LIVE' if execute else 'DRY RUN'}) ===")
    window = f"at/after {args.since}" if args.since else "across all history"
    scope = " (both sides placeholders)" if args.placeholders_only else ""
    log(f"{len(merges):,} merges by {args.merged_by} {window}{scope}, newest first")
    log("")

    reverted = 0
    errors = 0
    alias_shortfall = 0
    no_snapshot = 0

    for i, audit in enumerate(merges, start=1):
        snapshot = audit.get("deprecated_team_snapshot") or {}
        name = snapshot.get("team_name") or "(no snapshot)"
        if not snapshot:
            no_snapshot += 1

        try:
            result = revert_one(supabase, audit, execute)
        except Exception as e:
            errors += 1
            log(f"  ERROR reverting {audit['deprecated_team_id']}: {e}")
            continue

        reverted += 1
        if result["aliases_found"] < result["expected_aliases"]:
            alias_shortfall += 1

        if reverted <= 15 or reverted % 250 == 0:
            prefix = "  [DRY-RUN] " if not execute else "  "
            log(f"{prefix}restore {name[:44]:<44} aliases {result['aliases_found']}/{result['expected_aliases']}")
        if i % 500 == 0:
            log(f"  Progress: {i}/{len(merges)}...")

    log("")
    log("=== Summary ===")
    log(f"Reverted: {reverted:,}")
    log(f"Errors: {errors:,}")
    log(f"Merges whose extra aliases stayed on the canonical: {alias_shortfall:,}")
    if no_snapshot:
        log(f"Merges with no snapshot (teams row left as-is): {no_snapshot:,}")
    if not execute:
        log("")
        log("DRY RUN — nothing written. Re-run with --execute to apply.")


if __name__ == "__main__":
    main()
