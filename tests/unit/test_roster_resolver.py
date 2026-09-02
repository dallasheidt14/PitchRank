"""Unit tests for ``src.tournaments.roster_resolver``.

Pins the GotSport search contract (the parameter names the public endpoint
requires) and the two-pass resolution order. Both the HTTP search and the two
database lookups are injected, so nothing here touches the network or Supabase.
"""

from __future__ import annotations

from src.tournaments.roster_paste import parse_roster
from src.tournaments.roster_resolver import (
    ResolvedTeam,
    make_provider_id_lookup,
    build_search_params,
    resolve_roster,
    resolve_row,
    summarize,
)


def _row(text: str):
    return parse_roster(text).rows[0]


def _never_called(*args, **kwargs):
    raise AssertionError("lookup should not have been called")


def _no_gotsport_hits(team_name, age_group, gender):
    return []


def _no_local_id(provider_team_id):
    return None


def _no_exact_name(team_name, age_group, gender):
    return []


# -------- build_search_params ---------------------------------------------


def test_search_params_use_u_age_as_an_integer():
    params = build_search_params("A Team", "u14", "Male")

    assert params["search[age]"] == "14"


def test_search_params_map_canonical_gender_to_provider_letter():
    assert build_search_params("A", "u14", "Male")["search[gender]"] == "m"
    assert build_search_params("A", "u14", "Female")["search[gender]"] == "f"


def test_search_params_send_the_team_name_under_the_provider_key():
    params = build_search_params("Barcelona SC 13B Aztecas", "u14", "Male")

    assert params["search[team_or_club_name]"] == "Barcelona SC 13B Aztecas"
    assert params["search[team_country]"] == "USA"
    assert params["search[page]"] == "1"


# -------- pass A: GotSport id ---------------------------------------------


def test_single_gotsport_hit_resolving_locally_is_a_direct_match():
    row = _row("Male U14\nBarcelona Soccer Club\tBarcelona SC 13B Aztecas\tTX")

    resolved = resolve_row(
        row,
        gotsport_search=lambda name, age, gender: [{"team_id": 534748, "team_name": name}],
        lookup_provider_id=lambda pid: "master-1" if pid == "534748" else None,
        lookup_exact_name=_never_called,
    )

    assert resolved.status == "gotsport_id"
    assert resolved.team_id_master == "master-1"
    assert resolved.provider_team_id == "534748"


def test_marker_name_retries_the_stripped_form_when_the_raw_form_misses():
    row = _row("Male U14\nVictoria Youth Soccer Organization\tFire 13B-c\tTX")
    seen: list[str] = []

    def search(name, age_group, gender):
        seen.append(name)
        return [{"team_id": 99, "team_name": name}] if name == "Fire 13B" else []

    resolved = resolve_row(
        row,
        gotsport_search=search,
        lookup_provider_id=lambda pid: "master-2",
        lookup_exact_name=_never_called,
    )

    assert seen == ["Fire 13B-c", "Fire 13B"]
    assert resolved.status == "gotsport_id"


def test_unmarked_name_is_searched_only_once():
    row = _row("Male U14\nA Club\tA Team\tTX")
    seen: list[str] = []

    def search(name, age_group, gender):
        seen.append(name)
        return []

    resolve_row(
        row,
        gotsport_search=search,
        lookup_provider_id=_no_local_id,
        lookup_exact_name=_no_exact_name,
    )

    assert seen == ["A Team"]


def test_several_gotsport_hits_go_to_review_without_picking_one():
    row = _row("Male U12\nSTX Elevate FC\tSTX Elevate FC 2014/15 TR\tTX")

    resolved = resolve_row(
        row,
        gotsport_search=lambda name, age, gender: [
            {"team_id": 726565, "team_name": "STX Elevate FC 2015 M"},
            {"team_id": 724257, "team_name": "STX Elevate FC 2015 TR"},
        ],
        lookup_provider_id=lambda pid: "master-x",
        lookup_exact_name=_no_exact_name,
    )

    assert resolved.status == "review"
    assert resolved.team_id_master is None
    assert [c["team_id"] for c in resolved.candidates] == [726565, 724257]


