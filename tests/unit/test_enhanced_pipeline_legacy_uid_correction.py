"""A result must correct the scored row it duplicates, not sit beside it.

A game saved while its teams were only partly matched keeps a uid built from provider team ids,
and its first score can be stale by the time the master-id uid arrives. The master-level
duplicate check compares scores, so the changed score read as a different game and the same game
was stored twice.
"""

from src.etl.enhanced_pipeline import EnhancedETLPipeline
from tests.unit.test_enhanced_pipeline_changed_score import _CorrectionsDB
from tests.unit.test_enhanced_pipeline_fixture_score_fill import (
    AFC,
    DATE,
    FIXTURE_UID,
    GOTSPORT_ID,
    GREMIO,
    PM_TOURNAMENT_ID,
    RESULT_UID,
    _import_pipeline,
    _incoming,
    _row,
)

OTHER_PROVIDER_ID = "prov-other"


def _import(monkeypatch, db, games, **kwargs):
    return _import_pipeline(monkeypatch, db, games, provider_id=GOTSPORT_ID, **kwargs)


def test_a_changed_score_corrects_the_provider_id_row_instead_of_adding_a_twin(monkeypatch):
    stored = _row(FIXTURE_UID, GREMIO, AFC, 13, 0)
    db = _CorrectionsDB([stored])

    inserted, pipeline = _import(monkeypatch, db, [_incoming(GREMIO, AFC, 8, 0)])

    assert inserted == []
    assert (stored["home_score"], stored["away_score"]) == (8, 0)
    [correction] = db.corrections
    assert correction["original_game_uid"] == FIXTURE_UID
    assert correction["original_values"] == {"home_score": 13, "away_score": 0}
    assert (pipeline.metrics.scores_corrected, pipeline.metrics.scores_correct_failed) == (1, 0)


def test_the_corrected_scores_land_on_the_stored_sides(monkeypatch):
    stored = _row(FIXTURE_UID, GREMIO, AFC, 13, 0)
    db = _CorrectionsDB([stored])

    _import(monkeypatch, db, [_incoming(AFC, GREMIO, 0, 8)])

    assert (stored["home_score"], stored["away_score"]) == (8, 0)


def test_a_row_under_a_master_id_uid_is_left_alone_and_the_result_inserted(monkeypatch):
    stored = _row(f"gotsport:{DATE}:{AFC}:{GREMIO}:x", GREMIO, AFC, 13, 0)
    db = _CorrectionsDB([stored])

    inserted, _ = _import(monkeypatch, db, [_incoming(GREMIO, AFC, 8, 0)])

    assert len(inserted) == 1
    assert db.corrections == []
    assert (stored["home_score"], stored["away_score"]) == (13, 0)


def test_two_different_results_for_the_pair_in_one_batch_change_nothing(monkeypatch):
    stored = _row(FIXTURE_UID, GREMIO, AFC, 13, 0)
    db = _CorrectionsDB([stored])

    inserted, _ = _import(monkeypatch, db, [_incoming(GREMIO, AFC, 8, 0), _incoming(GREMIO, AFC, 1, 3)])

    assert db.corrections == []
    assert (stored["home_score"], stored["away_score"]) == (13, 0)
    assert len(inserted) == 2


def test_a_pair_with_two_games_that_day_is_not_corrected(monkeypatch):
    first = _row(FIXTURE_UID, GREMIO, AFC, 13, 0)
    second = _row(f"gotsport:{DATE}:{AFC}:{GREMIO}:2", GREMIO, AFC, 1, 3)
    db = _CorrectionsDB([first, second])

    inserted, _ = _import(monkeypatch, db, [_incoming(GREMIO, AFC, 8, 0)])

    assert db.corrections == []
    assert len(inserted) == 1


def test_a_same_day_rematch_row_from_a_rematch_provider_blocks_the_correction(monkeypatch):
    stored = _row(FIXTURE_UID, GREMIO, AFC, 13, 0)
    rematch = _row(f"playmetrics_tournament:{DATE}:{AFC}:{GREMIO}:9", GREMIO, AFC, 1, 3, provider=PM_TOURNAMENT_ID)
    db = _CorrectionsDB([stored, rematch])

    inserted, _ = _import(monkeypatch, db, [_incoming(GREMIO, AFC, 8, 0)])

    assert db.corrections == []
    assert len(inserted) == 1


def test_a_pair_that_also_has_an_unscored_fixture_is_not_corrected(monkeypatch):
    stored = _row(FIXTURE_UID, GREMIO, AFC, 13, 0)
    fixture = _row(f"gotsport:{DATE}:{AFC}:{GREMIO}:fx", GREMIO, AFC)
    db = _CorrectionsDB([stored, fixture])

    inserted, _ = _import(monkeypatch, db, [_incoming(GREMIO, AFC, 8, 0)])

    assert db.corrections == []
    assert (stored["home_score"], stored["away_score"]) == (13, 0)


