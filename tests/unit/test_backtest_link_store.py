"""Tests for the backtest team-link store."""

from __future__ import annotations

import json
import os

import pytest

from src.tournaments.backtest_link_store import (
    EventLinks,
    TeamLink,
    build_links,
    event_links_path,
    generations_agree,
    load_links,
    plan_sync,
    restore_overrides,
    rows_fingerprint,
    save_links,
)
from src.tournaments.roster_paste import RosterRow
from src.tournaments.storage.schema_version import SchemaVersionError
from src.tournaments.roster_resolver import ResolvedTeam

EVENT_KEY = "gotsport__51783__unknown"


def _row(source_index: int, name: str) -> RosterRow:
    return RosterRow(
        source_index=source_index,
        club_raw="",
        team_name_raw=name,
        state="",
        section_age_group="u13",
        section_gender="Male",
        team_name_stripped=name,
        has_star_marker=False,
        has_c_marker=False,
    )


def _links() -> EventLinks:
    return EventLinks(
        event_id="51783",
        links=(
            TeamLink(
                registration_id="4411807",
                event_team_name="Barcelona SC 13B Aztecas",
                team_id_master="aaaa-1111",
                matched_by="gotsport_id",
                linked_at="2026-09-11T00:00:00+00:00",
            ),
            TeamLink(
                registration_id="4383677",
                event_team_name="San Antonio City SC 12/13 WHITE",
                team_id_master="bbbb-2222",
                matched_by="operator",
                linked_at="2026-09-11T00:01:00+00:00",
            ),
        ),
    )


def test_save_then_load_round_trips_every_field(tmp_path):
    save_links(EVENT_KEY, _links(), base_dir=tmp_path)

    back = load_links(EVENT_KEY, base_dir=tmp_path)

    assert back.event_id == "51783"
    assert back.links == _links().links
    assert back.saved_at != ""


def test_links_land_beside_the_other_intake_artifacts(tmp_path):
    save_links(EVENT_KEY, _links(), base_dir=tmp_path)
    path = event_links_path(EVENT_KEY, base_dir=tmp_path)

    assert path == tmp_path / EVENT_KEY / "intake" / "event_links.json"
    assert path.exists()


def test_an_event_with_no_saved_links_reads_as_empty_rather_than_raising(tmp_path):
    back = load_links(EVENT_KEY, base_dir=tmp_path)

    assert back.links == ()
    assert back.event_id == ""


def test_an_unreadable_file_reads_as_empty_rather_than_raising(tmp_path):
    path = event_links_path(EVENT_KEY, base_dir=tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json at all", encoding="utf-8")

    assert load_links(EVENT_KEY, base_dir=tmp_path).links == ()


def test_a_payload_missing_a_required_field_reads_as_empty(tmp_path):
    path = event_links_path(EVENT_KEY, base_dir=tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"event_id": "51783", "links": [{"registration_id": "1"}]}), encoding="utf-8")

    assert load_links(EVENT_KEY, base_dir=tmp_path).links == ()


def test_build_links_records_how_each_team_was_settled():
    rows = (_row(0, "Aztecas"), _row(1, "City White"), _row(2, "Nobody"))
    resolved = (
        ResolvedTeam(source_index=0, status="gotsport_id", team_id_master="aaaa-1111"),
        ResolvedTeam(source_index=1, status="exact_name", team_id_master="bbbb-2222"),
        ResolvedTeam(source_index=2, status="unresolved"),
    )
    registrations = {0: "4411807", 1: "4383677", 2: "4428970"}

    built = build_links("51783", rows, resolved, {}, registrations)

    assert [(link.registration_id, link.matched_by) for link in built.links] == [
        ("4411807", "gotsport_id"),
        ("4383677", "exact_name"),
    ]
    assert built.links[0].event_team_name == "Aztecas"


def test_build_links_prefers_the_operators_fix_over_the_resolver():
    rows = (_row(0, "Aztecas"),)
    resolved = (ResolvedTeam(source_index=0, status="exact_name", team_id_master="wrong-one"),)

    built = build_links(
        "51783", rows, resolved, {0: {"team_id_master": "operator-pick"}}, {0: "4411807"}
    )

    assert built.links[0].team_id_master == "operator-pick"
    assert built.links[0].matched_by == "operator"


def test_an_override_carrying_no_team_falls_back_to_the_resolver():
    rows = (_row(0, "Aztecas"),)
    resolved = (ResolvedTeam(source_index=0, status="gotsport_id", team_id_master="aaaa-1111"),)

    built = build_links("51783", rows, resolved, {0: {"team_name": "half-entered"}}, {0: "4411807"})

    assert built.links[0].team_id_master == "aaaa-1111"
    assert built.links[0].matched_by == "gotsport_id"