def test_gotsport_id_we_do_not_hold_falls_through_to_the_name_pass():
    row = _row("Male U14\nA Club\tA Team\tTX")

    resolved = resolve_row(
        row,
        gotsport_search=lambda name, age, gender: [{"team_id": 4242, "team_name": "A Team"}],
        lookup_provider_id=_no_local_id,
        lookup_exact_name=lambda name, age, gender: ["master-3"],
    )

    assert resolved.status == "exact_name"
    assert resolved.team_id_master == "master-3"


# -------- pass B: exact local name ----------------------------------------


def test_unique_exact_name_resolves_when_gotsport_finds_nothing():
    row = _row("Male U14\nA Club\tA Team\tTX")

    resolved = resolve_row(
        row,
        gotsport_search=_no_gotsport_hits,
        lookup_provider_id=_no_local_id,
        lookup_exact_name=lambda name, age, gender: ["master-4"],
    )

    assert resolved.status == "exact_name"


def test_exact_name_matching_several_local_teams_goes_to_review():
    row = _row("Male U14\nA Club\tA Team\tTX")

    resolved = resolve_row(
        row,
        gotsport_search=_no_gotsport_hits,
        lookup_provider_id=_no_local_id,
        lookup_exact_name=lambda name, age, gender: ["master-5", "master-6"],
    )

    assert resolved.status == "review"
    assert resolved.team_id_master is None


def test_exact_name_pass_searches_the_stripped_name():
    row = _row("Male U14\nVictoria Youth Soccer Organization\tFire 13B-c\tTX")
    seen: list[str] = []

    def lookup(name, age_group, gender):
        seen.append(name)
        return []

    resolve_row(
        row,
        gotsport_search=_no_gotsport_hits,
        lookup_provider_id=_no_local_id,
        lookup_exact_name=lookup,
    )

    assert seen == ["Fire 13B"]


def test_neither_pass_matching_leaves_the_row_unresolved():
    row = _row("Male U14\nA Club\tA Team\tTX")

    resolved = resolve_row(
        row,
        gotsport_search=_no_gotsport_hits,
        lookup_provider_id=_no_local_id,
        lookup_exact_name=_no_exact_name,
    )

    assert resolved.status == "unresolved"
    assert resolved.team_id_master is None


# -------- resolve_roster --------------------------------------------------


def test_resolve_roster_keeps_source_order_and_tags_each_row():
    parsed = parse_roster("Male U14\nA Club\tA Team\tTX\nMale U13\nB Club\tB Team\tTX")

    resolved = resolve_roster(
        parsed.rows,
        gotsport_search=lambda name, age, gender: (
            [{"team_id": 1, "team_name": name}] if name == "A Team" else []
        ),
        lookup_provider_id=lambda pid: "master-a",
        lookup_exact_name=_no_exact_name,
    )

    assert [r.source_index for r in resolved] == [0, 1]
    assert [r.status for r in resolved] == ["gotsport_id", "unresolved"]


# -------- summarize -------------------------------------------------------


def test_summarize_counts_every_status_including_the_absent_ones():
    counts = summarize(
        [
            ResolvedTeam(source_index=0, status="gotsport_id"),
            ResolvedTeam(source_index=1, status="gotsport_id"),
            ResolvedTeam(source_index=2, status="review"),
        ]
    )

    assert counts == {"gotsport_id": 2, "exact_name": 0, "review": 1, "unresolved": 0}


# -------- a single search hit must still identify the team ----------------


