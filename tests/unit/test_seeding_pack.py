"""The saved operator pack is a complete, reproducible selected-cohort snapshot."""

import json
import re
from copy import deepcopy
from dataclasses import asdict, replace
from pathlib import Path

import pytest

from src.tournaments.compare_predictor_bridge import ComparePrediction
from src.tournaments.roster_paste import parse_roster
from src.tournaments.roster_resolver import ResolvedTeam
from src.tournaments.seeding_pack import (
    analyze_pack,
    available_cohorts,
    cohort_label,
    duplicate_identity_rows,
    make_pack,
    needs_placement_review,
    pack_matches,
    placement_review_fingerprint,
    prediction_request,
    roster_fingerprint,
    snapshot_ratings,
    team_ids_by_row,
    upgrade_pack_analysis,
)
from src.tournaments.seeding_predictions import SeedingPredictionBatch
from src.tournaments.seeding_sheet import build_cohort_sheets

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


@pytest.mark.parametrize("old_version", [1, 2])
def test_saved_analysis_upgrade_preserves_prediction_and_operator_choices_without_mutation(old_version):
    old = _pack()
    old["analysis_schema_version"] = old_version
    old["operator_notes"] = {"u12|Male": "Keep the director's exact note."}
    old["policy"]["max_expected_margin"] = 1.75
    old["legacy_manual_groups"] = {"u12|Male": [["0", "1"]]}
    before = deepcopy(old)
    upgraded = upgrade_pack_analysis(old, ROWS, RESOLVED, {}, ["u12|Male"], predictor_sha256="a" * 64)
    assert old == before
    assert upgraded["analysis_schema_version"] == 3
    assert {k: v for k, v in upgraded.items() if k != "analysis_schema_version"} == {
        k: v for k, v in old.items() if k != "analysis_schema_version"
    }
    upgraded["operator_notes"]["u12|Male"] = "Changed copy"
    assert old["operator_notes"]["u12|Male"] == "Keep the director's exact note."


def test_a_note_for_a_cohort_outside_the_selection_survives_an_upgrade():
    old = _pack()
    old["analysis_schema_version"] = 1
    old["operator_notes"] = {"u15|Female": "Girls placement notes"}
    upgraded = upgrade_pack_analysis(old, ROWS, RESOLVED, {}, ["u12|Male"], predictor_sha256="a" * 64)
    assert upgraded["operator_notes"] == {"u15|Female": "Girls placement notes"}


@pytest.mark.parametrize("corruption", ["prediction", "team", "policy", "notes", "roster", "version"])
def test_upgrade_rejects_invalid_snapshot_without_replacing_old_pack(corruption):
    old = _pack()
    old["analysis_schema_version"] = 1
    if corruption == "prediction":
        old["predictions"]["u12|Male"].pop()
    elif corruption == "team":
        old["teams"]["u12|Male"]["0"]["team_id_master"] = "invalid"
    elif corruption == "policy":
        old["policy"]["max_expected_margin"] = 0
    elif corruption == "notes":
        old["operator_notes"] = ["not", "a", "mapping"]
    elif corruption == "roster":
        old["roster_fingerprint"] = "stale"
    else:
        old["schema_version"] = 2
    before = deepcopy(old)
    with pytest.raises(ValueError):
        upgrade_pack_analysis(old, ROWS, RESOLVED, {}, ["u12|Male"], predictor_sha256="a" * 64)
    assert old == before


def test_upgrade_requires_matching_prediction_version_and_selected_cohorts():
    old = _pack()
    old["analysis_schema_version"] = 1
    with pytest.raises(ValueError, match="predictor has changed"):
        upgrade_pack_analysis(old, ROWS, RESOLVED, {}, ["u12|Male"], predictor_sha256="b" * 64)
    with pytest.raises(ValueError, match="selection changed"):
        upgrade_pack_analysis(old, ROWS, RESOLVED, {}, ["u12|Female"], predictor_sha256="a" * 64)


