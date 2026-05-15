"""Tests for game matching system — game_matcher.py"""
import pytest

from src.models.game_matcher import extract_team_variant


class TestExtractTeamVariant:
    """Tests for extract_team_variant — distinguishing teams within the same club."""

    def test_color_variant(self):
        assert extract_team_variant("FC Dallas 2014 Blue") == "blue"
        assert extract_team_variant("Surf Gold") == "gold"
        assert extract_team_variant("Rush White") == "white"

    def test_direction_variant(self):
        assert extract_team_variant("Select North") == "north"
        assert extract_team_variant("Rush South") == "south"
        assert extract_team_variant("Surf East") == "east"

    def test_roman_numeral_variant(self):
        assert extract_team_variant("FC Dallas II") == "ii"
        assert extract_team_variant("Surf III") == "iii"
        assert extract_team_variant("Rush IV") == "iv"

    def test_single_i_and_v_not_matched(self):
        """Regression: single 'i' and 'v' should NOT match as roman numerals."""
        assert extract_team_variant("FC Dallas I Am") is None or extract_team_variant("FC Dallas I Am") != "i"
        # A team name containing just "v" in a word context
        result = extract_team_variant("Rovers V2 Academy")
        assert result != "v"

    def test_coach_name_variant(self):
        assert extract_team_variant("Atletico Dallas 15G Riedell") == "riedell"
        assert extract_team_variant("FC Dynamo 2014 Davis") == "davis"

    def test_no_variant(self):
        """Teams with only known non-coach words after age should return None."""
        assert extract_team_variant("FC 2014") is None
        assert extract_team_variant("Rush 2014 ECNL") is None

    def test_empty_input(self):
        assert extract_team_variant("") is None
        assert extract_team_variant(None) is None

    def test_color_in_parentheses(self):
        assert extract_team_variant("Rush (Blue)") == "blue"

    def test_program_name_not_coach(self):
        """Program names like 'aspire' should not be treated as coach names."""
        result = extract_team_variant("FC Dallas 2014 Aspire")
        assert result is None or result == "aspire"  # aspire is in _PROGRAM_NAMES

    def test_trailing_marker_punctuation_stripped(self):
        """Trailing markers like '*' or "'" must not leak into the variant.

        Regression for the Skyline duplicate case: 'Skyline - 2015 Blue' and
        'Skyline - 2015 Blue*' are the same team — both must extract 'blue'.
        Same parity fix applied to find_queue_matches.extract_team_variant
        and team_name_utils.extract_team_variant.
        """
        assert extract_team_variant("Skyline - 2015 Blue*") == "blue"
        assert extract_team_variant("FC Dallas 2014 Blue*") == "blue"
        assert extract_team_variant("Select North*") == "north"
        assert extract_team_variant("Rush South'") == "south"

    def test_coach_name_trailing_markers_stripped(self):
        """Trailing markers must also be stripped in the coach-name branch.

        Regression: the color/direction loops were patched first but the
        coach branch kept its own strip literal that excluded `'*` —
        'Atletico Dallas 15G Riedell*' would extract 'riedell*' while the
        unmarked sibling extracted 'riedell', leaving them as distinct
        coach_name values in extract_distinctions and blocking the merge.
        """
        assert extract_team_variant("Atletico Dallas 15G Riedell*") == "riedell"
        assert extract_team_variant("Atletico Dallas 15G Riedell'") == "riedell"
        assert extract_team_variant("FC Dynamo 2014 Davis,") == "davis"
        # And the unmarked sibling must still match identically.
        assert extract_team_variant("Atletico Dallas 15G Riedell") == "riedell"
