"""Tests for the standalone GotSport event roster scraper."""

from __future__ import annotations

import argparse
import io
import json
import logging
from pathlib import Path
from urllib.parse import quote_plus

import pytest
import requests
from rich.console import Console

from scripts.scrape_event_roster import (
    _event_id_from,
    _non_negative_float,
    _positive_int,
    _printable,
    _redact,
    _resolve_master_ids,
    _summary_table,
    _write_roster,
)
from src.tournaments.gotsport_event_roster import (
    _ZENROWS_SIDE_STATUSES,
    EVENT_BASE,
    EventRoster,
    EventRosterTeam,
    WafChallengeError,
    make_zenrows_fetcher,
    parse_division_label,
    parse_group_ids,
    parse_group_teams,
    parse_provider_team_id,
    resolve_cohort,
    scrape_event_roster,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "gotsport"

# Every division label in the captured corpus, with the cohort it must resolve to.
# Snapshotted 2026-09-04 after each answer was checked individually; a rate or a
# board-membership assertion cannot fail when a label starts resolving one group
# out, which is how a real mixed-age label scored as a success in an earlier round.
CAPTURED_LABEL_COHORTS = {
    '11U BOYS GOLD A DIVISION': ('u11', 'Male'),
    '14U BOYS GOLD DIVISION': ('u14', 'Male'),
    '17/19U BOYS GOLD DIVISION': ('', 'Male'),
    'B2014 Silver 1 (9v9)': ('u13', 'Male'),
    'B2014 Silver 2 (9v9)': ('u13', 'Male'),
    'B2015 Gold (9v9)': ('u12', 'Male'),
    'U-10 BOYS GOLD': ('u10', 'Male'),
    'U-10 GIRLS GOLD': ('u10', 'Female'),
    'U-11 BOYS GOLD': ('u11', 'Male'),
    'U-11 BOYS SILVER': ('u11', 'Male'),
    'U-11 GIRLS GOLD': ('u11', 'Female'),
    'U-12 BOYS GOLD': ('u12', 'Male'),
    'U-12 BOYS SILVER': ('u12', 'Male'),
    'U-12 GIRLS GOLD': ('u12', 'Female'),
    'U-13 BOYS GOLD': ('u13', 'Male'),
    'U-13 BOYS SILVER': ('u13', 'Male'),
    'U-13 GIRLS GOLD': ('u13', 'Female'),
    'U-14 BOYS GOLD': ('u14', 'Male'),
    'U-15 BOYS GOLD': ('u15', 'Male'),
    'U-15 BOYS SILVER': ('u15', 'Male'),
    'U-15 GIRLS GOLD': ('u15', 'Female'),
    'U-16 BOYS GOLD': ('u16', 'Male'),
    'U-17 BOYS GOLD': ('u17', 'Male'),
    'U-19 BOYS GOLD': ('u19', 'Male'),
    'U10 Blue': ('u10', ''),
    'U10 Boys Tolkin': ('u10', 'Male'),
    'U10B Elite White': ('u10', 'Male'),
    'U11 Girls Sonnett': ('u11', 'Female'),
    'U12B Premier': ('u12', 'Male'),
    'U13 Boys Blue': ('u13', 'Male'),
    'U13 Boys Red': ('u13', 'Male'),
    'U13 Boys White': ('u13', 'Male'),
    'U13 Red': ('u13', ''),
    'U14 Gold': ('u14', ''),
    'U15 Red': ('u15', ''),
    'U15B Premier': ('u15', 'Male'),
    'U17 Boys Reyna': ('u17', 'Male'),
    'U17 Red': ('u17', ''),
    'U19 Gold': ('u19', ''),
}
DIVISION = "U11 Boys Gold"


def _landing_html(group_ids: list[str]) -> str:
    cards = "".join(
        f'<div><a href="/org_event/events/52975/schedules?group={gid}">Schedule</a>'
        f'<a href="/org_event/events/52975/results?group={gid}">Results</a></div>'
        for gid in group_ids
    )
    return f"<html><body><nav><a href='/org_event/events/52975/teams'>Brackets</a></nav>{cards}</body></html>"


def _fixture_row(reg_id: str, name: str, division: str) -> str:
    return (
        "<tr><td>408</td><td>Sep 04, 2026</td>"
        f'<td><a href="/org_event/events/52975/schedules?team={reg_id}">{name}</a></td>'
        "<td>-</td>"
        f'<td><a href="/org_event/events/52975/schedules?team={reg_id}">{name}</a></td>'
        f"<td>Reach 11</td><td>{division}</td></tr>"
    )


def _group_html(
    division: str,
    teams: list[tuple[str, str]],
    *,
    extra_rows: str = "",
    home_heading: str = "Home Team",
    away_heading: str = "Away Team",
) -> str:
    standings = "".join(
        f"<tr><td>{i + 1}</td><td>{name}</td><td>0</td><td>0</td><td>0</td>"
        f"<td>0</td><td>0</td><td>0</td><td>0</td><td>0</td></tr>"
        for i, (_, name) in enumerate(teams)
    )
    fixtures = "".join(_fixture_row(reg, name, division) for reg, name in teams) + extra_rows
    export_id = teams[0][0] if teams else "0"
    return (
        "<html><body>"
        f'<a href="/org_event/events/52975/matches_export?team={export_id}">Export</a>'
        f"<table><tr><td></td><td>Team</td><td>MP</td><td>W</td><td>L</td>"
        f"<td>D</td><td>GF</td><td>GA</td><td>GD</td><td>PTS</td></tr>{standings}</table>"
        f"<table><tr><th>Match #</th><th>Time</th><th>{home_heading}</th><th>Results</th>"
        f"<th>{away_heading}</th><th>Location</th><th>Division</th></tr>{fixtures}</table>"
        "</body></html>"
    )


def _team_html(provider_team_id: str | None, *, opponent_id: str | None = None) -> str:
    anchors = ""
    if opponent_id:
        anchors += f'<a href="https://rankings.gotsport.com/teams/{opponent_id}">Opponent</a>'
    if provider_team_id:
        anchors += f'<a href="https://rankings.gotsport.com/teams/{provider_team_id}">View Rankings</a>'
    if not anchors:
        anchors = '<a href="/org_event/events/52975/matches_export?team=4205984">Export</a>'
    return f"<html><body>{anchors}<table><tr><td>408</td></tr></table></body></html>"


def _fetch_for(
    pages: dict[str, str],
    *,
    failing: frozenset[str] = frozenset(),
    blocking: frozenset[str] = frozenset(),
):
    """One fake fetcher for every walk test; records the URLs it was asked for."""
    calls: list[str] = []

    def fetch(url: str) -> str:
        calls.append(url)
        for fragment in blocking:
            if fragment in url:
                raise WafChallengeError("GotSport returned a bot challenge")
        for fragment in failing:
            if url.endswith(fragment):
                raise requests.HTTPError("422 Unprocessable Entity")
        for fragment, html in pages.items():
            if url.endswith(fragment):
                return html
        raise AssertionError(f"unexpected url: {url}")

    fetch.calls = calls  # type: ignore[attr-defined]
    return fetch


def _one_division_event(division=DIVISION, teams=None, provider_ids=None, **group_kwargs):
    teams = teams or [("4205984", "RSL-AZ North U11B Kauffman")]
    provider_ids = {"4205984": "521426"} if provider_ids is None else provider_ids
    pages = {
        "/org_event/events/52975": _landing_html(["483088"]),
        "schedules?group=483088": _group_html(division, teams, **group_kwargs),
    }
    for reg_id, _ in teams:
        pages[f"schedules?team={reg_id}"] = _team_html(provider_ids.get(reg_id))
    return pages


def _two_division_event():
    return {
        "/org_event/events/52975": _landing_html(["483088", "483090"]),
        "schedules?group=483088": _group_html("U11 Boys Gold", [("1", "First FC")]),
        "schedules?group=483090": _group_html("U11 Girls Silver", [("2", "Second FC")]),
        "schedules?team=1": _team_html("521426"),
        "schedules?team=2": _team_html("521427"),
    }


class TestResolveCohort:
    @pytest.mark.parametrize(
        ("label", "expected"),
        [
            ("U11 Girls Silver", ("u11", "Female")),
            ("BU10", ("u10", "Male")),
            ("GU12 Red", ("u12", "Female")),
            ("U14 Silver", ("u14", "")),
            ("U11 Boys Gold - Alex Freeman", ("u11", "Male")),
            ("U-19 BOYS GOLD", ("u19", "Male")),
            ("U10B Elite White", ("u10", "Male")),
            ("11U BOYS", ("u11", "Male")),
            ("12U Boys Red", ("u12", "Male")),
            ("B2015 Gold (9v9)", ("u12", "Male")),
            ("U12 Flight 2", ("u12", "")),
            ("Group 3 U14", ("u14", "")),
            ("U10 9v9", ("u10", "")),
        ],
    )
    def test_reads_the_label_forms_gotsport_publishes(self, label, expected):
        assert resolve_cohort(label) == expected

    @pytest.mark.parametrize("label", ["U18 Boys", "U18/U19 Girls Gold", "U18/19 Girls"])
    def test_folds_the_u18_band_into_u19(self, label):
        assert resolve_cohort(label)[0] == "u19"

    def test_reads_a_birth_year_label_onto_its_board(self):
        assert resolve_cohort("G2007 Gold") == ("u19", "Female")

    def test_prefers_a_u_age_over_the_band_years_beside_it(self):
        assert resolve_cohort("U12G (AUG 1, 2014 - JULY 31, 2015)") == ("u12", "Female")

    @pytest.mark.parametrize(
        "label",
        [
            "BU12/BU13",
            "BU10-BU11",
            "GU6-GU7",
            "U13-U19",
            "U15/16",
            "U18/U19/20",
            "17/19U BOYS GOLD DIVISION",
            "13/14U Girls",
            "B2017/18",
            "G2015/2016",
        ],
    )
    def test_withholds_a_cohort_when_the_label_names_more_than_one(self, label):
        assert resolve_cohort(label)[0] == ""

    @pytest.mark.parametrize("label", ["U6 Boys", "U9 Boys Gold", "U20 Boys", "U٣٢ Boys"])
    def test_withholds_a_cohort_for_an_age_no_board_holds(self, label):
        assert resolve_cohort(label)[0] == ""

    def test_withholds_a_cohort_when_the_label_carries_no_age(self):
        assert resolve_cohort("Gold Bracket") == ("", "")

    @pytest.mark.parametrize("label", ["Boys/Girls U10", "U14 Girls and Boys", "BU10/GU10"])
    def test_withholds_gender_when_the_label_names_both(self, label):
        assert resolve_cohort(label)[1] == ""


class TestResolveCohortAgainstRealFixtures:
    """The corpus the sibling parser is already tested against.

    A hand-written label list can only confirm the pattern its author had in
    mind. These are real captured group pages, and the expectations are pinned
    per label — a rate alone would have scored ``17/19U BOYS GOLD DIVISION``
    resolving to ``u17`` as a success.
    """

    def _labels(self) -> list[str]:
        return [
            parse_division_label(path.read_text(encoding="utf-8", errors="ignore"))
            for path in sorted(FIXTURES.glob("event_*__group_*.html"))
        ]

    def test_every_captured_group_page_yields_a_division_label(self):
        pages = sorted(FIXTURES.glob("event_*__group_*.html"))
        unlabelled = [
            path.name
            for path in pages
            if not parse_division_label(path.read_text(encoding="utf-8", errors="ignore"))
        ]
        assert len(pages) >= 39, "the captured corpus shrank"
        assert len(unlabelled) <= 2, f"labels stopped parsing: {unlabelled}"

    def test_a_mixed_age_captured_division_is_withheld_not_guessed(self):
        page = FIXTURES / "event_49407__group_436924.html"
        label = parse_division_label(page.read_text(encoding="utf-8", errors="ignore"))
        assert "17/19U" in label
        assert resolve_cohort(label)[0] == "", (
            f"{label!r} names two cohorts; asserting either files half its teams wrong"
        )

    def test_every_captured_label_resolves_to_its_pinned_cohort(self):
        """Pin the answer, not the shape.

        A board-membership or resolution-rate assertion cannot fail when a
        label starts resolving one group out, which is how the real mixed-age
        `17/19U` label scored as a success in an earlier round.
        """
        actual = {label: resolve_cohort(label) for label in self._labels() if label}

        assert actual == CAPTURED_LABEL_COHORTS

    def test_the_pinned_table_covers_every_labelled_fixture(self):
        labels = {label for label in self._labels() if label}

        assert labels == set(CAPTURED_LABEL_COHORTS), (
            "a fixture was added or removed; re-pin the table after checking each answer"
        )


class TestPageParsers:
    def test_landing_page_yields_each_group_once_in_order(self):
        assert parse_group_ids(_landing_html(["483088", "483090", "483088"])) == ("483088", "483090")

    def test_group_page_yields_its_division_label(self):
        assert parse_division_label(_group_html(DIVISION, [("4205984", "A FC")])) == DIVISION

    def test_group_page_without_a_division_column_yields_no_label(self):
        assert parse_division_label("<html><body><table></table></body></html>") == ""

    def test_a_seven_column_standings_table_cannot_supply_the_label(self):
        html = (
            "<html><body><table>"
            "<tr><th>#</th><th>Team</th><th>MP</th><th>W</th><th>L</th><th>GF</th><th>PTS</th></tr>"
            "<tr><td>1</td><td>Some FC</td><td>0</td><td>0</td><td>0</td><td>0</td><td>0</td></tr>"
            "</table>"
            "<table><tr><th>Match #</th><th>Time</th><th>Home Team</th><th>Results</th>"
            "<th>Away Team</th><th>Location</th><th>Division</th></tr>"
            + _fixture_row("1", "Some FC", "U12 Boys Gold")
            + "</table></body></html>"
        )
        assert parse_division_label(html) == "U12 Boys Gold"

    def test_group_page_yields_registration_ids_with_names(self):
        html = _group_html(DIVISION, [("4205984", "RSL-AZ North"), ("4205985", "State 48 FC")])
        assert parse_group_teams(html) == (
            ("4205984", "RSL-AZ North"),
            ("4205985", "State 48 FC"),
        )

    @pytest.mark.parametrize(
        ("home", "away"),
        [("HOME TEAM", "AWAY TEAM"), ("Home team", "Away team"), ("Home&nbsp;Team", "Away Team")],
    )
    def test_heading_wording_and_case_do_not_cost_teams(self, home, away):
        html = _group_html(DIVISION, [("1", "A FC")], home_heading=home, away_heading=away)
        assert parse_group_teams(html) == (("1", "A FC"),)

    def test_an_unmappable_schedule_table_yields_no_teams(self):
        html = _group_html(DIVISION, [("1", "A FC")], home_heading="Host", away_heading="Visitor")
        assert parse_group_teams(html) == ()

    def test_an_export_link_is_never_read_as_a_team_name(self):
        assert parse_group_teams(_group_html(DIVISION, [("4205984", "RSL-AZ North")])) == (
            ("4205984", "RSL-AZ North"),
        )

    def test_the_first_spelling_of_a_team_wins(self):
        html = _group_html(
            DIVISION, [("1", "Full Name FC")], extra_rows=_fixture_row("1", "Trunc...", DIVISION)
        )
        assert parse_group_teams(html) == (("1", "Full Name FC"),)

    def test_team_page_yields_the_provider_id_behind_view_rankings(self):
        assert parse_provider_team_id(_team_html("521426")) == "521426"

    def test_team_page_without_a_rankings_link_yields_none(self):
        assert parse_provider_team_id(_team_html(None)) is None

    def test_an_opponents_rankings_link_is_not_mistaken_for_this_team(self):
        assert parse_provider_team_id(_team_html("521426", opponent_id="111111")) == "521426"

    def test_a_lone_unlabelled_rankings_link_is_not_trusted(self):
        assert parse_provider_team_id(_team_html(None, opponent_id="111111")) is None

    def test_yields_nothing_when_two_unlabelled_rankings_links_compete(self):
        html = (
            '<html><body><a href="https://rankings.gotsport.com/teams/111111">A</a>'
            '<a href="https://rankings.gotsport.com/teams/222222">B</a></body></html>'
        )
        assert parse_provider_team_id(html) is None


class TestScrapeEventRoster:
    def test_walks_landing_then_groups_then_teams(self):
        roster = scrape_event_roster("52975", fetch=_fetch_for(_one_division_event()))

        assert len(roster.teams) == 1
        team = roster.teams[0]
        assert team.registration_id == "4205984"
        assert team.provider_team_id == "521426"
        assert team.age_group == "u11"
        assert team.gender == "Male"
        assert roster.is_complete

    def test_keeps_a_team_whose_page_has_no_rankings_link(self):
        roster = scrape_event_roster("52975", fetch=_fetch_for(_one_division_event(provider_ids={})))

        assert roster.teams[0].provider_team_id is None
        assert roster.is_complete, "an unranked team is not an incomplete walk"

    def test_keeps_the_teams_of_a_division_naming_more_than_one_cohort(self):
        pages = _one_division_event(
            division="BU12/BU13", teams=[("3914600", "Rec Team")], provider_ids={}
        )

        roster = scrape_event_roster("52975", fetch=_fetch_for(pages))

        assert [team.team_name for team in roster.teams] == ["Rec Team"]
        assert roster.teams[0].age_group == ""
        assert any("BU12/BU13" in warning for warning in roster.warnings)

    def test_reports_a_division_whose_schedule_table_it_cannot_recognize(self):
        pages = _one_division_event(home_heading="Host", away_heading="Visitor")

        roster = scrape_event_roster("52975", fetch=_fetch_for(pages))

        assert roster.teams == ()
        assert any("recognize" in warning for warning in roster.warnings)

    def test_numbers_teams_in_walk_order(self):
        pages = _one_division_event(
            teams=[("4205984", "First FC"), ("4205985", "Second FC")],
            provider_ids={"4205984": "521426"},
        )

        roster = scrape_event_roster("52975", fetch=_fetch_for(pages))

        assert [team.source_index for team in roster.teams] == [0, 1]

    def test_paces_requests_when_a_delay_is_configured(self, monkeypatch):
        slept: list[float] = []
        monkeypatch.setattr(
            "src.tournaments.gotsport_event_roster.time.sleep",
            lambda seconds: slept.append(seconds),
        )

        scrape_event_roster(
            "52975", fetch=_fetch_for(_one_division_event()), delay_min=0.4, delay_max=0.4
        )

        assert slept == [0.4, 0.4, 0.4]

    def test_reports_progress_for_every_team_page(self):
        seen: list[tuple[int, int]] = []
        pages = _one_division_event(
            teams=[("1", "First FC"), ("2", "Second FC")], provider_ids={"1": "521426"}
        )

        scrape_event_roster(
            "52975", fetch=_fetch_for(pages), on_progress=lambda d, t: seen.append((d, t))
        )

        assert sorted(seen) == [(1, 2), (2, 2)]

    def test_a_broken_progress_callback_cannot_hide_a_block(self):
        fetch = _fetch_for(_one_division_event(), blocking=frozenset({"team="}))

        def exploding_progress(done, total):
            raise RuntimeError("console closed")

        with pytest.raises(WafChallengeError):
            scrape_event_roster("52975", fetch=fetch, on_progress=exploding_progress)


class TestCompleteness:
    def test_walks_only_the_first_n_divisions(self):
        fetch = _fetch_for(_two_division_event())

        roster = scrape_event_roster("52975", fetch=fetch, limit_groups=1)

        assert [team.team_name for team in roster.teams] == ["First FC"]
        assert not any("group=483090" in url for url in fetch.calls)

    def test_a_truncated_walk_says_so(self):
        roster = scrape_event_roster(
            "52975", fetch=_fetch_for(_two_division_event()), limit_groups=1
        )

        assert not roster.is_complete
        assert roster.divisions_found == 2
        assert any("partial" in warning for warning in roster.warnings)

    def test_a_full_walk_says_it_is_complete(self):
        assert scrape_event_roster("52975", fetch=_fetch_for(_one_division_event())).is_complete

    def test_a_failed_division_page_makes_the_roster_incomplete(self):
        fetch = _fetch_for(_two_division_event(), failing=frozenset({"schedules?group=483088"}))

        roster = scrape_event_roster("52975", fetch=fetch)

        assert not roster.is_complete
        assert roster.divisions_walked == 1

    def test_a_failed_team_page_makes_the_roster_incomplete(self):
        pages = _one_division_event(
            teams=[("1", "First FC"), ("2", "Second FC")], provider_ids={"1": "521426"}
        )
        fetch = _fetch_for(pages, failing=frozenset({"schedules?team=2"}))

        roster = scrape_event_roster("52975", fetch=fetch, max_workers=2)

        assert roster.teams_unreadable == 1
        assert not roster.is_complete, (
            "a blocked team page must not let this roster replace one that has ids"
        )

    def test_reports_an_event_that_published_no_divisions(self):
        fetch = _fetch_for({"/org_event/events/52975": "<html><body>nothing</body></html>"})

        roster = scrape_event_roster("52975", fetch=fetch)

        assert roster.teams == ()
        assert any("no divisions" in warning for warning in roster.warnings)
        assert not roster.is_complete


class TestFetchFailures:
    def _pages(self):
        return _one_division_event(
            teams=[("1", "First FC"), ("2", "Second FC")],
            provider_ids={"1": "521426", "2": "521427"},
        )

    def test_keeps_the_other_teams_when_one_team_page_fails(self):
        fetch = _fetch_for(self._pages(), failing=frozenset({"schedules?team=1"}))

        roster = scrape_event_roster("52975", fetch=fetch, max_workers=2)

        assert [team.team_name for team in roster.teams] == ["First FC", "Second FC"]
        assert roster.teams[0].provider_team_id is None
        assert roster.teams[1].provider_team_id == "521427"

    def test_reports_a_team_whose_page_could_not_be_read(self):
        fetch = _fetch_for(self._pages(), failing=frozenset({"schedules?team=1"}))

        roster = scrape_event_roster("52975", fetch=fetch, max_workers=2)

        assert any("First FC" in warning for warning in roster.warnings)

    def test_keeps_page_order_when_fetched_concurrently(self):
        roster = scrape_event_roster("52975", fetch=_fetch_for(self._pages()), max_workers=4)

        assert [team.team_name for team in roster.teams] == ["First FC", "Second FC"]

    def test_a_failed_group_page_does_not_end_the_walk(self):
        fetch = _fetch_for(_two_division_event(), failing=frozenset({"schedules?group=483088"}))

        roster = scrape_event_roster("52975", fetch=fetch)

        assert [team.team_name for team in roster.teams] == ["Second FC"]
        assert any("483088" in warning for warning in roster.warnings)

    @pytest.mark.parametrize("workers", [1, 4])
    def test_a_bot_challenge_aborts_the_walk_instead_of_emptying_it(self, workers):
        pages = _one_division_event(
            teams=[("1", "A"), ("2", "B"), ("3", "C")], provider_ids={}
        )
        fetch = _fetch_for(pages, blocking=frozenset({"team="}))

        with pytest.raises(WafChallengeError):
            scrape_event_roster("52975", fetch=fetch, max_workers=workers)

    def test_a_blocked_division_page_aborts_the_walk(self):
        fetch = _fetch_for(_one_division_event(), blocking=frozenset({"group="}))

        with pytest.raises(WafChallengeError):
            scrape_event_roster("52975", fetch=fetch)


class TestWalkOrder:
    def test_reads_every_division_before_fetching_any_team_page(self):
        fetch = _fetch_for(_two_division_event())

        scrape_event_roster("52975", fetch=fetch, max_workers=4)

        last_group = max(i for i, url in enumerate(fetch.calls) if "group=" in url)
        first_team = min(i for i, url in enumerate(fetch.calls) if "team=" in url)
        assert last_group < first_team, (
            "team pages must be resolved from one pool after every division is known, "
            "otherwise each division waits on its own slowest page"
        )

    def test_still_groups_each_team_under_its_own_division(self):
        roster = scrape_event_roster("52975", fetch=_fetch_for(_two_division_event()), max_workers=4)

        by_name = {team.team_name: team for team in roster.teams}
        assert by_name["First FC"].division_label == "U11 Boys Gold"
        assert by_name["First FC"].gender == "Male"
        assert by_name["Second FC"].division_label == "U11 Girls Silver"
        assert by_name["Second FC"].gender == "Female"

    def test_a_team_in_two_divisions_keeps_both_rows_but_is_fetched_once(self):
        pages = {
            "/org_event/events/52975": _landing_html(["483088", "483090"]),
            "schedules?group=483088": _group_html("U11 Boys Gold", [("1", "Shared FC")]),
            "schedules?group=483090": _group_html("U11 Boys Silver", [("1", "Shared FC")]),
            "schedules?team=1": _team_html("521426"),
        }
        fetch = _fetch_for(pages)

        roster = scrape_event_roster("52975", fetch=fetch)

        assert [team.group_id for team in roster.teams] == ["483088", "483090"]
        assert all(team.provider_team_id == "521426" for team in roster.teams)
        assert len([url for url in fetch.calls if "team=1" in url]) == 1


class _FakeResponse:
    def __init__(self, text: str, status_code: int = 200, url: str = ""):
        self.text = text
        self.status_code = status_code
        self.url = url

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} for url: {self.url}")