def test_equal_scores_use_registered_names_not_database_names():
    old = _pack()
    old["teams"]["u12|Male"]["0"]["team_name"] = "Z database name"
    old["teams"]["u12|Male"]["1"]["team_name"] = "A database name"
    assert analyze_pack(old, ROWS, RESOLVED, {})[("u12", "Male")].ordered_ids == ("0", "1")


def test_a_la_carte_request_keeps_row_identity_and_uses_manual_matches():
    result = prediction_request(ROWS, RESOLVED, {1: {"team_id_master": IDS[4]}}, ["u12|Male"])
    assert result == {"u12|Male": {"0": IDS[0], "1": IDS[4]}}


def test_not_found_overrides_rejected_match_in_predictions_duplicates_and_exports():
    import csv
    from io import StringIO
    from src.tournaments.seeding_intake_ui import team_csv

    resolved = (replace(RESOLVED[0], matched_name="Rejected match"),
                replace(RESOLVED[1], team_id_master=IDS[0]))
    rows = ROWS[:2]
    overrides = {0: {"not_found": True, "team_id_master": IDS[0], "team_name": "Rejected manual name"}}
    assert team_ids_by_row(rows, resolved, overrides) == {"0": None, "1": IDS[0]}
    assert prediction_request(rows, resolved, overrides, ["u12|Male"]) == {"u12|Male": {"1": IDS[0]}}
    assert duplicate_identity_rows(rows, resolved, overrides) == {}
    pack = _pack(rows=rows, resolved=resolved, overrides=overrides)
    analyses = analyze_pack(pack, rows, resolved, overrides)
    assert analyses[("u12", "Male")].placement_status == {"1": "Seeded", "0": "Not found in PitchRank"}
    ratings = snapshot_ratings(pack, team_ids_by_row(rows, resolved, overrides))
    sheet = build_cohort_sheets(rows, resolved, overrides, ratings, tier_analyses=analyses)[0]
    rejected = sheet.unrated[0]
    assert rejected.team_id_master is None
    assert rejected.pitchrank_team_name is None
    assert rejected.power_score is None
    assert rejected.state_rank is None
    exported = list(csv.DictReader(StringIO(team_csv(rows, resolved, overrides).decode("utf-8-sig"))))
    assert exported[0]["Match method"] == "Not found in PitchRank"
    assert exported[0]["PitchRank ID"] == ""
    assert exported[0]["PitchRank team name"] == ""


def test_duplicate_identity_uses_one_compare_representative_and_reviews_every_registration():
    rows = parse_roster(
        "Male U12\nClub A\tFirst registration\tTX\n"
        "Club B\tSecond registration\tTX\nClub C\tDistinct team\tTX"
    ).rows
    resolved = (
        ResolvedTeam(source_index=0, status="gotsport_id", team_id_master=IDS[0]),
        ResolvedTeam(source_index=1, status="exact_name", team_id_master=IDS[0]),
        ResolvedTeam(source_index=2, status="gotsport_id", team_id_master=IDS[1]),
    )

    request = prediction_request(rows, resolved, {}, ["u12|Male"])

    assert request == {"u12|Male": {"0": IDS[0], "2": IDS[1]}}
    pack = make_pack(
        rows,
        resolved,
        {},
        ["u12|Male"],
        _batch(request),
        {team_id: {"state": "TX", "rank_in_state_final": 10} for team_id in IDS[:2]},
    )
    analysis = analyze_pack(pack, rows, resolved, {})[("u12", "Male")]

    assert analysis.ordered_ids == ("2",)
    assert analysis.review == {
        "0": "Multiple roster entries resolve to the same PitchRank team. Confirm each registration before seeding.",
        "1": "Multiple roster entries resolve to the same PitchRank team. Confirm each registration before seeding.",
    }
    assert analysis.placement_status == {"0": "Data review required", "1": "Data review required", "2": "Seeded"}
    assert len(analysis.ordered_ids) + len(analysis.review) == len(rows)
    assert len({team["team_id_master"] for team in pack["teams"]["u12|Male"].values()}) == 2
    identities = team_ids_by_row(rows, resolved, {})
    sheets = build_cohort_sheets(
        rows,
        resolved,
        {},
        snapshot_ratings(pack, identities),
        tier_analyses={("u12", "Male"): analysis},
    )
    assert [team.team_name for team in (*sheets[0].rated, *sheets[0].unrated)] == [
        "First registration",
        "Second registration",
        "Distinct team",
    ]
    assert [team.review_reason for team in sheets[0].rated[:2]] == [
        "Multiple roster entries resolve to the same PitchRank team. Confirm each registration before seeding."
    ] * 2


