"""
Heartland Soccer game matcher (heartlandsoccer.net, the Kansas City Premier league).

The roster pass in ``scripts/import_heartland.py`` hands the matcher the club as PitchRank
stores it ("Sporting Blue Valley" beside "SBV IP Lions FC") and the club as the team's own
name writes it, and a created team keeps its full name. That is the case
``TourneyCentralGameMatcher`` handles.

Kansas City clubs are stored on both sides of the state line, and a team
whose club has no settled state reaches the roster pass with none. Athletes2Events matching
searches one state and refuses a team with none, so such a team could never find the stored
team it already is. In the roster pass this matcher searches Kansas, Missouri and stateless
teams for every team. A team's own state still earns its location score and wins a tie;
a stateless team stands neutral between the states, so equally good teams in two of them go
to review. A stateless team is still never created: the inherited ``_match_team`` creates only
a team with a state. Outside the roster pass (the game import) nothing changes, so
that import stays alias-only.
"""

from typing import Dict, Optional

from src.models.tourneycentral_matcher import TourneyCentralGameMatcher

REGION = ("KS", "MO")
# Stands in for a missing state while matching. It equals no stored state_code, so it earns
# no location score and wins no tie-break; it must never reach _match_team, whose create
# gate opens for any truthy state.
REGION_SEARCH = "KS/MO"


class HeartlandGameMatcher(TourneyCentralGameMatcher):
    """Tourney Central matching, across Kansas and Missouri in the roster pass, for the Heartland Premier league."""

    def _candidate_state_filter(self, state_code: str) -> str:
        if not self.registration_mode:
            return super()._candidate_state_filter(state_code)
        return ",".join([*(f"state_code.eq.{state}" for state in REGION), "state_code.is.null"])

    def _fuzzy_match_team(
        self,
        team_name: str,
        age_group: str,
        gender: str,
        club_name: Optional[str] = None,
        state_code: Optional[str] = None,
    ) -> Optional[Dict]:
        if self.registration_mode and not state_code:
            state_code = REGION_SEARCH
        match = super()._fuzzy_match_team(team_name, age_group, gender, club_name, state_code)
        if match is None:
            return None
        return {"team_id": match["team_id"], "team_name": match["team_name"], "confidence": match["confidence"]}
