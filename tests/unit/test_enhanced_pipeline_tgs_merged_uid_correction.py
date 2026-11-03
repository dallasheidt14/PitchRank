"""A changed TGS score must correct the stored row even when a team merge changed the game's ids.

The re-scrape builds its game_uid and master ids from the teams as they are now. A game saved before
the merge keeps the old ones, so the uid check misses it and the changed score would land as a second
live row beside it. The master-id pair lookup finds it through team_merge_map; the provider team ids,
which a merge does not change, find a row that map does not resolve, which the tests storing OLD_* ids
without recording a merge exercise.
"""

import pytest

from tests.unit.test_enhanced_pipeline_changed_score import _CorrectionsDB
from tests.unit.test_enhanced_pipeline_fixture_score_fill import (
    AFC,
    DATE,
    GREMIO,
    OLD_AFC,
    OLD_GREMIO,
    _import_pipeline,
    _incoming,
    _no_swallowed_dedup_error,  # noqa: F401 -- autouse: a swallowed dedup crash also reads as "not corrected"
    _row,
)
from tests.unit.test_enhanced_pipeline_legacy_uid_correction import _MasterMatcher, _perspective

TGS_PROVIDER_ID = "prov-tgs"
HOME_PROVIDER_TEAM = "471854"
AWAY_PROVIDER_TEAM = "483752"
CURRENT_UID = f"tgs:{DATE}:{AFC}:{GREMIO}"
MERGED_UID = f"tgs:{DATE}:{OLD_AFC}:{OLD_GREMIO}"
# TGS rows carry their division id as schedule_id
DIVISION_ID = "98765"


def _stored(home, away, home_score, away_score, uid=MERGED_UID, provider_id=TGS_PROVIDER_ID, excluded=False):
    return {
        **_row(uid, home, away, home_score, away_score, excluded=excluded, provider=provider_id),
        "home_provider_id": HOME_PROVIDER_TEAM,
        "away_provider_id": AWAY_PROVIDER_TEAM,
    }


def _tgs_incoming(home_score, away_score, result="W", home=GREMIO, away=AFC, swapped_provider_ids=False):
    game = {
        **_incoming(home, away, home_score, away_score, result=result),
        "game_uid": CURRENT_UID,
        "provider": "tgs",
        "schedule_id": DIVISION_ID,
    }
    if swapped_provider_ids:
        game["home_provider_id"], game["away_provider_id"] = AWAY_PROVIDER_TEAM, HOME_PROVIDER_TEAM
    return game


def _run(monkeypatch, db, incoming, **kwargs):
    return _import_pipeline(
        monkeypatch, db, incoming, provider="tgs", provider_id=TGS_PROVIDER_ID, uid_check=True, **kwargs
    )


def test_a_row_saved_under_merged_away_master_ids_is_corrected_not_duplicated(monkeypatch):
    stored = _stored(OLD_GREMIO, OLD_AFC, 2, 0)
    db = _CorrectionsDB([stored])

    inserted, pipeline = _run(monkeypatch, db, [_tgs_incoming(3, 0)])

    assert inserted == []
    assert (stored["home_score"], stored["away_score"]) == (3, 0)
    [correction] = db.corrections
    assert correction["original_game_uid"] == MERGED_UID
    assert (pipeline.metrics.scores_corrected, pipeline.metrics.scores_correct_failed) == (1, 0)


def test_a_row_under_merged_away_ids_found_through_the_merges_lands_the_scores_on_its_own_sides(monkeypatch):
    # AFC sorts first: the stored home side matches the sorted pair only once OLD_AFC is resolved
    stored = _stored(OLD_AFC, OLD_GREMIO, 0, 2)
    db = _CorrectionsDB([stored])
    db.merge(OLD_GREMIO, GREMIO)
    db.merge(OLD_AFC, AFC)

    inserted, _ = _run(monkeypatch, db, [_tgs_incoming(3, 0)])

    assert inserted == []
    [correction] = db.corrections
    assert correction["original_game_uid"] == MERGED_UID
    assert (stored["home_score"], stored["away_score"]) == (0, 3)


