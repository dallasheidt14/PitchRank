"""
Scrapy settings for outreach_scraper project.

Contact-harvesting spiders for the authority/backlink program. Forked from
modular11_scraper, with two deliberate differences:
- ROBOTSTXT_OBEY is True (modular11 disables it for API access). This project
  scrapes publicly-listed org/role inboxes and honors robots.txt.
- The item pipeline writes to Supabase instead of CSV.
"""

BOT_NAME = "outreach_scraper"

SPIDER_MODULES = ["outreach_scraper.spiders"]
NEWSPIDER_MODULE = "outreach_scraper.spiders"

# Identify the crawler honestly; this is outreach research, not stealth scraping.
USER_AGENT = "PitchRankOutreachBot/1.0 (+https://pitchrank.io; outreach@pitchrank.io)"

# Honor robots.txt — the compliance posture for harvesting public contact pages.
ROBOTSTXT_OBEY = True

# Be a polite guest on small club/association servers.
CONCURRENT_REQUESTS = 4
CONCURRENT_REQUESTS_PER_DOMAIN = 1
DOWNLOAD_DELAY = 1.0
COOKIES_ENABLED = False

ITEM_PIPELINES = {
    "outreach_scraper.pipelines.OutreachSupabasePipeline": 300,
}

FEED_EXPORT_ENCODING = "utf-8"
LOG_LEVEL = "INFO"

RETRY_ENABLED = True
RETRY_TIMES = 3
RETRY_HTTP_CODES = [500, 502, 503, 504, 408, 429]

DOWNLOAD_TIMEOUT = 30

AUTOTHROTTLE_ENABLED = True
AUTOTHROTTLE_START_DELAY = 1.0
AUTOTHROTTLE_MAX_DELAY = 10
AUTOTHROTTLE_TARGET_CONCURRENCY = 1.0

REQUEST_FINGERPRINTER_IMPLEMENTATION = "2.7"

# Required for Windows compatibility (matches modular11_scraper).
TWISTED_REACTOR = "twisted.internet.asyncioreactor.AsyncioSelectorReactor"
