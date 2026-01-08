"""
Tests for Club Name Normalization

Tests the club normalizer module's ability to reliably map
messy club name strings to canonical club_id / club_norm.
"""

import pytest
from src.utils.club_normalizer import (
    normalize_club_name,
    normalize_to_club,
    lookup_canonical,
    fuzzy_match_canonical,
    similarity_score,
    are_same_club,
    group_by_club,
    add_canonical_club,
    ClubNormResult,
)


class TestNormalizeClubName:
    """Tests for the normalize_club_name function"""

    def test_basic_normalization(self):
        """Test basic lowercasing and whitespace normalization"""
        assert normalize_club_name("Phoenix Rising") == "phoenix rising"
        assert normalize_club_name("  Phoenix  Rising  ") == "phoenix rising"
        assert normalize_club_name("PHOENIX RISING") == "phoenix rising"

    def test_suffix_removal(self):
        """Test removal of common suffixes (FC, SC, SA, etc.)"""
        assert normalize_club_name("Phoenix Rising FC") == "phoenix rising"
        assert normalize_club_name("Phoenix Rising SC") == "phoenix rising"
        assert normalize_club_name("Phoenix Rising SA") == "phoenix rising"
        assert normalize_club_name("Phoenix Rising Soccer Club") == "phoenix rising"
        assert normalize_club_name("Phoenix Rising Football Club") == "phoenix rising"
        assert normalize_club_name("Phoenix Rising Academy") == "phoenix rising"

    def test_prefix_removal(self):
        """Test removal of common prefixes (FC, CF, etc.)"""
        assert normalize_club_name("FC Dallas") == "dallas"
        assert normalize_club_name("CF Barcelona") == "barcelona"
        assert normalize_club_name("AC Milan") == "milan"

    def test_city_abbreviation_expansion(self):
        """Test expansion of city abbreviations"""
        assert normalize_club_name("PHX Rising") == "phoenix rising"
        assert normalize_club_name("LA Galaxy") == "los angeles galaxy"
        assert normalize_club_name("NYC FC") == "new york city"
        assert normalize_club_name("ATL United") == "atlanta"

    def test_location_suffix_removal(self):
        """Test removal of location suffixes like '- AZ'"""
        assert normalize_club_name("Phoenix Rising - AZ") == "phoenix rising"
        assert normalize_club_name("LA Galaxy - CA") == "los angeles galaxy"
        assert normalize_club_name("Solar SC - Texas") == "solar"
        assert normalize_club_name("Team Name - California") == "team name"

    def test_age_group_removal(self):
        """Test removal of age group patterns"""
        assert normalize_club_name("Phoenix Rising U13") == "phoenix rising"
        assert normalize_club_name("Phoenix Rising U-14") == "phoenix rising"
        assert normalize_club_name("Phoenix Rising U13 Boys") == "phoenix rising"
        assert normalize_club_name("Phoenix Rising 2012") == "phoenix rising"
        assert normalize_club_name("Phoenix Rising U13 HD") == "phoenix rising"
        assert normalize_club_name("Phoenix Rising U13 AD") == "phoenix rising"

    def test_punctuation_removal(self):
        """Test removal of punctuation"""
        assert normalize_club_name("Phoenix Rising F.C.") == "phoenix rising"
        assert normalize_club_name("D.C. United") == "dc"
        assert normalize_club_name("Phoenix Rising!") == "phoenix rising"

    def test_combined_normalization(self):
        """Test multiple normalizations combined"""
        # Full example from requirements
        variations = [
            "Phoenix Rising",
            "Phoenix Rising FC",
            "PHX Rising",
            "Phoenix Rising Soccer Club",
            "Phoenix Rising - AZ",
        ]
        expected = "phoenix rising"
        for v in variations:
            result = normalize_club_name(v)
            assert result == expected, f"'{v}' normalized to '{result}', expected '{expected}'"

    def test_complex_club_names(self):
        """Test normalization of complex real-world club names"""
        assert normalize_club_name("ALBION SC Las Vegas U13 HD") == "albion las vegas"
        assert normalize_club_name("Global Football Innovation Academy U13 HD") == "global football innovation"
        assert normalize_club_name("FC Bay Area Surf U13 HD") == "bay area surf"
        assert normalize_club_name("Michigan Jaguars U13 HD") == "michigan jaguars"

    def test_empty_and_none(self):
        """Test handling of empty and None values"""
        assert normalize_club_name("") == ""
        assert normalize_club_name("   ") == ""
        assert normalize_club_name(None) == ""


