"""Exercise the real offline harness and reject independently corrupted evidence."""

import importlib
import json
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from src.etl.glicko_config import GlickoConfig

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / ".claude/skills/measuring-ranking-changes/scripts"
sys.path.insert(0, str(TOOLS))
checks = importlib.import_module("c1_validation")
c1 = importlib.import_module("score_c1")
scorer = importlib.import_module("score_later_games")


def save_json(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")


@pytest.fixture(scope="module")
def captured_runs(tmp_path_factory):
    root = tmp_path_factory.mktemp("c1-captures")
    freeze = root / "freeze"
    freeze.mkdir()
    rows = []
    for a in range(4):
        for b in range(a + 1, 4):
            for repeat in range(6):
                game = f"{a}-{b}-{repeat}"
                for team, opp, gf, ga in ((a, b, 3, 1), (b, a, 1, 3)):
                    rows.append(dict(team_id=str(team), opp_id=str(opp), gf=gf, ga=ga,
                                     date=pd.Timestamp("2026-08-01") + pd.Timedelta(days=repeat),
                                     age="10", gender="male", opp_age="10", opp_gender="male",
                                     game_id=game, id=game, home_team_master_id=str(a)))
    frames = {
        "games.parquet": pd.DataFrame(rows),
        "teams-metadata.parquet": pd.DataFrame(dict(team_id_master=list("0123"),
                                                   state_code=["AZ", "AZ", "CA", None],
                                                   league=None, is_deprecated=False)),
        "merge-map.parquet": pd.DataFrame(dict(deprecated_team_id=["old"], canonical_team_id=["0"])),
    }
    # This fixture constructs recent games directly; describe this checkout's window.
    # Literal production window boundaries are tested by test_newest_game_selection.
    cfg = GlickoConfig()
    manifest = dict(today="2026-08-31", fetch_lookback_days=cfg.WINDOW_DAYS + cfg.WINDOW_GRACE_DAYS,
                    fetch_code_sha256=None)
    for (name, frame), key in zip(frames.items(), ("games_sha256", "teams_metadata_sha256", "merge_map_sha256")):
        frame.to_parquet(freeze / name, index=False)
        manifest[key] = checks.digest(freeze / name)
    save_json(freeze / "freeze-manifest.json", manifest)
    for name in ("base", "candidate"):
        command = [sys.executable, "-B", str(TOOLS / "shadow_harness.py"), "board", "--code-root", str(ROOT),
                   "--freeze", str(freeze), "--out", str(root / name), "--capture-stages"]
        if name == "candidate":
            command.append("--ceiling-connectivity")
        result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
        assert result.returncode == 0, result.stdout + result.stderr
    assert checks.compare_boundary(root / "base", root / "candidate", freeze)["passed"]
    return root


@pytest.mark.parametrize("corruption", [
    "pre_cap", "selection", "warm_start", "missing_stage", "missing_output", "missing_diagnostic",
    "nonfinite_diagnostic", "leaked_diagnostic", "timestamp", "extra_capture",
    "missing_score", "missing_reference_freeze",
])
def test_real_run_guards_reject_changed_or_missing_evidence(captured_runs, tmp_path, corruption):
    candidate = tmp_path / "candidate"
    shutil.copytree(captured_runs / "candidate", candidate)
    receipt = checks.read_json(candidate / "completed.json")
    if corruption in {"pre_cap", "selection", "warm_start", "leaked_diagnostic", "timestamp", "missing_score"}:
        name = {"pre_cap": "pre-cap-u10.parquet", "selection": "games-used.parquet",
                "warm_start": "stage-engine-01-warm-start.parquet"}.get(corruption, "teams.parquet")
        frame = pd.read_parquet(candidate / name)
        if corruption == "pre_cap":
            frame.loc[0, "shadow_pre_cap_score"] += 1e-10
        elif corruption == "selection":
            frame = pd.concat([frame, frame.iloc[:1]], ignore_index=True)
        elif corruption == "warm_start":
            frame.loc[0, "mu"] += 1e-10
        elif corruption == "leaked_diagnostic":
            frame["scf"] = .1
        elif corruption == "missing_score":
            frame.loc[0, "power_score_true"] = float("nan")
        else:
            frame["last_calculated"] += pd.Timedelta(days=1)
        frame.to_parquet(candidate / name, index=False)
        # Update the checksum too: detect actual invalid values, not just a stale hash.
        sha = checks.digest(candidate / name)
        for mapping in (receipt["pre_cap_files"], receipt["output_sha256"], receipt["stage_capture"]["files"]):
            if name in mapping:
                mapping[name] = sha
        if name == "teams.parquet":
            receipt["teams_sha256"] = sha
    elif corruption == "missing_stage":
        del receipt["stage_capture"]["files"]["stage-engine-01-warm-start.parquet"]
    elif corruption == "missing_output":
        del receipt["output_sha256"]["games-used.parquet"]
    elif corruption in {"missing_diagnostic", "nonfinite_diagnostic"}:
        name = "ceiling-connectivity.parquet"
        frame = pd.read_parquet(candidate / name)
        if corruption == "missing_diagnostic":
            frame = frame.iloc[1:]
        else:
            frame.loc[0, "scf"] = float("inf")
        frame.to_parquet(candidate / name, index=False)
        receipt["ceiling_connectivity_sha256"] = checks.digest(candidate / name)
    elif corruption == "extra_capture":
        shutil.copyfile(candidate / "pre-cap-u10.parquet", candidate / "pre-cap-u11.parquet")
        receipt["pre_cap_files"]["pre-cap-u11.parquet"] = checks.digest(candidate / "pre-cap-u11.parquet")
    else:
        provenance = checks.read_json(candidate / "provenance.json")
        provenance["freeze_manifest"]["teams_metadata_sha256"] = "wrong"
        save_json(candidate / "provenance.json", provenance)
    save_json(candidate / "completed.json", receipt)
    with pytest.raises(checks.InvalidRun):
        checks.compare_boundary(captured_runs / "base", candidate, captured_runs / "freeze")


def prerequisite_fixture(tmp_path):
    for role in ("base", "reference", "freeze"):
        (tmp_path / role).mkdir()
    for role in ("base", "reference"):
        save_json(tmp_path / role / "completed.json", {"role": role})
    save_json(tmp_path / "freeze/freeze-manifest.json", {"today": "2026-08-31"})
    args = SimpleNamespace(base=str(tmp_path / "base"), isolation_reference=str(tmp_path / "reference"),
                           prerequisite_report=str(tmp_path / "prerequisite.json"),
                           start="2026-09-01", end="2026-09-30")
    binding = dict(start=args.start, end=args.end,
                   scorer_sha256=checks.digest(TOOLS / "score_later_games.py"),
                   training_manifest_sha256=checks.digest(tmp_path / "freeze/freeze-manifest.json"),
                   run_completed_sha256={role: checks.digest(tmp_path / name / "completed.json")
                                         for role, name in (("base", "reference"), ("combo", "base"))})
    result = dict(screen="pass", published=dict(delta=.5), holm_p=.01, equal_weight_board_avg=.5,
                  boards_credibly_harmed=[], boards={b: dict(delta=.5, ci95=[-.5, 1.5]) for b in c1.BOARDS},
                  dampening_cut=dict(verdict="ok", n=300, delta=0, ci95=[-2, 2]))
    report = dict(evaluation=binding, isolation=dict(passed=True), results=dict(combo=result))
    return args, report


@pytest.mark.parametrize("corruption", [None, "period", "freeze", "run", "board", "scorer", "failed_stage"])
def test_first_stage_binding_and_actual_metrics(tmp_path, corruption):
    args, report = prerequisite_fixture(tmp_path)
    if corruption == "period":
        report["evaluation"]["start"] = "2026-08-01"
    elif corruption == "freeze":
        report["evaluation"]["training_manifest_sha256"] = "wrong"
    elif corruption == "run":
        report["evaluation"]["run_completed_sha256"]["combo"] = "wrong"
    elif corruption == "board":
        report["results"]["combo"]["boards"]["10M"]["ci95"] = [-5, -2]
    elif corruption == "scorer":
        report["evaluation"]["scorer_sha256"] = "wrong"
    elif corruption == "failed_stage":
        report["results"]["combo"]["screen"] = "fail"
    save_json(Path(args.prerequisite_report), report)
    loaded = {"reference": {"provenance": {"glicko_config": {"SCF_ENABLED": True}}}}
    if corruption in (None, "failed_stage"):
        passed, _ = c1._check_prerequisite(args, loaded, tmp_path / "freeze")
        assert passed is (corruption is None)
    else:
        with pytest.raises(checks.InvalidRun):
            c1._check_prerequisite(args, loaded, tmp_path / "freeze")


@pytest.mark.parametrize("profile", ["c1", "ceiling-release"])
@pytest.mark.parametrize("failure", ["boundary", "lock", "prerequisite"])
def test_cmd_never_reads_outcomes_when_a_gate_fails(captured_runs, tmp_path, monkeypatch, failure, profile):
    args = SimpleNamespace(out=str(tmp_path / "report.json"), start="2026-09-01", end="2026-09-30",
                           train_freeze=str(captured_runs / "freeze"), base=str(captured_runs / "base"),
                           cand=[f"c1={captured_runs / 'candidate'}"],
                           isolation_reference=str(captured_runs / "base"),
                           heldout_freeze="must-not-be-read", design_lock=str(tmp_path / "lock.json"),
                           prerequisite_report=str(tmp_path / "prerequisite.json"), profile=profile)
    save_json(Path(args.design_lock), {})
    save_json(Path(args.prerequisite_report), {})
    def reject(*unused):
        raise checks.InvalidRun("deliberate guard failure")
    monkeypatch.setattr(c1, "compare_boundary", reject if failure == "boundary" else lambda *a: {"passed": True})
    monkeypatch.setattr(c1, "_check_reference", lambda *a: None)
    monkeypatch.setattr(c1, "_check_lock", reject if failure == "lock" else lambda *a: {})
    monkeypatch.setattr(c1, "_check_prerequisite", lambda *a: (False, {}))
    monkeypatch.setattr(scorer, "heldout_games", lambda *a: pytest.fail("read held-out outcomes before gates"))
    if failure == "prerequisite":
        c1.cmd_c1(args, scorer)
        assert checks.read_json(Path(args.out))["verdict"] == "not_evaluated"
    else:
        with pytest.raises(SystemExit):
            c1.cmd_c1(args, scorer)
        assert checks.read_json(Path(args.out))["verdict"] == "void"


def test_release_command_applies_cumulative_veto(captured_runs, tmp_path, monkeypatch):
    heldout = tmp_path / "heldout"
    heldout.mkdir()
    (heldout / "games.parquet").write_bytes(b"hash-only fixture; score computation is separately tested")
    args = SimpleNamespace(out=str(tmp_path / "report.json"), start="2026-09-01", end="2026-09-30",
                           train_freeze=str(captured_runs / "freeze"), base=str(captured_runs / "base"),
                           cand=[f"release={captured_runs / 'candidate'}"],
                           isolation_reference=str(captured_runs / "base"), heldout_freeze=str(heldout),
                           design_lock=str(tmp_path / "lock.json"),
                           prerequisite_report=str(tmp_path / "prerequisite.json"), profile="ceiling-release")
    save_json(Path(args.design_lock), {})
    save_json(Path(args.prerequisite_report), {})
    monkeypatch.setattr(c1, "_check_reference", lambda *a: None)
    monkeypatch.setattr(c1, "_check_lock", lambda *a: {})
    monkeypatch.setattr(c1, "_check_prerequisite", lambda *a: (
        True, {"heldout_games_sha256": checks.digest(heldout / "games.parquet")}))
    calls = []
    def score(*values):
        calls.append(values)
        boards = {name: dict(delta=.5, ci95=[-.5, 1.5]) for name in c1.BOARDS}
        if len(calls) == 2:
            boards["10F"] = dict(delta=-2., ci95=[-3., -1.01])
        return dict(verdict="pass", boards=boards, isolation_cut=dict(delta=0., ci95=[-1., 1.]))
    monkeypatch.setattr(c1, "_score", score)
    c1.cmd_c1(args, scorer)
    report = checks.read_json(Path(args.out))
    assert len(calls) == 2
    assert report["incremental_verdict"] == "pass"
    assert report["verdict"] == "harm"
    assert report["cumulative_vs_incumbent"]["boards"]["10F"]["ci95"] == [-3., -1.01]


@pytest.mark.parametrize("scf", [None, float("inf"), float("nan")])
def test_invalid_reference_membership_is_rejected_before_scoring(scf):
    run = {"provenance": {"glicko_config": {"SCF_ENABLED": True}},
           "teams": pd.DataFrame({"scf": [scf], "state_code": ["AZ"]})}
    with pytest.raises(checks.InvalidRun):
        c1._check_reference(run)


@pytest.mark.parametrize("profile", ["c1", "ceiling-release"])
@pytest.mark.parametrize("corruption", [
    None, "unlocked", "seen", "time", "period", "engine", "scorer", "freeze", "profile", "comparisons",
])
def test_design_lock_binds_code_rules_inputs_and_unseen_outcomes(captured_runs, tmp_path, corruption, profile):
    freeze = captured_runs / "freeze"
    loaded = {role: checks.validate_run(captured_runs / name, freeze)
              for role, name in (("base", "base"), ("candidate", "candidate"), ("reference", "base"))}
    args = SimpleNamespace(design_lock=str(tmp_path / "synthetic-lock.json"),
                           start="2026-09-01", end="2026-09-30", profile=profile)
    lock = dict(locked=True, outcomes_unseen_at_lock=True, locked_at="2026-08-31T00:00:00+00:00",
                profile=profile, rules=c1.RULE, start=args.start, end=args.end,
                engine_file_sha256={role: run["provenance"]["engine_file_sha256"] for role, run in loaded.items()},
                scorer_sha256={name: checks.digest(TOOLS / name)
                               for name in ("score_later_games.py", "score_c1.py", "c1_validation.py")},
                training_manifest_sha256=checks.digest(freeze / "freeze-manifest.json"))
    if profile == "ceiling-release":
        lock["comparisons"] = c1.RELEASE_COMPARISONS
    if corruption == "unlocked":
        lock["locked"] = False
    elif corruption == "seen":
        lock["outcomes_unseen_at_lock"] = False
    elif corruption == "time":
        lock["locked_at"] = "2026-08-31"
    elif corruption == "period":
        lock["end"] = "2026-10-31"
    elif corruption == "engine":
        lock["engine_file_sha256"]["candidate"] = {}
    elif corruption == "scorer":
        lock["scorer_sha256"]["score_c1.py"] = "changed"
    elif corruption == "freeze":
        lock["training_manifest_sha256"] = "changed"
    elif corruption == "profile":
        lock["profile"] = "legacy"
    elif corruption == "comparisons":
        lock["comparisons"] = {}
    save_json(Path(args.design_lock), lock)
    if corruption is None or (corruption == "comparisons" and profile == "c1"):
        assert c1._check_lock(args, loaded, freeze) == lock
    else:
        with pytest.raises(checks.InvalidRun):
            c1._check_lock(args, loaded, freeze)
