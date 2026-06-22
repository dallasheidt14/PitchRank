"""Unit tests for the outreach spider's email extraction + role-inbox filter."""

import sys
from pathlib import Path

import pytest

# The Scrapy project and its YAML configs are heavy deps that live outside src/;
# skip cleanly (rather than abort the whole suite) where they aren't installed.
pytest.importorskip("scrapy")
pytest.importorskip("yaml")

from scrapy.http import HtmlResponse  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRAPER_DIR = REPO_ROOT / "scrapers" / "outreach_scraper"
if str(SCRAPER_DIR) not in sys.path:
    sys.path.insert(0, str(SCRAPER_DIR))

from outreach_scraper.items import OutreachTargetItem  # noqa: E402
from outreach_scraper.pipelines import OutreachSupabasePipeline  # noqa: E402
from outreach_scraper.spiders.associations import AssociationsSpider  # noqa: E402


def _spider():
    return AssociationsSpider(sources=str(SCRAPER_DIR / "sources" / "associations.yaml"))


def _response(html, url="https://example.org/contact"):
    return HtmlResponse(url=url, body=html.encode("utf-8"), encoding="utf-8")


def test_loads_seed_sources():
    spider = _spider()
    assert len(spider.sites) >= 10
    assert all("source_domain" in site for site in spider.sites)


def test_is_role_inbox_keeps_role_drops_personal():
    spider = _spider()
    assert spider._is_role_inbox("info@x.org")
    assert spider._is_role_inbox("contact@x.org")
    assert spider._is_role_inbox("director@x.org")
    assert not spider._is_role_inbox("jane.doe@x.org")
    assert not spider._is_role_inbox("john@x.org")


def test_extract_emails_filters_to_role_inboxes():
    html = """
      <a href="mailto:info@az.org">Email us</a>
      <a href="mailto:jane.smith@az.org">Jane</a>
      <p>reach press@az.org for media inquiries</p>
    """
    spider = _spider()
    site = {"org": "x", "source_domain": "az.org", "start_url": "u"}
    emails = spider._extract_emails(_response(html), site)
    assert "info@az.org" in emails
    assert "press@az.org" in emails
    assert "jane.smith@az.org" not in emails


def test_build_item_maps_table_fields():
    spider = _spider()
    site = {"org": "X Assoc", "source_domain": "x.org", "start_url": "https://x.org/contact"}
    item = spider._build_item(site, "info@x.org", {"state": "AZ"})
    assert item["segment"] == "associations"
    assert item["org"] == "X Assoc"
    assert item["contact"] == "info@x.org"
    assert item["source_domain"] == "x.org"
    assert item["link_url"] == "https://x.org/contact"
    assert item["personalization"] == {"state": "AZ"}


def test_default_branch_filters_off_domain_emails():
    html = '<a href="mailto:info@vendor.com">x</a><a href="mailto:info@az.org">y</a>'
    spider = _spider()
    site = {"org": "x", "source_domain": "az.org", "start_url": "u"}
    emails = spider._extract_emails(_response(html), site)
    assert "info@az.org" in emails
    assert "info@vendor.com" not in emails  # third-party role inbox dropped


def test_default_branch_keeps_subdomain_email():
    html = '<a href="mailto:info@mail.az.org">x</a>'
    spider = _spider()
    site = {"org": "x", "source_domain": "az.org", "start_url": "u"}
    assert spider._extract_emails(_response(html), site) == ["info@mail.az.org"]


def test_selector_override_bypasses_domain_filter():
    html = '<a class="c" href="mailto:info@thirdparty.com">x</a>'
    spider = _spider()
    site = {"org": "x", "source_domain": "az.org", "start_url": "u", "selectors": {"email": "a.c::attr(href)"}}
    assert spider._extract_emails(_response(html), site) == ["info@thirdparty.com"]


def test_no_role_email_returns_empty():
    html = '<a href="mailto:jane.doe@az.org">x</a><p>just prose, no inbox</p>'
    spider = _spider()
    site = {"org": "x", "source_domain": "az.org", "start_url": "u"}
    assert spider._extract_emails(_response(html), site) == []


# --- Pipeline in-memory dedupe (no DB) ---


class _StubSpider:
    pass


def _item(segment="associations", org="X", source_domain="x.org", contact=None):
    item = OutreachTargetItem()
    item["segment"] = segment
    item["org"] = org
    item["contact"] = contact
    item["source_domain"] = source_domain
    item["link_url"] = "u"
    item["personalization"] = {}
    return item


def test_pipeline_dedupes_by_key_and_by_email():
    pipeline = OutreachSupabasePipeline()
    spider = _StubSpider()

    pipeline.process_item(_item(contact="info@x.org"), spider)
    assert len(pipeline.buffer) == 1 and pipeline.skipped_dupes == 0

    # Same (segment, source_domain, org) -> skipped.
    pipeline.process_item(_item(contact="other@x.org"), spider)
    assert len(pipeline.buffer) == 1 and pipeline.skipped_dupes == 1

    # Different org, same email (case-insensitive) -> skipped by the email set.
    pipeline.process_item(_item(org="Y", source_domain="y.org", contact="INFO@x.org"), spider)
    assert len(pipeline.buffer) == 1 and pipeline.skipped_dupes == 2

    # New key and new email -> buffered.
    pipeline.process_item(_item(org="Z", source_domain="z.org", contact="hi@z.org"), spider)
    assert len(pipeline.buffer) == 2


def test_pipeline_blank_contact_normalized_to_none():
    pipeline = OutreachSupabasePipeline()
    pipeline.process_item(_item(contact="   "), _StubSpider())
    assert pipeline.buffer[0]["contact"] is None
