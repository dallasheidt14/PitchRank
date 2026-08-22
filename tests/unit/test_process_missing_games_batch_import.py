"""
Games are imported once per batch, not once per row. import_games_enhanced.py was
being spawned as a subprocess for every request — 40 Python cold starts per run,
measured at 148-276s of a 722-835s run. Also verifies the per-request sleep is gone:
GotSportScraper already rate-limits itself via delay_min/delay_max.
"""
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from unittest.mock import Mock

from scripts.process_missing_games import MissingGamesProcessor


def _request(idx):
    return {
        "id": f"req-{idx}",
        "team_id_master": f"team-{idx}",
        "team_name": f"Team {idx}",
        "provider_id": "prov-1",
        "provider_team_id": str(100 + idx),
        "game_date": "2026-08-20",
    }


def _game(idx):
    return {"game_date": "2026-08-20", "home_team_id": f"team-{idx}", "away_team_id": "opp"}


def _build_processor(requests, games_per_request=1):
    processor = MissingGamesProcessor(Mock(), dry_run=False)
    processor.get_pending_requests = Mock(return_value=requests)
    processor.update_request_status = Mock()
    processor.get_provider_code = Mock(return_value="gotsport")
    processor.import_games = Mock(return_value=games_per_request)
    processor.scrape_games_for_date = Mock(
        side_effect=lambda provider, team_id, date: [_game(team_id) for _ in range(games_per_request)]
    )
    return processor


def test_process_all_imports_every_request_in_one_call():
    processor = _build_processor([_request(i) for i in range(1, 4)])

    processor.process_all(limit=3)

    assert processor.import_games.call_count == 1, (
        f"expected one batched import, got {processor.import_games.call_count} calls"
    )
    games, provider_code = processor.import_games.call_args.args
    assert len(games) == 3
    assert provider_code == "gotsport"


def test_completed_status_uses_scraped_count_not_import_result():
    """Deferring the import must not change per-row games_found."""
    processor = _build_processor([_request(1)], games_per_request=2)
    processor.import_games = Mock(return_value=0)

    processor.process_all(limit=1)

    completed = [c for c in processor.update_request_status.call_args_list if c.args[1] == "completed"]
    assert len(completed) == 1
    assert completed[0].kwargs["games_found"] == 2


def test_flush_groups_pending_imports_by_provider():
    processor = _build_processor([])
    processor._pending_imports = [
        ("gotsport", [_game(1)], "req-1"),
        ("sincsports", [_game(2)], "req-2"),
        ("gotsport", [_game(3)], "req-3"),
    ]

    processor._flush_pending_imports()

    by_provider = {c.args[1]: c.args[0] for c in processor.import_games.call_args_list}
    assert set(by_provider) == {"gotsport", "sincsports"}
    assert len(by_provider["gotsport"]) == 2
    assert len(by_provider["sincsports"]) == 1


def test_flush_falls_back_to_per_request_import_when_batch_fails():
    """A single poison game must not cost the whole batch."""
    processor = _build_processor([])
    processor._pending_imports = [("gotsport", [_game(1)], "req-1"), ("gotsport", [_game(2)], "req-2")]
    processor.import_games = Mock(side_effect=[RuntimeError("poison batch"), 1, 1])

    processor._flush_pending_imports()

    assert processor.import_games.call_count == 3, "expected 1 batch attempt + 2 per-request retries"


def test_process_all_does_not_sleep_between_requests(monkeypatch):
    sleeps = []
    monkeypatch.setattr("scripts.process_missing_games.time.sleep", lambda seconds: sleeps.append(seconds))
    processor = _build_processor([_request(i) for i in range(1, 4)])

    processor.process_all(limit=3)

    assert sleeps == [], f"drainer should not add its own delay; slept {sleeps}"


def _writes(processor, status):
    return [c for c in processor.update_request_status.call_args_list if c.args[1] == status]


def test_request_is_not_completed_until_its_games_are_imported():
    """The pre-batching code imported before marking completed. A row marked
    completed with its games still unimported is excluded from get_pending_requests
    forever, so a crash before the flush would lose them silently."""
    processor = _build_processor([_request(1)])

    processor.process_request(_request(1))

    assert _writes(processor, "completed") == [], "completed must wait for the import"

    processor._flush_pending_imports()

    completed = _writes(processor, "completed")
    assert len(completed) == 1
    assert completed[0].args[0] == "req-1"
    assert completed[0].kwargs["games_found"] == 1


def test_request_with_no_games_is_completed_immediately():
    """Nothing to import means nothing to lose; don't leave the row in 'processing'."""
    processor = _build_processor([_request(1)])
    processor.scrape_games_for_date = Mock(return_value=[])

    processor.process_request(_request(1))

    assert [c.args[0] for c in _writes(processor, "completed")] == ["req-1"]


def test_chunk_whose_import_fails_is_marked_failed_not_completed():
    processor = _build_processor([_request(1), _request(2)])
    processor.import_games = Mock(side_effect=[RuntimeError("poison batch"), RuntimeError("still bad"), 1])

    processor.process_all(limit=2)

    failed = {c.args[0] for c in _writes(processor, "failed")}
    completed = {c.args[0] for c in _writes(processor, "completed")}
    assert "req-1" in failed, "an unimportable request must stay retryable, not silently completed"
    assert "req-1" not in completed
    assert "req-2" in completed, "the healthy request in the same batch must still complete"


def test_failed_import_moves_the_row_out_of_successful_stats():
    processor = _build_processor([_request(1)])
    processor.import_games = Mock(side_effect=[RuntimeError("poison"), RuntimeError("poison")])

    stats = processor.process_all(limit=1)

    assert stats["successful"] == 0
    assert stats["failed"] == 1
