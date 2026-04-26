"""Unit tests for ``src.tournaments.triage`` classifier + builder helpers.

Pins ``_classify_team_state``'s priority ladder, the placeholder/play-up
predicates, the ``_OVERRIDE_TYPES`` / ``_STRENGTH_MODES`` constants, and
``build_override_record``'s validation surface.
"""

from __future__ import annotations

import pytest

from src.tournaments.triage import (
    _OVERRIDE_TYPES,
    _STRENGTH_MODES,
    ProjectedTeamState,
    _classify_team_state,
    _is_placeholder_team,
    _is_play_up,
    build_override_record,
)

# -------- _OVERRIDE_TYPES + _STRENGTH_MODES constants --------------------


def test_override_types_constant_is_pinned():
    assert _OVERRIDE_TYPES == (
        "accept_match",
        "fix_match",
        "mark_external",
        "edit_external",
        "manual_add",
        "recompute_medians",
    )


def test_strength_modes_constant_is_pinned():
    assert _STRENGTH_MODES == ("median", "manual", "exclude")


# -------- _is_placeholder_team -------------------------------------------


def test_is_placeholder_team_canonical_match():
    assert _is_placeholder_team("unknown_12345", "12345") is True


def test_is_placeholder_team_case_insensitive():
    assert _is_placeholder_team("UNKNOWN_12345", "12345") is True
    assert _is_placeholder_team("Unknown_12345", "12345") is True


def test_is_placeholder_team_mismatched_id_is_false():
    assert _is_placeholder_team("unknown_99999", "12345") is False


def test_is_placeholder_team_empty_name_is_false():
    assert _is_placeholder_team("", "12345") is False
    assert _is_placeholder_team(None, "12345") is False


def test_is_placeholder_team_empty_pid_is_false():
    assert _is_placeholder_team("unknown_12345", "") is False


def test_is_placeholder_team_real_team_name_is_false():
    assert _is_placeholder_team("Phoenix Rising 2014", "12345") is False


# -------- _is_play_up ----------------------------------------------------


def test_is_play_up_younger_team_in_older_cohort():
    assert _is_play_up("u12", "u14") is True


def test_is_play_up_uppercase_inputs():
    assert _is_play_up("U12", "U14") is True


def test_is_play_up_same_age_is_false():
    assert _is_play_up("u14", "u14") is False


def test_is_play_up_older_team_in_younger_cohort_is_false():
    assert _is_play_up("u15", "u14") is False


def test_is_play_up_missing_resolved_age_is_false():
    assert _is_play_up(None, "u14") is False
    assert _is_play_up("", "u14") is False


def test_is_play_up_unparseable_age_is_false():
    assert _is_play_up("varsity", "u14") is False


# -------- _classify_team_state -------------------------------------------


def _record(scraper_state: str | None, *, pid: str = "12345") -> dict:
    canonical = {"scraper_state": scraper_state} if scraper_state is not None else {}
    return {"provider_team_id": pid, "canonical": canonical}


def test_classify_projected_external_wins():
    record = _record("alias_written")
    projected = ProjectedTeamState(state="external")
    assert _classify_team_state(record, resolved_team=None, projected=projected) == "external"


def test_classify_projected_resolved_with_real_team():
    record = _record("review_queued")
    projected = ProjectedTeamState(state="resolved", team_id_master="abc")
    resolved = {"team_id_master": "abc", "team_name": "Phoenix Rising 2014"}
    assert _classify_team_state(record, resolved_team=resolved, projected=projected) == "resolved"


def test_classify_projected_resolved_to_placeholder():
    record = _record("review_queued", pid="12345")
    projected = ProjectedTeamState(state="resolved", team_id_master="abc")
    resolved = {"team_id_master": "abc", "team_name": "unknown_12345"}
    assert _classify_team_state(record, resolved_team=resolved, projected=projected) == "placeholder"


def test_classify_projected_resolved_with_no_resolved_team_returns_resolved():
    """When the override projection says ``resolved`` but the placeholder
    check has no DB row to inspect, the team should still classify as
    ``resolved`` — the override is the authoritative source."""
    record = _record("review_queued", pid="12345")
    projected = ProjectedTeamState(state="resolved", team_id_master="abc")
    assert _classify_team_state(record, resolved_team=None, projected=projected) == "resolved"


def test_classify_review_queued_is_candidates():
    record = _record("review_queued")
    assert _classify_team_state(record, resolved_team=None, projected=None) == "candidates"


def test_classify_alias_written_is_resolved_with_real_team():
    record = _record("alias_written", pid="12345")
    resolved = {"team_name": "Phoenix Rising 2014"}
    assert _classify_team_state(record, resolved_team=resolved, projected=None) == "resolved"


