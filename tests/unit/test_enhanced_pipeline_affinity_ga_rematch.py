"""A Georgia doubleheader keeps both games through the importer, and a fixture still takes its later score.

Georgia's scraper sets ``schedule_id`` on every game, so every Georgia uid carries it. Without that the
second game of a day between the same two teams is dropped, counted only among the perspective duplicates.
"""

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


def _both_sides(home_goals, away_goals, schedule_id):
    rows = _gotsport_both_sides(home_goals, away_goals, schedule_id)
    return [{**row, "provider": "affinity_ga"} for row in rows]


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


def test_a_stored_fixture_takes_its_score_rather_than_a_second_row(monkeypatch):
    stored = _stored(f"{MASTER_UID}:698953", PITTSBURGH, ELITE, None, None)

    inserted, pipeline = _run(monkeypatch, _CorrectionsDB([stored]), _both_sides(2, 1, "698953"))

    assert inserted == []
    assert pipeline.metrics.scores_backfilled == 1