CHALLENGE_BODY = '<html><script>window.gokuProps = {"key":"x"};</script></html>'


class TestZenRowsFetcher:
    def _capture(self, text: str = "<html><body>ok</body></html>", status_code: int = 200):
        seen: dict = {}

        def get(url, params=None, timeout=None):
            seen.update(url=url, params=params, timeout=timeout)
            return _FakeResponse(text, status_code=status_code)

        return get, seen

    def test_asks_for_js_rendering_behind_a_us_residential_proxy(self):
        get, seen = self._capture()

        make_zenrows_fetcher("KEY", get=get)(f"{EVENT_BASE}/52975/schedules?group=1")

        assert seen["params"]["js_render"] == "true"
        assert seen["params"]["premium_proxy"] == "true"
        assert seen["params"]["proxy_country"] == "us"

    def test_asks_for_the_targets_own_status(self):
        get, seen = self._capture()

        make_zenrows_fetcher("KEY", get=get)(f"{EVENT_BASE}/52975")

        assert seen["params"]["original_status"] == "true"

    def test_waits_longer_than_the_vendors_render_budget(self):
        get, seen = self._capture()

        make_zenrows_fetcher("KEY", get=get)(f"{EVENT_BASE}/52975")

        assert seen["timeout"] > 180, "a 180s client timeout aborts before the 422 arrives"

    def test_waits_for_the_division_links_on_the_event_page(self):
        get, seen = self._capture()

        make_zenrows_fetcher("KEY", get=get)(f"{EVENT_BASE}/52975")

        assert "group=" in seen["params"]["wait_for"]

    def test_waits_for_a_table_on_a_schedule_page(self):
        get, seen = self._capture()

        make_zenrows_fetcher("KEY", get=get)(f"{EVENT_BASE}/52975/schedules?team=4205984")

        assert seen["params"]["wait_for"] == "table"

    def test_sends_the_key_without_putting_it_in_the_target_url(self):
        get, seen = self._capture()

        make_zenrows_fetcher("KEY", get=get)(f"{EVENT_BASE}/52975")

        assert seen["params"]["apikey"] == "KEY"
        assert "KEY" not in seen["params"]["url"]


