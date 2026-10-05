"""C1 evaluation gates. The legacy scorer remains the only statistical implementation."""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
from c1_validation import InvalidRun, compare_boundary, digest, read_json, validate_run

BOARDS = {f"{age}{gender}" for age in (*range(10, 18), 19) for gender in ("M", "F")}
RULE = {"gain": .25, "alpha": .05, "board_harm": -1., "cut_scf": .6,
        "cut_min_games": 300, "cut_estimate": -1., "cut_lower": -2.}


def _finite(value):
    return value is not None and math.isfinite(value)


def _interval(result):
    ci = result.get("ci95")
    return ci is not None and len(ci) == 2 and all(_finite(v) for v in ci) and ci[0] <= ci[1]


def verdict(overall: dict, boards: dict, cut: dict) -> str:
    """Apply harm before pass; uncertainty or absent boards never implies safety."""
    if (_finite(overall.get("delta")) and _finite(overall.get("p"))
            and overall["delta"] < 0 and overall["p"] < RULE["alpha"]):
        return "harm"
    if any(_interval(value) and value["ci95"][1] < RULE["board_harm"] for value in [*boards.values(), cut]):
        return "harm"
    complete = (set(boards) == BOARDS and all(_finite(b.get("delta")) and _interval(b) for b in boards.values()))
    if (complete and _finite(overall.get("delta")) and _finite(overall.get("p"))
            and overall["delta"] >= RULE["gain"] and overall["p"] < RULE["alpha"]
            and np.mean([b["delta"] for b in boards.values()]) > 0
            and cut.get("n", 0) >= RULE["cut_min_games"] and _finite(cut.get("delta"))
            and cut["delta"] >= RULE["cut_estimate"] and _interval(cut) and cut["ci95"][0] >= RULE["cut_lower"]):
        return "pass"
    return "inconclusive"


def _check_lock(args, loaded: dict, freeze: Path) -> dict:
    if not args.design_lock:
        raise InvalidRun("C1 requires a recorded design lock before held-out data is read")
    lock = read_json(Path(args.design_lock))
    if lock.get("locked") is not True or lock.get("outcomes_unseen_at_lock") is not True:
        raise InvalidRun("Design is not locked on untouched outcomes")
    stamp = pd.Timestamp(lock["locked_at"])
    if stamp.tzinfo is None or stamp > pd.Timestamp.now(tz="UTC"):
        raise InvalidRun("Invalid lock timestamp")
    if lock.get("profile") != "c1" or lock.get("rules") != RULE:
        raise InvalidRun("Locked C1 rules do not match this scorer")
    if (lock.get("start"), lock.get("end")) != (args.start, args.end):
        raise InvalidRun("Evaluation period differs from the lock")
    for role, run in loaded.items():
        if lock["engine_file_sha256"].get(role) != run["provenance"]["engine_file_sha256"]:
            raise InvalidRun(f"Unrecognized locked engine code: {role}")
    scripts = Path(__file__).parent
    for name in ("score_later_games.py", "score_c1.py", "c1_validation.py"):
        if lock["scorer_sha256"].get(name) != digest(scripts / name):
            raise InvalidRun(f"Scoring code changed after lock: {name}")
    if lock["training_manifest_sha256"] != digest(freeze / "freeze-manifest.json"):
        raise InvalidRun("Training freeze differs from the lock")
    return lock


