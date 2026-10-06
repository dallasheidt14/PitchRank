"""Publication cutoffs and bands must never cross age/gender boundaries."""

import pandas as pd
import pytest

from src.rankings import calculator
from src.rankings.calculator import (
    _apply_publication_cap_band,
    _collect_top_tier_weak_uncapped,
    _compute_publication_cap_scores,
)
from src.rankings.power_score_scale import published_power_score


def _teams():
    return pd.DataFrame(
        {
            "team_id": ["m1", "m2", "f1", "f2"],
            "age_num": [16, 16, 16, 16],
            "gender": ["Male", "Male", "Female", "Female"],
            "status": ["Active"] * 4,
            "publication_cap_rank": [2] * 4,
        },
        index=[10, 20, 30, 40],
    )


def test_cutoffs_do_not_change_when_only_other_gender_scores_change():
    teams = _teams()
    before = pd.Series([0.90, 0.80, 0.70, 0.60], index=teams.index)
    after = pd.Series([0.90, 0.80, 0.99, 0.98], index=teams.index)
    first = _compute_publication_cap_scores(teams, before)
    second = _compute_publication_cap_scores(teams, after)

    assert first.loc[10] == pytest.approx(0.799999)
    assert second.loc[10] == pytest.approx(0.799999)
    assert first.loc[30] == pytest.approx(0.599999)
    assert second.loc[30] == pytest.approx(0.979999)


def test_band_does_not_change_when_only_other_gender_scores_change():
    teams = _teams().assign(publication_cap_score=0.70)
    before = pd.Series([0.95, 0.90, 0.85, 0.80], index=teams.index)
    after = pd.Series([0.95, 0.90, 0.99, 0.98], index=teams.index)
    first = _apply_publication_cap_band(before, teams)
    second = _apply_publication_cap_band(after, teams)

    assert first.loc[10] == pytest.approx(0.699999)
    assert first.loc[20] == pytest.approx(0.694999)
    pd.testing.assert_series_equal(first.loc[[10, 20]], second.loc[[10, 20]])


def test_cutoffs_use_only_active_teams_in_the_same_age_and_gender():
    teams = _teams()
    teams.loc[30:40, "gender"] = "Male"
    teams.loc[30:40, "age_num"] = 17
    teams.loc[20, "status"] = "Inactive"
    scores = pd.Series([0.9, 0.1, 0.99, 0.98], index=teams.index)

    caps = _compute_publication_cap_scores(teams, scores)

    # Rank two in a one-active-team cohort uses the last eligible score.
    assert caps.loc[10] == pytest.approx(0.899999)
    assert caps.loc[30] == pytest.approx(0.979999)
    shuffled = teams.sample(frac=1, random_state=12)
    pd.testing.assert_series_equal(
        caps.sort_index(), _compute_publication_cap_scores(shuffled, scores).sort_index()
    )


@pytest.mark.parametrize("key", ["age_num", "gender"])
def test_capped_teams_without_cohort_identity_fail_closed(key):
    teams = _teams().assign(publication_cap_score=0.7)
    teams.loc[10, key] = None
    scores = pd.Series(0.9, index=teams.index)
    with pytest.raises(ValueError, match="non-null age_num and gender"):
        _compute_publication_cap_scores(teams, scores)
    with pytest.raises(ValueError, match="non-null age_num and gender"):
        _apply_publication_cap_band(scores, teams)


