"""Unit tests for ``src.tournaments.roster_resolver``.

Pins the GotSport search contract (the parameter names the public endpoint
requires) and the two-pass resolution order. Both the HTTP search and the two
database lookups are injected, so nothing here touches the network or Supabase.
"""

from __future__ import annotations

import re

from src.tournaments.roster_paste import parse_roster
from src.tournaments.roster_resolver import (
    ResolvedTeam,
    _exact_name_or_filter,
    _postgrest_ilike_operand,
    build_search_params,
    make_exact_name_lookup,
    make_provider_id_lookup,
    make_team_details_lookup,
    parse_manual_reference,
    resolve_manual_reference,
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


def test_single_gotsport_hit_with_a_conflicting_club_requires_review():
    row = _row("Male U14\nBarcelona Soccer Club\tBarcelona SC 13B Aztecas\tTX")

    resolved = resolve_row(
        row,
        gotsport_search=lambda name, age, gender: [
            {"team_id": 534748, "team_name": name, "club_name": "Beach FC"}
        ],
        lookup_provider_id=_never_called,
        lookup_exact_name=_never_called,
    )

    assert resolved.status == "review"
    assert resolved.provider_team_id == "534748"
    assert resolved.candidates[0]["club_name"] == "Beach FC"
    assert resolved.review_reason == (
        "Club conflict: submitted 'Barcelona Soccer Club', candidate 'Beach FC'."
    )


def test_single_gotsport_hit_with_a_database_state_conflict_requires_review():
    row = _row("Male U14\nBarcelona Soccer Club\tBarcelona SC 13B Aztecas\tTexas")

    resolved = resolve_row(
        row,
        gotsport_search=lambda name, age, gender: [
            {"team_id": 534748, "team_name": name, "club_name": "Barcelona SC"}
        ],
        lookup_provider_id=lambda _pid: "master-1",
        lookup_exact_name=_never_called,
        lookup_team_details=lambda _team_id: {
            "team_id_master": "master-1",
            "team_name": "Barcelona SC 13B Aztecas",
            "club_name": "Barcelona Soccer Club",
            "state_code": "CA",
        },
    )

    assert resolved.status == "review"
    assert resolved.candidates[0]["team_id_master"] == "master-1"
    assert resolved.review_reason == "State conflict: submitted 'TX', candidate 'CA'."


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


def test_unique_exact_name_with_a_conflicting_club_requires_review():
    row = _row("Male U14\nA Club\tA Team\tTX")

    resolved = resolve_row(
        row,
        gotsport_search=_no_gotsport_hits,
        lookup_provider_id=_no_local_id,
        lookup_exact_name=lambda *_args: ["master-4"],
        lookup_team_details=lambda _team_id: {
            "team_id_master": "master-4",
            "team_name": "A Team",
            "club_name": "Different Academy",
            "state_code": "TX",
        },
    )

    assert resolved.status == "review"
    assert resolved.team_id_master is None
    assert resolved.candidates[0]["team_id_master"] == "master-4"
    assert resolved.review_reason == "Club conflict: submitted 'A Club', candidate 'Different Academy'."


def test_unique_exact_name_with_a_conflicting_state_requires_review():
    row = _row("Male U14\nA Club\tA Team\tTX")

    resolved = resolve_row(
        row,
        gotsport_search=_no_gotsport_hits,
        lookup_provider_id=_no_local_id,
        lookup_exact_name=lambda *_args: ["master-4"],
        lookup_team_details=lambda _team_id: {
            "team_id_master": "master-4",
            "team_name": "A Team",
            "club_name": "A Club",
            "state_code": "California",
        },
    )

    assert resolved.status == "review"
    assert resolved.candidates[0]["team_id_master"] == "master-4"
    assert resolved.review_reason == "State conflict: submitted 'TX', candidate 'CA'."


def test_equivalent_club_and_state_forms_keep_the_unique_exact_name_match():
    row = _row("Male U14\nBarcelona Soccer Club\tA Team\tTexas")

    resolved = resolve_row(
        row,
        gotsport_search=_no_gotsport_hits,
        lookup_provider_id=_no_local_id,
        lookup_exact_name=lambda *_args: ["master-4"],
        lookup_team_details=lambda _team_id: {
            "team_id_master": "master-4",
            "club_name": "Barcelona SC",
            "state_code": "TX",
        },
    )

    assert resolved.status == "exact_name"
    assert resolved.team_id_master == "master-4"


def test_missing_candidate_club_and_state_are_neutral():
    row = _row("Male U14\nA Club\tA Team\tTX")

    resolved = resolve_row(
        row,
        gotsport_search=_no_gotsport_hits,
        lookup_provider_id=_no_local_id,
        lookup_exact_name=lambda *_args: ["master-4"],
        lookup_team_details=lambda _team_id: {"team_id_master": "master-4", "team_name": "A Team"},
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

    def __init__(self, rows, or_filters=None):
        self._rows = list(rows)
        self._selected: tuple[str, ...] | None = None
        self._or_filters = or_filters

    def select(self, fields, *_args, **_kwargs):
        self._selected = tuple(field.strip() for field in fields.split(","))
        return self

    def eq(self, column, value):
        self._rows = [row for row in self._rows if row.get(column) == value]
        return self

    def ilike(self, column, value):
        self._rows = [row for row in self._rows if _fake_ilike_matches(row.get(column, ""), value)]
        return self

    def or_(self, expression):
        if self._or_filters is not None:
            self._or_filters.append(expression)
        clauses = []
        for clause in _split_postgrest_clauses(expression):
            if clause.startswith("and(") and clause.endswith(")"):
                parts = _split_postgrest_clauses(clause[4:-1])
                if len(parts) != 2:
                    raise AssertionError(f"unsupported nested OR clause: {clause}")
                clauses.append([_parse_postgrest_ilike(part) for part in parts])
            else:
                clauses.append([_parse_postgrest_ilike(clause)])
        self._rows = [
            row
            for row in self._rows
            if any(
                all(_fake_ilike_matches(row.get(column, ""), pattern) for column, pattern in clause)
                for clause in clauses
            )
        ]
        return self

    def limit(self, count):
        self._rows = self._rows[:count]
        return self

    def execute(self):
        rows = self._rows
        if self._selected is not None:
            rows = [{field: row.get(field) for field in self._selected} for row in rows]

        class _Response:
            data = rows

        return _Response()


def _fake_ilike_matches(value, expression):
    regex_parts = []
    index = 0
    expression = str(expression)
    while index < len(expression):
        character = expression[index]
        if character == "\\" and index + 1 < len(expression):
            index += 1
            regex_parts.append(re.escape(expression[index]))
        elif character in {"%", "*"}:
            regex_parts.append(".*")
        elif character == "_":
            regex_parts.append(".")
        else:
            regex_parts.append(re.escape(character))
        index += 1
    pattern = re.compile("".join(regex_parts), re.IGNORECASE | re.DOTALL)
    return bool(pattern.fullmatch(str(value)))


def _split_postgrest_clauses(expression):
    clauses = []
    start = 0
    depth = 0
    quoted = False
    escaped = False
    for index, character in enumerate(expression):
        if quoted:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                quoted = False
            continue
        if character == '"':
            quoted = True
        elif character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
        elif character == "," and depth == 0:
            clauses.append(expression[start:index])
            start = index + 1
    if quoted or depth != 0:
        raise AssertionError(f"malformed PostgREST filter: {expression}")
    clauses.append(expression[start:])
    return clauses


def _parse_postgrest_ilike(clause):
    column, separator, operand = clause.partition(".ilike.")
    if not separator or not operand.startswith('"') or not operand.endswith('"'):
        raise AssertionError(f"unsupported PostgREST clause: {clause}")
    value = operand[1:-1]
    decoded = []
    index = 0
    while index < len(value):
        if value[index] == "\\" and index + 1 < len(value):
            decoded.append(value[index + 1])
            index += 2
        else:
            decoded.append(value[index])
            index += 1
    return column, "".join(decoded)


class _FakeClient:
    def __init__(self, **tables):
        self._tables = tables
        self.table_calls = []
        self.or_filters = []

    def table(self, name):
        self.table_calls.append(name)
        return _FakeQuery(self._tables.get(name, []), self.or_filters)


GOTSPORT = "gs-uuid"
OTHER = "other-uuid"
PROVIDERS = [{"id": GOTSPORT, "code": "gotsport"}, {"id": OTHER, "code": "sincsports"}]


def test_exact_name_lookup_treats_backslash_percent_and_underscore_as_literals():
    literal_name = r"FC\One_100%*"
    client = _FakeClient(
        teams=[
            {
                "team_id_master": "literal",
                "team_name": literal_name,
                "age_group": "u14",
                "gender": "Male",
                "is_deprecated": False,
            },
            {
                "team_id_master": "wildcard",
                "team_name": "FCXOneA1000Anything",
                "age_group": "u14",
                "gender": "Male",
                "is_deprecated": False,
            },
        ]
    )

    assert make_exact_name_lookup(client)(literal_name, "u14", "Male") == ["literal"]


def test_exact_name_lookup_matches_a_registered_club_plus_team_label():
    expected = "05742841-3bc5-41de-9820-92976f575d43"
    client = _FakeClient(
        teams=[
            {
                "team_id_master": expected,
                "team_name": "2016/17B Navy",
                "club_name": "Arizona Soccer Club",
                "age_group": "u10",
                "gender": "Male",
                "is_deprecated": False,
            },
            {
                "team_id_master": "same-suffix-different-club",
                "team_name": "2016/17B Navy",
                "club_name": "Arizona United",
                "age_group": "u10",
                "gender": "Male",
                "is_deprecated": False,
            },
        ]
    )

    assert make_exact_name_lookup(client)("Arizona Soccer Club 2016/17B Navy", "u10", "Male") == [expected]
    assert client.table_calls == ["teams"]
    assert len(client.or_filters) == 1


def test_combined_name_filter_batches_every_exact_interpretation():
    assert _exact_name_or_filter("Arizona Soccer Club 2016/17B Navy") == ",".join(
        [
            'team_name.ilike."Arizona Soccer Club 2016/17B Navy"',
            'and(club_name.ilike."Arizona",team_name.ilike."Soccer Club 2016/17B Navy")',
            'and(club_name.ilike."Arizona Soccer",team_name.ilike."Club 2016/17B Navy")',
            'and(club_name.ilike."Arizona Soccer Club",team_name.ilike."2016/17B Navy")',
            'and(club_name.ilike."Arizona Soccer Club 2016/17B",team_name.ilike."Navy")',
        ]
    )


def test_postgrest_name_filter_quotes_reserved_and_ilike_characters():
    assert _postgrest_ilike_operand('FC\\One_100% "Blue,(Team)"') == r'"FC\\\\One\\_100\\% \"Blue,(Team)\""'
    assert _postgrest_ilike_operand("A*B") == r'"A\\*B"'


def test_exact_name_lookup_keeps_direct_and_combined_interpretations_for_review():
    client = _FakeClient(
        teams=[
            {
                "team_id_master": "direct-label",
                "team_name": "Arizona Soccer Club 2016/17B Navy",
                "club_name": "Different Club",
                "age_group": "u10",
                "gender": "Male",
                "is_deprecated": False,
            },
            {
                "team_id_master": "combined-label",
                "team_name": "2016/17B Navy",
                "club_name": "Arizona Soccer Club",
                "age_group": "u10",
                "gender": "Male",
                "is_deprecated": False,
            },
        ]
    )

    assert make_exact_name_lookup(client)("Arizona Soccer Club 2016/17B Navy", "u10", "Male") == [
        "combined-label",
        "direct-label",
    ]


def test_unique_exact_name_uses_full_state_when_state_code_is_missing():
    row = _row("Male U14\nA Club\tA Team\tTX")
    client = _FakeClient(
        teams=[{
            "team_id_master": "master-4",
            "team_name": "A Team",
            "club_name": "A Club",
            "age_group": "u14",
            "gender": "Male",
            "state_code": None,
            "state": "California",
            "is_deprecated": False,
        }]
    )

    resolved = resolve_row(
        row,
        gotsport_search=_no_gotsport_hits,
        lookup_provider_id=_no_local_id,
        lookup_exact_name=lambda *_args: ["master-4"],
        lookup_team_details=make_team_details_lookup(client),
    )

    assert resolved.status == "review"
    assert resolved.review_reason == "State conflict: submitted 'TX', candidate 'CA'."
    assert resolved.candidates[0]["state"] == "California"


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


# -------- manual overrides ------------------------------------------------


def _details(**overrides):
    base = {
        "team_id_master": "master-1",
        "team_name": "Barcelona SC Aztecas U14",
        "club_name": "Barcelona Soccer Club",
        "age_group": "u14",
        "gender": "Male",
    }
    base.update(overrides)
    return base


def test_rankings_url_is_read_as_a_gotsport_id():
    ref = parse_manual_reference("https://rankings.gotsport.com/teams/534748")

    assert ref.kind == "gotsport_id"
    assert ref.value == "534748"


def test_rankings_url_with_trailing_path_still_yields_the_id():
    assert parse_manual_reference("https://rankings.gotsport.com/teams/534748/roster").value == "534748"


def test_bare_number_is_read_as_a_gotsport_id():
    ref = parse_manual_reference("  534748 ")

    assert ref.kind == "gotsport_id"
    assert ref.value == "534748"


def test_uuid_is_read_as_our_own_team_id():
    ref = parse_manual_reference("73af1f26-4629-434e-a61b-a0611d2802f3")

    assert ref.kind == "team_id_master"
    assert ref.value == "73af1f26-4629-434e-a61b-a0611d2802f3"


def test_uppercase_uuid_is_normalised():
    assert parse_manual_reference("73AF1F26-4629-434E-A61B-A0611D2802F3").value == "73af1f26-4629-434e-a61b-a0611d2802f3"


def test_free_text_is_not_guessed_at():
    assert parse_manual_reference("Barcelona SC 13B Aztecas").kind == "unrecognized"


def test_empty_input_is_unrecognized():
    assert parse_manual_reference("   ").kind == "unrecognized"


def test_manual_gotsport_id_resolves_through_the_provider_lookup():
    row = _row("Male U14\nBarcelona Soccer Club\tBarcelona SC 13B Aztecas\tTX")

    outcome = resolve_manual_reference(
        "https://rankings.gotsport.com/teams/534748",
        row,
        lookup_provider_id=lambda pid: "master-1" if pid == "534748" else None,
        lookup_team_details=lambda tid: _details() if tid == "master-1" else None,
    )

    assert outcome.status == "ok"
    assert outcome.team_id_master == "master-1"
    assert outcome.cohort_matches is True


def test_manual_uuid_resolves_without_touching_gotsport():
    row = _row("Male U14\nBarcelona Soccer Club\tBarcelona SC 13B Aztecas\tTX")

    outcome = resolve_manual_reference(
        "73af1f26-4629-434e-a61b-a0611d2802f3",
        row,
        lookup_provider_id=_never_called,
        lookup_team_details=lambda tid: _details(team_id_master=tid),
    )

    assert outcome.status == "ok"
    assert outcome.team_id_master == "73af1f26-4629-434e-a61b-a0611d2802f3"


def test_manual_reference_for_a_team_we_do_not_hold_reports_not_found():
    row = _row("Male U14\nA Club\tA Team\tTX")

    outcome = resolve_manual_reference(
        "999999",
        row,
        lookup_provider_id=lambda pid: None,
        lookup_team_details=lambda tid: None,
    )

    assert outcome.status == "not_found"
    assert outcome.team_id_master is None


def test_manual_reference_in_a_different_cohort_resolves_but_is_flagged():
    row = _row("Male U14\nA Club\tA Team\tTX")

    outcome = resolve_manual_reference(
        "534748",
        row,
        lookup_provider_id=lambda pid: "master-1",
        lookup_team_details=lambda tid: _details(age_group="u12"),
    )

    assert outcome.status == "ok"
    assert outcome.cohort_matches is False


def test_unreadable_manual_reference_is_reported_as_such():
    row = _row("Male U14\nA Club\tA Team\tTX")

    outcome = resolve_manual_reference(
        "Barcelona SC 13B Aztecas",
        row,
        lookup_provider_id=_never_called,
        lookup_team_details=_never_called,
    )

    assert outcome.status == "unrecognized"