class TestChallengeDetection:
    """The challenge must be classified before its status code is raised on.

    With ``original_status=true`` the block arrives under the target's own
    code — AWS WAF's CAPTCHA action answers 405 — so raising first would file a
    block as an ordinary failure and let the walk finish looking complete.
    """

    def _get(self, body: str, status_code: int):
        def get(url, params=None, timeout=None):
            return _FakeResponse(body, status_code=status_code)

        return get

    @pytest.mark.parametrize("status", [200, 202, 403, 405, 429, 503])
    def test_a_challenge_is_recognised_whatever_status_carries_it(self, status):
        fetcher = make_zenrows_fetcher(
            "KEY", get=self._get(CHALLENGE_BODY, status), attempts=1, backoff_seconds=0
        )

        with pytest.raises(WafChallengeError):
            fetcher(f"{EVENT_BASE}/52975")

    @pytest.mark.parametrize(
        "body",
        [
            '<html><body><a href="/verify_captchas/new">verify</a></body></html>',
            '<html><body><div class="g-recaptcha"></div></body></html>',
        ],
    )
    def test_recognises_the_captcha_shapes_too(self, body):
        fetcher = make_zenrows_fetcher("KEY", get=self._get(body, 200), attempts=1)

        with pytest.raises(WafChallengeError):
            fetcher(f"{EVENT_BASE}/52975")


