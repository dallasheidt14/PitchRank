#!/usr/bin/env python3
"""
Correct teams whose stored age group is older than both GotSport and the team's own
two-year band say it is.

Scope is derived, never hand-listed: every team in the reconcile_teams_with_gotsport
logs where

  * GotSport's cohort is YOUNGER than the stored one, and
  * the team's name (GotSport's current name, ours, or both) carries exactly one
    two-year band ("2015/16", "B2014-2015"), and that band resolves to GotSport's cohort.

The band is the value; GotSport is corroboration. A band names both birth years of a
cohort, so it resolves without knowing which season wrote it -- the project's own rule,
scripts/normalize_team_names._resolve_band. Measured 2026-09-15 across 50 states: where
a band decides a GotSport-younger disagreement it backs GotSport 9,149 times and the
stored label 65. The reverse direction (GotSport older) is out of scope; there the
stored label is usually the right one.

Three modes, so what gets reviewed is exactly what gets written:

  (default)                     Dry run. Re-verify every candidate against the live
                                table, check the target cohort for a same-named team,
                                write a plan CSV. No database writes.
  --apply PLAN [--limit N] [--include-collisions] --execute
                                Apply the plan. Each write carries the planned old value
                                as a predicate, so a team that moved since the plan is
                                skipped and reported, never overwritten.
  --revert LOG --execute        Undo an apply log, again only where the row still holds
                                the value this tool wrote.

Tracked under scripts/ so CI imports it; its plan and apply logs stay in data/exports/
(gitignored), because the revert path has to outlive the session that ran it.
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

from config.settings import AGE_GROUPS  # noqa: E402
from scripts.normalize_team_names import _resolve_band  # noqa: E402
from src.utils.age_group import normalize_age_group  # noqa: E402
from src.utils.team_utils import _soccer_season_year  # noqa: E402
from supabase import create_client  # noqa: E402

EXPORTS = ROOT / "data" / "exports"
IN_BATCH = 100
PAGE = 1000
SEASON_START = f"{_soccer_season_year()}-08-01"
_COHORT = re.compile(r"^u([0-9]{1,2})$")
_YEAR = re.compile(r"(?<![0-9])(20[0-2][0-9])(?![0-9])")

PLAN_FIELDS = [
    "state_code",
    "team_id_master",
    "team_name",
    "club_name",
    "gender",
    "gotsport_team_name",
    "band",
    "old_age_group",
    "new_age_group",
    "action",
    "collision_with",
    "evidence_tier",
    "fixture_verdict",
    "opp_games_proposed",
    "opp_games_current",
]


def load_env() -> None:
    env_local = ROOT / ".env.local"
    if env_local.exists():
        load_dotenv(env_local, override=True)
    else:
        load_dotenv(ROOT / ".env")


def get_supabase():
    url = os.getenv("SUPABASE_URL") or os.getenv("NEXT_PUBLIC_SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_SERVICE_KEY")
    if not url or not key:
        raise ValueError("Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY")
    return create_client(url, key)


def age_num(cohort: str) -> int:
    match = _COHORT.match(cohort or "")
    if not match:
        raise ValueError(f"not a cohort: {cohort!r}")
    return int(match.group(1))


def band_of(name: Optional[str]) -> Optional[str]:
    if not name:
        return None
    _, label = _resolve_band(name)
    return normalize_age_group(label) if label else None


def single_band(*names: Optional[str]) -> Optional[str]:
    """The one cohort the names' bands agree on, or None if none or they conflict."""
    bands = {b for b in (band_of(n) for n in names) if b}
    return bands.pop() if len(bands) == 1 else None


def norm_name(name: Optional[str]) -> str:
    return " ".join((name or "").lower().split())


