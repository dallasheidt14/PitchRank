"""Tests for event-structure persistence."""

from __future__ import annotations

import json

import pytest

from src.tournaments.gotsport_event_structure import (
    Fixture,
    Pool,
    PoolMember,
    ScrapedDivision,
)
from src.tournaments.storage.event_structure import (
    EventStructure,
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


def test_write_then_read_round_trips_every_field(tmp_path):
    write_event_structure("gotsport__51783__2026", _structure(), base_dir=tmp_path)

    assert read_event_structure("gotsport__51783__2026", base_dir=tmp_path) == _structure()


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