def _check_prerequisite(args, loaded: dict, freeze: Path) -> tuple[bool, dict]:
    if not args.prerequisite_report:
        raise InvalidRun("Missing first-stage report")
    report = read_json(Path(args.prerequisite_report))
    binding = report.get("evaluation", {})
    if binding.get("scorer_sha256") != digest(Path(__file__).with_name("score_later_games.py")):
        raise InvalidRun("First-stage scoring code differs from the locked scorer")
    if (binding.get("start"), binding.get("end")) != (args.start, args.end):
        raise InvalidRun("Missing or stale first-stage evaluation period")
    if binding.get("training_manifest_sha256") != digest(freeze / "freeze-manifest.json"):
        raise InvalidRun("First-stage training freeze differs")
    if not report.get("isolation", {}).get("passed"):
        raise InvalidRun("First-stage run checks did not pass")
    baseline_hash = digest(Path(args.base) / "completed.json")
    reference_hash = digest(Path(args.isolation_reference) / "completed.json")
    bindings = binding.get("run_completed_sha256", {})
    if bindings.get("base") != reference_hash:
        raise InvalidRun("First-stage incumbent does not match the isolation reference")
    names = [name for name, value in bindings.items() if name != "base" and value == baseline_hash]
    if len(names) != 1:
        raise InvalidRun("First-stage candidate does not match the C1 baseline")
    result = report["results"][names[0]]
    if result.get("screen") != "pass":
        return False, binding
    cut = result.get("dampening_cut", {})
    pub = result["published"]
    boards = result.get("boards", {})
    if (set(boards) != BOARDS or not all(_interval(b) and _finite(b.get("delta")) for b in boards.values())
            or any(b["ci95"][1] < -1 for b in boards.values())
            or np.mean([b["delta"] for b in boards.values()]) <= 0):
        raise InvalidRun("First-stage board results do not support a pass")
    if not (pub["delta"] >= .25 and result["holm_p"] < .05 and result["equal_weight_board_avg"] > 0
            and not result["boards_credibly_harmed"] and cut.get("verdict") == "ok"
            and cut.get("n", 0) >= 300 and _finite(cut.get("delta")) and cut["delta"] >= -1
            and _interval(cut) and cut["ci95"][0] >= -2):
        raise InvalidRun("First-stage pass is not supported by its recorded metrics")
    if loaded["reference"]["provenance"]["glicko_config"]["SCF_ENABLED"] is not True:
        raise InvalidRun("Isolation reference must have SCF enabled")
    return True, binding


def _check_reference(run: dict) -> None:
    if run["provenance"]["glicko_config"]["SCF_ENABLED"] is not True:
        raise InvalidRun("Isolation reference must have SCF enabled")
    teams = run["teams"]
    if not {"scf", "state_code"}.issubset(teams.columns):
        raise InvalidRun("Isolation reference is missing SCF or state metadata")
    if not np.isfinite(pd.to_numeric(teams.scf, errors="coerce").to_numpy(dtype=float)).all():
        raise InvalidRun("Isolation reference contains missing or nonfinite SCF values")


def _score(args, scorer, base, candidate, reference):
    games, counts = scorer.heldout_games(Path(args.heldout_freeze), Path(args.train_freeze), args.start, args.end)
    active = set(base.index[base.status == "Active"]) & set(candidate.index[candidate.status == "Active"])
    board = base.age_num.astype("Int64").astype(str) + base.gender.astype(str).str[0].str.upper()
    ba, bb = board.reindex(games.a), board.reindex(games.b)
    eligible = games.a.isin(active) & games.b.isin(active) & (ba.to_numpy() == bb.to_numpy())
    primary = games[eligible].reset_index(drop=True)
    labels = pd.Series(ba.to_numpy()[eligible.to_numpy()])
    d = scorer.credit(primary, candidate.power_score_true) - scorer.credit(primary, base.power_score_true)
    overall = scorer.dyadic(primary, d)
    boards = {name: scorer.dyadic(primary[labels == name].reset_index(drop=True), d[(labels == name).to_numpy()])
              for name in sorted(BOARDS)}
    # Missing board estimates are reported, but cannot satisfy the equal-board rule.
    observed = {name: value for name, value in boards.items() if value["n"]}
    low = set(reference.index[reference.scf < RULE["cut_scf"]])
    states = reference.state_code.fillna("").astype(str).str.strip().str.upper()
    sa, sb = states.reindex(primary.a).fillna(""), states.reindex(primary.b).fillna("")
    known = ~sa.isin(["", "UNKNOWN"]).to_numpy() & ~sb.isin(["", "UNKNOWN"]).to_numpy()
    mask = (primary.a.isin(low) | primary.b.isin(low)).to_numpy() & known & (sa.to_numpy() != sb.to_numpy())
    cut_games = primary[mask].reset_index(drop=True)
    cut = scorer.dyadic(cut_games, d[mask])
    changed = (np.sign(candidate.power_score_true.reindex(cut_games.a).to_numpy()
                       - candidate.power_score_true.reindex(cut_games.b).to_numpy())
               != np.sign(base.power_score_true.reindex(cut_games.a).to_numpy()
                          - base.power_score_true.reindex(cut_games.b).to_numpy()))
    u10 = labels.isin(["10M", "10F"]).to_numpy()
    return {
        "verdict": verdict(overall, observed, cut), "published": overall, "boards": boards,
        "equal_weight_board_avg": (
            float(np.mean([b["delta"] for b in observed.values()])) if len(observed) == 18 else None
        ),
        "boards_flagged": [name for name, value in observed.items() if value["delta"] < -1],
        "isolation_cut": {**cut, "orderings_changed": int(changed.sum()),
                          "low_scf_teams": len((set(cut_games.a) | set(cut_games.b)) & low)},
        "u10_combined": scorer.dyadic(primary[u10].reset_index(drop=True), d[u10]),
        "population": {**counts, "primary_same_board": len(primary)},
    }


