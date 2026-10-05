"""C1 must restore cap inputs without restoring their upstream consumers."""

import importlib
import json
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.etl import glicko_engine as engine
from src.etl.glicko_config import GlickoConfig
from src.rankings import calculator as calc

TOOLS = Path(__file__).resolve().parents[2] / ".claude/skills/measuring-ranking-changes/scripts"
sys.path.insert(0, str(TOOLS))
checks = importlib.import_module("c1_validation")
harness = importlib.import_module("shadow_harness")


@pytest.fixture
def league():
    rows = []
    metadata = []
    for gender in ("male", "female"):
        teams = [f"{gender}-{i}" for i in range(4)]
        for i, team in enumerate(teams):
            metadata.append({"team_id_master": team, "state_code": ["AZ", "CA", "NV", None][i],
                             "league": None, "is_deprecated": False})
        for a in range(4):
            for b in range(a + 1, 4):
                for repeat in range(6):
                    game = f"{gender}-{a}-{b}-{repeat}"
                    for team, opp, gf, ga in ((teams[a], teams[b], 3, 1), (teams[b], teams[a], 1, 3)):
                        rows.append({"team_id": team, "opp_id": opp, "gf": gf, "ga": ga,
                                     "date": pd.Timestamp("2026-08-01") + pd.Timedelta(days=repeat * 3),
                                     "age": "10", "gender": gender, "opp_age": "10", "opp_gender": gender,
                                     "game_id": game, "id": game, "home_team_master_id": teams[a]})
    return pd.DataFrame(rows), pd.DataFrame(metadata)


def test_connectivity_keeps_exact_legacy_values_and_neutral_wrapper(league):
    games, _ = league
    games = games[games["gender"] == "male"].copy()
    ratings = {t: (1500.0 + i * 100, 100.0, .06) for i, t in enumerate(games.team_id.unique())}
    states = {"male-0": "AZ", "male-1": "AZ", "male-2": "CA", "male-3": "UNKNOWN"}
    cfg = GlickoConfig(SCF_ENABLED=True)
    selected = {t: g.iloc[:5] for t, g in games.groupby("team_id")}
    old_path = engine.compute_scf(games, states, ratings, cfg, selected)
    measured = engine.compute_schedule_connectivity(games, states, ratings, replace(cfg, SCF_ENABLED=False), selected)
    assert measured == old_path
    assert measured["male-0"]["scf"] == .1
    assert measured["male-0"]["bridge_games"] == 0.0
    assert measured["male-0"]["unique_states"] == 0.0
    assert measured["male-0"]["is_isolated"] is True
    neutral = engine.compute_scf(games, states, ratings, replace(cfg, SCF_ENABLED=False), selected)
    assert neutral["male-0"] == {
        "scf": 1.0, "unique_states": 0, "bridge_games": 0, "is_isolated": False,
        "quality_boosted": False, "unique_leagues": 0, "league_scf": 1.0,
        "dominant_opp_league": None, "dominant_opp_league_share": 0.0,
    }


def test_refactor_matches_pinned_original(league):
    """Expected values were produced by the pinned old function, independent of this refactor."""
    fixture = Path(__file__).resolve().parents[1] / "fixtures/c1/scf-8338d25a7.json"
    expected = json.loads(fixture.read_text(encoding="utf-8"))["cases"]
    games, metadata = league
    states = dict(zip(metadata.team_id_master, metadata.state_code.fillna("UNKNOWN")))
    ratings = {t: (1200.0 + i * 90, 100.0, .06) for i, t in enumerate(games.team_id.unique())}
    leagues = {t: "ECNL_RL" if i % 2 else "ECNL" for i, t in enumerate(ratings)}
    for age in ("10", "14"):
        g = games.assign(age=age)
        for enabled in (True, False):
            cfg = GlickoConfig(SCF_ENABLED=enabled)
            assert engine.compute_scf(g, states, ratings, cfg, tier_league_map=leagues) == expected[f"{age}-{enabled}"]


