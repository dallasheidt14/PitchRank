"""Unit tests for the SincSports event teamlist parser.

Scope follows the repo convention set by ``tests/unit/test_scrape_playmetrics.py``
and ``tests/unit/test_sincsports_clubs.py``: branch-heavy pure functions only
(``parse_teamlist`` and ``_normalize_age``), no HTTP mocking. Live fetch is
covered by the narrow operator dry-run noted in the plan.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.scrapers.sincsports_events import (
    CANONICAL_AGE_GROUPS,
    SincSportsEventsScraper,
    _normalize_age,
)

FIXTURE = Path(__file__).parent.parent / "fixtures" / "sincsports_events" / "teamlist_puri.html"


@pytest.fixture
def puri_html() -> str:
    return FIXTURE.read_text(encoding="utf-8")


class TestNormalizeAge:
    @pytest.mark.parametrize("age_int, expected", [(10, "u10"), (14, "u14"), (17, "u17"), (19, "u19")])
    def test_canonical_band_pass_through(self, age_int, expected):
        assert _normalize_age(age_int) == expected

    def test_u18_merges_into_u19(self):
        assert _normalize_age(18) == "u19"

    @pytest.mark.parametrize("age_int, expected", [(6, "u6"), (7, "u7"), (8, "u8"), (9, "u9")])
    def test_micro_band_returned_so_caller_can_filter(self, age_int, expected):
        # Helper widened to ``[6, 19]`` for the Gotsport tier parser; the
        # SincSports caller's ``include_ages`` filter still excludes these
        # by default via ``CANONICAL_AGE_GROUPS``.
        assert _normalize_age(age_int) == expected

    @pytest.mark.parametrize("age_int", [0, 5, 20, 25, 99, -1])
    def test_out_of_band_returns_none(self, age_int):
        assert _normalize_age(age_int) is None


class TestParseTeamlist:
    def test_puri_cup_canonical_ages_only(self, puri_html):
        records = SincSportsEventsScraper.parse_teamlist(puri_html)
        # Known cardinality from the Puri Cup fixture at capture time.
        assert 250 <= len(records) <= 350, f"Unexpected team count: {len(records)}"
        # All records must be in the canonical age band.
        for r in records:
            assert r.age_group in CANONICAL_AGE_GROUPS
            assert r.gender in ("Male", "Female")

    def test_u8_u9_filtered_by_default(self, puri_html):
        records = SincSportsEventsScraper.parse_teamlist(puri_html)
        ages = {r.age_group for r in records}
        assert "u8" not in ages
        assert "u9" not in ages

    def test_include_ages_u8_u9_opt_in(self, puri_html):
        wide = frozenset({"u8", "u9", *CANONICAL_AGE_GROUPS})
        records = SincSportsEventsScraper.parse_teamlist(puri_html, include_ages=wide)
        ages = {r.age_group for r in records}
        # Puri Cup has u8 Male + u9 F/M per fixture.
        assert "u8" in ages
        assert "u9" in ages

    def test_every_record_has_required_fields(self, puri_html):
        records = SincSportsEventsScraper.parse_teamlist(puri_html)
        for r in records:
            assert r.provider_team_id, r
            assert r.team_name, r
            # club_name and state_code can technically be empty, but shouldn't be for a real tournament.
            assert r.state_code, r
            assert len(r.state_code) == 2, r  # postal code length
            assert r.club_name, r

    def test_team_ids_uppercase_and_unique(self, puri_html):
        records = SincSportsEventsScraper.parse_teamlist(puri_html)
        ids = [r.provider_team_id for r in records]
        assert all(tid == tid.upper() for tid in ids)
        assert len(set(ids)) == len(ids), "parse_teamlist must dedupe by provider_team_id"

    def test_known_team_extracted(self, puri_html):
        """Spot-check: Chicago Inter Soccer 2016B Red should be present as u10 Male IL."""
        records = SincSportsEventsScraper.parse_teamlist(puri_html)
        match = [r for r in records if r.provider_team_id == "ILM161BC"]
        assert len(match) == 1
        r = match[0]
        assert r.team_name == "Chicago Inter Soccer 2016B Red South"
        assert r.club_name == "Chicago Inter Soccer"
        assert r.state_code == "IL"
        assert r.age_group == "u10"
        assert r.gender == "Male"

    def test_gender_derived_from_heading_not_team_name(self, puri_html):
        """Heading ('Under X Boys/Girls') is authoritative for gender."""
        records = SincSportsEventsScraper.parse_teamlist(puri_html)
        by_gender = {"Male": 0, "Female": 0}
        for r in records:
            by_gender[r.gender] += 1
        # Both buckets populated (sanity check — both exist in Puri Cup).
        assert by_gender["Male"] > 0
        assert by_gender["Female"] > 0

    @pytest.mark.parametrize(
        "fragment, expected_count",
        [
            ("", 0),
            ("<html><body><p>no tables</p></body></html>", 0),
            (
                # table without the Team|Club|State header
                "<html><body><h3>Under 14 Girls</h3><table><tr><td>X</td></tr></table></body></html>",
                0,
            ),
            (
                # Team|Club|State table but no preceding heading
                "<html><body><table><tr><td>Team</td><td>Club</td><td>State</td></tr>"
                "<tr><td><a onclick=\"eo_Callback('cpTeamSummary','ZZZ1')\">t</a></td>"
                "<td>c</td><td>ZZ</td></tr></table></body></html>",
                0,
            ),
        ],
    )
    def test_malformed_inputs_return_empty(self, fragment, expected_count):
        records = SincSportsEventsScraper.parse_teamlist(fragment)
        assert len(records) == expected_count

    def test_anchor_without_onclick_skipped(self):
        """Rows lacking the eo_Callback onclick pattern are silently dropped."""
        html = (
            "<h3>Under 14 Girls First Division</h3>"
            "<table>"
            "<tr><td>Team</td><td>Club</td><td>State</td></tr>"
            "<tr><td><a href='#'>Plain team no onclick</a></td><td>C</td><td>WI</td></tr>"
            "</table>"
        )
        assert SincSportsEventsScraper.parse_teamlist(html) == []

    def test_dual_age_heading_takes_younger(self):
        """`Under 9/10 Girls First Division` → u9 (younger primary cohort)."""
        html = (
            "<h3>Under 9/10 Girls First Division</h3>"
            "<table>"
            "<tr><td>Team</td><td>Club</td><td>State</td></tr>"
            "<tr><td><a onclick=\"eo_Callback('cpTeamSummary', 'WIF9100'); return false;\">Sample</a></td>"
            "<td>Sample Club</td><td>WI</td></tr>"
            "</table>"
        )
        wide = frozenset({"u9", *CANONICAL_AGE_GROUPS})
        records = SincSportsEventsScraper.parse_teamlist(html, include_ages=wide)
        assert len(records) == 1
        assert records[0].age_group == "u9"
        assert records[0].gender == "Female"

    def test_compact_birthyear_heading_format(self):
        """`2016 - U10 Girls Mendota 7v7` (RWISC) → u10 Female, not just `Under 10`."""
        html = (
            "<h2>2016 - U10 Girls Mendota 7v7</h2>"
            "<table>"
            "<tr><td>Team</td><td>Club</td><td>State</td></tr>"
            "<tr><td><a onclick=\"eo_Callback('cpTeamSummary', 'ILF1611F'); return false;\">"
            "FC-1 Academy G2016 Elite</a></td><td>FC-1 Academy</td><td>IL</td></tr>"
            "</table>"
        )
        records = SincSportsEventsScraper.parse_teamlist(html)
        assert len(records) == 1
        assert records[0].provider_team_id == "ILF1611F"
        assert records[0].age_group == "u10"
        assert records[0].gender == "Female"
        assert records[0].club_name == "FC-1 Academy"
        assert records[0].state_code == "IL"

    def test_compact_dual_age_heading_takes_younger(self):
        """`2017 - U9/10 Girls` (compact dual-age) → u9 (younger primary cohort)."""
        html = (
            "<h2>2017 - U9/10 Girls Mendota 7v7</h2>"
            "<table>"
            "<tr><td>Team</td><td>Club</td><td>State</td></tr>"
            "<tr><td><a onclick=\"eo_Callback('cpTeamSummary', 'WIF9100'); return false;\">Sample</a></td>"
            "<td>Sample Club</td><td>WI</td></tr>"
            "</table>"
        )
        wide = frozenset({"u9", *CANONICAL_AGE_GROUPS})
        records = SincSportsEventsScraper.parse_teamlist(html, include_ages=wide)
        assert len(records) == 1
        assert records[0].age_group == "u9"
        assert records[0].gender == "Female"

    def test_heading_without_gender_token_not_classified(self):
        """The broadened `U<age>` regex still requires a Boys/Girls token: a
        `U12 Coed` heading must NOT classify its Team|Club|State table as a division."""
        html = (
            "<h2>2014 - U12 Coed Bracket</h2>"
            "<table>"
            "<tr><td>Team</td><td>Club</td><td>State</td></tr>"
            "<tr><td><a onclick=\"eo_Callback('cpTeamSummary', 'WIX1200'); return false;\">Sample</a></td>"
            "<td>Sample Club</td><td>WI</td></tr>"
            "</table>"
        )
        assert SincSportsEventsScraper.parse_teamlist(html) == []
