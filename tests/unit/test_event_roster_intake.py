"""Unit tests for ``src.tournaments.event_roster_intake``.

Pins the conversion from a walked event to the pair the seeding intake renders,
and the second free pass over the teams the walk could not link. Both database
lookups and the GotSport search are injected, so nothing here touches the
network or Supabase — and no Streamlit runtime is required.
"""

from __future__ import annotations

import pytest

from src.tournaments.event_roster_intake import (
    needs_name_lookup,
    resolve_master_ids,
    resolve_unlinked,
    to_seeding_rows,
)
from src.tournaments.gotsport_event_roster import EventRoster, EventRosterTeam, redact_secret
from src.tournaments.roster_paste import ParsedRoster, RosterRow
from src.tournaments.roster_resolver import ResolvedTeam, build_search_params


def _team(index: int, **overrides) -> EventRosterTeam:
    return EventRosterTeam(
        **{
            "source_index": index,
            "group_id": "77",
            "division_label": "U-13 BOYS GOLD",
            "age_group": "u13",
            "gender": "Male",
            "team_name": f"Team {index}",
            "registration_id": str(4200000 + index),
            "provider_team_id": None,
            **overrides,
        }
    )


def _roster(*teams: EventRosterTeam, warnings: tuple[str, ...] = ()) -> EventRoster:
    return EventRoster(
        event_id="52975",
        teams=teams,
        warnings=warnings,
        divisions_found=len({team.group_id for team in teams}) or 1,
        divisions_walked=len({team.group_id for team in teams}) or 1,
    )


def _never_called(*args, **kwargs):
    raise AssertionError("this collaborator should not have been called")


def _no_local_id(provider_team_id):
    return None


def _no_exact_name(team_name, age_group, gender):
    return []


# -------- to_seeding_rows -------------------------------------------------


def test_a_mapped_provider_id_is_a_direct_match():
    parsed, resolved = to_seeding_rows(
        _roster(_team(0, provider_team_id="521426")), {"521426": "uuid-a"}
    )

    assert resolved[0].status == "gotsport_id"
    assert resolved[0].team_id_master == "uuid-a"
    assert resolved[0].provider_team_id == "521426"
    assert parsed.rows[0].team_name_raw == "Team 0"


def test_an_unmapped_provider_id_is_unresolved_but_keeps_the_id():
    parsed, resolved = to_seeding_rows(_roster(_team(0, provider_team_id="521426")), {})

    assert resolved[0].status == "unresolved"
    assert resolved[0].provider_team_id == "521426"
    assert resolved[0].team_id_master is None
    assert needs_name_lookup(parsed, resolved) == (0,)


def test_a_team_with_no_provider_id_is_unresolved_and_needs_a_name_pass():
    parsed, resolved = to_seeding_rows(_roster(_team(0)), {})

    assert resolved[0].status == "unresolved"
    assert resolved[0].provider_team_id is None
    assert needs_name_lookup(parsed, resolved) == (0,)


def test_a_matched_team_is_not_sent_for_a_name_pass():
    parsed, resolved = to_seeding_rows(
        _roster(_team(0, provider_team_id="521426")), {"521426": "uuid-a"}
    )

    assert needs_name_lookup(parsed, resolved) == ()


def test_rows_keep_the_order_and_index_the_walk_gave_them():
    roster = _roster(_team(0), _team(1, provider_team_id="1"), _team(2))

    parsed, resolved = to_seeding_rows(roster, {"1": "uuid-b"})

    assert [row.source_index for row in parsed.rows] == [0, 1, 2]
    assert [row.team_name_raw for row in parsed.rows] == ["Team 0", "Team 1", "Team 2"]
    assert [item.source_index for item in resolved] == [0, 1, 2]


def test_a_scraped_row_carries_the_division_cohort_and_no_club():
    parsed, _ = to_seeding_rows(_roster(_team(0)), {})
    row = parsed.rows[0]

    assert (row.section_age_group, row.section_gender) == ("u13", "Male")
    assert row.club_raw == ""
    assert row.state == ""
    assert (row.has_star_marker, row.has_c_marker) == (False, False)


