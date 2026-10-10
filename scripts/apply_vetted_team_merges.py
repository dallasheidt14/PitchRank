#!/usr/bin/env python3
"""Apply a hand-vetted list of team merges via the execute_team_merge RPC.

This is an operator tool, not part of any scheduled job. It takes an explicit list of
(deprecated, canonical) pairs that have already been checked, and applies exactly those --
it does no matching of its own. That separation is deliberate: the weekly Step 3 scan
decides *which* pairs to propose, and this script only carries out a decision already made.

A merge is three writes -- a team_merge_map row, a team_alias_map repoint, and
teams.is_deprecated = TRUE -- plus a full snapshot in team_merge_audit. Game rows are never
rewritten; they resolve to the surviving team at read time through team_merge_map. That makes
a merge reversible via scripts/revert_fuzzy_auto_merges.py.

It refuses a pair the owner chose Keep separate, read from team_cleanup_decisions with both
teams resolved through team_merge_map and through the merges this run plans before it, and will
not run at all while that table cannot be read.
It also refuses a pair whose age group, gender, state or club no longer matches what the list
recorded when it was built, or that does not record them in full, checking again immediately
before each merge.

Usage:
    python scripts/apply_vetted_team_merges.py --file merges.json            # dry run
    python scripts/apply_vetted_team_merges.py --file merges.json --execute
    python scripts/apply_vetted_team_merges.py --file merges.json --execute --limit 10
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Root .env holds the keys on a local checkout and .env.local overrides it where one exists; CI
# supplies the environment directly.
load_dotenv(ROOT / ".env")
load_dotenv(ROOT / ".env.local", override=True)

from scripts.find_cross_provider_duplicates import (  # noqa: E402
    batched,
    load_keep_separate,
    load_merge_map,
    resolver,
)
from scripts.team_cleanup.decisions import (  # noqa: E402
    MERGES_WAIT_FOR_DECISIONS,
    DecisionsUnavailable,
    keep_separate_index,
    kept_apart_reason,
)
from scripts.team_cleanup.vetted import IDENTITY_FIELDS, changed_since_vetted  # noqa: E402
from supabase import create_client  # noqa: E402

MERGED_BY = "pitchrank-operator"
MERGE_REASON = "Vetted duplicate: same birth year, schedules consistent with one squad"
LIVE_COLS = ",".join(("team_id_master", "is_deprecated", "team_name", *IDENTITY_FIELDS))


def get_client():
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY")
    if not url or not key:
        raise SystemExit("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set")
    return create_client(url, key)


def order_for_cascades(pairs: list[dict]) -> list[dict]:
    """Order so a team receives its merges before it is itself merged away.

    A chain A->B, B->C must run in that order. execute_team_merge cascades merge_map rows
    pointing at B when B is later deprecated, but the reverse order asks it to merge into a
    row that is already deprecated.
    """
    survivors = defaultdict(list)
    for p in pairs:
        survivors[p["keep_id"]].append(p)

    ordered: list[dict] = []
    seen: set[int] = set()

    def emit(p: dict) -> None:
        key = id(p)
        if key in seen:
            return
        seen.add(key)
        # anything merging INTO this pair's deprecated team must happen first
        for earlier in survivors.get(p["merge_id"], []):
            emit(earlier)
        ordered.append(p)

    for p in pairs:
        emit(p)
    return ordered


def resolve_through_merge_map(pairs: list[dict], canonical) -> list[dict]:
    """Rewrite both sides of every pair to their current canonical team.

    A vetted list ages: between vetting and applying, an operator may merge one of the named
    teams somewhere else. Following team_merge_map first means a pair still points at whatever
    that team has become, instead of failing on a row that is now deprecated. This is the same
    rule the rest of the codebase follows via MergeResolver. A redirected side is then checked
    against the row it now names, so the pair is refused unless that row carries the age group,
    gender, state and club the list recorded for the team it replaced.
    """
    out = []
    for p in pairs:
        q = dict(p)
        q["merge_id"] = canonical(p["merge_id"])
        q["keep_id"] = canonical(p["keep_id"])
        if q["merge_id"] != p["merge_id"] or q["keep_id"] != p["keep_id"]:
            q["_redirected"] = True
        out.append(q)
    return out


def drop_conflicting(pairs: list[dict]) -> tuple[list[dict], list[dict]]:
    """Keep one merge per deprecated team.

    A team can only be merged into a single canonical. Two pairs naming the same deprecated
    team disagree about where it belongs, so neither is safe to guess at -- both are dropped
    for a human rather than silently resolved by ordering.
    """
    by_dep = defaultdict(list)
    for p in pairs:
        by_dep[p["merge_id"]].append(p)
    keep, dropped = [], []
    for rows in by_dep.values():
        if len(rows) == 1:
            keep.append(rows[0])
        else:
            dropped.extend(rows)
    return keep, dropped


def without_kept_apart(pairs: list[dict], keep_separate, merge_map: dict[str, str]):
    """Split the pairs, in order, into those that can merge and those, each with a reason, that
    would join two teams the owner kept apart.

    Each merge let through is added to a copy of the merge map before the next pair is checked, so two
    merges that would together put a kept-apart pair on one row -- A and C both into B, or A into
    B and B into C -- are caught at the second.
    """
    planned = dict(merge_map)
    allowed, refused = [], []
    for p in pairs:
        canonical = resolver(planned)
        index = keep_separate_index(keep_separate, canonical)
        reason = kept_apart_reason(index, canonical, p["merge_id"], p["keep_id"])
        if reason:
            refused.append((p, reason))
            continue
        planned[p["merge_id"]] = p["keep_id"]
        allowed.append(p)
    return allowed, refused


def fetch_live(sb, ids: list[str]) -> dict[str, dict]:
    live = {}
    for batch in batched(ids):
        for t in sb.table("teams").select(LIVE_COLS).in_("team_id_master", batch).execute().data or []:
            live[t["team_id_master"]] = t
    return live


def missing_or_deprecated(pair: dict, live: dict[str, dict]) -> bool:
    rows = (live.get(pair["merge_id"]), live.get(pair["keep_id"]))
    return any(row is None or row["is_deprecated"] for row in rows)


def refusal(pair: dict, live: dict[str, dict]) -> str | None:
    """Why a pair must not merge, read against its two rows as they stand now."""
    if missing_or_deprecated(pair, live):
        return "a row is missing or already deprecated"
    return changed_since_vetted(pair, live[pair["merge_id"]], live[pair["keep_id"]])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument(
        "--file",
        required=True,
        help="JSON array with merge_id, keep_id, merge_name, keep_name, merge_as_vetted, keep_as_vetted",
    )
    ap.add_argument("--execute", action="store_true", help="apply the merges (default is a dry run)")
    ap.add_argument("--limit", type=int, default=None, help="apply at most N merges")
    ap.add_argument("--out", default=None, help="where to write the result log (default alongside --file)")
    args = ap.parse_args()

    pairs = json.loads(Path(args.file).read_text(encoding="utf-8"))
    if not isinstance(pairs, list):
        raise SystemExit(f"{args.file} holds no list of pairs; pass a list such as a scan's proposals JSON")
    print(f"loaded {len(pairs)} pairs from {args.file}")

    sb = get_client()
    merge_map = load_merge_map(sb)
    canonical = resolver(merge_map)
    try:
        keep_separate = load_keep_separate(sb)
    except DecisionsUnavailable as exc:
        raise SystemExit(f"{exc}\n{MERGES_WAIT_FOR_DECISIONS}") from exc

    pairs = resolve_through_merge_map(pairs, canonical)
    redirected = [p for p in pairs if p.get("_redirected")]
    for p in redirected:
        print(f"  redirected through an existing merge: {p['merge_name']!r} -> {p['keep_name']!r}")

    # A pair whose two sides now resolve to the same team is already done.
    already = [p for p in pairs if p["merge_id"] == p["keep_id"]]
    pairs = [p for p in pairs if p["merge_id"] != p["keep_id"]]
    for p in already:
        print(f"  already merged, skipping: {p['merge_name']!r} -> {p['keep_name']!r}")

    # Redirection can collapse two pairs onto one; keep a single copy, preferring one that was not
    # redirected, since only its recorded values describe the rows it names.
    deduped: dict[tuple[str, str], dict] = {}
    for p in pairs:
        key = (p["merge_id"], p["keep_id"])
        if key not in deduped:
            deduped[key] = p
            continue
        dropped = p
        if deduped[key].get("_redirected") and not p.get("_redirected"):
            dropped, deduped[key] = deduped[key], p
        print(f"  duplicate of another pair, skipping: {dropped['merge_name']!r} -> {dropped['keep_name']!r}")
    pairs = list(deduped.values())

    pairs, conflicting = drop_conflicting(pairs)
    for p in conflicting:
        print(f"  SKIP (deprecated team claimed by two merges): {p['merge_name']!r} -> {p['keep_name']!r}")
    if conflicting:
        print(f"  dropped {len(conflicting)} conflicting pairs\n")

    pairs, kept_apart = without_kept_apart(order_for_cascades(pairs), keep_separate, merge_map)
    for p, reason in kept_apart:
        print(f"  SKIP ({reason}): {p['merge_name']!r} -> {p['keep_name']!r}")

    if args.limit:
        pairs = pairs[: args.limit]

    # Refuse to run against a list that has gone stale since it was vetted.
    ids = sorted({p["merge_id"] for p in pairs} | {p["keep_id"] for p in pairs})
    live = fetch_live(sb, ids)
    stale = [p for p in pairs if missing_or_deprecated(p, live)]
    if stale:
        print(f"REFUSING: {len(stale)} pairs are stale (row missing or already deprecated).")
        for p in stale[:10]:
            print(f"   {p['merge_name']!r} -> {p['keep_name']!r}")
        print("Re-vet the list against current data before applying.")
        return 1

    unchanged = []
    for p in pairs:
        reason = refusal(p, live)
        if reason:
            print(f"  SKIP ({reason}): {p['merge_name']!r} -> {p['keep_name']!r}")
        else:
            unchanged.append(p)
    pairs = unchanged

    if not args.execute:
        print(f"\nDRY RUN — would merge {len(pairs)} pairs. Nothing was written.")
        for p in pairs[:15]:
            print(f"   {p['merge_name'][:46]!r} -> {p['keep_name'][:46]!r}")
        if len(pairs) > 15:
            print(f"   ... and {len(pairs) - 15} more")
        print("\nRe-run with --execute to apply.")
        return 0

    print(f"\nApplying {len(pairs)} merges...")
    log, ok, failed, refused = [], 0, 0, 0
    for i, p in enumerate(pairs, 1):
        try:
            reason = refusal(p, fetch_live(sb, [p["merge_id"], p["keep_id"]]))
        except Exception as exc:  # noqa: BLE001
            reason = f"its rows could not be read again: {str(exc)[:110]}"
        if reason:
            refused += 1
            print(f"  SKIP ({reason}): {p['merge_name'][:40]!r} -> {p['keep_name'][:40]!r}")
            continue
        try:
            res = sb.rpc("execute_team_merge", {
                "p_deprecated_team_id": p["merge_id"],
                "p_canonical_team_id": p["keep_id"],
                "p_merged_by": MERGED_BY,
                "p_merge_reason": MERGE_REASON,
            }).execute()
            data = res.data if isinstance(res.data, dict) else {"success": bool(res.data)}
        except Exception as exc:  # noqa: BLE001
            # The RPC's success payload carries a `message` key, which postgrest-py reads
            # as an API error, so a committed merge raises "JSON could not be generated"
            # with the real payload in the exception text. run_all_merges.execute_merge
            # carries the same workaround; treating the exception as a failure reports
            # every successful merge as failed and leaves the log unusable for a revert.
            text = str(exc)
            if '"success": true' in text or "'success': True" in text:
                data = {"success": True, "note": "recovered from postgrest-py's message-key error"}
            else:
                data = {"success": False, "error": text[:300]}

        if data.get("success"):
            ok += 1
        else:
            failed += 1
            print(f"  FAILED {p['merge_name'][:40]!r} -> {p['keep_name'][:40]!r}: {str(data.get('error'))[:110]}")
        log.append({**{k: p.get(k) for k in ("merge_id", "keep_id", "merge_name", "keep_name")}, "result": data})
        if i % 25 == 0:
            print(f"  {i}/{len(pairs)}  ({ok} ok, {failed} failed)")

    out = Path(args.out) if args.out else Path(args.file).with_name(
        f"merge_results_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.json")
    out.write_text(json.dumps(log, indent=1), encoding="utf-8")
    print(f"\nDone: {ok} merged, {failed} failed, {refused} refused by the check before each merge. Log: {out}")
    print(f"To undo: scripts/revert_fuzzy_auto_merges.py --dry-run --since <today> --merged-by {MERGED_BY}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
