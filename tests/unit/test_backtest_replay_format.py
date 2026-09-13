from dataclasses import replace

from src.tournaments.backtest_replay_format import (
    assess_replay_format,
    ordered_captured_fixtures,
)
from src.tournaments.gotsport_event_structure import Fixture, Pool, PoolMember, ScrapedDivision


def _division(*, fixture_kind: str = "pool", fixture_count: int = 1) -> ScrapedDivision:
    fixtures = tuple(
        Fixture(str(index + 1), "", fixture_kind, "reg-a", "reg-b", None, None, "", "")
        for index in range(fixture_count)
    )
    return ScrapedDivision(
        group_id="group-1",
        division_label="Gold",
        pools=(
            Pool(
                "pool-a",
                "Pool A",
                (PoolMember("reg-a", "Alpha", 1), PoolMember("reg-b", "Bravo", 2)),
            ),
        ),
        fixtures=fixtures,
        pools_readable=True,
        fixtures_readable=True,
        warnings=(),
        age_group="u14",
        gender="Male",
    )


def test_unique_captured_shape_is_replay_ready_without_manual_review():
    assessment = assess_replay_format(_division())

    assert assessment.ready is True
    assert assessment.format_code == "CAPTURED_GRAPH"


def test_cross_pool_schedule_is_replay_ready():
    assessment = assess_replay_format(_division(fixture_kind="cross_pool"))

    assert assessment.ready is True
    assert assessment.format_code == "CAPTURED_GRAPH"


def test_empty_captured_schedule_is_not_replay_ready():
    division = _division(fixture_count=0)
    assessment = assess_replay_format(division)

    assert assessment.ready is False
    assert "No fixture rows" in assessment.reason


def test_unreadable_source_evidence_is_never_automatically_ready():
    assessment = assess_replay_format(replace(_division(), fixtures_readable=False))

    assert assessment.ready is False
    assert "could not be read completely" in assessment.reason


def test_mixed_numbered_and_unnumbered_fixtures_preserve_page_order():
    pool_fixture = Fixture(
        "", "", "pool", "reg-a", "reg-b", None, None, "9:00 AM", "Field 1"
    )
    playoff_fixture = Fixture(
        "20", "Final", "bracket", "reg-a", "reg-b", None, None, "1:00 PM", "Field 1"
    )

    assert ordered_captured_fixtures((pool_fixture, playoff_fixture)) == (
        pool_fixture,
        playoff_fixture,
    )


def test_fully_numbered_fixtures_use_published_match_number_order():
    later = Fixture(
        "20", "Final", "bracket", "reg-a", "reg-b", None, None, "1:00 PM", "Field 1"
    )
    earlier = Fixture(
        "10", "", "pool", "reg-a", "reg-b", None, None, "9:00 AM", "Field 1"
    )

    assert ordered_captured_fixtures((later, earlier)) == (earlier, later)
