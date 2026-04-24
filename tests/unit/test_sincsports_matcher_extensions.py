"""Unit tests for the SincSports matcher discovery extensions (plan Step 2).

Covers three extensions, all branch-heavy per repo test convention:

- ``was_created`` tuple from ``_create_new_sincsports_team``
- ``state_code`` kwarg cascading through ``_match_team`` and
  ``_fuzzy_match_team`` and being persisted on INSERT
- ``discovery_mode`` suppression of base review-queue writes plus
  forward-carry of ``suppressed_review_method`` / ``suppressed_review_confidence``

The full fluent Supabase chain is mocked once per test via a helper; the
existing game-import path stays intact because every new field carries a
backward-compatible default.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.models.sincsports_matcher import SincSportsGameMatcher


def _mock_supabase():
    """Return a ``Mock`` whose ``.table(...)`` chain terminates in a caller-controlled result.

    Each test threads its own ``.execute()`` return value — the helper only
    sets up the chain so ``db.table("X").select(...).eq(...).execute()``
    reaches a ``MagicMock`` node the test can pre-program.
    """
    return MagicMock()


def _make_matcher(supabase=None, discovery_mode=False) -> SincSportsGameMatcher:
    """Instantiate the matcher with the heavy lifting of ``__init__`` bypassed.

    The real ``__init__`` logs; giving it a Mock ``supabase`` is sufficient.
    """
    return SincSportsGameMatcher(
        supabase=supabase or _mock_supabase(),
        provider_id="test-provider-uuid",
        discovery_mode=discovery_mode,
    )


class TestWasCreatedTuple:
    """Part 1 of Step 2b: ``_create_new_sincsports_team`` returns ``(id, was_created)``."""

    def test_returns_true_on_fresh_insert(self):
        m = _make_matcher()
        # Pre-insert lookup raises (simulating no-row found via .single())
        pre_check = MagicMock()
        pre_check.data = None
        pre_check_exec = MagicMock()
        # .single().execute() raises when no row found in real supabase-py;
        # the matcher catches the exception in a try block.
        pre_check_exec.execute.side_effect = Exception("PGRST116: no rows")

        m.db.table.return_value.select.return_value.eq.return_value.eq.return_value.single.return_value = pre_check_exec
        # Insert succeeds
        insert_exec = MagicMock()
        insert_exec.execute.return_value = MagicMock(data=[{"team_id_master": "fake"}])
        m.db.table.return_value.insert.return_value = insert_exec

        team_id, was_created = m._create_new_sincsports_team(
            team_name="Test FC",
            club_name="Test",
            age_group="U12",
            gender="Male",
            provider_id="pid",
            provider_team_id="TST123",
        )

        assert was_created is True
        assert team_id  # a uuid4 was generated
        # Insert body must include state_code (None when not provided).
        insert_call = m.db.table.return_value.insert.call_args
        payload = insert_call[0][0]
        assert "state_code" in payload
        assert payload["state_code"] is None

    def test_returns_false_on_preinsert_hit(self):
        m = _make_matcher()
        # Pre-insert lookup returns an existing row.
        pre_check = MagicMock()
        pre_check.data = {"team_id_master": "existing-master-id"}
        single_exec = (
            m.db.table.return_value.select.return_value.eq.return_value.eq.return_value.single.return_value.execute
        )
        single_exec.return_value = pre_check

        team_id, was_created = m._create_new_sincsports_team(
            team_name="Existing FC",
            club_name="Existing",
            age_group="u12",
            gender="Male",
            provider_id="pid",
            provider_team_id="TST999",
        )

        assert team_id == "existing-master-id"
        assert was_created is False
        # No INSERT may have been attempted.
        assert m.db.table.return_value.insert.call_count == 0

    def test_returns_false_on_23505_fallback(self):
        m = _make_matcher()

        # First lookup: .single().execute() raises (no pre-existing row).
        # Second lookup (23505 fallback): .single().execute() returns data.
        pre_exec = MagicMock()
        pre_exec.execute.side_effect = [
            Exception("PGRST116: no rows"),
            MagicMock(data={"team_id_master": "race-winner-id"}),
        ]
        m.db.table.return_value.select.return_value.eq.return_value.eq.return_value.single.return_value = pre_exec

        # Insert raises 23505 duplicate-key.
        insert_exec = MagicMock()
        insert_exec.execute.side_effect = Exception("duplicate key value violates unique constraint (23505)")
        m.db.table.return_value.insert.return_value = insert_exec

        team_id, was_created = m._create_new_sincsports_team(
            team_name="Race FC",
            club_name="Race",
            age_group="u12",
            gender="Male",
            provider_id="pid",
            provider_team_id="TSTRACE",
        )

        assert team_id == "race-winner-id"
        assert was_created is False

    def test_state_code_persisted_on_insert(self):
        m = _make_matcher()
        pre_exec = MagicMock()
        pre_exec.execute.side_effect = Exception("PGRST116: no rows")
        m.db.table.return_value.select.return_value.eq.return_value.eq.return_value.single.return_value = pre_exec
        m.db.table.return_value.insert.return_value = MagicMock()

        m._create_new_sincsports_team(
            team_name="AZ Team",
            club_name="AZ Club",
            age_group="u12",
            gender="Male",
            provider_id="pid",
            provider_team_id="AZM14001",
            state_code="AZ",
        )

        insert_call = m.db.table.return_value.insert.call_args
        payload = insert_call[0][0]
        assert payload["state_code"] == "AZ"


class TestMatchTeamReturnShape:
    """Part 2 & 3 of Step 2b: ``_match_team`` wraps every return with ``created`` / ``suppressed_*``."""

    def test_created_false_on_direct_id_path(self):
        m = _make_matcher()
        with patch.object(m, "_match_by_provider_id") as mock_pid:
            mock_pid.return_value = {
                "team_id_master": "existing-id",
                "review_status": "approved",
                "match_method": "direct_id",
            }
            result = m._match_team(
                provider_id="pid",
                provider_team_id="TST001",
                team_name="Test",
                age_group="u12",
                gender="Male",
            )
            assert result["matched"] is True
            assert result["method"] == "direct_id"
            assert result["created"] is False
            assert result["suppressed_review_method"] is None
            assert result["suppressed_review_confidence"] is None

    def test_created_true_on_fresh_create_path(self):
        m = _make_matcher()
        with (
            patch.object(m, "_match_by_provider_id", return_value=None),
            patch.object(m, "_match_by_alias", return_value=None),
            patch.object(m, "_fuzzy_match_team", return_value=None),
            patch.object(m, "_create_review_queue_entry"),
            patch.object(m, "_create_alias"),
            patch.object(m, "_create_new_sincsports_team", return_value=("new-master-id", True)) as mock_create,
        ):
            result = m._match_team(
                provider_id="pid",
                provider_team_id="TST002",
                team_name="Fresh FC",
                age_group="u12",
                gender="Male",
                state_code="AZ",
            )
            assert result["matched"] is True
            assert result["method"] == "direct_id"
            assert result["created"] is True
            assert result["team_id"] == "new-master-id"
            assert result["suppressed_review_method"] is None
            # state_code was threaded through to the creation helper.
            assert mock_create.call_args.kwargs["state_code"] == "AZ"

    def test_created_false_when_create_returns_existing(self):
        """Driver's ``direct_alias_hit`` bucket — created=False for race with pre-check."""
        m = _make_matcher()
        with (
            patch.object(m, "_match_by_provider_id", return_value=None),
            patch.object(m, "_match_by_alias", return_value=None),
            patch.object(m, "_fuzzy_match_team", return_value=None),
            patch.object(m, "_create_review_queue_entry"),
            patch.object(m, "_create_alias"),
            patch.object(m, "_create_new_sincsports_team", return_value=("existing-id", False)),
        ):
            result = m._match_team(
                provider_id="pid",
                provider_team_id="TST003",
                team_name="Race FC",
                age_group="u12",
                gender="Male",
            )
            assert result["matched"] is True
            assert result["created"] is False
            assert result["team_id"] == "existing-id"


