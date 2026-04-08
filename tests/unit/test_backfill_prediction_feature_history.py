from __future__ import annotations

from datetime import date

import pytest

from scripts.backfill_prediction_feature_history import (
    generate_snapshot_dates,
    parse_weekday,
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
