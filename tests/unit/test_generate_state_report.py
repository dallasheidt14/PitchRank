"""Tests for the state report generator's credibility gate."""

import os
import sys

import pytest

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from scripts.generate_state_report import (
    MIN_PER_REQUIRED_LEAGUE,
    MIN_RANKED_TEAMS,
    REQUIRED_LEAGUES,
    run_credibility_gate,
)


def _passing_leagues():
    return {lg: MIN_PER_REQUIRED_LEAGUE for lg in REQUIRED_LEAGUES}


def test_gate_passes_at_the_floor_boundary():
    # Both bars are inclusive: exactly at the minimum should not raise.
    assert run_credibility_gate("TX", "Texas", MIN_RANKED_TEAMS, _passing_leagues()) is None


def test_gate_fails_when_ranked_below_floor():
    with pytest.raises(SystemExit) as exc:
        run_credibility_gate("WY", "Wyoming", MIN_RANKED_TEAMS - 1, _passing_leagues())
    assert "ranked teams" in str(exc.value)


def test_gate_fails_when_required_league_below_minimum():
    leagues = _passing_leagues()
    leagues["EA"] = MIN_PER_REQUIRED_LEAGUE - 1
    with pytest.raises(SystemExit) as exc:
        run_credibility_gate("TX", "Texas", MIN_RANKED_TEAMS, leagues)
    assert "EA" in str(exc.value)


def test_gate_fails_when_required_league_absent():
    leagues = _passing_leagues()
    del leagues["NL"]
    with pytest.raises(SystemExit) as exc:
        run_credibility_gate("TX", "Texas", MIN_RANKED_TEAMS, leagues)
    assert "NL" in str(exc.value)


def test_gate_reports_floor_and_league_failures_together():
    with pytest.raises(SystemExit) as exc:
        run_credibility_gate("WY", "Wyoming", 100, {})
    message = str(exc.value)
    assert "ranked teams" in message
    for league in REQUIRED_LEAGUES:
        assert league in message
