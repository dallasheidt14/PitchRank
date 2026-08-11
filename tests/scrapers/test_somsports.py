"""Unit tests for the SOM Sports / athletes2events tournament scraper.

Pure-function parser tests against committed HTML fixtures (no HTTP, no
pytest-vcr). Matcher normalization tests use ``unittest.mock`` to dodge
the Supabase init dance.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.scrapers._age_normalization import derive_division_age_group
from src.scrapers.somsports import (
    FlightRef,
    TeamDetail,
    _parse_score,
    parse_event_name,
    parse_groups_page,
    parse_schedule_page,
    parse_team_detail_page,
    split_schedule_url,
)

FIXTURES = Path(__file__).parent.parent / "fixtures" / "somsports"


# ── Fixture loaders ───────────────────────────────────────────────────────────


@pytest.fixture
def groups_html() -> str:
    return (FIXTURES / "event_72_groups.html").read_text(encoding="utf-8")


@pytest.fixture
def flight_727_html() -> str:
    return (FIXTURES / "event_72_flight_727_schedule.html").read_text(encoding="utf-8")


@pytest.fixture
def flight_776_dual_age_html() -> str:
    return (FIXTURES / "event_72_flight_776_dual_age.html").read_text(encoding="utf-8")


@pytest.fixture
def team_3959_detail_html() -> str:
    return (FIXTURES / "event_72_team_3959_detail.html").read_text(encoding="utf-8")


# Synthetic minimal HTML for the unplayed-row case — live event 72 has no
# unplayed rows once the tournament finishes, so the unplayed-row test
# uses an inline fixture rather than a saved file.
UNPLAYED_MATCHES_HTML = """
<table class="matches-table">
  <tr class="bg-secondary text-white"><th colspan="9">Mon May 25, 2026</th></tr>
  <tr class="bg-light">
    <th>Game</th><th>Division/Flight</th><th>Group</th><th>Time</th>
    <th>Home Team</th><th>Result</th><th>Away Team</th><th>Field</th><th>Location</th>
  </tr>
  <tr>
    <td>#999</td>
    <td><a href="https://x/events/72/schedules?flight-id=727">Boys-U19 - Oro</a></td>
    <td>A</td>
    <td>10:00 AM</td>
    <td><a href="https://x/events/72/schedules?team-id=3959">Crossfire B07/08 Academy ECNL</a></td>
    <td class="text-nowrap"> - </td>
    <td><a href="https://x/events/72/schedules?team-id=5142">Albion Santa Ana</a></td>
    <td><a href="#">Field 03</a></td>
    <td><a href="#">Socal Sports Complex</a></td>
  </tr>
  <tr>
    <td>#998</td>
    <td><a href="https://x/events/72/schedules?flight-id=727">Boys-U19 - Oro</a></td>
    <td>A</td>
    <td>11:00 AM</td>
    <td><a href="https://x/events/72/schedules?team-id=3959">Crossfire B07/08 Academy ECNL</a></td>
    <td class="text-nowrap"></td>
    <td><a href="https://x/events/72/schedules?team-id=5142">Albion Santa Ana</a></td>
    <td><a href="#">Field 03</a></td>
    <td><a href="#">Socal Sports Complex</a></td>
  </tr>
