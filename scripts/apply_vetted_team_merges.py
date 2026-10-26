#!/usr/bin/env python3
"""Apply a hand-vetted list of team merges via the execute_team_merge RPC.

This is an operator tool, not part of any scheduled job. It takes an explicit list of
(deprecated, canonical) pairs that have already been checked, and applies exactly those --
it does no matching of its own. That separation is deliberate: the weekly Step 3 scan
decides *which* pairs to propose, and this script only carries out a decision already made.

A merge is four writes -- the team_merge_map rows retiring other teams into the retired one
repointed to the survivor, its own team_merge_map row, a team_alias_map repoint, and
teams.is_deprecated = TRUE -- plus a full snapshot in team_merge_audit. Game rows are never
rewritten; they resolve to the surviving team at read time through team_merge_map. That makes
a merge reversible.

It refuses a pair the owner chose Keep separate, read from team_cleanup_decisions with both
teams resolved through team_merge_map and through the merges this run plans before it, and will
not run at all while that table cannot be read.
It also refuses a pair whose age group, gender, state or club no longer matches what the list
recorded when it was built, or that does not record them in full, checking again immediately
before each merge.

Each merge is recorded as --actor. Its log, which --out must not already name, gains each merge's
entry before the merge is sent and is replaced whole after it, so a stopped run still leaves one. An
entry keeps the alias rows and the incoming team_merge_map rows the merge repoints to the survivor,
and the team_merge_map row it wrote. --revert replays the log newest merge first: it calls
revert_team_merge on that row, checks the team is live again, then points those incoming rows and
aliases back at it while they still point at the survivor. A merge whose row is gone was reverted
already, and a re-run finishes pointing its rows back while the team is still live. An entry whose
run never read back its merge row stops the revert, to be settled by hand. A revert is recorded as
the merge's actor plus ":revert".

Usage:
    python scripts/apply_vetted_team_merges.py --file merges.json            # dry run
    python scripts/apply_vetted_team_merges.py --file merges.json --execute
    python scripts/apply_vetted_team_merges.py --file merges.json --execute --limit 10
    python scripts/apply_vetted_team_merges.py --revert merge_results.json   # dry run
    python scripts/apply_vetted_team_merges.py --revert merge_results.json --execute
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
    page,
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
REVERT_REASON = "Undo of a vetted merge, replayed from its applier log"
LIVE_COLS = ",".join(("team_id_master", "is_deprecated", "team_name", *IDENTITY_FIELDS))
LOGGED = ("merge_id", "keep_id", "merge_name", "keep_name")


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


def is_live(sb, team_id: str) -> bool:
    row = fetch_live(sb, [team_id]).get(team_id)
    return row is not None and not row["is_deprecated"]


def refusal(pair: dict, live: dict[str, dict]) -> str | None:
    """Why a pair must not merge, read against its two rows as they stand now."""
    if missing_or_deprecated(pair, live):
        return "a row is missing or already deprecated"
    return changed_since_vetted(pair, live[pair["merge_id"]], live[pair["keep_id"]])


def call_rpc(sb, name: str, params: dict) -> dict:
    """The RPC's JSON answer. Both merge RPCs' success payloads carry a `message` key, which
    postgrest-py reads as an API error, so a committed write raises "JSON could not be generated"
    with the real payload in the exception text; treating that as a failure would report every
    successful merge or revert as failed."""
    try:
        res = sb.rpc(name, params).execute()
        return res.data if isinstance(res.data, dict) else {"success": bool(res.data)}
    except Exception as exc:  # noqa: BLE001
        text = str(exc)
        if '"success": true' in text or "'success': True" in text:
            return {"success": True, "note": "recovered from postgrest-py's message-key error"}
        return {"success": False, "error": text[:300]}


# The rows a merge repoints from the retired team to its survivor and revert_team_merge leaves there:
# the merges retiring other teams into it, which execute_team_merge cascades, and its aliases, of which
# it moves back only those whose ids the retired team's games carry.
REPOINTED = {
    "incoming_ids": ("team_merge_map", "canonical_team_id"),
    "alias_ids": ("team_alias_map", "team_id_master"),
}


def repointed(sb, team_id: str) -> dict[str, list]:
    """The ids of the rows a merge of the team would repoint, keyed as the log records them."""
    found = {}
    for key, (table, column) in REPOINTED.items():
        rows = page(lambda table=table, column=column: sb.table(table).select("id").eq(column, team_id), "id")
        found[key] = [row["id"] for row in rows]
    return found


def own_merge_row(sb, merge_id: str, actor: str):
    """The id of the team_merge_map row retiring the team, or None when there is none or another actor
    wrote it, as for a team merged elsewhere before this run's merge reached it."""
    rows = sb.table("team_merge_map").select("id,merged_by").eq("deprecated_team_id", merge_id).execute().data
    return rows[0]["id"] if rows and rows[0]["merged_by"] == actor else None


