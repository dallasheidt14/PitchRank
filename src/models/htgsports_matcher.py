"""
HTG Sports game matcher (events.htgsports.net).

The roster pass in ``scripts/import_htgsports_event.py`` hands the matcher the club each
division's standings print ("Des Moines Soccer Club" beside "DMSC U12 Boys Red") and the club as
the team's own name writes it, and a created team keeps its full registered name. That is the
case ``TourneyCentralGameMatcher`` handles, so this reuses it whole. HTG runs Heartland Soccer's
Kansas City tournaments, whose clubs name squads by words no shared gate reads, so the
squad-word rules of ``src/models/squad_word_rules.py`` apply too, to every HTG event.
"""

from src.models.squad_word_rules import SquadWordRules
from src.models.tourneycentral_matcher import TourneyCentralGameMatcher


class HtgSportsGameMatcher(SquadWordRules, TourneyCentralGameMatcher):
    """Tourney Central matching for HTG Sports events."""