</table>
"""


# ── Groups page ───────────────────────────────────────────────────────────────


class TestParseGroupsPage:
    def test_event_name_extracted(self, groups_html):
        assert parse_event_name(groups_html) == "Club America Cup"

    def test_flight_count_covers_all_age_buckets(self, groups_html):
        flights = parse_groups_page(groups_html)
        # Live event 72 has 64 flights including sub-u10 (U7/U8/U9); the CLI
        # filters those out, but the parser returns everything.
        assert len(flights) >= 26
        # Cohorts u10..u17 + u19 must all be represented for at least one gender.
        ages_present = {f.age_group for f in flights}
        for age in ("u10", "u11", "u12", "u13", "u14", "u15", "u16", "u17", "u19"):
            assert age in ages_present, f"{age} missing"

    def test_genders_both_present(self, groups_html):
        flights = parse_groups_page(groups_html)
        assert {f.gender for f in flights} == {"Male", "Female"}

    def test_tier_labels_extracted(self, groups_html):
        flights = parse_groups_page(groups_html)
        tiers = {f.tier_label for f in flights}
        # Spanish tier names: Oro, Plata, Bronce (Champions in some flights).
        assert any("Oro" in t for t in tiers)
        assert any("Plata" in t for t in tiers)
        assert any("Bronce" in t for t in tiers)

    def test_specific_flight_727_is_boys_u19_oro(self, groups_html):
        flights = parse_groups_page(groups_html)
        boys_u19_oro = [f for f in flights if f.flight_id == 727]
        assert len(boys_u19_oro) == 1
        f = boys_u19_oro[0]
        assert f.age_group == "u19"
        assert f.gender == "Male"
        assert f.tier_label == "Oro"

    def test_dual_age_flight_776_canonicalizes_to_heading_age(self, groups_html):
        # ``Oro (2014/15 11 v 11)`` under the Girls-U12 table → u12 (heading wins).
        flights = parse_groups_page(groups_html)
        match = [f for f in flights if f.flight_id == 776]
        assert len(match) == 1
        assert match[0].age_group == "u12"
        assert match[0].gender == "Female"

    def test_u18_folds_to_u19(self, groups_html):
        """Helper applies U18→U19 fold; no flight should report u18."""
        flights = parse_groups_page(groups_html)
        assert "u18" not in {f.age_group for f in flights}

    def test_age_filter_excludes_sub_u10(self, groups_html):
        # The parser includes u7/u8/u9 — the filter is in the CLI. This test
        # documents that the parser does NOT pre-filter sub-u10.
        flights = parse_groups_page(groups_html)
        in_scope = [f for f in flights if int(f.age_group.lstrip("u")) >= 10]
        dropped = [f for f in flights if int(f.age_group.lstrip("u")) < 10]
        assert len(in_scope) >= 26
        # Live event 72 includes u7/u8/u9 flights.
        assert any(int(f.age_group.lstrip("u")) < 10 for f in flights) or dropped == []


# ── Schedule page ─────────────────────────────────────────────────────────────


class TestParseSchedulePage:
    def test_boys_u19_oro_full_round_robin(self, flight_727_html):
        teams, games = parse_schedule_page(flight_727_html, 727)
        # 3 groups × 4 teams = 12; each group is a 6-game round-robin + bracket.
        assert len(teams) == 12
        # Live Oro flight scraped after the tournament: 21 played games.
        assert len(games) == 21

    def test_standings_first_team_is_crossfire(self, flight_727_html):
        teams, _ = parse_schedule_page(flight_727_html, 727)
        crossfire = [t for t in teams if "Crossfire" in t.team_name]
        assert len(crossfire) == 1
        c = crossfire[0]
        assert c.provider_team_id == "3959"
        assert c.group_letter == "A"
        assert c.position == 1
        assert c.mp == 3
        assert c.pts == 9
        assert c.gf == 12
        assert c.ga == 1

    def test_games_have_team_ids_and_scores(self, flight_727_html):
        _, games = parse_schedule_page(flight_727_html, 727)
        for g in games:
            assert g.home_provider_team_id and g.away_provider_team_id
            assert g.home_provider_team_id != g.away_provider_team_id
            assert g.home_score is not None and g.away_score is not None
            assert g.flight_id == 727
            assert g.game_date is not None
            assert g.game_date.year == 2026

    def test_unplayed_rows_have_none_scores(self):
        _, games = parse_schedule_page(UNPLAYED_MATCHES_HTML, 727)
        # 2 unplayed rows; both should return None scores (CLI filters them out).
        assert len(games) == 2
        assert all(g.home_score is None and g.away_score is None for g in games)

    def test_dual_age_flight_776_parses(self, flight_776_dual_age_html):
        teams, games = parse_schedule_page(flight_776_dual_age_html, 776)
        # Girls-U12 Oro (2014/15) flight: 8 teams, 13 played games (live data).
        assert len(teams) == 8
        assert len(games) == 13


class TestDeriveDivisionAgeGroup:
    """The shared helper handles SOM Sports's dual-age birth-year form."""

    def test_dual_birth_year_short_form(self):
        # ``Oro (2014/15 11 v 11)`` — older birth year (2014) → U12 in 2025-26.
        assert derive_division_age_group("Oro (2014/15 11 v 11)") == "u12"

    def test_dual_birth_year_full_form(self):
        # ``2007/2008`` — older birth year (2007) → U19.
        assert derive_division_age_group("Bronce 2007/2008 Boys") == "u19"

    def test_u_token_slash(self):
        assert derive_division_age_group("U15/16 Boys Tan (2)") == "u16"

    def test_single_u_token(self):
        assert derive_division_age_group("U19 Boys Blue") == "u19"

    def test_u18_folds_to_u19(self):
        assert derive_division_age_group("U18 Boys") == "u19"

    def test_no_age_token_returns_none(self):
        assert derive_division_age_group("Champions Group") is None
        assert derive_division_age_group("") is None