def test_a_changed_result_carrying_a_merged_away_id_corrects_the_row_under_the_survivor(monkeypatch):
    stored = _stored(GREMIO, AFC, 2, 0)
    db = _CorrectionsDB([stored])
    db.merge(OLD_GREMIO, GREMIO)

    inserted, _ = _run(monkeypatch, db, [_tgs_incoming(3, 0, home=OLD_GREMIO)])

    assert inserted == []
    assert (stored["home_score"], stored["away_score"]) == (3, 0)


def test_a_changed_result_whose_home_is_the_sorted_first_team_merged_away_keeps_its_sides(monkeypatch):
    # AFC sorts first: the incoming home side matches the sorted pair only once OLD_AFC is resolved
    stored = _stored(GREMIO, AFC, 2, 0)
    db = _CorrectionsDB([stored])
    db.merge(OLD_AFC, AFC)

    inserted, _ = _run(monkeypatch, db, [_tgs_incoming(0, 3, result="L", home=OLD_AFC, away=GREMIO)])

    assert inserted == []
    assert (stored["home_score"], stored["away_score"]) == (3, 0)


def test_both_perspectives_of_a_result_under_a_merged_away_id_are_read_as_one_result(monkeypatch):
    stored = _stored(GREMIO, AFC, 2, 0)
    db = _CorrectionsDB([stored])
    db.merge(OLD_AFC, AFC)
    perspectives = [
        _tgs_incoming(0, 3, result="L", home=OLD_AFC, away=GREMIO),
        _tgs_incoming(3, 0, home=GREMIO, away=OLD_AFC),
    ]

    inserted, _ = _run(monkeypatch, db, perspectives)

    assert inserted == []
    assert (stored["home_score"], stored["away_score"]) == (3, 0)


def test_a_changed_score_after_a_fill_corrects_the_filled_fixture_despite_a_merged_away_copy(monkeypatch):
    fixture = _stored(GREMIO, AFC, None, None, uid=f"tgs:{DATE}:{HOME_PROVIDER_TEAM}:{AWAY_PROVIDER_TEAM}")
    copy = {**_stored(OLD_GREMIO, AFC, None, None), "id": "row-copy"}
    db = _CorrectionsDB([fixture, copy])
    db.merge(OLD_GREMIO, GREMIO)

    first, _ = _run(monkeypatch, db, [_tgs_incoming(0, 3)])
    second, _ = _run(monkeypatch, db, [_tgs_incoming(1, 3)])

    assert (first, second) == ([], [])
    assert (fixture["home_score"], fixture["away_score"]) == (1, 3)
    assert (copy["home_score"], copy["away_score"]) == (None, None)
    assert len(db.corrections) == 1


def test_a_blank_saved_under_the_scored_rows_ids_still_blocks_its_correction(monkeypatch):
    # Sharing the scored row's saved ids, the blank may be that day's other meeting
    stored = _stored(OLD_GREMIO, AFC, 2, 0)
    blank = {**_stored(OLD_GREMIO, AFC, None, None, uid=f"{MERGED_UID}:blank"), "id": "row-blank"}
    db = _CorrectionsDB([stored, blank])
    db.merge(OLD_GREMIO, GREMIO)

    inserted, _ = _run(monkeypatch, db, [_tgs_incoming(3, 0)])

    assert db.corrections == []
    assert (stored["home_score"], stored["away_score"]) == (2, 0)
    assert [(g["home_score"], g["away_score"]) for g in inserted] == [(3, 0)]