def write_csv(rows: List[Dict], path: Path, fields: List[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    tmp.replace(path)


def read_csv(path: Path) -> List[Dict]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


# --------------------------------------------------------------------------- plan


def derive_candidates() -> List[Dict]:
    """Latest execute-mode audit row per team, filtered to band-confirmed too-old labels."""
    latest: Dict[str, Dict] = {}
    for path in sorted(EXPORTS.glob("reconcile_teams_with_gotsport_*.csv")):
        try:
            for row in read_csv(path):
                if (row.get("run_mode") or "").lower() == "execute":
                    latest[row["team_id_master"]] = row
        except Exception as e:  # a log still being written by a live chunk
            print(f"  skipped unreadable log {path.name}: {e}")

    candidates = []
    for row in latest.values():
        ours = normalize_age_group(row.get("stored_age_group"))
        theirs = normalize_age_group(row.get("gotsport_age_group"))
        if not ours or not theirs or age_num(theirs) >= age_num(ours):
            continue
        if single_band(row.get("gotsport_team_name"), row.get("stored_team_name")) != theirs:
            continue
        candidates.append(
            {
                "team_id_master": row["team_id_master"],
                "audit_age_group": ours,
                "new_age_group": theirs,
                "gotsport_team_name": row.get("gotsport_team_name") or "",
            }
        )
    print(f"Audit rows read: {len(latest):,} teams | band-confirmed too-old candidates: {len(candidates):,}")
    return candidates


def fetch_live(sb, ids: List[str]) -> Dict[str, Dict]:
    live: Dict[str, Dict] = {}
    cols = "team_id_master,team_name,club_name,age_group,gender,state_code,is_deprecated"
    for i in range(0, len(ids), IN_BATCH):
        for row in sb.table("teams").select(cols).in_("team_id_master", ids[i : i + IN_BATCH]).execute().data or []:
            live[row["team_id_master"]] = row
    return live


def fetch_all_live_teams(sb) -> List[Dict]:
    rows: List[Dict] = []
    start = 0
    while True:
        batch = (
            sb.table("teams")
            .select("team_id_master,team_name,age_group,gender")
            .eq("is_deprecated", False)
            .order("team_id_master")
            .range(start, start + PAGE - 1)
            .execute()
            .data
            or []
        )
        rows.extend(batch)
        if len(batch) < PAGE:
            return rows
        start += PAGE


def evidence_tier(our_name: Optional[str], target: str) -> str:
    """How independent of GotSport the name evidence for this move is.

    A band found only in GotSport's name is GotSport agreeing with itself, and a bare
    year in ours ("2014") fits both of the cohorts it straddles, so neither decides.
    A bare year OUTSIDE the target's two birth years means our record and GotSport's
    describe different squads -- a wrong alias or a fused row, not a label to move.
    """
    if band_of(our_name) == target:
        return "A_own_name_band"
    years = {int(y) for y in _YEAR.findall(our_name or "")}
    if not years:
        return "B_gotsport_name_only"
    younger = _soccer_season_year() - age_num(target) + 1
    return "C_bare_year_fits" if years <= {younger, younger - 1} else "D_name_contradicts"


def attach_fixture_evidence(sb, rows: List[Dict]) -> None:
    """Count this season's games against opponents whose OWN band names each cohort.

    Opponent names are independent of both our column and GotSport's label, which is
    why they are the witness (CLAUDE.md: settle a cohort from the fixtures, reading the
    opponent's name, not its column). Games are resolved from the pre-merge ids they
    carry, so evidence can only be undercounted -- that makes a team "thin", never moves it.
    """
    by_id = {r["team_id_master"]: r for r in rows}
    ids = list(by_id)
    games = []
    for i in range(0, len(ids), 50):
        batch = ids[i : i + 50]
        sides = (
            ("home_team_master_id", "away_team_master_id"),
            ("away_team_master_id", "home_team_master_id"),
        )
        for col, other in sides:
            data = (
                sb.table("games")
                .select(f"{col},{other}")
                .in_(col, batch)
                .gte("game_date", SEASON_START)
                .execute()
                .data
            )
            games += [(g[col], g[other]) for g in data or [] if g.get(other)]

    opp_ids = list({o for _, o in games})
    names: Dict[str, str] = {}
    for i in range(0, len(opp_ids), IN_BATCH):
        listed = (
            sb.table("teams")
            .select("team_id_master,team_name")
            .in_("team_id_master", opp_ids[i : i + IN_BATCH])
            .execute()
            .data
            or []
        )
        for t in listed:
            names[t["team_id_master"]] = t["team_name"]

    counts: Dict[str, Counter] = defaultdict(Counter)
    for me, opp in games:
        cohort = band_of(names.get(opp))
        row = by_id[me]
        if cohort == row["new_age_group"]:
            counts[me]["proposed"] += 1
        elif cohort and cohort == normalize_age_group(row["old_age_group"]):
            counts[me]["current"] += 1

    for tid, row in by_id.items():
        proposed, current = counts[tid]["proposed"], counts[tid]["current"]
        row["opp_games_proposed"], row["opp_games_current"] = proposed, current
        if proposed + current < 2:
            row["fixture_verdict"] = "thin"
        elif proposed >= 3 * current:
            row["fixture_verdict"] = "backs_move"
        elif current >= 3 * proposed:
            row["fixture_verdict"] = "backs_current"
        else:
            row["fixture_verdict"] = "mixed"


def build_plan(sb) -> Path:
    candidates = derive_candidates()
    live = fetch_live(sb, [c["team_id_master"] for c in candidates])

    plan: List[Dict] = []
    for c in candidates:
        tid = c["team_id_master"]
        team = live.get(tid)
        row = {
            "team_id_master": tid,
            "gotsport_team_name": c["gotsport_team_name"],
            "new_age_group": c["new_age_group"],
            "collision_with": "",
        }
        if not team:
            plan.append({**row, "action": "skipped_missing"})
            continue
        row.update(
            state_code=team.get("state_code") or "",
            team_name=team.get("team_name") or "",
            club_name=team.get("club_name") or "",
            gender=team.get("gender") or "",
            old_age_group=team.get("age_group") or "",
        )
        current = normalize_age_group(team.get("age_group"))
        band = single_band(c["gotsport_team_name"], team.get("team_name"))
        row["band"] = band or ""
        if team.get("is_deprecated"):
            action = "skipped_deprecated"
        elif current == c["new_age_group"]:
            action = "skipped_already_correct"
        elif current != c["audit_age_group"]:
            action = "skipped_moved_since_audit"
        elif band != c["new_age_group"]:
            action = "skipped_band_changed"
        else:
            action = "would_update"
        plan.append({**row, "action": action})

    pending = [r for r in plan if r["action"] == "would_update"]
    for r in pending:
        r["evidence_tier"] = evidence_tier(r["team_name"], r["new_age_group"])
    print(f"Reading this season's fixtures for {len(pending):,} teams...")
    attach_fixture_evidence(sb, pending)
    # Holds are decided before the collision index, so a team that will NOT move is
    # indexed in its current cohort rather than the one it was proposed for.
    for r in pending:
        if r["evidence_tier"] == "D_name_contradicts":
            r["action"] = "held_name_contradicts"
        elif r["fixture_verdict"] in ("backs_current", "mixed"):
            r["action"] = "held_fixtures_disagree"

    movers = {r["team_id_master"]: r for r in plan if r["action"] == "would_update"}
    print("Paging live teams for the collision check...")
    index: Dict[tuple, set] = defaultdict(set)
    for t in fetch_all_live_teams(sb):
        tid = t["team_id_master"]
        cohort = movers[tid]["new_age_group"] if tid in movers else normalize_age_group(t.get("age_group"))
        index[(norm_name(t.get("team_name")), t.get("gender") or "", cohort)].add(tid)
    for tid, r in movers.items():
        others = index[(norm_name(r["team_name"]), r["gender"], r["new_age_group"])] - {tid}
        if others:
            r["action"] = "would_update_collision"
            r["collision_with"] = ";".join(sorted(others)[:3])

    plan.sort(key=lambda r: (r.get("state_code") or "", r.get("new_age_group") or "", r.get("team_name") or ""))
    path = EXPORTS / f"fix_band_cohorts_plan_{datetime.now():%Y%m%d_%H%M%S}.csv"
    write_csv(plan, path, PLAN_FIELDS)

    counts = Counter(r["action"] for r in plan)
    print("\n=== Plan (DRY RUN - nothing written) ===")
    for action, n in counts.most_common():
        print(f"  {action:28s} {n:>6,}")
    clean = [r for r in plan if r["action"] == "would_update"]
    transitions = Counter(f"{r['old_age_group']} -> {r['new_age_group']}" for r in clean)
    print("\nMoves (clean rows): " + ", ".join(f"{k} {v:,}" for k, v in transitions.most_common(12)))
    per_state = Counter(r["state_code"] for r in clean)
    print("By state (clean rows): " + ", ".join(f"{k} {v:,}" for k, v in per_state.most_common(12)))
    print("Clean rows by evidence tier x fixture verdict:")
    for (tier, verdict), n in sorted(Counter((r["evidence_tier"], r["fixture_verdict"]) for r in clean).items()):
        print(f"  {tier:22s} {verdict:14s} {n:>6,}")
    off_board = sum(1 for r in clean if r["new_age_group"] not in AGE_GROUPS)
    print(f"Clean rows landing in a cohort the boards do not rank: {off_board:,}")
    print("\nSample:")
    for r in clean[:: max(1, len(clean) // 12)][:12]:
        print(f"  {r['state_code']:2s} {r['old_age_group']:>3s} -> {r['new_age_group']:3s}  {r['team_name'][:60]}")
    coll = [r for r in plan if r["action"] == "would_update_collision"]
    if coll:
        print("\nCollision samples (a same-named team already in the target cohort):")
        for r in coll[:6]:
            print(f"  {r['state_code']:2s} {r['old_age_group']:>3s} -> {r['new_age_group']:3s}  {r['team_name'][:60]}")
    print(f"\nPlan: {path}")
    return path


# --------------------------------------------------------------------------- apply


def classify_miss(sb, tid: str, new: str) -> str:
    rows = sb.table("teams").select("age_group,is_deprecated").eq("team_id_master", tid).execute().data or []
    if not rows:
        return "skipped_missing"
    if rows[0].get("is_deprecated"):
        return "skipped_deprecated"
    return "already_applied" if normalize_age_group(rows[0].get("age_group")) == new else "skipped_moved"


def is_strong(row: Dict) -> bool:
    """Two independent signals: our own name's band, or the opponents' own names."""
    return row.get("evidence_tier", "").startswith("A_") or row.get("fixture_verdict") == "backs_move"


# A year this recent in a youth team's name is a season label ("2025 Fairfield FC", "(24/25)").
_SEASON_FROM = 2022
_NAME_YEAR4 = re.compile(r"(?<![0-9])(20[0-2][0-9])(?![0-9])")
# Two-digit pairs, apostrophes allowed ("'11/'12", "16/17"); not a U-age pair ("U09/10", "11/12uB").
_NAME_PAIR2 = re.compile(r"(?i)(?<![0-9u])'?([0-2][0-9])\s*[/-]\s*'?([0-2][0-9])(?![0-9])(?!\s*u)")
_NAME_APOS = re.compile(r"'([0-2][0-9])(?![0-9/])")
_NAME_UAGE = re.compile(r"(?i)(?<![a-z0-9])[bg]?u-?([0-9]{1,2})(?![0-9])|(?<![0-9])([0-9]{1,2})u(?=[bg]?(?![a-z0-9]))")


def name_contradiction(name: Optional[str], target: str) -> str:
    """Why OUR name plainly describes a different age than the move, or "" if it does not.

    Deliberately narrow, because the user's rule is that GotSport's two-year band is
    trusted: this only catches a name stating another squad outright. A U-age one away
    passes -- names keep last season's U-age after the Aug 1 roll -- and recent years
    are season labels, not birth years. _resolve_band misses the apostrophe and
    two-digit forms, which is how "BRAUSA '11/'12" slipped through the first batch.
    """
    name = name or ""
    n = age_num(target)
    younger = _soccer_season_year() - n + 1
    allowed = {younger, younger - 1}
    years = {int(y) for y in _NAME_YEAR4.findall(name) if int(y) < _SEASON_FROM}
    for a, b in _NAME_PAIR2.findall(name):
        a, b = int(a), int(b)
        if abs(a - b) == 1 and 2000 + max(a, b) < _SEASON_FROM:
            years |= {2000 + a, 2000 + b}
    years |= {2000 + int(a) for a in _NAME_APOS.findall(name) if 2000 + int(a) < _SEASON_FROM}
    stray = sorted(years - allowed)
    if stray:
        return f"name has birth year {stray[0]}, outside {target.upper()} ({younger}/{younger - 1})"
    for match in _NAME_UAGE.finditer(name):
        age = int(match.group(1) or match.group(2))
        if 5 <= age <= 19 and abs(age - n) >= 2:
            return f"name says U{age}, {abs(age - n)} away from {target.upper()}"
    return ""


def apply_plan(
    sb,
    plan_path: Path,
    execute: bool,
    limit: Optional[int],
    include_collisions: bool,
    strong_only: bool,
    boarded_only: bool,
    unboarded_only: bool = False,
    exclude: frozenset = frozenset(),
    gotsport_only: bool = False,
    skip_name_contradictions: bool = False,
) -> None:
    if boarded_only and unboarded_only:
        raise SystemExit("--boarded-only and --unboarded-only select disjoint sets; pass one")
    if strong_only and gotsport_only:
        raise SystemExit("--strong-only and --gotsport-only select disjoint sets; pass one")
    wanted = {"would_update"} | ({"would_update_collision"} if include_collisions else set())
    selected = [
        r
        for r in read_csv(plan_path)
        if r["action"] in wanted
        and r["team_id_master"] not in exclude
        and (not strong_only or is_strong(r))
        and (not gotsport_only or not is_strong(r))
        and (not boarded_only or r["new_age_group"] in AGE_GROUPS)
        and (not unboarded_only or r["new_age_group"] not in AGE_GROUPS)
    ]
    held, writable = [], []
    for r in selected:
        reason = name_contradiction(r["team_name"], r["new_age_group"]) if skip_name_contradictions else ""
        r["hold_reason"] = reason
        (held if reason else writable).append(r)
    # Apply in id order: effectively a random spread, so a --limit pilot samples every state.
    writable.sort(key=lambda r: r["team_id_master"])
    if limit:
        writable = writable[:limit]
    todo = writable + ([] if limit else sorted(held, key=lambda r: r["team_id_master"]))

    log_path = EXPORTS / f"fix_band_cohorts_apply_{datetime.now():%Y%m%d_%H%M%S}.csv"
    fields = PLAN_FIELDS + ["result", "hold_reason"]
    for r in todo:
        if r["hold_reason"]:
            r["result"] = "held_name_contradicts"
        else:
            r["result"] = "planned_not_applied" if execute else "would_update"
    write_csv(todo, log_path, fields)  # lands before the first write: the log is the way back

    print(
        f"=== Apply {plan_path.name} ({'EXECUTE' if execute else 'DRY RUN'}) : "
        f"{len(writable):,} to write, {len(held):,} held ==="
    )
    try:
        for i, r in enumerate(todo, 1):
            if not execute or r["hold_reason"]:
                continue
            updated = (
                sb.table("teams")
                .update({"age_group": r["new_age_group"]})
                .eq("team_id_master", r["team_id_master"])
                .eq("is_deprecated", False)
                .eq("age_group", r["old_age_group"])
                .execute()
                .data
            )
            r["result"] = "updated" if updated else classify_miss(sb, r["team_id_master"], r["new_age_group"])
            if i % 500 == 0:
                print(f"  {i:,} / {len(todo):,}")
                write_csv(todo, log_path, fields)
    finally:
        write_csv(todo, log_path, fields)

    print("\n=== Result ===")
    for result, n in Counter(r["result"] for r in todo).most_common():
        print(f"  {result:22s} {n:>6,}")
    print(f"\nLog: {log_path}")
    if execute:
        print(f"Undo with: python {Path(__file__).relative_to(ROOT)} --revert {log_path.relative_to(ROOT)} --execute")


def revert(sb, log_path: Path, execute: bool) -> None:
    rows = [r for r in read_csv(log_path) if r.get("result") == "updated"]
    print(f"=== Revert {log_path.name} ({'EXECUTE' if execute else 'DRY RUN'}) : {len(rows):,} rows ===")
    outcome = Counter()
    for r in rows:
        if not execute:
            outcome["would_revert"] += 1
            continue
        done = (
            sb.table("teams")
            .update({"age_group": r["old_age_group"]})
            .eq("team_id_master", r["team_id_master"])
            .eq("age_group", r["new_age_group"])
            .execute()
            .data
        )
        outcome["reverted" if done else "skipped_changed_since"] += 1
    for k, n in outcome.most_common():
        print(f"  {k:22s} {n:>6,}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", type=Path, help="Apply a plan CSV produced by a dry run")
    parser.add_argument("--revert", type=Path, help="Undo an apply log")
    parser.add_argument("--execute", action="store_true", help="Write to the database (default is a dry run)")
    parser.add_argument("--dry-run", action="store_true", help="Force a dry run; wins over --execute")
    parser.add_argument("--limit", type=int, help="Apply only the first N plan rows (pilot)")
    parser.add_argument(
        "--include-collisions", action="store_true", help="Also apply rows with a same-named team in the target cohort"
    )
    parser.add_argument(
        "--strong-only", action="store_true", help="Only rows with two independent signals (own-name band or opponents)"
    )
    parser.add_argument(
        "--boarded-only", action="store_true", help="Only rows whose new cohort is one the ranking boards rank"
    )
    parser.add_argument(
        "--unboarded-only",
        action="store_true",
        help="Only rows whose new cohort the boards do not rank (u9 and younger)",
    )
    parser.add_argument("--exclude", default="", help="Comma-separated team_id_master values to leave untouched")
    parser.add_argument(
        "--gotsport-only", action="store_true", help="Only rows whose evidence is GotSport's two-year band alone"
    )
    parser.add_argument(
        "--skip-name-contradictions", action="store_true", help="Hold rows whose own name states a different age"
    )
    args = parser.parse_args()
    execute = args.execute and not args.dry_run

    load_env()
    sb = get_supabase()
    if args.revert:
        revert(sb, args.revert, execute)
    elif args.apply:
        apply_plan(
            sb,
            args.apply,
            execute,
            args.limit,
            args.include_collisions,
            args.strong_only,
            args.boarded_only,
            args.unboarded_only,
            frozenset(x.strip() for x in args.exclude.split(",") if x.strip()),
            args.gotsport_only,
            args.skip_name_contradictions,
        )
    else:
        if args.execute:
            print("--execute without --apply does nothing: take a dry run, review the plan, then --apply it.")
        build_plan(sb)


if __name__ == "__main__":
    main()