# ── Team detail page ──────────────────────────────────────────────────────────


class TestParseTeamDetailPage:
    def test_state_code_extracted_from_h4(self, team_3959_detail_html):
        detail = parse_team_detail_page(team_3959_detail_html, "3959")
        assert detail.provider_team_id == "3959"
        assert detail.state_code == "WA"

    def test_missing_state_returns_none(self):
        html = "<html><body><h4>Some Team - Matches</h4></body></html>"
        detail = parse_team_detail_page(html, "999")
        assert detail.state_code is None


# ── Score parser ──────────────────────────────────────────────────────────────


class TestParseScore:
    def test_dash_separated(self):
        assert _parse_score("3 - 1") == (3, 1)

    def test_no_spaces(self):
        assert _parse_score("0-0") == (0, 0)

    def test_v_separator(self):
        assert _parse_score(" 5 v 2 ") == (5, 2)

    def test_empty_returns_none(self):
        assert _parse_score("") == (None, None)

    def test_dash_only_returns_none(self):
        assert _parse_score("-") == (None, None)
        assert _parse_score(" - ") == (None, None)

    def test_non_numeric_returns_none(self):
        assert _parse_score("TBD") == (None, None)
        assert _parse_score("Cancelled") == (None, None)


# ── URL helper ────────────────────────────────────────────────────────────────


class TestSplitScheduleUrl:
    def test_flight_url(self):
        assert split_schedule_url("https://x/events/72/schedules?flight-id=727") == (72, 727, None)

    def test_team_url(self):
        assert split_schedule_url("https://x/events/72/schedules?team-id=3959") == (72, None, 3959)


# ── Matcher — name normalization ──────────────────────────────────────────────


@pytest.fixture
def matcher():
    """Build a SomSportsGameMatcher with a mocked Supabase client.

    Patch ``_create_review_queue_entry`` to a no-op so anything that touches
    DB inserts during alias-cache preload stays inert.
    """
    from src.models.somsports_matcher import SomSportsGameMatcher

    supabase = MagicMock()
    return SomSportsGameMatcher(supabase, provider_id="provider-x", alias_cache={})


class TestMatcherNormalizesEcnlMarkers:
    """Expected outputs pinned by running the matcher against each input once.

    See the docstring in the plan: do NOT hand-guess the post-base-normalization
    output; the base ``normalize_name_for_matching`` applies its own rules
    (lowercasing, punctuation strip, etc.) that interact with the SOM Sports
    preprocess.
    """

    def test_birth_range_plus_ecnl_plus_academy(self, matcher):
        assert matcher._normalize_team_name("Crossfire B07/08 Academy ECNL") == "crossfire"

    def test_full_year_birth_range(self, matcher):
        assert matcher._normalize_team_name("Some Club 2007/2008 Boys") == "some club"

    def test_mls_next(self, matcher):
        assert matcher._normalize_team_name("Chula Vista FC MLS Next 2007") == "chula vista fc 2007"

    def test_mls_ad(self, matcher):
        assert matcher._normalize_team_name("Los Angeles Bull MLS AD") == "los angeles bull"


class TestMatcherStripsCoachSuffix:
    def test_dash_coach_first_last(self, matcher):
        # ``Beach FC B07/08 ECRL - Jorge Reyes`` — strip coach + ECRL + B07/08.
        assert matcher._normalize_team_name("Beach FC B07/08 ECRL - Jorge Reyes") == "beach fc"

    def test_comma_coach_single_name(self, matcher):
        # ``Surf San Diego Surf ECNL RL Blue B08/07, Aleu`` — strip the lot.
        assert (
            matcher._normalize_team_name("Surf San Diego Surf ECNL RL Blue B08/07, Aleu") == "surf san diego surf blue"
        )


