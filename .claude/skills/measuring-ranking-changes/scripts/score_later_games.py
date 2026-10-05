"""Score candidate runs against a baseline on held-out games played after the split date (a time split).

Every run should rate the training freeze, whose manifest `today` is the split date, and --start should
fall after that date. The report's `isolation` block records what can be checked about the runs and the
freeze, but verdicts are written whether or not it passes, and nothing compares --start with the split.
The primary measure is published-score (power_score_true) agreement on decided same-board held-out games
between teams Active in the baseline and in every candidate passed in this call: per game, credit 1 when
the team with the higher power_score_true won and 0.5 when the two scores tie. Each candidate's mean
per-game credit difference against the baseline gets a dyadic-robust standard error (games sharing a team
are correlated), and Holm adjusts the primary p-values across the candidates scored in one call. The
verdict rules in main and the constants below were locked before scoring; change them only before any
held-out outcome is seen.

Usage:
  python score_later_games.py --base RUN --cand NAME=RUN [--cand NAME=RUN ...]
      --train-freeze FREEZE --heldout-freeze LATER_FREEZE --start YYYY-MM-DD --end YYYY-MM-DD
      [--scf-cand NAME] --out REPORT.json
"""

import argparse
import json
import math
import re
from pathlib import Path

import numpy as np
import pandas as pd

WORTHWHILE_GAIN = 0.25  # points of published agreement
BOARD_HARM = 1.0  # points: harmed if a board's 95% upper bound is below -BOARD_HARM, flagged if only its estimate is
ALPHA = 0.05
CUT_SCF = 0.6
CUT_MIN_GAMES = 300
CUT_HARM = 1.0
CUT_LOWER_BOUND = 2.0
ALLOWED_CALLS = {
    "team_merge_map.select(deprecated_team_id,canonical_team_id).range",
    "teams.select(team_id_master,state_code,league).in_(team_id_master)",
    "teams.select(team_id_master).in_(team_id_master).eq(is_deprecated)",
}
TEAM_COLS = ["team_id", "status", "age_num", "gender", "power_score_true", "power_score_final", "mu", "sigma", "scf",
             "last_calculated", "state_code"]


def _read_teams(path: Path) -> pd.DataFrame:
    # A run with dampening off writes no scf column.
    teams = pd.read_parquet(path)
    return teams[[c for c in TEAM_COLS if c in teams.columns]].set_index("team_id")


def load_run(run_dir: Path) -> dict:
    return {
        "dir": str(run_dir),
        "teams": _read_teams(run_dir / "teams.parquet"),
        "completed": json.loads((run_dir / "completed.json").read_text(encoding="utf-8")),
        "provenance": json.loads((run_dir / "provenance.json").read_text(encoding="utf-8")),
    }


def isolation_checks(runs: dict, train_freeze: Path) -> dict:
    manifest = json.loads((train_freeze / "freeze-manifest.json").read_text(encoding="utf-8"))
    today = pd.Timestamp(manifest["today"])
    dates = pd.to_datetime(pd.read_parquet(train_freeze / "games.parquet", columns=["date"])["date"])
    out = {"freeze_today": str(today.date()), "freeze_latest_game": str(dates.max().date()),
           "freeze_games_after_today": int((dates.dt.normalize() > today).sum()), "runs": {}}
    for name, run in runs.items():
        calls = set(run["completed"].get("frozen_client_calls", {}))
        stamps = pd.to_datetime(run["teams"]["last_calculated"], utc=True).dt.date.dropna().unique()
        out["runs"][name] = {
            "same_freeze": run["provenance"]["freeze_manifest"]["games_sha256"] == manifest["games_sha256"],
            "unexpected_client_calls": sorted(calls - ALLOWED_CALLS),
            "last_calculated_dates": sorted(str(d) for d in stamps),
        }
    out["passed"] = out["freeze_games_after_today"] == 0 and all(
        r["same_freeze"] and not r["unexpected_client_calls"] and r["last_calculated_dates"] == [out["freeze_today"]]
        for r in out["runs"].values()
    )
    return out