class TestNormalizeToClub:
    """Tests for the normalize_to_club function (main entry point)"""

    def test_exact_canonical_match(self):
        """Test exact match to canonical club registry"""
        result = normalize_to_club("Phoenix Rising FC")
        assert result.club_norm == "PHOENIX RISING"
        assert result.club_id == "phoenix_rising"
        assert result.matched_canonical is True
        assert result.confidence == 1.0

    def test_abbreviation_to_canonical(self):
        """Test abbreviation expands to canonical match"""
        result = normalize_to_club("PHX Rising")
        assert result.club_norm == "PHOENIX RISING"
        assert result.club_id == "phoenix_rising"
        assert result.matched_canonical is True

    def test_fuzzy_canonical_match(self):
        """Test fuzzy matching to canonical club"""
        result = normalize_to_club("Pheonix Rising")  # Typo
        # Should still match to Phoenix Rising with lower confidence
        assert result.club_norm == "PHOENIX RISING"
        assert result.matched_canonical is True
        assert result.confidence < 1.0

    def test_unknown_club_normalization(self):
        """Test normalization of unknown clubs"""
        result = normalize_to_club("Some Random Club FC")
        assert result.club_norm == "SOME RANDOM CLUB"
        assert result.club_id == "some_random_club"
        assert result.matched_canonical is False
        assert result.confidence > 0

    def test_result_preserves_original(self):
        """Test that original name is preserved in result"""
        original = "Phoenix Rising FC U13 Boys"
        result = normalize_to_club(original)
        assert result.original == original

    def test_mls_clubs(self):
        """Test MLS clubs are recognized"""
        test_cases = [
            ("LA Galaxy", "LA GALAXY"),
            ("Los Angeles Galaxy", "LA GALAXY"),
            ("FC Dallas", "FC DALLAS"),
            ("Seattle Sounders FC", "SEATTLE SOUNDERS"),
            ("Atlanta United", "ATLANTA UNITED"),
            ("Inter Miami CF", "INTER MIAMI"),
        ]
        for input_name, expected_canonical in test_cases:
            result = normalize_to_club(input_name)
            assert result.club_norm == expected_canonical, f"'{input_name}' -> '{result.club_norm}', expected '{expected_canonical}'"
            assert result.matched_canonical is True

    def test_youth_clubs(self):
        """Test major youth clubs are recognized"""
        test_cases = [
            ("Solar SC", "SOLAR SC"),
            ("IMG Academy", "IMG ACADEMY"),
            ("Michigan Jaguars", "MICHIGAN JAGUARS"),
            ("Beadling SC", "BEADLING SC"),
        ]
        for input_name, expected_canonical in test_cases:
            result = normalize_to_club(input_name)
            assert result.club_norm == expected_canonical, f"'{input_name}' -> '{result.club_norm}', expected '{expected_canonical}'"


class TestLookupCanonical:
    """Tests for the lookup_canonical function"""

    def test_exact_match(self):
        """Test exact variation match"""
        assert lookup_canonical("phoenix rising") == "PHOENIX RISING"
        assert lookup_canonical("phx rising") == "PHOENIX RISING"
        assert lookup_canonical("la galaxy") == "LA GALAXY"

    def test_case_insensitive(self):
        """Test lookup is case insensitive"""
        assert lookup_canonical("Phoenix Rising") == "PHOENIX RISING"
        assert lookup_canonical("PHOENIX RISING") == "PHOENIX RISING"

    def test_no_match_returns_none(self):
        """Test unrecognized names return None"""
        assert lookup_canonical("unknown club") is None
        assert lookup_canonical("random team") is None


class TestFuzzyMatchCanonical:
    """Tests for the fuzzy_match_canonical function"""

    def test_close_match(self):
        """Test close matches are found"""
        result = fuzzy_match_canonical("phoenix risng")  # Typo
        assert result is not None
        assert result[0] == "PHOENIX RISING"
        assert result[1] >= 0.85

    def test_threshold_enforcement(self):
        """Test threshold is enforced"""
        # With high threshold, loose matches fail
        result = fuzzy_match_canonical("totally different", threshold=0.95)
        assert result is None

    def test_word_reordering(self):
        """Test fuzzy match handles word reordering"""
        result = fuzzy_match_canonical("rising phoenix")
        # Token set ratio should handle this
        assert result is not None


class TestSimilarityScore:
    """Tests for the similarity_score function"""

    def test_identical_names(self):
        """Test identical names have score 1.0"""
        assert similarity_score("Phoenix Rising", "Phoenix Rising") == 1.0

    def test_normalized_identical(self):
        """Test names that normalize to same form"""
        score = similarity_score("Phoenix Rising FC", "Phoenix Rising SC")
        assert score == 1.0

    def test_similar_names(self):
        """Test similar names have high score"""
        score = similarity_score("Phoenix Rising", "Pheonix Rising")
        assert score >= 0.8

    def test_different_names(self):
        """Test different names have low score"""
        score = similarity_score("Phoenix Rising", "LA Galaxy")
        assert score < 0.5


