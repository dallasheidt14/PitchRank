"""The production game policy is newest 30/365, independent of game outcomes."""

from dataclasses import replace

import pandas as pd
import pytest

from src.etl.glicko_config import GlickoConfig
from src.etl.glicko_engine import compute_rankings_v2, derive_windowed_record, select_games_balanced
from src.rankings import calculator

TODAY = pd.Timestamp("2026-08-31")


def games_for(team="A", days=range(40)):
    return pd.DataFrame(
        [
            {
                "team_id": team,
                "opp_id": "B",
                "date": TODAY - pd.Timedelta(days=day),
                "game_id": f"{team}-{day:03}",
                "id": f"{team}-{day:03}",
                "gf": 0,
                "ga": 1,
                "age": "14",
                "gender": "male",
                "opp_age": "14",
                "opp_gender": "male",
            }
            for day in days
        ]
    )


def offline_context():
    return calculator.RankingContext(
        save_snapshot=False, persist_game_residuals=False, persist_game_explainability=False
    )


async def identity_ml(**kwargs):
    return kwargs["teams_df"].copy(), pd.DataFrame()


@pytest.mark.parametrize("tz", [None, "UTC"])
def test_default_window_includes_boundaries_but_no_grace_or_future(tz):
    games = games_for(days=[-1, 0, 364, 365, 366, 393])
    if tz:
        games["date"] = games["date"].dt.tz_localize(tz)
    today = TODAY.tz_localize(tz)
    cfg = GlickoConfig()
    selected = select_games_balanced(games, "A", cfg, today)
    assert selected["game_id"].tolist() == ["A-000", "A-364", "A-365"]
    record = derive_windowed_record(games, cfg, today).set_index("team_id")
    assert record.loc["A", "rec_window_games"] == 3
    assert record.loc["A", "rec_window_goals_against"] == 3


def test_newest_30_never_buys_older_wins_strong_opponents_or_travel():
    games = games_for()
    older = games.index >= 30
    games.loc[older, ["gf", "ga", "opp_age", "opp_id"]] = [9, 0, "15", "StrongAway"]
    original = games.copy(deep=True)

    def forbidden_selection_tier_lookup(_):
        pytest.fail("Selection must not consult league strength")

    for rating in [1000, 2000]:
        selected = select_games_balanced(
            games.sample(frac=1, random_state=rating),
            "A",
            GlickoConfig(),
            TODAY,
            rating_lookup={"B": (rating, 100, 0.06)},
            global_rating_map={"StrongAway": rating},
            team_state_map={"A": "TX", "B": "TX", "StrongAway": "CA"},
            tier_mult_fn=forbidden_selection_tier_lookup,
        )
        assert selected["game_id"].tolist() == [f"A-{day:03}" for day in range(30)]
    pd.testing.assert_frame_equal(games, original)


def test_tied_dates_use_ids_independent_of_input_order():
    games = games_for()
    games["date"] = TODAY
    for seed in [1, 2]:
        selected = select_games_balanced(games.sample(frac=1, random_state=seed), "A", GlickoConfig(), TODAY)
        assert selected["game_id"].tolist() == [f"A-{day:03}" for day in range(30)]


def eligibility_boundary_games():
    return pd.concat(
        [
            games_for(),
            games_for("C", range(10)),
            games_for("D", [*range(9), 366]),
            games_for("E", range(11)),
            games_for("F", range(181, 191)),
        ],
        ignore_index=True,
    )


def assert_10_game_eligibility(teams):
    teams = teams.set_index("team_id")
    for team, count in [("A", 30), ("C", 10), ("E", 11)]:
        assert teams.loc[team, "games_played"] == count
        assert teams.loc[team, "status"] == "Active"
        assert teams.loc[team, "sample_flag"] == "OK"
        assert pd.notna(teams.loc[team, "rank_in_cohort"])
    assert teams.loc["D", "games_played"] == 9
    assert teams.loc["D", "status"] == "Not Enough Ranked Games"
    assert teams.loc["D", "sample_flag"] == "LOW_SAMPLE"
    assert pd.isna(teams.loc["D", "rank_in_cohort"])
    assert teams.loc["F", "games_played"] == 10
    assert teams.loc["F", "status"] == "Inactive"
    assert pd.isna(teams.loc["F", "rank_in_cohort"])


