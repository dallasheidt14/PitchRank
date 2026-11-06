"""A Georgia doubleheader keeps both games through the importer, and a fixture still takes its later score.

Georgia's scraper sets ``schedule_id`` on every game, so every Georgia uid carries it. Without that the
second game of a day between the same two teams is dropped, counted only among the perspective duplicates.
"""

import asyncio

from src.etl.enhanced_pipeline import EnhancedETLPipeline
from tests.unit.test_enhanced_pipeline_changed_score import _CorrectionsDB
from tests.unit.test_enhanced_pipeline_gotsport_rematch import (
    DATE,
    ELITE,
    PITTSBURGH,
    _no_swallowed_dedup_error,  # noqa: F401 -- autouse: a swallowed dedup crash reads as an insert
    _rows,
    _stored,
    _validated_uids,
)
from tests.unit.test_enhanced_pipeline_gotsport_rematch import _both_sides as _gotsport_both_sides
from tests.unit.test_enhanced_pipeline_gotsport_rematch import _run as _gotsport_run

PROVIDER_ID_UID = f"affinity_ga:{DATE}:250383:647111"
MASTER_UID = f"affinity_ga:{DATE}:{ELITE}:{PITTSBURGH}"


def _both_sides(home_goals, away_goals, schedule_id, **kwargs):
    rows = _gotsport_both_sides(home_goals, away_goals, schedule_id, **kwargs)
    return [{**row, "provider": "affinity_ga"} for row in rows]


def _fixture(schedule_id, **kwargs):
    """An unplayed game, dated ahead so the importer keeps its blank scores."""
    rows = _both_sides(0, 0, schedule_id, **kwargs)
    return [{**row, "goals_for": "", "goals_against": "", "result": "U", "game_date": "2099-11-07"} for row in rows]


def _run(monkeypatch, db, games):
    inserted, pipeline = _gotsport_run(monkeypatch, db, games, provider="affinity_ga")
    return _rows(inserted), pipeline


def test_validation_keeps_each_game_of_a_doubleheader_under_its_own_uid():
    games = _both_sides(1, 0, "698953") + _both_sides(3, 2, "698968")

    assert _validated_uids(games, provider="affinity_ga") == [
        f"{PROVIDER_ID_UID}:698953",
        f"{PROVIDER_ID_UID}:698968",
    ]


def test_a_doubleheader_stores_both_games(monkeypatch):
    inserted, _ = _run(monkeypatch, _CorrectionsDB([]), _both_sides(1, 0, "698953") + _both_sides(3, 2, "698968"))

    assert inserted == [(f"{MASTER_UID}:698953", 1, 0), (f"{MASTER_UID}:698968", 3, 2)]


def _composite_keys(games):
    """The keys ``_bulk_insert_games`` dedups on, which mirror ``idx_games_unique`` and hold no schedule_id."""
    pipeline = EnhancedETLPipeline(_CorrectionsDB([]), "affinity_ga")
    valid, _, _ = asyncio.run(pipeline._validate_and_dedup(games, run_validation=False))
    return {pipeline._make_composite_key(game) for game in valid}


def test_two_fixtures_stay_two_rows_when_the_teams_swap_home():
    """The shape on the league's pages: one game at each club, so the home and away ids differ between them."""
    games = _fixture("698953", home="647111", away="250383") + _fixture("698968", home="250383", away="647111")

    assert len(_composite_keys(games)) == 2


def test_two_fixtures_with_one_home_team_collapse_at_the_insert():
    """A known limit: ``idx_games_unique`` holds no schedule_id, so this shape needs that index changed."""
    games = _fixture("698953", home="647111", away="250383") + _fixture("698968", home="647111", away="250383")

    assert len(_composite_keys(games)) == 1


def test_a_stored_fixture_takes_its_score_rather_than_a_second_row(monkeypatch):
    stored = _stored(f"{MASTER_UID}:698953", PITTSBURGH, ELITE, None, None)

    inserted, pipeline = _run(monkeypatch, _CorrectionsDB([stored]), _both_sides(2, 1, "698953"))

    assert inserted == []
    assert pipeline.metrics.scores_backfilled == 1