def test_a_scored_copy_under_a_merged_away_id_does_not_stop_the_live_rows_correction(monkeypatch):
    live = _stored(GREMIO, AFC, 2, 0, uid=f"tgs:{DATE}:{HOME_PROVIDER_TEAM}:{AWAY_PROVIDER_TEAM}")
    copy = {**_stored(OLD_GREMIO, AFC, 2, 0), "id": "row-copy"}
    db = _CorrectionsDB([live, copy])
    db.merge(OLD_GREMIO, GREMIO)

    inserted, _ = _run(monkeypatch, db, [_tgs_incoming(3, 0)])

    assert inserted == []
    assert (live["home_score"], live["away_score"]) == (3, 0)
    assert (copy["home_score"], copy["away_score"]) == (2, 0)


def test_a_hidden_copy_under_a_merged_away_id_does_not_swallow_the_live_rows_correction(monkeypatch):
    live = _stored(GREMIO, AFC, 2, 0, uid=f"tgs:{DATE}:{HOME_PROVIDER_TEAM}:{AWAY_PROVIDER_TEAM}")
    # Saved under the merged-away team's own provider id, so the unique index does not tie the two rows
    hidden = {**_stored(OLD_GREMIO, AFC, 3, 0, excluded=True), "id": "row-hidden", "home_provider_id": "3012345"}
    db = _CorrectionsDB([live, hidden])
    db.merge(OLD_GREMIO, GREMIO)

    inserted, _ = _run(monkeypatch, db, [_tgs_incoming(3, 0)])

    assert inserted == []
    assert (live["home_score"], live["away_score"]) == (3, 0)
    assert len(db.corrections) == 1


def test_a_blank_saved_under_the_results_own_ids_blocks_the_correction(monkeypatch):
    # The blank may be the meeting this result reports, not a copy of the scored one
    stored = _stored(OLD_GREMIO, AFC, 2, 0)
    blank = {**_stored(GREMIO, AFC, None, None, uid=f"tgs:{DATE}:blank"), "id": "row-blank"}
    db = _CorrectionsDB([stored, blank])
    db.merge(OLD_GREMIO, GREMIO)

    _run(monkeypatch, db, [_tgs_incoming(3, 0)])

    assert db.corrections == []
    assert (stored["home_score"], stored["away_score"]) == (2, 0)


@pytest.mark.parametrize(
    ("blank_home", "scored_home"),
    [
        pytest.param(OLD_GREMIO, GREMIO, id="blank-under-the-results-merged-away-ids"),
        pytest.param(GREMIO, GREMIO, id="blank-under-the-scored-rows-ids"),
    ],
)
def test_a_blank_blocks_the_correction_of_a_result_naming_a_merged_away_team(monkeypatch, blank_home, scored_home):
    stored = _stored(scored_home, AFC, 2, 0)
    blank = {**_stored(blank_home, AFC, None, None, uid=f"tgs:{DATE}:blank"), "id": "row-blank"}
    db = _CorrectionsDB([stored, blank])
    db.merge(OLD_GREMIO, GREMIO)

    _run(monkeypatch, db, [_tgs_incoming(3, 0, home=OLD_GREMIO)])

    assert db.corrections == []
    assert (stored["home_score"], stored["away_score"]) == (2, 0)


def test_a_row_saved_under_a_stale_uid_but_current_master_ids_is_corrected(monkeypatch):
    stored = _stored(GREMIO, AFC, 2, 0)
    db = _CorrectionsDB([stored])

    inserted, _ = _run(monkeypatch, db, [_tgs_incoming(3, 0)])

    assert inserted == []
    assert (stored["home_score"], stored["away_score"]) == (3, 0)


def test_the_provider_ids_in_the_other_order_land_the_scores_on_the_stored_sides(monkeypatch):
    stored = _stored(OLD_GREMIO, OLD_AFC, 2, 0)
    db = _CorrectionsDB([stored])

    _run(monkeypatch, db, [_tgs_incoming(0, 3, result="L", swapped_provider_ids=True)])

    assert (stored["home_score"], stored["away_score"]) == (3, 0)


