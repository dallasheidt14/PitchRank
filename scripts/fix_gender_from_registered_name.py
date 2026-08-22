#!/usr/bin/env python3
"""Correct teams.gender where the team's own registered name contradicts it.

A team's gender is stored in a column, but the name the club registered also states it --
"North Scott U8 Boys Black" is not a girls team whatever the column says. Where the two
disagree, the name is usually right: the column is set by importers and matchers, while the
name came from the club.

The name alone is not enough to act on, because a lone B or G can be a colour or a squad
code, so this script requires TWO independent witnesses:

  1. the team's own name spells out "Boys" or "Girls" as a word, and
  2. the names of the teams it has actually played agree with that reading.

The second test matters more than it looks. Youth soccer is gender-segregated, so opponents
are a natural check -- but their *stored* gender is not independent, because mislabelling
arrives in whole import batches: a girls team plays girls teams that are all stored Male, and
the column appears to confirm the error. Their *names* are independent, having been written
by other clubs. On the first run, 57 of 73 corrected teams had opponents whose column pointed
the wrong way, so reading the column instead of the names would have got most of them wrong.

Gender moves a team between ranking boards, so every change is logged with its previous value
and can be replayed backwards from the log.

Usage:
    python scripts/fix_gender_from_registered_name.py                # dry run
    python scripts/fix_gender_from_registered_name.py --execute
    python scripts/fix_gender_from_registered_name.py --execute --limit 10
    python scripts/fix_gender_from_registered_name.py --revert <log.json>
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
load_dotenv(Path(__file__).resolve().parent.parent / ".env.local")

from supabase import create_client  # noqa: E402

WORD_B = re.compile(r"(?<![a-z0-9])boys?(?![a-z0-9])", re.I)
WORD_G = re.compile(r"(?<![a-z0-9])girls?(?![a-z0-9])", re.I)
AFFIX_B = re.compile(r"(?<![a-z0-9])b(?=u?\d)|(?<=\d)b(?![a-z0-9])", re.I)
AFFIX_G = re.compile(r"(?<![a-z0-9])g(?=u?\d)|(?<=\d)g(?![a-z0-9])", re.I)


def get_client():
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY")
    if not url or not key:
        raise SystemExit("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set")
    return create_client(url, key)


def spelled_gender(name: str | None) -> str | None:
    """Gender a name states in words. Ignores bare B/G, which is too weak to act on."""
    n = name or ""
    b, g = bool(WORD_B.search(n)), bool(WORD_G.search(n))
    if b and not g and not AFFIX_G.search(n):
        return "Male"
    if g and not b and not AFFIX_B.search(n):
        return "Female"
    return None


def any_gender(name: str | None) -> str | None:
    """Gender a name states in words OR as a B/G affix. Used only to read opponents."""
    n = name or ""
    s = spelled_gender(n)
    if s:
        return s
    b, g = bool(AFFIX_B.search(n)), bool(AFFIX_G.search(n))
    if b and not g:
        return "Male"
    if g and not b:
        return "Female"
    return None


def fetch_candidates(sb):
    rows, off = [], 0
    while True:
        res = (
            sb.table("teams")
            .select("team_id_master,team_name,team_name_original,gender,club_name,age_group,is_deprecated")
            .not_.is_("team_name_original", "null")
            .range(off, off + 999)
            .execute()
        )
        d = res.data or []
        rows.extend(d)
        if len(d) < 1000:
            break
        off += 1000

    out = []
    for t in rows:
        if t["is_deprecated"] or not t.get("gender"):
            continue
        says = spelled_gender(t["team_name_original"])
        if says and says != t["gender"]:
            out.append({**t, "says": says})
    return len(rows), out


def opponent_names(sb, ids):
    # A set, not a list: a team that plays the same opponent six times would otherwise cast
    # six votes and outweigh several distinct opponents that disagree.
    opps = defaultdict(set)
    for i in range(0, len(ids), 50):
        batch = ids[i : i + 50]
        for side in ("home_team_master_id", "away_team_master_id"):
            off = 0
            while True:
                res = (
                    sb.table("games")
                    .select(f"{side},home_team_master_id,away_team_master_id")
                    .in_(side, batch)
                    .range(off, off + 999)
                    .execute()
                )
                d = res.data or []
                for g in d:
                    other = g["away_team_master_id"] if side == "home_team_master_id" else g["home_team_master_id"]
                    if other:
                        opps[g[side]].add(other)
                if len(d) < 1000:
                    break
                off += 1000

    everyone = sorted({o for v in opps.values() for o in v})
    info = {}
    for i in range(0, len(everyone), 100):
        res = (
            sb.table("teams")
            .select("team_id_master,team_name,team_name_original")
            .in_("team_id_master", everyone[i : i + 100])
            .execute()
        )
        for t in res.data or []:
            info[t["team_id_master"]] = t
    return opps, info


def revert(sb, log_path: str, execute: bool) -> int:
    log = json.loads(Path(log_path).read_text(encoding="utf-8"))
    print(f"reverting {len(log)} gender changes from {log_path}")
    done = 0
    for r in log:
        if not r.get("applied"):
            continue
        if execute:
            sb.table("teams").update({"gender": r["was"]}).eq("team_id_master", r["team_id_master"]).execute()
        done += 1
        print(f"   {r['team_name']!r}: {r['now']} -> {r['was']}")
    print(f"{'reverted' if execute else 'would revert'} {done}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--execute", action="store_true", help="apply the changes (default is a dry run)")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--out", default=None, help="where to write the change log")
    ap.add_argument("--revert", default=None, help="undo the changes recorded in a log file")
    args = ap.parse_args()

    sb = get_client()
    if args.revert:
        return revert(sb, args.revert, args.execute)

    scanned, cands = fetch_candidates(sb)
    print(f"rows with a registered original name : {scanned}")
    print(f"name spells a gender the column denies: {len(cands)}")

    opps, info = opponent_names(sb, [t["team_id_master"] for t in cands])

    confirmed, rejected = [], Counter()
    for t in cands:
        votes = Counter()
        for o in opps.get(t["team_id_master"], []):
            i = info.get(o, {})
            s = any_gender(i.get("team_name_original") or i.get("team_name"))
            if s:
                votes[s] += 1
        if not votes:
            rejected["no opponent names to check against"] += 1
            continue
        top, n = votes.most_common(1)[0]
        if top != t["says"]:
            rejected["opponents' names disagree"] += 1
            continue
        # most_common breaks a tie by insertion order, so an even split would otherwise read
        # as agreement. Gender moves a team between ranking boards, so require a real majority.
        if n * 2 <= sum(votes.values()):
            rejected["opponents' names are evenly split"] += 1
            continue
        confirmed.append({**t, "opp_votes": dict(votes), "opp_agree": n, "opp_total": sum(votes.values())})

    print(f"\nconfirmed by opponents' names        : {len(confirmed)}")
    for k, v in rejected.most_common():
        print(f"  left alone, {k}: {v}")

    if args.limit:
        confirmed = confirmed[: args.limit]

    print(f"\n{'APPLYING' if args.execute else 'DRY RUN —'} {len(confirmed)} gender corrections")
    for t in confirmed[:20]:
        print(f"   {t['gender']} -> {t['says']:<6} {t['team_name_original'][:48]!r} "
              f"({t['opp_agree']}/{t['opp_total']} opponents)  {t['club_name'] or ''}")
    if len(confirmed) > 20:
        print(f"   ... and {len(confirmed) - 20} more")

    if not args.execute:
        print("\nNothing written. Re-run with --execute to apply.")
        return 0

    log, ok = [], 0
    for t in confirmed:
        rec = {"team_id_master": t["team_id_master"], "team_name": t["team_name"],
               "team_name_original": t["team_name_original"], "was": t["gender"],
               "now": t["says"], "club_name": t["club_name"], "age_group": t["age_group"],
               "opp_votes": t["opp_votes"], "applied": False}
        try:
            sb.table("teams").update({"gender": t["says"]}).eq("team_id_master", t["team_id_master"]).execute()
            rec["applied"] = True
            ok += 1
        except Exception as exc:  # noqa: BLE001
            rec["error"] = str(exc)[:200]
            print(f"  FAILED {t['team_name']!r}: {rec['error'][:100]}")
        log.append(rec)

    out = Path(args.out) if args.out else Path(f"gender_fix_log_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.json")
    out.write_text(json.dumps(log, indent=1), encoding="utf-8")
    print(f"\nUpdated {ok} of {len(confirmed)}. Log: {out}")
    print(f"To undo: python scripts/fix_gender_from_registered_name.py --revert {out} --execute")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
