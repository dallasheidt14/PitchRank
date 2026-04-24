"""Back-compat shim — contents moved to ``src.scrapers.gotsport`` (Shell 01 Step 3 Commit B).

The former ``GotSportEventScraper`` class body now lives in
``src/scrapers/gotsport.py`` as ``GotsportScraper(ProviderScraper)``. This
module re-exports the old names so the 8 external importer scripts keep
working with zero changes. New code should import from ``src.scrapers.gotsport``
directly.
"""

from src.scrapers.gotsport import (
    EventCaptchaGatedError,
    EventTeam,
    GotsportScraper as GotSportEventScraper,
)

__all__ = [
    "EventCaptchaGatedError",
    "EventTeam",
    "GotSportEventScraper",
]