class TestDiscoveryModeSuppression:
    """Step 2c: ``discovery_mode`` suppresses review-queue writes and carries forward the signal."""

    def test_review_queue_insert_suppressed_in_discovery_mode(self):
        m = _make_matcher(discovery_mode=True)
        # Call the override directly — it should return without hitting the DB.
        result = m._create_review_queue_entry(
            provider_id="pid",
            provider_team_id="TST005",
            provider_team_name="Whatever",
            suggested_master_team_id="x",
            confidence_score=0.80,
            match_details={},
        )
        assert result is None
        # The db.table chain must not have been touched.
        assert m.db.table.call_count == 0

    def test_review_queue_insert_passes_through_when_not_discovery_mode(self):
        m = _make_matcher(discovery_mode=False)
        # Patch the base class method to verify delegation.
        with patch.object(
            SincSportsGameMatcher.__mro__[1], "_create_review_queue_entry", return_value=None
        ) as base_method:
            m._create_review_queue_entry(
                provider_id="pid",
                provider_team_id="TST006",
                provider_team_name="Whatever",
                suggested_master_team_id="x",
                confidence_score=0.80,
                match_details={},
            )
            base_method.assert_called_once()

    def test_suppressed_review_method_carried_forward_on_create_path(self):
        """Discovery auto-create wraps sub-0.91 fuzzy result into suppressed fields."""
        m = _make_matcher(discovery_mode=True)
        with (
            patch.object(m, "_match_by_provider_id", return_value=None),
            patch.object(m, "_match_by_alias", return_value=None),
            patch.object(
                m,
                "_fuzzy_match_team",
                return_value=None,  # fuzzy found nothing — base routes to no-match/review-queue
            ),
            patch.object(m, "_create_alias"),
            patch.object(m, "_create_new_sincsports_team", return_value=("new-id", True)),
        ):
            # Force the base to return a fuzzy_review-shaped result so we can
            # verify the carry-forward wiring. Patch the PARENT class so super()
            # dispatch lands on our stub.
            with patch(
                "src.models.sincsports_matcher.GameHistoryMatcher._match_team",
                return_value={
                    "matched": False,
                    "team_id": None,
                    "method": "fuzzy_review",
                    "confidence": 0.82,
                },
            ):
                result = m._match_team(
                    provider_id="pid",
                    provider_team_id="TST007",
                    team_name="Borderline FC",
                    age_group="u12",
                    gender="Male",
                    state_code="NC",
                )

            assert result["matched"] is True
            assert result["created"] is True
            assert result["suppressed_review_method"] == "fuzzy_review"
            assert result["suppressed_review_confidence"] == pytest.approx(0.82)

    def test_suppressed_fields_none_on_auto_approved_fuzzy(self):
        """fuzzy_auto (≥0.91) never triggers subclass create — suppressed_* stays None."""
        m = _make_matcher(discovery_mode=True)
        with patch(
            "src.models.sincsports_matcher.GameHistoryMatcher._match_team",
            return_value={
                "matched": True,
                "team_id": "auto-id",
                "method": "fuzzy_auto",
                "confidence": 0.94,
            },
        ):
            result = m._match_team(
                provider_id="pid",
                provider_team_id="TST008",
                team_name="High-Confidence FC",
                age_group="u12",
                gender="Male",
            )
            assert result["matched"] is True
            assert result["method"] == "fuzzy_auto"
            assert result["created"] is False
            assert result["suppressed_review_method"] is None
            assert result["suppressed_review_confidence"] is None


