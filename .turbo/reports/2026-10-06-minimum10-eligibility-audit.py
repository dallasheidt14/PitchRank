"""Recheck the approved 10-game eligibility policy on saved selection evidence.

Reads archived rows only. Does not fetch data, calculate ratings, or publish.
Usage: python this_file.py --selection DIR --baseline DIR --out DIR
"""
import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--selection", required=True, type=Path)
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    receipt = json.loads((args.selection / "completed.json").read_text())
    for filename, expected in receipt["output_sha256"].items():
        assert digest(args.selection / filename) == expected, filename
    for path, expected in receipt["inputs"].items():
        assert digest(path) == expected, path
    rows = pd.read_parquet(args.selection / "per-team.parquet")
    selected = pd.read_parquet(args.selection / "selected.parquet")
    assert rows.team_id.is_unique
    assert not selected.duplicated(["team_id", "game_id"]).any()
    counts = selected.groupby("team_id").size().reindex(rows.team_id).fillna(0).to_numpy()
    assert (counts == rows.new_games).all()
    last = pd.to_datetime(selected.date).groupby(selected.team_id).max().reindex(rows.team_id)
    recorded = pd.to_datetime(rows.new_last_game)
    assert ((last.to_numpy() == recorded.to_numpy()) | (last.isna().to_numpy() & recorded.isna().to_numpy())).all()
    today = pd.Timestamp(receipt["as_of"])
    recent = recorded.ge(today - pd.Timedelta(days=180)) & recorded.le(today)
    recent60 = recorded.ge(today - pd.Timedelta(days=60)) & recorded.le(today)
    rows["eligible12"] = recent & rows.new_games.ge(12)
    rows["eligible10"] = recent & rows.new_games.ge(10)
    assert rows.eligible12.equals(rows.new_status.eq("Active"))
    rows["previously_active"] = rows.status.eq("Active")
    rows["lost_at12"] = rows.previously_active & ~rows.eligible12
    rows["restored"] = rows.lost_at12 & rows.eligible10
    rows["leaving"] = rows.previously_active & ~rows.eligible10
    rows["newly_eligible"] = ~rows.previously_active & rows.eligible10
    def counts_for(frame):
        result = {key: int(frame[key].sum()) for key in ["previously_active", "eligible12", "eligible10", "lost_at12", "restored", "leaving", "newly_eligible"]}
        assert result["previously_active"] - result["leaving"] + result["newly_eligible"] == result["eligible10"]
        return result
    totals = counts_for(rows)
    totals.update({"restored_recent60": int((rows.restored & recent60).sum()),
                   "leaving_recent60": int((rows.leaving & recent60).sum()),
                   "newly_eligible_recent60": int((rows.newly_eligible & recent60).sum())})
    boards = [{"age": str(age), "gender": str(gender), **counts_for(frame)} for (age, gender), frame in rows.groupby(["age", "gender"])]
    assert len(boards) == 18
    ranks = pd.read_parquet(args.baseline / "teams.parquet", columns=["team_id", "rank_in_cohort_final"])
    joined = rows.merge(ranks, on="team_id", validate="one_to_one")
    top = joined.loc[joined.lost_at12 & joined.rank_in_cohort_final.le(100), ["team_id", "age", "gender", "rank_in_cohort_final", "new_games", "eligible10"]]
    root = Path(__file__).resolve().parents[2]
    report = {"as_of": str(today.date()), "policy": "Newest 30 valid games within 365 days, minimum 10; inactivity still 180 days",
              "owner_approval": "October 6, 2026: ok lets go with the 10",
              "scope": "Eligibility-only reclassification of verified archived selected games; not final ranking movement or current live counts",
              "totals": totals, "boards": boards,
              "old_top100_lost_at12": json.loads(top.to_json(orient="records")),
              "selected_games_sha256": digest(args.selection / "selected.parquet"),
              "selection_receipt_sha256": digest(args.selection / "completed.json"),
              "baseline_teams_sha256": digest(args.baseline / "teams.parquet"),
              "per_team_sha256": digest(args.selection / "per-team.parquet"),
              "source_sha256": {rel: digest(root / rel) for rel in ["src/etl/glicko_config.py", "src/etl/glicko_engine.py", "src/rankings/calculator.py"]},
              "limits": ["Saved August inputs; not today's live eligibility.", "Rank movement and effects on SOS or ceilings require the combined full preview.", "The archived 12-game audit is preserved separately.", "No October outcomes, prediction scoring, live database reads or publication."]}
    args.out.mkdir(parents=True, exist_ok=False)
    (args.out / "evidence.json").write_text(json.dumps(report, indent=2) + "\n")
    lines = ["# Approved 10-game minimum: eligibility impact", "", "The owner approved 10 games on October 6, 2026. Newest-30/365 selection stays fixed. The earlier 12-game report is historical; this addendum supersedes only its minimum-game policy and eligibility projection.", "", "## Saved August 31 snapshot", "", f"Of the 1,095 previously ranked teams that fell below 12 after expired games were removed, **{totals['restored']:,} remain eligible at 10** and **{totals['leaving']:,} still fall out**. Of the 504 with a game in the prior 60 days, {totals['restored_recent60']:,} are restored and {totals['leaving_recent60']:,} still fall out.", "", f"Another **{totals['newly_eligible']:,} previously unranked teams** qualify, including {totals['newly_eligible_recent60']:,} with a game in the prior 60 days. Eligibility rises from {totals['previously_active']:,} to **{totals['eligible10']:,}**: {totals['previously_active']:,} - {totals['leaving']:,} + {totals['newly_eligible']:,}. These are archived-data eligibility counts, not completed candidate ranks or current production counts.", "", "## All 18 boards", "", "| Board | Previously ranked | Restored from 12-game losses | Still leave | Newly eligible | Eligible at 10 |", "|---|---:|---:|---:|---:|---:|"]
    for b in sorted(boards, key=lambda b: (int(b["age"]), b["gender"])):
        lines.append(f"| U{b['age']} {b['gender']} | {b['previously_active']:,} | {b['restored']:,} | {b['leaving']:,} | {b['newly_eligible']:,} | {b['eligible10']:,} |")
    lines += ["", "## Previously top-100 teams affected by the 12-game cutoff", "", "These are archived baseline positions, not new positions. Qualifying for a rank does not establish support for a high placement.", "", "| Team ID | Board | Old rank | Games in new window | Eligible at 10 |", "|---|---|---:|---:|---|"]
    for r in report["old_top100_lost_at12"]:
        lines.append(f"| {r['team_id']} | U{r['age']} {r['gender']} | {int(r['rank_in_cohort_final'])} | {r['new_games']} | {'Yes' if r['eligible10'] else 'No'} |")
    lines += ["", "## Verification and limits", "", "The saved selection receipt, all four output hashes, original input hashes, distinct team/game pairs, selected-game counts and latest-game dates were verified. Reapplying 12 exactly reproduced the prior eligibility labels; reapplying 10 produced the counts above. The 10-game policy changes eligibility, not game selection. Inactivity and the separate ML/evidence-support thresholds remain unchanged. Ceiling safeguards are supplied by PR #1255 and will be retained in the combined preview.", "", "The combined preview must check final ranks, newly eligible high placements, all boards, and the Texas/Washington cases. No ranking improvement or safe publication is inferred from eligibility counts alone.", "", "Source and artifact hashes are in the companion evidence JSON. The original September and 12-game reports remain intact.", ""]
    (args.out / "report.md").write_text("\n".join(lines))
    print(json.dumps(totals))


if __name__ == "__main__":
    main()
