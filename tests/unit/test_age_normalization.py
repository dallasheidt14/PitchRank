"""Unit tests for ``src.scrapers._age_normalization.normalize_age``.

Pure-function tests — no fixtures, no network. Mirrors the per-band style
of ``tests/unit/test_sincsports_*`` modules.
"""

from __future__ import annotations

from src.scrapers._age_normalization import normalize_age


class TestNormalizeAge:
    def test_micro_cohorts_widened_band(self):
        # The widened ``[6, 19]`` band is the whole point of the extraction —
        # it lets ``gotsport_tier_parser`` distinguish known-out-of-scope from
        # genuine unknowns. ``sincsports_events._normalize_age``'s prior band
        # was ``[8, 19]``; ``u6``/``u7`` would have returned ``None``.
        assert normalize_age(6) == "u6"
        assert normalize_age(7) == "u7"

    def test_legacy_band_below_micro(self):
        assert normalize_age(8) == "u8"
        assert normalize_age(9) == "u9"

    def test_in_scope_band(self):
        assert normalize_age(10) == "u10"
        assert normalize_age(13) == "u13"
        assert normalize_age(17) == "u17"
        assert normalize_age(19) == "u19"

    def test_u18_merges_into_u19(self):
        # Repo convention per ``gotcha_age_group_format.md`` — U18 has no
        # standalone bucket; players merge into U19.
        assert normalize_age(18) == "u19"

    def test_below_band_returns_none(self):
        assert normalize_age(5) is None
        assert normalize_age(0) is None
        assert normalize_age(-1) is None

    def test_above_band_returns_none(self):
        assert normalize_age(20) is None
        assert normalize_age(99) is None
