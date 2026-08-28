#!/usr/bin/env python3
"""Propose merges for GotSport registration-ID placeholder teams from game evidence alone.

A placeholder row (team_name == 'unknown_<provider_team_id>', provider_team_id >= 3_000_000)
is a per-event registration ID that GotSport's team_details API cannot resolve. Where the
same real team also exists under its true 6-digit team ID, both rows carry the same matches:
one imported from the org_event schedule page, one from the rankings game-history scrape.

This reads no name, so it reaches the placeholder rows that name similarity cannot compare at
all. It is the "Doorway B" of .claude/skills/merging-duplicate-teams -- the tool that produced
the 639 merges applied on 2026-08-27.

Tier A requires ALL of:
  - every scored game on the placeholder is matched on (date, opponent, score) by one named team
  - at least --min-games such games
  - exactly one candidate target
  - the two rows never played each other
  - the target's age_group and gender match, and its provider_team_id is a real team ID

Opponents are resolved through team_merge_map first, so a merged opponent does not hide a
match. Games with a NULL score are skipped -- unplayed fixtures would match indiscriminately.

Scope, deliberately narrow: it seeds only from placeholder rows, so it answers "which named
team is this placeholder" and cannot answer "which two teams in this cohort are duplicates".
Only GotSport rankings-ID targets can win, and placeholder-to-placeholder pairs are invisible.
.turbo/specs/second-layer-duplicate-detection.md carries the design for generalising it and
the rest of its known blind spots. Tier A on the 2026-08-27 corpus is exhausted; what remains
is the held tiers, which need a rule change or a person rather than a rerun.

Read-only: writes JSON, never touches the database. Feed the Tier A file to
scripts/apply_vetted_team_merges.py, which is where the writes happen.

Usage:
    python scripts/find_regid_duplicate_merges.py --out-dir data/exports
    python scripts/find_regid_duplicate_merges.py --out-dir data/exports --min-games 5
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")
load_dotenv(ROOT / ".env.local", override=True)

from supabase import create_client  # noqa: E402

REG_ID_FLOOR = 3_000_000
GAME_COLS = "id,home_team_master_id,away_team_master_id,home_score,away_score,game_date"


def get_client():
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY")
    if not url or not key:
        raise SystemExit("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set")
    return create_client(url, key)


def page(build):
    """Drain a PostgREST query past the 1000-row cap."""
    rows, off = [], 0
    while True:
        chunk = build().range(off, off + 999).execute().data or []
        rows.extend(chunk)
        if len(chunk) < 1000:
            return rows
        off += 1000


def batched(seq, n=100):
    seq = list(seq)
    for i in range(0, len(seq), n):
        yield seq[i : i + n]


def load_merge_map(sb):
    raw = {}
    for r in page(lambda: sb.table("team_merge_map").select("deprecated_team_id,canonical_team_id")):
        raw[r["deprecated_team_id"]] = r["canonical_team_id"]

    def canon(tid):
        seen = set()
        while tid in raw and tid not in seen:
            seen.add(tid)
            tid = raw[tid]
        return tid

    return canon


def load_placeholders(sb, gotsport):
    placeholders = {}
    for r in page(
        lambda: sb.table("teams")
        .select("team_id_master,team_name,provider_team_id,age_group,gender")
        .like("team_name", "unknown\\_%")
        .eq("provider_id", gotsport)
        .eq("is_deprecated", False)
    ):
        pid = str(r.get("provider_team_id") or "")
        if not pid.isdigit() or int(pid) < REG_ID_FLOOR:
            continue
        if r["team_name"].lower() != f"unknown_{pid.lower()}":
            continue
        placeholders[r["team_id_master"]] = r
    return placeholders


def fetch_games_for(sb, ids):
    out = {}
    ids = [i for i in ids if i]
    for side in ("home_team_master_id", "away_team_master_id"):
        for batch in batched(ids):
            for g in page(lambda b=batch, s=side: sb.table("games").select(GAME_COLS).in_(s, b)):
                out[g["id"]] = g
    return out


def build_tiers(sb, canon, placeholders, min_games):
    ph_games = fetch_games_for(sb, placeholders)
    print(f"  {len(ph_games):,} placeholder games")

    ph_fixtures = defaultdict(list)
    ph_total = defaultdict(int)
    opponents = set()
    for g in ph_games.values():
        if g["home_score"] is None or g["away_score"] is None:
            continue
        for me, them, mine, theirs in (
            (g["home_team_master_id"], g["away_team_master_id"], g["home_score"], g["away_score"]),
            (g["away_team_master_id"], g["home_team_master_id"], g["away_score"], g["home_score"]),
        ):
            if me not in placeholders:
                continue
            opp = canon(them)
            ph_total[me] += 1
            ph_fixtures[me].append((g["id"], g["game_date"], opp, mine, theirs))
            opponents.add(them)
            opponents.add(opp)

    eligible = {t for t, n in ph_total.items() if n >= min_games}
    print(f"  {len(eligible):,} placeholders with >= {min_games} scored games")

    print(f"opponent games ({len(opponents):,} opponents)...", flush=True)
    opp_games = fetch_games_for(sb, opponents)
    print(f"  {len(opp_games):,} games")

    index = defaultdict(set)
    for g in opp_games.values():
        if g["home_score"] is None or g["away_score"] is None:
            continue
        for them, me, theirs, mine in (
            (g["home_team_master_id"], g["away_team_master_id"], g["home_score"], g["away_score"]),
            (g["away_team_master_id"], g["home_team_master_id"], g["away_score"], g["home_score"]),
        ):
            if not them or not me:
                continue
            index[(g["game_date"], canon(them), theirs, mine)].add((me, g["id"]))

    print("scoring candidates...", flush=True)
    support = defaultdict(lambda: defaultdict(set))
    for ph in eligible:
        for gid, date, opp, mine, theirs in ph_fixtures[ph]:
            for other, other_gid in index.get((date, opp, theirs, mine), ()):
                if other == ph or other_gid == gid or other in placeholders:
                    continue
                support[ph][other].add(gid)

    meta = {}
    for batch in batched({c for m in support.values() for c in m if c}):
        rows = (
            sb.table("teams")
            .select("team_id_master,team_name,provider_team_id,club_name,age_group,gender,is_deprecated")
            .in_("team_id_master", batch)
            .execute()
            .data
        ) or []
        for r in rows:
            meta[r["team_id_master"]] = r

    def is_valid_target(cand, ph_row):
        m = meta.get(cand)
        if not m or m["is_deprecated"]:
            return False
        pid = str(m.get("provider_team_id") or "")
        if not pid.isdigit() or int(pid) >= REG_ID_FLOOR:
            return False
        return m["age_group"] == ph_row["age_group"] and m["gender"] == ph_row["gender"]

    head_to_head = set()
    for ph, cands in support.items():
        for _gid, _date, opp, _mine, _theirs in ph_fixtures[ph]:
            if opp in cands or opp in {canon(c) for c in cands}:
                head_to_head.add(ph)

    tiers = defaultdict(list)
    for ph, cands in support.items():
        ph_row = placeholders[ph]
        valid = {c: g for c, g in cands.items() if is_valid_target(c, ph_row)}
        if not valid:
            continue
        if ph in head_to_head:
            tiers["excluded_head_to_head"].append(ph)
            continue
        if len(valid) > 1:
            tiers["excluded_ambiguous"].append(ph)
            continue
        target, matched = next(iter(valid.items()))
        n, total = len(matched), ph_total[ph]
        rec = {
            "merge_id": ph,
            "keep_id": target,
            "merge_name": ph_row["team_name"],
            "keep_name": meta[target]["team_name"],
            "club": meta[target].get("club_name"),
            "age_group": ph_row["age_group"],
            "gender": ph_row["gender"],
            "matched_games": n,
            "placeholder_total_games": total,
        }
        # `eligible` already required total >= min_games, so n == total implies n >= min_games.
        tiers["A" if n == total else "partial"].append(rec)

    for name in ("A", "partial"):
        tiers[name].sort(key=lambda r: -r["matched_games"])
    return tiers


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--out-dir", default="data/exports", help="where to write the tier JSON")
    parser.add_argument("--min-games", type=int, default=3, help="scored games a placeholder needs")
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    if not out_dir.is_absolute():
        out_dir = ROOT / out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    sb = get_client()
    print("provider + merge map...", flush=True)
    gotsport = sb.table("providers").select("id").eq("code", "gotsport").execute().data[0]["id"]
    canon = load_merge_map(sb)

    print("placeholder rows...", flush=True)
    placeholders = load_placeholders(sb, gotsport)
    print(f"  {len(placeholders):,} registration-ID placeholders")

    tiers = build_tiers(sb, canon, placeholders, args.min_games)

    tier_a = out_dir / "regid_tier_a.json"
    tier_a.write_text(json.dumps(tiers["A"], indent=1), encoding="utf-8")
    (out_dir / "regid_all_tiers.json").write_text(
        json.dumps(dict(tiers), indent=1, default=list), encoding="utf-8"
    )

    print("\n=== Tier summary ===")
    print(f"  A  (every scored game matched)     : {len(tiers['A']):,}")
    print(f"  partial history matched            : {len(tiers['partial']):,}")
    print(f"  excluded, played each other        : {len(tiers['excluded_head_to_head']):,}")
    print(f"  excluded, >1 candidate target      : {len(tiers['excluded_ambiguous']):,}")
    print(f"\nwrote {tier_a}")
    print("Tier A is a proposal, not a decision. Vet it before apply_vetted_team_merges.py.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
