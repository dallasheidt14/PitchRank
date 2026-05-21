"""Unit tests for find_queue_matches fetch-side helpers."""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT))

from find_queue_matches import _stored_club_looks_wrong  # noqa: E402


class TestStoredClubLooksWrong:
    def test_obvious_cross_state_mismatch(self):
        # La Roca FC is in Utah; LOS ANGELES SC is California.
        # Provider name and stored club share zero >=4-char tokens.
        assert _stored_club_looks_wrong("LOS ANGELES SC", "La Roca FC AV Pre-ECNL B15") is True

    def test_acronym_legit(self):
        # EBU is a legitimate acronym for Elmbrook United. Provider uses
        # acronym, stored uses full name. No long-token overlap, but the
        # stored club_name has been confirmed correct via other rows.
        # Heuristic must return False to avoid re-deriving correctly-stored data.
        assert _stored_club_looks_wrong("Elmbrook United", "EBU 14U GIRLS ACADEMY ASPIRE") is True

    def test_substring_overlap(self):
        # Stored "Jackson Soccer Club" overlaps "Jackson" with provider — legit.
        assert _stored_club_looks_wrong("Jackson Soccer Club", "Jackson SC - 2012 Girls Blaze") is False

    def test_empty_stored(self):
        assert _stored_club_looks_wrong("", "Any Team Name") is False
        assert _stored_club_looks_wrong(None, "Any Team Name") is False

    def test_short_tokens_only(self):
        # Only short tokens — heuristic can't reliably tell. Default to trusting stored data.
        assert _stored_club_looks_wrong("FC SC", "Any Team Name") is False

    def test_mixed_tokens(self):
        # Stored has long tokens "Ventura" and "County"; provider has "County" in "Deptford Premier..."
        # Long token has overlap -> looks fine.
        assert _stored_club_looks_wrong("VENTURA COUNTY FC", "Deptford Premier County 13 Girls") is False


from find_queue_matches import _cohort_fallback_candidates  # noqa: E402


class _FakeQuery:
    """Minimal supabase query-builder stub for cohort fallback tests."""

    def __init__(self, rows):
        self._rows = rows
        self.filters = []

    def select(self, *_args, **_kwargs):
        return self

    def ilike(self, col, val):
        self.filters.append(("ilike", col, val))
        return self

    def or_(self, clause):
        self.filters.append(("or", clause))
        return self

    def eq(self, col, val):
        self.filters.append(("eq", col, val))
        return self

    def limit(self, n):
        self.filters.append(("limit", n))
        return self

    def execute(self):
        return type("R", (), {"data": self._rows})()


class _FakeClient:
    def __init__(self, rows):
        self._rows = rows
        self.last_query = None

    def table(self, _name):
        self.last_query = _FakeQuery(self._rows)
        return self.last_query


class TestCohortFallbackCandidates:
    def test_filters_by_gender_age_and_state(self):
        client = _FakeClient([])
        _cohort_fallback_candidates(client, gender="male", age_group="u12", state_code="AZ")
        filters = client.last_query.filters
        assert any(f[0] == "ilike" and f[1] == "gender" for f in filters)
        assert any(f[0] == "or" for f in filters)
        assert any(f[0] == "eq" and f[1] == "state_code" and f[2] == "AZ" for f in filters)
        assert any(f[0] == "limit" for f in filters)

    def test_no_state_filter_when_state_is_none(self):
        client = _FakeClient([])
        _cohort_fallback_candidates(client, gender="female", age_group="u14", state_code=None)
        filters = client.last_query.filters
        assert not any(f[0] == "eq" and f[1] == "state_code" for f in filters)

    def test_returns_query_results(self):
        client = _FakeClient([
            {"team_id_master": "abc", "team_name": "Sample 2012 White"},
            {"team_id_master": "def", "team_name": "Sample 2012 Black"},
        ])
        rows = _cohort_fallback_candidates(client, gender="male", age_group="u14", state_code="AZ")
        assert len(rows) == 2
        assert rows[0]["team_id_master"] == "abc"

    def test_returns_empty_list_when_no_gender_or_age(self):
        client = _FakeClient([])
        rows = _cohort_fallback_candidates(client, gender=None, age_group="u14", state_code=None)
        assert rows == []
        rows = _cohort_fallback_candidates(client, gender="male", age_group=None, state_code=None)
        assert rows == []