def test_override_that_separates_duplicate_identities_restores_tier_eligibility():
    rows = parse_roster("Male U12\nClub A\tTeam A\tTX\nClub B\tTeam B\tTX").rows
    resolved = tuple(
        ResolvedTeam(source_index=index, status="gotsport_id", team_id_master=IDS[0])
        for index in range(2)
    )
    overrides = {1: {"team_id_master": IDS[1]}}

    request = prediction_request(rows, resolved, overrides, ["u12|Male"])
    pack = make_pack(rows, resolved, overrides, ["u12|Male"], _batch(request), {})
    analysis = analyze_pack(pack, rows, resolved, overrides)[("u12", "Male")]

    assert request == {"u12|Male": {"0": IDS[0], "1": IDS[1]}}
    assert analysis.review == {}
    assert set(analysis.ordered_ids) == {"0", "1"}


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


def test_previous_pack_schema_requires_rebuilding_the_matchup_matrix():
    pack = _pack()
    pack["schema_version"] = 1

    assert not pack_matches(pack, ROWS, RESOLVED, {})
    with pytest.raises(ValueError, match="Rebuild matchup tiers"):
        analyze_pack(pack, ROWS, RESOLVED, {})


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


@pytest.mark.parametrize("published,loaded", [(0, 0), (1, 2), (2, 10), (10, 2), (None, 10)])
def test_game_count_does_not_exclude_a_team_with_a_valid_powerscore(published, loaded):
    pack = _pack(change_team={"games_played": published, "prediction_game_count": loaded})
    result = analyze_pack(pack, ROWS, RESOLVED, {})[("u12", "Male")]
    assert "0" in result.ordered_ids
    assert "0" not in result.review


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
    assert result.placement_status["0"] == "Data review required"


def test_younger_team_may_play_up_into_the_tournament_cohort():
    result = analyze_pack(_pack(change_team={"age": 11}), ROWS, RESOLVED, {})[("u12", "Male")]
    assert "0" in result.ordered_ids


def test_matched_gender_disagreement_requires_review():
    result = analyze_pack(_pack(change_team={"gender": "F"}), ROWS, RESOLVED, {})[("u12", "Male")]
    assert result.review["0"] == "The matched team may be in a different gender group. Confirm before seeding."
    assert result.placement_status["0"] == "Data review required"


@pytest.mark.parametrize("age,gender", [("u²", "Male"), ("u123", "Male"), ("u0", "Male"), ("u12", "Unknown")])
def test_invalid_tournament_cohort_is_retained_for_review_without_requesting_predictions(age, gender):
    rows = (replace(ROWS[0], section_age_group=age, section_gender=gender),)
    key = f"{age}|{gender}"
    request = prediction_request(rows, RESOLVED, {}, [key])
    assert request == {key: {}}
    pack = _pack([key], rows=rows)
    result = analyze_pack(pack, rows, RESOLVED, {})[(age, gender)]
    assert result.review == {"0": "Confirm the listed age group and gender before seeding."}
    assert result.placement_status == {"0": "Data review required"}


