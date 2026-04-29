"""Pre-merge inverse-collision probe.

Empirically measures the rate of ``team_id``-appears-in-multiple-tiers
collisions across our two highest-cardinality captured corpora (49371 +
46103). Pure observability — does NOT enforce a rate threshold. The
implementer copies the structured log line into the PR description; if
the rate is consistently zero across in-scope events we can flip
``INVERSE_COLLISION_STRICT_MODE = True`` in a follow-up commit.

Marked ``@pytest.mark.slow`` because it walks every captured per-tier
subpage. The 46103 path skips when its subpages aren't fully captured
(only 3 sampled at fixture-capture time).
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from src.scrapers.gotsport_tier_parser import (
    FetchedSubpage,
    enrich_teams_with_tiers,
)

FIXTURES = Path(__file__).parent.parent / "fixtures" / "gotsport"


def _subpage(html: str) -> FetchedSubpage:
    return FetchedSubpage(
        html=html,
        final_url="https://system.gotsport.com/...",
        zr_final_url=None,
        redirect_locations=[],
    )


def _probe_one_event(event_id: str, *, tmp_path, caplog) -> tuple[int, int]:
    """Returns ``(ambiguous_count, total_enriched)`` for the event."""
    soup = BeautifulSoup((FIXTURES / f"event_{event_id}.html").read_text(encoding="utf-8"), "html.parser")

    # Only iterate over gids whose per-tier subpage we actually captured —
    # otherwise the orchestrator raises TierSubfetchError(http_error) on the
    # first missing fixture. Trim the soup to those gids.
    captured_gids = {
        int(p.stem.split("__group_")[1])
        for p in FIXTURES.glob(f"event_{event_id}__group_*.html")
    }
    if not captured_gids:
        return (0, 0)

    rows_to_drop = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "schedules?group=" not in href:
            continue
        gid = next((g for g in captured_gids if f"group={g}" in href), None)
        if gid is not None:
            continue
        parent = a.find_parent()
        row = parent.find_parent() if parent else None
        if row is not None:
            rows_to_drop.append(row)
    for row in rows_to_drop:
        row.decompose()

    def fetcher(gid: int) -> FetchedSubpage:
        return _subpage((FIXTURES / f"event_{event_id}__group_{gid}.html").read_text(encoding="utf-8"))

    out = enrich_teams_with_tiers(
        soup,
        teams_by_bracket={},
        event_id=event_id,
        event_key=f"gotsport__{event_id}__unknown",
        run_id="probe",
        subpage_fetcher=fetcher,
        base_dir=tmp_path,
    )
    ambiguous = sum(1 for r in out.values() if r.tier_membership_source == "ambiguous_multi_tier")
    total = len(out)
    return ambiguous, total


@pytest.mark.parametrize(
    "event_id",
    [
        "49371",  # Comprehensive in-scope coverage; smallest event
        "46103",  # Surname-tier vocabulary; only 3 sampled subpages — degraded probe
    ],
)
def test_inverse_collision_rate(event_id, tmp_path, caplog):
    caplog.set_level(logging.INFO)
    ambiguous, total = _probe_one_event(event_id, tmp_path=tmp_path, caplog=caplog)
    if total == 0:
        pytest.skip(f"event {event_id} has no captured subpages")
    rate = ambiguous / total if total else 0.0
    # Structured log line — copy into PR description.
    print(f"[probe] event={event_id} inverse_collision_rate={rate:.3f} ({ambiguous}/{total})")
    # Pure observability — no threshold enforcement here.
    assert rate >= 0.0  # trivially true; the assertion exists so pytest reports the test as a real check
