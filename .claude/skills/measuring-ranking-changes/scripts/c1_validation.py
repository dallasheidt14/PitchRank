"""Offline stage capture and exact upstream checks for the C1 experiment."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from functools import wraps
from pathlib import Path

import numpy as np
import pandas as pd


class InvalidRun(ValueError):
    """A missing, changed or incompatible artifact voids the comparison."""


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class StageCapture:
    """Observe existing calls; never recompute a scoring value for instrumentation."""

    def __init__(self, calculator, out: Path):
        self.calculator = calculator
        self.out = out
        self.files: list[str] = []
        self.counts = Counter()
        self.stack: list[str] = []
        self.adjustments: list[dict] = []
        self.originals = {}

    def save(self, name: str, frame: pd.DataFrame) -> None:
        path = self.out / name
        if path.exists():
            raise InvalidRun(f"Duplicate stage capture: {name}")
        frame.to_parquet(path, index=False)
        self.files.append(name)

    def engine(self, result: dict, call_kwargs: dict) -> None:
        index = self.counts["engine"]
        self.counts["engine"] += 1
        label = f"stage-engine-{index:02d}"
        for key in ("teams", "games_used", "game_explainability"):
            self.save(f"{label}-{key}.parquet", result[key])
        initial = call_kwargs.get("initial_ratings") or {}
        self.save(
            f"{label}-warm-start.parquet",
            pd.DataFrame([(team, *values) for team, values in initial.items()],
                         columns=["team_id", "mu", "sigma", "volatility"]),
        )

    def install(self) -> None:
        calc = self.calculator
        ml = calc.apply_predictive_adjustment
        self.originals["apply_predictive_adjustment"] = ml

        @wraps(ml)
        async def capture_ml(*args, **kwargs):
            index = self.counts["ml"]
            self.counts["ml"] += 1
            result = await ml(*args, **kwargs)
            teams, residuals = result
            self.save(f"stage-ml-{index:02d}-teams.parquet", teams)
            self.save(f"stage-ml-{index:02d}-residuals.parquet", residuals)
            return result

        calc.apply_predictive_adjustment = capture_ml
        for name in (
            "_publication_cap_rank", "_same_age_authority_score", "_same_age_raw_shrink",
            "_play_up_bonus", "_same_age_publish_penalty", "_positive_ml_evidence_scale",
        ):
            original = getattr(calc, name)
            self.originals[name] = original
            setattr(calc, name, self._wrap_adjustment(name, original))

    def _wrap_adjustment(self, name, original):
        @wraps(original)
        def capture(row, *args, **kwargs):
            caller = self.stack[-1] if self.stack else "pipeline"
            self.stack.append(name)
            try:
                value = original(row, *args, **kwargs)
                if "_publication_cap_rank" not in self.stack:
                    self.adjustments.append({"team_id": row["team_id"], "function": name,
                                             "caller": caller, "value": value})
                return value
            finally:
                self.stack.pop()
        return capture

    def close(self) -> dict:
        for name, original in self.originals.items():
            setattr(self.calculator, name, original)
        self.save("stage-upstream-adjustments.parquet", pd.DataFrame(
            self.adjustments, columns=["team_id", "function", "caller", "value"]
        ))
        return {"version": 1, "counts": dict(self.counts),
                "files": {name: digest(self.out / name) for name in sorted(self.files)}}


def validate_run(run: Path, freeze: Path) -> dict:
    """Validate immutable inputs and receipts without reading held-out outcomes."""
    manifest = read_json(freeze / "freeze-manifest.json")
    provenance = read_json(run / "provenance.json")
    completed = read_json(run / "completed.json")
    files = {"games.parquet": "games_sha256", "teams-metadata.parquet": "teams_metadata_sha256",
             "merge-map.parquet": "merge_map_sha256"}
    for name, field in files.items():
        if digest(freeze / name) != manifest[field] or provenance["freeze_manifest"][field] != manifest[field]:
            raise InvalidRun(f"Input hash mismatch: {name}")
    day = pd.Timestamp(manifest["today"])
    if pd.Timestamp(provenance["today"]) != day:
        raise InvalidRun("Run cutoff differs from the training freeze")
    dates = pd.to_datetime(pd.read_parquet(freeze / "games.parquet", columns=["date"])["date"])
    if dates.isna().any() or (dates.dt.normalize() > day).any():
        raise InvalidRun("Invalid date or post-cutoff game in training")
    if provenance.get("fetch_code_not_measured"):
        raise InvalidRun("Unmeasured fetch differences")
    if digest(run / "teams.parquet") != completed["teams_sha256"]:
        raise InvalidRun("Team output changed after completion")
    outputs = completed.get("output_sha256", {})
    expected_outputs = {"teams.parquet", "games-used.parquet", "explainability.parquet"}
    if completed.get("stage_capture") and set(outputs) != expected_outputs:
        raise InvalidRun("Incomplete output receipts")
    for name, sha in outputs.items():
        if name not in {"teams.parquet", "games-used.parquet", "explainability.parquet"} or digest(run / name) != sha:
            raise InvalidRun(f"Output changed after completion: {name}")
    teams = pd.read_parquet(run / "teams.parquet")
    required_teams = {"team_id", "status", "age_num", "gender", "power_score_true", "power_score_final",
                      "last_calculated"}
    if not required_teams.issubset(teams.columns) or teams["team_id"].isna().any():
        raise InvalidRun("Missing required team output fields")
    if teams["team_id"].duplicated().any():
        raise InvalidRun("Duplicate team in run output")
    active = teams[teams["status"] == "Active"]
    if (active[["age_num", "gender"]].isna().any().any()
            or not np.isfinite(active[["power_score_true", "power_score_final"]].to_numpy(dtype=float)).all()):
        raise InvalidRun("Invalid active-team scores or board labels")
    dates = pd.to_datetime(teams["last_calculated"], utc=True)
    if dates.isna().any() or not dates.eq(pd.Timestamp(day, tz="UTC")).all():
        raise InvalidRun("Unpinned calculation timestamps")
    allowed = {
        "team_merge_map.select(deprecated_team_id,canonical_team_id).range",
        "teams.select(team_id_master,state_code,league).in_(team_id_master)",
        "teams.select(team_id_master).in_(team_id_master).eq(is_deprecated)",
    }
    calls = completed.get("frozen_client_calls", {})
    if not calls or set(calls) - allowed or any(n <= 0 for n in calls.values()):
        raise InvalidRun("Missing or unexpected frozen-client call receipts")
    loaded = completed.get("loaded_module_sha256", {})
    if not loaded or any(loaded.get(name) != sha for name, sha in provenance["engine_file_sha256"].items()):
        raise InvalidRun("Loaded engine code differs from provenance")
    caps = completed.get("pre_cap_files", {})
    if not caps or set(caps) != {p.name for p in run.glob("pre-cap-u*.parquet")}:
        raise InvalidRun("Missing or extra pre-cap capture")
    for name, sha in caps.items():
        if digest(run / name) != sha:
            raise InvalidRun(f"Pre-cap artifact changed: {name}")
        cap_frame = pd.read_parquet(run / name)
        if "shadow_pre_cap_score" not in cap_frame or cap_frame["shadow_pre_cap_score"].isna().any():
            raise InvalidRun(f"Missing pre-cap boundary scores: {name}")
    if provenance.get("ceiling_connectivity_enabled"):
        if provenance["glicko_config"]["SCF_ENABLED"]:
            raise InvalidRun("C1 unexpectedly applied SCF")
        diagnostic = run / "ceiling-connectivity.parquet"
        if digest(diagnostic) != completed.get("ceiling_connectivity_sha256"):
            raise InvalidRun("Missing or altered ceiling diagnostics")
        frame = pd.read_parquet(diagnostic)
        required = {"team_id", "source_cohort_age", "source_cohort_gender",
                    "scf", "unique_opp_states", "bridge_games", "is_isolated"}
        if (not required.issubset(frame.columns) or frame[list(required)].isna().any().any()
                or frame.team_id.duplicated().any() or set(frame.team_id) != set(teams.team_id)):
            raise InvalidRun("Invalid ceiling diagnostic coverage")
        if not np.isfinite(frame[["scf", "unique_opp_states", "bridge_games"]].to_numpy(dtype=float)).all():
            raise InvalidRun("Nonfinite ceiling diagnostics")
        if not pd.api.types.is_bool_dtype(frame["is_isolated"]):
            raise InvalidRun("Nonboolean ceiling isolation diagnostics")
        if {"scf", "unique_opp_states", "bridge_games", "is_isolated"} & set(teams.columns):
            raise InvalidRun("Ceiling diagnostics leaked into normal team output")
    log = (run / "run.log").read_text(encoding="utf-8")
    if any(token in log for token in ("Traceback", "BlockedCall", "Failed to check is_deprecated")):
        raise InvalidRun("Run log contains a failed input/read check")
    return {"provenance": provenance, "completed": completed, "teams": teams}


def _canonical(frame: pd.DataFrame) -> pd.DataFrame:
    # Preserve multiplicities. Hashing only chooses a stable order; equality is still exact.
    frame = frame.reindex(sorted(frame.columns), axis=1).reset_index(drop=True)
    order = pd.util.hash_pandas_object(frame, index=False).sort_values(kind="stable").index
    return frame.loc[order].reset_index(drop=True)


def assert_equal_frames(left: pd.DataFrame, right: pd.DataFrame, name: str) -> None:
    try:
        pd.testing.assert_frame_equal(_canonical(left), _canonical(right), check_exact=True, check_dtype=True)
    except AssertionError as error:
        raise InvalidRun(f"Upstream difference in {name}: {str(error)[:700]}") from error


def compare_boundary(base: Path, candidate: Path, freeze: Path, *, allow_legacy_base=False) -> dict:
    b, c = validate_run(base, freeze), validate_run(candidate, freeze)
    for key in ("environment", "glicko_config", "ml_config", "merge_version"):
        if b["provenance"][key] != c["provenance"][key]:
            raise InvalidRun(f"Different {key}")
    if b["completed"]["frozen_client_calls"] != c["completed"]["frozen_client_calls"]:
        raise InvalidRun("Different frozen-client read counts")
    checked = []
    if set(b["completed"]["pre_cap_files"]) != set(c["completed"]["pre_cap_files"]):
        raise InvalidRun("Different pre-cap capture coverage")
    for name in sorted(b["completed"]["pre_cap_files"]):
        excluded = ["publication_cap_rank", "publication_cap_score"]
        left = pd.read_parquet(base / name).drop(columns=excluded, errors="ignore")
        right = pd.read_parquet(candidate / name).drop(columns=excluded, errors="ignore")
        assert_equal_frames(left, right, name)
        checked.append(name)
    # Older artifacts still verify selection, eligible teams and every pre-cap field.
    assert_equal_frames(pd.read_parquet(base / "games-used.parquet"),
                        pd.read_parquet(candidate / "games-used.parquet"), "games-used")
    bs, cs = b["completed"].get("stage_capture"), c["completed"].get("stage_capture")
    if not cs or (not bs and not allow_legacy_base):
        raise InvalidRun("Stage receipts required for both C1 comparison runs")
    if bs:
        tooling = b["provenance"].get("tool_sha256", {})
        if (set(tooling) != {"shadow_harness.py", "c1_validation.py"}
                or tooling != c["provenance"].get("tool_sha256")):
            raise InvalidRun("Different or missing capture tooling hashes")
        n = bs["counts"].get("engine", 0)
        expected = {"stage-upstream-adjustments.parquet"}
        for index in range(n):
            expected.update(f"stage-engine-{index:02d}-{part}.parquet"
                            for part in ("teams", "games_used", "game_explainability", "warm-start"))
            expected.update(f"stage-ml-{index:02d}-{part}.parquet" for part in ("teams", "residuals"))
        if n <= 0 or n % 2 or bs["counts"].get("ml") != n or set(bs["files"]) != expected:
            raise InvalidRun("Incomplete two-pass stage receipts")
        if bs["version"] != cs["version"] or bs["counts"] != cs["counts"] or set(bs["files"]) != set(cs["files"]):
            raise InvalidRun("Different stage capture coverage")
        for name in sorted(bs["files"]):
            if digest(base / name) != bs["files"][name] or digest(candidate / name) != cs["files"][name]:
                raise InvalidRun(f"Stage artifact changed: {name}")
            assert_equal_frames(pd.read_parquet(base / name), pd.read_parquet(candidate / name), name)
            checked.append(name)
    allowed = {"publication_cap_rank", "publication_cap_score", "power_score_true", "power_score_final",
               "national_power_score", "global_power_score", "rank_in_cohort_final",
               "national_rank", "state_rank", "global_rank", "rank_in_state_final"}
    assert_equal_frames(b["teams"].drop(columns=list(allowed), errors="ignore"),
                        c["teams"].drop(columns=list(allowed), errors="ignore"), "final upstream columns")
    return {"passed": True, "base": str(base.resolve()), "candidate": str(candidate.resolve()),
            "freeze": str(freeze.resolve()), "checked_artifacts": checked,
            "legacy_reproduction_only": not bool(bs),
            "base_completed_sha256": digest(base / "completed.json"),
            "candidate_completed_sha256": digest(candidate / "completed.json")}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--cand", type=Path, required=True)
    parser.add_argument("--freeze", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--allow-legacy-base", action="store_true", help="saved-baseline reproduction only")
    args = parser.parse_args()
    try:
        report = compare_boundary(args.base, args.cand, args.freeze, allow_legacy_base=args.allow_legacy_base)
    except (InvalidRun, OSError, KeyError, ValueError) as error:
        report = {"passed": False, "verdict": "void", "reason": str(error)}
    with args.out.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, allow_nan=False)
    print(json.dumps(report))
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
