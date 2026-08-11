"""Unit tests for the shared club-name canonical override registry.

Two layers:
1. Direct semantics on ``canonicalize_club_name`` — case-insensitive,
   per-state lookup, cross-state safe fallback, no-match passthrough.
2. Backwards-compatibility check that the legacy in-script
   ``_matches_override`` symbol in ``scripts/full_club_analysis.py``
   still resolves (via re-export) and produces identical decisions.
"""

from __future__ import annotations

import pytest

from src.utils.club_canonical_overrides import (
    CLUB_CANONICAL_OVERRIDES,
    canonicalize_club_name,
    matches_override,
)


class TestCanonicalizeStateSpecific:
    @pytest.mark.parametrize(
        "state,raw,expected",
        [
            ("CA", "Mustang SC", "Mustang Soccer"),
            ("CA", "mvla", "Mountain View Los Altos Soccer Club"),
            ("CA", "mvla soccer club", "Mountain View Los Altos Soccer Club"),
            ("CA", "San Diego Surf", "San Diego Surf Soccer Club"),
            ("CA", "LAFC SOCAL", "Los Angeles FC"),
            ("CA", "bakersfield alliance s c", "bakersfield alliance"),
            ("WA", "XF", "Crossfire Premier"),
            ("WA", "XL", "Crossfire Select Soccer Club"),
            ("WA", "PacNW", "Pacific Northwest SC"),
            ("AZ", "RSL-AZ", "RSL Arizona"),
            ("AZ", "RSL-AZ North", "RSL Arizona North"),
            ("AZ", "ARIZONA ARSENAL", "Arizona Arsenal Soccer Club"),
        ],
    )
    def test_state_exact_match(self, state, raw, expected):
        assert canonicalize_club_name(state, raw) == expected

    @pytest.mark.parametrize(
        "state,raw,expected",
        [
            ("CA", "MUSTANG SC", "Mustang Soccer"),
            ("CA", "mustang sc", "Mustang Soccer"),
            ("WA", "xf", "Crossfire Premier"),
        ],
    )
    def test_case_insensitive_exact(self, state, raw, expected):
        assert canonicalize_club_name(state, raw) == expected

    def test_trailing_whitespace_stripped(self):
        assert canonicalize_club_name("CA", "Mustang SC ") == "Mustang Soccer"
        assert canonicalize_club_name("CA", "  Mustang SC  ") == "Mustang Soccer"

    def test_regex_match(self):
        # CA: r"Beach FC\s+\(CA\)\s*$" → "Beach Futbol Club"
        assert canonicalize_club_name("CA", "Beach FC (CA)") == "Beach Futbol Club"
        # Trailing whitespace tolerated by the regex
        assert canonicalize_club_name("CA", "Beach FC (CA)   ") == "Beach Futbol Club"

    def test_prefix_match(self):
        # WA: prefix "NW United" → "Northwest United FC"
        assert canonicalize_club_name("WA", "NW United Eagles 2011") == "Northwest United FC"
        assert canonicalize_club_name("WA", "nw united") == "Northwest United FC"

    def test_no_match_returns_input(self):
        assert canonicalize_club_name("CA", "Totally Unknown Club") == "Totally Unknown Club"
        assert canonicalize_club_name("XX", "Mustang SC") == "Mustang SC"  # unknown state

    def test_per_state_isolation(self):
        # FC Stars is IL-specific → IL hits canonical, TX doesn't.
        assert canonicalize_club_name("IL", "FC Stars") == "FC Stars (il)"
        assert canonicalize_club_name("TX", "FC Stars") == "FC Stars"

    def test_state_code_normalized_to_uppercase(self):
        # The helper should treat lowercase state codes the same as uppercase.
        assert canonicalize_club_name("ca", "Mustang SC") == "Mustang Soccer"


class TestCanonicalizeCrossStateSafe:
    """``state_code=None`` should only apply overrides whose ``(match_type,
    pattern)`` resolves to one canonical across all states."""

    def test_aZ_only_pattern_resolves(self):
        # RSL-AZ exists only in AZ → safe to apply without state context.
        assert canonicalize_club_name(None, "RSL-AZ") == "RSL Arizona"
        assert canonicalize_club_name("", "RSL-AZ") == "RSL Arizona"

    def test_ca_only_pattern_resolves(self):
        # MVLA exists only in CA → safe.
        assert canonicalize_club_name(None, "mvla") == "Mountain View Los Altos Soccer Club"

    def test_pattern_only_in_one_state_resolves(self):
        # WA's XF is unique to WA → safe.
        assert canonicalize_club_name(None, "XF") == "Crossfire Premier"


class TestEmptyInputs:
    def test_empty_raw_name_returns_empty(self):
        assert canonicalize_club_name("CA", "") == ""

    def test_none_state_with_unknown_name(self):
        assert canonicalize_club_name(None, "Unknown Club") == "Unknown Club"


class TestMatchesOverridePrimitive:
    """The exposed ``matches_override`` helper preserves
    ``_matches_override`` semantics from the legacy in-script version."""

    def test_exact_case_insensitive(self):
        assert matches_override("XF", "exact", "XF") is True
        assert matches_override("xf", "exact", "XF") is True
        assert matches_override("XF ", "exact", "XF") is True
        assert matches_override("XFB", "exact", "XF") is False

    def test_prefix(self):
        assert matches_override("NW United Eagles", "prefix", "NW United") is True
        assert matches_override("United NW", "prefix", "NW United") is False

    def test_regex(self):
        pat = r"Beach FC\s+\(CA\)\s*$"
        assert matches_override("Beach FC (CA)", "regex", pat) is True
        assert matches_override("Beach FC (VA)", "regex", pat) is False

    def test_empty_club_returns_false(self):
        assert matches_override("", "exact", "XF") is False
        assert matches_override(None, "exact", "XF") is False

    def test_unknown_match_type_returns_false(self):
        assert matches_override("XF", "fuzzy", "XF") is False


class TestRegistryIntegrity:
    def test_total_override_count(self):
        # Guardrail: the count should match the legacy inline list. If you
        # add or remove an override, update this number.
        assert len(CLUB_CANONICAL_OVERRIDES) == 487

    def test_no_duplicate_full_tuples(self):
        seen = set()
        for entry in CLUB_CANONICAL_OVERRIDES:
            assert entry not in seen, f"duplicate override: {entry}"
            seen.add(entry)

    def test_each_entry_is_four_tuple(self):
        for entry in CLUB_CANONICAL_OVERRIDES:
            assert len(entry) == 4
            state, mtype, pattern, canonical = entry
            assert isinstance(state, str) and len(state) == 2
            assert mtype in ("exact", "prefix", "regex")
            assert isinstance(pattern, str) and pattern
            assert isinstance(canonical, str) and canonical


class TestLegacyReExport:
    """``scripts/full_club_analysis.py`` re-exports the shared symbols. Tests
    here guarantee the legacy entrypoints didn't silently break."""

    def test_script_module_loads(self):
        import scripts.full_club_analysis as fca

        assert hasattr(fca, "CLUB_CANONICAL_OVERRIDES")
        assert hasattr(fca, "_matches_override")
        assert len(fca.CLUB_CANONICAL_OVERRIDES) == 487

    def test_script_matches_override_decisions(self):
        import scripts.full_club_analysis as fca

        # The script's _matches_override is the shared module's
        # matches_override. Same decisions, same identity.
        assert fca._matches_override is matches_override
        assert fca._matches_override("XF", "exact", "XF") is True
        assert fca._matches_override("Beach FC (CA)", "regex", r"Beach FC\s+\(CA\)\s*$") is True
