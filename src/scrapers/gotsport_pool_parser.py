"""Pool-play structure parser for gotsport schedule pages.

Each tier subpage (``/org_event/events/{event_id}/schedules?group={group_id}``)
renders a Bootstrap collapse panel per round-robin pool. The standings
panel for each pool lives at::

    <a role="button" aria-controls="collapse-{bracket_id}">Bracket A</a>
    ...
    <div id="collapse-{bracket_id}">
      <table>
        <tbody>
          <tr><td>1</td><td><a href="...?team={pid}">Team Name</a></td>...</tr>
          ...
        </tbody>
      </table>
    </div>

Per-day schedule sections re-use the SAME panel id but with text like
``"Bracket A | Feb 13, 2026"``. The standings anchors are the ones whose
text is exactly ``"Bracket {label}"`` (no pipe). We match on that to avoid
double-counting.

This parser is read-only HTML inspection — no HTTP, no captcha logic, no
rate limiting. Callers fetch via ``GotsportScraper._fetch_event_page``
(which already handles ZenRows / captcha gating) and feed the response
text into ``parse_pool_assignments_from_html``.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

__all__ = [
    "PoolAssignment",
    "parse_pool_assignments_from_html",
]


# Pool-label headings render as ``<a role="button">Bracket A</a>``. Reject
# the per-day schedule anchors (``"Bracket A | Feb 13, 2026"``) that
# share the same aria-controls but mean a schedule section, not a
# standings panel.
_POOL_LABEL_PATTERN = re.compile(r"^Bracket\s+(\S+)$")
_TEAM_ID_PATTERN = re.compile(r"team=(\d+)")


@dataclass(frozen=True)
class PoolAssignment:
    """One round-robin pool inside a tier.

    ``label`` is the gotsport pool label as rendered (``"A"``, ``"B"``,
    ``"1"``, etc.). ``bracket_id`` is gotsport's internal bracket primary
    key — extracted from the ``collapse-{id}`` panel anchor. Surfaced so
    callers can correlate to gotsport's tiebreaker URLs without re-parsing.
    ``provider_team_ids`` preserves the on-page row order (which is
    finishing order for completed events).
    """

    label: str
    bracket_id: str
    provider_team_ids: tuple[str, ...]

    @property
    def team_count(self) -> int:
        return len(self.provider_team_ids)


def parse_pool_assignments_from_html(html: str) -> list[PoolAssignment]:
    """Extract round-robin pool assignments from a tier's schedule page.

    Returns one ``PoolAssignment`` per standings panel. Empty list when
    the page has no recognized pool headings (e.g., a tier rendered as
    pure knockout with no group play). Pools with no team rows are
    dropped — those are typically aggregate / placeholder panels.
    """
    soup = BeautifulSoup(html, "html.parser")
    pools: list[PoolAssignment] = []
    seen_panel_ids: set[str] = set()

    for anchor in soup.find_all("a", attrs={"role": "button"}):
        text = anchor.get_text(" ", strip=True)
        match = _POOL_LABEL_PATTERN.match(text)
        if not match:
            continue
        label = match.group(1)
        panel_id = anchor.get("aria-controls") or (anchor.get("href") or "").lstrip("#")
        if not panel_id or panel_id in seen_panel_ids:
            continue
        panel = soup.find(id=panel_id)
        if panel is None:
            continue
        team_ids = _extract_team_ids(panel)
        if not team_ids:
            continue
        seen_panel_ids.add(panel_id)
        bracket_id = panel_id.removeprefix("collapse-") if panel_id.startswith("collapse-") else panel_id
        pools.append(PoolAssignment(label=label, bracket_id=bracket_id, provider_team_ids=tuple(team_ids)))

    return pools


def _extract_team_ids(panel) -> list[str]:
    """Pull provider team IDs out of a standings panel's team-link rows."""
    team_ids: list[str] = []
    for link in panel.find_all("a", href=_TEAM_ID_PATTERN):
        match = _TEAM_ID_PATTERN.search(link.get("href") or "")
        if match:
            team_ids.append(match.group(1))
    return team_ids
