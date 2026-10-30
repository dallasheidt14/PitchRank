"""
Demosphere game matcher (elements.demosphere.com, one site id per league).

Demosphere teams are registered by a roster pass in ``scripts/import_demosphere.py``, which hands
the matcher a stored club and the club as the team's own name writes it ("Villarreal Virginia
Academy" beside "Villarreal VA Azul G2013/14"), as Tourney Central's does. A created team keeps
the full name its schedule gives it. So this reuses that matcher whole.
"""

from src.models.tourneycentral_matcher import TourneyCentralGameMatcher


class DemosphereGameMatcher(TourneyCentralGameMatcher):
    """Tourney Central matching for Demosphere league schedules."""