def test_collection_uses_current_pass2_ratings_and_selected_games(league, monkeypatch):
    games, metadata = league
    games = games[games.gender == "male"].copy()
    initial = {team: (800., 300., .06) for team in games.team_id.unique()}
    states = dict(zip(metadata.team_id_master, metadata.state_code.fillna("UNKNOWN")))
    observed = {}
    calculate = engine.compute_schedule_connectivity
    def capture(games_df, team_state_map, team_ratings, cfg, team_games, tier_league_map):
        observed["ratings"] = dict(team_ratings)
        observed["games"] = pd.concat(list(team_games.values()), ignore_index=True)
        return calculate(games_df, team_state_map, team_ratings, cfg, team_games, tier_league_map)
    monkeypatch.setattr(engine, "compute_schedule_connectivity", capture)
    result = engine.compute_rankings_v2(
        games, today=pd.Timestamp("2026-08-31"), cfg=GlickoConfig(SCF_ENABLED=False),
        team_state_map=states, initial_ratings=initial, pass_label="Pass2", collect_ceiling_connectivity=True,
    )
    current = result["teams"].set_index("team_id")
    assert observed["ratings"] != initial
    assert observed["ratings"] == {
        team: tuple(current.loc[team, ["mu", "sigma", "volatility"]]) for team in current.index
    }
    columns = ["team_id", "opp_id", "id", "date", "gf", "ga"]
    checks.assert_equal_frames(observed["games"][columns], result["games_used"][columns], "connectivity source games")


@pytest.mark.parametrize("field,value", [("scf", np.nan), ("bridge_games", np.inf), ("is_isolated", 1)])
def test_bad_diagnostics_fail(field, value):
    row = {"team_id": "a", "source_cohort_age": "10", "source_cohort_gender": "male",
           "scf": .1, "unique_opp_states": 0., "bridge_games": 0., "is_isolated": True}
    row[field] = value
    with pytest.raises(ValueError):
        calc._validate_ceiling_connectivity(pd.DataFrame([row]))


def test_overlay_uses_surviving_cohort_and_does_not_mutate_input(monkeypatch):
    row = pd.Series({"team_id": "a", "age_num": 10, "_ceiling_source_cohort": 1, "powerscore_adj": .8})
    original = row.copy(deep=True)
    diagnostics = pd.DataFrame([
        {"team_id": "a", "_ceiling_source_cohort": cohort, "scf": scf, "unique_opp_states": states,
         "bridge_games": 4., "is_isolated": False}
        for cohort, scf, states in [(0, .1, 0.), (1, .9, 5.4)]
    ]).set_index(["_ceiling_source_cohort", "team_id"])
    def cap(observed):
        assert observed["scf"] == .9
        assert observed["unique_opp_states"] == 5.4
        assert "_ceiling_source_cohort" not in observed
        return 250
    monkeypatch.setattr(calc, "_publication_cap_rank", cap)
    assert calc._publication_cap_rank_with_connectivity(row, diagnostics) == 250
    pd.testing.assert_series_equal(row, original)
    with pytest.raises(ValueError, match="Missing ceiling"):
        calc._publication_cap_rank_with_connectivity(row, diagnostics.drop(index=(1, "a")))


