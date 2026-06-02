"""Unit tests for Modular11 division-aware fuzzy matching.

Modular11 (MLS NEXT) reuses one club_id across every age group AND division,
so the HD/AD suffix is the *only* signal that distinguishes two genuinely
different teams (e.g. "FC Dallas U13 AD" is a different roster than
"FC Dallas U13 HD"). The matcher must never collapse a confirmed division
conflict — its docstring states the contract as "Division matches or absent
(not conflicting)".

The fluent Supabase candidate-fetch chain is mocked per test; the real
``_calculate_match_score`` runs against the in-memory candidate so the
similarity score reflects production behavior.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.models.modular11_matcher import Modular11GameMatcher


def _mock_supabase():
    """Return a Mock whose ``.table(...)`` chain the test pre-programs."""
    return MagicMock()


def _make_matcher(supabase=None) -> Modular11GameMatcher:
    """Instantiate the matcher with a Mock client (real ``__init__`` only logs)."""
    return Modular11GameMatcher(
        supabase=supabase or _mock_supabase(),
        provider_id="modular11-provider-uuid",
    )


def _program_candidate_fetch(matcher: Modular11GameMatcher, candidates: list[dict]) -> None:
    """Pre-program the ``teams`` candidate fetch:
    ``db.table("teams").select(...).eq("age_group",...).eq("gender",...).execute()``.
    """
    exec_node = MagicMock()
    exec_node.execute.return_value = MagicMock(data=candidates)
    matcher.db.table.return_value.select.return_value.eq.return_value.eq.return_value = exec_node


_FC_DALLAS_HD = {
    "team_id_master": "hd-team-1",
    "team_name": "FC Dallas U13 HD",
    "club_name": "FC Dallas",
    "age_group": "u13",
    "gender": "Male",
    "state_code": "TX",
}


# Two Modular11 names that differ ONLY by the division token score very high on
# the base name/club scorer in production (canonical club match + near-identical
# name). Pin the base so these unit tests exercise the division gate, not the
# separately-tested similarity scorer.
_HIGH_BASE_SCORE = 0.95


class TestDivisionConflictRejected:
    """A confirmed AD-vs-HD conflict on the same club/age must hard-reject."""

    def test_ad_does_not_match_hd_via_alias_division(self):
        m = _make_matcher()
        _program_candidate_fetch(m, [_FC_DALLAS_HD])

        with (
            patch.object(m, "_get_candidate_divisions", return_value={"hd-team-1": "HD"}),
            patch.object(m, "_calculate_match_score", return_value=_HIGH_BASE_SCORE),
        ):
            result = m.fuzzy_match_modular11_team(
                incoming_name="FC Dallas U13 AD",
                age_group="U13",
                gender="Male",
                division="AD",
                club_name="FC Dallas",
            )

        assert result is None, "AD incoming must not match HD candidate (different team)"

    def test_ad_does_not_match_hd_when_alias_division_missing(self):
        """Defense in depth: even if the alias map has no division, the HD suffix
        in the candidate *name* must still trigger the conflict gate."""
        m = _make_matcher()
        _program_candidate_fetch(m, [_FC_DALLAS_HD])

        with (
            patch.object(m, "_get_candidate_divisions", return_value={}),
            patch.object(m, "_calculate_match_score", return_value=_HIGH_BASE_SCORE),
        ):
            result = m.fuzzy_match_modular11_team(
                incoming_name="FC Dallas U13 AD",
                age_group="U13",
                gender="Male",
                division="AD",
                club_name="FC Dallas",
            )

        assert result is None, "AD incoming must not match HD-named candidate even with empty alias division"


class TestSameDivisionStillMatches:
    """The gate must not over-correct: a matching division still resolves."""

    def test_hd_matches_hd(self):
        m = _make_matcher()
        _program_candidate_fetch(m, [_FC_DALLAS_HD])

        with (
            patch.object(m, "_get_candidate_divisions", return_value={"hd-team-1": "HD"}),
            patch.object(m, "_calculate_match_score", return_value=_HIGH_BASE_SCORE),
        ):
            result = m.fuzzy_match_modular11_team(
                incoming_name="FC Dallas U13 HD",
                age_group="U13",
                gender="Male",
                division="HD",
                club_name="FC Dallas",
            )

        assert result is not None, "HD incoming should still match the HD candidate"
        assert result.team_id_master == "hd-team-1"
        assert result.division_match is True
