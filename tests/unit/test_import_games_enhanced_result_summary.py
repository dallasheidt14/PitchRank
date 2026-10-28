"""The IMPORT_RESULT line carries the score-correction counts, summed across streamed batches."""

import asyncio
import json
import sys

from scripts import import_games_enhanced as importer
from src.etl.enhanced_pipeline import ImportMetrics


def test_the_summary_carries_the_correction_counts_beside_the_existing_ones():
    metrics = ImportMetrics(
        games_processed=1,
        games_accepted=2,
        duplicates_skipped=3,
        duplicates_found=4,
        games_quarantined=5,
        failed_games_count=6,
        duplicate_key_violations=7,
        skipped_empty_provider_ids=8,
        skipped_empty_game_date=9,
        skipped_empty_scores=10,
        duplicate_links_backfilled=11,
        scores_corrected=12,
        scores_correct_failed=13,
        scores_correct_held=14,
    )

    assert importer.import_result_summary(metrics) == {
        "games_processed": 1,
        "games_accepted": 2,
        "duplicates_skipped": 3,
        "duplicates_found": 4,
        "games_quarantined": 5,
        "failed_games_count": 6,
        "duplicate_key_violations": 7,
        "skipped_empty_provider_ids": 8,
        "skipped_empty_game_date": 9,
        "skipped_empty_scores": 10,
        "duplicate_links_backfilled": 11,
        "scores_corrected": 12,
        "scores_correct_failed": 13,
        "scores_correct_held": 14,
    }


class _Pipeline:
    """Reports a distinct correction count per counter in every batch, whatever the batch holds."""

    def __init__(self, *_args, **_kwargs):
        pass

    async def import_games(self, batch):
        return ImportMetrics(
            games_processed=len(batch), scores_corrected=1, scores_correct_failed=2, scores_correct_held=3
        )

    def print_modular11_summary(self, _metrics):
        pass


# More batches than twice the concurrency, so both the in-flight and the final summing blocks run.
def test_streamed_batches_sum_the_correction_counts(tmp_path, monkeypatch, capsys):
    path = tmp_path / "games.jsonl"
    path.write_text("\n".join(json.dumps({"game_uid": f"g{i}"}) for i in range(12)), encoding="utf-8")
    monkeypatch.setenv("SUPABASE_URL", "http://localhost")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "key")
    monkeypatch.setattr(importer, "create_client", lambda *_a: object())
    monkeypatch.setattr(importer, "EnhancedETLPipeline", _Pipeline)
    argv = ["import_games_enhanced.py", str(path), "mlsnext_kitman", "--batch-size", "1", "--concurrency", "4"]
    monkeypatch.setattr(sys, "argv", argv)

    asyncio.run(importer.main())

    [line] = [x for x in capsys.readouterr().out.splitlines() if x.startswith("IMPORT_RESULT:")]
    result = json.loads(line.removeprefix("IMPORT_RESULT:"))
    assert (result["scores_corrected"], result["scores_correct_failed"], result["scores_correct_held"]) == (12, 24, 36)
    # the workflow summary greps this exact spacing
    assert '"scores_corrected": 12' in line