def resolve(ids: pd.Series, merge: dict) -> pd.Series:
    out = ids.astype(str)
    for _ in range(10):
        nxt = out.map(lambda t: merge.get(t, t))
        if nxt.equals(out):
            break
        out = nxt
    return out


def heldout_games(heldout_freeze: Path, train_freeze: Path, start: str, end: str) -> tuple[pd.DataFrame, dict]:
    g = pd.read_parquet(heldout_freeze / "games.parquet", columns=["id", "team_id", "opp_id", "gf", "ga", "date"])
    g["date"] = pd.to_datetime(g["date"])
    g = g[(g["date"] >= start) & (g["date"] <= end)].dropna(subset=["gf", "ga"])
    merge_df = pd.read_parquet(train_freeze / "merge-map.parquet")
    merge = dict(zip(merge_df["deprecated_team_id"].astype(str), merge_df["canonical_team_id"].astype(str)))
    team, opp = resolve(g["team_id"], merge), resolve(g["opp_id"], merge)
    swap = team > opp
    frame = pd.DataFrame({
        "id": g["id"].astype(str).values,
        "a": team.where(~swap, opp).values,
        "b": opp.where(~swap, team).values,
        "gf_a": g["gf"].where(~swap, g["ga"]).values,
        "ga_a": g["ga"].where(~swap, g["gf"]).values,
    })
    frame = frame[frame["a"] != frame["b"]].drop_duplicates("id")
    counts = {"games": int(len(frame)), "draws": int((frame["gf_a"] == frame["ga_a"]).sum())}
    return frame[frame["gf_a"] != frame["ga_a"]].reset_index(drop=True), counts


def credit(frame: pd.DataFrame, scores: pd.Series) -> np.ndarray:
    sa, sb = scores.reindex(frame["a"]).values, scores.reindex(frame["b"]).values
    a_won = (frame["gf_a"] > frame["ga_a"]).values
    return np.where(sa == sb, 0.5, (((sa > sb) & a_won) | ((sa < sb) & ~a_won)).astype(float))


def dyadic(frame: pd.DataFrame, d: np.ndarray) -> dict:
    n = len(d)
    if n == 0:
        return {"n": 0, "delta": None, "se": None, "z": None, "p": None, "ci95": None}
    mean = float(d.mean())
    c = d - mean
    per_team = pd.concat([pd.Series(c, index=frame["a"].values), pd.Series(c, index=frame["b"].values)])
    s_t = per_team.groupby(level=0).sum()
    pair = frame["a"].values + "|" + frame["b"].values
    p_p = pd.Series(c, index=pair).groupby(level=0).sum()
    var = max(float((s_t**2).sum() - (p_p**2).sum()), 0.0) / n**2
    se = math.sqrt(var)
    z = mean / se if se > 0 else 0.0
    p = math.erfc(abs(z) / math.sqrt(2))
    return {"n": n, "delta": 100 * mean, "se": 100 * se, "z": z, "p": p,
            "ci95": [100 * (mean - 1.96 * se), 100 * (mean + 1.96 * se)]}


def holm(pvalues: dict) -> dict:
    order = sorted(pvalues, key=lambda k: pvalues[k])
    m, running, out = len(order), 0.0, {}
    for i, k in enumerate(order):
        running = max(running, min(1.0, (m - i) * pvalues[k]))
        out[k] = running
    return out


