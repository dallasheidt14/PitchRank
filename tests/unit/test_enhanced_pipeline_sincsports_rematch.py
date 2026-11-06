"""A SincSports repeat day keeps both games through the importer, and no other game changes uid.

The schedule driver sets ``schedule_id`` only when the same two teams have two numbered games on one
date. A first meeting stored before its day was marked has a plain uid, so a re-import must recognise
it by its score and add only the second meeting.
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

PROVIDER_ID_UID = f"sincsports:{DATE}:250383:647111"
MASTER_UID = f"sincsports:{DATE}:{ELITE}:{PITTSBURGH}"


def _both_sides(home_goals, away_goals, schedule_id, **kwargs):
    rows = _gotsport_both_sides(home_goals, away_goals, schedule_id, **kwargs)
    return [{**row, "provider": "sincsports"} for row in rows]


def _run(monkeypatch, db, games, **kwargs):
    inserted, pipeline = _gotsport_run(monkeypatch, db, games, provider="sincsports", **kwargs)
    return _rows(inserted), pipeline


def test_validation_keeps_each_repeat_day_meeting_under_its_own_uid():
    games = _both_sides(1, 0, "T-7") + _both_sides(3, 2, "T-8")

    assert _validated_uids(games, provider="sincsports") == [
        f"{PROVIDER_ID_UID}:T-7",
        f"{PROVIDER_ID_UID}:T-8",
    ]


def test_validation_keeps_the_plain_uid_for_a_game_without_a_schedule_id():
    assert _validated_uids(_both_sides(1, 0, ""), provider="sincsports") == [PROVIDER_ID_UID]


def test_a_repeat_day_with_nothing_stored_stores_both_games(monkeypatch):
    inserted, _ = _run(monkeypatch, _CorrectionsDB([]), _both_sides(1, 0, "T-7") + _both_sides(3, 2, "T-8"))

    assert inserted == [(f"{MASTER_UID}:T-7", 1, 0), (f"{MASTER_UID}:T-8", 3, 2)]


def test_re_importing_adds_only_the_meeting_not_stored(monkeypatch):
    stored = _stored(MASTER_UID, PITTSBURGH, ELITE, 1, 0)
    db = _CorrectionsDB([stored])

    inserted, pipeline = _run(
        monkeypatch,
        db,
        _both_sides(1, 0, "T-7") + _both_sides(3, 2, "T-8"),
        composite_hits={f"prov-gotsport|647111|250383|{DATE}|1|0"},
    )

    assert inserted == [(f"{MASTER_UID}:T-8", 3, 2)]
    assert stored["game_uid"] == MASTER_UID
    assert pipeline.metrics.scores_corrected == 0


def test_a_re_import_of_the_whole_day_adds_nothing_new(monkeypatch):
    db = _CorrectionsDB(
        [_stored(MASTER_UID, PITTSBURGH, ELITE, 1, 0), _stored(f"{MASTER_UID}:T-8", PITTSBURGH, ELITE, 3, 2)]
    )

    inserted, _ = _run(monkeypatch, db, _both_sides(1, 0, "T-7") + _both_sides(3, 2, "T-8"))

    assert inserted == []


def test_a_repeat_day_result_still_fills_the_pairs_one_stored_fixture(monkeypatch):
    fixture = _stored(MASTER_UID, PITTSBURGH, ELITE, None, None)

    inserted, _ = _run(monkeypatch, _CorrectionsDB([fixture]), _both_sides(1, 0, "T-7") + _both_sides(3, 2, "T-8"))

    assert (fixture["home_score"], fixture["away_score"]) == (1, 0)
    assert inserted == [(f"{MASTER_UID}:T-8", 3, 2)]


def test_a_swapped_side_same_score_repeat_already_stored_once_stays_once(monkeypatch):
    db = _CorrectionsDB([_stored(MASTER_UID, PITTSBURGH, ELITE, 1, 0)])
    swapped = _both_sides(0, 1, "T-8", home="250383", away="647111")

    inserted, _ = _run(monkeypatch, db, _both_sides(1, 0, "T-7") + swapped)

    assert inserted == []


def test_a_changed_score_on_an_ordinary_day_is_not_a_new_game(monkeypatch):
    stored = _stored(MASTER_UID, PITTSBURGH, ELITE, 1, 0)

    inserted, pipeline = _run(monkeypatch, _CorrectionsDB([stored]), _both_sides(2, 0, ""))

    assert inserted == []
    assert (stored["home_score"], stored["away_score"]) == (1, 0)
    assert pipeline.metrics.scores_corrected == 0
