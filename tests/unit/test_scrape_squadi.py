"""Unit tests for pure helpers in scripts/scrape_squadi_competition.py.

Scope (mirroring tests/unit/test_scrape_playmetrics.py):
- Pure parsers for age/gender/tier, club, external org id, source URL.
- Score validator and UTC-to-local-date converter.
- Token-bundle regex extractors.

The token harvester's network round-trip, the SquadiClient HTTP layer, the
discovery filter, and the CSV writer are covered by the end-to-end dry-run
verification in Task 16, not by unit tests.
"""

from scripts.scrape_squadi_competition import REQUIRED_COLUMNS


def test_required_columns_match_canonical_27_plus_division_name():
    assert REQUIRED_COLUMNS[0] == "provider"
    assert REQUIRED_COLUMNS[-1] == "division_name"
    assert len(REQUIRED_COLUMNS) == 28
    # Order matches scripts/scrape_playmetrics_league.py REQUIRED_COLUMNS exactly
    expected = [
        "provider", "scrape_run_id", "event_id", "event_name", "schedule_id",
        "age_year", "age_group", "gender", "team_id", "team_id_source",
        "team_name", "club_name", "opponent_id", "opponent_id_source",
        "opponent_name", "opponent_club_name", "state", "state_code",
        "game_date", "game_time", "home_away", "goals_for", "goals_against",
        "result", "venue", "source_url", "scraped_at", "division_name",
    ]
    assert REQUIRED_COLUMNS == expected