class TestFetcherResilience:
    def test_retries_a_zenrows_side_failure_before_giving_up(self):
        attempts = {"n": 0}

        def get(url, params=None, timeout=None):
            attempts["n"] += 1
            if attempts["n"] == 1:
                return _FakeResponse("", status_code=422)
            return _FakeResponse("<html><body>ok</body></html>")

        fetcher = make_zenrows_fetcher("KEY", get=get, attempts=3, backoff_seconds=0)

        assert "ok" in fetcher(f"{EVENT_BASE}/52975")
        assert attempts["n"] == 2

    def test_gives_up_after_the_configured_attempts(self):
        attempts = {"n": 0}

        def get(url, params=None, timeout=None):
            attempts["n"] += 1
            return _FakeResponse("", status_code=422)

        fetcher = make_zenrows_fetcher("KEY", get=get, attempts=2, backoff_seconds=0)

        with pytest.raises(RuntimeError):
            fetcher(f"{EVENT_BASE}/52975")
        assert attempts["n"] == 2

    @pytest.mark.parametrize("status", [404, 403, 410])
    def test_does_not_re_buy_a_settled_answer_from_the_target(self, status):
        attempts = {"n": 0}

        def get(url, params=None, timeout=None):
            attempts["n"] += 1
            return _FakeResponse("<html>not found</html>", status_code=status)

        fetcher = make_zenrows_fetcher("KEY", get=get, attempts=3, backoff_seconds=0)

        with pytest.raises(RuntimeError):
            fetcher(f"{EVENT_BASE}/52975")
        assert attempts["n"] == 1, "ZenRows bills every attempt; a target 4xx is settled"


