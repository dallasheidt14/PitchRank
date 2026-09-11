"""Tests for the backtest team-link store."""

from __future__ import annotations

import json

from src.tournaments.backtest_link_store import (
    EventLinks,
    TeamLink,
    build_links,
    event_links_path,
    load_links,
    restore_overrides,
    save_links,
)
from src.tournaments.roster_paste import RosterRow
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


def test_a_saved_link_for_a_team_this_walk_did_not_find_is_ignored():
    rows = (_row(0, "Barcelona SC 13B Aztecas"),)

    assert restore_overrides(rows, _links(), {0: "4411807", 1: "4383677"}) == {}
