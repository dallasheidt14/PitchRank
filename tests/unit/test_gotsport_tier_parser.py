"""Unit tests for the pure helpers in ``src.scrapers.gotsport_tier_parser``.

Pure-function tests only — no fixtures bigger than a synthetic snippet,
no network. Mirrors the layout of ``tests/unit/test_sincsports_schedule.py``:
class-grouped tests with a per-class focus.

The fixture-driven (real-event HTML) coverage lives in
``test_gotsport_tier_parser_fixtures.py``; orchestrator state-machine
coverage in ``test_gotsport_tier_orchestrator.py``.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from src.scrapers.gotsport_tier_parser import (
    EventTeamMembershipCollisionError,
    RawTierLabel,
    extract_tier_catalog,
    parse_cohort_identity,
    parse_team_ids_from_subpage,
    strip_cohort_prefix,
)
from src.utils import team_utils

FIXTURES = Path(__file__).parent.parent / "fixtures" / "gotsport"


class TestStripCohortPrefix:
    @pytest.mark.parametrize(
        "label,expected_prefix,expected_residue",
        [
            # Form 1 — standard U-prefix
            ("U13 Boys Red", "U13 Boys ", "Red"),
            ("U10 Girls Tolkin", "U10 Girls ", "Tolkin"),
            # Form 2 — hyphenated uppercase
            ("U-13 BOYS GOLD", "U-13 BOYS ", "GOLD"),
            # Form 3 — bare U-token (no gender suffix), with residue
            ("U12 Red", "U12 ", "Red"),
            # Form 4 — birth-year (with residue)
            ("B2017 Gold", "B2017 ", "Gold"),
            ("B2010/11 Silver", "B2010/11 ", "Silver"),
            # Form 5 — reverse-token
            ("12U Boys Red", "12U Boys ", "Red"),
            ("11U BOYS GOLD A DIVISION", "11U BOYS ", "GOLD A DIVISION"),
            # Form 5 slash variant — the 17/19U form on event 49407
            ("17/19U BOYS GOLD DIVISION", "17/19U BOYS ", "GOLD DIVISION"),
            # Form 7 — explicit second-U
            ("U16/U15 Girls Reyna", "U16/U15 Girls ", "Reyna"),
            # Form 7 — implicit second-U (event 42433)
            ("U18/19 Girls Blue", "U18/19 Girls ", "Blue"),
            # Form 9 — lowercase variant
            ("u13 boys gold", "u13 boys ", "gold"),
            # Form 10 — high school
            ("Varsity Boys Red", "Varsity Boys ", "Red"),
            # Form 11 — glued U-prefix + gender
            ("U10B Premier", "U10B ", "Premier"),
            # Format-token suffix stripped
            ("B2017 Gold (4v4)", "B2017 ", "Gold"),
            ("U12 Red (10v10)", "U12 ", "Red"),
            # Double whitespace tolerated (44692 has "B2017  Bronze")
            ("B2017  Bronze", "B2017  ", "Bronze"),
        ],
    )
    def test_matched_forms(self, label, expected_prefix, expected_residue):
        prefix, residue, outcome = strip_cohort_prefix(label)
        assert prefix == expected_prefix
        assert residue == expected_residue
        assert outcome == "matched"

    @pytest.mark.parametrize(
        "label,expected_prefix",
        [
            ("U10", "U10"),
            ("U12B", "U12B"),
        ],
    )
    def test_empty_residue(self, label, expected_prefix):
        prefix, residue, outcome = strip_cohort_prefix(label)
        assert prefix == expected_prefix
        assert residue == ""
        assert outcome == "empty_residue"

    def test_unknown_prefix_returns_full_text_as_residue(self):
        prefix, residue, outcome = strip_cohort_prefix("Adult Co-Ed Hammer")
        assert prefix == ""
        assert residue == "Adult Co-Ed Hammer"
        assert outcome == "unknown_prefix"

    def test_unknown_cohort_prefix_logs_warning(self, caplog):
        # Logger-scoped per ``test_bulk_ops.py:97-99`` idiom.
        caplog.set_level(logging.WARNING, logger="src.scrapers.gotsport_tier_parser")
        _, residue, outcome = strip_cohort_prefix("Adult Co-Ed Hammer")
        assert outcome == "unknown_prefix"
        assert any(
            "unknown_cohort_prefix" in r.message
            for r in caplog.records
            if r.levelno == logging.WARNING
        )


class TestParseCohortIdentity:
    @pytest.mark.parametrize(
        "prefix,expected",
        [
            # Form 1/2/9 standard
            ("U13 Boys ", ("u13", "M")),
            ("U13 Girls ", ("u13", "F")),
            ("U10 Co-Ed ", ("u10", None)),
            ("u13 boys ", ("u13", "M")),  # lowercase
            ("U-13 BOYS ", ("u13", "M")),  # uppercase + hyphen
            # U18 → U19 merge
            ("U18 Boys ", ("u19", "M")),
            # Form 5 reverse-token + multi-word residue handled upstream
            ("12U Boys ", ("u12", "M")),
            ("11U BOYS ", ("u11", "M")),
            # Form 5 slash variant
            ("17/19U BOYS ", ("u17", "M")),
            # Form 7 explicit second-U + younger picked
            ("U16/U15 Girls ", ("u15", "F")),
            # Form 7 implicit second-U + U18 merge
            ("U18/19 Girls ", ("u19", "F")),
            # Form 11 glued
            ("U10B ", ("u10", "M")),
            ("U12G ", ("u12", "F")),
        ],
    )
    def test_recognized_forms(self, prefix, expected):
        assert parse_cohort_identity(prefix) == expected

    def test_int_min_not_lex_min(self):
        # CRITICAL: lex-min would return ``"16"`` (since ``"1" < "9"``); int-min
        # returns ``"9"``. This is the discriminator from
        # ``gotcha_slash_age_tokens.md``.
        assert parse_cohort_identity("U16/U9 Girls ") == ("u9", "F")

    def test_hs_form_returns_none(self):
        assert parse_cohort_identity("Varsity Boys ") is None

    def test_birth_year_uses_module_level_current_year(self, monkeypatch):
        # CRITICAL: this enforces the module-style ``team_utils.CURRENT_YEAR``
        # import. If the parser had imported ``CURRENT_YEAR`` directly via
        # ``from team_utils import CURRENT_YEAR``, this monkeypatch would not
        # affect ``parse_cohort_identity`` and the test would silently flip
        # truth value depending on the calendar date.
        monkeypatch.setattr(team_utils, "CURRENT_YEAR", 2025)
        # 2025 - 2017 + 1 = 9 → "u9"
        assert parse_cohort_identity("B2017 ") == ("u9", "M")
        # 2025 - 2014 + 1 = 12 → "u12"
        assert parse_cohort_identity("G2014 ") == ("u12", "F")

    def test_birth_year_below_band_returns_none(self, monkeypatch):
        monkeypatch.setattr(team_utils, "CURRENT_YEAR", 2025)
        # 2025 - 2024 + 1 = 2 → out of band
        assert parse_cohort_identity("B2024 ") is None


class TestExtractTierCatalog:
    def test_dedupes_schedule_results_pairs(self):
        # Schedule + Results anchors share gid + label — first wins.
        html = """
        <div><div>
          <b>U13 Boys Red</b>
          <a href="/org_event/events/99/schedules?group=42">Schedule</a>
          <a href="/org_event/events/99/results?group=42">Results</a>
        </div></div>
        """
        soup = BeautifulSoup(html, "html.parser")
        catalog = extract_tier_catalog(soup, event_id="99")
        # Only one anchor matches GROUP_ANCHOR_HREF_RE (results URL doesn't);
        # but if both matched the same gid + sig, dedup wins. Verify by gid.
        assert 42 in catalog
        assert catalog[42].cohort_age_group == "u13"
        assert catalog[42].tier_residue == "Red"

    def test_filters_schedule_results_label_literals(self):
        # Anchors whose sibling-<b> reads "Schedule" or "Results" are noise.
        html = """
        <div><div>
          <b>Schedule</b>
          <a href="/org_event/events/99/schedules?group=42">Click here</a>
        </div></div>
        """
        soup = BeautifulSoup(html, "html.parser")
        catalog = extract_tier_catalog(soup, event_id="99")
        assert catalog == {}

    def test_skips_anchor_without_row_parent(self):
        # An anchor at the document root (no parent.parent) is silently skipped.
        html = '<a href="/schedules?group=42">x</a>'
        soup = BeautifulSoup(html, "html.parser")
        # No exception, just empty catalog.
        catalog = extract_tier_catalog(soup, event_id="99")
        assert catalog == {}

    def test_preserves_mixed_case_residue(self):
        html = """
        <div><div>
          <b>U13 Boys RED</b>
          <a href="/schedules?group=7">Schedule</a>
        </div></div>
        """
        soup = BeautifulSoup(html, "html.parser")
        catalog = extract_tier_catalog(soup, event_id="99")
        assert catalog[7].raw_label == "U13 Boys RED"
        assert catalog[7].tier_residue == "RED"

    def test_forward_collision_raises_typed(self):
        # Same gid, different labels → forward collision.
        html = """
        <div><div>
          <b>U13 Boys Gold</b>
          <a href="/schedules?group=42">Schedule</a>
        </div></div>
        <div><div>
          <b>U13 Boys Silver</b>
          <a href="/schedules?group=42">Schedule</a>
        </div></div>
        """
        soup = BeautifulSoup(html, "html.parser")
        with pytest.raises(EventTeamMembershipCollisionError) as excinfo:
            extract_tier_catalog(soup, event_id="99")
        err = excinfo.value
        assert err.mode == "forward"
        assert err.group_id == 42
        assert err.event_id == "99"
        # conflicting_tier_residues carries both residues, in the order encountered.
        assert "Gold" in err.conflicting_tier_residues
        assert "Silver" in err.conflicting_tier_residues


class TestParseTeamIdsFromSubpage:
    def test_extracts_distinct_team_ids(self):
        html = """
        <a href="/org_event/teams/100?team=100">A</a>
        <a href="/org_event/teams/200?team=200">B</a>
        <a href="/org_event/teams/300?team=300">C</a>
        """
        ids = parse_team_ids_from_subpage(html)
        assert ids == {"100", "200", "300"}

    def test_dedupes_repeated_ids(self):
        html = """
        <a href="?team=42">A</a>
        <a href="?team=42">A again</a>
        <a href="?team=99">B</a>
        """
        ids = parse_team_ids_from_subpage(html)
        assert ids == {"42", "99"}

    def test_empty_html_returns_empty_set(self):
        assert parse_team_ids_from_subpage("") == set()
        assert parse_team_ids_from_subpage("<html></html>") == set()


class TestRawTierLabel:
    def test_is_frozen_dataclass(self):
        # Provenance dataclasses must be frozen so we can put them in
        # dicts/sets safely.
        label = RawTierLabel(
            group_id=1,
            raw_label="U13 Boys Red",
            cohort_age_group="u13",
            cohort_gender="M",
            tier_residue="Red",
            parse_outcome="matched",
        )
        with pytest.raises((AttributeError, Exception)):
            label.tier_residue = "Blue"  # type: ignore[misc]

    def test_load_synthetic_inverse_collision_landing(self):
        # Sanity check the synthetic landing fixture parses cleanly into a
        # 2-entry catalog that the orchestrator test will consume.
        path = FIXTURES / "event_synthetic_inverse_collision.html"
        soup = BeautifulSoup(path.read_text(encoding="utf-8"), "html.parser")
        catalog = extract_tier_catalog(soup, event_id="inverse")
        assert set(catalog.keys()) == {1001, 1002}
        assert catalog[1001].tier_residue == "Gold"
        assert catalog[1002].tier_residue == "Silver"
        assert catalog[1001].cohort_age_group == "u13"