def test_top_tier_warning_ranks_each_gender_and_excludes_inactive_teams():
    teams = pd.DataFrame({
        "team_id": [f"m{i:02}" for i in range(26)] + ["girl", "inactive"],
        "age_num": [13] * 28,
        "gender": ["Male"] * 26 + ["Female", "Female"],
        "status": ["Active"] * 27 + ["Inactive"],
        "publication_cap_rank": [pd.NA] * 28,
        "same_age_top100_opp_count": [3] * 26 + [0, 0],
        "same_age_top500_opp_count": [7] * 26 + [2, 2],
        "same_age_top500_non_loss_opp_count": [6] * 26 + [1, 1],
        "same_age_avg_opp_power_adj": [0.7] * 26 + [0.5, 0.5],
    })
    scores = pd.Series([0.9] * 26 + [0.8, 0.99], index=teams.index)

    flagged = _collect_top_tier_weak_uncapped(teams, scores)

    assert flagged["team_id"].tolist() == ["girl"]
    assert flagged["provisional_rank"].tolist() == [1]


@pytest.mark.asyncio
async def test_full_publication_matches_gender_only_run_and_ignores_other_gender_changes(monkeypatch):
    """Drive the real orchestrator, not just correctly pre-split helper inputs."""
    # Equal cutoff values must not accidentally join the two cap bands.
    baseline = {"m1": 0.9, "m2": 0.8, "f1": 0.95, "f2": 0.8}

    async def fake_engine(supabase_client, games_df, today, **_kwargs):
        cohort = games_df.iloc[0]
        rows = [{
            "team_id": team_id,
            "age": "16",
            "age_num": 16,
            "gender": cohort["gender"],
            "mu": 1500.0,
            "sigma": 80.0,
            "volatility": 0.06,
            "sos_norm": 0.6,
            "powerscore_adj": baseline[team_id],
            "powerscore_ml": baseline[team_id],
            "status": "Active",
        } for team_id in games_df["team_id"].unique()]
        return {"teams": pd.DataFrame(rows), "games_used": games_df.copy()}

    monkeypatch.setattr(calculator, "compute_rankings_with_ml", fake_engine)
    monkeypatch.setattr(calculator, "batch_fetch_rows", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        calculator, "_compute_same_age_evidence_metrics",
        lambda _games, teams, _frozen: teams[["team_id"]].copy(),
    )
    # Fixed gate decisions isolate publication composition from schedule modelling.
    monkeypatch.setattr(calculator, "_publication_cap_rank", lambda _row: 2)
    monkeypatch.setattr(calculator, "_positive_ml_evidence_scale", lambda _row: 1.0)
    for name in ("_same_age_raw_shrink", "_same_age_publish_penalty", "_play_up_bonus"):
        monkeypatch.setattr(calculator, name, lambda _row: 0.0)

    games = pd.DataFrame([
        {"team_id": t, "opp_id": opp, "age": "16", "opp_age": "16",
         "gender": gender, "opp_gender": gender, "gf": 1, "ga": 1,
         "date": pd.Timestamp("2026-09-20")}
        for t, opp, gender in (
            ("m1", "m2", "male"), ("m2", "m1", "male"),
            ("f1", "f2", "female"), ("f2", "f1", "female"),
        )
    ])

    async def publish(source):
        result = await calculator.compute_all_cohorts(
            object(), games_df=source.copy(), today=pd.Timestamp("2026-09-25"),
            fetch_from_supabase=False, persist_game_residuals=False,
            persist_game_explainability=False, calculate_rank_changes_enabled=False,
            save_snapshot=False,
        )
        return result["teams"].set_index("team_id").loc[
            ["m1", "m2"],
            ["publication_cap_score", "power_score_true", "power_score_final", "rank_in_cohort_final"],
        ]

    combined = await publish(games)
    alone = await publish(games[games["gender"] == "male"])
    baseline.update(f1=0.99, f2=0.98)
    changed = await publish(games)

    pd.testing.assert_frame_equal(combined, alone)
    pd.testing.assert_frame_equal(combined, changed)
    assert combined.loc["m1", "publication_cap_score"] == pytest.approx(0.799999)
    assert combined.loc["m1", "power_score_final"] == pytest.approx(
        published_power_score(0.799998, 16, "Male")
    )
    assert combined["rank_in_cohort_final"].tolist() == [1, 2]