def merge_row(sb, map_id: str) -> dict | None:
    query = sb.table("team_merge_map").select("id,deprecated_team_id,canonical_team_id").eq("id", map_id)
    return next(iter(query.execute().data), None)


def survivor_of(sb, team_id: str) -> str:
    """The team the team's merges now lead to, itself when it is merged into nothing."""
    seen = set()
    while team_id not in seen:
        seen.add(team_id)
        rows = sb.table("team_merge_map").select("canonical_team_id").eq("deprecated_team_id", team_id).execute().data
        if not rows:
            break
        team_id = rows[0]["canonical_team_id"]
    return team_id


def new_log(out: str | None, directory: Path, stem: str) -> Path:
    """--out, or a timestamped file in the directory, refused when a file is already there, since a log
    may be the only record a revert can replay."""
    path = Path(out) if out else directory / f"{stem}_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.json"
    if path.exists():
        raise SystemExit(f"{path} already exists and may be the only record a revert can replay; pass another --out")
    return path


def read_log(path: Path) -> list[dict]:
    entries = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(entries, list):
        raise SystemExit(f"{path} holds no apply_vetted_team_merges.py log; pass the JSON list a --file run wrote")
    return entries


def write_log(path: Path, log: list | dict) -> None:
    """Replaced whole, so a run stopped while writing leaves the previous copy rather than a cut-off one."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(log, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def repointed_text(counts: dict[str, int]) -> str:
    return f"{counts['incoming_ids']} merge(s) into it and {counts['alias_ids']} alias row(s)"


def point_back(sb, entry: dict, survivor: str) -> dict[str, int]:
    """Point the rows the entry's merge repointed back at its retired team, each only while it still
    points at the survivor; how many of each moved."""
    moved = {}
    for key, (table, column) in REPOINTED.items():
        moved[key] = 0
        for batch in batched(entry[key]):
            query = sb.table(table).update({column: entry["merge_id"]}).in_("id", batch).eq(column, survivor)
            moved[key] += len(query.execute().data or [])
    return moved


def revert_one(sb, entry: dict, execute: bool) -> tuple[str, bool]:
    """What reverting one logged merge did, or would do, and whether that is a failure.

    revert_team_merge runs first, since check_merge_chains refuses a merge row pointing at a team that
    is still merged away; the rows its merge repointed are pointed back after it. A re-run of a revert
    stopped between the two finds the merge row gone and the team live, and points them back then. An
    entry whose run never read back the merge row is refused rather than guessed at: a row the same
    actor wrote for the team later is not this entry's."""
    if "merged_by" not in entry:
        return "the log predates --revert and records no merge row to undo", True
    team_id = entry["merge_id"]
    if not entry["map_id"]:
        if entry["map_read"]:
            return "nothing of this run's to revert", False
        return f"its merge may have committed, but its run never read back a merge row; settle {team_id} by hand", True
    row = merge_row(sb, entry["map_id"])
    if row is None:
        if not is_live(sb, team_id):
            return "already reverted, and merged again since; left as it is", False
        outcome, survivor = "already reverted", survivor_of(sb, entry["keep_id"])
    elif row["deprecated_team_id"] != team_id:
        return f"team_merge_map row {row['id']} retires another team", True
    else:
        outcome, survivor = "reverted", row["canonical_team_id"]
    if not execute:
        counts = {key: len(entry[key]) for key in REPOINTED}
        plan = "already reverted; would point back" if row is None else "would revert it, then point back"
        return f"{plan} {repointed_text(counts)}", False
    if row is not None:
        params = {"p_merge_id": row["id"], "p_reverted_by": f"{entry['merged_by']}:revert"}
        data = call_rpc(sb, "revert_team_merge", {**params, "p_revert_reason": REVERT_REASON})
        if not data.get("success"):
            return f"revert_team_merge failed: {str(data.get('error'))[:110]}", True
        if not is_live(sb, team_id):
            return "still deprecated after revert_team_merge answered success", True
    moved = point_back(sb, entry, survivor)
    return f"{outcome}, with {repointed_text(moved)} pointed back", False