def test_a_control_character_is_stripped_from_a_provider_name():
    parsed, _ = to_seeding_rows(_roster(_team(0, team_name="Rush\x1b[2J SC")), {})

    assert "\x1b" not in parsed.rows[0].team_name_raw
    assert parsed.rows[0].team_name_stripped == parsed.rows[0].team_name_raw


def test_accented_text_survives_the_sanitizer():
    parsed, _ = to_seeding_rows(_roster(_team(0, team_name="Atlético Español")), {})

    assert parsed.rows[0].team_name_raw == "Atlético Español"


# -------- warnings --------------------------------------------------------


def test_resolution_warnings_come_before_the_capped_walk_warnings():
    roster = _roster(_team(0), warnings=tuple(f"page {n} failed" for n in range(20)))

    parsed, _ = to_seeding_rows(roster, {}, ["No Supabase credentials"])

    assert parsed.warnings[0] == "No Supabase credentials"
    assert sum(1 for warning in parsed.warnings if warning.startswith("page ")) == 10
    assert parsed.warnings[-1] == "...and 10 more from the walk."


def test_a_short_walk_is_not_capped_and_gains_no_overflow_line():
    roster = _roster(_team(0), warnings=("one page failed",))

    parsed, _ = to_seeding_rows(roster, {})

    assert parsed.warnings == ("one page failed",)


def test_a_clean_cohort_raises_no_cohort_warning():
    parsed, _ = to_seeding_rows(_roster(_team(0)), {})

    assert parsed.warnings == ()


def test_an_unreadable_division_keeps_its_teams_and_counts_the_blank_cohort():
    roster = _roster(_team(0, age_group="", gender=""), _team(1))

    parsed, resolved = to_seeding_rows(roster, {})

    assert len(parsed.rows) == 2
    assert len(resolved) == 2
    assert any("1 team(s) kept with no age group" in warning for warning in parsed.warnings)
    assert any("1 team(s) kept with no gender" in warning for warning in parsed.warnings)


def test_a_warning_carrying_a_control_character_is_sanitized():
    roster = _roster(_team(0), warnings=("lost \x1b[2J page",))

    parsed, _ = to_seeding_rows(roster, {}, ["credentials ​missing"])

    assert "\x1b" not in parsed.warnings[1]
    assert "​" not in parsed.warnings[0]


# -------- resolve_unlinked ------------------------------------------------


def _pair(*, provider_team_id=None, age_group="u13", gender="Male", name="Team 0"):
    row = RosterRow(
        source_index=0,
        club_raw="",
        team_name_raw=name,
        state="",
        section_age_group=age_group,
        section_gender=gender,
        team_name_stripped=name,
        has_star_marker=False,
        has_c_marker=False,
    )
    item = ResolvedTeam(source_index=0, status="unresolved", provider_team_id=provider_team_id)
    return ParsedRoster(rows=(row,), warnings=()), (item,)


def test_a_known_id_that_resolves_on_retry_never_reaches_the_name_search():
    parsed, resolved = _pair(provider_team_id="521426")

    spliced = resolve_unlinked(
        parsed,
        resolved,
        indices=(0,),
        gotsport_search=_never_called,
        lookup_provider_id=lambda pid: "uuid-a" if pid == "521426" else None,
        lookup_exact_name=_never_called,
    )

    assert spliced[0].status == "gotsport_id"
    assert spliced[0].team_id_master == "uuid-a"
    assert spliced[0].provider_team_id == "521426"


def test_a_known_id_falls_back_to_an_exact_name_and_keeps_the_id():
    parsed, resolved = _pair(provider_team_id="521426")

    spliced = resolve_unlinked(
        parsed,
        resolved,
        indices=(0,),
        gotsport_search=_never_called,
        lookup_provider_id=_no_local_id,
        lookup_exact_name=lambda name, age, gender: ["uuid-b"],
    )

    assert spliced[0].status == "exact_name"
    assert spliced[0].team_id_master == "uuid-b"
    assert spliced[0].provider_team_id == "521426", "the event published this id; a name match does not retire it"