class TestKeyRedaction:
    """A key with reserved characters is the case a plain replace misses.

    ``requests`` percent-encodes query parameters, so the literal key is absent
    from the URL it names in an ``HTTPError``. That text reaches the roster's
    warnings and from there a file under ``reports/``, which is not gitignored,
    in a public repository.
    """

    KEY = "abc+def/ghi=="

    def _failing_get(self):
        def get(url, params=None, timeout=None):
            encoded = f"https://api.zenrows.com/v1/?apikey={quote_plus(self.KEY)}&url=x"
            return _FakeResponse("", status_code=422, url=encoded)

        return get

    def test_the_give_up_error_carries_neither_form_of_the_key(self):
        fetcher = make_zenrows_fetcher(
            self.KEY, get=self._failing_get(), attempts=1, backoff_seconds=0
        )

        with pytest.raises(RuntimeError) as caught:
            fetcher(f"{EVENT_BASE}/52975")

        assert self.KEY not in str(caught.value)
        assert quote_plus(self.KEY) not in str(caught.value)

    def test_the_retry_warning_carries_neither_form_of_the_key(self, caplog):
        fetcher = make_zenrows_fetcher(
            self.KEY, get=self._failing_get(), attempts=2, backoff_seconds=0
        )

        with caplog.at_level(logging.WARNING), pytest.raises(RuntimeError):
            fetcher(f"{EVENT_BASE}/52975")

        logged = "\n".join(record.getMessage() for record in caplog.records)
        assert logged, "the retry arm should log a warning"
        assert self.KEY not in logged
        assert quote_plus(self.KEY) not in logged


class TestCli:
    def _args(self, **fields):
        return type("Args", (), {"event_id": None, "event_url": None, **fields})()

    def _team(self, **overrides):
        return EventRosterTeam(
            **{
                "source_index": 0,
                "group_id": "1",
                "division_label": DIVISION,
                "age_group": "u11",
                "gender": "Male",
                "team_name": "A FC",
                "registration_id": "1",
                "provider_team_id": None,
                **overrides,
            }
        )

    def test_reads_the_event_id_from_a_url(self):
        assert _event_id_from(self._args(event_url=f"{EVENT_BASE}/52975")) == "52975"

    def test_accepts_a_well_formed_event_id(self):
        assert _event_id_from(self._args(event_id="52975")) == "52975"

    def test_refuses_an_event_id_that_could_escape_the_reports_directory(self):
        with pytest.raises(SystemExit):
            _event_id_from(self._args(event_id="x/../../etc"))

    def test_strips_terminal_control_sequences_from_scraped_text(self):
        assert _printable("Rush\x1b[2J SC") == "Rush[2J SC"
        assert "\x1b" not in _printable("\x1b]0;title\x07")

    def test_a_bracketed_team_name_cannot_abort_the_summary(self):
        table = _summary_table([self._team(division_label="U12 [/b] Gold")], {})

        Console(file=io.StringIO(), width=120).print(table)

    def test_refuses_to_replace_a_complete_roster_with_a_partial_one(self, tmp_path):
        out = tmp_path / "roster.json"
        out.write_text(json.dumps({"is_complete": True}), encoding="utf-8")

        with pytest.raises(SystemExit):
            _write_roster(out, {"is_complete": False}, force=False)

        assert json.loads(out.read_text(encoding="utf-8"))["is_complete"] is True

    def test_replaces_a_complete_roster_when_forced(self, tmp_path):
        out = tmp_path / "roster.json"
        out.write_text(json.dumps({"is_complete": True}), encoding="utf-8")

        _write_roster(out, {"is_complete": False}, force=True)

        assert json.loads(out.read_text(encoding="utf-8"))["is_complete"] is False

    def test_writes_a_complete_roster_over_a_partial_one(self, tmp_path):
        out = tmp_path / "roster.json"
        out.write_text(json.dumps({"is_complete": False}), encoding="utf-8")

        _write_roster(out, {"is_complete": True}, force=False)

        assert json.loads(out.read_text(encoding="utf-8"))["is_complete"] is True

    def test_an_unreadable_existing_roster_does_not_discard_the_walk(self, tmp_path):
        out = tmp_path / "roster.json"
        out.write_text("{ truncated", encoding="utf-8")

        _write_roster(out, {"is_complete": False}, force=False)

        assert json.loads(out.read_text(encoding="utf-8"))["is_complete"] is False

    def test_leaves_no_temporary_file_behind(self, tmp_path):
        out = tmp_path / "roster.json"

        _write_roster(out, {"is_complete": True}, force=False)

        assert [path.name for path in tmp_path.iterdir()] == ["roster.json"]