def cmd_c1(args, scorer) -> None:
    out = Path(args.out)
    if out.exists():
        raise FileExistsError(out)
    report = {"profile": "c1", "rules": RULE, "start": args.start, "end": args.end}
    try:
        if len(args.cand) != 1 or not args.isolation_reference:
            raise InvalidRun("C1 needs one candidate and a separate SCF-enabled reference")
        name, candidate_path = args.cand[0].split("=", 1)
        if not name or name == "base":
            raise InvalidRun("Invalid candidate name")
        freeze = Path(args.train_freeze)
        cutoff = pd.Timestamp(read_json(freeze / "freeze-manifest.json")["today"])
        if not cutoff < pd.Timestamp(args.start) <= pd.Timestamp(args.end):
            raise InvalidRun("Held-out dates must start strictly after the training cutoff")
        loaded = {"base": validate_run(Path(args.base), freeze),
                  "candidate": validate_run(Path(candidate_path), freeze),
                  "reference": validate_run(Path(args.isolation_reference), freeze)}
        _check_reference(loaded["reference"])
        if not loaded["candidate"]["provenance"].get("ceiling_connectivity_enabled"):
            raise InvalidRun("Candidate was not run with C1 enabled")
        if loaded["base"]["provenance"].get("ceiling_connectivity_enabled"):
            raise InvalidRun("C1 baseline must not have C1 enabled")
        report["boundary"] = compare_boundary(Path(args.base), Path(candidate_path), freeze)
        _check_lock(args, loaded, freeze)
        passed, binding = _check_prerequisite(args, loaded, freeze)
        report["design_lock_sha256"] = digest(Path(args.design_lock))
        report["prerequisite_report_sha256"] = digest(Path(args.prerequisite_report))
        if not passed:
            report.update(verdict="not_evaluated", reason="The October candidate did not pass its first-stage check")
        else:
            heldout_hash = digest(Path(args.heldout_freeze) / "games.parquet")
            if heldout_hash != binding.get("heldout_games_sha256"):
                raise InvalidRun("Held-out games differ from the first-stage report")
            report["heldout_games_sha256"] = heldout_hash
            frames = {role: value["teams"].set_index("team_id") for role, value in loaded.items()}
            report.update(_score(args, scorer, frames["base"], frames["candidate"], frames["reference"]))
    except (InvalidRun, OSError, KeyError, ValueError, TypeError) as error:
        report.update(verdict="void", reason=str(error))
    with out.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, allow_nan=False)
    print(json.dumps({"verdict": report["verdict"], "reason": report.get("reason"), "report": str(out)}))
    if report["verdict"] == "void":
        raise SystemExit(1)