@pytest.mark.parametrize("score", [None, "unknown", True, 1.5])
def test_missing_or_invalid_display_score_requires_review_not_default_strength(score):
    result = analyze_pack(_pack(change_team={"power_score_final": score}), ROWS, RESOLVED, {})[("u12", "Male")]
    assert result.review["0"] == "No current PitchRank score. Use recent results or club input."
    assert result.placement_status["0"] == "No current rating"


def test_valid_powerscore_without_a_published_rank_is_still_seeded():
    result = analyze_pack(
        _pack(change_team={
            "rank_in_cohort_final": None,
            "status": "Not Enough Ranked Games",
            "games_played": 0,
            "prediction_game_count": 0,
        }),
        ROWS,
        RESOLVED,
        {},
    )[("u12", "Male")]
    assert "0" in result.ordered_ids
    assert "0" not in result.review
    assert result.limited_history == ("0",)


def test_placement_review_is_bound_to_evidence_order_and_notes_not_rebuild_timestamp():
    pack = _pack(change_team={"status": "Not Enough Ranked Games"})
    key = "u12|Male"
    analysis = analyze_pack(pack, ROWS, RESOLVED, {})[("u12", "Male")]
    assert needs_placement_review(pack, key, analysis)
    pack["placement_reviews"] = {key: placement_review_fingerprint(pack, key, analysis)}
    restored = json.loads(json.dumps(pack))
    restored["generated_at"] = "2026-09-20T12:00:00Z"
    assert not needs_placement_review(restored, key, analysis)
    for change in ("score", "prediction", "notes", "version"):
        altered = deepcopy(restored)
        if change == "score":
            altered["teams"][key]["0"]["power_score_final"] = .3
        elif change == "prediction":
            altered["predictions"][key][0]["expected_margin"] = 3.5
        elif change == "notes":
            altered["operator_notes"][key] = "Updated guidance"
        else:
            altered["placement_reviews"][key] = "old review fingerprint"
        assert needs_placement_review(altered, key, analysis)


def test_clean_cohort_does_not_require_placement_acknowledgment():
    pack = _pack()
    analysis = analyze_pack(pack, ROWS, RESOLVED, {})[("u12", "Male")]
    assert not needs_placement_review(pack, "u12|Male", analysis)


def test_forecast_reversal_alone_requires_placement_acknowledgment():
    pack = _pack()
    key = "u12|Male"
    for prediction in pack["predictions"][key]:
        pair = (prediction["entrant_a"], prediction["entrant_b"])
        replacement = _prediction(-4 if pair == ("0", "1") else 4)
        prediction.update(asdict(replacement))

    analysis = analyze_pack(pack, ROWS, RESOLVED, {})[("u12", "Male")]

    assert analysis.limited_history == ()
    assert analysis.placement_checks
    assert needs_placement_review(pack, key, analysis)


def test_matched_girls_team_reaches_the_female_seeded_sheet():
    pack = _pack(selected=("u12|Female",))
    analyses = analyze_pack(pack, ROWS, RESOLVED, {})
    analysis = analyses[("u12", "Female")]
    sheets = build_cohort_sheets(
        ROWS,
        RESOLVED,
        {},
        snapshot_ratings(pack, team_ids_by_row(ROWS, RESOLVED, {})),
        tier_analyses=analyses,
    )
    sheet = next(item for item in sheets if item.age_group == "u12" and item.gender == "Female")

    assert analysis.placement_status["3"] == "Seeded"
    assert [team.entrant_id for team in sheet.rated] == ["3"]
    assert sheet.gender == "Female"


def test_inactive_ranking_is_named_clearly():
    result = analyze_pack(_pack(change_team={"status": "Inactive"}), ROWS, RESOLVED, {})[("u12", "Male")]
    assert result.review["0"] == "No current ranking. Use recent results or club input."
    assert result.placement_status["0"] == "No current rating"


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


