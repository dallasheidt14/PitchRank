"""The actual ranking CLI must request the whole release and preserve dry-run flags."""

import sys
from types import SimpleNamespace

import pandas as pd
import pytest

import scripts.calculate_rankings as command
from src.etl.glicko_config import GlickoConfig
from src.etl.glicko_engine import run_glicko2_cohort


@pytest.mark.parametrize("gender,label", [("male", "Male"), ("female", "Female")])
def test_same_age_opponent_uses_current_cohort_rating_despite_gender_case(gender, label):
    games = pd.DataFrame([dict(team_id="a", opp_id="b", gf=2, ga=1,
                               date=pd.Timestamp("2026-08-01"), age="14", gender=gender,
                               opp_age="14", opp_gender=gender)])
    args = dict(cfg=GlickoConfig(SCF_ENABLED=False), today=pd.Timestamp("2026-08-31"), cohort_gender=label)
    normal, _ = run_glicko2_cohort(games, global_rating_map={}, **args)
    stale_map, _ = run_glicko2_cohort(games, global_rating_map={"b": 2500.}, **args)
    assert normal.set_index("team_id").loc["a", "mu"] == stale_map.set_index("team_id").loc["a", "mu"]
    older, _ = run_glicko2_cohort(games.assign(opp_age="15"), global_rating_map={"b": 2500.}, **args)
    assert older.set_index("team_id").loc["a", "mu"] > normal.set_index("team_id").loc["a", "mu"] + 100


@pytest.mark.asyncio
@pytest.mark.parametrize("ml", [False, True])
@pytest.mark.parametrize("dry_run", [False, True])
@pytest.mark.parametrize("engine", ["glicko", "v53e"])
async def test_cli_wires_release_without_enabling_dry_run_writes(monkeypatch, ml, dry_run, engine):
    arguments = ["calculate_rankings.py", "--engine", engine]
    if ml:
        arguments.append("--ml")
    if dry_run:
        arguments.append("--dry-run")
    monkeypatch.setattr(sys, "argv", arguments)
    monkeypatch.setenv("SUPABASE_URL", "https://example.invalid")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "fixture-only")
    client = object()
    monkeypatch.setattr(command, "create_client", lambda *args: client)
    monkeypatch.setattr(command, "MergeResolver", lambda *args: SimpleNamespace(
        load_merge_map=lambda: None, has_merges=False, version="fixture"))
    calls = []
    async def compute(**kwargs):
        calls.append(kwargs)
        assert kwargs["supabase_client"] is client
        if engine == "glicko" or ml:
            assert kwargs["ceiling_connectivity_enabled"] is (engine == "glicko")
            assert kwargs["persist_game_residuals"] is (not dry_run)
            assert kwargs["persist_game_explainability"] is (not dry_run)
            assert kwargs["save_snapshot"] is (not dry_run)
        else:
            assert "ceiling_connectivity_enabled" not in kwargs
        return {"teams": pd.DataFrame()}
    monkeypatch.setattr(command, "compute_all_cohorts", compute)
    monkeypatch.setattr(command, "compute_rankings_v53e_only", compute)
    await command.main()
    assert len(calls) == 1