class TestBirthYearBand:
    """A four-digit number in a label must never end the walk.

    ``calculate_age_group_from_birth_year`` answers None outside a fourteen-wide
    window that slides every Aug 1, so a season or graduation year in a division
    name reaches it — and the walk it would abort has already been paid for.
    """

    @pytest.mark.parametrize(
        "label",
        [
            "B1990 Masters",
            "G2005 Premier",
            "B2006 Gold",
            "2026 Presidents Cup U12 Boys",
            "Fall 2026 League U14 Girls",
            "B2024 Micro",
            "2029 Grad Showcase",
        ],
    )
    def test_a_year_outside_the_boards_withholds_rather_than_raising(self, label):
        age_group, _ = resolve_cohort(label)

        assert isinstance(age_group, str)

    def test_a_u_age_still_wins_when_a_season_year_shares_the_label(self):
        assert resolve_cohort("2026 Presidents Cup U12 Boys")[0] == "u12"

    def test_a_boardable_birth_year_still_resolves(self):
        assert resolve_cohort("G2007 Gold") == ("u19", "Female")

    def test_the_whole_walk_survives_a_season_year_in_a_division_name(self):
        pages = _one_division_event(division="2026 Spring Kickoff U13 Boys")

        roster = scrape_event_roster("52975", fetch=_fetch_for(pages))

        assert [team.age_group for team in roster.teams] == ["u13"]


class TestUnicodeDashSpans:
    @pytest.mark.parametrize(
        "label", ["U13-14", "U13\u201314", "U13\u201414", "13\u201314U", "U9\u2013U10"]
    )
    def test_a_dash_span_names_two_cohorts_whatever_dash_it_uses(self, label):
        assert resolve_cohort(label)[0] == ""

    def test_a_single_age_with_a_hyphen_still_resolves(self):
        assert resolve_cohort("U-13 BOYS GOLD") == ("u13", "Male")


class TestRankingsAnchorText:
    def _page(self, text: str) -> str:
        return (
            '<html><body><a href="https://rankings.gotsport.com/teams/521426">'
            + text
            + "</a></body></html>"
        )

    @pytest.mark.parametrize(
        "text",
        ["View Rankings", "view rankings", "VIEW RANKINGS", "View   Rankings", "  View Rankings  "],
    )
    def test_accepts_the_anchor_however_its_whitespace_falls(self, text):
        assert parse_provider_team_id(self._page(text)) == "521426"

    def test_accepts_the_anchor_split_across_nested_markup(self):
        page = self._page("<span>View</span> <span>Rankings</span>")

        assert parse_provider_team_id(page) == "521426"

    @pytest.mark.parametrize("text", ["Preview Rankings", "View Rankings History", "Rankings"])
    def test_rejects_text_that_merely_contains_the_words(self, text):
        assert parse_provider_team_id(self._page(text)) is None


class TestUnreadableVersusEmptyDivisions:
    """Only a table this module cannot READ makes a walk incomplete.

    A division with no fixtures posted is the normal state of an event being
    seeded. Counting it as incomplete disarms the overwrite guard for that
    event permanently, so a later --limit-groups probe could replace a paid
    full roster with two divisions.
    """

    def test_an_unrecognized_schedule_table_is_not_a_complete_walk(self):
        pages = _one_division_event(home_heading="Host", away_heading="Visitor")

        roster = scrape_event_roster("52975", fetch=_fetch_for(pages))

        assert roster.teams == ()
        assert roster.divisions_unreadable == 1
        assert not roster.is_complete, (
            "an empty roster must not be allowed to replace one that has provider ids"
        )

    def test_a_division_with_no_fixtures_posted_is_still_complete(self):
        pages = {
            "/org_event/events/52975": _landing_html(["483088"]),
            "schedules?group=483088": _group_html(DIVISION, []),
        }

        roster = scrape_event_roster("52975", fetch=_fetch_for(pages))

        assert roster.teams == ()
        assert roster.divisions_unreadable == 0
        assert roster.is_complete, (
            "an event whose schedule is not posted yet must still be able to complete, "
            "or its overwrite guard never arms again"
        )
        assert any("no fixtures posted" in warning for warning in roster.warnings)

    def test_a_division_with_teams_leaves_the_unreadable_count_at_zero(self):
        roster = scrape_event_roster("52975", fetch=_fetch_for(_one_division_event()))

        assert roster.divisions_unreadable == 0
        assert roster.is_complete


class TestChallengeNeedsChallengeShape:
    """A marker word alone is the provider's users' to write; the shape is not."""

    def _get(self, body: str, status_code: int = 200):
        def get(url, params=None, timeout=None):
            return _FakeResponse(body, status_code=status_code)

        return get

    def test_a_marker_word_in_a_team_name_does_not_abort_the_walk(self):
        page = _group_html(DIVISION, [("1", "awswaf United")])
        fetcher = make_zenrows_fetcher("KEY", get=self._get(page), attempts=1)

        assert "awswaf United" in fetcher(EVENT_BASE + "/52975/schedules?group=1")

    def test_a_recaptcha_widget_on_a_real_page_does_not_abort_the_walk(self):
        page = _landing_html(["483088"]).replace("<nav>", '<div class="g-recaptcha"></div><nav>')
        fetcher = make_zenrows_fetcher("KEY", get=self._get(page), attempts=1)

        assert "group=483088" in fetcher(EVENT_BASE + "/52975")

    def test_a_real_challenge_page_still_aborts(self):
        fetcher = make_zenrows_fetcher("KEY", get=self._get(CHALLENGE_BODY), attempts=1)

        with pytest.raises(WafChallengeError):
            fetcher(EVENT_BASE + "/52975")


