"""
Tests for Club Name Normalization

Tests the club normalizer module's ability to reliably map
messy club name strings to canonical club_id / club_norm.
"""

from collections import defaultdict

import pytest

from src.utils.club_normalizer import (
    CANONICAL_CLUBS,
    SHARED_CLUB_NAMES,
    _core_and_codes,
    _light_form,
    _signature,
    _word_set_similarity,
    are_same_club,
    group_by_club,
    lookup_canonical,
    normalize_club_name,
    normalize_to_club,
    similarity_score,
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
        assert normalize_club_name("ATL United") == "atlanta united"

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
        assert normalize_club_name("D.C. United") == "washington dc united"
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
        assert normalize_club_name("ALBION SC Las Vegas U13 HD") == "albion sc las vegas"
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

    def test_misspelt_club_is_not_matched_to_the_registry(self):
        """A typo is not fuzzy-matched to a canonical club."""
        result = normalize_to_club("Pheonix Rising")
        assert (result.club_norm, result.matched_canonical, result.confidence) == ("PHEONIX RISING", False, 0.8)

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
            assert result.club_norm == expected_canonical, (
                f"'{input_name}' -> '{result.club_norm}', expected '{expected_canonical}'"
            )
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
            assert result.club_norm == expected_canonical, (
                f"'{input_name}' -> '{result.club_norm}', expected '{expected_canonical}'"
            )

    @pytest.mark.parametrize(
        "name, expected",
        [
            ("FC Dallas", "FC DALLAS"),
            ("Charlotte FC", "CHARLOTTE FC"),
            ("Solar SC", "SOLAR SC"),
            ("LA Galaxy", "LA GALAXY"),
            ("Phoenix Rising Soccer Club", "PHOENIX RISING"),
            ("Los Angeles Soccer Club", "LOS ANGELES SC"),
            ("FC United", "FC UNITED"),
            ("Dallas Hornets", "DALLAS HORNETS"),
            ("Cedar Stars Academy", "CEDAR STARS ACADEMY"),
            ("Bavarian SC", "BAVARIAN UNITED"),
            ("Bavarian Soccer Club", "BAVARIAN UNITED"),
        ],
    )
    def test_registered_name_is_an_exact_match(self, name, expected):
        result = normalize_to_club(name)
        assert (result.club_norm, result.matched_canonical, result.confidence) == (expected, True, 1.0)

    @pytest.mark.parametrize(
        "name",
        [
            "Albion SC San Diego",
            "Strikers FC - Irvine",
            "Real Salt Lake Arizona South",
            "Solar Scorpions",
            "Dallas Hornets East",
            "Dallas Hornets North",
            "Cedar Stars Academy Bergen",
            "Cedar Stars Academy Monmouth",
            "Cedar Stars Academy Newark",
            "St Louis Scott Gallagher Illinois",
            "SLSG Illinois",
            "RSL Arizona Mesa",
            "PDA Hibernian",
        ],
    )
    def test_a_name_that_only_begins_with_a_registered_club_is_not_that_club(self, name):
        """A branch fields its own squads, so it keeps its own name rather than its parent's."""
        result = normalize_to_club(name)
        assert (result.matched_canonical, result.confidence) == (False, 0.8)

    @pytest.mark.parametrize(
        "name",
        [
            # A place, a generic soccer word, or a word many clubs share
            "Dallas",
            "Fusion",
            "Surf",
            "Kansas City Comets",
            "Columbus SC",
            "Houston Football Club",
            "Galaxy SC",
            "New England Force",
            "New England FC",
            "Dallas FC",
            # An alias whose city abbreviation spells a removed name ("dallas fc")
            "DAL FC",
            # Canonical names that are one shared word get no bare key
            "Barcelona",
            "Crossfire",
            "Lamorinda",
            # A registered name followed by more words is not that club
            "Silicon Valley Eagles",
            "FC Dallas Red",
            "Club Ohio West",
            # Names a fuzzy or suffix-stripped lookup files under a different club
            "NC Fusion",
            "NCFC",
            "Asheville Football Club",
            "Charlotte Soccer Academy",
            "Impact Futbol Club",
            # A name that only ends with a registered one
            "NY Hota Bavarian Soccer Club",
        ],
    )
    def test_shared_or_unregistered_name_is_not_canonical(self, name):
        result = normalize_to_club(name)
        assert (result.matched_canonical, result.confidence) == (False, 0.8)


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

    def test_suffix_is_part_of_the_key(self):
        """Two clubs that differ only by their suffix do not share a key."""
        assert lookup_canonical("Charlotte FC") == "CHARLOTTE FC"
        assert lookup_canonical("Charlotte Soccer Academy") is None

    def test_exact_only(self):
        assert lookup_canonical("Albion SC San Diego") is None


class TestRegistry:
    """The reverse lookup built from CANONICAL_CLUBS"""

    def test_no_light_form_key_is_claimed_by_two_clubs(self):
        shared_keys = {_light_form(name) for name in SHARED_CLUB_NAMES}
        claims = defaultdict(set)
        for canonical, variations in CANONICAL_CLUBS.items():
            for name in [canonical.lower(), *variations]:
                key = _light_form(name)
                if key not in shared_keys:
                    claims[key].add(canonical)
        assert {key: clubs for key, clubs in claims.items() if len(clubs) > 1} == {}

    def test_barca_residency_stays_with_its_own_club(self):
        assert normalize_to_club("Barca Residency").club_norm == "BARCA RESIDENCY ACADEMY"


class TestNameForms:
    """The light form, core and signature that club comparison reads"""

    @pytest.mark.parametrize(
        "name, expected",
        [
            ("Charlotte Soccer Academy", "charlotte sa"),
            ("Charlotte FC", "charlotte fc"),
            ("East Sacramento Youth Soccer Club", "east sacramento ysc"),
            ("Frisco Soccer Association", "frisco sa"),
            ("Frisco Soccer Assn", "frisco sa"),
            ("Legends Futbol Academy", "legends fa"),
            ("Legends Football Academy", "legends fa"),
            ("Legends Football Club", "legends fc"),
            ("Sporting Athletic Club", "sporting ac"),
            ("DAL FC", "dallas fc"),
        ],
    )
    def test_light_form(self, name, expected):
        assert _light_form(name) == expected

    @pytest.mark.parametrize(
        "name, expected",
        [
            ("Charlotte Soccer Academy", ("charlotte", frozenset({"sa"}))),
            ("FC Dallas", ("dallas", frozenset({"fc"}))),
            ("Club Ohio Soccer", ("ohio", frozenset())),
            ("FC", ("fc", frozenset())),
        ],
    )
    def test_core_and_codes(self, name, expected):
        assert _core_and_codes(name) == expected

    @pytest.mark.parametrize(
        "name, expected",
        [
            ("FC Arkansas", "club arkansas"),
            ("Arkansas Soccer Club", "arkansas club"),
            ("East Sacramento Youth Soccer Club", "east sacramento club"),
        ],
    )
    def test_signature(self, name, expected):
        assert _signature(name) == expected


class TestWordSetSimilarity:
    """The score similarity_score gives two different cores no earlier rule decides"""

    @pytest.mark.parametrize(
        "name1, name2, expected",
        [
            # Word order and case do not matter; spelling does
            ("Rising Pheonix", "phoenix rising", 0.9286),
            # One shared word in three outscores the letters the words have in common
            ("red thunder", "red academy", 0.3333),
            ("", "", 0.0),
        ],
    )
    def test_word_set_similarity(self, name1, name2, expected):
        assert _word_set_similarity(name1, name2) == pytest.approx(expected, abs=1e-4)


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

    def test_place_only_core_needs_equal_signatures(self):
        assert similarity_score("FC Arkansas", "Arkansas Soccer Club") == 0.0
        assert similarity_score("FC San Jose", "San Jose SC") == 0.0
        assert similarity_score("Club Ohio", "Club Ohio Soccer") == 1.0

    @pytest.mark.parametrize(
        "name1, name2",
        [
            ("East Sacramento SC", "Real Sacramento Futbol Club"),
            ("Real Sacramento Futbol Club", "East Sacramento SC"),
        ],
    )
    def test_place_only_core_on_either_side(self, name1, name2):
        """Word-set similarity alone would pair these two clubs"""
        assert similarity_score(name1, name2) == 0.0

    def test_short_single_word_cores_must_be_equal(self):
        assert similarity_score("NCFC", "NYCFC") == 0.0

    def test_short_word_rule_reads_the_shorter_core_at_five_letters(self):
        """The shorter core decides: "storm" is five letters and "stormy" six"""
        assert similarity_score("Storm FC", "Stormy FC") == 0.0
        assert are_same_club("Storm FC", "Stormy FC") is False

    @pytest.mark.parametrize(
        "name1, name2",
        [
            ("Oregon Rush", "Rush SC"),
            ("Rush SC", "Oregon Rush"),
        ],
    )
    def test_short_word_against_a_longer_core_keeps_word_similarity(self, name1, name2):
        """The short-word rule needs both cores to be one word"""
        assert similarity_score(name1, name2) == pytest.approx(0.5333, abs=1e-4)

    def test_short_single_word_cores_that_are_equal_still_match(self):
        assert similarity_score("Tyler FC", "Tyler Soccer Club") == 1.0

    def test_longer_single_word_cores_keep_word_similarity(self):
        assert are_same_club("Legends FC", "Legend FC") is True

    def test_equal_cores_with_codes_of_different_families(self):
        assert similarity_score("Tyler FC", "Tyler SA") == 0.0
        assert similarity_score("East Sacramento SC", "East Sacramento Youth Soccer Club") == 1.0

    @pytest.mark.parametrize(
        "name1, name2",
        [
            ("Oregon Surf SC", "Oregon Surf"),
            ("Oregon Surf", "Oregon Surf SC"),
        ],
    )
    def test_equal_cores_with_a_code_on_one_side(self, name1, name2):
        assert similarity_score(name1, name2) == 1.0

    @pytest.mark.parametrize(
        "name1, name2",
        [
            ("Legends Youth Soccer", "Legends FC"),
            ("Legends FC", "Legends Youth Soccer"),
        ],
    )
    def test_youth_code_counts_as_club(self, name1, name2):
        assert similarity_score(name1, name2) == 1.0


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

    @pytest.mark.parametrize(
        "name1, name2",
        [
            ("NCFC", "NYCFC"),
            ("FC Arkansas", "Arkansas Soccer Club"),
            ("Club Ohio", "Ohio Soccer Association"),
            ("Legends FC", "Legends Futbol Academy"),
            ("Legends Football Club", "Legends Futbol Academy"),
            ("Legends Football Academy", "Legends FC"),
            ("Charlotte FC", "Charlotte Soccer Academy"),
            ("Tyler FC", "Tyler SA"),
            ("AC Dallas Soccer", "FC Dallas"),
            ("FC Dallas Red", "FC Dallas"),
            ("Galaxy SC", "LA Galaxy"),
            ("FC Portland", "Rogue Valley Timbers"),
            ("Cascade Surf", "Oregon Surf"),
            ("Vancouver West SC", "Vancouver Lightning"),
            ("FC Portland", "Portland City United SC"),
            ("NC Fusion", "Ventura County Fusion"),
            ("Asheville Football Club", "Nashville SC"),
            ("Impact Futbol Club", "CF Montreal"),
            ("Dallas Texans", "FC Dallas"),
            ("Philadelphia Union", "Union Soccer Club"),
            ("Atlanta Fire United", "Atlanta United"),
            ("San Diego FC", "San Diego Force FC"),
            ("East Sacramento SC", "Real Sacramento Futbol Club"),
            # Branches of one club field their own squads
            ("Albion SC San Diego", "Albion SC Colorado"),
            ("Strikers FC - Irvine", "Strikers FC North"),
            ("Dallas Hornets East", "Dallas Hornets North"),
            ("Cedar Stars Academy Bergen", "Cedar Stars Academy Monmouth"),
        ],
    )
    def test_clubs_sharing_a_word_are_different(self, name1, name2):
        assert are_same_club(name1, name2) is False

    @pytest.mark.parametrize(
        "name1, name2",
        [
            ("Club Ohio", "Club Ohio Soccer"),
            ("East Sacramento SC", "East Sacramento Youth Soccer Club"),
            ("Strikers FC", "Strikers SC"),
            ("Oregon Surf", "Oregon Surf SC"),
            ("Phoenix Rising FC", "PHX Rising"),
            ("Solar SC", "Solar Soccer Club"),
            ("Frisco SA", "Frisco Soccer Association"),
            ("Frisco Soccer Assn", "Frisco Soccer Association"),
            ("Pheonix Rising", "Phoenix Rising"),
            ("Bavarian SC", "Bavarian United"),
        ],
    )
    def test_spellings_of_one_club_are_the_same(self, name1, name2):
        assert are_same_club(name1, name2) is True

    def test_names_with_nothing_outside_brackets_are_not_one_club(self):
        assert are_same_club("(ABC)", "[XYZ]") is False


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
        """ALBION SC's branches keep their own names, and no two are one club"""
        base = normalize_to_club("ALBION SC")
        assert (base.club_norm, base.confidence) == ("ALBION SC", 1.0)

        branches = ["ALBION SC Las Vegas", "ALBION SC Denver", "ALBION SC Colorado", "ALBION SC Los Angeles"]
        for branch in branches:
            assert normalize_to_club(branch).matched_canonical is False, branch
        for i, first in enumerate(branches):
            for second in branches[i + 1 :]:
                assert are_same_club(first, second) is False, (first, second)

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
        """A one-word name many clubs share is normalized, not filed under a canonical club"""
        result = normalize_to_club("Surf")
        assert (result.club_norm, result.club_id, result.matched_canonical) == ("SURF", "surf", False)

    def test_numeric_in_name(self):
        """Test club names with numbers"""
        result = normalize_to_club("One FC")
        assert result.club_norm == "ONE FC"
        assert result.club_id is not None

    def test_very_short_name(self):
        """Test very short club names"""
        result = normalize_to_club("FC")
        assert (result.club_norm, result.matched_canonical) == ("FC", False)

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
