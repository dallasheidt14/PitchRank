from dataclasses import replace
from pathlib import Path

from src.tournaments.backtest_replay_format import (
    assess_replay_format,
    build_captured_fixture_slots,
    ordered_captured_fixtures,
)
from src.tournaments.gotsport_event_structure import (
    Fixture,
    Pool,
    PoolMember,
    ScrapedDivision,
    parse_division_structure,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "gotsport"


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


def test_cross_pool_wildcards_use_division_wide_standings_ranks():
    division = parse_division_structure(
        group_id="436891",
        division_label="U11 Boys",
        html=(FIXTURES / "event_49407__group_436891.html").read_text(encoding="utf-8"),
    )

    slots = build_captured_fixture_slots(division)
    final = next(slot for slot in slots if slot["match_number"] == "23")

    assert final["stage"] == "Final- Wildcard 1 v Wildcard 2"
    assert final["home"] == {
        "kind": "division_rank",
        "rank": 0,
        "evidence": "published_wildcard_slot_label",
    }
    assert final["away"] == {
        "kind": "division_rank",
        "rank": 1,
        "evidence": "published_wildcard_slot_label",
    }
    assert assess_replay_format(division).ready is True


def test_cross_pool_qualification_without_published_wildcard_slots_is_blocked():
    division = _division(fixture_kind="bracket")
    division = replace(
        division,
        pools=(
            replace(
                division.pools[0],
                label="Top 2 Teams In Points Advance Regardless Of Group",
            ),
        ),
    )

    assessment = assess_replay_format(division)

    assert assessment.ready is False
    assert "needs its published wildcard slot labels" in assessment.reason


def test_wildcard_slots_without_division_wide_eligibility_are_blocked():
    division = _division(fixture_kind="bracket")
    division = replace(
        division,
        fixtures=(replace(division.fixtures[0], bracket_label="Final- Wildcard 1 v Wildcard 2"),),
    )

    assessment = assess_replay_format(division)

    assert assessment.ready is False
    assert "do not establish that every team is ranked together" in assessment.reason


def test_bracket_slot_with_missing_published_match_reference_is_blocked():
    division = _division(fixture_kind="bracket")
    division = replace(
        division,
        fixtures=(replace(division.fixtures[0], home_label="Winner Match #5"),),
    )

    assessment = assess_replay_format(division)

    assert assessment.ready is False
    assert "references a missing or later published match" in assessment.reason


def test_bracket_slot_cannot_reference_a_later_published_match():
    division = _division(fixture_kind="bracket", fixture_count=2)
    division = replace(
        division,
        fixtures=(replace(division.fixtures[0], home_label="Winner Match #2"), division.fixtures[1]),
    )

    assessment = assess_replay_format(division)

    assert assessment.ready is False
    assert "references a missing or later published match" in assessment.reason
