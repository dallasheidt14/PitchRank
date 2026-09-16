"""The saved operator pack is a complete, reproducible selected-cohort snapshot."""

import json
from copy import deepcopy
from dataclasses import replace

import pytest

from src.tournaments.compare_predictor_bridge import ComparePrediction
from src.tournaments.roster_paste import parse_roster
from src.tournaments.roster_resolver import ResolvedTeam
from src.tournaments.seeding_pack import (
    analyze_pack,
    available_cohorts,
    cohort_label,
    make_pack,
    pack_matches,
    prediction_request,
    roster_fingerprint,
    snapshot_ratings,
    team_ids_by_row,
)
from src.tournaments.seeding_predictions import SeedingPredictionBatch

IDS = [f"00000000-0000-4000-8000-{number:012d}" for number in range(1, 6)]
ROWS = parse_roster(
    "Male U12\nClub A\tBoys A\tTX\nClub B\tBoys B\tTX\nUnknown\tUnmatched\tTX\n"
    "Female U12\nClub C\tGirls C\tTX\nMale U14\nClub D\tOlder D\tTX"
).rows
RESOLVED = tuple(
    ResolvedTeam(source_index=index, status="gotsport_id", team_id_master=IDS[slot])
    for index, slot in ((0, 0), (1, 1), (3, 2), (4, 3))
) + (ResolvedTeam(source_index=2, status="unresolved"),)


def _prediction(margin):
    return ComparePrediction(
        predicted_winner="team_a" if margin > 0 else "team_b",
        win_probability_a=0.90 if margin > 0 else 0.05,
        win_probability_b=0.05 if margin > 0 else 0.90,
        draw_probability=0.05,
        expected_score={"teamA": 4 if margin > 0 else 0, "teamB": 0 if margin > 0 else 4},
        expected_margin=margin,
        expected_absolute_goal_difference=4.2,
        blowout_4plus_probability=0.60,
        confidence="low",
        confidence_score=0.42,
    )


def _batch(request):
    teams = {}
    predictions = {}
    for key, cohort in request.items():
        age, gender = key.split("|", 1)
        teams[key] = {
            entrant: {
                "team_id_master": team_id, "team_name": f"Team {entrant}", "power_score_final": 0.55,
                "rank_in_cohort_final": 100, "age": int(age[1:]), "gender": "M" if gender == "Male" else "F",
                "games_played": 10, "prediction_game_count": 10, "latest_game_date": "2026-09-10",
                "test_metadata": {"source": "captured"},
            }
            for entrant, team_id in cohort.items()
        }
        predictions[key] = {(a, b): _prediction(4 if a < b else -4) for a in cohort for b in cohort if a != b}
    return SeedingPredictionBatch(
        predictions=predictions, teams=teams, unavailable={key: {} for key in request},
        generated_at="2026-09-15T18:00:00Z", ratings_as_of="2026-09-14T12:30:00Z", predictor_sha256="a" * 64,
    )


def _pack(selected=("u12|Male",), *, rows=ROWS, resolved=RESOLVED, overrides=None, change_team=None):
    overrides = overrides or {}
    batch = _batch(prediction_request(rows, resolved, overrides, selected))
    if change_team:
        batch.teams["u12|Male"]["0"].update(change_team)
    ratings = {
        team_id: {"state": "TX", "rank_in_state_final": 10, "test_metadata": {"source": "old"}} for team_id in IDS
    }
    return make_pack(rows, resolved, overrides, selected, batch, ratings)


def test_cohorts_have_separate_age_gender_labels_and_numeric_order():
    assert available_cohorts(ROWS) == ("u12|Female", "u12|Male", "u14|Male")
    assert cohort_label("u12|Female") == "U12 Girls"
    assert cohort_label("u14|Male") == "U14 Boys"


def test_a_la_carte_request_keeps_row_identity_and_uses_manual_matches():
    result = prediction_request(ROWS, RESOLVED, {1: {"team_id_master": IDS[4]}}, ["u12|Male"])
    assert result == {"u12|Male": {"0": IDS[0], "1": IDS[4]}}


@pytest.mark.parametrize("selected", [[], ["u13|Male"], ["u12|Male", "u13|Male"]])
def test_requests_reject_empty_or_absent_cohorts(selected):
    with pytest.raises(ValueError, match="Select at least one cohort"):
        prediction_request(ROWS, RESOLVED, {}, selected)


