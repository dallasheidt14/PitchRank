#!/usr/bin/env python3
"""Phase A diagnostic for the gotsport event scraper.

Implements Step 1 of
.turbo/plans/matchbalance-backtest-intake-01-scraper-fix-and-abstraction.md:

  - Baseline capture across 3 known-good completed events (median bytes).
  - Three-back-to-back-request protocol against the target event URL.
  - Decision-table classification against
    ua_block / rate_limited / html_drift / js_rendered / unknown_html_state.
  - Emits `PHASE_A_CLASSIFICATION=<tag>[,<tag>...]` as the final log line.

`url_change` cannot be observed from a single URL fetch (it requires
attempting to resolve canonical team IDs from team-schedule pages). Run
`scripts/scrape_specific_event.py <id> --verbose --no-auto-import` alongside
this diagnostic to catch that tag.

Mirrors `src/scrapers/gotsport_event.py:_init_http_session` (same UA, Accept
headers, urllib3 Retry on {500,502,503,504}) so the diagnostic signal reflects
production session behavior. No app-level retry wrapper, per the plan.
"""

import argparse
import logging
import re
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import requests
from requests.adapters import HTTPAdapter
from requests.exceptions import RequestException, Timeout
from urllib3.util.retry import Retry

try:
    import certifi

    CERTIFI_AVAILABLE = True
except ImportError:
    CERTIFI_AVAILABLE = False
    certifi = None

EVENT_BASE = "https://system.gotsport.com/org_event/events"
WARMUP_URL = "https://system.gotsport.com/"
DEFAULT_BASELINE_EVENTS = ["40550", "40610", "41012"]
MIN_BASELINE_BYTES = 10_000
BODY_HEAD_CHARS = 400
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36"
)

JSON_TEAM_REGS_RE = re.compile(r"jsonTeamRegs")
SCRIPT_TAG_RE = re.compile(r"<script\b", re.IGNORECASE)
LOGIN_REDIRECT_RE = re.compile(r"/(?:login|users/sign_in|verify_captchas?)", re.IGNORECASE)

logger = logging.getLogger("phase_a")


@dataclass
class RequestSample:
    attempt: int
    status: Optional[int]
    length: Optional[int]
    body_head: str
    timed_out: bool
    request_error: Optional[str]
    redirect_chain: List[tuple]
    jsonteamregs_matches: int
    script_tag_count: int
    retry_after: Optional[str]
    elapsed_ms: float
    cookies_after: int