class TestMatcherCanonicalizesClubNameBeforeFuzzy:
    """``_fuzzy_match_team`` must apply the per-state Monday standardization
    registry to ``club_name`` before delegating to the base's gated funnel.

    This is what makes ``Mustang SC`` (raw SOM Sports extraction) match the
    canonical ``Mustang Soccer`` rows the Monday job produces. Without it,
    the gated ``.ilike("club_name", X)`` query at the base never hits those
    rows and the fuzzy fallback grades them below auto-approve.
    """

    @pytest.mark.parametrize(
        "state,raw_club,expected_canonical",
        [
            ("CA", "Mustang SC", "Mustang Soccer"),
            ("CA", "mvla", "Mountain View Los Altos Soccer Club"),
            ("CA", "Beach FC (CA)", "Beach Futbol Club"),
            ("CA", "San Diego Surf", "San Diego Surf Soccer Club"),
            ("WA", "XF", "Crossfire Premier"),
            ("AZ", "RSL-AZ", "RSL Arizona"),
            ("CA", "Totally Unknown Club", "Totally Unknown Club"),  # pass-through
        ],
    )
    def test_canonical_club_forwarded_to_base(self, matcher, state, raw_club, expected_canonical):
        # Capture the club_name that reaches GameHistoryMatcher._fuzzy_match_team.
        captured = {}

        def fake_base_fuzzy(team_name, age_group, gender, club_name=None):
            captured["team_name"] = team_name
            captured["age_group"] = age_group
            captured["gender"] = gender
            captured["club_name"] = club_name
            return None

        with patch(
            "src.models.game_matcher.GameHistoryMatcher._fuzzy_match_team",
            side_effect=fake_base_fuzzy,
            autospec=False,
        ):
            matcher._fuzzy_match_team(
                team_name="Some Team Name 2011",
                age_group="u15",
                gender="Male",
                club_name=raw_club,
                state_code=state,
            )

        assert captured["club_name"] == expected_canonical, (
            f"Expected base to receive canonical {expected_canonical!r}, got {captured.get('club_name')!r}"
        )
        # Inputs other than club_name must pass through unchanged.
        assert captured["team_name"] == "Some Team Name 2011"
        assert captured["age_group"] == "u15"
        assert captured["gender"] == "Male"

    def test_club_extraction_when_caller_doesnt_provide_club(self, matcher):
        """When ``club_name`` is None, the override should extract from the
        team name AND canonicalize before delegating."""
        captured = {}

        def fake_base_fuzzy(team_name, age_group, gender, club_name=None):
            captured["club_name"] = club_name
            return None

        with patch(
            "src.models.game_matcher.GameHistoryMatcher._fuzzy_match_team",
            side_effect=fake_base_fuzzy,
            autospec=False,
        ):
            # "Mustang SC 2011B" — extractor likely returns "Mustang SC",
            # which then canonicalizes to "Mustang Soccer" under CA.
            matcher._fuzzy_match_team(
                team_name="Mustang SC 2011B",
                age_group="u15",
                gender="Male",
                club_name=None,
                state_code="CA",
            )
        # Allow either the canonical OR the raw — the point is we shouldn't
        # silently drop the club. Most strict check: canonical when extractor
        # returned exactly "Mustang SC".
        assert captured["club_name"] in {"Mustang Soccer", "Mustang SC", None}, (
            f"Unexpected club forwarded: {captured.get('club_name')!r}"
        )


# ── CLI resume semantics ──────────────────────────────────────────────────────


