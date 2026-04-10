from scripts.settle_prospective_match_predictions import _pick_candidate


def test_pick_candidate_prefers_exact_team_match_and_division():
    fixture = {
        "competition": "Spring Showcase",
        "division_name": "U12 Gold",
    }
    candidates = [
        (
            {
                "id": "provider-only",
                "competition": "Spring Showcase",
                "division_name": "U12 Gold",
                "event_name": "Spring Showcase",
            },
            False,
            "provider_ids_direct",
        ),
        (
            {
                "id": "team-exact",
                "competition": "Spring Showcase",
                "division_name": "U12 Gold",
                "event_name": "Spring Showcase",
            },
            False,
            "team_ids_direct",
        ),
    ]

    candidate, reversed_orientation, source, scored = _pick_candidate(fixture, candidates)

    assert candidate is not None
    assert candidate["id"] == "team-exact"
    assert reversed_orientation is False
    assert source == "team_ids_direct"
    assert scored[0]["score"] > scored[1]["score"]