class TestStateCodeCascade:
    """Step 2a: ``state_code`` threads from driver → _match_team → fuzzy scoring."""

    @staticmethod
    def _fuzzy_chain(mock_db, *, clubbed: bool):
        """Walk ``mock_db`` down the fuzzy-candidate query chain and return the terminal ``execute``.

        Keeps the ``.return_value...`` ladder off of a single line so ruff E501
        doesn't flag the mock setup. ``clubbed=True`` mirrors the club-filtered
        gated-funnel query (``.ilike("club_name", ...)``); ``clubbed=False`` is
        the broad fallback (no ``ilike``).
        """
        chain = mock_db.table.return_value.select.return_value.eq.return_value.eq.return_value
        if clubbed:
            chain = chain.ilike.return_value
        return chain.limit.return_value.execute

    def test_state_code_reaches_fuzzy_match(self):
        """Subclass ``_fuzzy_match_team`` receives ``state_code`` and passes into scoring dict."""
        m = _make_matcher()
        self._fuzzy_chain(m.db, clubbed=True).return_value = MagicMock(data=[])
        self._fuzzy_chain(m.db, clubbed=False).return_value = MagicMock(data=[])

        # Spy on scoring — just verify state_code flows into the provider dict.
        seen_kwargs = {}
        orig_score = m._calculate_match_score

        def spy(provider_team, candidate):
            seen_kwargs["state_code"] = provider_team.get("state_code")
            return orig_score(provider_team, candidate)

        with patch.object(m, "_calculate_match_score", side_effect=spy):
            m._fuzzy_match_team(
                team_name="Sample FC",
                age_group="u12",
                gender="Male",
                club_name="Sample",
                state_code="AZ",
            )
        # With empty candidate list, score isn't called — re-run with a fake candidate so
        # the scoring spy actually fires and we can confirm state_code reaches the dict.
        candidate_result = MagicMock(
            data=[
                {
                    "team_id_master": "cand-id",
                    "team_name": "Sample FC",
                    "club_name": "Sample",
                    "age_group": "u12",
                    "gender": "Male",
                    "state_code": "AZ",
                }
            ]
        )
        m.db.reset_mock()
        self._fuzzy_chain(m.db, clubbed=True).return_value = candidate_result
        with patch.object(m, "_calculate_match_score", side_effect=spy):
            m._fuzzy_match_team(
                team_name="Sample FC",
                age_group="u12",
                gender="Male",
                club_name="Sample",
                state_code="AZ",
            )
        assert seen_kwargs.get("state_code") == "AZ"

    def test_state_code_threads_through_match_team_to_create(self):
        """End-to-end: ``_match_team(..., state_code=AZ)`` reaches ``_create_new_sincsports_team``."""
        m = _make_matcher()
        with (
            patch.object(m, "_match_by_provider_id", return_value=None),
            patch.object(m, "_match_by_alias", return_value=None),
            patch.object(m, "_fuzzy_match_team", return_value=None) as mock_fuzzy,
            patch.object(m, "_create_review_queue_entry"),
            patch.object(m, "_create_alias"),
            patch.object(m, "_create_new_sincsports_team", return_value=("nid", True)) as mock_create,
        ):
            m._match_team(
                provider_id="pid",
                provider_team_id="TST010",
                team_name="AZ FC",
                age_group="u12",
                gender="Male",
                state_code="AZ",
            )
            # Base forwards state_code to subclass fuzzy (conditional forward).
            fuzzy_call = mock_fuzzy.call_args
            assert fuzzy_call.kwargs.get("state_code") == "AZ"
            # Create helper receives state_code.
            assert mock_create.call_args.kwargs["state_code"] == "AZ"


class TestBackwardCompatibility:
    """Existing callers that don't pass new kwargs still work (plan's verification rule)."""

    def test_match_team_without_state_code(self):
        """Game-import pipeline path — no state_code arg, defaults to None."""
        m = _make_matcher()
        with patch(
            "src.models.sincsports_matcher.GameHistoryMatcher._match_team",
            return_value={"matched": True, "team_id": "id", "method": "direct_id", "confidence": 1.0},
        ) as base_mt:
            result = m._match_team(
                provider_id="pid",
                provider_team_id="TST020",
                team_name="Legacy FC",
                age_group="u12",
                gender="Male",
            )
            # Base receives state_code=None (default).
            assert base_mt.call_args.kwargs.get("state_code") is None
            # Subclass return dict still carries the new fields (all None).
            assert result["created"] is False
            assert result["suppressed_review_method"] is None
            assert result["suppressed_review_confidence"] is None

    def test_discovery_mode_defaults_off(self):
        m = _make_matcher()
        assert m.discovery_mode is False
