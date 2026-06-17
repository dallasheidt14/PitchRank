"""
Scrapy Item definition for the outreach_scraper project.

Fields map 1:1 to the outreach_targets table. ``contact`` is nullable until
the enrichment step (Hunter) resolves an email; ``link_url`` carries the public
source page and ``personalization.state`` carries the state, so there are no
top-level source_url/state fields.
"""

import scrapy


class OutreachTargetItem(scrapy.Item):
    """One scraped outreach target (an org/role inbox), pre-enrichment."""

    segment = scrapy.Field()  # "associations" | "clubs" | "media" | "bloggers"
    org = scrapy.Field()
    contact = scrapy.Field()  # role inbox email, or None until enriched
    source_domain = scrapy.Field()  # the org's domain — Hunter input + dedupe key
    link_url = scrapy.Field()  # the public page the contact was found on
    personalization = scrapy.Field()  # dict: state, league_mix, a team/standing signal
