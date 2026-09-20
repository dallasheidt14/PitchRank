#!/usr/bin/env python3
"""
Weekly, read-only re-check of teams whose age group GotSport says is younger but that
could not be safely corrected yet. Writes nothing to the database.

Why weekly: most were held for lack of evidence, not for contrary evidence. It was
mid-September when they were first checked and many teams had played few games, so
the witnesses -- opponents whose OWN names carry a two-year range such as "2015/16",
which is correct in any season -- accumulate as the season goes on.

Population, derived fresh each run (never a hand-kept list):
  every team in the reconcile_teams_with_gotsport logs where GotSport's age group is
  younger than ours, still true in the live table, and not deprecated.
That covers every earlier hold: too little evidence, play-up teams, name
contradictions and duplicates alike, because the same rules re-judge all of them.

A team qualifies under exactly the rules the user approved for the 2026-09-15 batches:
  * at least 2 games this season against range-named opponents, 3:1 for GotSport's age
  * our own name does not state a clearly different age
  * no identical team (name + gender) already sits in the new age group

Outputs, in data/exports/:
  weekly_age_recheck_<date>.md      the summary to read
  weekly_age_recheck_plan_<date>.csv  qualifying teams, in fix_band_cohorts.py plan format
  weekly_age_recheck_history.csv    one row per run, so progress is visible week to week

Applying is a separate, approved step:
  python scripts/fix_band_cohorts.py --apply <plan> --skip-name-contradictions --limit 50 --execute
"""

from __future__ import annotations

import csv
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

from config.settings import AGE_GROUPS  # noqa: E402
from scripts import fix_band_cohorts as fbc  # noqa: E402
from src.utils.age_group import normalize_age_group  # noqa: E402

EXPORTS = ROOT / "data" / "exports"
MIN_GAMES = 2


def pending_population(sb) -> list[dict]:
    latest: dict[str, dict] = {}
    for path in sorted(EXPORTS.glob("reconcile_teams_with_gotsport_*.csv")):
        try:
            for row in fbc.read_csv(path):
                if (row.get("run_mode") or "").lower() == "execute":
                    latest[row["team_id_master"]] = row
        except Exception as e:
            print(f"  skipped unreadable log {path.name}: {e}")

    audit = {}
    for row in latest.values():
        ours = normalize_age_group(row.get("stored_age_group"))
        gs = normalize_age_group(row.get("gotsport_age_group"))
        if ours and gs and fbc.age_num(gs) < fbc.age_num(ours):
            audit[row["team_id_master"]] = row

    live = fbc.fetch_live(sb, list(audit))
    rows = []
    for tid, row in audit.items():
        team = live.get(tid)
        if not team or team.get("is_deprecated"):
            continue
        current = normalize_age_group(team.get("age_group"))
        target = normalize_age_group(row.get("gotsport_age_group"))
        # Already fixed (by a batch or by hand), or moved somewhere that no longer
        # disagrees in this direction: nothing left to decide.
        if not current or current == target or fbc.age_num(target) >= fbc.age_num(current):
            continue
        rows.append(
            {
                "team_id_master": tid,
                "state_code": team.get("state_code") or "",
                "team_name": team.get("team_name") or "",
                "club_name": team.get("club_name") or "",
                "gender": team.get("gender") or "",
                "gotsport_team_name": row.get("gotsport_team_name") or "",
                "band": "",
                "old_age_group": team.get("age_group") or "",
                "new_age_group": target,
                "collision_with": "",
                "evidence_tier": "W_weekly_recheck",
            }
        )
    return rows