class TestRetryableStatuses:
    @pytest.mark.parametrize("status", sorted(_ZENROWS_SIDE_STATUSES))
    def test_every_member_of_the_retry_set_is_retried(self, status):
        attempts = {"n": 0}

        def get(url, params=None, timeout=None):
            attempts["n"] += 1
            if attempts["n"] == 1:
                return _FakeResponse("", status_code=status)
            return _FakeResponse("<html><body>ok</body></html>")

        fetcher = make_zenrows_fetcher("KEY", get=get, attempts=3, backoff_seconds=0)

        assert "ok" in fetcher(EVENT_BASE + "/52975")
        assert attempts["n"] == 2


class TestCredentialRedaction:
    """The resolution warning is serialized into a file this repo does not ignore."""

    def test_a_resolution_error_carrying_the_key_is_redacted(self):
        key = "eyJhbGciOiJIUzI1NiJ9.SERVICE_ROLE_SECRET.sig"
        exc = ValueError("Illegal header value b'" + key + "'")

        assert key not in _redact(exc, key)

    def test_redaction_catches_the_stripped_form_too(self):
        key = "SECRET_KEY_VALUE"
        exc = ValueError("bad header " + key)

        assert "SECRET" not in _redact(exc, key + "\n")

    def test_redaction_catches_a_soft_wrapped_key_run_by_run(self):
        """The shape that leaks is the shape that causes the failure.

        A key wrapped across lines in .env.local never appears whole in the
        error, because h11 formats the header with repr — but a long run of it
        does, and deleting the escape recovers the key.
        """
        key = "eyJhbGciOiJIUzI1NiJ9.SERVICE_ROLE_SECRET\n.signature_tail_value"
        exc = ValueError("Illegal header value " + repr(key))

        redacted = _redact(exc, key)

        assert "SERVICE_ROLE_SECRET" not in redacted
        assert "signature_tail_value" not in redacted

    def test_a_message_without_the_key_is_left_alone(self):
        assert _redact(ValueError("connection refused"), "SECRET") == "connection refused"


