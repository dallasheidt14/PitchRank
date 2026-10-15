"""MLS NEXT (Kitman) game matcher: alias-only.

``scripts/link_mlsnext_kitman_teams.py`` is the only thing that links or creates MLS NEXT
teams from Kitman. The game import resolves a season-keyed squad id through the alias that script wrote,
and a team without one stays unmatched -- its games were already held back by
``scripts/build_mlsnext_kitman_games_csv.py``, so this is a backstop, not a path.
"""

from typing import Dict, Optional

from src.models.game_matcher import GameHistoryMatcher

PROVIDER_CODE = "mlsnext_kitman"
UNMATCHED = {"matched": False, "team_id": None, "method": None, "confidence": 0.0}


class MlsNextKitmanGameMatcher(GameHistoryMatcher):
    def _match_team(
        self,
        provider_id: str,
        provider_team_id: Optional[str],
        team_name: Optional[str],
        age_group: Optional[str],
        gender: Optional[str],
        club_name: Optional[str] = None,
        state_code: Optional[str] = None,
    ) -> Dict:
        if not provider_team_id:
            return dict(UNMATCHED)
        alias = self._match_by_provider_id(provider_id, str(provider_team_id), age_group, gender)
        if not alias:
            return dict(UNMATCHED)
        method = "direct_id" if alias.get("match_method") == "direct_id" else "provider_id"
        return {"matched": True, "team_id": alias["team_id_master"], "method": method, "confidence": 1.0}
