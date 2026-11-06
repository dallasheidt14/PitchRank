"""
Affinity Sports GA game matcher - Georgia Soccer's fall league (gs.sportsaffinity.com).

Georgia Soccer's pages follow the Oregon conventions and its names the state league ones, so
that matcher applies, with Georgia's state and these changes for how the league writes names:

- A name states its age in many forms ('B17U', 'U13B', '13UG', 'Boys 13U', '14/15B', '2014B').
  Those with the U after the number are respelled ('B14U' and 'BA12U' are 'U14' and 'U12', 'COS CREW14U' is
  'COS CREW U14'), which ``read_label`` and the UT club reader can both read. A bare 'B14' is
  'U14' too, because each bare form sits in a division of its own number and 'B15' as a birth
  year is a u12 team in u15 GPL.
- GPL and CH are league tags that change by season, so they are no squad's own words, as CF
  already is for being a generic club word, and neither is BVBIA, how stored rows spell BVB IA.
  'Pre-GPL' is written as 'GPL', so PRE stays a squad word and 'Pre-ECNL' is not 'ECNL'. GA stays
  a squad word too: it also means Girls Academy, which is a different squad.
- A club's branch ('South', 'Oconee', 'PTC', 'Waycross', 'Griffin') is a squad word, so a
  written club stops short of it.
- The squad-word rule replaces the variant gate, which would take a league tag, the gender
  letter of 'U15 B' or the 'SC-' of 'SC-U15B' for a squad and refuse a stored team over it.
- A club's one live stored row carrying the league's own name is that team, even where a
  duplicate, live or merged away, would tie with it and refuse them both.
"""

import logging
import re
from typing import Dict, Optional

from src.models.affinity_state_league_matcher import AffinityStateLeagueMatcher
from src.models.squad_name_gates import is_same_club
from src.tournaments.cohort_labels import read_label

logger = logging.getLogger(__name__)

_PRE_GPL = re.compile(r"\bPre[- ]GPL\b", re.IGNORECASE)
_U_AFTER_AGE = re.compile(r"\b(?:B[AR]?|G)?(\d{2})U[BG]?\b", re.IGNORECASE)
_GLUED_AGE = re.compile(r"\b(CREW)(\d{2})U\b", re.IGNORECASE)
_BARE_AGE = re.compile(r"(?<![A-Za-z0-9/])B(\d{2})(?![A-Za-z0-9/])", re.IGNORECASE)

# How the league writes a club, against the name PitchRank stores it under; each pairing is
# read from stored Georgia rows. A club mapping to itself is one the UT reader cuts wrongly.
_GA_CLUBS = {
    "BVB IA Georgia": "BVB IA Georgia",
    "All-In FC Sugar Hill": "All-IN FC Sugar Hill",
    "AFC Lightning": "AFC Lightning",
    "Georgia Wolves": "Georgia Wolves SC",
    "Georgia Athletic SC": "Georgia Athletic Soccer Club",
    "Hinesville": "Hinesville Soccer Association",
    "TCSA United": "Toombs County Soccer Association",
    "TCSA Flames": "Toombs County Soccer Association",
    "Coastal Outre": "Coastal Outreach Soccer Prog.",
    "Coastal Outreach": "Coastal Outreach Soccer Prog.",
    "Football Club OLeary": "FC O'Leary",
    "Path Academy FC": "PATH ACADEMY FC",
    "Piedmont SA": "Piedmont SA",
    "Alianza Soccer": "Alianza Soccer Club",
    "Bryson Park Soccer": "Bryson Park",
    "Bryson Park Flash Soccer": "Bryson Park",
    "Atlanta Furious": "Atlanta Furious",
    "GUSA Rome": "Georgia United SA",
    "Champions FC": "Champions FC",
}


def _respelled(name: Optional[str]) -> str:
    """'Pre-GPL' and the ages with a U after the number respelled, which also holds for a stored name."""
    tagged = _PRE_GPL.sub("GPL", name or "")
    return _GLUED_AGE.sub(r"\1 U\2", _U_AFTER_AGE.sub(r"U\1", tagged))


class AffinityGAGameMatcher(AffinityStateLeagueMatcher):
    """Affinity GA matcher: the state league matcher with Georgia's state and the league's name conventions."""

    state_code = "GA"
    state_name = "Georgia"
    clubs = _GA_CLUBS
    not_squad_words = frozenset({"GPL", "CH", "BVBIA"})

    def __init__(self, supabase, provider_id=None, alias_cache=None, dry_run=False):
        super().__init__(supabase, provider_id=provider_id, alias_cache=alias_cache, dry_run=dry_run)
        self._affinity_variant_gate_required = False

    def _prepared(self, name: Optional[str]) -> str:
        """The league's forms respelled for ``read_label`` and the UT club reader."""
        return _BARE_AGE.sub(r"U\1", _respelled(name))

    def _own_board(self, team_name: Optional[str]) -> Optional[str]:
        return read_label(self._prepared(team_name)).cohort or None

    def _squads_conflict(self, provider_name: str, candidate_name: str) -> bool:
        """Compared as respelled, so the U-age check reads 'CREW18U'. A stored bare 'B14' may be a birth year."""
        return super()._squads_conflict(self._prepared(provider_name), _respelled(candidate_name))

    def _fuzzy_match_team(
        self, team_name: str, age_group: str, gender: str, club_name: Optional[str] = None
    ) -> Optional[Dict]:
        stored = self._stored_under_own_name(team_name, age_group, gender, club_name)
        if stored:
            return {"team_id": stored["team_id_master"], "team_name": stored["team_name"], "confidence": 1.0}
        return super()._fuzzy_match_team(team_name, age_group, gender, club_name)

    def _stored_under_own_name(
        self, team_name: str, age_group: str, gender: str, club_name: Optional[str]
    ) -> Optional[Dict]:
        """The club's one live stored team in Georgia on this board under exactly this name."""
        try:
            rows = (
                self.db.table("teams")
                .select("team_id_master, team_name, club_name")
                .eq("team_name", team_name)
                .eq("age_group", age_group.lower())
                .eq("gender", gender)
                .eq("state_code", self.state_code)
                .eq("is_deprecated", False)
                .execute()
            ).data or []
        except Exception as e:  # a read failure falls back to the fuzzy match
            logger.debug(f"[AffinityGA] Exact name lookup failed for {team_name!r}: {e}")
            return None
        threshold = self._affinity_club_similarity_threshold
        club = self._club_for(team_name, club_name)
        ours = [row for row in rows if is_same_club(club, row.get("club_name") or "", threshold)]
        return ours[0] if len(ours) == 1 else None
