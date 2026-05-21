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