_TYPESCRIPT_PREDICTOR = Path(__file__).resolve().parents[2] / "frontend" / "lib" / "seedingPredictions.ts"
_STATUS_BY_CODE = {
    "team_not_found": "Data review required",
    "no_current_rating": "No current rating",
    "metadata_conflict": "Data review required",
    "duplicate_entry": "Data review required",
}


def _typescript_unavailable_codes():
    source = _TYPESCRIPT_PREDICTOR.read_text(encoding="utf-8")
    declared = re.search(r"SEEDING_UNAVAILABLE_CODES = \[(.*?)\] as const", source, re.DOTALL)
    return sorted(re.findall(r"'([^']+)'", declared.group(1))), sorted(set(re.findall(r"code: '([^']+)'", source)))


def test_every_code_the_typescript_predictor_sends_has_a_placement_status():
    declared, sent = _typescript_unavailable_codes()
    assert declared == sorted(_STATUS_BY_CODE)
    assert sent == sorted(_STATUS_BY_CODE)


def _unavailable_pack(reason, code=None):
    batch = _batch(prediction_request(ROWS, RESOLVED, {}, ["u12|Male"]))
    batch.teams["u12|Male"].pop("0")
    batch.predictions["u12|Male"] = {}
    batch.unavailable["u12|Male"]["0"] = reason
    if code:
        batch.unavailable_codes["u12|Male"] = {"0": code}
    return make_pack(ROWS, RESOLVED, {}, ["u12|Male"], batch, {})


@pytest.mark.parametrize("code", _typescript_unavailable_codes()[0])
def test_each_typescript_unavailable_code_sets_the_status_whatever_the_sentence_says(code):
    pack = json.loads(json.dumps(_unavailable_pack("Director note: confirm the local team name.", code)))

    result = analyze_pack(pack, ROWS, RESOLVED, {})[("u12", "Male")]

    assert result.review["0"] == "Director note: confirm the local team name."
    assert result.placement_status["0"] == _STATUS_BY_CODE[code]


def test_matched_team_without_a_rating_is_unrated_not_a_data_review():
    pack = _unavailable_pack("No usable current PitchRank rating is available.", "no_current_rating")

    result = analyze_pack(pack, ROWS, RESOLVED, {})[("u12", "Male")]

    assert result.placement_status == {"0": "No current rating", "1": "Seeded", "2": "Data review required"}


@pytest.mark.parametrize("reason,status", [
    ("No usable current PitchRank rating is available.", "No current rating"),
    ("Two roster entries appear to be the same team. Confirm both team matches before seeding.",
     "Data review required"),
    ("Confirm the club, team name, and age group before seeding.", "Data review required"),
])
def test_pack_saved_before_codes_still_classifies_its_reasons(reason, status):
    pack = _unavailable_pack(reason)
    del pack["unavailable_codes"]

    result = analyze_pack(pack, ROWS, RESOLVED, {})[("u12", "Male")]

    assert result.placement_status["0"] == status


def test_saved_unavailable_code_for_a_seeded_team_is_rejected():
    pack = _unavailable_pack("No usable current PitchRank rating is available.", "no_current_rating")
    pack["unavailable_codes"]["u12|Male"]["1"] = "no_current_rating"

    with pytest.raises(ValueError, match="unavailable code"):
        analyze_pack(pack, ROWS, RESOLVED, {})


def test_saved_unavailable_codes_for_an_unrequested_cohort_are_rejected():
    pack = _unavailable_pack("No usable current PitchRank rating is available.", "no_current_rating")
    pack["unavailable_codes"]["u14|Male"] = {}

    with pytest.raises(ValueError, match="unavailable_codes cohort coverage"):
        analyze_pack(pack, ROWS, RESOLVED, {})


def test_unknown_saved_unavailable_code_is_rejected():
    pack = _unavailable_pack("No usable current PitchRank rating is available.", "no_current_rating")
    pack["unavailable_codes"]["u12|Male"]["0"] = "inactive"

    with pytest.raises(ValueError, match="unavailable code"):
        analyze_pack(pack, ROWS, RESOLVED, {})


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