def test_a_known_id_matching_two_teams_is_offered_as_a_choice():
    """The same shape ``resolve_row`` returns, so the operator gets the pick list."""
    parsed, resolved = _pair(provider_team_id="521426")

    spliced = resolve_unlinked(
        parsed,
        resolved,
        indices=(0,),
        gotsport_search=_never_called,
        lookup_provider_id=_no_local_id,
        lookup_exact_name=lambda name, age, gender: ["uuid-b", "uuid-c"],
    )

    assert spliced[0].status == "review"
    assert spliced[0].team_id_master is None
    assert spliced[0].provider_team_id == "521426"
    assert [c["team_id_master"] for c in spliced[0].candidates] == ["uuid-b", "uuid-c"]


def test_a_known_id_matching_nothing_at_all_is_left_alone():
    parsed, resolved = _pair(provider_team_id="521426")

    spliced = resolve_unlinked(
        parsed,
        resolved,
        indices=(0,),
        gotsport_search=_never_called,
        lookup_provider_id=_no_local_id,
        lookup_exact_name=_no_exact_name,
    )

    assert spliced[0] == resolved[0]


def test_a_team_with_no_id_takes_the_pasted_roster_path():
    parsed, resolved = _pair()
    searched: list[tuple[str, str, str]] = []

    spliced = resolve_unlinked(
        parsed,
        resolved,
        indices=(0,),
        gotsport_search=lambda name, age, gender: searched.append((name, age, gender)) or [],
        lookup_provider_id=_no_local_id,
        lookup_exact_name=lambda name, age, gender: ["uuid-d"],
    )

    assert searched == [("Team 0", "u13", "Male")]
    assert spliced[0].status == "exact_name"
    assert spliced[0].team_id_master == "uuid-d"


def test_a_team_with_no_id_and_no_age_is_left_unresolved():
    parsed, resolved = _pair(age_group="")

    spliced = resolve_unlinked(
        parsed,
        resolved,
        indices=(0,),
        gotsport_search=_never_called,
        lookup_provider_id=_never_called,
        lookup_exact_name=_never_called,
    )

    assert spliced[0].status == "unresolved"


def test_a_blank_age_is_what_the_search_parameters_refuse():
    with pytest.raises(ValueError):
        build_search_params("X", "", "Male")


def test_a_team_with_no_id_and_no_gender_is_left_unresolved():
    parsed, resolved = _pair(gender="")

    spliced = resolve_unlinked(
        parsed,
        resolved,
        indices=(0,),
        gotsport_search=_never_called,
        lookup_provider_id=_never_called,
        lookup_exact_name=_never_called,
    )

    assert spliced[0].status == "unresolved"


def test_a_blank_gender_is_what_the_search_parameters_refuse():
    with pytest.raises(KeyError):
        build_search_params("X", "u14", "")


def test_only_the_named_indices_are_touched_and_the_rest_are_returned_as_given():
    rows = tuple(
        RosterRow(
            source_index=index,
            club_raw="",
            team_name_raw=f"Team {index}",
            state="",
            section_age_group="u13",
            section_gender="Male",
            team_name_stripped=f"Team {index}",
            has_star_marker=False,
            has_c_marker=False,
        )
        for index in range(3)
    )
    resolved = (
        ResolvedTeam(source_index=0, status="gotsport_id", team_id_master="uuid-a"),
        ResolvedTeam(source_index=1, status="unresolved", provider_team_id="521426"),
        ResolvedTeam(source_index=2, status="unresolved"),
    )

    spliced = resolve_unlinked(
        ParsedRoster(rows=rows, warnings=()),
        resolved,
        indices=(1,),
        gotsport_search=_never_called,
        lookup_provider_id=lambda pid: "uuid-b",
        lookup_exact_name=_no_exact_name,
    )

    assert [item.source_index for item in spliced] == [0, 1, 2]
    assert spliced[0] == resolved[0]
    assert spliced[2] == resolved[2]
    assert spliced[1].team_id_master == "uuid-b"


