from src.tournaments.event_team_matcher import (
    EventTeamSearchQuery,
    build_candidate_age_groups,
    classify_match_result,
    rank_db_candidates,
)


def test_build_candidate_age_groups_prefers_name_age_and_event_age():
    query = EventTeamSearchQuery(
        event_team_name="Dynamos SC 2016 SC",
        event_age_group="u11",
        event_gender="Male",
        event_club_name="Dynamos SC",
    )

    assert build_candidate_age_groups(query) == ["u10", "u11"]


def test_rank_db_candidates_skips_same_club_wrong_variant():
    query = EventTeamSearchQuery(
        event_team_name="Eastside B14 white",
        event_age_group="u12",
        event_gender="Male",
        event_club_name="Eastside FC",
        search_age_group="u12",
    )
    candidates = [
        {
            "team_id_master": "white-team",
            "team_name": "Eastside FC 2014 White",
            "club_name": "Eastside FC",
            "state_code": "WA",
            "age_group": "u12",
            "gender": "Male",
            "provider_team_id": "490629",
            "is_deprecated": False,
        },
        {
            "team_id_master": "blue-team",
            "team_name": "Eastside FC 2014 Blue",
            "club_name": "Eastside FC",
            "state_code": "WA",
            "age_group": "u12",
            "gender": "Male",
            "provider_team_id": "490630",
            "is_deprecated": False,
        },
    ]

    matches = rank_db_candidates(query, candidates, limit=5)

    assert [match.team_id_master for match in matches] == ["white-team"]
    assert matches[0].score_reason in {"normalized_name_exact", "weekly_score"}


def test_rank_db_candidates_prefers_actual_play_up_team_age():
    query = EventTeamSearchQuery(
        event_team_name="Dynamos SC 2016 SC",
        event_age_group="u11",
        event_gender="Male",
        event_club_name="Dynamos SC",
    )
    candidates = [
        {
            "team_id_master": "play-up-u10",
            "team_name": "Dynamos SC 2016 SC",
            "club_name": "Dynamos SC",
            "state_code": "AZ",
            "age_group": "u10",
            "gender": "Male",
            "provider_team_id": "126693",
            "is_deprecated": False,
        },
        {
            "team_id_master": "older-u11",
            "team_name": "Dynamos SC 2015 SC",
            "club_name": "Dynamos SC",
            "state_code": "AZ",
            "age_group": "u11",
            "gender": "Male",
            "provider_team_id": "999999",
            "is_deprecated": False,
        },
    ]

    matches = rank_db_candidates(query, candidates, limit=5)

    assert matches[0].team_id_master == "play-up-u10"
    assert matches[0].age_match_kind == "search_age_exact"


def test_classify_match_result_uses_margin_for_high_confidence():
    query = EventTeamSearchQuery(
        event_team_name="FC Dallas 2012",
        event_age_group="u14",
        event_gender="Male",
        event_club_name="FC Dallas",
        search_age_group="u14",
    )
    candidates = [
        {
            "team_id_master": "best",
            "team_name": "FC Dallas 2012",
            "club_name": "FC Dallas",
            "state_code": "TX",
            "age_group": "u14",
            "gender": "Male",
            "provider_team_id": "123",
            "is_deprecated": False,
        },
        {
            "team_id_master": "second",
            "team_name": "Dallas Texans 2012",
            "club_name": "Dallas Texans",
            "state_code": "TX",
            "age_group": "u14",
            "gender": "Male",
            "provider_team_id": "124",
            "is_deprecated": False,
        },
    ]

    matches = rank_db_candidates(query, candidates, limit=5)
    status, best_score, second_score, score_gap = classify_match_result(matches)

    assert status in {"strict_exact", "high_confidence"}
    assert best_score is not None
    assert second_score is not None
    assert score_gap is not None and score_gap >= 0