def test_a_row_of_another_provider_with_the_same_provider_ids_is_left_alone(monkeypatch):
    stored = _stored(OLD_GREMIO, OLD_AFC, 2, 0, provider_id="prov-other")
    db = _CorrectionsDB([stored])

    inserted, _ = _run(monkeypatch, db, [_tgs_incoming(3, 0)])

    assert db.corrections == []
    assert len(inserted) == 1
    assert (stored["home_score"], stored["away_score"]) == (2, 0)


def test_an_excluded_row_is_not_corrected(monkeypatch):
    stored = _stored(OLD_GREMIO, OLD_AFC, 2, 0, excluded=True)
    db = _CorrectionsDB([stored])

    inserted, _ = _run(monkeypatch, db, [_tgs_incoming(3, 0)])

    assert db.corrections == []
    assert len(inserted) == 1


def test_two_stored_rows_for_the_provider_id_pair_are_not_guessed_between(monkeypatch):
    first = _stored(OLD_GREMIO, OLD_AFC, 2, 0)
    second = {**_stored(OLD_GREMIO, OLD_AFC, 1, 1, uid=f"{MERGED_UID}:2"), "id": "row-second"}
    db = _CorrectionsDB([first, second])

    inserted, _ = _run(monkeypatch, db, [_tgs_incoming(3, 0)])

    assert db.corrections == []
    assert len(inserted) == 1


def test_a_result_the_batch_reports_twice_with_different_scores_is_not_a_change(monkeypatch):
    stored = _stored(OLD_GREMIO, OLD_AFC, 2, 0)
    db = _CorrectionsDB([stored])

    inserted, _ = _run(monkeypatch, db, [_tgs_incoming(3, 0), _tgs_incoming(1, 2, result="L")])

    assert db.corrections == []
    assert (stored["home_score"], stored["away_score"]) == (2, 0)


def test_a_both_sides_change_under_merged_away_ids_is_held(monkeypatch):
    stored = _stored(OLD_GREMIO, OLD_AFC, 1, 1)
    db = _CorrectionsDB([stored])

    inserted, pipeline = _run(monkeypatch, db, [_tgs_incoming(0, 2, result="L")])

    assert inserted == []
    assert db.corrections == []
    assert (stored["home_score"], stored["away_score"]) == (1, 1)
    assert pipeline.metrics.scores_correct_held == 1


def test_a_dry_run_writes_nothing(monkeypatch):
    stored = _stored(OLD_GREMIO, OLD_AFC, 2, 0)
    db = _CorrectionsDB([stored])

    _run(monkeypatch, db, [_tgs_incoming(3, 0)], dry_run=True)

    assert db.corrections == []
    assert (stored["home_score"], stored["away_score"]) == (2, 0)


def test_an_unscored_row_under_merged_away_ids_is_not_read_as_a_changed_score(monkeypatch):
    stored = _stored(OLD_GREMIO, OLD_AFC, None, None)
    db = _CorrectionsDB([stored])

    inserted, pipeline = _run(monkeypatch, db, [_tgs_incoming(3, 0)])

    assert db.corrections == []
    assert pipeline.metrics.scores_correct_held == 0
    assert (stored["home_score"], stored["away_score"]) == (None, None)
    assert len(inserted) == 1


def test_a_pair_with_another_providers_live_row_is_not_guessed_between(monkeypatch):
    merged = _stored(OLD_GREMIO, OLD_AFC, 2, 0)
    other = {
        **_stored(GREMIO, AFC, 2, 0, uid=f"gotsport:{DATE}:{AFC}:{GREMIO}", provider_id="prov-gotsport"),
        "id": "row-other",
    }
    db = _CorrectionsDB([merged, other])

    inserted, _ = _run(monkeypatch, db, [_tgs_incoming(3, 0)])

    assert db.corrections == []
    assert (merged["home_score"], merged["away_score"]) == (2, 0)
    assert len(inserted) == 1