def test_build_links_skips_a_team_with_no_registration_id():
    rows = (_row(0, "Aztecas"),)
    resolved = (ResolvedTeam(source_index=0, status="gotsport_id", team_id_master="aaaa-1111"),)

    assert build_links("51783", rows, resolved, {}, {}).links == ()


def test_a_manual_fix_reattaches_after_a_rewalk_moves_the_team():
    """A division that fails to load shifts every later position, so the
    registration id is the only thing that can carry a fix across walks."""
    saved = _links()
    rows = (_row(0, "someone else"), _row(1, "San Antonio City SC 12/13 WHITE"))
    registrations = {0: "9999999", 1: "4383677"}

    assert restore_overrides(rows, saved, registrations) == {
        1: {"team_id_master": "bbbb-2222", "team_name": "San Antonio City SC 12/13 WHITE"}
    }


def test_only_the_operators_fixes_are_restored():
    """An automatic match is recomputed by the resolver on every walk; restoring
    it as an override would freeze a stale decision the resolver has moved past."""
    rows = (_row(0, "Barcelona SC 13B Aztecas"),)

    assert restore_overrides(rows, _links(), {0: "4411807"}) == {}


def test_a_probe_does_not_erase_links_saved_for_the_rest_of_the_event():
    """The UI requires a two-division probe before the full walk unlocks, so a
    roster holding a handful of teams is the normal path, not an edge case."""
    saved = _links()
    rows = (_row(0, "Barcelona SC 13B Aztecas"),)
    resolved = (ResolvedTeam(source_index=0, status="gotsport_id", team_id_master="aaaa-1111"),)

    _, merged = plan_sync(saved, rows, resolved, {}, {0: "4411807"}, "51783")

    assert {link.registration_id for link in merged.links} == {"4411807", "4383677"}
    assert next(link for link in merged.links if link.registration_id == "4383677").matched_by == "operator"


def test_this_walk_wins_for_a_team_it_actually_saw():
    saved = _links()
    rows = (_row(0, "Barcelona SC 13B Aztecas"),)
    resolved = (ResolvedTeam(source_index=0, status="exact_name", team_id_master="moved-on"),)

    _, merged = plan_sync(saved, rows, resolved, {}, {0: "4411807"}, "51783")

    link = next(item for item in merged.links if item.registration_id == "4411807")
    assert (link.team_id_master, link.matched_by) == ("moved-on", "exact_name")


def test_a_fresh_walk_of_the_same_event_gets_its_saved_fixes_back():
    """`_park_event_roster` clears the overrides on every walk, so the second
    walk of an event starts empty and must be refilled from disk."""
    rows = (_row(0, "San Antonio City SC 12/13 WHITE"),)
    resolved = (ResolvedTeam(source_index=0, status="unresolved"),)

    to_add, _ = plan_sync(_links(), rows, resolved, {}, {0: "4383677"}, "51783")

    assert to_add == {0: {"team_id_master": "bbbb-2222", "team_name": "San Antonio City SC 12/13 WHITE"}}


def test_an_override_the_operator_is_already_changing_is_left_alone():
    rows = (_row(0, "San Antonio City SC 12/13 WHITE"),)
    resolved = (ResolvedTeam(source_index=0, status="unresolved"),)
    in_progress = {0: {"team_id_master": "just-picked", "team_name": "whatever"}}

    to_add, merged = plan_sync(_links(), rows, resolved, in_progress, {0: "4383677"}, "51783")

    assert to_add == {}
    assert next(link for link in merged.links if link.registration_id == "4383677").team_id_master == "just-picked"


def _parked(rows, by_index, event_id="51783"):
    return {"event_id": event_id, "fingerprint": rows_fingerprint(rows), "by_index": by_index}


def test_a_registration_map_from_the_same_walk_is_accepted():
    rows = (_row(0, "Aztecas"), _row(1, "City White"))

    assert generations_agree(rows, _parked(rows, {0: "4411807", 1: "4383677"}), "51783")


def test_a_map_from_a_walk_that_found_a_different_set_of_teams_is_refused():
    """`source_index` is assigned as `len(teams)`, so every walk's indexes are
    0..n-1 and two walks of the same size share an index set no matter how
    different their teams are. Only the rows themselves separate them."""
    walked = (_row(0, "Aztecas"), _row(1, "City White"))
    other = (_row(0, "Someone Else"), _row(1, "A Third Club"))

    assert not generations_agree(other, _parked(walked, {0: "4411807", 1: "4383677"}), "51783")