def revert(args) -> int:
    """Undo a log's merges, newest first; with --execute, stop at the first that fails."""
    path = Path(args.revert)
    entries = read_log(path)
    print(f"loaded {len(entries)} logged merges from {args.revert}")

    sb = get_client()
    out = new_log(args.out, path.parent, "merge_reverts") if args.execute else None
    log, problems = [], 0
    for entry in reversed(entries):
        try:
            outcome, failed = revert_one(sb, entry, args.execute)
        except Exception as exc:  # noqa: BLE001
            outcome, failed = f"its rows could not be read or written: {str(exc)[:110]}", True
        print(f"  {entry['merge_name'][:40]!r} -> {entry['keep_name'][:40]!r}: {outcome}")
        problems += failed
        if args.execute:
            log.append({**{k: entry.get(k) for k in (*LOGGED, "map_id")}, "outcome": outcome})
            write_log(out, log)
            if failed:
                print(f"\nStopped at the first failure; the merges before it in the log are untouched. Log: {out}")
                return 1
    if not args.execute:
        unrevertable = f" {problems} of them could not be reverted." if problems else ""
        print(f"\nDRY RUN — nothing was written.{unrevertable} Re-run with --execute to revert.")
        return 1 if problems else 0
    print(f"\nDone: every logged merge is reverted or was not this run's. Log: {out}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    source = ap.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--file",
        help="JSON array with merge_id, keep_id, merge_name, keep_name, merge_as_vetted, keep_as_vetted",
    )
    source.add_argument("--revert", help="a log a --file run wrote: undo its merges, newest first")
    ap.add_argument("--execute", action="store_true", help="write to the database (default is a dry run)")
    ap.add_argument("--limit", type=int, default=None, help="apply at most N merges")
    ap.add_argument("--actor", default=MERGED_BY, help=f"who the merges are recorded as (default: {MERGED_BY})")
    ap.add_argument("--out", default=None, help="where to write the log (default alongside --file or --revert)")
    args = ap.parse_args()
    if args.revert:
        if args.limit is not None or args.actor != MERGED_BY:
            ap.error("--limit and --actor apply to merging; a revert replays the whole log as each merge's actor")
        return revert(args)

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
    out = new_log(args.out, Path(args.file).parent, "merge_results")
    log, ok, failed, refused = [], 0, 0, 0
    for i, p in enumerate(pairs, 1):
        try:
            reason = refusal(p, fetch_live(sb, [p["merge_id"], p["keep_id"]]))
            moving = None if reason else repointed(sb, p["merge_id"])
        except Exception as exc:  # noqa: BLE001
            reason = f"its rows could not be read again: {str(exc)[:110]}"
        if reason:
            refused += 1
            print(f"  SKIP ({reason}): {p['merge_name'][:40]!r} -> {p['keep_name'][:40]!r}")
            continue
        # Logged before the merge is sent, so one that commits while the run is stopping is still on record.
        entry = {
            **{k: p.get(k) for k in LOGGED},
            "result": {"pending": True},
            "merged_by": args.actor,
            "map_id": None,
            "map_read": False,
            **moving,
        }
        log.append(entry)
        write_log(out, log)
        data = call_rpc(
            sb,
            "execute_team_merge",
            {
                "p_deprecated_team_id": p["merge_id"],
                "p_canonical_team_id": p["keep_id"],
                "p_merged_by": args.actor,
                "p_merge_reason": MERGE_REASON,
            },
        )
        try:
            entry["map_id"] = own_merge_row(sb, p["merge_id"], args.actor)
            entry["map_read"] = True
        except Exception as exc:  # noqa: BLE001
            print(f"  could not read back its team_merge_map row, so --revert will refuse it: {str(exc)[:110]}")
        if entry["map_id"] and not data.get("success"):
            data = {"success": True, "note": f"its reply was lost but its merge row is there: {data.get('error')}"}
        entry["result"] = data
        if data.get("success"):
            ok += 1
        else:
            failed += 1
            print(f"  FAILED {p['merge_name'][:40]!r} -> {p['keep_name'][:40]!r}: {str(data.get('error'))[:110]}")
        write_log(out, log)
        if i % 25 == 0:
            print(f"  {i}/{len(pairs)}  ({ok} ok, {failed} failed)")

    write_log(out, log)
    print(f"\nDone: {ok} merged, {failed} failed, {refused} refused by the check before each merge. Log: {out}")
    print(f"To undo: python scripts/apply_vetted_team_merges.py --revert {out}  (a dry run; add --execute)")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