def test_single_hit_naming_a_different_team_goes_to_review():
    """`team_or_club_name` also matches club names, so one row is not proof of identity.

    Measured: searching `Pre-ECNL B2014/15 Gold` for a San Antonio City SC team
    returned exactly one row named `Beach FC Pre-ECNL B2014/15 Gold`.
    """
    row = _row("Male U12\nSan Antonio City SC\tPre-ECNL B2014/15 Gold-c\tTX")

    resolved = resolve_row(
        row,
        gotsport_search=lambda name, age, gender: [
            {"team_id": 1, "team_name": "Beach FC Pre-ECNL B2014/15 Gold"}
        ],
        lookup_provider_id=_never_called,
        lookup_exact_name=_no_exact_name,
    )

    assert resolved.status == "review"
    assert resolved.team_id_master is None
    assert resolved.candidates[0]["team_name"] == "Beach FC Pre-ECNL B2014/15 Gold"


def test_single_hit_naming_the_stripped_roster_name_is_accepted():
    row = _row("Male U14\nVictoria Youth Soccer Organization\tFire 13B-c\tTX")

    resolved = resolve_row(
        row,
        gotsport_search=lambda name, age, gender: ([{"team_id": 7, "team_name": "Fire 13B"}] if name == "Fire 13B" else []),
        lookup_provider_id=lambda pid: "master-7",
        lookup_exact_name=_never_called,
    )

    assert resolved.status == "gotsport_id"


def test_single_hit_naming_the_roster_team_in_another_case_is_accepted():
    row = _row("Male U12\nSoccer Centro\tSOCCER CENTRO 2015\tTX")

    resolved = resolve_row(
        row,
        gotsport_search=lambda name, age, gender: [{"team_id": 8, "team_name": "Soccer Centro 2015"}],
        lookup_provider_id=lambda pid: "master-8",
        lookup_exact_name=_never_called,
    )

    assert resolved.status == "gotsport_id"


# -------- provider scoping + alias approval -------------------------------


class _FakeQuery:
    """Applies the filters the way PostgREST does, so the assertions test real scoping."""

    def __init__(self, rows):
        self._rows = list(rows)

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, column, value):
        self._rows = [row for row in self._rows if row.get(column) == value]
        return self

    def ilike(self, column, value):
        self._rows = [row for row in self._rows if str(row.get(column, "")).lower() == str(value).lower()]
        return self

    def limit(self, count):
        self._rows = self._rows[:count]
        return self

    def execute(self):
        class _Response:
            data = self._rows

        return _Response()


class _FakeClient:
    def __init__(self, **tables):
        self._tables = tables

    def table(self, name):
        return _FakeQuery(self._tables.get(name, []))


GOTSPORT = "gs-uuid"
OTHER = "other-uuid"
PROVIDERS = [{"id": GOTSPORT, "code": "gotsport"}, {"id": OTHER, "code": "sincsports"}]


def test_provider_id_lookup_ignores_the_same_id_under_another_provider():
    client = _FakeClient(
        providers=PROVIDERS,
        teams=[{"team_id_master": "wrong", "provider_team_id": "534748", "provider_id": OTHER, "is_deprecated": False}],
        team_alias_map=[],
    )

    assert make_provider_id_lookup(client)("534748") is None


def test_provider_id_lookup_accepts_the_gotsport_team_row():
    client = _FakeClient(
        providers=PROVIDERS,
        teams=[{"team_id_master": "right", "provider_team_id": "534748", "provider_id": GOTSPORT, "is_deprecated": False}],
        team_alias_map=[],
    )

    assert make_provider_id_lookup(client)("534748") == "right"


def test_provider_id_lookup_ignores_an_unapproved_alias():
    client = _FakeClient(
        providers=PROVIDERS,
        teams=[],
        team_alias_map=[
            {"team_id_master": "pending-one", "provider_team_id": "534748", "provider_id": GOTSPORT, "review_status": "pending"}
        ],
    )

    assert make_provider_id_lookup(client)("534748") is None


def test_provider_id_lookup_accepts_an_approved_gotsport_alias():
    client = _FakeClient(
        providers=PROVIDERS,
        teams=[],
        team_alias_map=[
            {"team_id_master": "aliased", "provider_team_id": "534748", "provider_id": GOTSPORT, "review_status": "approved"}
        ],
    )

    assert make_provider_id_lookup(client)("534748") == "aliased"
