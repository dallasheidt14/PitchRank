"""Compare identical paired fixtures, emitted winners, fallback coverage and sealed-read behavior."""

from copy import deepcopy
from types import SimpleNamespace

import pytest
import httpx
from storage3.exceptions import StorageApiError

from src.predictions import score_study_review as review
from src.predictions.score_study import score_payload
from tests.score_study_fixtures import definition, parent_row, sample_artifact


def result_row(index=0):
    row = parent_row()
    fit, _, _ = sample_artifact()
    payload = score_payload(row, definition(), fit, "f"*64)
    return {"baseline_forecast_id": str(index), "source_game_id": "source-"+str(index),
            "game_date": "2026-11-23", "captured_at": "2026-11-16T18:00:00Z",
            "fixture_payload": {"source_snapshot": {"source_url": "https://system.gotsport.com/events/5/schedules",
                                                       "provider_id": "posting-site", "competition": "test"}},
            "group": "gotsport:5", "group_kind": "event", "source_event_id": "5", "provider": "gotsport",
            "payload": payload, "result": {"home_score": 2, "away_score": 1}}


def test_metrics_use_point_score_and_emitted_winner_on_same_fixtures():
    row = result_row()
    report = review.accuracy_report([row])
    assert report["status"] == "insufficient_data" and report["paired_matches"] == 1
    assert report["metrics"]["baseline"]["mean_absolute_goals_per_team"] == 0
    assert report["metrics"]["baseline"]["exact_score_rate"] == 1
    assert report["metrics"]["baseline"]["margin_mae"] == 0
    assert all(m["winner_accuracy"] == 1 for m in report["metrics"].values())
    assert report["production_promotion"] is False
    assert report["group_provenance"] == {"event": 1}


def test_duplicate_source_is_removed_and_ambiguous_reversed_fixtures_cannot_inflate_sample():
    first = result_row()
    duplicate = deepcopy(first)
    duplicate["baseline_forecast_id"] = "another"
    report = review.accuracy_report([first, duplicate])
    assert report["paired_matches"] == 1 and report["coverage"]["duplicate_source_removed"] == 1
    second = result_row(1)
    assert review.accuracy_report([first, second])["coverage"] == {"ambiguous_same_pair_day": 2}


def test_missing_results_and_changed_predictions_are_not_silently_scored():
    row = result_row()
    row["result"] = None
    assert review.accuracy_report([row])["coverage"] == {"missing_or_changed_exact_source_result": 1}
    row = result_row()
    row["payload"]["candidates"]["blend_25"]["prediction"]["expectedScore"]["teamA"] = 19
    with pytest.raises(ValueError, match="replay differs"):
        review.accuracy_report([row])


def test_sealed_review_uses_only_metadata_rpc_and_never_queries_games(monkeypatch):
    class Client:
        def __init__(self):
            self.calls = []

        def rpc(self, name, parameters):
            assert name in {"compare_score_review", "compare_score_coverage"}
            def execute():
                self.calls.append((name, parameters))
                return SimpleNamespace(data=[{"open": False, "captured": 20}] if name.endswith("review") else [])
            return SimpleNamespace(execute=execute)

    monkeypatch.setattr(review, "registered_study", lambda client, signature: definition())
    client = Client()
    report = review.review_scores(client, "f"*64, dry_run=False)
    assert report["status"] == "coverage_only"
    assert [name for name, _ in client.calls] == ["compare_score_review", "compare_score_coverage"]


def test_group_bootstrap_is_deterministic_and_detects_consistent_harm():
    rows = [{"group": str(i), "metrics": {"baseline": {"mean_absolute_goals_per_team": 1},
                                           "blend_25": {"mean_absolute_goals_per_team": 2}}} for i in range(20)]
    result = review._paired_interval(rows, "blend_25")
    assert result == review._paired_interval(rows, "blend_25")
    assert result["difference"] == 1 and result["interval_95"] == [1, 1]
    assert result["one_sided_p"] == 1


@pytest.mark.parametrize("mode", ["preview", "normal", "lost_ack", "corrupt"])
def test_private_report_publication_is_immutable_and_readback_verified(monkeypatch, mode):
    from src.rankings import archive_storage
    monkeypatch.setattr(archive_storage.time, "sleep", lambda _: None)
    class Bucket:
        def __init__(self):
            self.objects, self.calls = {}, []

        def upload(self, key, raw, options):
            self.calls.append(("upload", key))
            assert options["upsert"] == "false"
            if key in self.objects:
                raise StorageApiError("exists", "Duplicate", 409)
            self.objects[key] = raw
            if mode == "lost_ack":
                raise httpx.ReadTimeout("Response lost after committed upload")
        def download(self, key):
            self.calls.append(("download", key))
            return b"corrupt" if mode == "corrupt" else self.objects[key]

    bucket = Bucket()
    client = SimpleNamespace(storage=SimpleNamespace(from_=lambda name: bucket))
    if mode == "corrupt":
        with pytest.raises(ValueError, match="readback differs"):
            review.preserve_report(client, "a"*64, {"status": "test"}, dry_run=False)
        return
    receipt = review.preserve_report(client, "a"*64, {"status": "test"}, dry_run=mode == "preview")
    assert receipt["published"] is (mode != "preview")
    assert len(bucket.objects) == (0 if mode == "preview" else 1)
    if mode == "lost_ack":
        assert sum(call[0] == "upload" for call in bucket.calls) == 2
