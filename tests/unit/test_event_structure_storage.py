"""Tests for event-structure persistence."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from src.tournaments.gotsport_event_structure import (
    Fixture,
    Pool,
    PoolMember,
    PublishedLink,
    ScrapedDivision,
)
from src.tournaments.storage.event_structure import (
    EventStructure,
    StructureOverwriteRefused,
    division_from_dict,
    event_structure_path,
    read_event_structure,
    write_event_structure,
)
from src.tournaments.storage.schema_version import SchemaVersionError


def _structure() -> EventStructure:
    return EventStructure(
        event_id="51783",
        walked_at="2026-09-10T00:00:00+00:00",
        is_complete=True,
        divisions=(
            ScrapedDivision(
                group_id="501350",
                division_label="U13 Boys Red",
                pools=(
                    Pool(
                        pool_id="501350",
                        label="Bracket A",
                        members=(
                            PoolMember(registration_id="1", team_name="One", standings_position=1),
                        ),
                    ),
                ),
                fixtures=(
                    Fixture(
                        match_number="56",
                        bracket_label="Final",
                        kind="bracket",
                        home_registration_id="1",
                        away_registration_id="2",
                        home_score=3,
                        away_score=4,
                        kickoff="Feb 16, 2026 12:45PM MST MST",
                        location="West Field #16",
                    ),
                ),
                pools_readable=True,
                fixtures_readable=True,
                warnings=(),
            ),
        ),
    )


def _structure_with_unplayed_fixture() -> EventStructure:
    """A structure with an unplayed fixture (all nullable fields are None)."""
    return EventStructure(
        event_id="51783",
        walked_at="2026-09-10T00:00:00+00:00",
        is_complete=False,
        divisions=(
            ScrapedDivision(
                group_id="501350",
                division_label="U13 Boys Red",
                pools=(
                    Pool(
                        pool_id="501350",
                        label="Bracket A",
                        members=(
                            PoolMember(registration_id="1", team_name="One", standings_position=1),
                        ),
                    ),
                ),
                fixtures=(
                    Fixture(
                        match_number="57",
                        bracket_label="",
                        kind="unknown",
                        home_registration_id=None,
                        away_registration_id=None,
                        home_score=None,
                        away_score=None,
                        kickoff="",
                        location="",
                    ),
                ),
                pools_readable=True,
                fixtures_readable=True,
                warnings=(),
            ),
        ),
    )


def test_write_then_read_round_trips_every_field(tmp_path):
    write_event_structure("gotsport__51783__2026", _structure(), base_dir=tmp_path)

    assert read_event_structure("gotsport__51783__2026", base_dir=tmp_path) == _structure()


def test_unplayed_fixtures_round_trip_with_none_values(tmp_path):
    """Verify that unplayed fixtures with all nullable fields as None round-trip correctly."""
    structure = _structure_with_unplayed_fixture()
    write_event_structure("gotsport__51783__2026", structure, base_dir=tmp_path)

    assert read_event_structure("gotsport__51783__2026", base_dir=tmp_path) == structure


def test_the_file_lands_beside_the_other_intake_artifacts(tmp_path):
    write_event_structure("gotsport__51783__2026", _structure(), base_dir=tmp_path)
    path = event_structure_path("gotsport__51783__2026", base_dir=tmp_path)

    assert path == tmp_path / "gotsport__51783__2026" / "intake" / "event_structure.json"
    assert path.exists()


def test_the_payload_is_stamped_with_a_schema_version(tmp_path):
    write_event_structure("gotsport__51783__2026", _structure(), base_dir=tmp_path)
    payload = json.loads(
        event_structure_path("gotsport__51783__2026", base_dir=tmp_path).read_text(encoding="utf-8")
    )

    assert payload["schema_version"] == 1


def test_a_future_schema_is_refused_rather_than_half_read(tmp_path):
    write_event_structure("gotsport__51783__2026", _structure(), base_dir=tmp_path)
    path = event_structure_path("gotsport__51783__2026", base_dir=tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["schema_version"] = 99
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(SchemaVersionError):
        read_event_structure("gotsport__51783__2026", base_dir=tmp_path)


def test_reading_an_absent_structure_raises_file_not_found(tmp_path):
    with pytest.raises(FileNotFoundError):
        read_event_structure("gotsport__51783__2026", base_dir=tmp_path)


def test_a_partial_write_refuses_to_replace_a_complete_structure(tmp_path):
    """The writer's own guard, not one caller's good manners: a probe reading
    two divisions costs pennies, and must never silently replace a full walk
    that cost dollars — no matter who calls write_event_structure next."""
    write_event_structure("gotsport__51783__2026", _structure(), base_dir=tmp_path)

    partial = replace(_structure(), is_complete=False, walked_at="2026-09-11T00:00:00+00:00")
    with pytest.raises(StructureOverwriteRefused):
        write_event_structure("gotsport__51783__2026", partial, base_dir=tmp_path)

    assert read_event_structure("gotsport__51783__2026", base_dir=tmp_path) == _structure()


def test_a_complete_walk_may_replace_a_complete_one(tmp_path):
    """The other half of the guard, which no other test exercises.

    Only `is_complete=False` landing on a complete file is refused. Without
    this, dropping the `not structure.is_complete and` conjunct leaves the
    suite green while the writer permanently refuses every re-walk — the
    operator who paid to walk an event again, because its structure came back
    wrong, could never save the corrected one.
    """
    write_event_structure("gotsport__51783__2026", _structure(), base_dir=tmp_path)

    rewalked = replace(_structure(), walked_at="2026-09-11T00:00:00+00:00")
    write_event_structure("gotsport__51783__2026", rewalked, base_dir=tmp_path)

    on_disk = read_event_structure("gotsport__51783__2026", base_dir=tmp_path)
    assert on_disk.walked_at == "2026-09-11T00:00:00+00:00"
    assert on_disk == rewalked


def test_enriched_fixture_and_source_evidence_round_trip(tmp_path):
    original = _structure()
    fixture = replace(
        original.divisions[0].fixtures[0],
        home_score=3, away_score=3,
        home_label="Home FC", away_label="Away FC",
        result_text="3 - 3 PKS: 4 - 3",
        home_shootout_score=4, away_shootout_score=3,
        winner_side="home", winner_registration_id="1", result_status="played",
        date_label="February 16, 2026",
        source_url="https://system.gotsport.com/org_event/events/51783/schedules?match=123",
    )
    division = replace(
        original.divisions[0], fixtures=(fixture,),
        source_url="https://system.gotsport.com/org_event/events/51783/schedules?group=501350",
        rules_links=(PublishedLink("Tournament Rules", "https://organizer.example/rules.pdf"),),
        published_age_group="u13", published_cohort_label="Male U13 - U13 Boys Gold",
    )
    enriched = replace(original, divisions=(division,))
    write_event_structure("gotsport__51783__2026", enriched, base_dir=tmp_path)
    saved = read_event_structure("gotsport__51783__2026", base_dir=tmp_path)

    assert saved == enriched
    assert saved.divisions[0].fixtures[0].result_text == "3 - 3 PKS: 4 - 3"
    assert saved.divisions[0].fixtures[0].winner_registration_id == "1"
    assert saved.divisions[0].rules_links[0].url == "https://organizer.example/rules.pdf"
    assert saved.divisions[0].published_age_group == "u13"


def test_legacy_structure_is_readable_without_inventing_missing_source_evidence():
    legacy = {
        "group_id": "1", "division_label": "Gold", "pools": [],
        "pools_readable": True, "fixtures_readable": True, "warnings": [],
        "fixtures": [{
            "match_number": "9", "bracket_label": "Final", "kind": "bracket",
            "home_registration_id": "1", "away_registration_id": "2",
            "home_score": None, "away_score": None, "kickoff": "9:00 AM", "location": "Field 1",
        }],
    }
    division = division_from_dict(legacy)

    assert division.source_url == ""
    assert division.rules_links == ()
    assert division.published_age_group == ""
    fixture, = division.fixtures
    assert fixture.result_text == ""
    assert fixture.result_status == "not_captured"
    assert fixture.home_shootout_score is None
    assert fixture.winner_side == ""
    assert fixture.winner_registration_id is None
    assert fixture.home_label == ""
    assert fixture.date_label == ""
