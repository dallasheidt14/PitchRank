"""A GotSport repeat day keeps both games through the importer, and no other GotSport game changes uid.

The GotSport scraper sets ``schedule_id`` to GotSport's match id only when the same two teams met
more than once that date. The importer keys and suffixes those games by it, and must never read one
of them as a changed score of the pair's other stored game.
"""

import asyncio
import logging

import pytest

from src.etl.enhanced_pipeline import EnhancedETLPipeline
from tests.unit.test_enhanced_pipeline_changed_score import _CorrectionsDB
from tests.unit.test_enhanced_pipeline_fixture_score_fill import GOTSPORT_ID, _row
from tests.unit.test_enhanced_pipeline_legacy_uid_correction import _import

DATE = "2026-10-11"
PITTSBURGH = "a81e5812-e089-4400-bd43-9cadff4aa7bf"
ELITE = "8afe7bfb-f7be-4958-8859-413df9ca76d6"
PROVIDER_ID_UID = "gotsport:2026-10-11:250383:647111"
MASTER_UID = "gotsport:2026-10-11:8afe7bfb-f7be-4958-8859-413df9ca76d6:a81e5812-e089-4400-bd43-9cadff4aa7bf"


@pytest.fixture(autouse=True)
def _no_swallowed_dedup_error(caplog):
    """The master-id stage logs and swallows its own exceptions, so a crash there reads as an insert.

    Read the call phase's records: pytest resets ``caplog.text`` for teardown, where it is always empty.
    """
    caplog.set_level(logging.WARNING, logger="src.etl.enhanced_pipeline")
    yield
    swallowed = [r for r in caplog.get_records("call") if "Error in master-level dedup check" in r.getMessage()]
    assert swallowed == []


def _stored(uid, home, away, home_score, away_score):
    """A stored row on this module's date; the shared ``_row`` dates every row on its own module's day."""
    return {**_row(uid, home, away, home_score, away_score), "game_date": DATE}


def _perspective(team, opponent, home_away, goals_for, goals_against, schedule_id):
    return {
        "team_id": team,
        "opponent_id": opponent,
        "home_away": home_away,
        "goals_for": goals_for,
        "goals_against": goals_against,
        "game_date": DATE,
        "provider": "gotsport",
        "result": "W" if goals_for > goals_against else "D" if goals_for == goals_against else "L",
        "schedule_id": schedule_id,
    }


def _both_sides(home_goals, away_goals, schedule_id, home="647111", away="250383"):
    """One meeting as each team's own scrape reports it."""
    return [
        _perspective(home, away, "H", home_goals, away_goals, schedule_id),
        _perspective(away, home, "A", away_goals, home_goals, schedule_id),
    ]


class _GameRecordMatcher:
    """Builds the record the way match_game_history does: schedule_id survives only inside raw_data."""

    def __init__(self, masters=None):
        self.masters = masters if masters is not None else {"647111": PITTSBURGH, "250383": ELITE}

    def match_game_history(self, game):
        home = self.masters.get(game["home_provider_id"])
        away = self.masters.get(game["away_provider_id"])
        return {
            "game_uid": game["game_uid"],
            "home_team_master_id": home,
            "away_team_master_id": away,
            "home_provider_id": game["home_provider_id"],
            "away_provider_id": game["away_provider_id"],
            "home_score": game["home_score"],
            "away_score": game["away_score"],
            "result": game.get("result"),
            "game_date": game["game_date"],
            "provider_id": GOTSPORT_ID,
            "match_status": "matched" if home and away else "partial",
            "raw_data": game,
        }


def _run(monkeypatch, db, games, matcher=None, **kwargs):
    inserted, pipeline = _import(
        monkeypatch,
        db,
        games,
        real_validation=True,
        uid_check=True,
        matcher=matcher or _GameRecordMatcher(),
        **kwargs,
    )
    assert pipeline.batch_metrics.errors == []
    return inserted, pipeline


def _rows(inserted):
    return sorted((g["game_uid"], g["home_score"], g["away_score"]) for g in inserted)


def _validated_uids(games):
    pipeline = EnhancedETLPipeline(_CorrectionsDB([]), "gotsport")
    valid, _, _ = asyncio.run(pipeline._validate_and_dedup(games, run_validation=False))
    return sorted(g["game_uid"] for g in valid)


def test_validation_keeps_each_repeat_day_meeting_under_its_own_uid():
    games = _both_sides(1, 0, "27873104") + _both_sides(0, 0, "27873025")

    assert _validated_uids(games) == [
        "gotsport:2026-10-11:250383:647111:27873025",
        "gotsport:2026-10-11:250383:647111:27873104",
    ]


def test_validation_keeps_the_plain_uid_for_games_without_a_schedule_id():
    assert _validated_uids(_both_sides(1, 0, "") + _both_sides(0, 0, "")) == ["gotsport:2026-10-11:250383:647111"]