def main() -> None:
    fbc.load_env()
    sb = fbc.get_supabase()
    stamp = datetime.now().strftime("%Y%m%d")
    print("Deriving the pending population...", flush=True)
    rows = pending_population(sb)
    print(f"Pending: {len(rows):,}. Reading this season's fixtures...", flush=True)
    fbc.attach_fixture_evidence(sb, rows)

    for r in rows:
        reason = fbc.name_contradiction(r["team_name"], r["new_age_group"])
        confirmed = r["fixture_verdict"] == "backs_move" and r["opp_games_proposed"] >= MIN_GAMES
        if not confirmed:
            r["action"] = f"waiting_{r['fixture_verdict']}"
        elif reason:
            r["action"] = "held_name_contradicts"
            r["hold_reason"] = reason
        else:
            r["action"] = "would_update"

    movers = {r["team_id_master"]: r for r in rows if r["action"] == "would_update"}
    print(f"{len(movers):,} confirmed. Paging live teams for the duplicate check...", flush=True)
    index: dict[tuple, set] = defaultdict(set)
    for t in fbc.fetch_all_live_teams(sb):
        tid = t["team_id_master"]
        cohort = movers[tid]["new_age_group"] if tid in movers else normalize_age_group(t.get("age_group"))
        index[(fbc.norm_name(t.get("team_name")), t.get("gender") or "", cohort)].add(tid)
    for tid, r in movers.items():
        others = index[(fbc.norm_name(r["team_name"]), r["gender"], r["new_age_group"])] - {tid}
        if others:
            r["action"] = "would_update_collision"
            r["collision_with"] = ";".join(sorted(others)[:3])

    qualifying = sorted(
        (r for r in rows if r["action"] == "would_update"),
        key=lambda r: (r["state_code"], r["team_name"]),
    )
    plan_path = EXPORTS / f"weekly_age_recheck_plan_{stamp}.csv"
    fbc.write_csv(qualifying, plan_path, fbc.PLAN_FIELDS)

    counts = Counter(r["action"] for r in rows)
    off_board = sum(1 for r in qualifying if r["new_age_group"] not in AGE_GROUPS)
    p = sum(r["opp_games_proposed"] for r in qualifying)
    c = sum(r["opp_games_current"] for r in qualifying)
    agreement = f"{100 * p / (p + c):.1f}%" if p + c else "n/a"

    history = EXPORTS / "weekly_age_recheck_history.csv"
    previous = fbc.read_csv(history)[-1] if history.exists() and fbc.read_csv(history) else None
    hist_row = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "pending": len(rows),
        "qualifying": len(qualifying),
        "waiting_thin": counts.get("waiting_thin", 0),
        "waiting_backs_current": counts.get("waiting_backs_current", 0),
        "waiting_mixed": counts.get("waiting_mixed", 0),
        "held_name_contradicts": counts.get("held_name_contradicts", 0),
        "held_duplicate": counts.get("would_update_collision", 0),
    }
    new_file = not history.exists()
    with history.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(hist_row))
        if new_file:
            w.writeheader()
        w.writerow(hist_row)

    trend = ""
    if previous:
        trend = (
            f"\nLast run ({previous['date']}): {int(previous['pending']):,} pending, "
            f"{int(previous['qualifying']):,} qualifying, {int(previous['waiting_thin']):,} waiting for games.\n"
        )
    samples = "\n".join(
        f"| {r['state_code']} | {r['old_age_group'].upper()} -> {r['new_age_group'].upper()} | "
        f"{r['opp_games_proposed']} v {r['opp_games_current']} | {r['team_name'][:48]} |"
        for r in qualifying[:: max(1, len(qualifying) // 15)][:15]
    )
    by_state = ", ".join(f"{k} {v:,}" for k, v in Counter(r["state_code"] for r in qualifying).most_common(10))
    report = f"""# Weekly age-group re-check — {hist_row['date']}

Read-only. Nothing was written to the database.

**{len(qualifying):,} teams now qualify** for a correction under the approved rules
(of {len(rows):,} still pending).{trend}

| Status | Teams |
|---|---|
| Qualify now | {len(qualifying):,} |
| Waiting — not enough games against range-named opponents yet | {counts.get('waiting_thin', 0):,} |
| Waiting — opponents back our current age group (likely playing up) | {counts.get('waiting_backs_current', 0):,} |
| Waiting — mixed opponents | {counts.get('waiting_mixed', 0):,} |
| Held — our name states a different age | {counts.get('held_name_contradicts', 0):,} |
| Held — identical team already in the new age group | {counts.get('would_update_collision', 0):,} |

Qualifying teams' range-named opponents side with the new age group: **{agreement}**
({p:,} v {c:,} games). {off_board:,} of them move to U9 or younger.

By state: {by_state or 'none'}

| State | Move | Opponent games (new v current) | Team |
|---|---|---|---|
{samples}

## To apply (after review)

```
python scripts/fix_band_cohorts.py --apply {plan_path.relative_to(ROOT)} --skip-name-contradictions --limit 50 --execute
python scripts/fix_band_cohorts.py --apply {plan_path.relative_to(ROOT)} --skip-name-contradictions --execute
```

Verify in the database afterwards; each apply log carries its own undo command.
"""
    report_path = EXPORTS / f"weekly_age_recheck_{stamp}.md"
    report_path.write_text(report, encoding="utf-8")
    print(report)
    print(f"Report: {report_path}\nPlan:   {plan_path}")


if __name__ == "__main__":
    # Run unattended by Task Scheduler, where stdout goes nowhere: record the outcome,
    # so a week with no report is explained rather than silent.
    last_run = EXPORTS / "weekly_age_recheck_last_run.log"
    started = datetime.now().isoformat(timespec="seconds")
    try:
        main()
        last_run.write_text(f"{started} ok\n", encoding="utf-8")
    except BaseException:
        import traceback

        last_run.write_text(f"{started} FAILED\n{traceback.format_exc()}", encoding="utf-8")
        raise