def test_whole_tournament_pack_covers_every_entrant_in_every_cohort():
    pack = _pack(available_cohorts(ROWS))
    analyses = analyze_pack(pack, ROWS, RESOLVED, {})
    assert set(analyses) == {("u12", "Female"), ("u12", "Male"), ("u14", "Male")}
    assert sum(len(item.ordered_ids) + len(item.review) for item in analyses.values()) == 5
    assert analyses[("u12", "Male")].review == {
        "2": "Confirm the club, team name, and age group before seeding."
    }


def test_a_la_carte_snapshot_excludes_other_cohorts_and_ratings():
    pack = _pack()
    assert pack["selected_cohorts"] == ["u12|Male"]
    assert set(pack["teams"]) == {"u12|Male"}
    assert set(pack["ratings"]) == {IDS[0], IDS[1]}
    assert set(analyze_pack(pack, ROWS, RESOLVED, {})) == {("u12", "Male")}


def test_snapshot_does_not_alias_mutable_batch_or_rating_cache():
    request = prediction_request(ROWS, RESOLVED, {}, ["u12|Male"])
    batch = _batch(request)
    ratings = {IDS[0]: {"test_metadata": {"source": "original"}}}
    pack = make_pack(ROWS, RESOLVED, {}, ["u12|Male"], batch, ratings)
    batch.teams["u12|Male"]["0"]["test_metadata"]["source"] = "refreshed"
    batch.unavailable["u12|Male"]["0"] = "later change"
    batch.predictions[("u12|Male")][("0", "1")].expected_score["teamA"] = 99
    ratings[IDS[0]]["test_metadata"]["source"] = "refreshed"
    assert pack["teams"]["u12|Male"]["0"]["test_metadata"] == {"source": "captured"}
    assert pack["unavailable"]["u12|Male"] == {}
    assert pack["predictions"]["u12|Male"][0]["expected_score"]["teamA"] == 4
    assert pack["ratings"][IDS[0]]["test_metadata"] == {"source": "original"}


def test_json_reload_reproduces_predictions_tiers_and_operator_decisions_without_fetching():
    pack = _pack()
    pack["policy"] = {"max_expected_margin": 1.5, "max_blowout_probability": 0.25}
    pack["manual_groups"] = {"u12|Male": [["0", "1"]]}
    pack["operator_notes"] = {"u12|Male": "Director requested one flight; review the mismatch."}
    loaded = json.loads(json.dumps(pack))
    assert analyze_pack(pack, ROWS, RESOLVED, {}) == analyze_pack(loaded, ROWS, RESOLVED, {})
    assert loaded["generated_at"] == "2026-09-15T18:00:00Z"
    assert loaded["ratings_as_of"] == "2026-09-14T12:30:00Z"
    assert loaded["predictor_sha256"] == "a" * 64
    assert loaded["operator_notes"]["u12|Male"].startswith("Director requested")
    assert any("exceeds the matchup limits" in value for value in analyze_pack(loaded, ROWS, RESOLVED, {})[
        ("u12", "Male")
    ].warnings)


def test_changed_identity_roster_or_purchase_selection_invalidates_snapshot():
    pack = _pack()
    assert pack_matches(pack, ROWS, RESOLVED, {}, ["u12|Male"])
    assert not pack_matches(pack, ROWS, RESOLVED, {0: {"team_id_master": IDS[4]}})
    assert not pack_matches(pack, (replace(ROWS[0], team_name_raw="Changed"), *ROWS[1:]), RESOLVED, {})
    assert not pack_matches(pack, (replace(ROWS[0], section_age_group="u13"), *ROWS[1:]), RESOLVED, {})
    assert not pack_matches(pack, ROWS, RESOLVED, {}, ["u12|Female"])
    with pytest.raises(ValueError, match="Rebuild matchup tiers"):
        analyze_pack(pack, ROWS, RESOLVED, {0: {"team_id_master": IDS[4]}})


def test_selection_order_and_duplicate_input_selection_do_not_change_coverage():
    pack = _pack(["u12|Male", "u14|Male", "u12|Male"])
    assert pack["selected_cohorts"] == ["u12|Male", "u14|Male"]
    assert pack_matches(pack, ROWS, RESOLVED, {}, ["u14|Male", "u12|Male"])