@pytest.mark.parametrize("pass_label", ["Pass1", "Pass2"])
def test_engine_ranks_at_10_games_but_not_nine_or_inactive(pass_label):
    result = compute_rankings_v2(
        eligibility_boundary_games(),
        today=TODAY,
        pass_label=pass_label,
        global_rating_map={"B": 1750} if pass_label == "Pass2" else None,
    )
    used = result["games_used"]
    assert set(used.loc[used.team_id == "A", "game_id"]) == {f"A-{day:03}" for day in range(30)}
    assert "D-366" not in set(used.game_id)
    assert_10_game_eligibility(result["teams"])


@pytest.mark.asyncio
async def test_normal_calculator_fetches_365_days_and_passes_newest_games_to_ml(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    calls = []
    received = []

    async def fetch(**kwargs):
        calls.append(kwargs)
        return eligibility_boundary_games()

    async def ml(**kwargs):
        received.extend(kwargs["games_used_df"]["game_id"])
        return await identity_ml(**kwargs)

    monkeypatch.setattr(calculator, "fetch_games_for_rankings", fetch)
    monkeypatch.setattr(calculator, "apply_predictive_adjustment", ml)
    result = await calculator.compute_rankings_with_ml(object(), today=TODAY, ctx=offline_context())
    assert calls[0]["lookback_days"] == 365
    assert calls[0]["today"] == TODAY
    expected = {
        f"{team}-{day:03}"
        for team, days in [("A", range(30)), ("C", range(10)), ("D", range(9)), ("E", range(11)), ("F", range(181, 191))]
        for day in days
    }
    assert set(received) == expected
    assert_10_game_eligibility(result["teams"])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    [
        {"MIN_GAMES_PROVISIONAL": 12},
        {"MAX_GAMES": 29},
        {"WINDOW_DAYS": 364},
        {"WINDOW_GRACE_DAYS": 1},
        {"BALANCED_SELECTION_ENABLED": True},
        {"date": "2026-09-01"},
    ],
)
async def test_cached_calculation_is_invalidated_by_selection_inputs(monkeypatch, tmp_path, change):
    monkeypatch.chdir(tmp_path)
    calls = []

    def engine(**kwargs):
        calls.append(kwargs)
        return {
            "teams": pd.DataFrame([{"team_id": "A", "powerscore_adj": 0.5}]),
            "games_used": games_for(days=range(2)),
            "game_explainability": pd.DataFrame([{"team_id": "A", "game_id": "A-000"}]),
        }

    monkeypatch.setattr(calculator, "compute_rankings_v2", engine)
    monkeypatch.setattr(calculator, "apply_predictive_adjustment", identity_ml)
    kwargs = dict(
        supabase_client=object(), games_df=games_for(), today=TODAY, fetch_from_supabase=False, ctx=offline_context()
    )
    await calculator.compute_rankings_with_ml(**kwargs)
    await calculator.compute_rankings_with_ml(**kwargs)
    assert len(calls) == 1, "Identical inputs should reuse the complete cache"
    if "date" in change:
        kwargs["today"] = pd.Timestamp(change["date"])
    else:
        monkeypatch.setattr(calculator, "GlickoConfig", lambda: replace(GlickoConfig(), **change))
    await calculator.compute_rankings_with_ml(**kwargs)
    assert len(calls) == 2, "Changed selection inputs must rebuild rankings"


@pytest.mark.asyncio
async def test_legacy_engine_cache_still_accepts_its_game_limit(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    calls = []

    def engine(**kwargs):
        calls.append(kwargs)
        return {"teams": pd.DataFrame(), "games_used": pd.DataFrame()}

    monkeypatch.setattr(calculator, "compute_rankings", engine)
    ctx = offline_context()
    ctx.use_glicko = False
    await calculator.compute_rankings_with_ml(
        object(), games_df=games_for(), today=TODAY, fetch_from_supabase=False, ctx=ctx
    )
    assert len(calls) == 1
