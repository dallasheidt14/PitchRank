"""
Tourney Central game matcher (tourneycentral.com, one subdomain per tournament).

Tourney Central teams are registered by a roster pass in
``scripts/import_tourneycentral_event.py``, as Athletes2Events teams are, and need the
same matching: the club gate (the driver passes the team list's club as ``club_name``
and the club as the team name writes it as ``written_club``), the squad and tier gates,
state scoping, and review for ties. So this reuses that matcher whole.

Two things differ, both because each team list prints the club in a field of its
own, often spelled differently from the name's own prefix ("Warrior Soccer Club"
beside "Warrior SC B15/16 White"). Candidates are gated on that field and, when it
matches none, on the club as the name writes it. And the team name is the team's
full registered name: the Athletes2Events habit of cutting the club off the front of
a created team's name would store "U11B Green" for "Club Ohio Dayton U11B Green", so a
created Tourney Central team keeps its full name.
"""

from typing import Dict, Optional, Tuple

from src.models.athletes2events_matcher import Athletes2EventsGameMatcher, _squad_marks
from src.models.tournament_name_gates import is_boys
from src.utils.team_name_utils import resolve_distinction
from src.utils.us_states import STATE_CODE_TO_NAME


def club_before_squad_marks(written_club: Optional[str]) -> Optional[str]:
    """``written_club`` cut back until no squad mark is left in it.

    For a written club guessed from the words before the age, not for a club field
    that opens the name. The squad gates strip the written club from the team's name,
    so a guess that runs on past the club ("Lakota FC Pre", "Ohio Premier North",
    "Worthington United Navy 1") strips a tier, direction, color or squad number with
    it, and a stored row without that mark then matches. A club field is the club
    itself, and its own words ("Elite FC", "Dayton Futbol Academy") are not marks:
    cutting it would leave them in the name and miss the club's stored squads.
    """
    words = (written_club or "").split()
    while words and any(_squad_marks(" ".join(words)).values()):
        words.pop()
    return " ".join(words) or None


class TourneyCentralGameMatcher(Athletes2EventsGameMatcher):
    """Athletes2Events matching; a created team keeps the name its team list gives it."""

    def _fuzzy_match_team(
        self,
        team_name: str,
        age_group: str,
        gender: str,
        club_name: Optional[str] = None,
        state_code: Optional[str] = None,
    ) -> Optional[Dict]:
        """Gate on the team list's club, and failing that on the club as the name writes it.

        The two are often different words ("Valentis" beside "VASC B12/13"), and a stored
        row can carry the second in its name while its club field holds a third, so the
        team list's club alone would decline it and create a duplicate.
        """
        gate_clubs = [club_name]
        written = self._written_club
        if written and written.lower() != (club_name or "").lower():
            gate_clubs.append(written)
        for gate_club in gate_clubs:
            match = super()._fuzzy_match_team(team_name, age_group, gender, gate_club, state_code)
            if match is not None:
                return {"team_id": match["team_id"], "team_name": match["team_name"], "confidence": match["confidence"]}
        return None

    def _create_new_athletes2events_team(
        self,
        team_name: str,
        club_name: Optional[str],
        age_group: str,
        gender: str,
        provider_id: Optional[str],
        provider_team_id: Optional[str] = None,
        state_code: Optional[str] = None,
    ) -> Tuple[str, bool]:
        """A team already carrying this Tourney Central id is returned with ``was_created`` False."""
        if provider_id and provider_team_id:
            try:
                existing = (
                    self.db.table("teams")
                    .select("team_id_master")
                    .eq("provider_id", provider_id)
                    .eq("provider_team_id", provider_team_id)
                    .single()
                    .execute()
                )
                if existing.data:
                    return existing.data["team_id_master"], False
            except Exception:
                # PostgREST raises PGRST116 on a zero-row .single(), which is the
                # normal path for a team this run has never seen.
                pass

        team_id_master = self._new_team_id_master(provider_id, provider_team_id, team_name, age_group, gender)
        clean_team_name = " ".join(team_name.replace("\xa0", " ").split())
        team_data = {
            "team_id_master": team_id_master,
            "team_name": clean_team_name,
            "club_name": club_name or clean_team_name,
            "age_group": age_group.lower(),
            "gender": "Male" if is_boys(gender) else "Female",
            "state_code": state_code,
            "state": STATE_CODE_TO_NAME.get(state_code) if state_code else None,
            "provider_id": provider_id,
            "provider_team_id": provider_team_id,
            "distinction": resolve_distinction(clean_team_name, club_name, state_code),
        }
        if not self.dry_run:
            self.db.table("teams").insert(team_data).execute()
        return team_id_master, True