@pytest.mark.parametrize("selection", [None, "u12|Male", [], ["u12|Male", "u12|Male"], ["u99|Male"], [{}]])
def test_malformed_saved_selection_cannot_match(selection):
    pack = _pack()
    pack["selected_cohorts"] = selection
    assert not pack_matches(pack, ROWS, RESOLVED, {})


def test_low_confidence_is_reported_without_removing_supported_teams():
    result = analyze_pack(_pack(), ROWS, RESOLVED, {})[("u12", "Male")]
    assert result.ordered_ids == ("0", "1")
    assert set(result.review) == {"2"}
    assert any("low outcome confidence" in warning for warning in result.warnings)


@pytest.mark.parametrize("published,loaded,reviewed", [(2, 10, True), (10, 2, True), (3, 3, False), (None, 10, True)])
def test_three_scored_games_is_an_explicit_floor_on_both_sources(published, loaded, reviewed):
    pack = _pack(change_team={"games_played": published, "prediction_game_count": loaded})
    result = analyze_pack(pack, ROWS, RESOLVED, {})[("u12", "Male")]
    assert ("0" in result.review) is reviewed
    if reviewed:
        assert result.review["0"] == "Fewer than 3 scored games. Use recent results or club input."


@pytest.mark.parametrize(
    "age,reason",
    [
        (13, "The matched team may be older than this age group. Confirm eligibility before seeding."),
        (None, "Confirm the team's age before seeding."),
        (True, "Confirm the team's age before seeding."),
        ("12", "Confirm the team's age before seeding."),
    ],
)
def test_older_or_unknown_team_age_requires_review(age, reason):
    result = analyze_pack(_pack(change_team={"age": age}), ROWS, RESOLVED, {})[("u12", "Male")]
    assert result.review["0"] == reason


def test_younger_team_may_play_up_into_the_tournament_cohort():
    result = analyze_pack(_pack(change_team={"age": 11}), ROWS, RESOLVED, {})[("u12", "Male")]
    assert "0" in result.ordered_ids


def test_matched_gender_disagreement_requires_review():
    result = analyze_pack(_pack(change_team={"gender": "F"}), ROWS, RESOLVED, {})[("u12", "Male")]
    assert result.review["0"] == "The matched team may be in a different gender group. Confirm before seeding."


@pytest.mark.parametrize("age,gender", [("u²", "Male"), ("u123", "Male"), ("u0", "Male"), ("u12", "Unknown")])
def test_invalid_tournament_cohort_is_retained_for_review_without_requesting_predictions(age, gender):
    rows = (replace(ROWS[0], section_age_group=age, section_gender=gender),)
    key = f"{age}|{gender}"
    request = prediction_request(rows, RESOLVED, {}, [key])
    assert request == {key: {}}
    pack = _pack([key], rows=rows)
    result = analyze_pack(pack, rows, RESOLVED, {})[(age, gender)]
    assert result.review == {"0": "Confirm the listed age group and gender before seeding."}


@pytest.mark.parametrize("score", [None, "unknown", True, 1.5])
def test_missing_or_invalid_display_score_requires_review_not_default_strength(score):
    result = analyze_pack(_pack(change_team={"power_score_final": score}), ROWS, RESOLVED, {})[("u12", "Male")]
    assert result.review["0"] == "No current PitchRank score. Use recent results or club input."


def test_preliminary_score_without_a_published_rank_is_named_clearly():
    result = analyze_pack(_pack(change_team={"rank_in_cohort_final": None}), ROWS, RESOLVED, {})[
        ("u12", "Male")
    ]
    assert result.review["0"] == (
        "Not yet ranked. PitchRank has a preliminary score but no published U12 Boys ranking. "
        "Use recent results or club input."
    )


def test_inactive_ranking_is_named_clearly():
    result = analyze_pack(_pack(change_team={"status": "Inactive"}), ROWS, RESOLVED, {})[("u12", "Male")]
    assert result.review["0"] == "No current ranking. Use recent results or club input."


