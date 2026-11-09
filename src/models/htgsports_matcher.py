"""
HTG Sports game matcher (events.htgsports.net).

The roster pass in ``scripts/import_htgsports_event.py`` hands the matcher the club each
division's standings print ("Des Moines Soccer Club" beside "DMSC U12 Boys Red") and the club as
the team's own name writes it, and a created team keeps its full registered name. That is the
case ``TourneyCentralGameMatcher`` handles, so this reuses it whole.
"""

from src.models.tourneycentral_matcher import TourneyCentralGameMatcher


class HtgSportsGameMatcher(TourneyCentralGameMatcher):
    """Tourney Central matching for HTG Sports events."""
