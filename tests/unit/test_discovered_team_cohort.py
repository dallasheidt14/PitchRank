"""A discovered team's cohort and gender come from the team, never its opponent.

`build_unknown_profile` and `_build_team_metadata` rank four sources: the team's
own GotSport record, the CSV column the previous stage wrote, the team's own name,
and — last — `top_known_team_age_group`, the cohort of the team it played. The
order is the whole point: a cohort in a name describes this team, while the
opponent's only describes a fixture, and same-age is a convention rather than a
rule. These tests pin each rung and the boundaries between them.
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT))

from auto_match_unknown_opponents import (  # noqa: E402
    UNMATCHABLE_AGE_GROUP,
    build_unknown_profile,
)
from discover_teams_from_opponents import _build_team_metadata  # noqa: E402


class _FakeResolver:
    """Stands in for GotSportResolver, which no test otherwise exercises."""

    def __init__(self, **fields):
        self.fields = fields
        self.calls = []

    def resolve(self, provider_team_id):
        self.calls.append(provider_team_id)
        return self.fields


class _ExplodingResolver:
    def resolve(self, provider_team_id):  # pragma: no cover - must never run
        raise AssertionError(f"resolver consulted for {provider_team_id!r}")


def test_cohort_in_the_name_beats_the_opponents():
    profile = build_unknown_profile(
        {"unknown_team_name": "Rayados academy boys U15", "top_known_team_age_group": "u12"},
        None,
    )
    assert profile.age_group == "u15"


def test_gender_in_the_name_beats_the_opponents():
    """A wrong gender is worse than a wrong cohort: fetch_candidates filters on it
    before scoring, so the team can never match its real duplicate."""
    profile = build_unknown_profile(
        {"unknown_team_name": "Legends FC 2012 Girls", "top_known_team_gender": "Male"},
        None,
    )
    assert profile.gender == "Female"


def test_a_boys_name_resolves_male():
    profile = build_unknown_profile({"unknown_team_name": "Surf SC U14 Boys"}, None)
    assert (profile.gender, profile.age_group) == ("Male", "u14")


def test_a_cohort_off_the_boards_is_not_replaced_by_the_opponents():
    profile = build_unknown_profile(
        {"unknown_team_name": "Surf SC U8 Boys", "top_known_team_age_group": "u12"},
        None,
    )
    assert profile.age_group == "u8"


def test_u18_in_a_name_reaches_the_stored_spelling():
    """extract_age_group preserves U18 by design; the fold happens on the way out."""
    profile = build_unknown_profile({"unknown_team_name": "Surf SC U18 Boys"}, None)
    assert profile.age_group == "u19"


def test_a_graduation_year_keeps_the_unmatchable_sentinel():
    """None would drop the age filter in fetch_candidates and search every cohort."""
    profile = build_unknown_profile(
        {"unknown_team_name": "Rush 2027", "top_known_team_age_group": "u12"},
        None,
    )
    assert profile.age_group == UNMATCHABLE_AGE_GROUP


def test_the_opponents_cohort_is_still_a_last_resort():
    profile = build_unknown_profile(
        {"unknown_team_name": "ELI7E FC", "top_known_team_age_group": "u12"},
        None,
    )
    assert profile.age_group == "u12"


def test_the_teams_own_record_outranks_its_name():
    """The name is a guess about the team; its GotSport record is a statement.
    A name parsing to the unmatchable sentinel must not displace a real cohort."""
    profile = build_unknown_profile(
        {
            "provider_code": "gotsport",
            "unknown_provider_team_id": "999",
            "unknown_team_full_name": "Rush 2027",
            "top_known_team_age_group": "u12",
        },
        _FakeResolver(unknown_age="U14"),
    )
    assert profile.age_group == "u14"


def test_the_resolver_is_consulted_even_when_the_row_already_has_a_name():
    """The lookup was gated on an empty name, so rows with one took their cohort
    from the team they played."""
    resolver = _FakeResolver(unknown_age="U14", unknown_gender="Female", unknown_state="TX")
    profile = build_unknown_profile(
        {
            "provider_code": "gotsport",
            "unknown_provider_team_id": "999",
            "unknown_team_full_name": "Some Full Name FC",
            "top_known_team_age_group": "u12",
            "top_known_team_gender": "Male",
            "top_known_team_state": "CA",
        },
        resolver,
    )
    assert (profile.age_group, profile.gender, profile.state_code) == ("u14", "Female", "TX")
    assert resolver.calls == ["999"]


def test_the_provider_cohort_outranks_the_inherited_csv_column():
    """unknown_age_group_used carries the previous stage's last-resort guess, which
    is the cohort of the team this one played."""
    meta = _build_team_metadata(
        {
            "provider_code": "gotsport",
            "unknown_provider_team_id": "999",
            "unknown_team_name_used": "Real Name FC",
            "unknown_age_group_used": "u12",
            "unknown_gender_used": "Male",
        },
        _FakeResolver(name="Real Name FC", age="U14", gender="Female", state="TX"),
    )
    assert (meta["age_group"], meta["gender"], meta["state_code"]) == ("u14", "Female", "TX")


def test_the_csv_column_still_fills_in_when_the_provider_says_nothing():
    meta = _build_team_metadata(
        {
            "provider_code": "gotsport",
            "unknown_provider_team_id": "999",
            "unknown_team_name_used": "Real Name FC",
            "unknown_age_group_used": "u12",
            "unknown_gender_used": "Male",
        },
        _FakeResolver(name="Real Name FC"),
    )
    assert (meta["age_group"], meta["gender"]) == ("u12", "Male")


def test_a_resolved_name_displaces_the_unknown_placeholder():
    """auto_match hands over `unknown_<pid>` as a scratch value. Persisting it
    creates exactly the rows backfill-unknown-team-names.yml exists to clean up."""
    meta = _build_team_metadata(
        {
            "provider_code": "gotsport",
            "unknown_provider_team_id": "742007",
            "unknown_team_name_used": "unknown_742007",
            "unknown_age_group_used": "u12",
            "unknown_gender_used": "Male",
        },
        _FakeResolver(name="Seattle United B12 ECNL RL", age="U15"),
    )
    assert meta["team_name"] == "Seattle United B12 ECNL RL"


def test_a_real_name_is_not_displaced_by_the_resolver():
    meta = _build_team_metadata(
        {
            "provider_code": "gotsport",
            "unknown_provider_team_id": "742007",
            "unknown_team_name_used": "Real Name FC",
            "unknown_age_group_used": "u12",
            "unknown_gender_used": "Male",
        },
        _FakeResolver(name="Seattle United B12 ECNL RL"),
    )
    assert meta["team_name"] == "Real Name FC"


def test_a_non_gotsport_row_is_never_looked_up_in_gotsport():
    """Discovery always constructs a GotSportResolver, so widening the provider
    guard would resolve a TGS id against a colliding GotSport team."""
    meta = _build_team_metadata(
        {
            "provider_code": "tgs",
            "unknown_provider_team_id": "742007",
            "unknown_team_name_used": "Real Name FC",
            "unknown_age_group_used": "u12",
            "unknown_gender_used": "Male",
        },
        _ExplodingResolver(),
    )
    assert (meta["team_name"], meta["age_group"]) == ("Real Name FC", "u12")
