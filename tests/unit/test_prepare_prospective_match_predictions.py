import json

from scripts.prepare_prospective_match_predictions import load_fixtures_from_jsonl


def test_load_fixtures_from_jsonl_dedupes_home_and_away_rows(tmp_path):
    fixtures_file = tmp_path / "fixtures.jsonl"
    rows = [
        {
            "provider": "gotsport",
            "team_id_source": "111",
            "opponent_id_source": "222",
            "team_name": "Home Team",
            "opponent_name": "Away Team",
            "home_away": "H",
            "game_date": "2026-04-15",
            "competition": "Spring Showcase",
            "division_name": "U12 Gold",
            "venue": "Field 1",
            "match_id": "555_111_222_2026-04-15",
            "source_url": "https://system.gotsport.com/org_event/events/555/schedules",
        },
        {
            "provider": "gotsport",
            "team_id_source": "222",
            "opponent_id_source": "111",
            "team_name": "Away Team",
            "opponent_name": "Home Team",
            "home_away": "A",
            "game_date": "2026-04-15",
            "competition": "Spring Showcase",
            "division_name": "U12 Gold",
            "venue": "Field 1",
            "match_id": "555_111_222_2026-04-15",
            "source_url": "https://system.gotsport.com/org_event/events/555/schedules",
        },
    ]
    fixtures_file.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")

    fixtures = load_fixtures_from_jsonl(fixtures_file, "artifact.jsonl")

    assert len(fixtures) == 1
    fixture = fixtures[0]
    assert fixture.source_event_id == "555"
    assert fixture.home_provider_team_id == "111"
    assert fixture.away_provider_team_id == "222"
    assert fixture.home_team_name == "Home Team"
    assert fixture.away_team_name == "Away Team"
    assert fixture.fixture_key.startswith("gotsport|555|2026-04-15")
