from dataclasses import dataclass
from datetime import date

from scripts.scrape_upcoming_gotsport_events import event_overlaps_window, filter_games_to_window


@dataclass
class DummyGame:
    game_date: str


def test_event_overlaps_window_with_actual_dates():
    assert event_overlaps_window(
        event_start_date=date(2026, 4, 12),
        event_end_date=date(2026, 4, 13),
        search_date=date(2026, 4, 10),
        window_start=date(2026, 4, 10),
        window_end=date(2026, 4, 17),
    )
    assert not event_overlaps_window(
        event_start_date=date(2026, 4, 20),
        event_end_date=date(2026, 4, 21),
        search_date=date(2026, 4, 10),
        window_start=date(2026, 4, 10),
        window_end=date(2026, 4, 17),
    )


def test_filter_games_to_window_keeps_only_target_dates():
    games = [
        DummyGame("2026-04-09"),
        DummyGame("2026-04-10"),
        DummyGame("2026-04-14"),
        DummyGame("2026-04-18"),
        DummyGame(""),
    ]

    filtered = filter_games_to_window(games, date(2026, 4, 10), date(2026, 4, 17))

    assert [game.game_date for game in filtered] == ["2026-04-10", "2026-04-14"]