def test_known_duplicate_reason_is_friendly_and_every_roster_row_stays_visible():
    batch = _batch(prediction_request(ROWS, RESOLVED, {}, ["u12|Male"]))
    batch.teams["u12|Male"].pop("0")
    batch.predictions["u12|Male"] = {}
    batch.unavailable["u12|Male"]["0"] = "Two roster entries resolve to the same team; verify the matches."
    pack = make_pack(ROWS, RESOLVED, {}, ["u12|Male"], batch, {})
    result = analyze_pack(pack, ROWS, RESOLVED, {})[("u12", "Male")]
    assert result.ordered_ids == ("1",)
    assert set(result.review) == {"0", "2"}
    assert result.review["0"] == (
        "Two roster entries appear to be the same team. Confirm both team matches before seeding."
    )


def test_arbitrary_unavailable_reason_survives_unchanged():
    batch = _batch(prediction_request(ROWS, RESOLVED, {}, ["u12|Male"]))
    batch.teams["u12|Male"].pop("0")
    batch.predictions["u12|Male"] = {}
    batch.unavailable["u12|Male"]["0"] = "Director note: confirm the local team name."
    pack = make_pack(ROWS, RESOLVED, {}, ["u12|Male"], batch, {})

    result = analyze_pack(pack, ROWS, RESOLVED, {})[("u12", "Male")]

    assert result.review["0"] == "Director note: confirm the local team name."


@pytest.mark.parametrize("reason", [
    "No published cohort rank; placement review required.",
    "No scored games in the Compare lookback window; placement review required.",
])
def test_saved_legacy_unavailable_reason_uses_plain_recent_results_guidance(reason):
    batch = _batch(prediction_request(ROWS, RESOLVED, {}, ["u12|Male"]))
    batch.teams["u12|Male"].pop("0")
    batch.predictions["u12|Male"] = {}
    batch.unavailable["u12|Male"]["0"] = reason
    pack = make_pack(ROWS, RESOLVED, {}, ["u12|Male"], batch, {})

    result = analyze_pack(pack, ROWS, RESOLVED, {})[("u12", "Male")]

    assert result.review["0"] == "Limited recent results. Use club input or recent scores."


@pytest.mark.parametrize(
    "unavailable,rank,expected",
    [
        (
            "No published cohort rank; placement review required.",
            None,
            "Not yet ranked. PitchRank has a preliminary score but no published U12 Boys ranking. "
            "Use recent results or club input.",
        ),
        (
            "No scored games in the Compare lookback window; placement review required.",
            20,
            "No recent Compare results. Use recent results or club input.",
        ),
    ],
)
def test_unavailable_team_uses_saved_rating_to_explain_the_review(unavailable, rank, expected):
    batch = _batch(prediction_request(ROWS, RESOLVED, {}, ["u12|Male"]))
    batch.teams["u12|Male"].pop("0")
    batch.predictions["u12|Male"] = {}
    batch.unavailable["u12|Male"]["0"] = unavailable
    ratings = {
        IDS[0]: {
            "team_name": "Preliminary Team",
            "power_score_final": 0.55,
            "rank_in_cohort_final": rank,
        },
    }
    pack = make_pack(ROWS, RESOLVED, {}, ["u12|Male"], batch, ratings)

    result = analyze_pack(pack, ROWS, RESOLVED, {})[("u12", "Male")]

    assert result.review["0"] == expected


def test_ambiguous_legacy_ranking_error_preserves_identity_and_recent_results_actions():
    batch = _batch(prediction_request(ROWS, RESOLVED, {}, ["u12|Male"]))
    batch.teams["u12|Male"].pop("0")
    batch.predictions["u12|Male"] = {}
    batch.unavailable["u12|Male"]["0"] = "Current ranking data unavailable; placement review required."
    pack = make_pack(ROWS, RESOLVED, {}, ["u12|Male"], batch, {})

    result = analyze_pack(pack, ROWS, RESOLVED, {})[("u12", "Male")]

    assert result.review["0"] == (
        "Confirm the club and team match. Then use recent results or club input before seeding."
    )


def test_duplicate_prediction_rows_fail_instead_of_overwriting():
    pack = _pack()
    pack["predictions"]["u12|Male"].append(deepcopy(pack["predictions"]["u12|Male"][0]))
    with pytest.raises(ValueError, match="duplicate Seeding Compare matchup"):
        analyze_pack(pack, ROWS, RESOLVED, {})


