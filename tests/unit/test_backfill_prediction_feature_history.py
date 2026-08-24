from __future__ import annotations

from datetime import date

import pytest

from scripts.backfill_prediction_feature_history import (
    generate_snapshot_dates,
    parse_weekday,
    slice_snapshot_dates,
)


def test_parse_weekday_accepts_names_and_numbers():
    assert parse_weekday("Mon") == 0
    assert parse_weekday("thursday") == 3
    assert parse_weekday("6") == 6


def test_parse_weekday_rejects_invalid_values():
    with pytest.raises(Exception):
        parse_weekday("8")

    with pytest.raises(Exception):
        parse_weekday("noday")


def test_generate_snapshot_dates_weekly_aligns_to_requested_weekday():
    dates = generate_snapshot_dates(
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 31),
        cadence="weekly",
        weekday=0,
    )

    assert dates == [
        date(2026, 1, 5),
        date(2026, 1, 12),
        date(2026, 1, 19),
        date(2026, 1, 26),
    ]


def test_generate_snapshot_dates_daily_includes_range_endpoints():
    dates = generate_snapshot_dates(
        start_date=date(2026, 4, 6),
        end_date=date(2026, 4, 8),
        cadence="daily",
        weekday=0,
    )

    assert dates == [
        date(2026, 4, 6),
        date(2026, 4, 7),
        date(2026, 4, 8),
    ]


def test_generate_snapshot_dates_rejects_inverted_ranges():
    with pytest.raises(ValueError):
        generate_snapshot_dates(
            start_date=date(2026, 4, 8),
            end_date=date(2026, 4, 6),
            cadence="weekly",
            weekday=0,
        )


def test_slice_snapshot_dates_applies_skip_and_max():
    candidate_dates = [
        date(2026, 1, 5),
        date(2026, 1, 12),
        date(2026, 1, 19),
        date(2026, 1, 26),
    ]

    sliced = slice_snapshot_dates(candidate_dates, skip_snapshots=1, max_snapshots=2)

    assert sliced == [
        date(2026, 1, 12),
        date(2026, 1, 19),
    ]


def test_slice_snapshot_dates_rejects_negative_skip():
    with pytest.raises(ValueError):
        slice_snapshot_dates([date(2026, 1, 5)], skip_snapshots=-1)


@pytest.mark.asyncio
async def test_replay_disables_every_compute_writer_and_dry_run_skips_the_save(monkeypatch):
    """A replayed historical board must never write through compute_all_cohorts.

    Every persist_* flag defaults to True, so a kwarg left off here upserts rows
    derived from a historical board onto the live tables.
    """
    import pandas as pd

    import scripts.backfill_prediction_feature_history as backfill

    captured = {"feature_saves": 0}

    async def fake_compute_all_cohorts(**kwargs):
        captured.update(kwargs)
        return {"teams": pd.DataFrame([{"team_id": "team-1"}])}

    async def fake_save(**_kwargs):
        captured["feature_saves"] += 1
        return 1

    monkeypatch.setattr(backfill, "compute_all_cohorts", fake_compute_all_cohorts)
    monkeypatch.setattr(backfill, "save_prediction_feature_snapshot", fake_save)

    for dry_run, expected_saves in ((True, 0), (False, 1)):
        captured["feature_saves"] = 0
        await backfill.replay_prediction_snapshot(
            supabase_client=object(),
            merge_resolver=object(),
            snapshot_date=date(2026, 8, 17),
            lookback_days=365,
            provider_filter=None,
            use_glicko=True,
            ml_enabled=False,
            force_rebuild=False,
            dry_run=dry_run,
        )
        assert captured["persist_game_residuals"] is False
        assert captured["persist_game_explainability"] is False
        assert captured["save_snapshot"] is False
        assert captured["calculate_rank_changes_enabled"] is False
        assert captured["feature_saves"] == expected_saves