def test_classify_alias_written_is_placeholder_with_unknown_name():
    record = _record("alias_written", pid="12345")
    resolved = {"team_name": "unknown_12345"}
    assert _classify_team_state(record, resolved_team=resolved, projected=None) == "placeholder"


def test_classify_alias_written_without_resolved_team_is_unknown():
    record = _record("alias_written")
    assert _classify_team_state(record, resolved_team=None, projected=None) == "unknown"


def test_classify_unresolved_is_external():
    record = _record("unresolved")
    assert _classify_team_state(record, resolved_team=None, projected=None) == "external"


def test_classify_missing_canonical_is_unknown():
    record = {"provider_team_id": "12345"}
    assert _classify_team_state(record, resolved_team=None, projected=None) == "unknown"


def test_classify_novel_scraper_state_is_unknown():
    record = _record("not_a_real_state")
    assert _classify_team_state(record, resolved_team=None, projected=None) == "unknown"


# -------- build_override_record ------------------------------------------


def _envelope(**overrides):
    base = dict(
        ts="2026-04-26T12:00:00+00:00",
        actor="dallas@example.com",
        scope="team",
        type="accept_match",
        team_ref="pid-1",
        before={"state": "candidates"},
        after={"state": "resolved", "team_id_master": "abc"},
        reason="best match accepted",
    )
    base.update(overrides)
    return base


def test_build_override_record_envelope_keys():
    record = build_override_record(**_envelope())
    # ``schema_version`` is stamped by ``append_override``, not the builder.
    assert set(record.keys()) == {
        "ts",
        "actor",
        "scope",
        "type",
        "team_ref",
        "before",
        "after",
        "reason",
    }


def test_build_override_record_refuses_empty_actor():
    with pytest.raises(ValueError, match="non-empty reviewer email"):
        build_override_record(**_envelope(actor=""))
    with pytest.raises(ValueError, match="non-empty reviewer email"):
        build_override_record(**_envelope(actor="   "))


def test_build_override_record_refuses_non_email_actor():
    with pytest.raises(ValueError, match="valid reviewer email"):
        build_override_record(**_envelope(actor="dallas"))
    with pytest.raises(ValueError, match="valid reviewer email"):
        build_override_record(**_envelope(actor="dallas@nodot"))


def test_build_override_record_refuses_unknown_type():
    with pytest.raises(ValueError, match="not in"):
        build_override_record(**_envelope(type="invent_a_type"))


def test_build_override_record_refuses_unknown_scope():
    with pytest.raises(ValueError, match="scope must be"):
        build_override_record(**_envelope(scope="event"))


def test_build_override_record_copies_before_and_after():
    """Builder must defensively copy mutable inputs so post-hoc mutation
    by the caller cannot mutate the record after it's been queued for
    append."""
    before = {"state": "candidates"}
    after = {"state": "resolved", "team_id_master": "abc"}
    record = build_override_record(**_envelope(before=before, after=after))
    before["state"] = "external"
    after["state"] = "external"
    assert record["before"] == {"state": "candidates"}
    assert record["after"]["state"] == "resolved"


# -------- per-type ``after`` payload contract (Override Record §3) --------


@pytest.mark.parametrize(
    ("type_", "after_keys"),
    [
        ("accept_match", {"state", "team_id_master", "match_rank"}),
        ("fix_match", {"state", "team_id_master"}),
        ("mark_external", {"state"}),
        (
            "edit_external",
            {"state", "manual_seed_group", "strength_mode", "manual_power_score", "note"},
        ),
        ("manual_add", {"state", "team_id_master", "manual_seed_group"}),
        ("recompute_medians", {"medians_by_division"}),
    ],
)
def test_per_type_after_payload_keys_round_trip(type_, after_keys):
    """Pin the per-type ``after`` payload key set documented in the
    Override Record Contract §3. Builder accepts it; reader sees it back."""
    after = {key: "x" for key in after_keys}
    if "match_rank" in after:
        after["match_rank"] = 1
    if "manual_power_score" in after:
        after["manual_power_score"] = 12.5
    if "medians_by_division" in after:
        after["medians_by_division"] = {"Premier": 14.2}
    scope = "cohort" if type_ == "recompute_medians" else "team"
    team_ref = "u14_Male" if scope == "cohort" else "pid-1"
    record = build_override_record(
        ts="2026-04-26T12:00:00+00:00",
        actor="dallas@example.com",
        scope=scope,
        type=type_,
        team_ref=team_ref,
        before={},
        after=after,
        reason="test",
    )
    assert set(record["after"].keys()) == after_keys