def test_a_first_meeting_filtered_out_as_a_duplicate_still_counts_as_a_second_result(monkeypatch):
    pool_game = _row(FIXTURE_UID, GREMIO, AFC, 2, 1)
    db = _CorrectionsDB([pool_game])
    pool_copy, final = _incoming(GREMIO, AFC, 2, 1), _incoming(GREMIO, AFC, 3, 0)
    pool_key = EnhancedETLPipeline._make_composite_key(object(), pool_copy)

    inserted, _ = _import(monkeypatch, db, [pool_copy, final], composite_hits={pool_key})

    assert db.corrections == []
    assert (pool_game["home_score"], pool_game["away_score"]) == (2, 1)
    assert [(g["home_score"], g["away_score"]) for g in inserted] == [(3, 0)]


class _MasterMatcher:
    """Resolves both provider ids to masters and keeps the uid a real match would build."""

    MASTERS = {"471854": GREMIO, "483752": AFC}

    def match_game_history(self, game):
        return {
            **game,
            "home_team_master_id": self.MASTERS[game["home_team_id"]],
            "away_team_master_id": self.MASTERS[game["away_team_id"]],
            "game_uid": RESULT_UID,
            "match_status": "matched",
        }


def _perspective(goals_for, goals_against):
    return {
        "team_id": "471854",
        "opponent_id": "483752",
        "home_away": "H",
        "goals_for": goals_for,
        "goals_against": goals_against,
        "game_date": DATE,
        "provider": "gotsport",
        "result": "W" if goals_for > goals_against else "L",
    }


def test_a_second_meeting_dropped_by_validation_blocks_the_correction(monkeypatch):
    stored = _row(FIXTURE_UID, GREMIO, AFC, 2, 1)
    db = _CorrectionsDB([stored])

    _import(monkeypatch, db, [_perspective(3, 0), _perspective(2, 1)], real_validation=True, matcher=_MasterMatcher())

    assert db.corrections == []
    assert (stored["home_score"], stored["away_score"]) == (2, 1)


def test_one_result_that_changed_still_corrects_through_real_validation(monkeypatch):
    stored = _row(FIXTURE_UID, GREMIO, AFC, 13, 0)
    db = _CorrectionsDB([stored])

    inserted, pipeline = _import(monkeypatch, db, [_perspective(8, 0)], real_validation=True, matcher=_MasterMatcher())

    assert inserted == []
    assert (stored["home_score"], stored["away_score"]) == (8, 0)
    assert pipeline.metrics.scores_corrected == 1


def test_a_correction_needs_the_provider_id_to_be_known(monkeypatch):
    stored = _row(FIXTURE_UID, GREMIO, AFC, 13, 0, provider=None)
    db = _CorrectionsDB([stored])

    inserted, _ = _import_pipeline(monkeypatch, db, [_incoming(GREMIO, AFC, 8, 0)], provider_id=None)

    assert db.corrections == []
    assert len(inserted) == 1


def test_a_provider_outside_the_correction_list_is_not_corrected(monkeypatch):
    stored = _row(f"sincsports:{DATE}:471854:483752", GREMIO, AFC, 13, 0)
    db = _CorrectionsDB([stored])

    incoming = {**_incoming(GREMIO, AFC, 8, 0), "provider": "sincsports"}

    inserted, _ = _import(monkeypatch, db, [incoming], provider="sincsports")

    assert db.corrections == []
    assert len(inserted) == 1


def test_a_row_from_another_provider_is_not_corrected(monkeypatch):
    stored = {**_row(FIXTURE_UID, GREMIO, AFC, 13, 0), "provider_id": OTHER_PROVIDER_ID}
    db = _CorrectionsDB([stored])

    inserted, _ = _import(monkeypatch, db, [_incoming(GREMIO, AFC, 8, 0)])

    assert db.corrections == []
    assert len(inserted) == 1


def test_an_excluded_row_is_not_corrected(monkeypatch):
    stored = _row(FIXTURE_UID, GREMIO, AFC, 13, 0, excluded=True)
    db = _CorrectionsDB([stored])

    inserted, _ = _import(monkeypatch, db, [_incoming(GREMIO, AFC, 8, 0)])

    assert db.corrections == []
    assert len(inserted) == 1


def test_both_perspectives_of_the_same_result_give_one_correction(monkeypatch):
    stored = _row(FIXTURE_UID, GREMIO, AFC, 13, 0)
    db = _CorrectionsDB([stored])

    inserted, pipeline = _import(
        monkeypatch, db, [_incoming(GREMIO, AFC, 8, 0), _incoming(AFC, GREMIO, 0, 8, result="L")]
    )

    assert inserted == []
    assert len(db.corrections) == 1
    assert pipeline.metrics.scores_corrected == 1


def test_a_dry_run_changes_nothing(monkeypatch):
    stored = _row(FIXTURE_UID, GREMIO, AFC, 13, 0)
    db = _CorrectionsDB([stored])

    inserted, _ = _import(monkeypatch, db, [_incoming(GREMIO, AFC, 8, 0)], dry_run=True)

    assert inserted == []
    assert db.corrections == []
    assert (stored["home_score"], stored["away_score"]) == (13, 0)
