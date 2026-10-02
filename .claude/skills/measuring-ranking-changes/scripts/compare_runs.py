"""Compare two shadow board runs of the PitchRank ranking engine made on the same freeze.

  python compare_runs.py --base RUN_DIR --cand RUN_DIR --freeze FREEZE_DIR --out REPORT.json [--label TEXT]

Metrics
- rank: each run's own position among its Active teams on the (age, gender) board, by
  power_score_true descending with ties by team_id, mirroring rank_in_cohort_final. Moves are
  measured for teams Active in both runs; teams entering or leaving Active are counted in checks.
- points: power_score_final x 100, the published 0-100 scale.
- agreement with recorded results (in-sample): the share of the freeze's decided games between two
  teams Active in both runs, on the same board, that the higher-scored team won; equal scores count
  half. The ratings were fit to these same games, so it measures consistency, not prediction.
- ML swing: |ml_norm change| > ML_SWING between the runs (a size test, not a sign test).
- ceiling depth changed: publication_cap_rank differs between the runs.
Labels on big movers record a change that co-occurred with the move, not its cause.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd

TEAM_COLUMNS = [
    "team_id",
    "age_num",
    "gender",
    "status",
    "games_played",
    "mu",
    "powerscore_adj",
    "powerscore_ml",
    "power_score_true",
    "power_score_final",
    "last_calculated",
]
# ml_norm spans about [-0.5, +0.5]; a change this large moves a team across most of its board's scale.
ML_SWING = 0.3
MOVE_THRESHOLDS = (25, 100, 300)
PROVENANCE_KEYS = (
    "code_root",
    "code_head",
    "code_diff_sha256",
    "engine_file_sha256",
    "environment",
    "last_calculated_pinned_to",
    "fetch_code_not_measured",
)


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def load_run(run_dir: Path) -> dict:
    if not (run_dir / "completed.json").exists():
        raise SystemExit(f"{run_dir} has no completed.json; the board did not finish")
    teams = pd.read_parquet(run_dir / "teams.parquet", columns=TEAM_COLUMNS)
    teams["team_id"] = teams["team_id"].astype(str)
    precap = pd.concat(
        [
            pd.read_parquet(path, columns=["team_id", "ml_norm", "publication_cap_rank"])
            for path in sorted(run_dir.glob("pre-cap-u*.parquet"))
        ],
        ignore_index=True,
    )
    precap["team_id"] = precap["team_id"].astype(str)
    return {
        "teams": teams.set_index("team_id"),
        "precap": precap.set_index("team_id"),
        "completed": json.loads((run_dir / "completed.json").read_text(encoding="utf-8")),
        "provenance": json.loads((run_dir / "provenance.json").read_text(encoding="utf-8")),
    }


def published_ranks(teams: pd.DataFrame) -> pd.DataFrame:
    active = teams[teams["status"] == "Active"].reset_index()
    active = active.sort_values(
        ["age_num", "gender", "power_score_true", "team_id"], ascending=[True, True, False, True]
    )
    active["rank"] = active.groupby(["age_num", "gender"]).cumcount() + 1
    return active.set_index("team_id")[["age_num", "gender", "rank"]]


def board_movement(base: pd.DataFrame, cand: pd.DataFrame) -> list[dict]:
    base_ranks, cand_ranks = published_ranks(base), published_ranks(cand)
    both = base_ranks.index.intersection(cand_ranks.index)
    rows = []
    for (age, gender), board in base_ranks.loc[both].groupby(["age_num", "gender"]):
        ids = board.index
        move = cand_ranks.loc[ids, "rank"] - base_ranks.loc[ids, "rank"]
        delta = (cand.loc[ids, "power_score_final"] - base.loc[ids, "power_score_final"]) * 100
        on_board = {
            name: ranks.loc[(ranks["age_num"] == age) & (ranks["gender"] == gender), "rank"]
            for name, ranks in (("base", base_ranks), ("cand", cand_ranks))
        }
        entrants = {
            f"top{n}_entrants": len(
                set(on_board["cand"][on_board["cand"] <= n].index) - set(on_board["base"][on_board["base"] <= n].index)
            )
            for n in (25, 100)
        }
        rows.append(
            {
                "board": f"U{int(age)} {'boys' if str(gender).lower().startswith('m') else 'girls'}",
                "active_teams_in_both": len(ids),
                "scores_changed": int((delta.abs() > 1e-9).sum()),
                "ranks_changed": int((move != 0).sum()),
                "median_rank_move_of_movers": float(move[move != 0].abs().median()) if (move != 0).any() else 0.0,
                "largest_rank_move": int(move.abs().max()),
                "points_delta_median_abs": float(delta.abs().median()),
                "points_delta_p90_abs": float(delta.abs().quantile(0.9)),
                "points_delta_max_abs": float(delta.abs().max()),
                "points_delta_min": float(delta.min()),
                "points_delta_max": float(delta.max()),
                **entrants,
            }
        )
    return rows


def big_movers(base: dict, cand: dict) -> dict:
    base_ranks, cand_ranks = published_ranks(base["teams"]), published_ranks(cand["teams"])
    both = base_ranks.index.intersection(cand_ranks.index)
    for name, run in (("base", base), ("cand", cand)):
        missing = both.difference(run["precap"].index)
        if len(missing):
            raise SystemExit(f"{name}: {len(missing)} Active teams have no pre-cap row, e.g. {list(missing[:3])}")
    move = cand_ranks.loc[both, "rank"] - base_ranks.loc[both, "rank"]
    ml_swing = (cand["precap"]["ml_norm"].reindex(both) - base["precap"]["ml_norm"].reindex(both)).abs() > ML_SWING
    ceiling_changed = pd.Series(
        base["precap"]["publication_cap_rank"].reindex(both).fillna(-1).values
        != cand["precap"]["publication_cap_rank"].reindex(both).fillna(-1).values,
        index=both,
    )
    out: dict = {}
    for n in MOVE_THRESHOLDS:
        big = move[move.abs() > n].index
        # Later assignments win, so an ML swing is listed ahead of a ceiling change.
        label = pd.Series("other", index=big)
        label[ceiling_changed.reindex(big).values] = "ceiling depth changed"
        label[ml_swing.reindex(big).values] = "ML swing over 0.3"
        out[f"moved_more_than_{n}"] = {"teams": int(len(big)), "by_co_occurring_change": label.value_counts().to_dict()}
    out["active_teams_rank_changed"] = int((move != 0).sum())
    out["active_teams_with_ml_swing"] = int(ml_swing.sum())
    out["active_teams_with_ceiling_change"] = int(ceiling_changed.sum())
    return out


def decided_board_games(freeze_dir: Path, base: pd.DataFrame, cand: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    # Team ids are used as stored: the freeze's games were merge-resolved when fetched, and the
    # engine rates them without resolving again.
    games = pd.read_parquet(freeze_dir / "games.parquet", columns=["id", "team_id", "opp_id", "gf", "ga"])
    team, opp = games["team_id"].astype(str), games["opp_id"].astype(str)
    # Each game appears once per side; orienting on the lower id and de-duplicating by game id counts it once.
    swap = team > opp
    frame = pd.DataFrame(
        {
            "id": games["id"].astype(str),
            "a": team.where(~swap, opp),
            "b": opp.where(~swap, team),
            "gf_a": games["gf"].where(~swap, games["ga"]),
            "ga_a": games["ga"].where(~swap, games["gf"]),
        }
    )
    frame = frame[frame["a"] != frame["b"]].drop_duplicates("id")
    active = base[base["status"] == "Active"]
    for side in ("a", "b"):
        frame = frame.join(active[["age_num", "gender"]].add_suffix(f"_{side}"), on=side, how="inner")
    frame = frame[(frame["age_num_a"] == frame["age_num_b"]) & (frame["gender_a"] == frame["gender_b"])]
    frame = frame[frame["gf_a"] != frame["ga_a"]]
    cand_active = cand.index[cand["status"] == "Active"]
    in_both = frame["a"].isin(cand_active) & frame["b"].isin(cand_active)
    return frame[in_both], int((~in_both).sum())


def agreement(frame: pd.DataFrame, scores: pd.Series) -> pd.Series:
    sa = scores.reindex(frame["a"]).values
    sb = scores.reindex(frame["b"]).values
    a_won = (frame["gf_a"] > frame["ga_a"]).values
    hit = ((sa > sb) & a_won) | ((sa < sb) & ~a_won)
    credit = pd.Series(hit.astype(float) + 0.5 * (sa == sb), index=frame.index)
    boards = frame["age_num_a"].astype(int).astype(str) + frame["gender_a"].astype(str).str[0].str.upper()
    by_board = credit.groupby(boards).mean()
    by_board["ALL"] = credit.mean()
    return by_board


def utc_days(teams: pd.DataFrame) -> list[str]:
    stamps = pd.to_datetime(teams["last_calculated"], utc=True)
    return sorted({str(d) for d in stamps.dt.date.dropna()})


def run_checks(base: dict, cand: dict, freeze_dir: Path) -> dict:
    base_freeze, cand_freeze = base["provenance"]["freeze_manifest"], cand["provenance"]["freeze_manifest"]
    keys = ("games_sha256", "teams_metadata_sha256", "merge_map_sha256")
    if any(base_freeze[k] != cand_freeze[k] for k in keys):
        raise SystemExit("the two runs used different frozen inputs; compare runs made on the same freeze")
    if sha256(freeze_dir / "games.parquet") != base_freeze["games_sha256"]:
        raise SystemExit(f"{freeze_dir / 'games.parquet'} is not the games file these runs used")

    bt, ct = base["teams"], cand["teams"]
    # Outer, so a team one run dropped entirely still counts: it is "absent" with no games.
    joined = bt[["status", "games_played"]].join(ct[["status", "games_played"]], rsuffix="_c", how="outer")
    joined[["status", "status_c"]] = joined[["status", "status_c"]].fillna("absent")
    joined[["games_played", "games_played_c"]] = joined[["games_played", "games_played_c"]].fillna(0)
    min_games = base["provenance"]["glicko_config"]["MIN_GAMES_PROVISIONAL"]
    engine_cols = ["mu", "powerscore_adj", "powerscore_ml"]
    before, after = bt[engine_cols].reindex(ct.index), ct[engine_cols]
    engine_changed = (~((before == after) | (before.isna() & after.isna()))).any(axis=1)
    base_days, cand_days = utc_days(bt), utc_days(ct)
    base_calls, cand_calls = base["completed"]["frozen_client_calls"], cand["completed"]["frozen_client_calls"]
    config_differences = {}
    for section in ("glicko_config", "ml_config", "environment"):
        old, new = base["provenance"].get(section) or {}, cand["provenance"].get(section) or {}
        config_differences[section] = sorted(k for k in set(old) | set(new) if old.get(k) != new.get(k))
    return {
        "same_today": base["provenance"]["today"] == cand["provenance"]["today"],
        "same_team_set": bool(bt.index.sort_values().equals(ct.index.sort_values())),
        "teams_only_in_base": int(len(bt.index.difference(ct.index))),
        "teams_only_in_cand": int(len(ct.index.difference(bt.index))),
        "same_frozen_client_calls": base_calls == cand_calls,
        "became_active": int(((joined["status"] != "Active") & (joined["status_c"] == "Active")).sum()),
        "left_active": int(((joined["status"] == "Active") & (joined["status_c"] != "Active")).sum()),
        "crossed_min_games_up": int(
            ((joined["games_played"] < min_games) & (joined["games_played_c"] >= min_games)).sum()
        ),
        "crossed_min_games_down": int(
            ((joined["games_played"] >= min_games) & (joined["games_played_c"] < min_games)).sum()
        ),
        "games_played_changes": int((joined["games_played"] != joined["games_played_c"]).sum()),
        "teams_with_engine_or_ml_change": int(engine_changed.sum()),
        "last_calculated_utc_days": {"base": base_days, "cand": cand_days},
        "gate_columns_comparable": base_days == cand_days and len(base_days) == 1,
        "config_differences": config_differences,
        # A list when the freeze fingerprinted its fetch code; None when it reused saved games.
        "fetch_code_not_measured": cand["provenance"].get("fetch_code_not_measured"),
    }


def warnings(checks: dict) -> list[str]:
    out = []
    if not checks["gate_columns_comparable"]:
        out.append(
            "last_calculated falls on different UTC days in the two runs, so gate and ceiling outputs differ for "
            "that reason alone; trust teams_with_engine_or_ml_change, not the published movement."
        )
    if checks["became_active"] or checks["left_active"] or not checks["same_team_set"]:
        out.append(
            f"{checks['became_active']} teams became Active and {checks['left_active']} left Active "
            f"({checks['teams_only_in_base']} exist only in the base run, {checks['teams_only_in_cand']} only in the "
            "candidate); movement covers teams Active in both runs, so report these counts and the min-games "
            "crossings beside it."
        )
    if checks["fetch_code_not_measured"]:
        out.append(
            f"the candidate's games-fetch code differs from the freeze's ({checks['fetch_code_not_measured']}); "
            "a board never runs the fetch, so that part of the change is not in these numbers."
        )
    changed = {k: v for k, v in checks["config_differences"].items() if v}
    if changed:
        out.append(f"configuration differs between the runs: {changed}")
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base", required=True, help="baseline run directory")
    parser.add_argument("--cand", required=True, help="candidate run directory")
    parser.add_argument("--freeze", required=True, help="the freeze both runs used")
    parser.add_argument("--out", required=True, help="new JSON report path")
    parser.add_argument("--label", default="", help="free-text label stored in the report")
    args = parser.parse_args()

    out = Path(args.out)
    if out.exists():
        raise SystemExit(f"{out} exists")
    base, cand = load_run(Path(args.base)), load_run(Path(args.cand))
    checks = run_checks(base, cand, Path(args.freeze))
    frame, excluded = decided_board_games(Path(args.freeze), base["teams"], cand["teams"])
    table = pd.DataFrame(
        {
            "base engine": agreement(frame, base["teams"]["mu"]),
            "cand engine": agreement(frame, cand["teams"]["mu"]),
            "base published": agreement(frame, base["teams"]["power_score_true"]),
            "cand published": agreement(frame, cand["teams"]["power_score_true"]),
        }
    )
    report = {
        "label": args.label,
        "base": args.base,
        "cand": args.cand,
        "checks": checks,
        "warnings": warnings(checks),
        "movement": board_movement(base["teams"], cand["teams"]),
        "big_movers": big_movers(base, cand),
        "agreement_with_recorded_results_pct": (table * 100).round(3).reset_index().to_dict(orient="records"),
        "agreement_decided_games": int(len(frame)),
        "agreement_games_excluded_for_status_change": excluded,
        "freeze_manifest": base["provenance"]["freeze_manifest"],
        "provenance": {
            "base": {k: base["provenance"].get(k) for k in PROVENANCE_KEYS},
            "cand": {k: cand["provenance"].get(k) for k in PROVENANCE_KEYS},
        },
    }
    out.write_text(json.dumps(report, indent=2, default=str, allow_nan=False), encoding="utf-8")

    pd.set_option("display.width", 250)
    print(json.dumps({k: report[k] for k in ("label", "checks", "big_movers")}, indent=2, default=str))
    for line in report["warnings"]:
        print("WARNING:", line)
    print(pd.DataFrame(report["movement"]).to_string(index=False))
    print((table * 100).round(2).to_string())


if __name__ == "__main__":
    main()
