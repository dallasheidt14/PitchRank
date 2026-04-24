"""Unit tests for pure helpers in src/scrapers/sincsports_clubs.py.

Scope is limited to the novel, branch-heavy pure functions per repo
convention (``tests/unit/test_scrape_playmetrics.py``): HTML fixture
parsing, response-shape validation, envelope decoding, state-code
round-trip. HTTP plumbing is covered by the end-to-end narrow live-run
verification in the implementation plan, not by mocked HTTP tests.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.scrapers.sincsports_clubs import SincSportsClubsScraper, TeamRecord
from src.utils.us_states import STATE_CODE_TO_NAME, STATE_NAME_TO_CODE, state_name_to_code

FIXTURES = Path(__file__).parent.parent / "fixtures" / "sincsports_clubs"


@pytest.fixture
def scraper():
    return SincSportsClubsScraper(delay_min=0, delay_max=0, max_retries=1)


@pytest.fixture
def initial_page_soup():
    from bs4 import BeautifulSoup

    html = (FIXTURES / "search_page_initial.html").read_text(encoding="utf-8")
    return BeautifulSoup(html, "html.parser")


def test_extract_form_state_returns_all_hidden_inputs(scraper, initial_page_soup):
    form_state = scraper._extract_form_state(initial_page_soup)
    # The three well-known ASP.NET fields MUST be present.
    assert "__VIEWSTATE" in form_state
    assert "__VIEWSTATEGENERATOR" in form_state
    assert "__EVENTVALIDATION" in form_state
    # EO framework fields captured in Step 3 reconnaissance.
    assert "eo_version" in form_state
    assert "eo_style_keys" in form_state
    assert "__eo_obj_states" in form_state
    # Sanity on values: VIEWSTATE is base64-ish, non-empty
    assert len(form_state["__VIEWSTATE"]) > 100
    # Observed count of hidden inputs on the live page is 18; allow ±2 for site drift.
    assert 15 <= len(form_state) <= 25, f"unexpected hidden input count: {len(form_state)}"


class TestParseResultRows:
    def test_single_page_populated(self, scraper):
        import re

        id_pattern = re.compile(r"^[A-Z]{2,4}[A-Z0-9]+$")
        html = (FIXTURES / "results_page_1.html").read_text(encoding="utf-8")
        records = scraper._parse_result_rows(html, age_group="u12", gender="Male", state_code="NC")
        assert len(records) >= 100
        for r in records:
            assert r.age_group == "u12"
            assert r.gender == "Male"
            assert r.state_code == "NC"
            # Provider IDs use alphanumeric codes like NCM14762 / TNM142BF — cross-state
            # IDs surface because SincSports encodes the originating state in the prefix.
            assert id_pattern.match(r.provider_team_id), f"unexpected id format: {r.provider_team_id!r}"
            assert r.team_name, "team_name must be non-empty"
        # Most records SHOULD originate in NC; sanity check the majority.
        nc_count = sum(1 for r in records if r.provider_team_id.startswith("NC"))
        assert nc_count / len(records) > 0.8, f"expected >80% NC-prefixed ids, got {nc_count}/{len(records)}"
        # No duplicate IDs within a single combo parse.
        ids = [r.provider_team_id for r in records]
        assert len(set(ids)) == len(ids), "duplicate provider_team_ids in populated fixture"

    def test_empty_results_yields_zero_rows(self, scraper):
        html = (FIXTURES / "results_empty.html").read_text(encoding="utf-8")
        records = scraper._parse_result_rows(html, age_group="u4", gender="Female", state_code="WY")
        assert records == []

    def test_club_name_populated_from_cbox_header(self, scraper):
        html = (FIXTURES / "results_page_1.html").read_text(encoding="utf-8")
        records = scraper._parse_result_rows(html, age_group="u12", gender="Male", state_code="NC")
        clubs = {r.club_name for r in records if r.club_name}
        # Fixture includes the "AC Sandhills (ACS)" club with 3 teams.
        assert any("AC Sandhills" in c for c in clubs), f"expected AC Sandhills club, got {clubs!r}"

    def test_multi_team_club_yields_all_teams(self, scraper):
        html = (FIXTURES / "results_az_u12_boys.html").read_text(encoding="utf-8")
        records = scraper._parse_result_rows(html, age_group="u12", gender="Male", state_code="AZ")
        # AZ U12 fixture has clubs with multiple teams — 202 teams across 74 clubs.
        assert len(records) > 150
        # Every record's provider_team_id should be unique.
        ids = [r.provider_team_id for r in records]
        assert len(set(ids)) == len(ids)

    def test_filter_inputs_are_authoritative_for_metadata(self, scraper):
        """age / gender / state come from filter args, never parsed from the row."""
        html = (FIXTURES / "results_page_1.html").read_text(encoding="utf-8")
        # Deliberately pass mismatched labels — scraper should honour the args.
        records = scraper._parse_result_rows(html, age_group="u99", gender="Custom", state_code="XX")
        assert records, "fixture has teams"
        assert all(r.age_group == "u99" for r in records)
        assert all(r.gender == "Custom" for r in records)
        assert all(r.state_code == "XX" for r in records)


class TestValidateResponseShape:
    def test_accepts_populated(self, scraper):
        html = (FIXTURES / "results_page_1.html").read_text(encoding="utf-8")
        assert scraper._validate_response_shape(html) is True

    def test_accepts_empty(self, scraper):
        html = (FIXTURES / "results_empty.html").read_text(encoding="utf-8")
        # Real empty responses carry the same "<h3>Under X Girls from Y</h3>"
        # title as populated ones — this IS a valid response.
        assert scraper._validate_response_shape(html) is True

    @pytest.mark.parametrize(
        "fragment",
        [
            "",
            None,
            "<html>completely unrelated page</html>",
            "<div>no header</div>",
            "<h3>Some other heading</h3>",
        ],
    )
    def test_rejects_non_search_shapes(self, scraper, fragment):
        assert scraper._validate_response_shape(fragment) is False


class TestDecodeEnvelope:
    def test_decodes_raw_envelope(self, scraper):
        raw = (FIXTURES / "results_page_1_raw.xml").read_text(encoding="utf-8")
        decoded = scraper._decode_envelope(raw)
        assert decoded is not None
        assert "<h3>Under 12 Boys from North Carolina</h3>" in decoded
        assert 'class="cbox' in decoded

    def test_returns_none_when_no_envelope(self, scraper):
        assert scraper._decode_envelope("") is None
        assert scraper._decode_envelope("<html>plain</html>") is None


class TestHasMoreResults:
    def test_single_response_site_never_paginates(self, scraper):
        """SincSports returns every match in one response — pagination=none."""
        populated = (FIXTURES / "results_page_1.html").read_text(encoding="utf-8")
        empty = (FIXTURES / "results_empty.html").read_text(encoding="utf-8")
        assert scraper._has_more_results(populated) is False
        assert scraper._has_more_results(empty) is False


class TestStateCodeRoundTrip:
    def test_canonical_name_roundtrip(self):
        for code, name in STATE_CODE_TO_NAME.items():
            assert STATE_NAME_TO_CODE[name] == code

    def test_case_insensitive_lookup(self):
        assert state_name_to_code("Arizona") == "AZ"
        assert state_name_to_code("arizona") == "AZ"
        assert state_name_to_code("ARIZONA") == "AZ"

    def test_dc_variants(self):
        assert state_name_to_code("D.C.") == "DC"
        assert state_name_to_code("DC") == "DC"
        assert state_name_to_code("District of Columbia") == "DC"
        assert state_name_to_code("Washington D.C.") == "DC"

    def test_unknown_returns_none(self):
        assert state_name_to_code("") is None
        assert state_name_to_code("   ") is None
        assert state_name_to_code("Narnia") is None

    def test_fifty_states_plus_dc(self):
        assert len(STATE_CODE_TO_NAME) == 51
        assert "DC" in STATE_CODE_TO_NAME


class TestTeamRecord:
    def test_dataclass_fields(self):
        r = TeamRecord(
            provider_team_id="NCM14762",
            team_name="Test Team",
            club_name="Test Club",
            age_group="u12",
            gender="Male",
            state_code="NC",
        )
        assert r.provider_team_id == "NCM14762"
        assert r.state_code == "NC"