def test_a_row_of_the_same_pair_on_another_day_is_not_the_game_being_corrected(monkeypatch):
    earlier_meeting = {**_stored(OLD_GREMIO, OLD_AFC, 2, 0), "game_date": "2026-09-13"}
    db = _CorrectionsDB([earlier_meeting])

    inserted, _ = _run(monkeypatch, db, [_tgs_incoming(3, 0)])

    assert db.corrections == []
    assert (earlier_meeting["home_score"], earlier_meeting["away_score"]) == (2, 0)
    assert len(inserted) == 1


@pytest.mark.parametrize("home_score, away_score", [(None, 0), (2, None)])
def test_a_row_scored_on_one_side_only_is_not_read_as_a_scored_game(monkeypatch, home_score, away_score):
    stored = _stored(OLD_GREMIO, OLD_AFC, home_score, away_score)
    db = _CorrectionsDB([stored])

    inserted, _ = _run(monkeypatch, db, [_tgs_incoming(3, 0)])

    assert db.corrections == []
    assert len(inserted) == 1


@pytest.mark.parametrize("unlinked", ["home_team_master_id", "away_team_master_id"])
def test_a_half_linked_row_is_not_corrected_and_the_linked_result_is_inserted(monkeypatch, unlinked):
    stored = {**_stored(OLD_GREMIO, OLD_AFC, 2, 0), unlinked: None}
    db = _CorrectionsDB([stored])

    inserted, _ = _run(monkeypatch, db, [_tgs_incoming(3, 0)])

    assert db.corrections == []
    assert (stored["home_score"], stored["away_score"]) == (2, 0)
    assert len(inserted) == 1


def test_the_same_score_listed_the_other_way_round_is_a_duplicate_not_a_correction(monkeypatch):
    stored = _stored(OLD_GREMIO, OLD_AFC, 2, 0)
    db = _CorrectionsDB([stored])

    inserted, pipeline = _run(monkeypatch, db, [_tgs_incoming(0, 2, result="L", swapped_provider_ids=True)])

    assert inserted == []
    assert db.corrections == []
    assert pipeline.metrics.scores_corrected == 0
    assert pipeline.metrics.duplicates_found == 1


# a same-day second meeting on the regenerated-uid path


def _meeting(home_goals, away_goals):
    return {**_perspective(home_goals, away_goals), "provider": "tgs"}


def _run_validated(monkeypatch, db, games):
    return _import_pipeline(
        monkeypatch, db, games, provider="tgs", uid_check=True, real_validation=True, matcher=_MasterMatcher()
    )


def test_a_second_meeting_dropped_by_validation_blocks_the_correction_on_the_master_uid(monkeypatch):
    stored = _row(CURRENT_UID, GREMIO, AFC, 2, 1)
    db = _CorrectionsDB([stored])

    _run_validated(monkeypatch, db, [_meeting(3, 1), _meeting(2, 1)])

    assert db.corrections == []
    assert (stored["home_score"], stored["away_score"]) == (2, 1)


def test_one_changed_result_still_corrects_on_the_master_uid_through_real_validation(monkeypatch):
    stored = _row(CURRENT_UID, GREMIO, AFC, 2, 1)
    db = _CorrectionsDB([stored])

    _, pipeline = _run_validated(monkeypatch, db, [_meeting(3, 1)])

    assert (stored["home_score"], stored["away_score"]) == (3, 1)
    assert pipeline.metrics.scores_corrected == 1


def test_a_pair_with_several_other_rows_under_its_current_ids_is_not_guessed_between(monkeypatch):
    merged = _stored(OLD_GREMIO, OLD_AFC, 2, 0)
    pool = {**_stored(GREMIO, AFC, 1, 0, uid="gotsport:pool", provider_id="prov-gotsport"), "id": "row-pool"}
    final = {**_stored(GREMIO, AFC, 0, 0, uid="gotsport:final", provider_id="prov-gotsport"), "id": "row-final"}
    db = _CorrectionsDB([merged, pool, final])

    inserted, _ = _run(monkeypatch, db, [_tgs_incoming(3, 0)])

    assert db.corrections == []
    assert (merged["home_score"], merged["away_score"]) == (2, 0)
    assert len(inserted) == 1