@pytest.mark.parametrize("profile,before,after", [
    (dict(age_num=14, same_age_top100_opp_count=0, same_age_top500_opp_count=3,
          same_age_top500_non_loss_opp_count=3, same_age_top1000_non_loss_opp_count=3,
          same_age_avg_opp_power_adj=.645, repeat_opponent_share=.15,
          unique_opp_states=1., scf=.8, bridge_games=1., is_isolated=True), 400, 1800),
    (dict(age_num=12, same_age_games=34, same_age_unique_opponents=21,
          same_age_top100_opp_count=5, same_age_top100_non_loss_opp_count=6,
          same_age_top500_opp_count=11, same_age_top500_non_loss_opp_count=12,
          same_age_top1000_non_loss_opp_count=14, same_age_avg_opp_power_adj=.699,
          same_age_quality_opp_power_adj=.699, repeat_opponent_share=.558,
          unique_opp_states=2., bridge_games=4.78, scf=.73, is_isolated=False,
          games_last_180_days=27, days_since_last=9, powerscore_adj=.935, powerscore_ml=.975), 250, None),
])
def test_existing_restriction_and_relief_receive_restored_inputs(profile, before, after):
    row = pd.Series({key: value for key, value in profile.items() if key not in calc._CEILING_CONNECTIVITY_FIELDS})
    row["team_id"], row["_ceiling_source_cohort"] = "a", 0
    assert calc._publication_cap_rank(row) == before
    upstream = (calc._positive_ml_evidence_scale(row), calc._same_age_raw_shrink(row),
                calc._same_age_publish_penalty(row), calc._play_up_bonus(row))
    diagnostics = pd.DataFrame([dict(team_id="a", _ceiling_source_cohort=0,
                                   **{key: profile[key] for key in calc._CEILING_CONNECTIVITY_FIELDS})])
    assert calc._publication_cap_rank_with_connectivity(
        row, diagnostics.set_index(["_ceiling_source_cohort", "team_id"])
    ) == after
    assert upstream == (calc._positive_ml_evidence_scale(row), calc._same_age_raw_shrink(row),
                        calc._same_age_publish_penalty(row), calc._play_up_bonus(row))


@pytest.mark.asyncio
async def test_two_pass_composition_preserves_upstream_and_blocks_cache(league, monkeypatch, tmp_path):
    games, metadata = league
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SCF_ENABLED", "false")
    monkeypatch.setenv("ML_LAYER_ENABLED", "false")
    pinned = pd.Timestamp("2026-08-31", tz="UTC")
    original_v2 = calc.compute_rankings_v2
    collected = []
    def pin(*args, **kwargs):
        collected.append((kwargs["pass_label"], kwargs.get("collect_ceiling_connectivity", False)))
        result = original_v2(*args, **kwargs)
        result["teams"]["last_calculated"] = pinned
        return result
    monkeypatch.setattr(calc, "compute_rankings_v2", pin)
    frames = []
    original_caps = calc._compute_publication_cap_scores
    def capture(teams, base):
        frames.append(teams.assign(shadow_pre_cap_score=base).copy(deep=True))
        return original_caps(teams, base)
    monkeypatch.setattr(calc, "_compute_publication_cap_scores", capture)
    kwargs = dict(games_df=games, today=pd.Timestamp("2026-08-31"), fetch_from_supabase=False,
                  persist_game_residuals=False, persist_game_explainability=False,
                  calculate_rank_changes_enabled=False, save_snapshot=False)
    client = harness.FrozenClient(metadata, pd.DataFrame(columns=["deprecated_team_id", "canonical_team_id"]))
    baseline = await calc.compute_all_cohorts(client, **kwargs)
    baseline_frames = frames.copy()
    frames.clear()
    collected.clear()
    cache_bytes = {p.name: p.read_bytes() for p in (tmp_path / "data/cache").glob("*.parquet")}
    assert cache_bytes
    reads = []
    read = pd.read_parquet
    def no_cache(path, *args, **kwargs):
        reads.append(str(path))
        assert "rankings_" not in str(path)
        return read(path, *args, **kwargs)
    monkeypatch.setattr(pd, "read_parquet", no_cache)
    candidate = await calc.compute_all_cohorts(client, ceiling_connectivity_enabled=True, **kwargs)
    assert not reads, "C1 attempted a cache read even if the loader later fell back to rebuilding"
    assert collected == [("Pass1", False), ("Pass1", False), ("Pass2", True), ("Pass2", True)]
    assert cache_bytes == {p.name: p.read_bytes() for p in (tmp_path / "data/cache").glob("*.parquet")}
    assert "scf" not in candidate["teams"].columns
    assert "_ceiling_source_cohort" not in candidate["teams"].columns
    assert set(candidate["ceiling_connectivity"].team_id) == set(candidate["teams"].team_id)
    pd.testing.assert_frame_equal(baseline["games_used"], candidate["games_used"], check_exact=True)
    assert len(frames) == len(baseline_frames) == 1
    for left, right in zip(baseline_frames, frames):
        checks.assert_equal_frames(left.drop(columns="publication_cap_rank"),
                                   right.drop(columns="publication_cap_rank"), "pre-cap integration")


