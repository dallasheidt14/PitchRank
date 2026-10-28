"""A changed MLS NEXT Kitman score must correct the stored row, including after a team merge.

Kitman edits results after posting them, and the importer re-reads every played game of the season, so
SCORE_CORRECTION_PROVIDERS decides whether a changed score reaches the stored row or is filed as a duplicate.
"""

from tests.unit.test_enhanced_pipeline_changed_score import _CorrectionsDB
from tests.unit.test_enhanced_pipeline_fixture_score_fill import (
    AFC,
    DATE,
    GREMIO,
    _import_pipeline,
    _incoming,
    _row,
)

KITMAN_PROVIDER_ID = "prov-kitman"
OLD_GREMIO = "11111111-1111-4111-8111-111111111111"
OLD_AFC = "22222222-2222-4222-8222-222222222222"
HOME_SQUAD_KEY = "5737:2026"
AWAY_SQUAD_KEY = "5738:2026"
CURRENT_UID = f"mlsnext_kitman:{DATE}:{AFC}:{GREMIO}"
MERGED_UID = f"mlsnext_kitman:{DATE}:{OLD_AFC}:{OLD_GREMIO}"


def _stored(home, away, home_score, away_score, uid=CURRENT_UID, excluded=False):
    return {
        **_row(uid, home, away, home_score, away_score, excluded=excluded, provider=KITMAN_PROVIDER_ID),
        "home_provider_id": HOME_SQUAD_KEY,
        "away_provider_id": AWAY_SQUAD_KEY,
    }


def _kitman_incoming(home_score, away_score, result="W", home=GREMIO, away=AFC, swapped_provider_ids=False):
    game = {
        **_incoming(home, away, home_score, away_score, result=result),
        "game_uid": CURRENT_UID,
        "provider": "mlsnext_kitman",
        "home_provider_id": HOME_SQUAD_KEY,
        "away_provider_id": AWAY_SQUAD_KEY,
    }
    if swapped_provider_ids:
        game["home_provider_id"], game["away_provider_id"] = AWAY_SQUAD_KEY, HOME_SQUAD_KEY
    return game


def _run(monkeypatch, db, incoming, **kwargs):
    return _import_pipeline(
        monkeypatch, db, incoming, provider="mlsnext_kitman", provider_id=KITMAN_PROVIDER_ID, uid_check=True, **kwargs
    )


def test_a_score_that_moved_on_one_side_is_corrected(monkeypatch):
    game = _stored(GREMIO, AFC, 2, 0)
    db = _CorrectionsDB([game])

    inserted, pipeline = _run(monkeypatch, db, [_kitman_incoming(3, 0)])

    assert inserted == []
    assert (game["home_score"], game["away_score"]) == (3, 0)
    assert (pipeline.metrics.scores_corrected, pipeline.metrics.scores_correct_held) == (1, 0)
    assert (pipeline.batch_metrics.scores_corrected, pipeline.batch_metrics.scores_correct_failed) == (1, 0)


def test_a_score_that_swapped_sides_is_corrected(monkeypatch):
    game = _stored(GREMIO, AFC, 3, 1)
    db = _CorrectionsDB([game])

    _, pipeline = _run(monkeypatch, db, [_kitman_incoming(1, 3, result="L")])

    assert (game["home_score"], game["away_score"], game["result"]) == (1, 3, "L")
    assert (pipeline.metrics.scores_corrected, pipeline.metrics.scores_correct_held) == (1, 0)


def test_a_score_read_from_the_other_side_lands_on_the_stored_sides(monkeypatch):
    game = _stored(GREMIO, AFC, 2, 0)
    db = _CorrectionsDB([game])

    _run(monkeypatch, db, [_kitman_incoming(4, 0, home=AFC, away=GREMIO, swapped_provider_ids=True)])

    assert (game["home_score"], game["away_score"]) == (0, 4)


def test_a_score_that_moved_on_both_sides_is_applied_not_held(monkeypatch):
    game = _stored(GREMIO, AFC, 3, 4)
    db = _CorrectionsDB([game])

    inserted, pipeline = _run(monkeypatch, db, [_kitman_incoming(5, 1)])

    assert inserted == []
    assert (game["home_score"], game["away_score"]) == (5, 1)
    assert (pipeline.metrics.scores_corrected, pipeline.metrics.scores_correct_held) == (1, 0)


def test_a_changed_score_without_a_result_is_counted_and_not_written(monkeypatch):
    game = _stored(GREMIO, AFC, 2, 0)
    db = _CorrectionsDB([game])
    incoming = _kitman_incoming(3, 0)
    incoming["result"] = None

    _, pipeline = _run(monkeypatch, db, [incoming])

    assert db.corrections == []
    assert (game["home_score"], game["away_score"]) == (2, 0)
    assert pipeline.metrics.scores_correct_failed == 1
    assert pipeline.batch_metrics.scores_correct_failed == 1


def test_a_row_saved_under_merged_away_master_ids_is_corrected_not_duplicated(monkeypatch):
    stored = _stored(OLD_GREMIO, OLD_AFC, 2, 0, uid=MERGED_UID)
    db = _CorrectionsDB([stored])

    inserted, pipeline = _run(monkeypatch, db, [_kitman_incoming(3, 0)])

    assert inserted == []
    assert (stored["home_score"], stored["away_score"]) == (3, 0)
    [correction] = db.corrections
    assert correction["original_game_uid"] == MERGED_UID
    assert (pipeline.metrics.scores_corrected, pipeline.metrics.scores_correct_failed) == (1, 0)
    assert (pipeline.batch_metrics.scores_corrected, pipeline.batch_metrics.scores_correct_failed) == (1, 0)


def test_a_row_saved_under_a_stale_uid_but_current_master_ids_is_corrected(monkeypatch):
    stored = _stored(GREMIO, AFC, 2, 0, uid=MERGED_UID)
    db = _CorrectionsDB([stored])

    inserted, _ = _run(monkeypatch, db, [_kitman_incoming(3, 0)])

    assert inserted == []
    assert (stored["home_score"], stored["away_score"]) == (3, 0)


def test_the_provider_ids_in_the_other_order_land_the_scores_on_the_stored_sides(monkeypatch):
    stored = _stored(OLD_GREMIO, OLD_AFC, 2, 0, uid=MERGED_UID)
    db = _CorrectionsDB([stored])

    _run(monkeypatch, db, [_kitman_incoming(0, 3, result="L", swapped_provider_ids=True)])

    assert (stored["home_score"], stored["away_score"]) == (3, 0)


def test_two_meetings_of_the_same_squads_in_one_batch_are_not_read_as_a_changed_score(monkeypatch):
    game = _stored(GREMIO, AFC, 2, 0)
    db = _CorrectionsDB([game])

    _run(monkeypatch, db, [_kitman_incoming(2, 0), _kitman_incoming(1, 3, result="L")])

    assert db.corrections == []
    assert (game["home_score"], game["away_score"]) == (2, 0)