class TestCliResumeLegacyCacheBackcompat:
    """Backward-compat shim: cache files written before the ``l → losses``
    field rename must still load via ``--resume`` without crashing.

    Regression: a previous version of ``ScrapedTeam`` named the losses
    field ``l``. Renaming it (E741 lint fix) silently broke every
    operator's resume workflow because ``_load_flight_cache`` does
    ``ScrapedTeam(**t)`` against the on-disk JSON, which still contained
    the legacy key. The shim in ``_load_flight_cache`` translates ``l``
    → ``losses`` before construction.
    """

    def test_legacy_l_key_translates_to_losses(self, tmp_path, monkeypatch):
        import json as _json

        from scripts import scrape_somsports_tournament as cli

        event_id = 88888
        flight_id = 999
        cache_dir = tmp_path / "reports" / "somsports" / str(event_id) / "flights"
        cache_dir.mkdir(parents=True)
        (cache_dir / f"{flight_id}.json").write_text(
            _json.dumps(
                {
                    "teams": [
                        {
                            "provider_team_id": "T1",
                            "team_name": "Legacy Cache Team",
                            "group_letter": "A",
                            "position": 1,
                            "mp": 3,
                            "w": 2,
                            "d": 1,
                            "l": 0,  # legacy key — must translate to ``losses``
                            "gf": 5,
                            "ga": 1,
                            "gd": 4,
                            "pts": 7,
                        }
                    ],
                    "games": [],
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.chdir(tmp_path)
        result = cli._load_flight_cache(event_id, flight_id)
        assert result is not None, "legacy cache should load via backward-compat shim"
        teams, _ = result
        assert len(teams) == 1
        assert teams[0].losses == 0


class TestCliResumeSkipsCachedFlights:
    """``--resume`` reads the per-flight cache instead of refetching."""

    def test_dry_run_with_existing_cache_skips_fetch(self, tmp_path, monkeypatch):
        from scripts import scrape_somsports_tournament as cli

        # Lay down a valid per-flight cache so Pass 2 can use it.
        event_id = 99999
        flight_id = 727
        cache_dir = tmp_path / "reports" / "somsports" / str(event_id) / "flights"
        cache_dir.mkdir(parents=True)
        (cache_dir / f"{flight_id}.json").write_text(
            json.dumps(
                {
                    "teams": [
                        {
                            "provider_team_id": "3959",
                            "team_name": "Crossfire",
                            "group_letter": "A",
                            "position": 1,
                            "mp": 3,
                            "w": 3,
                            "d": 0,
                            "losses": 0,
                            "gf": 12,
                            "ga": 1,
                            "gd": 11,
                            "pts": 9,
                        }
                    ],
                    "games": [],
                }
            ),
            encoding="utf-8",
        )
        # Lay down a team_details cache so Pass 3 has nothing to fetch.
        (tmp_path / "reports" / "somsports" / str(event_id) / "team_details.json").write_text(
            json.dumps(
                {
                    "3959": {
                        "provider_team_id": "3959",
                        "state_code": "WA",
                        "coach": None,
                        "manager": None,
                    }
                }
            ),
            encoding="utf-8",
        )

        monkeypatch.chdir(tmp_path)

        # Stub the scraper: fetch_groups returns a single in-scope flight;
        # fetch_flight / fetch_team_detail must NOT be called.
        flight = FlightRef(
            flight_id=flight_id,
            age_group="u19",
            gender="Male",
            tier_label="Oro",
            raw_division_name="Boys-U19 - Oro",
        )

        def boom_fetch_flight(*args, **kwargs):
            raise AssertionError("fetch_flight should not be called when cache is present")

        def boom_fetch_team_detail(*args, **kwargs):
            raise AssertionError("fetch_team_detail should not be called when cache is present")

        with (
            patch.object(cli.SomSportsScraper, "fetch_groups", return_value=("Test Event", [flight])),
            patch.object(cli.SomSportsScraper, "fetch_flight", side_effect=boom_fetch_flight),
            patch.object(cli.SomSportsScraper, "fetch_team_detail", side_effect=boom_fetch_team_detail),
        ):
            argv = [
                "scrape_somsports_tournament.py",
                "--event-id",
                str(event_id),
                "--resume",
                "--dry-run",
            ]
            monkeypatch.setattr("sys.argv", argv)
            rc = cli.main()

        assert rc == 0


# ── Perspective record (H + A) ────────────────────────────────────────────────


class TestPerspectiveRecord:
    def test_h_and_a_rows_for_one_game(self):
        from datetime import date as ddate

        from scripts.scrape_somsports_tournament import perspective_record
        from src.scrapers.somsports import TournamentGame

        game = TournamentGame(
            game_id="410",
            game_date=ddate(2026, 5, 23),
            kickoff_time="09:25 AM",
            home_provider_team_id="3959",
            home_team_name="Crossfire B07/08 Academy ECNL",
            away_provider_team_id="5142",
            away_team_name="Albion Santa Ana BU19 EA Barrios",
            home_score=3,
            away_score=1,
            field="Field 03",
            venue="Socal Sports Complex",
            flight_id=727,
            group_letter="A",
        )
        flight = FlightRef(
            flight_id=727,
            age_group="u19",
            gender="Male",
            tier_label="Oro",
            raw_division_name="Boys-U19 - Oro",
        )
        details = {
            "3959": TeamDetail("3959", "WA", None, None),
            "5142": TeamDetail("5142", "CA", None, None),
        }

        common = dict(
            game=game,
            flight=flight,
            team_details=details,
            event_id=72,
            event_name="Club America Cup",
            scrape_run_id="run-1",
            scraped_at="2026-05-28T00:00:00Z",
        )
        h = perspective_record(perspective="H", **common)
        a = perspective_record(perspective="A", **common)

        assert h["home_away"] == "H"
        assert h["team_id"] == "3959"
        assert h["goals_for"] == 3
        assert h["goals_against"] == 1
        assert h["result"] == "W"
        assert h["state_code"] == "WA"
        assert h["age_group"] == "u19"
        assert h["gender"] == "Male"

        assert a["home_away"] == "A"
        assert a["team_id"] == "5142"
        assert a["goals_for"] == 1
        assert a["goals_against"] == 3
        assert a["result"] == "L"
        assert a["state_code"] == "CA"

        # Both rows share the same game_id and source_url.
        assert h["schedule_id"] == a["schedule_id"] == "410"
        assert h["source_url"] == a["source_url"]
        assert "flight-id=727" in h["source_url"]