@pytest.mark.asyncio
async def test_full_composition_keeps_the_winning_cohorts_diagnostics(league, monkeypatch, tmp_path):
    games, metadata = league
    older = games[(games.gender == "male") & (games.date <= "2026-08-10")].copy()
    names = {f"male-{i}": f"older-{i}" for i in range(1, 4)}
    for column in ("team_id", "opp_id", "home_team_master_id"):
        older[column] = older[column].replace(names)
    for column in ("id", "game_id"):
        older[column] = "older-" + older[column]
    older["age"], older["opp_age"] = "11", "11"
    games = pd.concat([games, older], ignore_index=True)
    metadata = pd.concat([metadata, pd.DataFrame(dict(team_id_master=list(names.values()), state_code="AZ",
                                                     league=None, is_deprecated=False))], ignore_index=True)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SCF_ENABLED", "false")
    monkeypatch.setenv("ML_LAYER_ENABLED", "false")
    captured = []
    original = calc.compute_rankings_v2
    def record(*args, **kwargs):
        result = original(*args, **kwargs)
        if kwargs.get("collect_ceiling_connectivity"):
            captured.append(result["ceiling_connectivity"].copy(deep=True))
        result["teams"]["last_calculated"] = pd.Timestamp("2026-08-31", tz="UTC")
        return result
    monkeypatch.setattr(calc, "compute_rankings_v2", record)
    client = harness.FrozenClient(metadata, pd.DataFrame(columns=["deprecated_team_id", "canonical_team_id"]))
    result = await calc.compute_all_cohorts(
        client, games_df=games, today=pd.Timestamp("2026-08-31"), fetch_from_supabase=False,
        persist_game_residuals=False, persist_game_explainability=False,
        calculate_rank_changes_enabled=False, save_snapshot=False, ceiling_connectivity_enabled=True,
    )
    possibilities = pd.concat(captured, ignore_index=True).query("team_id == 'male-0'")
    assert set(possibilities.source_cohort_age) == {"10", "11"}
    # The younger cohort has 18 games and the older cohort has 12 for this team.
    selected = result["teams"].set_index("team_id").loc["male-0"]
    assert selected["age_num"] == 10
    expected = possibilities[possibilities.source_cohort_age == "10"].reset_index(drop=True)
    actual = result["ceiling_connectivity"].query("team_id == 'male-0'").reset_index(drop=True)
    pd.testing.assert_frame_equal(actual[expected.columns], expected, check_exact=True)


@pytest.mark.asyncio
async def test_enabled_mode_refuses_unsafe_or_incompatible_entry(monkeypatch):
    monkeypatch.setenv("SCF_ENABLED", "false")
    with pytest.raises(ValueError, match="requires Glicko"):
        await calc.compute_all_cohorts(object(), ceiling_connectivity_enabled=True, use_glicko=False)
    monkeypatch.setenv("SCF_ENABLED", "true")
    with pytest.raises(ValueError, match="SCF disabled"):
        await calc.compute_all_cohorts(object(), ceiling_connectivity_enabled=True)
    with pytest.raises(ValueError, match="Pass2"):
        engine.compute_rankings_v2(pd.DataFrame(), cfg=GlickoConfig(SCF_ENABLED=False),
                                   collect_ceiling_connectivity=True, pass_label="Pass1", team_state_map={})