@pytest.mark.parametrize("mutation,error", [
    (lambda pack: pack["predictions"]["u12|Male"].pop(), "matchup coverage"),
    (lambda pack: pack["teams"]["u12|Male"].pop("0"), "entrant coverage"),
    (lambda pack: pack["teams"].pop("u12|Male"), "cohort coverage"),
    (lambda pack: pack["manual_groups"].update({"u14|Male": []}), "manual_groups cohort coverage"),
    (lambda pack: pack["operator_notes"].update({"u12|Male": {"bad": "note"}}), "invalid placement notes"),
    (lambda pack: pack.update(predictor_sha256=""), "predictor identity"),
])
def test_malformed_snapshot_coverage_fails_actionably(mutation, error):
    pack = _pack()
    mutation(pack)
    with pytest.raises(ValueError, match=error):
        analyze_pack(pack, ROWS, RESOLVED, {})


def test_batch_for_the_wrong_selection_cannot_be_saved():
    batch = _batch(prediction_request(ROWS, RESOLVED, {}, ["u14|Male"]))
    with pytest.raises(ValueError, match="cohort coverage"):
        make_pack(ROWS, RESOLVED, {}, ["u12|Male"], batch, {})


def test_duplicate_source_rows_and_resolutions_cannot_silently_overwrite():
    with pytest.raises(ValueError, match="unique source index"):
        roster_fingerprint((ROWS[0], ROWS[0]), RESOLVED, {})
    with pytest.raises(ValueError, match="at most one team resolution"):
        team_ids_by_row(ROWS, (*RESOLVED, RESOLVED[0]), {})


def test_duplicate_canonical_team_in_reloaded_snapshot_cannot_be_tiered_twice():
    pack = _pack()
    pack["teams"]["u12|Male"]["1"]["team_id_master"] = IDS[0]
    with pytest.raises(ValueError, match="duplicate canonical teams"):
        analyze_pack(pack, ROWS, RESOLVED, {})


def test_snapshot_ratings_use_captured_canonical_data_under_requested_id():
    pack = _pack()
    pack["teams"]["u12|Male"]["0"]["team_id_master"] = IDS[4]
    ratings = snapshot_ratings(pack, team_ids_by_row(ROWS, RESOLVED, {}))
    assert ratings[IDS[0]]["team_id_master"] == IDS[4]
    assert ratings[IDS[0]]["power_score_final"] == 0.55
    assert ratings[IDS[0]]["rank_in_state_final"] == 10
    ratings[IDS[0]]["test_metadata"]["source"] = "consumer changed"
    assert pack["teams"]["u12|Male"]["0"]["test_metadata"]["source"] == "captured"


def test_missing_compare_state_rank_preserves_supplemental_display_but_not_strength_values():
    pack = _pack()
    pack["ratings"][IDS[0]].update(power_score_final=0.90, rank_in_cohort_final=1)
    pack["teams"]["u12|Male"]["0"].update(
        rank_in_state_final=None, state=None, power_score_final=None, rank_in_cohort_final=None,
    )
    rating = snapshot_ratings(pack, team_ids_by_row(ROWS, RESOLVED, {}))[IDS[0]]
    assert rating["rank_in_state_final"] == 10
    assert rating["state"] == "TX"
    assert rating["power_score_final"] is None
    assert rating["rank_in_cohort_final"] is None


def test_present_compare_state_rank_takes_precedence_over_supplemental_display():
    pack = _pack()
    pack["teams"]["u12|Male"]["0"].update(rank_in_state_final=4, state="AZ")
    rating = snapshot_ratings(pack, team_ids_by_row(ROWS, RESOLVED, {}))[IDS[0]]
    assert rating["rank_in_state_final"] == 4
    assert rating["state"] == "AZ"


def test_invalid_manual_coverage_and_nonfinite_policy_fail_on_reload():
    pack = _pack()
    pack["manual_groups"] = {"u12|Male": [["0"]]}
    with pytest.raises(ValueError, match="every eligible entrant exactly once"):
        analyze_pack(pack, ROWS, RESOLVED, {})
    pack["manual_groups"] = {}
    pack["policy"]["max_expected_margin"] = float("nan")
    with pytest.raises(ValueError, match="finite"):
        analyze_pack(pack, ROWS, RESOLVED, {})
