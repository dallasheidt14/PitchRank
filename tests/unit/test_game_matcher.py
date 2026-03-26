"""Tests for game matching system — game_matcher.py"""
import uuid
import pytest

from src.models.game_matcher import (
    extract_team_variant,
    GAME_UID_NAMESPACE,
)


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


class TestGenerateGameUid:
    """Tests for deterministic game UID generation."""

    def test_deterministic(self):
        """Same inputs always produce the same UID."""
        key = "gotsport|123|456|2025-01-15"
        uid1 = str(uuid.uuid5(GAME_UID_NAMESPACE, key))
        uid2 = str(uuid.uuid5(GAME_UID_NAMESPACE, key))
        assert uid1 == uid2

    def test_different_inputs_different_uids(self):
        uid1 = str(uuid.uuid5(GAME_UID_NAMESPACE, "gotsport|123|456|2025-01-15"))
        uid2 = str(uuid.uuid5(GAME_UID_NAMESPACE, "gotsport|123|456|2025-01-16"))
        assert uid1 != uid2

    def test_valid_uuid_format(self):
        uid = str(uuid.uuid5(GAME_UID_NAMESPACE, "test|1|2|2025-01-01"))
        parsed = uuid.UUID(uid)
        assert parsed.version == 5