class TestCredentialRedaction:
    """The resolution warning is serialized into a file this repo does not ignore."""

    def test_a_resolution_error_carrying_the_key_is_redacted(self):
        key = "eyJhbGciOiJIUzI1NiJ9.SERVICE_ROLE_SECRET.sig"
        exc = ValueError("Illegal header value b'" + key + "'")

        assert key not in redact_secret(exc, key)

    def test_redaction_catches_the_stripped_form_too(self):
        key = "SECRET_KEY_VALUE"
        exc = ValueError("bad header " + key)

        assert "SECRET" not in redact_secret(exc, key + "\n")

    def test_redaction_catches_a_soft_wrapped_key_run_by_run(self):
        """The shape that leaks is the shape that causes the failure.

        A key wrapped across lines in .env.local never appears whole in the
        error, because h11 formats the header with repr — but a long run of it
        does, and deleting the escape recovers the key.
        """
        key = "eyJhbGciOiJIUzI1NiJ9.SERVICE_ROLE_SECRET\n.signature_tail_value"
        exc = ValueError("Illegal header value " + repr(key))

        redacted = redact_secret(exc, key)

        assert "SERVICE_ROLE_SECRET" not in redacted
        assert "signature_tail_value" not in redacted

    def test_a_message_without_the_key_is_left_alone(self):
        assert redact_secret(ValueError("connection refused"), "SECRET") == "connection refused"

    def test_redaction_catches_the_percent_encoded_form(self):
        """`requests` names the URL in its errors, and a key with +, / or = is
        encoded there — so it never appears literally and a plain replace misses it."""
        from urllib.parse import quote_plus

        key = "ab+cd/ef=gh12345"
        exc = ValueError("failed for https://api.example/v1/?apikey=" + quote_plus(key))

        redacted = redact_secret(exc, key)

        assert quote_plus(key) not in redacted
        assert "REDACTED" in redacted


class TestResolveMasterIds:
    """Drive every arm, including the redaction, at its call site.

    A guard proved only against the helper it calls does not show the helper is
    reached — the reason this class exists is that a mutation removing the
    redaction from this function left the whole suite green.
    """

    KEY = "eyJhbGciOiJIUzI1NiJ9.SERVICE_ROLE_SECRET.sig"

    def _team(self, provider_team_id):
        return EventRosterTeam(
            source_index=0,
            group_id="1",
            division_label="U11 Boys Gold",
            age_group="u11",
            gender="Male",
            team_name="A FC",
            registration_id="1",
            provider_team_id=provider_team_id,
        )

    def _credentials(self, monkeypatch):
        monkeypatch.setenv("SUPABASE_URL", "https://project.supabase.co")
        monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", self.KEY)

    def test_skips_the_lookup_when_resolution_is_disabled(self):
        mapping, warnings = resolve_master_ids([self._team("521426")], enabled=False)

        assert (mapping, warnings) == ({}, [])

    def test_skips_the_lookup_when_no_team_has_a_provider_id(self):
        mapping, warnings = resolve_master_ids([self._team(None)], enabled=True)

        assert (mapping, warnings) == ({}, [])

    def test_warns_and_continues_without_credentials(self, monkeypatch):
        monkeypatch.delenv("SUPABASE_URL", raising=False)
        monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
        monkeypatch.delenv("SUPABASE_KEY", raising=False)

        mapping, warnings = resolve_master_ids([self._team("521426")], enabled=True)

        assert mapping == {}
        assert any("credentials" in warning for warning in warnings)

    def test_maps_each_provider_id_once(self, monkeypatch):
        self._credentials(monkeypatch)
        asked = []

        def lookup_factory(_client, _resolver):
            def lookup(provider_id):
                asked.append(provider_id)
                return "master-" + provider_id

            return lookup

        mapping, warnings = resolve_master_ids(
            [self._team("521426"), self._team("521426"), self._team("999")],
            enabled=True,
            client_factory=lambda url, key: object(),
            resolver_factory=lambda client: type("R", (), {"load_merge_map": lambda self: None})(),
            lookup_factory=lookup_factory,
        )

        assert mapping == {"521426": "master-521426", "999": "master-999"}
        assert asked == ["521426", "999"], "each provider id is looked up once"
        assert warnings == []

    def test_warns_when_the_merge_map_failed_to_load(self, monkeypatch):
        self._credentials(monkeypatch)

        class BrokenResolver:
            version = "error"

            def load_merge_map(self):
                return None

        _, warnings = resolve_master_ids(
            [self._team("521426")],
            enabled=True,
            client_factory=lambda url, key: object(),
            resolver_factory=lambda client: BrokenResolver(),
            lookup_factory=lambda client, resolver: (lambda pid: "master"),
        )

        assert any("merge" in warning.lower() for warning in warnings), (
            "load_merge_map swallows its own errors, so this state is the only signal"
        )

    def test_a_database_failure_keeps_the_walk_and_hides_the_key(self, monkeypatch):
        self._credentials(monkeypatch)

        def exploding_client(url, key):
            raise ValueError("Illegal header value b'" + self.KEY + "'")

        mapping, warnings = resolve_master_ids(
            [self._team("521426")], enabled=True, client_factory=exploding_client
        )

        assert mapping == {}
        assert len(warnings) == 1
        assert self.KEY not in warnings[0], (
            "this warning is serialized into reports/, which is not gitignored, "
            "in a public repository"
        )
        assert "REDACTED" in warnings[0]


