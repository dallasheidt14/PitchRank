from __future__ import annotations

import shutil
from types import SimpleNamespace

import pytest

import src.tournaments.compare_predictor_bridge as bridge
from src.tournaments.compare_predictor_bridge import (
    canonical_predictor_sha256,
    run_compare_prediction_batch,
    validate_predictor_cutoff,
    validate_predictor_runtime,
)


def _team(team_id: str, age: int, power_score: float) -> dict:
    return {
        "team_id_master": team_id,
        "team_name": team_id,
        "club_name": None,
        "league": None,
        "distinction": None,
        "state": "TX",
        "age": age,
        "gender": "M",
        "rank_in_cohort_final": 10,
        "power_score_final": power_score,
        "glicko_rating": 1500 + (power_score - 0.5) * 500,
        "glicko_rd": 80,
        "glicko_volatility": 0.05,
        "sos_norm": 0.5,
        "offense_norm": power_score,
        "defense_norm": power_score,
        "wins": 10,
        "losses": 5,
        "draws": 2,
        "games_played": 17,
        "last_scraped_at": None,
        "win_percentage": 64.7,
        "exp_margin": (power_score - 0.5) * 2,
        "exp_win_rate": power_score,
        "exp_goals_for": 1.5 + power_score,
        "exp_goals_against": 2.5 - power_score,
        "publication_cap_score": float("nan"),
    }


def test_predictor_identity_and_cutoff_are_stable(monkeypatch):
    original_identity = canonical_predictor_sha256()
    assert len(original_identity) == 64
    validate_predictor_cutoff("2026-09-05")
    with pytest.raises(ValueError, match="earliest supported cutoff is 2026-04-21"):
        validate_predictor_cutoff("2026-04-20")

    monkeypatch.setattr(
        "src.tournaments.compare_predictor_bridge.PREDICTOR_CALIBRATION_AVAILABLE_DATE",
        "2026-04-21",
    )
    assert canonical_predictor_sha256() != original_identity


def test_predictor_runtime_requires_the_checked_in_tsx_install(monkeypatch, tmp_path):
    monkeypatch.setattr(bridge.shutil, "which", lambda _name: "node")
    monkeypatch.setattr(bridge, "_TSX_CLI", tmp_path / "missing-tsx.mjs")

    with pytest.raises(RuntimeError, match="npm ci --prefix frontend"):
        validate_predictor_runtime()


def test_predictor_runtime_probes_tsx_with_node(monkeypatch, tmp_path):
    tsx_cli = tmp_path / "cli.mjs"
    tsx_cli.write_text("", encoding="utf-8")
    monkeypatch.setattr(bridge.shutil, "which", lambda _name: "node-20")
    monkeypatch.setattr(bridge, "_TSX_CLI", tsx_cli)
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout="tsx v4", stderr="")

    monkeypatch.setattr(bridge.subprocess, "run", run)
    validate_predictor_runtime()

    assert calls[0][0] == ["node-20", str(tsx_cli), "--version"]
    assert calls[0][1]["cwd"] == bridge._FRONTEND_DIR


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is required by the Compare predictor")
def test_batch_runs_the_compare_predictor_for_both_orientations():
    predictions = run_compare_prediction_batch(
        {
            "entrant-a": _team("team-a", 19, 0.67),
            "entrant-b": _team("team-b", 17, 0.43),
        },
        [],
    )

    forward = predictions[("entrant-a", "entrant-b")]
    reversed_order = predictions[("entrant-b", "entrant-a")]
    assert forward.expected_margin == pytest.approx(-reversed_order.expected_margin)
    assert forward.expected_absolute_goal_difference == pytest.approx(
        reversed_order.expected_absolute_goal_difference
    )
    assert forward.expected_absolute_goal_difference >= abs(forward.expected_margin)
    assert forward.win_probability_a == pytest.approx(reversed_order.win_probability_b)
    assert forward.win_probability_b == pytest.approx(reversed_order.win_probability_a)
    assert forward.draw_probability == pytest.approx(reversed_order.draw_probability)
    assert forward.expected_score == {
        "teamA": reversed_order.expected_score["teamB"],
        "teamB": reversed_order.expected_score["teamA"],
    }
    assert reversed_order.predicted_winner == {
        "team_a": "team_b",
        "team_b": "team_a",
        "draw": "draw",
    }[forward.predicted_winner]
    assert forward.blowout_4plus_probability == pytest.approx(
        reversed_order.blowout_4plus_probability
    )
    assert forward.win_probability_a + forward.draw_probability + forward.win_probability_b == pytest.approx(1.0)


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is required by the Compare predictor")
def test_batch_mirrors_nearly_even_matchups_instead_of_repredicting_them():
    predictions = run_compare_prediction_batch(
        {
            "entrant-a": _team("team-a", 14, 0.500),
            "entrant-b": _team("team-b", 14, 0.501),
        },
        [],
    )

    forward = predictions[("entrant-a", "entrant-b")]
    reversed_order = predictions[("entrant-b", "entrant-a")]
    assert reversed_order.predicted_winner == {
        "team_a": "team_b",
        "team_b": "team_a",
        "draw": "draw",
    }[forward.predicted_winner]
    assert forward.win_probability_a == pytest.approx(reversed_order.win_probability_b)
    assert forward.win_probability_b == pytest.approx(reversed_order.win_probability_a)
    assert forward.expected_margin == pytest.approx(-reversed_order.expected_margin)
