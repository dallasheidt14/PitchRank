"""
Scrapy settings for modular11_scraper project.

For simplicity, this file contains only settings considered important or
commonly used. You can find more settings consulting the documentation:
    https://docs.scrapy.org/en/latest/topics/settings.html
"""

BOT_NAME = "modular11_scraper"

SPIDER_MODULES = ["modular11_scraper.spiders"]
NEWSPIDER_MODULE = "modular11_scraper.spiders"

# Crawl responsibly by identifying yourself
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

# Obey robots.txt rules - disabled for API access
ROBOTSTXT_OBEY = False

# Configure maximum concurrent requests
CONCURRENT_REQUESTS = 8

# Configure a delay for requests (be nice to the server)
DOWNLOAD_DELAY = 0.5

# Disable cookies (not needed for API)
COOKIES_ENABLED = False

# Configure item pipelines
ITEM_PIPELINES = {
    "modular11_scraper.pipelines.Modular11Pipeline": 300,
}

# Feed export encoding
FEED_EXPORT_ENCODING = "utf-8"

# Logging
LOG_LEVEL = "INFO"

# Retry settings
RETRY_ENABLED = True
RETRY_TIMES = 3
RETRY_HTTP_CODES = [500, 502, 503, 504, 408, 429]

# Timeout
DOWNLOAD_TIMEOUT = 30

# AutoThrottle extension (helps with rate limiting)
AUTOTHROTTLE_ENABLED = True
AUTOTHROTTLE_START_DELAY = 0.5
AUTOTHROTTLE_MAX_DELAY = 5
AUTOTHROTTLE_TARGET_CONCURRENCY = 4.0

# HTTP cache (optional, for development)
# HTTPCACHE_ENABLED = True
# HTTPCACHE_EXPIRATION_SECS = 3600
# HTTPCACHE_DIR = "httpcache"

# Request fingerprinter (Scrapy 2.7+)
REQUEST_FINGERPRINTER_IMPLEMENTATION = "2.7"

# Twisted reactor (required for Windows compatibility)
TWISTED_REACTOR = "twisted.internet.asyncioreactor.AsyncioSelectorReactor"