@pytest.mark.asyncio
@pytest.mark.parametrize("dry_run", [False, True])
async def test_production_composition_restores_caps_and_respects_writers(league, monkeypatch, tmp_path, dry_run):
    """Drive the actual fetch/two-pass/cap path with production persistence settings."""
    games, metadata = league
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SCF_ENABLED", "false")
    monkeypatch.setenv("ML_LAYER_ENABLED", "false")
    calls = []
    async def fetch(**kwargs):
        calls.append("fetch")
        return games.copy(deep=True)
    monkeypatch.setattr(calc, "fetch_games_for_rankings", fetch)
    async def explain(_client, frame):
        assert "scf" not in frame.columns
        calls.append("explainability")
        return len(frame), 0
    async def snapshot(**kwargs):
        frame = kwargs["rankings_df"]
        assert "scf" not in frame.columns
        assert "_ceiling_source_cohort" not in frame.columns
        assert frame.power_score_true.between(0, 1).all()
        calls.append("snapshot")
    async def features(supabase_client, rankings_df, **kwargs):
        frame = rankings_df
        assert "scf" not in frame.columns
        calls.append("features")
    async def changes(supabase_client, current_rankings_df, **kwargs):
        calls.append("rank_changes")
        return current_rankings_df
    monkeypatch.setattr(calc, "_persist_game_explainability", explain)
    monkeypatch.setattr(calc, "save_ranking_snapshot", snapshot)
    monkeypatch.setattr(calc, "_save_prediction_feature_snapshot_safe", features)
    monkeypatch.setattr(calc, "calculate_rank_changes", changes)
    # An absent ML layer has no residual rows to persist; any call is a mistake.
    async def unexpected(*args, **kwargs):
        pytest.fail("Unexpected residual persistence without ML")
    monkeypatch.setattr(calc, "_persist_game_residuals", unexpected)
    original = calc._publication_cap_rank
    capped = []
    def cap(row):
        assert all(field in row for field in ("scf", "unique_opp_states", "bridge_games", "is_isolated"))
        capped.append(row.team_id)
        return original(row)
    monkeypatch.setattr(calc, "_publication_cap_rank", cap)
    client = harness.FrozenClient(metadata, pd.DataFrame(columns=["deprecated_team_id", "canonical_team_id"]))
    result = await calc.compute_all_cohorts(
        client, today=pd.Timestamp("2026-08-31"), fetch_from_supabase=True,
        ceiling_connectivity_enabled=True, persist_game_residuals=not dry_run,
        persist_game_explainability=not dry_run, save_snapshot=not dry_run,
    )
    assert set(capped) == set(result["teams"].team_id)
    assert len(result["teams"]) == 8
    assert calls.count("fetch") == 1
    assert calls.count("rank_changes") == 1
    assert calls.count("explainability") == (0 if dry_run else 2)
    assert calls.count("snapshot") == (0 if dry_run else 1)
    assert calls.count("features") == (0 if dry_run else 1)


@pytest.mark.asyncio
async def test_missing_connectivity_stops_before_publication_snapshot(league, monkeypatch, tmp_path):
    games, metadata = league
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SCF_ENABLED", "false")
    monkeypatch.setenv("ML_LAYER_ENABLED", "false")
    original = calc.compute_rankings_v2
    def incomplete(*args, **kwargs):
        result = original(*args, **kwargs)
        if kwargs.get("collect_ceiling_connectivity"):
            result["ceiling_connectivity"] = result["ceiling_connectivity"].iloc[1:]
        return result
    monkeypatch.setattr(calc, "compute_rankings_v2", incomplete)
    async def forbidden(**kwargs):
        pytest.fail("An incomplete connectivity result reached snapshot publication")
    monkeypatch.setattr(calc, "save_ranking_snapshot", forbidden)
    client = harness.FrozenClient(metadata, pd.DataFrame(columns=["deprecated_team_id", "canonical_team_id"]))
    with pytest.raises(ValueError, match="Ceiling diagnostics"):
        await calc.compute_all_cohorts(
            client, games_df=games, today=pd.Timestamp("2026-08-31"), fetch_from_supabase=False,
            ceiling_connectivity_enabled=True, persist_game_residuals=False,
            persist_game_explainability=False, save_snapshot=True,
        )
