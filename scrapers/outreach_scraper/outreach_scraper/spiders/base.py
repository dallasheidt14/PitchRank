"""
Config-driven base spider for outreach contact harvesting.

Each segment spider loads ``sources/<segment>.yaml`` and, per listed site,
fetches the page (directly, or through ZenRows when ``fetch: zenrows``),
extracts publicly-listed role inboxes, and yields one OutreachTargetItem per
contact (or a single contactless item when no email is public, leaving the
email for the Hunter enrichment step). Keeping the site list in YAML lets one
generic spider cover dozens of heterogeneous sites without bespoke code.
"""

import logging
import re
from pathlib import Path

import scrapy
import yaml

from outreach_scraper.items import OutreachTargetItem
from outreach_scraper.zenrows import zenrows_url

logger = logging.getLogger(__name__)

SOURCES_DIR = Path(__file__).resolve().parents[2] / "sources"

# Publicly-listed role inboxes we are willing to harvest (never personal addresses).
ROLE_INBOX_PREFIXES = (
    "info",
    "contact",
    "hello",
    "office",
    "admin",
    "doc",
    "coaching",
    "director",
    "registrar",
    "media",
    "press",
    "editor",
    "editorial",
    "news",
    "tips",
)

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


class OutreachSpider(scrapy.Spider):
    """Loads a segment's YAML source list and harvests role inboxes."""

    segment = None  # set by each subclass

    def __init__(self, dry_run=False, sources=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.dry_run = dry_run if isinstance(dry_run, bool) else str(dry_run).lower() in ("1", "true", "yes")
        self.sources_path = Path(sources) if sources else SOURCES_DIR / f"{self.segment}.yaml"
        self.sites = self._load_sites()

    def _load_sites(self):
        with open(self.sources_path, encoding="utf-8") as fh:
            config = yaml.safe_load(fh) or {}
        sites = config.get("sites") or []
        logger.info("Loaded %d sources for '%s' from %s", len(sites), self.segment, self.sources_path)
        return sites

    async def start(self):
        for site in self.sites:
            target_url = site["start_url"]
            if site.get("fetch") == "zenrows":
                request_url = zenrows_url(target_url, js_render=bool(site.get("js_render", False)))
            else:
                request_url = target_url
            yield scrapy.Request(request_url, callback=self.parse, meta={"site": site}, dont_filter=True)

    def parse(self, response):
        site = response.meta["site"]
        personalization = dict(site.get("personalization") or {})
        emails = self._extract_emails(response, site)

        if not emails:
            yield self._build_item(site, None, personalization)
            return
        for email in emails:
            yield self._build_item(site, email, personalization)

    def _extract_emails(self, response, site):
        selector = (site.get("selectors") or {}).get("email")
        if selector:
            # An explicit selector means the operator targeted this address, so
            # trust it (a masthead may publish an editor on a different domain).
            candidates = list(response.css(selector).getall())
            restrict_domain = None
        else:
            # The default heuristic scans the whole page, so restrict harvested
            # addresses to the site's own domain — otherwise a third party's
            # role inbox in the footer would be stored under the wrong org.
            candidates = response.css("a[href^='mailto:']::attr(href)").getall()
            candidates += EMAIL_RE.findall(response.text)
            restrict_domain = (site.get("source_domain") or "").lower()

        emails = []
        seen = set()
        for raw in candidates:
            email = raw.replace("mailto:", "").split("?", 1)[0].strip().lower()
            if not EMAIL_RE.fullmatch(email) or not self._is_role_inbox(email):
                continue
            if restrict_domain and not self._domain_matches(email, restrict_domain):
                continue
            if email not in seen:
                seen.add(email)
                emails.append(email)
        return emails

    @staticmethod
    def _is_role_inbox(email):
        local = email.split("@", 1)[0]
        return any(local.startswith(prefix) for prefix in ROLE_INBOX_PREFIXES)

    @staticmethod
    def _domain_matches(email, domain):
        email_domain = email.split("@", 1)[1]
        return email_domain == domain or email_domain.endswith("." + domain)

    def _build_item(self, site, email, personalization):
        item = OutreachTargetItem()
        item["segment"] = self.segment
        item["org"] = site["org"]
        item["contact"] = email
        item["source_domain"] = site["source_domain"]
        item["link_url"] = site["start_url"]
        item["personalization"] = personalization
        return item