def make_session() -> requests.Session:
    session = requests.Session()
    verify_ssl = True
    if CERTIFI_AVAILABLE:
        verify_ssl = certifi.where()
    adapter = HTTPAdapter(
        pool_connections=10,
        pool_maxsize=10,
        max_retries=Retry(
            total=3,
            backoff_factor=0.3,
            status_forcelist=[500, 502, 503, 504],
            allowed_methods=["GET", "HEAD"],
        ),
    )
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.verify = verify_ssl
    # Keep this bundle in lockstep with src/scrapers/gotsport_event.py
    # `_init_http_session` so the diagnostic reflects production session
    # behavior. Step 3 (scraper migration) will consolidate into a single
    # builder under src/scrapers/.
    session.headers.update(
        {
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",  # noqa: E501
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Sec-Ch-Ua": '"Chromium";v="133", "Not(A:Brand";v="24", "Google Chrome";v="133"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"Windows"',
            "Priority": "u=0, i",
        }
    )
    return session


def fetch_once(
    session: requests.Session,
    url: str,
    timeout_s: int,
    attempt: int,
    *,
    same_origin_referer: Optional[str] = None,
) -> RequestSample:
    t0 = time.perf_counter()
    per_request_headers: dict = {}
    if same_origin_referer:
        # Mark this request as a same-origin navigation from a prior page
        # on the site. `Sec-Fetch-Site: none` with session cookies from a
        # prior GET is inconsistent (claims "no prior page" while sending
        # cookies from one) and is a common bot-detection tell.
        per_request_headers = {
            "Referer": same_origin_referer,
            "Sec-Fetch-Site": "same-origin",
        }
    try:
        r = session.get(
            url,
            timeout=timeout_s,
            allow_redirects=True,
            headers=per_request_headers or None,
        )
    except Timeout as e:
        elapsed_ms = (time.perf_counter() - t0) * 1000
        return RequestSample(
            attempt=attempt,
            status=None,
            length=None,
            body_head="",
            timed_out=True,
            request_error=f"Timeout: {e}",
            redirect_chain=[],
            jsonteamregs_matches=0,
            script_tag_count=0,
            retry_after=None,
            elapsed_ms=elapsed_ms,
            cookies_after=len(session.cookies),
        )
    except RequestException as e:
        elapsed_ms = (time.perf_counter() - t0) * 1000
        return RequestSample(
            attempt=attempt,
            status=None,
            length=None,
            body_head="",
            timed_out=False,
            request_error=f"{type(e).__name__}: {e}",
            redirect_chain=[],
            jsonteamregs_matches=0,
            script_tag_count=0,
            retry_after=None,
            elapsed_ms=elapsed_ms,
            cookies_after=len(session.cookies),
        )
    elapsed_ms = (time.perf_counter() - t0) * 1000
    redirect_chain = [(hr.status_code, hr.headers.get("Location")) for hr in r.history]
    body = r.text or ""
    return RequestSample(
        attempt=attempt,
        status=r.status_code,
        length=len(body),
        body_head=body[:BODY_HEAD_CHARS],
        timed_out=False,
        request_error=None,
        redirect_chain=redirect_chain,
        jsonteamregs_matches=len(JSON_TEAM_REGS_RE.findall(body)) if r.status_code == 200 else 0,
        script_tag_count=len(SCRIPT_TAG_RE.findall(body)) if r.status_code == 200 else 0,
        retry_after=r.headers.get("Retry-After"),
        elapsed_ms=elapsed_ms,
        cookies_after=len(session.cookies),
    )


def capture_baseline(
    session: requests.Session, events: List[str], timeout_s: int
) -> Optional[int]:
    samples: list[int] = []
    for eid in events:
        url = f"{EVENT_BASE}/{eid}"
        logger.info("[baseline] fetching event_id=%s url=%s", eid, url)
        r = fetch_once(session, url, timeout_s, attempt=0)
        if r.status != 200 or r.length is None:
            logger.warning(
                "[baseline] event_id=%s status=%s length=%s error=%s — excluding",
                eid, r.status, r.length, r.request_error,
            )
            continue
        samples.append(r.length)
        logger.info(
            "[baseline] event_id=%s bytes=%d scripts=%d jsonteamregs=%d elapsed_ms=%.1f",
            eid, r.length, r.script_tag_count, r.jsonteamregs_matches, r.elapsed_ms,
        )
    if not samples:
        logger.error("[baseline] no usable samples captured; baseline unavailable")
        return None
    median_bytes = int(statistics.median(samples))
    logger.info(
        "[baseline] samples=%s median=%d min_required=%d",
        samples, median_bytes, MIN_BASELINE_BYTES,
    )
    return median_bytes


def three_request_protocol(
    session: requests.Session,
    event_id: str,
    timeout_s: int,
    *,
    same_origin_referer: Optional[str] = None,
) -> List[RequestSample]:
    url = f"{EVENT_BASE}/{event_id}"
    samples: list[RequestSample] = []
    for i in range(3):
        logger.info(
            "[three_request] attempt=%d url=%s referer=%s",
            i, url, same_origin_referer,
        )
        r = fetch_once(
            session,
            url,
            timeout_s,
            attempt=i,
            same_origin_referer=same_origin_referer,
        )
        logger.info(
            "[three_request] attempt=%d status=%s length=%s timeout=%s error=%s "
            "jsonteamregs=%d scripts=%d retry_after=%s cookies=%d elapsed_ms=%.1f "
            "redirects=%s",
            i, r.status, r.length, r.timed_out, r.request_error,
            r.jsonteamregs_matches, r.script_tag_count, r.retry_after,
            r.cookies_after, r.elapsed_ms, r.redirect_chain,
        )
        samples.append(r)
    return samples


def classify(
    samples: List[RequestSample],
    baseline_bytes: Optional[int],
    cookies_after_warmup: Optional[int],
) -> List[str]:
    tags: list[str] = []

    any_403 = any(s.status == 403 for s in samples)
    any_login_redirect = any(
        loc and LOGIN_REDIRECT_RE.search(loc)
        for s in samples
        for _, loc in s.redirect_chain
    )
    # Deliberately dropping the plan's "empty cookie jar after warmup" signal.
    # Observed 2026-04-24: gotsport's root page returns 200 with no Set-Cookie
    # for a fresh session, so treating that as ua_block produces false positives
    # on healthy events. Flag for plan/spec update. True ua_block is signalled
    # by 403 or login/captcha redirect; the cookie rule carries no independent
    # information at this domain.
    _unused_cookies_after_warmup = cookies_after_warmup
    if any_403 or any_login_redirect:
        tags.append("ua_block")

    any_429 = any(s.status == 429 for s in samples)
    any_503 = any(s.status == 503 for s in samples)
    timeout_count = sum(1 for s in samples if s.timed_out)
    short_body_count = 0
    if baseline_bytes:
        threshold = baseline_bytes * 0.1
        short_body_count = sum(
            1
            for s in samples
            if s.status == 200 and s.length is not None and s.length < threshold
        )
    if any_429 or any_503 or timeout_count >= 2 or short_body_count >= 2:
        tags.append("rate_limited")

    if baseline_bytes:
        half = baseline_bytes * 0.5
        html_like = [
            s
            for s in samples
            if s.status == 200
            and s.length is not None
            and s.length >= half
            and s.jsonteamregs_matches == 0
        ]
        if len(html_like) >= 2:
            high_script = sum(1 for s in html_like if s.script_tag_count > 4)
            if high_script >= 2:
                tags.append("html_drift")
            else:
                tags.append("js_rendered")

    if not tags:
        # Pass detection: event URL returned HTTP 200 with jsonTeamRegs team
        # data on >= 2/3 requests. The plan's decision table has no explicit
        # pass state (only failure tags + unknown_html_state sentinel); flag
        # for plan/spec update.
        healthy = sum(
            1
            for s in samples
            if s.status == 200 and s.jsonteamregs_matches > 0
        )
        tags.append("ok" if healthy >= 2 else "unknown_html_state")
    return tags


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Phase A diagnostic for gotsport event scraper.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Emits PHASE_A_CLASSIFICATION=<tag>[,<tag>...] as the final log line."
        ),
    )
    parser.add_argument("event_id", help="Target event id (e.g., 45224)")
    parser.add_argument(
        "--baseline-events",
        nargs="+",
        default=DEFAULT_BASELINE_EVENTS,
        help="Known-good completed event ids for baseline capture (default: %(default)s)",
    )
    parser.add_argument(
        "--timeout", type=int, default=15, help="Per-request timeout seconds (default: 15)"
    )
    parser.add_argument(
        "--no-warmup",
        action="store_true",
        help="Skip GET to system.gotsport.com root (default: warm up to seed cookies)",
    )
    parser.add_argument(
        "--same-origin-referer",
        metavar="URL",
        default=None,
        help="Send Referer + Sec-Fetch-Site: same-origin on event-URL fetches",
    )
    parser.add_argument(
        "--log-file",
        type=Path,
        default=None,
        help="Mirror log output to this file (directory created if missing)",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Enable DEBUG-level logging"
    )
    args = parser.parse_args()

    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    if args.log_file:
        args.log_file.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(args.log_file, mode="w", encoding="utf-8"))
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
        force=True,
    )
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    session = make_session()

    cookies_after_warmup: Optional[int] = None
    if not args.no_warmup:
        logger.info("[warmup] GET %s", WARMUP_URL)
        r = fetch_once(session, WARMUP_URL, args.timeout, attempt=0)
        # Only treat cookies-empty as a ua_block signal when the warmup actually
        # succeeded. A timed-out/errored warmup trivially produces 0 cookies and
        # tells us nothing about UA rejection.
        if r.status == 200 and r.request_error is None:
            cookies_after_warmup = r.cookies_after
        logger.info(
            "[warmup] status=%s length=%s cookies=%d error=%s",
            r.status, r.length, r.cookies_after, r.request_error,
        )

    baseline = capture_baseline(session, args.baseline_events, args.timeout)
    if baseline is None:
        logger.error("HALT — baseline unavailable (all sample fetches failed)")
        logger.info("PHASE_A_CLASSIFICATION=unknown_html_state")
        return 1
    if baseline < MIN_BASELINE_BYTES:
        logger.error(
            "HALT — baseline median %d < required %d; baseline itself degraded",
            baseline, MIN_BASELINE_BYTES,
        )
        logger.info("PHASE_A_CLASSIFICATION=unknown_html_state")
        return 1

    samples = three_request_protocol(
        session,
        args.event_id,
        args.timeout,
        same_origin_referer=args.same_origin_referer,
    )
    for s in samples:
        logger.debug("[three_request_body] attempt=%d body_head=%r", s.attempt, s.body_head)

    tags = classify(samples, baseline, cookies_after_warmup)
    logger.info("PHASE_A_CLASSIFICATION=%s", ",".join(tags))
    return 0


if __name__ == "__main__":
    sys.exit(main())