def pass_diagnostics(console_log: Path) -> list[dict]:
    passes, cur = [], None
    for line in console_log.read_text(encoding="utf-8", errors="replace").splitlines():
        m = re.search(r"Starting Glicko-2 ranking engine \[(Pass\d)\]", line)
        if m:
            cur = {"pass": m.group(1), "rounds": 0, "stop": None, "max_delta": None, "mean_delta": None, "teams": None}
            passes.append(cur)
            continue
        if cur is None:
            continue
        m = re.search(r"Glicko-2 iteration (\d+): max_delta=([\d.]+), mean_delta=([\d.]+)", line)
        if m:
            cur.update(rounds=int(m.group(1)), max_delta=float(m.group(2)), mean_delta=float(m.group(3)))
        if "Glicko-2 converged after" in line:
            cur["stop"] = "converged"
        elif "did not converge after" in line:
            cur["stop"] = "cap"
        m = re.search(r"Glicko-2 engine complete \[Pass\d\]: (\d+) teams", line)
        if m:
            cur["teams"] = int(m.group(1))
    return passes


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--cand", action="append", required=True, help="name=run_dir")
    ap.add_argument("--train-freeze", required=True)
    ap.add_argument("--heldout-freeze", required=True)
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--scf-cand", default="scf", help="candidate name the dampening cut applies to")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    out_path = Path(args.out)
    if out_path.exists():
        raise SystemExit(f"{out_path} exists")

    runs = {"base": load_run(Path(args.base))}
    for spec in args.cand:
        name, path = spec.split("=", 1)
        runs[name] = load_run(Path(path))
    cands = [k for k in runs if k != "base"]
    base = runs["base"]["teams"]

    report = {"rule": {"worthwhile_gain": WORTHWHILE_GAIN, "board_harm": BOARD_HARM, "alpha": ALPHA, "cut_scf": CUT_SCF,
                       "cut_min_games": CUT_MIN_GAMES, "cut_harm": CUT_HARM, "cut_lower_bound": -CUT_LOWER_BOUND},
              "runs": {k: v["dir"] for k, v in runs.items()}}
    report["isolation"] = isolation_checks(runs, Path(args.train_freeze))

    games, counts = heldout_games(Path(args.heldout_freeze), Path(args.train_freeze), args.start, args.end)
    active_all = set.intersection(*(set(r["teams"].index[r["teams"]["status"] == "Active"]) for r in runs.values()))
    both = games["a"].isin(active_all) & games["b"].isin(active_all)
    board = base["age_num"].astype("Int64").astype(str) + base["gender"].astype(str).str[0].str.upper()
    ba, bb = board.reindex(games["a"]).values, board.reindex(games["b"]).values
    same = both & (ba == bb)
    prim = games[same].reset_index(drop=True)
    prim_board = pd.Series(ba[same.values])
    cross = games[both & (ba != bb)].reset_index(drop=True)
    report["population"] = {**counts, "decided": int(len(games)), "unpublished_in_some_run": int((~both).sum()),
                            "cross_board": int(len(cross)), "primary_same_board": int(len(prim)),
                            "primary_per_board": prim_board.value_counts().sort_index().to_dict()}

    results, pvals = {}, {}
    base_pub, base_eng = credit(prim, base["power_score_true"]), credit(prim, base["mu"])
    for name in cands:
        teams = runs[name]["teams"]
        d_pub = credit(prim, teams["power_score_true"]) - base_pub
        d_eng = credit(prim, teams["mu"]) - base_eng
        pub, eng = dyadic(prim, d_pub), dyadic(prim, d_eng)
        boards = {}
        for b in sorted(prim_board.unique()):
            mask = (prim_board == b).values
            boards[b] = dyadic(prim[mask].reset_index(drop=True), d_pub[mask])
        eq_avg = float(np.mean([v["delta"] for v in boards.values() if v["n"]]))
        d_cross = credit(cross, teams["power_score_final"]) - credit(cross, base["power_score_final"])
        res = {"published": pub, "engine_diagnostic": eng, "boards": boards, "equal_weight_board_avg": eq_avg,
               "worst_board": min(boards.items(), key=lambda kv: kv[1]["delta"])[0],
               "cross_board_exploratory": dyadic(cross, d_cross),
               "baseline_published_agreement": 100 * float(base_pub.mean()),
               "candidate_published_agreement": 100 * float((base_pub + d_pub).mean())}
        if name == args.scf_cand:
            low = set(base.index[base["scf"] < CUT_SCF])
            st = base["state_code"]
            sa, sb = st.reindex(prim["a"]).values, st.reindex(prim["b"]).values
            known = pd.notna(sa) & pd.notna(sb)
            cut_mask = (prim["a"].isin(low) | prim["b"].isin(low)).values & known & (sa != sb)
            cut = prim[cut_mask].reset_index(drop=True)
            cut_res = dyadic(cut, d_pub[cut_mask])
            ordering_changed = np.sign(teams["power_score_true"].reindex(cut["a"]).values
                                       - teams["power_score_true"].reindex(cut["b"]).values) != np.sign(
                base["power_score_true"].reindex(cut["a"]).values - base["power_score_true"].reindex(cut["b"]).values)
            cut_teams = set(cut["a"][cut["a"].isin(low)]) | set(cut["b"][cut["b"].isin(low)])
            if cut_res["n"] < CUT_MIN_GAMES:
                verdict = "inconclusive (too few games)"
            elif cut_res["delta"] < -CUT_HARM:
                verdict = "harm"
            elif cut_res["ci95"][0] < -CUT_LOWER_BOUND:
                verdict = "inconclusive (interval too wide)"
            else:
                verdict = "ok"
            res["dampening_cut"] = {**cut_res, "low_scf_teams": len(cut_teams),
                                    "orderings_changed": int(ordering_changed.sum()), "verdict": verdict}
        results[name] = res
        pvals[name] = pub["p"]
    adjusted = holm(pvals)
    for name, res in results.items():
        pub = res["published"]
        res["holm_p"] = adjusted[name]
        harmed = sorted(b for b, v in res["boards"].items() if v["ci95"][1] < -BOARD_HARM)
        flagged = sorted(b for b, v in res["boards"].items() if v["delta"] < -BOARD_HARM and b not in harmed)
        res["boards_credibly_harmed"], res["boards_flagged_for_confirmation"] = harmed, flagged
        cut_ok = res.get("dampening_cut", {}).get("verdict", "ok") == "ok"
        if (pub["delta"] < 0 and adjusted[name] < ALPHA) or harmed:
            res["screen"] = "fail"
        elif (pub["delta"] >= WORTHWHILE_GAIN and adjusted[name] < ALPHA and res["equal_weight_board_avg"] > 0
              and cut_ok):
            res["screen"] = "pass"
        else:
            res["screen"] = "inconclusive"
    report["results"] = results

    diag = {}
    for name, run in runs.items():
        log = Path(run["dir"] + ".console.log")
        passes = pass_diagnostics(log) if log.exists() else []
        diag[name] = {"passes": passes, "capped": sum(p["stop"] == "cap" for p in passes),
                      "converged": sum(p["stop"] == "converged" for p in passes)}
        if name != "base":
            dsig = (run["teams"]["sigma"] - base["sigma"].reindex(run["teams"].index)).abs()
            diag[name]["sigma_abs_change_median_by_board"] = dsig.groupby(
                board.reindex(run["teams"].index)).median().round(4).to_dict()
    report["iteration_diagnostics"] = diag
    out_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    print(f"isolation passed: {report['isolation']['passed']}  primary games: {len(prim):,}  "
          f"cross-board: {len(cross):,}")
    for name, res in results.items():
        pub = res["published"]
        line = (f"{name}: published {pub['delta']:+.2f} pts (SE {pub['se']:.2f}, Holm p {res['holm_p']:.3g}); "
                f"board avg {res['equal_weight_board_avg']:+.2f}; harmed {res['boards_credibly_harmed'] or 'none'}; "
                f"flagged {res['boards_flagged_for_confirmation'] or 'none'}; screen: {res['screen']}")
        if "dampening_cut" in res:
            c = res["dampening_cut"]
            line += f"; cut {c['delta']:+.2f} on {c['n']} games -> {c['verdict']}" if c["n"] else "; cut: no games"
        print(line)


if __name__ == "__main__":
    main()
