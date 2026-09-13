from dataclasses import replace

from src.tournaments.backtest_replay_format import assess_replay_format
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
                (PoolMember("reg-a", "Alpha", None), PoolMember("reg-b", "Bravo", None)),
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
    assert assessment.format_code == "ROUND_ROBIN"


def test_cross_pool_schedule_is_an_engineering_gap():
    assessment = assess_replay_format(_division(fixture_kind="cross_pool"))

    assert assessment.ready is False
    assert "dedicated replay template" in assessment.reason


def test_incomplete_round_robin_is_not_cleared_by_game_count_guessing():
    division = _division(fixture_count=0)
    assessment = assess_replay_format(division)

    assert assessment.ready is False
    assert "full round robin" in assessment.reason


def test_unreadable_source_evidence_is_never_automatically_ready():
    assessment = assess_replay_format(replace(_division(), fixtures_readable=False))

    assert assessment.ready is False
    assert "could not be read completely" in assessment.reason