class TestAreSameClub:
    """Tests for the are_same_club function"""

    def test_same_club_variations(self):
        """Test that variations of the same club are recognized"""
        assert are_same_club("Phoenix Rising", "Phoenix Rising FC") is True
        assert are_same_club("PHX Rising", "Phoenix Rising SC") is True
        assert are_same_club("Phoenix Rising - AZ", "Phoenix Rising Soccer Club") is True

    def test_different_clubs(self):
        """Test that different clubs are distinguished"""
        assert are_same_club("Phoenix Rising", "LA Galaxy") is False
        assert are_same_club("FC Dallas", "Solar SC") is False

    def test_canonical_clubs(self):
        """Test canonical club matching"""
        assert are_same_club("LA Galaxy", "Los Angeles Galaxy") is True
        assert are_same_club("ATL United", "Atlanta United") is True


class TestGroupByClub:
    """Tests for the group_by_club function"""

    def test_grouping(self):
        """Test that variations are grouped correctly"""
        names = [
            "Phoenix Rising FC",
            "PHX Rising",
            "Phoenix Rising Soccer Club",
            "LA Galaxy",
            "Los Angeles Galaxy",
        ]
        groups = group_by_club(names)

        # Phoenix Rising variations should be grouped
        assert "phoenix_rising" in groups
        assert len(groups["phoenix_rising"]) == 3

        # LA Galaxy variations should be grouped
        assert "la_galaxy" in groups
        assert len(groups["la_galaxy"]) == 2


class TestAddCanonicalClub:
    """Tests for the add_canonical_club function"""

    def test_add_new_club(self):
        """Test adding a new canonical club"""
        add_canonical_club("Test Club", ["test club", "tc", "test fc"])

        # Should now be recognized
        result = normalize_to_club("Test FC")
        assert result.club_norm == "TEST CLUB"
        assert result.matched_canonical is True


class TestRealWorldExamples:
    """Tests with real-world club name variations"""

    def test_phoenix_rising_all_variations(self):
        """Test all Phoenix Rising variations from requirements"""
        variations = [
            "Phoenix Rising",
            "Phoenix Rising FC",
            "PHX Rising",
            "Phoenix Rising Soccer Club",
            "Phoenix Rising - AZ",
        ]

        results = [normalize_to_club(v) for v in variations]

        # All should map to the same club
        club_ids = set(r.club_id for r in results)
        assert len(club_ids) == 1
        assert "phoenix_rising" in club_ids

        # All should have PHOENIX RISING as normalized name
        for r in results:
            assert r.club_norm == "PHOENIX RISING"

    def test_albion_regional_clubs(self):
        """Test ALBION SC with regional suffixes"""
        variations = [
            "ALBION SC",
            "ALBION SC Las Vegas",
            "ALBION SC Denver",
            "ALBION SC Colorado",
            "ALBION SC Los Angeles",
        ]

        results = [normalize_to_club(v) for v in variations]

        # Base ALBION should match canonical
        base_result = results[0]
        assert base_result.club_norm == "ALBION SC"

        # Regional variants should normalize but may not match canonical
        # since they're different clubs (ALBION LV vs ALBION Denver)
        for i, r in enumerate(results[1:], 1):
            # They should at least normalize sensibly
            assert r.club_id is not None
            assert r.club_norm is not None

    def test_scraped_data_examples(self):
        """Test examples from actual scraped data"""
        test_cases = [
            ("Sacramento United U13 HD", "sacramento_united"),
            ("Alexandria SA U13 HD", "alexandria_sa"),
            ("Michigan Jaguars U13 HD", "michigan_jaguars"),
            ("Bavarian United SC U13 HD", "bavarian_united"),
            ("Beadling SC U13 HD", "beadling_sc"),
            ("FC Bay Area Surf U13 HD", "fc_bay_area"),
            ("LA Galaxy U13 HD", "la_galaxy"),
            ("Inter Atlanta FC U13 HD", "inter_atlanta"),
        ]

        for input_name, expected_id in test_cases:
            result = normalize_to_club(input_name)
            assert result.club_id == expected_id, f"'{input_name}' -> '{result.club_id}', expected '{expected_id}'"


class TestEdgeCases:
    """Tests for edge cases and unusual inputs"""

    def test_single_word_club(self):
        """Test single word club names"""
        result = normalize_to_club("Surf")
        assert result.club_norm == "SURF"
        assert result.club_id == "surf"

    def test_numeric_in_name(self):
        """Test club names with numbers"""
        result = normalize_to_club("One FC")
        assert result.club_norm == "ONE FC"
        assert result.matched_canonical is True

    def test_very_short_name(self):
        """Test very short club names"""
        result = normalize_to_club("FC")
        # After stripping prefix, nothing left
        assert result.club_norm == ""

    def test_unicode_characters(self):
        """Test handling of unicode characters"""
        result = normalize_to_club("São Paulo FC")
        assert result.club_id is not None

    def test_all_caps_input(self):
        """Test ALL CAPS input"""
        result = normalize_to_club("PHOENIX RISING FC")
        assert result.club_norm == "PHOENIX RISING"
        assert result.matched_canonical is True

    def test_mixed_case_input(self):
        """Test MiXeD cAsE input"""
        result = normalize_to_club("pHoEnIx RiSiNg Fc")
        assert result.club_norm == "PHOENIX RISING"
