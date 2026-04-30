"""``EventTeam`` dataclass — extracted from ``gotsport.py`` so pure tier-parser
helpers can import it without dragging the full scraper class (and its
``requests`` / ``urllib3`` / ``certifi`` transitive imports) into the import
graph. ``gotsport.py`` re-exports ``EventTeam`` for back-compat.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class EventTeam:
    """Team information within an event bracket/group"""

    team_id: str
    team_name: str
    bracket_name: str
    group_name: Optional[str] = None  # Group name (e.g., "Group A", "Pool A")
    age_group: Optional[str] = None  # Team's ACTUAL age group (e.g., "U11")
    gender: Optional[str] = None
    division: Optional[str] = None
    playing_up: bool = False  # True if team is playing in a bracket above their age group