def test_a_repeat_day_with_nothing_stored_stores_both_games(monkeypatch):
    inserted, _ = _run(monkeypatch, _CorrectionsDB([]), _both_sides(1, 0, "27873104") + _both_sides(0, 0, "27873025"))

    assert _rows(inserted) == [
        (f"{MASTER_UID}:27873025", 0, 0),
        (f"{MASTER_UID}:27873104", 1, 0),
    ]


def test_a_stored_game_matching_one_meeting_lets_only_the_other_in(monkeypatch):
    stored = _stored(PROVIDER_ID_UID, PITTSBURGH, ELITE, 0, 0)
    db = _CorrectionsDB([stored])

    inserted, _ = _run(
        monkeypatch,
        db,
        _both_sides(1, 0, "27873104") + _both_sides(0, 0, "27873025"),
        composite_hits={"prov-gotsport|647111|250383|2026-10-11|0|0"},
    )

    assert _rows(inserted) == [(f"{MASTER_UID}:27873104", 1, 0)]
    assert db.corrections == []
    assert (stored["home_score"], stored["away_score"]) == (0, 0)


def test_a_chunk_holding_only_the_second_meeting_inserts_it_instead_of_correcting_the_first(monkeypatch):
    stored = _stored(PROVIDER_ID_UID, PITTSBURGH, ELITE, 0, 0)
    db = _CorrectionsDB([stored])

    inserted, _ = _run(monkeypatch, db, _both_sides(1, 0, "27873104"))

    assert _rows(inserted) == [(f"{MASTER_UID}:27873104", 1, 0)]
    assert db.corrections == []
    assert (stored["home_score"], stored["away_score"]) == (0, 0)


def test_a_game_on_an_ordinary_day_keeps_the_uid_it_always_had(monkeypatch):
    inserted, _ = _run(monkeypatch, _CorrectionsDB([]), _both_sides(1, 0, ""))

    assert _rows(inserted) == [(MASTER_UID, 1, 0)]


def test_a_changed_score_on_an_ordinary_day_is_still_corrected(monkeypatch):
    stored = _stored(PROVIDER_ID_UID, PITTSBURGH, ELITE, 2, 0)
    db = _CorrectionsDB([stored])

    inserted, pipeline = _run(monkeypatch, db, _both_sides(1, 0, ""))

    assert inserted == []
    assert (stored["home_score"], stored["away_score"]) == (1, 0)
    assert pipeline.metrics.scores_corrected == 1


def test_a_partly_matched_repeat_day_game_keeps_its_match_id(monkeypatch):
    inserted, _ = _run(
        monkeypatch,
        _CorrectionsDB([]),
        _both_sides(1, 0, "27873104"),
        matcher=_GameRecordMatcher({"647111": PITTSBURGH}),
    )

    assert _rows(inserted) == [("gotsport:2026-10-11:250383:647111:27873104", 1, 0)]


def test_a_stored_placeholder_is_corrected_through_its_own_uid_and_the_other_meeting_added(monkeypatch):
    stored = _stored(f"{MASTER_UID}:27873025", PITTSBURGH, ELITE, 0, 0)
    db = _CorrectionsDB([stored])

    inserted, pipeline = _run(monkeypatch, db, _both_sides(1, 0, "27873104") + _both_sides(2, 2, "27873025"))

    assert (stored["home_score"], stored["away_score"]) == (2, 2)
    assert _rows(inserted) == [(f"{MASTER_UID}:27873104", 1, 0)]
    assert pipeline.metrics.scores_corrected == 1


def test_a_repeat_day_result_still_fills_the_pairs_one_stored_fixture(monkeypatch):
    fixture = _stored(PROVIDER_ID_UID, PITTSBURGH, ELITE, None, None)
    db = _CorrectionsDB([fixture])

    inserted, _ = _run(monkeypatch, db, _both_sides(1, 0, "27873104") + _both_sides(0, 0, "27873025"))

    meetings = {(1, 0): f"{MASTER_UID}:27873104", (0, 0): f"{MASTER_UID}:27873025"}
    filled = (fixture["home_score"], fixture["away_score"])
    assert filled in meetings
    [other] = [score for score in meetings if score != filled]
    assert _rows(inserted) == [(meetings[other], *other)]


def test_a_swapped_side_same_score_repeat_already_stored_once_stays_once(monkeypatch):
    stored = _stored(PROVIDER_ID_UID, ELITE, PITTSBURGH, 2, 4)
    db = _CorrectionsDB([stored])
    games = _both_sides(4, 2, "27672820") + _both_sides(2, 4, "27672821", home="250383", away="647111")

    inserted, _ = _run(monkeypatch, db, games, composite_hits={"prov-gotsport|250383|647111|2026-10-11|2|4"})

    assert inserted == []
    assert (stored["home_score"], stored["away_score"]) == (2, 4)
