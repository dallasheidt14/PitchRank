from scripts import backtest_tournament_event as event_backtest


def test_parse_group_title_extracts_age_gender_and_division():
    age_group, gender, division_name = event_backtest._parse_group_title("Male U14 - BU14 Super Elite")

    assert age_group == "u14"
    assert gender == "Male"
    assert division_name == "BU14 Super Elite"


def test_derive_pool_sizes_even_and_uneven():
    assert event_backtest._derive_pool_sizes(8, 2) == [4, 4]
    assert event_backtest._derive_pool_sizes(7, 2) == [4, 3]
    assert event_backtest._derive_pool_sizes(5, 1) == [5]


def test_build_event_structure_filters_out_of_scope_ages():
    rows = [
        {
            "group_title": "Male U9 - BU9 Super Elite",
            "team_count": "6",
            "bracket_count": "2",
            "group_url": "https://example.com/u9",
        },
        {
            "group_title": "Male U10 - BU10 Super Elite",
            "team_count": "4",
            "bracket_count": "1",
            "group_url": "https://example.com/u10",
        },
    ]

    structure = event_backtest._build_event_structure(rows)

    assert ("u9", "Male") not in structure
    assert ("u10", "Male") in structure


def test_cohort_status_rows_marks_only_complete_cohorts_runnable():
    event_structure = {
        ("u14", "Male"): [
            {"division_name": "BU14 Super Elite", "team_count": 8},
            {"division_name": "BU14 Super Pro", "team_count": 6},
            {"division_name": "BU14 Premier", "team_count": 6},
        ],
        ("u15", "Male"): [
            {"division_name": "BU15 Super Elite", "team_count": 6},
            {"division_name": "BU15 Super Pro", "team_count": 6},
        ],
    }
    teams_by_division = {
        "BU14 Super Elite": {f"se-{index}" for index in range(8)},
        "BU14 Super Pro": {f"sp-{index}" for index in range(6)},
        "BU14 Premier": {f"p-{index}" for index in range(6)},
        "BU15 Super Elite": {f"u15-se-{index}" for index in range(6)},
        "BU15 Super Pro": {f"u15-sp-{index}" for index in range(4)},
    }

    statuses = event_backtest._cohort_status_rows(event_structure, teams_by_division)

    by_key = {(row["age_group"], row["gender"]): row for row in statuses}
    assert by_key[("u14", "Male")]["runnable"] is True
    assert by_key[("u15", "Male")]["runnable"] is False
    assert by_key[("u15", "Male")]["divisions"][1]["actual_team_count"] == 4


def test_recover_orphaned_games_by_division_assigns_unique_match():
    orphaned_games = [
        {
            "id": "game-1",
            "event_name": None,
            "division_name": None,
            "game_date": "2026-03-21",
            "home_team_master_id": "team-a",
            "away_team_master_id": "team-b",
            "home_score": 1,
            "away_score": 0,
        },
        {
            "id": "game-2",
            "event_name": None,
            "division_name": None,
            "game_date": "2026-03-21",
            "home_team_master_id": "team-a",
            "away_team_master_id": "team-c",
            "home_score": 1,
            "away_score": 1,
        },
    ]
    expected_team_ids_by_division = {
        "BU10 Premier": {"team-a", "team-b"},
        "BU10 Super Elite": {"team-c", "team-d"},
    }

    recovered = event_backtest._recover_orphaned_games_by_division(
        orphaned_games,
        expected_team_ids_by_division,
        event_name="2026 Phoenix Cup - Boys Weekend",
    )

    assert list(recovered) == ["BU10 Premier"]
    assert recovered["BU10 Premier"][0]["id"] == "game-1"
    assert recovered["BU10 Premier"][0]["event_name"] == "2026 Phoenix Cup - Boys Weekend"
    assert recovered["BU10 Premier"][0]["division_name"] == "BU10 Premier"


def test_build_request_payload_marks_event_cohort_on_entrants():
    payload = event_backtest._build_request_payload(
        age_group="u11",
        gender="Male",
        event_name="2026 Phoenix Cup - Boys Weekend",
        divisions=[
            {
                "division_name": "BU11 Platinum",
                "team_count": 6,
                "pool_sizes": [6],
            }
        ],
        teams_by_division={"BU11 Platinum": {"team-a"}},
        teams_by_id={
            "team-a": {
                "team_name": "Dynamos SC 2016 SC",
                "provider_team_id": "126693",
            }
        },
    )

    assert payload["age_group"] == "u11"
    assert payload["gender"] == "male"
    assert payload["entrants"][0]["event_age_group"] == "u11"
    assert payload["entrants"][0]["event_gender"] == "Male"


def test_enrich_registry_rows_with_matcher_promotes_high_confidence_match(monkeypatch):
    registry_rows = [
        {
            "event_team_name": "16B Tesensky",
            "event_club_name": "RSL-AZ North",
            "event_age_group": "u10",
            "search_age_group": "u10",
            "event_gender": "Male",
            "group_titles": "Male U10 - BU10 Premier",
            "in_scope_u10_u19": "True",
            "canonical_resolution_status": "none",
            "resolved_gotsport_provider_team_id": "",
            "resolved_team_id_master": "",
            "resolved_team_name": "",
            "resolved_club_name": "",
        }
    ]

    class FakeResult:
        resolved_status = "high_confidence"
        best_score = 0.9667
        second_score = None
        score_gap = None
        matches = [
            {
                "team_id_master": "team-123",
                "team_name": "2016 Tesensky",
                "club_name": "RSL Arizona North",
                "provider_team_id": "430549",
            }
        ]

    monkeypatch.setattr(event_backtest, "search_event_team_in_db", lambda *args, **kwargs: FakeResult())

    enriched_rows, status_counts = event_backtest._enrich_registry_rows_with_matcher(client=None, registry_rows=registry_rows)

    assert status_counts == {"high_confidence": 1}
    assert enriched_rows[0]["matcher_status"] == "high_confidence"
    assert enriched_rows[0]["resolved_gotsport_provider_team_id"] == "430549"
    assert enriched_rows[0]["resolved_team_id_master"] == "team-123"
    assert enriched_rows[0]["resolved_team_name"] == "2016 Tesensky"
    assert enriched_rows[0]["canonical_resolution_status"] == "high_confidence"
