"""Tier 1 fixture replay: real captured event HTMLs end-to-end.

For each event, loads the landing fixture, builds a mocked
``subpage_fetcher`` that returns the captured ``event_<eid>__group_<gid>.html``
files, and asserts the orchestrator produces the expected enrichment
shape. Missing per-tier fixtures are tolerated via ``pytest.mark.skipif``
so a partial capture (e.g., CAPTCHA-gated subpage) never breaks CI.

Synthetic-fixture coverage (single_tier, unknown_prefix, id_collision,
inverse_collision, captcha_subfetch) lives in the second half of the file.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from src.scrapers.gotsport import EventCaptchaGatedError
from src.scrapers.gotsport_tier_parser import (
    EventTeamMembershipCollisionError,
    FetchedSubpage,
    enrich_teams_with_tiers,
    extract_tier_catalog,  # noqa: F401  (used in TestEvent47021CaptchaLanding only — keep flat import)
)

FIXTURES = Path(__file__).parent.parent / "fixtures" / "gotsport"


def _subpage(html: str) -> FetchedSubpage:
    return FetchedSubpage(
        html=html,
        final_url="https://system.gotsport.com/...",
        zr_final_url=None,
        redirect_locations=[],
    )


def _fetcher_from_disk(event_id: str):
    """Build a fetcher that reads ``event_<eid>__group_<gid>.html`` lazily.

    Raises ``FileNotFoundError`` when a captured subpage is missing — the
    orchestrator wraps it as ``TierSubfetchError(http_error)``.
    """

    def fetcher(gid: int) -> FetchedSubpage:
        path = FIXTURES / f"event_{event_id}__group_{gid}.html"
        return _subpage(path.read_text(encoding="utf-8"))

    return fetcher


def _has_subpages_for(event_id: str, group_ids: list[int]) -> bool:
    return all((FIXTURES / f"event_{event_id}__group_{gid}.html").exists() for gid in group_ids)


# ---------------------------------------------------------------------------
# Comprehensive coverage — event 49371 (smallest in-scope, all tiers captured)
# ---------------------------------------------------------------------------


class TestEvent49371Comprehensive:
    """Brazas Ginga — uppercase ``U-13 BOYS GOLD`` form. ~18 in-scope groups."""

    EVENT_ID = "49371"
    # All in-scope U10+ gids per the captured corpus (excludes 485437 U-8,
    # 485438 U-7, 485443 U-9 GIRLS — those are micro-cohort skips).
    IN_SCOPE_GIDS = [
        485294, 485295, 485296, 485297, 485298, 485299, 485300, 485301,
        485425, 485434, 485435, 485436, 485439, 485440, 485441, 485442,
        485444, 485513,
    ]

    @pytest.fixture
    def landing_soup(self):
        return BeautifulSoup(
            (FIXTURES / f"event_{self.EVENT_ID}.html").read_text(encoding="utf-8"),
            "html.parser",
        )

    def test_full_subfetch_against_captured_corpus(self, landing_soup, tmp_path):
        if not _has_subpages_for(self.EVENT_ID, self.IN_SCOPE_GIDS):
            pytest.skip(f"event {self.EVENT_ID} subpages not fully captured")
        fetcher = _fetcher_from_disk(self.EVENT_ID)
        out = enrich_teams_with_tiers(
            landing_soup,
            teams_by_bracket={},
            event_id=self.EVENT_ID,
            event_key=f"gotsport__{self.EVENT_ID}__unknown",
            run_id="rid",
            subpage_fetcher=fetcher,
            base_dir=tmp_path,
        )
        # Assert at least the captured group_ids appear in enrichment.
        gids_seen = {r.group_id for r in out.values()}
        for gid in self.IN_SCOPE_GIDS:
            assert gid in gids_seen, f"missing enrichment for gid {gid}"
        # Uppercase residues preserved (e.g., "GOLD" / "SILVER").
        residues = {r.group_name for r in out.values() if r.group_name}
        assert "GOLD" in residues
        assert "SILVER" in residues
        # Non-zero team count.
        assert len(out) > 50


# ---------------------------------------------------------------------------
# Sampled coverage — 7 other captured events
# ---------------------------------------------------------------------------


SAMPLED_EVENTS = [
    pytest.param(
        "42433",
        [365847, 365850, 365849],
        {"Red", "White", "Blue"},
        id="42433_color_tiers",
    ),
    pytest.param(
        "44692",
        [391315, 391318, 474710],
        {"Gold", "Silver 1", "Silver 2"},
        id="44692_birth_year_silver_n",
    ),
    pytest.param(
        "46103",
        [478925, 478952, 479440],
        {"Tolkin", "Reyna", "Sonnett"},
        id="46103_surname_tiers",
    ),
    pytest.param(
        "50469",
        [477680, 477685, 477692],
        {"Red"},  # All three captured gids are "Red" tiers
        id="50469_bare_u_token",
    ),
    pytest.param(
        "46958",
        [409815, 409827, 409838],
        # Captured corpus: 409815=U10B Elite White, 409827=U12B Premier,
        # 409838=U15B Premier — Form 11 ``UxxB`` glued prefix preserved across
        # multi-word ("Elite White") and single-word ("Premier") residues.
        {"Elite White", "Premier"},
        id="46958_form11_glued",
    ),
    pytest.param(
        "49407",
        [436891, 436907, 436924],
        {"GOLD A DIVISION", "GOLD DIVISION"},  # form 5 multi-word residue
        id="49407_form5_multiword",
    ),
    pytest.param(
        "45394",
        [469715, 469721, 469726],
        {"Blue", "Gold"},
        id="45394_bare_u_token",
    ),
]


@pytest.mark.parametrize("event_id,gids,expected_residues", SAMPLED_EVENTS)
def test_sampled_event_subfetches_resolve_residues(event_id, gids, expected_residues, tmp_path):
    if not _has_subpages_for(event_id, gids):
        pytest.skip(f"event {event_id} subpages not fully captured")
    soup = BeautifulSoup(
        (FIXTURES / f"event_{event_id}.html").read_text(encoding="utf-8"),
        "html.parser",
    )
    fetcher = _fetcher_from_disk(event_id)

    # We need to limit which gids actually run subfetches. The orchestrator
    # walks the full landing catalog by default. Trim the soup by removing
    # rows for any ``?group=`` anchor whose gid isn't in our sampled set.
    # IMPORTANT: collect rows-to-drop FIRST, then decompose — calling
    # ``row.decompose()`` mid-iteration leaves stale Tag objects in the
    # remaining list (with ``attrs == None``) and ``a.get(...)`` crashes.
    rows_to_drop = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "schedules?group=" not in href:
            continue
        if any(f"group={g}" in href for g in gids):
            continue
        parent = a.find_parent()
        row = parent.find_parent() if parent else None
        if row is not None:
            rows_to_drop.append(row)
    for row in rows_to_drop:
        row.decompose()

    # Now run with a fetcher that only knows our sampled gids.
    out = enrich_teams_with_tiers(
        soup,
        teams_by_bracket={},
        event_id=event_id,
        event_key=f"gotsport__{event_id}__unknown",
        run_id="rid",
        subpage_fetcher=fetcher,
        base_dir=tmp_path,
    )
    seen_residues = {r.group_name for r in out.values() if r.group_name}
    for residue in expected_residues:
        assert residue in seen_residues, (
            f"event {event_id}: expected residue {residue!r} not found; "
            f"got {sorted(seen_residues)}"
        )


# ---------------------------------------------------------------------------
# Captcha-gated landing — graceful-empty path (Shell 02 owns detection)
# ---------------------------------------------------------------------------


class TestEvent47021CaptchaLanding:
    """Confirms the Shell 01 helper does NOT crash on a captcha body.

    Captcha detection at the LANDING-page boundary lives in Shell 02's
    ``_fetch_event_page``, which runs BEFORE the orchestrator. In Shell
    01's isolated context, the helper sees a captcha-body soup and treats
    it as empty discovery (no ?group= anchors → empty catalog → empty
    enrichment dict). NO ``EventCaptchaGatedError`` is raised by Shell 01.
    """

    EVENT_ID = "47021"
    LANDING = FIXTURES / "event_47021.html"

    @pytest.mark.skipif(
        not LANDING.exists(),
        reason="event_47021.html capture missing — captcha may have cleared",
    )
    def test_graceful_empty_no_captcha_error_raised(self, tmp_path):
        soup = BeautifulSoup(self.LANDING.read_text(encoding="utf-8"), "html.parser")
        # Pure-helper assertion: empty catalog.
        catalog = extract_tier_catalog(soup, event_id=self.EVENT_ID)
        assert catalog == {}
        # Orchestrator assertion: empty enrichment, NO captcha error.
        out = enrich_teams_with_tiers(
            soup,
            teams_by_bracket={},
            event_id=self.EVENT_ID,
            event_key=f"gotsport__{self.EVENT_ID}__unknown",
            run_id="rid",
            subpage_fetcher=lambda gid: pytest.fail("must not subfetch"),
            base_dir=tmp_path,
        )
        assert out == {}
        # Metrics file present, total_candidates=0.
        payload = json.loads(
            (tmp_path / f"gotsport__{self.EVENT_ID}__unknown" / "intake" / "tier_parse_metrics.json").read_text()
        )
        assert payload["total_candidates"] == 0


# ---------------------------------------------------------------------------
# Synthetic fixtures
# ---------------------------------------------------------------------------


class TestSyntheticSingleTier:
    def test_zero_group_anchors_returns_empty(self, tmp_path):
        path = FIXTURES / "event_synthetic_single_tier.html"
        soup = BeautifulSoup(path.read_text(encoding="utf-8"), "html.parser")
        out = enrich_teams_with_tiers(
            soup,
            teams_by_bracket={},
            event_id="single",
            event_key="ek",
            run_id="rid",
            subpage_fetcher=lambda gid: pytest.fail("must not subfetch"),
            base_dir=tmp_path,
        )
        assert out == {}
        payload = json.loads((tmp_path / "ek" / "intake" / "tier_parse_metrics.json").read_text())
        assert payload["total_candidates"] == 0
        assert payload["unknown_prefix_count"] == 0
        assert payload["gated_at_threshold"] is False


class TestSyntheticUnknownPrefix:
    def test_residue_persisted_as_unknown_prefix(self, tmp_path):
        path = FIXTURES / "event_synthetic_unknown_prefix.html"
        soup = BeautifulSoup(path.read_text(encoding="utf-8"), "html.parser")

        def fetcher(gid):
            return _subpage('<a href="?team=12345">x</a>')

        out = enrich_teams_with_tiers(
            soup,
            teams_by_bracket={},
            event_id="unknown",
            event_key="ek",
            run_id="rid",
            subpage_fetcher=fetcher,
            base_dir=tmp_path,
        )
        assert "12345" in out
        result = out["12345"]
        assert result.tier_parse_outcome == "unknown_prefix"
        assert result.group_name == "Adult Co-Ed Hammer"


class TestSyntheticIdCollision:
    def test_forward_collision_raises(self, tmp_path):
        path = FIXTURES / "event_synthetic_id_collision.html"
        soup = BeautifulSoup(path.read_text(encoding="utf-8"), "html.parser")
        with pytest.raises(EventTeamMembershipCollisionError) as excinfo:
            enrich_teams_with_tiers(
                soup,
                teams_by_bracket={},
                event_id="collision",
                event_key="ek",
                run_id="rid",
                subpage_fetcher=lambda gid: pytest.fail("must not subfetch"),
                base_dir=tmp_path,
            )
        assert excinfo.value.mode == "forward"


class TestSyntheticInverseCollision:
    def test_default_marks_ambiguous(self, tmp_path):
        landing = FIXTURES / "event_synthetic_inverse_collision.html"
        sub_1001 = (FIXTURES / "event_synthetic_inverse_collision__group_1001.html").read_text(encoding="utf-8")
        sub_1002 = (FIXTURES / "event_synthetic_inverse_collision__group_1002.html").read_text(encoding="utf-8")
        soup = BeautifulSoup(landing.read_text(encoding="utf-8"), "html.parser")

        def fetcher(gid):
            return _subpage(sub_1001 if gid == 1001 else sub_1002)

        out = enrich_teams_with_tiers(
            soup,
            teams_by_bracket={},
            event_id="inverse",
            event_key="ek",
            run_id="rid",
            subpage_fetcher=fetcher,
            base_dir=tmp_path,
        )
        # team 12345 in BOTH gids → marked ambiguous, resolves to first.
        assert out["12345"].group_id == 1001
        assert out["12345"].tier_membership_source == "ambiguous_multi_tier"
        # Singletons resolve to their own gid, plain provenance.
        assert out["99001"].group_id == 1001
        assert out["99001"].tier_membership_source == "subpage"
        assert out["99002"].group_id == 1002

    def test_strict_mode_raises(self, tmp_path, monkeypatch):
        from src.scrapers import gotsport_tier_parser as gtp

        monkeypatch.setattr(gtp, "INVERSE_COLLISION_STRICT_MODE", True)
        landing = FIXTURES / "event_synthetic_inverse_collision.html"
        sub_1001 = (FIXTURES / "event_synthetic_inverse_collision__group_1001.html").read_text(encoding="utf-8")
        sub_1002 = (FIXTURES / "event_synthetic_inverse_collision__group_1002.html").read_text(encoding="utf-8")
        soup = BeautifulSoup(landing.read_text(encoding="utf-8"), "html.parser")

        def fetcher(gid):
            return _subpage(sub_1001 if gid == 1001 else sub_1002)

        with pytest.raises(EventTeamMembershipCollisionError) as excinfo:
            enrich_teams_with_tiers(
                soup,
                teams_by_bracket={},
                event_id="inverse",
                event_key="ek",
                run_id="rid",
                subpage_fetcher=fetcher,
                base_dir=tmp_path,
            )
        assert excinfo.value.mode == "inverse"
        assert excinfo.value.team_id == "12345"


class TestSyntheticCaptchaSubfetch:
    def test_mid_orchestration_captcha_raises(self, tmp_path):
        # Use a 1-tier landing soup; the synthetic captcha body lives in the
        # subfetch response, not the landing.
        landing = """
        <html><body>
        <div><div>
          <b>U13 Boys Red</b>
          <a href="/schedules?group=42">Schedule</a>
        </div></div>
        </body></html>
        """
        soup = BeautifulSoup(landing, "html.parser")
        captcha_body = (FIXTURES / "event_synthetic_captcha_subfetch.html").read_text(encoding="utf-8")

        def fetcher(gid):
            return _subpage(captcha_body)

        with pytest.raises(EventCaptchaGatedError):
            enrich_teams_with_tiers(
                soup,
                teams_by_bracket={},
                event_id="X",
                event_key="ek",
                run_id="rid",
                subpage_fetcher=fetcher,
                base_dir=tmp_path,
            )