def test_a_map_from_a_walk_that_reordered_the_same_teams_is_refused():
    walked = (_row(0, "Aztecas"), _row(1, "City White"))
    reordered = (_row(0, "City White"), _row(1, "Aztecas"))

    assert not generations_agree(reordered, _parked(walked, {0: "4411807", 1: "4383677"}), "51783")


def test_a_map_of_a_different_size_is_refused():
    walked = (_row(0, "Aztecas"), _row(1, "City White"))

    assert not generations_agree((_row(0, "Aztecas"),), _parked(walked, {0: "4411807", 1: "4383677"}), "51783")


def test_a_malformed_parked_map_is_refused_rather_than_trusted():
    rows = (_row(0, "Aztecas"),)

    assert not generations_agree(rows, {}, "51783")
    assert not generations_agree(rows, {"by_index": {0: "4411807"}}, "51783")
    assert not generations_agree(rows, {"fingerprint": "nope", "by_index": {0: "4411807"}}, "51783")


def test_a_walk_of_another_event_with_the_same_teams_is_refused():
    """Annual editions can field the same clubs in the same order, so the rows
    alone cannot separate two events — only the event the map was walked for."""
    rows = (_row(0, "Aztecas"), _row(1, "City White"))
    other_event = _parked(rows, {0: "4411807", 1: "4383677"}, event_id="60001")

    assert not generations_agree(rows, other_event, "51783")


def test_a_restored_link_is_resolved_through_the_merge_map():
    """A team merged between sessions leaves the saved id deprecated, and an
    override both wins over the resolver and hides the row from the outstanding
    list — so an unresolved id would be re-saved with nothing to notice it."""
    rows = (_row(0, "San Antonio City SC 12/13 WHITE"),)

    restored = restore_overrides(
        rows, _links(), {0: "4383677"},
        resolve_team_id=lambda team_id: "canonical-9999" if team_id == "bbbb-2222" else team_id,
    )

    assert restored[0]["team_id_master"] == "canonical-9999"


def test_a_resolver_that_answers_nothing_leaves_the_saved_id_alone():
    rows = (_row(0, "San Antonio City SC 12/13 WHITE"),)

    restored = restore_overrides(rows, _links(), {0: "4383677"}, resolve_team_id=lambda _t: None)

    assert restored[0]["team_id_master"] == "bbbb-2222"


def test_a_payload_that_is_not_an_object_reads_as_empty(tmp_path):
    """A hand-repaired `[]` is valid JSON, and the version check calls `.get` on
    it. That must follow this reader's malformed-file path, not abort the screen
    over an optional artifact."""
    path = event_links_path(EVENT_KEY, base_dir=tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    for payload in ("[]", '"just a string"', "42", "null"):
        path.write_text(payload, encoding="utf-8")
        assert load_links(EVENT_KEY, base_dir=tmp_path).links == (), payload


def test_the_payload_is_stamped_with_a_schema_version(tmp_path):
    save_links(EVENT_KEY, _links(), base_dir=tmp_path)
    payload = json.loads(event_links_path(EVENT_KEY, base_dir=tmp_path).read_text(encoding="utf-8"))

    assert payload["schema_version"] == 1


def test_a_file_from_a_future_version_is_refused_rather_than_read_as_empty(tmp_path):
    """Reading it as empty would be worse than failing: the next render would
    persist that emptiness over decisions this build cannot understand."""
    save_links(EVENT_KEY, _links(), base_dir=tmp_path)
    path = event_links_path(EVENT_KEY, base_dir=tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["schema_version"] = 99
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(SchemaVersionError):
        load_links(EVENT_KEY, base_dir=tmp_path)


def test_a_failed_replacement_leaves_the_previous_links_intact(tmp_path, monkeypatch):
    """The file is the only copy of work that cost an operator real lookups."""
    save_links(EVENT_KEY, _links(), base_dir=tmp_path)

    def explode(*args, **kwargs):
        raise OSError("disk went away mid-replace")

    monkeypatch.setattr(os, "replace", explode)
    with pytest.raises(OSError):
        save_links(EVENT_KEY, EventLinks(event_id="51783", links=()), base_dir=tmp_path)

    monkeypatch.undo()
    assert load_links(EVENT_KEY, base_dir=tmp_path).links == _links().links


def test_a_saved_link_for_a_team_this_walk_did_not_find_is_ignored():
    rows = (_row(0, "Barcelona SC 13B Aztecas"),)

    assert restore_overrides(rows, _links(), {0: "4411807", 1: "4383677"}) == {}
