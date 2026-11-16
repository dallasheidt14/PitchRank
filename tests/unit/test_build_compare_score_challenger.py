import hashlib
import json
from pathlib import Path

import pytest

from scripts import build_compare_score_challenger as cli


def inputs(tmp_path):
    model = tmp_path / "fit.json"
    model.write_text(json.dumps({"receipt": {"cutoff": "2026-11-14", "latest_training_game": "2026-11-12",
                                           "optimizer_success": True}}), encoding="utf-8")
    source = tmp_path / "input.json"
    source.write_text(json.dumps({
        "model_sha256": hashlib.sha256(model.read_bytes()).hexdigest(),
        "rows": [{"id": "baseline-1", "source_game_id": "game-1", "game_date": "2026-11-15",
                  "eligibility": "eligible", "learned_rates": [1.5, .9],
                  "variants": {"baseline": {
                      "winProbabilityA": .6, "drawProbability": .2, "winProbabilityB": .2,
                      "predictedWinner": "team_a", "expectedScore": {"teamA": 3, "teamB": 1},
                      "expectedGoals": {"teamA": 3.2, "teamB": 1.2}, "blowout4PlusProbability": .3,
                  }}}],
    }), encoding="utf-8")
    return ["--input", str(source), "--fit", str(model)]


def test_preview_writes_nothing_and_prints_no_private_forecasts(tmp_path, capsys):
    args = inputs(tmp_path)
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    cli.main(args)
    report = json.loads(capsys.readouterr().out)
    assert report["dry_run"] is True and report["fixtures"] == 1
    assert report["live_formula_changed"] is False
    assert "rows" not in report and "game-1" not in json.dumps(report)
    assert before == {p.name: p.read_bytes() for p in tmp_path.iterdir()}


def test_output_and_execution_are_required_together(tmp_path):
    args = inputs(tmp_path)
    for extra in [["--execute"], ["--output", str(tmp_path / "out.json")]]:
        with pytest.raises(SystemExit) as exc:
            cli.main(args + extra)
        assert exc.value.code == 1
    assert not (tmp_path / "out.json").exists()


def test_execute_requires_private_new_destination_and_records_hashes(tmp_path, monkeypatch, capsys):
    args = inputs(tmp_path)
    output = tmp_path / "private.json"
    calls = []

    def git_check(args, **kwargs):
        calls.append((args, kwargs))

    monkeypatch.setattr("src.predictions.private_research_output.subprocess.run", git_check)
    cli.main(args + ["--execute", "--output", str(output)])
    saved = json.loads(output.read_text())
    assert saved["provenance"]["input_sha256"] == hashlib.sha256(Path(args[1]).read_bytes()).hexdigest()
    assert saved["provenance"]["fit_sha256"] == hashlib.sha256(Path(args[3]).read_bytes()).hexdigest()
    assert len(saved["provenance"]["candidate_signature"]) == 64
    assert calls[0][0] == ["git", "check-ignore", "-q", "--", str(output.resolve())]
    assert calls[0][1]["check"] is True
    before = output.read_bytes()
    with pytest.raises(SystemExit) as exc:
        cli.main(args + ["--execute", "--output", str(output)])
    assert exc.value.code == 1
    assert output.read_bytes() == before
    capsys.readouterr()


def test_wrong_fit_is_rejected_before_writing(tmp_path):
    args = inputs(tmp_path)
    Path(args[3]).write_text("{}", encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        cli.main(args)
    assert exc.value.code == 1