class TestCredentialIsCheckedBeforeUse:
    """A malformed key must never reach the client that logs it raw.

    `MergeResolver.load_merge_map` catches its own exception and logs the text
    at `src/utils/merge_resolver.py:108`, unredacted. `h11` formats the
    offending header with `repr`, so a service-role key carrying an internal
    newline — the shape `python-dotenv` returns for a soft-wrapped value —
    reaches stderr before this module's own redaction is ever reached.
    """

    KEY = "eyJhbGciOiJIUzI1NiJ9.SERVICE_ROLE\n.signature_tail"

    def _run(self, monkeypatch, key):
        import scripts.scrape_event_roster as cli

        built: list = []
        monkeypatch.setenv("SUPABASE_URL", "https://project.supabase.co")
        monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", key)
        team = EventRosterTeam(
            source_index=0, group_id="1", division_label="U13 Boys",
            age_group="u13", gender="Male", team_name="A",
            registration_id="1", provider_team_id="521426",
        )
        return cli.resolve_master_ids(
            [team],
            enabled=True,
            client_factory=lambda url, key: built.append((url, key)) or object(),
            resolver_factory=lambda client: (_ for _ in ()).throw(AssertionError("reached")),
            lookup_factory=lambda client, resolver: (lambda pid: None),
        ), built

    def test_a_key_with_an_internal_newline_never_reaches_the_client(self, monkeypatch):
        (resolved, warnings), built = self._run(monkeypatch, self.KEY)

        assert built == [], "the client was constructed, so the key can still be logged raw"
        assert resolved == {}
        assert warnings and "SUPABASE_SERVICE_ROLE_KEY" in warnings[0]

    def test_the_refusal_does_not_echo_the_key(self, monkeypatch):
        (_, warnings), _ = self._run(monkeypatch, self.KEY)

        joined = " ".join(warnings)
        # Naming the variable is the point of the message; echoing its value is
        # the leak, so assert on the key's own material rather than on a word
        # that legitimately appears in the variable name.
        assert "eyJhbGciOiJIUzI1NiJ9" not in joined
        assert "signature_tail" not in joined

    def test_a_merely_trailing_newline_is_stripped_and_used(self, monkeypatch):
        (_, warnings), built = self._run(monkeypatch, "cleankey123\n")

        assert built and built[0][1] == "cleankey123", "a trailing newline is not malformed"


def test_the_free_pass_paces_its_calls_to_the_public_search():
    """The GotSport search belongs to someone else and a walked event is hundreds of rows.

    Every other test here leaves ``delay_seconds`` at its default, so the sleep
    never runs and the parameter could be accepted and ignored.
    """
    slept: list[float] = []
    rows = tuple(
        RosterRow(
            source_index=index,
            club_raw="",
            team_name_raw=f"Team {index}",
            state="",
            section_age_group="u13",
            section_gender="Male",
            team_name_stripped=f"Team {index}",
            has_star_marker=False,
            has_c_marker=False,
        )
        for index in range(3)
    )
    resolved = tuple(ResolvedTeam(source_index=index, status="unresolved") for index in range(3))

    import src.tournaments.event_roster_intake as module

    original = module.time.sleep
    module.time.sleep = slept.append
    try:
        resolve_unlinked(
            ParsedRoster(rows=rows, warnings=()),
            resolved,
            indices=(0, 1, 2),
            gotsport_search=lambda *_a: [],
            lookup_provider_id=_no_local_id,
            lookup_exact_name=_no_exact_name,
            delay_seconds=0.25,
        )
    finally:
        module.time.sleep = original

    assert slept == [0.25, 0.25, 0.25], "each searched row must be paced"
