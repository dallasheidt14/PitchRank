from scripts.explainy_commentary import generate_commentary


def test_scale_change_is_not_reported_as_team_power_movement():
    commentary = generate_commentary(
        {
            "rank_change": 0,
            "previous_rank": 12,
            "current_rank": 12,
            "previous_power": 0.8,
            "current_power": 0.4,
            "power_change": 0,
            "power_change_comparable": False,
            "games": [],
        },
        "Test FC",
        "Test Club",
    )

    assert "display scale changed" in commentary
    assert "-50.0%" not in commentary
