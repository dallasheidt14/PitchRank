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

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Scripts here are run from the repo root and from GitHub Actions; .env.local holds the
# service-role key locally while CI supplies the environment directly. A bare load_dotenv()
# finds .env and comes back empty, so the path is explicit.
load_dotenv(Path(__file__).resolve().parent.parent / ".env.local")

from supabase import create_client  # noqa: E402

MERGED_BY = "pitchrank-operator"
MERGE_REASON = "Vetted duplicate: same birth year, schedules consistent with one squad"


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


def resolve_through_merge_map(sb, pairs: list[dict]) -> list[dict]:
    """Rewrite both sides of every pair to their current canonical team.

    A vetted list ages: between vetting and applying, an operator may merge one of the named
    teams somewhere else. Following team_merge_map first means a pair still points at whatever
    that team has become, instead of failing on a row that is now deprecated. This is the same
    rule the rest of the codebase follows via MergeResolver.
    """
    mapping: dict[str, str] = {}
    page = 0
    while True:
        res = (
            sb.table("team_merge_map")
            .select("deprecated_team_id,canonical_team_id")
            .range(page * 1000, page * 1000 + 999)
            .execute()
        )
        rows = res.data or []
        for r in rows:
            mapping[r["deprecated_team_id"]] = r["canonical_team_id"]
        if len(rows) < 1000:
            break
        page += 1

    def canonical(tid: str) -> str:
        seen = set()
        while tid in mapping and tid not in seen:
            seen.add(tid)
            tid = mapping[tid]
        return tid

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


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--file", required=True, help="JSON array with merge_id, keep_id, merge_name, keep_name")
    ap.add_argument("--execute", action="store_true", help="apply the merges (default is a dry run)")
    ap.add_argument("--limit", type=int, default=None, help="apply at most N merges")
    ap.add_argument("--out", default=None, help="where to write the result log (default alongside --file)")
    args = ap.parse_args()

    pairs = json.loads(Path(args.file).read_text(encoding="utf-8"))
    print(f"loaded {len(pairs)} pairs from {args.file}")

    sb = get_client()

    pairs = resolve_through_merge_map(sb, pairs)
    redirected = [p for p in pairs if p.get("_redirected")]
    for p in redirected:
        print(f"  redirected through an existing merge: {p['merge_name']!r} -> {p['keep_name']!r}")

    # A pair whose two sides now resolve to the same team is already done.
    already = [p for p in pairs if p["merge_id"] == p["keep_id"]]
    pairs = [p for p in pairs if p["merge_id"] != p["keep_id"]]
    for p in already:
        print(f"  already merged, skipping: {p['merge_name']!r} -> {p['keep_name']!r}")

    # Redirection can collapse two pairs onto one; keep a single copy.
    seen_pairs: set[tuple[str, str]] = set()
    deduped = []
    for p in pairs:
        key = (p["merge_id"], p["keep_id"])
        if key in seen_pairs:
            print(f"  duplicate of another pair, skipping: {p['merge_name']!r} -> {p['keep_name']!r}")
            continue
        seen_pairs.add(key)
        deduped.append(p)
    pairs = deduped

    pairs, conflicting = drop_conflicting(pairs)
    for p in conflicting:
        print(f"  SKIP (deprecated team claimed by two merges): {p['merge_name']!r} -> {p['keep_name']!r}")
    if conflicting:
        print(f"  dropped {len(conflicting)} conflicting pairs\n")

    pairs = order_for_cascades(pairs)
    if args.limit:
        pairs = pairs[: args.limit]

    # Refuse to run against a list that has gone stale since it was vetted.
    ids = sorted({p["merge_id"] for p in pairs} | {p["keep_id"] for p in pairs})
    live = {}
    for i in range(0, len(ids), 100):
        res = (
            sb.table("teams")
            .select("team_id_master,is_deprecated,team_name")
            .in_("team_id_master", ids[i : i + 100])
            .execute()
        )
        for t in res.data or []:
            live[t["team_id_master"]] = t
    stale = [p for p in pairs
             if p["merge_id"] not in live or p["keep_id"] not in live
             or live[p["merge_id"]]["is_deprecated"] or live[p["keep_id"]]["is_deprecated"]]
    if stale:
        print(f"REFUSING: {len(stale)} pairs are stale (row missing or already deprecated).")
        for p in stale[:10]:
            print(f"   {p['merge_name']!r} -> {p['keep_name']!r}")
        print("Re-vet the list against current data before applying.")
        return 1

    if not args.execute:
        print(f"\nDRY RUN — would merge {len(pairs)} pairs. Nothing was written.")
        for p in pairs[:15]:
            print(f"   {p['merge_name'][:46]!r} -> {p['keep_name'][:46]!r}")
        if len(pairs) > 15:
            print(f"   ... and {len(pairs) - 15} more")
        print("\nRe-run with --execute to apply.")
        return 0

    print(f"\nApplying {len(pairs)} merges...")
    log, ok, failed = [], 0, 0
    for i, p in enumerate(pairs, 1):
        try:
            res = sb.rpc("execute_team_merge", {
                "p_deprecated_team_id": p["merge_id"],
                "p_canonical_team_id": p["keep_id"],
                "p_merged_by": MERGED_BY,
                "p_merge_reason": MERGE_REASON,
            }).execute()
            data = res.data if isinstance(res.data, dict) else {"success": bool(res.data)}
        except Exception as exc:  # noqa: BLE001
            # PostgREST cannot serialise this RPC's JSONB return and raises
            # "JSON could not be generated" even when the merge committed -- the real
            # payload is embedded in the exception text. run_all_merges.execute_merge
            # carries the same workaround; treating the exception as a failure reports
            # every successful merge as failed and leaves the log unusable for a revert.
            text = str(exc)
            if '"success": true' in text or "'success': True" in text:
                data = {"success": True, "note": "recovered from PostgREST serialisation error"}
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
    print(f"\nDone: {ok} merged, {failed} failed. Log: {out}")
    print("To undo: scripts/revert_fuzzy_auto_merges.py --dry-run --since <today>")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
