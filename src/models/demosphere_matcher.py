"""
Demosphere game matcher (elements.demosphere.com, one site id per league).

Demosphere teams are registered by a roster pass in ``scripts/import_demosphere.py``, which hands
the matcher a stored club and the club as the team's own name writes it ("Villarreal Virginia
Academy" beside "Villarreal VA Azul G2013/14"), as Tourney Central's does. A created team keeps
the full name its schedule gives it. So this reuses that matcher whole.
"""

from typing import Dict, Optional

from src.models.tourneycentral_matcher import TourneyCentralGameMatcher


def expand_club_code(team_name: str, club_name: Optional[str]) -> str:
    """``team_name`` with its leading club code spelled out when the stored club starts with it.

    NCSL writes ``HERN NCSL B2011/12 White`` for the team stored as ``Herndon NCSL B2011/12 White``;
    spelled out, the stored team is an exact name match instead of a tie with every other white squad
    of the club.
    """
    first, _, rest = team_name.partition(" ")
    word = (club_name or "").split(" ", 1)[0]
    if rest and 3 <= len(first) < len(word) and word.lower().startswith(first.lower()):
        return f"{word} {rest}"
    return team_name


class DemosphereGameMatcher(TourneyCentralGameMatcher):
    """Tourney Central matching for Demosphere league schedules."""

    def _fuzzy_match_team(
        self,
        team_name: str,
        age_group: str,
        gender: str,
        club_name: Optional[str] = None,
        state_code: Optional[str] = None,
    ) -> Optional[Dict]:
        match = super()._fuzzy_match_team(
            expand_club_code(team_name, club_name), age_group, gender, club_name, state_code
        )
        if match is None:
            return None
        return {"team_id": match["team_id"], "team_name": match["team_name"], "confidence": match["confidence"]}
