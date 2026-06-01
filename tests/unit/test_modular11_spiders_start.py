"""Regression tests for the Modular11 spiders' start-request entry point.

Scrapy 2.13 renamed the spider entry point from ``start_requests()`` to an async
``start()`` method and stopped calling ``start_requests()`` from the base
``Spider`` class (its ``start()`` only iterates ``start_urls``). Both Modular11
spiders override the entry point and define no ``start_urls``, so once CI moved to
Scrapy >= 2.13 they silently produced ZERO start requests: the crawl opened and
immediately closed with 0 games, while the workflow still exited green.

These tests pin the contract that each spider's ``start()`` yields at least one
request, so a future Scrapy upgrade (``requirements.txt`` allows ``scrapy>=2.13.0``)
can't silently re-break startup without turning a test red.

The spiders live in the standalone ``scrapers/modular11_scraper`` Scrapy project,
which is not on the repo-root import path, so we add it to ``sys.path`` here.
``start()`` is an async generator; we drive it with ``asyncio.run`` rather than a
pytest-asyncio marker because the suite configures no ``asyncio_mode``.
"""

import asyncio
import sys
from pathlib import Path

import pytest

scrapy = pytest.importorskip("scrapy")

_SCRAPER_ROOT = Path(__file__).resolve().parents[2] / "scrapers" / "modular11_scraper"
if str(_SCRAPER_ROOT) not in sys.path:
    sys.path.insert(0, str(_SCRAPER_ROOT))

from modular11_scraper.spiders.modular11_events import Modular11EventsSpider  # noqa: E402
from modular11_scraper.spiders.modular11_schedule import Modular11ScheduleSpider  # noqa: E402


def _collect_start(spider):
    """Async-iterate ``spider.start()`` to a list of yielded requests."""

    async def _run():
        return [request async for request in spider.start()]

    return asyncio.run(_run())


def test_events_spider_start_yields_request():
    """The events spider seeds exactly one request: the events list page."""
    spider = Modular11EventsSpider(age_min="13", age_max="17", days_back="14")

    requests = _collect_start(spider)

    assert len(requests) == 1
    assert all(isinstance(request, scrapy.Request) for request in requests)
    assert all(request.method == "GET" for request in requests)


def test_schedule_spider_start_yields_one_request_per_division_age():
    """The schedule spider fans out one request per division/age-group pair."""
    spider = Modular11ScheduleSpider(age_min="13", age_max="17", days_back="14", division="both")

    requests = _collect_start(spider)

    assert len(requests) == len(spider.divisions_to_scrape) * len(spider.age_group_ids)
    assert all(isinstance(request, scrapy.Request) for request in requests)
    assert all(request.method == "GET" for request in requests)
