"""A tournament rematch keeps its own game_uid through the master-id regeneration.

Bracket play puts the same two teams on the pitch twice in a day (a pool game and
then a final or consolation). Each such provider gives every match its own
``schedule_id``, and both the in-batch dedup key and the first ``game_uid`` are
suffixed with it. The pipeline then regenerates the uid from the two master ids
and has to re-append that suffix, or both games collapse onto one uid and the
unique index on ``games.game_uid`` drops the second result.

The suffix is read from the row the matcher matched: ``match_game_history``
returns ``schedule_id`` only inside ``raw_data``, so reading its result directly
yields ``None`` and loses the rematch silently.
"""

import pytest

from src.etl.enhanced_pipeline import REMATCH_PROVIDERS, rematch_game_uid
from src.models.game_matcher import GameHistoryMatcher


def _matched(schedule_id, on_result=False):
    """A matched game as the pipeline sees it, with schedule_id where the matcher puts it."""
    row = {"schedule_id": schedule_id, "game_date": "2026-09-06"}
    matched = {"game_uid": f"athletes2events:2026-09-06:A:B:{schedule_id}", "game_date": "2026-09-06", "raw_data": row}
    if on_result:
        matched["schedule_id"] = schedule_id
    return matched


def _regenerate(provider_code, matched_game):
    """The uid the pipeline writes; calls the production helper, never a copy of it."""
    uid = GameHistoryMatcher.generate_game_uid(
        provider=provider_code, game_date=matched_game.get("game_date", ""), team1_id="master-a", team2_id="master-b"
    )
    return rematch_game_uid(provider_code, uid, matched_game)


@pytest.mark.parametrize("provider", sorted(REMATCH_PROVIDERS))
def test_two_games_of_one_day_keep_two_uids(provider):
    first = _regenerate(provider, _matched("2013-#035-2026-09-06"))
    second = _regenerate(provider, _matched("2013-#118-2026-09-06"))

    assert first != second


@pytest.mark.parametrize("provider", sorted(REMATCH_PROVIDERS))
def test_the_suffix_is_found_where_the_matcher_actually_leaves_it(provider):
    """Only ``raw_data`` carries it; the matcher's own result never does."""
    from_raw = _regenerate(provider, _matched("2013-#035-2026-09-06"))
    from_result = _regenerate(provider, _matched("2013-#035-2026-09-06", on_result=True))

    assert from_raw.endswith(":2013-#035-2026-09-06")
    assert from_raw == from_result


def test_a_provider_without_rematches_is_unsuffixed():
    assert _regenerate("gotsport", _matched("whatever")) == "gotsport:2026-09-06:master-a:master-b"


def test_the_matcher_still_leaves_schedule_id_only_in_raw_data():
    """Pins the reason the lookup reads raw_data; if this fails the fallback can be dropped."""
    import inspect

    source = inspect.getsource(GameHistoryMatcher.match_game_history)
    record = source.split("game_record = {", 1)[1].split("return game_record", 1)[0]

    assert '"schedule_id"' not in record
