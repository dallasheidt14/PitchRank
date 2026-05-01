"""State-machine coverage for ``enrich_teams_with_tiers``.

Mocks the ``subpage_fetcher`` callable so each test injects canned
``FetchedSubpage`` instances. Uses ``tmp_path`` for ``base_dir`` so
artifact writes don't pollute the real ``reports/`` tree.

Together with ``test_gotsport_tier_parser_fixtures.py`` (real-fixture
replay) this covers the full Phase 0 behavior contract.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Callable

import pytest
from bs4 import BeautifulSoup

from src.scrapers.gotsport import EventCaptchaGatedError
from src.scrapers.gotsport_tier_parser import (
    EnrichmentResult,
    EventTeamMembershipCollisionError,
    FetchedSubpage,
    TierSubfetchError,
    enrich_teams_with_tiers,
)


def _subpage(html: str) -> FetchedSubpage:
    """Build a normal (non-captcha) FetchedSubpage."""
    return FetchedSubpage(
        html=html,
        final_url="https://system.gotsport.com/org_event/events/X/schedules?group=Y",
        zr_final_url=None,
        redirect_locations=[],
    )


def _captcha_subpage() -> FetchedSubpage:
    """Build a FetchedSubpage whose body trips _CAPTCHA_BODY_MARKER."""
    return FetchedSubpage(
        html='<html><body>Please verify to continue.<div data-sitekey="6Lc1234567890">x</div></body></html>',
        final_url="https://system.gotsport.com/org_event/events/X/schedules?group=Y",
        zr_final_url=None,
        redirect_locations=[],
    )


def _team_html(team_ids: list[int]) -> str:
    anchors = "\n".join(f'<a href="?team={tid}">T{tid}</a>' for tid in team_ids)
    return f"<html><body>{anchors}</body></html>"


def _two_tier_landing() -> str:
    """Synthetic landing with U13 Boys Gold (gid 1001) + Silver (gid 1002)."""
    return """
    <html><body>
    <div><div>
      <b>U13 Boys Gold</b>
      <a href="/org_event/events/X/schedules?group=1001">Schedule</a>
    </div></div>
    <div><div>
      <b>U13 Boys Silver</b>
      <a href="/org_event/events/X/schedules?group=1002">Schedule</a>
    </div></div>
    </body></html>
    """


def _make_fetcher(by_gid: dict[int, FetchedSubpage]) -> Callable[[int], FetchedSubpage]:
    def fetcher(gid: int) -> FetchedSubpage:
        return by_gid[gid]

    return fetcher


# ---------------------------------------------------------------------------


class TestDiscoverySuccess:
    def test_all_subfetches_succeed(self, tmp_path):
        soup = BeautifulSoup(_two_tier_landing(), "html.parser")
        fetcher = _make_fetcher(
            {
                1001: _subpage(_team_html([100, 101])),
                1002: _subpage(_team_html([200, 201])),
            }
        )
        out = enrich_teams_with_tiers(
            soup,
            teams_by_bracket={},
            event_id="X",
            event_key="gotsport__X__unknown",
            run_id="2026-04-29T00:00:00+00:00",
            subpage_fetcher=fetcher,
            base_dir=tmp_path,
        )
        assert set(out.keys()) == {"100", "101", "200", "201"}
        assert out["100"].group_id == 1001
        assert out["100"].group_name == "Gold"
        assert out["100"].tier_membership_source == "subpage"
        assert out["200"].group_id == 1002
        assert out["200"].group_name == "Silver"

        # Metrics file written at base_dir/<event_key>/intake/.
        metrics_path = tmp_path / "gotsport__X__unknown" / "intake" / "tier_parse_metrics.json"
        assert metrics_path.exists()
        payload = json.loads(metrics_path.read_text())
        assert payload["total_candidates"] == 2
        assert payload["unknown_prefix_count"] == 0
        assert payload["gated_at_threshold"] is False


class TestDiscoveryEmpty:
    def test_no_group_anchors_returns_empty_dict(self, tmp_path):
        soup = BeautifulSoup("<html><body><p>no tiers here</p></body></html>", "html.parser")
        out = enrich_teams_with_tiers(
            soup,
            teams_by_bracket={},
            event_id="X",
            event_key="ek",
            run_id="rid",
            subpage_fetcher=lambda gid: pytest.fail("should not subfetch"),
            base_dir=tmp_path,
        )
        assert out == {}
        # Metrics still written with total_candidates=0.
        payload = json.loads((tmp_path / "ek" / "intake" / "tier_parse_metrics.json").read_text())
        assert payload["total_candidates"] == 0


class TestSubfetchHttpError:
    def test_wraps_as_typed_error_and_writes_abort_artifact(self, tmp_path):
        soup = BeautifulSoup(_two_tier_landing(), "html.parser")

        def fetcher(gid):
            if gid == 1001:
                return _subpage(_team_html([100]))
            raise ConnectionError("boom")

        with pytest.raises(TierSubfetchError) as excinfo:
            enrich_teams_with_tiers(
                soup,
                teams_by_bracket={},
                event_id="X",
                event_key="ek",
                run_id="rid",
                subpage_fetcher=fetcher,
                base_dir=tmp_path,
            )
        assert excinfo.value.underlying_kind == "http_error"
        assert excinfo.value.group_id == 1002

        # BOTH metrics + abort artifacts exist.
        intake = tmp_path / "ek" / "intake"
        assert (intake / "tier_parse_metrics.json").exists()
        abort = json.loads((intake / "tier_orchestrator_abort__rid.json").read_text())
        assert abort["failure_kind"] == "http_error"
        assert abort["failed_group_id"] == 1002
        # gid 1001 completed before the failure on 1002.
        assert 1001 in abort["completed_group_ids"]


class TestSubfetchCaptcha:
    def test_raises_captcha_error_and_writes_both_artifacts(self, tmp_path):
        soup = BeautifulSoup(_two_tier_landing(), "html.parser")
        fetcher = _make_fetcher(
            {
                1001: _captcha_subpage(),  # captcha hits the FIRST gid
                1002: _subpage(_team_html([200])),
            }
        )
        with pytest.raises(EventCaptchaGatedError) as excinfo:
            enrich_teams_with_tiers(
                soup,
                teams_by_bracket={},
                event_id="X",
                event_key="ek",
                run_id="rid",
                subpage_fetcher=fetcher,
                base_dir=tmp_path,
            )
        assert excinfo.value.provider_event_id == "X"
        intake = tmp_path / "ek" / "intake"
        # BOTH metrics (immediate) + abort (captcha) artifacts exist.
        assert (intake / "tier_parse_metrics.json").exists()
        abort = json.loads((intake / "tier_orchestrator_abort__rid.json").read_text())
        assert abort["failure_kind"] == "captcha"


class TestSubfetchMalformed:
    def test_zero_team_anchors_with_real_residue_raises_malformed(self, tmp_path):
        # gid 1001 claims tier residue "Gold" (matched outcome), but the
        # subpage has zero ?team= anchors → orchestrator flags as malformed.
        soup = BeautifulSoup(_two_tier_landing(), "html.parser")
        fetcher = _make_fetcher(
            {
                1001: _subpage("<html><body>no team links</body></html>"),
                1002: _subpage(_team_html([200])),
            }
        )
        with pytest.raises(TierSubfetchError) as excinfo:
            enrich_teams_with_tiers(
                soup,
                teams_by_bracket={},
                event_id="X",
                event_key="ek",
                run_id="rid",
                subpage_fetcher=fetcher,
                base_dir=tmp_path,
            )
        assert excinfo.value.underlying_kind == "malformed_html"


class TestForwardCollision:
    def test_forward_collision_caught_and_written(self, tmp_path):
        # Two anchors with same gid but different residue → forward collision.
        html = """
        <div><div>
          <b>U13 Boys Gold</b>
          <a href="/schedules?group=42">Schedule</a>
        </div></div>
        <div><div>
          <b>U13 Boys Silver</b>
          <a href="/schedules?group=42">Schedule</a>
        </div></div>
        """
        soup = BeautifulSoup(html, "html.parser")
        with pytest.raises(EventTeamMembershipCollisionError) as excinfo:
            enrich_teams_with_tiers(
                soup,
                teams_by_bracket={},
                event_id="X",
                event_key="ek",
                run_id="rid",
                subpage_fetcher=lambda gid: pytest.fail("should not subfetch"),
                base_dir=tmp_path,
            )
        assert excinfo.value.mode == "forward"
        assert excinfo.value.group_id == 42
        abort = json.loads((tmp_path / "ek" / "intake" / "tier_orchestrator_abort__rid.json").read_text())
        assert abort["failure_kind"] == "collision_forward"


class TestInverseCollision:
    def test_default_log_and_proceed_marks_ambiguous(self, tmp_path, caplog):
        soup = BeautifulSoup(_two_tier_landing(), "html.parser")
        # Team 12345 appears in BOTH gids — inverse collision.
        fetcher = _make_fetcher(
            {
                1001: _subpage(_team_html([12345, 99001])),
                1002: _subpage(_team_html([12345, 99002])),
            }
        )
        caplog.set_level(logging.WARNING, logger="src.scrapers.gotsport_tier_parser")
        out = enrich_teams_with_tiers(
            soup,
            teams_by_bracket={},
            event_id="X",
            event_key="ek",
            run_id="rid",
            subpage_fetcher=fetcher,
            base_dir=tmp_path,
        )
        # Team 12345 resolves to gid 1001 (catalog insertion order).
        assert out["12345"].group_id == 1001
        assert out["12345"].tier_membership_source == "ambiguous_multi_tier"
        # Singletons get plain "subpage" provenance.
        assert out["99001"].tier_membership_source == "subpage"
        assert out["99002"].tier_membership_source == "subpage"
        # WARNING log surfaced.
        assert any("tier_inverse_collision" in r.message for r in caplog.records)

    def test_strict_mode_raises(self, tmp_path, monkeypatch):
        # Monkeypatch the module-level flag rather than a local import — both
        # work, but module-attr setattr is the canonical pattern.
        from src.scrapers import gotsport_tier_parser as gtp

        monkeypatch.setattr(gtp, "INVERSE_COLLISION_STRICT_MODE", True)
        soup = BeautifulSoup(_two_tier_landing(), "html.parser")
        fetcher = _make_fetcher(
            {
                1001: _subpage(_team_html([12345])),
                1002: _subpage(_team_html([12345])),
            }
        )
        with pytest.raises(EventTeamMembershipCollisionError) as excinfo:
            enrich_teams_with_tiers(
                soup,
                teams_by_bracket={},
                event_id="X",
                event_key="ek",
                run_id="rid",
                subpage_fetcher=fetcher,
                base_dir=tmp_path,
            )
        assert excinfo.value.mode == "inverse"
        assert excinfo.value.team_id == "12345"


class TestU10U19Filter:
    def test_micro_cohorts_skipped_no_subfetch(self, tmp_path):
        html = """
        <div><div>
          <b>U7 Boys Red</b>
          <a href="/schedules?group=700">Schedule</a>
        </div></div>
        <div><div>
          <b>U10 Boys Red</b>
          <a href="/schedules?group=1000">Schedule</a>
        </div></div>
        """
        soup = BeautifulSoup(html, "html.parser")
        called: list[int] = []

        def fetcher(gid):
            called.append(gid)
            return _subpage(_team_html([gid]))

        out = enrich_teams_with_tiers(
            soup,
            teams_by_bracket={},
            event_id="X",
            event_key="ek",
            run_id="rid",
            subpage_fetcher=fetcher,
            base_dir=tmp_path,
        )
        # U7 group never invoked the fetcher; U10 did.
        assert called == [1000]
        assert "1000" in out

    def test_unknown_prefix_still_subfetched(self, tmp_path):
        html = """
        <div><div>
          <b>U7 Boys Red</b>
          <a href="/schedules?group=700">Schedule</a>
        </div></div>
        <div><div>
          <b>Adult Co-Ed Hammer</b>
          <a href="/schedules?group=999">Schedule</a>
        </div></div>
        """
        soup = BeautifulSoup(html, "html.parser")
        called: list[int] = []

        def fetcher(gid):
            called.append(gid)
            return _subpage(_team_html([gid]))

        out = enrich_teams_with_tiers(
            soup,
            teams_by_bracket={},
            event_id="X",
            event_key="ek",
            run_id="rid",
            subpage_fetcher=fetcher,
            base_dir=tmp_path,
        )
        # Unknown-prefix kept (per spec line 278); U7 dropped.
        assert called == [999]
        assert out["999"].tier_parse_outcome == "unknown_prefix"
        assert out["999"].group_name == "Adult Co-Ed Hammer"


class TestHsPath:
    def test_varsity_subfetched_with_residue(self, tmp_path):
        html = """
        <div><div>
          <b>Varsity Boys Red</b>
          <a href="/schedules?group=42">Schedule</a>
        </div></div>
        """
        soup = BeautifulSoup(html, "html.parser")
        fetcher = _make_fetcher({42: _subpage(_team_html([100]))})
        out = enrich_teams_with_tiers(
            soup,
            teams_by_bracket={},
            event_id="X",
            event_key="ek",
            run_id="rid",
            subpage_fetcher=fetcher,
            base_dir=tmp_path,
        )
        assert out["100"].group_name == "Red"
        # parse_cohort_identity returned None for "Varsity Boys "; the catalog
        # records the residue but the cohort is None.
        assert out["100"].tier_parse_outcome == "matched"


class TestUnknownPrefixGate:
    def test_above_10pct_gates(self, tmp_path):
        # 10 candidates total, 2 unknown_prefix (20%) → gated.
        rows = []
        for i in range(8):
            rows.append(
                f'<div><div><b>U10 Boys Tier{i}</b><a href="/schedules?group={1000 + i}">Schedule</a></div></div>'
            )
        for i in range(2):
            rows.append(
                f'<div><div><b>Adult Co-Ed Hammer{i}</b><a href="/schedules?group={9000 + i}">Schedule</a></div></div>'
            )
        soup = BeautifulSoup("<html><body>" + "".join(rows) + "</body></html>", "html.parser")

        def fetcher(gid):
            return _subpage(_team_html([gid]))

        enrich_teams_with_tiers(
            soup,
            teams_by_bracket={},
            event_id="X",
            event_key="ek",
            run_id="rid",
            subpage_fetcher=fetcher,
            base_dir=tmp_path,
        )
        payload = json.loads((tmp_path / "ek" / "intake" / "tier_parse_metrics.json").read_text())
        assert payload["total_candidates"] == 10
        assert payload["unknown_prefix_count"] == 2
        assert payload["gated_at_threshold"] is True


class TestMemoryLifecycle:
    def test_two_separate_events_dont_share_state(self, tmp_path):
        soup = BeautifulSoup(_two_tier_landing(), "html.parser")
        fetcher_a = _make_fetcher({1001: _subpage(_team_html([100])), 1002: _subpage(_team_html([200]))})
        fetcher_b = _make_fetcher({1001: _subpage(_team_html([300])), 1002: _subpage(_team_html([400]))})
        out_a = enrich_teams_with_tiers(
            soup,
            teams_by_bracket={},
            event_id="A",
            event_key="ekA",
            run_id="rid",
            subpage_fetcher=fetcher_a,
            base_dir=tmp_path,
        )
        out_b = enrich_teams_with_tiers(
            soup,
            teams_by_bracket={},
            event_id="B",
            event_key="ekB",
            run_id="rid",
            subpage_fetcher=fetcher_b,
            base_dir=tmp_path,
        )
        assert set(out_a.keys()) == {"100", "200"}
        assert set(out_b.keys()) == {"300", "400"}


class TestConcurrencyDeterminism:
    def test_inverse_collision_resolves_to_first_catalog_gid_under_concurrency(self, tmp_path):
        # Use the synthetic_inverse_collision landing fixture (gid 1001 first in
        # document order; gid 1002 second; team 12345 in both).
        landing = Path("tests/fixtures/gotsport/event_synthetic_inverse_collision.html")
        sub_1001 = Path("tests/fixtures/gotsport/event_synthetic_inverse_collision__group_1001.html")
        sub_1002 = Path("tests/fixtures/gotsport/event_synthetic_inverse_collision__group_1002.html")
        soup = BeautifulSoup(landing.read_text(encoding="utf-8"), "html.parser")

        # Mocked fetcher returns 1002 BEFORE 1001 in completion order — inject
        # an artificial delay so 1001's future completes second under the
        # ThreadPoolExecutor.
        import time

        def fetcher(gid):
            if gid == 1001:
                time.sleep(0.05)  # arrives second
            return _subpage((sub_1001 if gid == 1001 else sub_1002).read_text(encoding="utf-8"))

        out = enrich_teams_with_tiers(
            soup,
            teams_by_bracket={},
            event_id="inverse",
            event_key="ek",
            run_id="rid",
            subpage_fetcher=fetcher,
            max_concurrent_subfetches=2,
            base_dir=tmp_path,
        )
        # team 12345 must resolve to gid 1001 (catalog/document order),
        # NOT gid 1002 (which completed first under concurrency).
        assert out["12345"].group_id == 1001
        assert out["12345"].tier_membership_source == "ambiguous_multi_tier"
        # Singletons resolved as expected.
        assert out["99001"].group_id == 1001
        assert out["99002"].group_id == 1002


class TestEnrichmentResultShape:
    def test_returns_frozen_dataclasses(self, tmp_path):
        soup = BeautifulSoup(_two_tier_landing(), "html.parser")
        fetcher = _make_fetcher({1001: _subpage(_team_html([100])), 1002: _subpage(_team_html([200]))})
        out = enrich_teams_with_tiers(
            soup,
            teams_by_bracket={},
            event_id="X",
            event_key="ek",
            run_id="rid",
            subpage_fetcher=fetcher,
            base_dir=tmp_path,
        )
        for result in out.values():
            assert isinstance(result, EnrichmentResult)
            with pytest.raises(AttributeError):
                result.group_id = 99  # type: ignore[misc]


class TestSafeFilenameToken:
    """Windows rejects ``<>:"/\\|?*`` in filenames; the abort-artifact filename
    must sanitize the ISO ``run_id`` while the payload preserves it."""

    def test_iso_run_id_round_trip(self):
        from src.scrapers.gotsport_tier_parser import _safe_filename_token

        assert _safe_filename_token("2026-04-29T00:00:00+00:00") == "2026-04-29T00-00-00_00-00"

    def test_no_op_when_no_specials(self):
        from src.scrapers.gotsport_tier_parser import _safe_filename_token

        assert _safe_filename_token("rid") == "rid"

    @pytest.mark.parametrize("ch", ["<", ">", ":", '"', "/", "\\", "|", "?", "*"])
    def test_strips_every_windows_reserved_char(self, ch):
        from src.scrapers.gotsport_tier_parser import _safe_filename_token

        out = _safe_filename_token(f"a{ch}b")
        assert ch not in out, f"reserved char {ch!r} survived sanitization: {out!r}"