class TestExistingRosterShapes:
    @pytest.mark.parametrize("body", ["[]", "null", '"a string"', "42"])
    def test_a_non_object_roster_does_not_discard_the_walk(self, tmp_path, body):
        out = tmp_path / "roster.json"
        out.write_text(body, encoding="utf-8")

        _write_roster(out, {"is_complete": False}, force=False)

        assert json.loads(out.read_text(encoding="utf-8"))["is_complete"] is False

    def test_a_string_flag_is_not_read_as_complete(self, tmp_path):
        out = tmp_path / "roster.json"
        out.write_text(json.dumps({"is_complete": "false"}), encoding="utf-8")

        _write_roster(out, {"is_complete": False}, force=False)

        assert json.loads(out.read_text(encoding="utf-8"))["is_complete"] is False


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
            division_label=DIVISION,
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
        mapping, warnings = _resolve_master_ids([self._team("521426")], enabled=False)

        assert (mapping, warnings) == ({}, [])

    def test_skips_the_lookup_when_no_team_has_a_provider_id(self):
        mapping, warnings = _resolve_master_ids([self._team(None)], enabled=True)

        assert (mapping, warnings) == ({}, [])

    def test_warns_and_continues_without_credentials(self, monkeypatch):
        monkeypatch.delenv("SUPABASE_URL", raising=False)
        monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
        monkeypatch.delenv("SUPABASE_KEY", raising=False)

        mapping, warnings = _resolve_master_ids([self._team("521426")], enabled=True)

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

        mapping, warnings = _resolve_master_ids(
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

        _, warnings = _resolve_master_ids(
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

        mapping, warnings = _resolve_master_ids(
            [self._team("521426")], enabled=True, client_factory=exploding_client
        )

        assert mapping == {}
        assert len(warnings) == 1
        assert self.KEY not in warnings[0], (
            "this warning is serialized into reports/, which is not gitignored, "
            "in a public repository"
        )
        assert "REDACTED" in warnings[0]


class TestPrintableByCategory:
    """Decided by Unicode category, so the class is covered by construction.

    Enumerated ranges are what let U+061C, U+FEFF and the Tags block through
    while the docstring named exactly the class they belong to.
    """

    @pytest.mark.parametrize(
        "invisible",
        [
            "\x00", "\x1b", "\x7f", "\x9b",           # Cc
            "\u200b", "\u200e", "\u061c", "\ufeff",   # Cf
            "\u2060", "\u202e", "\u2069",              # Cf
            "\U000e0074",                                # Tags
            "\u2028", "\u2029",                         # Zl / Zp
        ],
    )
    def test_strips_every_invisible_character(self, invisible):
        assert _printable("A" + invisible + "B") == "AB"

    @pytest.mark.parametrize(
        "keep", ["\u00e9", "\u00f1", "\U0001f525", "\t", "\n", " ", "\u2014", "\u4e2d"]
    )
    def test_keeps_everything_legitimate(self, keep):
        assert _printable("A" + keep + "B") == "A" + keep + "B"


class TestDashSpansByCategory:
    @pytest.mark.parametrize(
        "dash",
        ["-", "\u2010", "\u2013", "\u2014", "\u2015", "\u2212", "\uff0d", "\u00ad",
         "\u2043", "\ufe58", "\ufe63"],
    )
    def test_a_two_cohort_span_withholds_whatever_dash_joins_it(self, dash):
        assert resolve_cohort("U13" + dash + "14 Boys")[0] == "", (
            "an unattached second age is invisible to the multi-cohort check, "
            "so an uncovered dash turns a withheld cohort into a wrong one"
        )

    def test_a_hyphenated_single_age_still_resolves(self):
        assert resolve_cohort("U-13 BOYS GOLD") == ("u13", "Male")


class TestIdBoundsRejectRatherThanTruncate:
    @pytest.mark.parametrize("pattern_name", ["_GROUP_ID", "_TEAM_ID"])
    def test_an_overlong_id_is_refused_not_shortened(self, pattern_name):
        import src.tournaments.gotsport_event_roster as module

        pattern = getattr(module, pattern_name)
        key = "group" if pattern_name == "_GROUP_ID" else "team"

        assert pattern.findall(f"?{key}=1234567890123") == []
        assert pattern.findall(f"?{key}=4205984") == ["4205984"]

    def test_an_overlong_rankings_id_is_refused(self):
        html = '<html><body><a href="https://rankings.gotsport.com/teams/1234567890123">View Rankings</a></body></html>'

        assert parse_provider_team_id(html) is None, (
            "a truncated id is a different team, accepted by direct lookup at full confidence"
        )


class TestAccessibleRankingsNames:
    @pytest.mark.parametrize("attribute", ["aria-label", "title"])
    def test_an_icon_only_link_is_honoured(self, attribute):
        html = (
            '<html><body><a href="https://rankings.gotsport.com/teams/521426" '
            + attribute
            + '="View Rankings"><svg/></a></body></html>'
        )

        assert parse_provider_team_id(html) == "521426"

    def test_an_accessible_name_that_merely_contains_the_words_is_rejected(self):
        html = (
            '<html><body><a href="https://rankings.gotsport.com/teams/521426" '
            'aria-label="Preview Rankings"><svg/></a></body></html>'
        )

        assert parse_provider_team_id(html) is None


class TestRetryableStatusesPinned:
    """Pin the literals, not the production set.

    Parametrizing over `_ZENROWS_SIDE_STATUSES` derives the cases from the
    thing under test, so removing a status removes its own guard.
    """

    EXPECTED = frozenset({408, 422, 425, 429, 500, 502, 503, 504})

    def test_the_retry_set_is_exactly_these_statuses(self):
        assert _ZENROWS_SIDE_STATUSES == self.EXPECTED

    @pytest.mark.parametrize("status", sorted(EXPECTED))
    def test_each_expected_status_is_retried(self, status):
        attempts = {"n": 0}

        def get(url, params=None, timeout=None):
            attempts["n"] += 1
            if attempts["n"] == 1:
                return _FakeResponse("", status_code=status)
            return _FakeResponse("<html><body>ok</body></html>")

        fetcher = make_zenrows_fetcher("KEY", get=get, attempts=3, backoff_seconds=0)

        assert "ok" in fetcher(EVENT_BASE + "/52975")
        assert attempts["n"] == 2


class TestCliArgumentGuards:
    @pytest.mark.parametrize("value", ["-1", "0"])
    def test_a_non_positive_limit_is_refused(self, value):
        with pytest.raises(argparse.ArgumentTypeError):
            _positive_int(value)

    def test_a_positive_limit_is_accepted(self):
        assert _positive_int("2") == 2

    def test_a_negative_delay_is_refused(self):
        with pytest.raises(argparse.ArgumentTypeError):
            _non_negative_float("-1")

    def test_a_zero_delay_is_accepted(self):
        assert _non_negative_float("0") == 0.0


class TestMain:
    """Drive the entry point itself.

    Every guard in `main()` was previously proved only through the helper it
    calls: a mutation putting `raise SystemExit` as its first statement left the
    whole suite green. That is the same shape that hid an unredacted credential
    two rounds ago, so the sanitizer's real call sites are pinned here rather
    than only as a pure function.
    """

    DIRTY = "Rush\x1b[2J \u202eSC"

    def _roster(self, **overrides):
        team = EventRosterTeam(
            source_index=0,
            group_id="1",
            division_label="U11 Boys \x1b[2J Gold",
            age_group="u11",
            gender="Male",
            team_name=self.DIRTY,
            registration_id="1",
            provider_team_id="521426",
        )
        fields = {
            "event_id": "52975",
            "teams": (team,),
            "warnings": ("touched \x1b[2J warning",),
            "divisions_found": 1,
            "divisions_walked": 1,
            "divisions_unreadable": 0,
            "teams_unreadable": 0,
        }
        fields.update(overrides)
        return EventRoster(**fields)

    def _run(self, monkeypatch, tmp_path, argv, roster=None, **stubs):
        import scripts.scrape_event_roster as cli

        monkeypatch.setenv("ZENROWS_API_KEY", "KEY")
        monkeypatch.setattr(cli, "make_zenrows_fetcher", lambda *a, **k: (lambda url: ""))
        monkeypatch.setattr(
            cli, "scrape_event_roster", stubs.get("scrape", lambda *a, **k: roster or self._roster())
        )
        monkeypatch.setattr(cli, "_resolve_master_ids", lambda teams, **k: ({}, []))
        monkeypatch.setattr(cli.console, "file", io.StringIO())
        out = tmp_path / "roster.json"
        monkeypatch.setattr(
            "sys.argv", ["scrape_event_roster.py", "--event-id", "52975", "--out", str(out), *argv]
        )
        return cli.main(), out

    def test_writes_a_roster_with_no_control_characters_in_it(self, monkeypatch, tmp_path):
        code, out = self._run(monkeypatch, tmp_path, [])

        assert code == 0
        written = out.read_text(encoding="utf-8")
        assert "\x1b" not in written
        assert "\u202e" not in written
        payload = json.loads(written)
        assert payload["teams"][0]["team_name"] == "Rush[2J SC"
        assert payload["is_complete"] is True

    def test_a_dry_run_writes_nothing(self, monkeypatch, tmp_path):
        code, out = self._run(monkeypatch, tmp_path, ["--dry-run"])

        assert code == 0
        assert not out.exists()

    def test_a_blocked_walk_exits_with_a_message_not_a_traceback(self, monkeypatch, tmp_path):
        def blocked(*args, **kwargs):
            raise WafChallengeError("GotSport returned a bot challenge for /events/52975")

        with pytest.raises(SystemExit) as caught:
            self._run(monkeypatch, tmp_path, [], scrape=blocked)

        assert "Blocked" in str(caught.value)

    def test_an_unreadable_event_exits_with_a_message_not_a_traceback(self, monkeypatch, tmp_path):
        def refused(*args, **kwargs):
            raise RuntimeError("Fetching /events/52975 answered 404; not retried")

        with pytest.raises(SystemExit) as caught:
            self._run(monkeypatch, tmp_path, [], scrape=refused)

        assert "Could not read event 52975" in str(caught.value)

    def test_a_missing_api_key_stops_before_any_fetch(self, monkeypatch, tmp_path):
        import scripts.scrape_event_roster as cli

        monkeypatch.delenv("ZENROWS_API_KEY", raising=False)
        monkeypatch.setattr(
            "sys.argv", ["scrape_event_roster.py", "--event-id", "52975"]
        )
        monkeypatch.setattr(cli.console, "file", io.StringIO())

        with pytest.raises(SystemExit) as caught:
            cli.main()

        assert "ZENROWS_API_KEY" in str(caught.value)

    def test_a_partial_walk_cannot_replace_a_complete_roster(self, monkeypatch, tmp_path):
        out = tmp_path / "roster.json"
        out.write_text(json.dumps({"is_complete": True, "teams": [1, 2]}), encoding="utf-8")
        partial = self._roster(divisions_found=2, divisions_walked=1)

        with pytest.raises(SystemExit) as caught:
            self._run(monkeypatch, tmp_path, [], roster=partial)

        assert "--force" in str(caught.value)
        assert json.loads(out.read_text(encoding="utf-8"))["teams"] == [1, 2]
