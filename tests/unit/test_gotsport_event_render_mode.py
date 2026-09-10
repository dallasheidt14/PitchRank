"""The event scraper's ZenRows request must render the page, or it gets a reCAPTCHA.

Measured 2026-09-09 against event 51783, an hour apart: a request carrying
``js_render=false`` and no ``wait_for`` came back as a reCAPTCHA v2 challenge,
and the same event with rendering plus a ``wait_for`` selector came back 200
with all 58 of its divisions. The challenge finishes a proof-of-work in
JavaScript and then rebuilds the page, so a fetch that never runs the script
never sees the page behind it.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
import requests

from src.scrapers._http import RateLimitedError
from src.scrapers.gotsport import (
    EventCaptchaGatedError,
    GotsportScraper,
    _extract_captcha_signals_from_parts,
)

EVENT_URL = "https://system.gotsport.com/org_event/events/51783"
SCHEDULE_URL = "https://system.gotsport.com/org_event/events/51783/schedules?group=543004"


class _Recorder:
    """A ``requests``-faithful stand-in for the scraper's session.

    Returns real ``requests.Response`` objects built from bytes, so ``.text``
    decodes the way production's does rather than handing back a ready-made
    ``str`` — a double that skips the decode cannot fail when the charset
    handling regresses. Records the params and timeout of every call, which is
    the whole point: the defect this guards against is a parameter that is not
    sent and a timeout that is too short.
    """

    def __init__(self, *statuses: int, body: bytes = b"<html><body>ok</body></html>") -> None:
        self.statuses = list(statuses) or [200]
        self.body = body
        self.calls: list[dict] = []

    def get(self, url: str, params: dict | None = None, timeout: int | None = None, **kwargs) -> requests.Response:
        self.calls.append({"url": url, "params": dict(params or {}), "timeout": timeout, **kwargs})
        response = requests.Response()
        response.status_code = self.statuses[min(len(self.calls) - 1, len(self.statuses) - 1)]
        response._content = self.body
        response.url = url
        response.headers["content-type"] = "text/html"
        return response


def _scraper(monkeypatch: pytest.MonkeyPatch, **env: str) -> GotsportScraper:
    monkeypatch.setenv("ZENROWS_API_KEY", "test-key")
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    supabase = MagicMock()
    supabase.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value.data = {
        "id": "provider-uuid",
        "code": "gotsport",
    }
    return GotsportScraper(supabase, "gotsport", skip_team_id_resolution=True)


def _only_call(scraper: GotsportScraper, url: str) -> dict:
    recorder = _Recorder()
    scraper.render_session = recorder
    scraper._make_zenrows_request(url)
    assert len(recorder.calls) == 1
    return recorder.calls[0]


# -------- the parameters that clear the challenge --------------------------


def test_the_request_renders_the_page(monkeypatch):
    """``js_render=false`` is what returns a reCAPTCHA, so it cannot be sent."""
    params = _only_call(_scraper(monkeypatch), EVENT_URL)["params"]

    assert params["js_render"] == "true"


def test_the_request_keeps_the_residential_proxy_and_country(monkeypatch):
    """Rendering alone was measured insufficient; both are required together."""
    params = _only_call(_scraper(monkeypatch), EVENT_URL)["params"]

    assert params["premium_proxy"] == "true"
    assert params["proxy_country"] == "us"


def test_the_request_asks_for_the_targets_own_status(monkeypatch):
    """Without it a 403 arrives wrapped as a ZenRows 200 and is read as content."""
    params = _only_call(_scraper(monkeypatch), EVENT_URL)["params"]

    assert params["original_status"] == "true"


def test_an_event_page_waits_for_its_division_links(monkeypatch):
    """A fixed wait returns the page half-rebuilt, with none of its divisions."""
    params = _only_call(_scraper(monkeypatch), EVENT_URL)["params"]

    assert params["wait_for"] == 'a[href*="group="]'


def test_a_schedule_page_waits_for_its_table(monkeypatch):
    """The division links it waits for on the landing page never appear here."""
    params = _only_call(_scraper(monkeypatch), SCHEDULE_URL)["params"]

    assert params["wait_for"] == "table"


# -------- the timeout the four workflows would otherwise cap ---------------


def test_the_render_timeout_survives_a_workflow_pinning_the_scrape_timeout(monkeypatch):
    """The trap this guard exists for.

    Four workflows pin ``GOTSPORT_TIMEOUT`` to 12-30s. A render needs headroom
    above the vendor's 180s ``wait_for`` ceiling, and ``requests`` counts its
    timeout as silence between bytes — so a 12s budget aborts mid-render and
    looks exactly like the challenge never went away.
    """
    scraper = _scraper(monkeypatch, GOTSPORT_TIMEOUT="12")
    assert scraper.timeout == 12

    call = _only_call(scraper, EVENT_URL)

    assert call["timeout"] == 240


def test_the_render_timeout_has_its_own_knob(monkeypatch):
    scraper = _scraper(monkeypatch, GOTSPORT_RENDER_TIMEOUT="300")

    assert _only_call(scraper, EVENT_URL)["timeout"] == 300


# -------- retry, which ZenRows makes necessary and bills for ---------------


def test_a_render_that_missed_its_budget_is_retried(monkeypatch):
    """ZenRows answers 422 when the selector never appeared; the URL survives it."""
    scraper = _scraper(monkeypatch)
    recorder = _Recorder(422, 200)
    scraper.render_session = recorder
    monkeypatch.setattr("src.scrapers.gotsport.time.sleep", lambda _s: None)

    response = scraper._make_zenrows_request(EVENT_URL)

    assert [call["params"]["url"] for call in recorder.calls] == [EVENT_URL, EVENT_URL]
    assert response.status_code == 200


def test_a_settled_refusal_is_not_retried(monkeypatch):
    """Every attempt is billed, and a 404 is the same answer three times."""
    scraper = _scraper(monkeypatch)
    recorder = _Recorder(404, 200)
    scraper.render_session = recorder
    monkeypatch.setattr("src.scrapers.gotsport.time.sleep", lambda _s: None)

    response = scraper._make_zenrows_request(EVENT_URL)

    assert len(recorder.calls) == 1
    assert response.status_code == 404


def test_the_retries_are_bounded(monkeypatch):
    """An event that keeps missing its budget must not bill without end."""
    scraper = _scraper(monkeypatch)
    recorder = _Recorder(422)
    scraper.render_session = recorder
    monkeypatch.setattr("src.scrapers.gotsport.time.sleep", lambda _s: None)

    response = scraper._make_zenrows_request(EVENT_URL)

    assert len(recorder.calls) == 3
    assert response.status_code == 422, "the last response is returned for the caller to judge"


def test_the_api_json_path_is_not_rendered(monkeypatch):
    """The JSON API is not challenge-gated, so rendering it only costs credits.

    Verified 2026-05-01: ``/api/v1/teams/{id}/matches`` answers even on events
    whose HTML pages are gated.
    """
    from src.scrapers.gotsport import _zenrows_get

    recorder = _Recorder()
    _zenrows_get(recorder, "test-key", "https://system.gotsport.com/api/v1/teams/1/matches", timeout=10)

    assert recorder.calls[0]["params"]["js_render"] == "false"
    assert "wait_for" not in recorder.calls[0]["params"]
    assert recorder.calls[0]["params"]["premium_proxy"] == "true", (
        "datacenter IPs trip the CloudFront WAF; the residential proxy is what this path buys"
    )


# -------- one routed fetch for every event page ---------------------------


def _prepared(endpoint: str, params: dict) -> str:
    """The URL as `requests` will actually send it, apikey and all."""
    return requests.Request("GET", endpoint, params=params).prepare().url


class _PreparedRecorder(_Recorder):
    """`_Recorder`, but honest about the URL `requests` builds.

    The base double assigns the bare endpoint to `response.url`, which is what
    let a leak guard written on it pass while production put the apikey in every
    exception message. Here the response carries the prepared URL, so an
    assertion about redaction can fail.
    """

    def get(self, url: str, params: dict | None = None, timeout: int | None = None, **kwargs) -> requests.Response:
        response = super().get(url, params=params, timeout=timeout, **kwargs)
        response.url = _prepared(url, params or {})
        return response


def test_the_api_key_never_survives_on_the_returned_response(monkeypatch):
    """`raise_for_status()` prints `response.url` verbatim into its exception.

    Anything downstream that stringifies a fetch failure — the tier
    orchestrator writes one into `reports/`, which is not gitignored and this
    repo is public — would carry a live credential.
    """
    scraper = _scraper(monkeypatch)
    recorder = _PreparedRecorder(404)
    scraper.render_session = recorder

    response = scraper._make_zenrows_request(EVENT_URL)

    assert "test-key" not in (response.url or ""), response.url
    assert "REDACTED" in (response.url or "")


def test_rendered_calls_use_a_session_that_does_not_retry_statuses(monkeypatch):
    """The mounted Retry pre-empts the app loop and bills a render each time.

    `_init_http_session` retries 500/502/503/504 to exhaustion and then raises
    `RetryError`, so those statuses never reach the loop that is supposed to
    bound them — while four renders have already been billed per attempt.
    """
    scraper = _scraper(monkeypatch)
    adapter = scraper.render_session.get_adapter("https://api.zenrows.com/v1/")
    retries = adapter.max_retries

    assert list(retries.status_forcelist or []) == [], "a status retry here bills a render"
    assert retries.connect, "connection errors are still worth retrying"


def test_a_retry_error_is_reported_as_rate_limiting(monkeypatch):
    """Otherwise the caller sees a raw urllib3 error the scraper never names."""
    scraper = _scraper(monkeypatch)

    def _exhausted(*_a, **_kw):
        raise requests.exceptions.RetryError("too many retries")

    scraper.render_session = type("S", (), {"get": staticmethod(_exhausted)})()

    with pytest.raises(RateLimitedError):
        scraper._make_zenrows_request(EVENT_URL)


def test_the_routed_fetch_raises_on_a_challenge(monkeypatch, tmp_path):
    """Every routed fetch detects, not just the one entry point that used to.

    The challenge arrives as a redirect and answers 200, so `raise_for_status`
    passes and a parser simply finds nothing. Ten fetch sites returned zero
    teams that way with no error.
    """
    monkeypatch.chdir(tmp_path)
    scraper = _scraper(monkeypatch)
    challenge = (
        b"<html><body>Please verify to continue"
        b"<div class='g-recaptcha' data-sitekey='abc123'></div></body></html>"
    )
    recorder = _PreparedRecorder(200, body=challenge)
    recorder.final_url = f"{scraper.EVENT_BASE}/51783/verify_captchas/new"
    scraper.render_session = recorder

    with pytest.raises(EventCaptchaGatedError):
        scraper._fetch_event_html(f"{scraper.EVENT_BASE}/51783")


def test_the_routed_fetch_forces_utf8_before_the_body_is_read(monkeypatch):
    """GotSport declares no charset, so `requests` would decode ISO-8859-1."""
    scraper = _scraper(monkeypatch)
    recorder = _PreparedRecorder(200, body="Fútbol Club Ñandú".encode("utf-8"))
    scraper.render_session = recorder

    response = scraper._fetch_event_html(f"{scraper.EVENT_BASE}/51783")

    assert "Fútbol Club Ñandú" in response.text


# -------- a page that arrived is not a challenge, whatever the header says ---


def test_a_rendered_page_is_not_a_challenge_because_it_passed_through_one():
    """Observed live on event 51783, 2026-09-09.

    ZenRows' renderer follows GotSport's 302 to ``/verify_captchas/new``, the
    challenge finishes its JavaScript proof-of-work and navigates on to the real
    page, and ZenRows reports the URL it passed *through* in ``Zr-Final-Url``.
    The body that came back was the event page: 260,919 bytes carrying 232
    ``group=`` links. Trusting the header alone turns every successful render
    into a fake block.
    """
    html = "<html><body>" + "".join(
        f'<a href="/org_event/events/51783/schedules?group={n}">Schedule</a>' for n in range(1, 60)
    ) + "</body></html>"

    signals = _extract_captcha_signals_from_parts(
        html=html,
        final_url="https://api.zenrows.com/v1/",
        zr_final_url="https://system.gotsport.com/org_event/events/51783/verify_captchas/new",
        redirect_locations=[],
        fallback_target_url="https://system.gotsport.com/org_event/events/51783",
    )

    assert signals is None, f"the event's own divisions were on the page: {signals}"


def test_a_real_challenge_is_still_caught_by_the_header():
    """The challenge page carries no division or team link — that is the gate."""
    signals = _extract_captcha_signals_from_parts(
        html="<html><body>Please verify to continue</body></html>",
        final_url="https://api.zenrows.com/v1/",
        zr_final_url="https://system.gotsport.com/org_event/events/51783/verify_captchas/new",
        redirect_locations=[],
        fallback_target_url="https://system.gotsport.com/org_event/events/51783",
    )

    assert signals is not None
    assert "verify_captchas" in signals["captcha_url"]


def test_a_real_challenge_is_still_caught_by_a_redirect_location():
    signals = _extract_captcha_signals_from_parts(
        html="<html><body>nothing here</body></html>",
        final_url="https://system.gotsport.com/org_event/events/51783",
        zr_final_url=None,
        redirect_locations=["https://system.gotsport.com/org_event/events/51783/verify_captchas/new"],
        fallback_target_url="https://system.gotsport.com/org_event/events/51783",
    )

    assert signals is not None


def test_a_challenge_served_at_the_target_url_is_still_caught():
    """No redirect at all — observed on events 40550 and 40610."""
    signals = _extract_captcha_signals_from_parts(
        html="<html><body>Please verify to continue</body></html>",
        final_url="https://system.gotsport.com/org_event/events/40550",
        zr_final_url=None,
        redirect_locations=[],
        fallback_target_url="https://system.gotsport.com/org_event/events/40550",
    )

    assert signals is not None
    assert signals["captcha_url"] == "https://system.gotsport.com/org_event/events/40550"


def test_a_team_named_after_a_challenge_marker_does_not_abort_a_paid_walk():
    """The provider's users choose these strings; a marker match is not consent."""
    html = (
        "<html><body><a href='?team=4205984'>awswaf United</a>"
        "<a href='?group=1'>Schedule</a></body></html>"
    )

    signals = _extract_captcha_signals_from_parts(
        html=html,
        final_url="https://system.gotsport.com/org_event/events/51783",
        zr_final_url=None,
        redirect_locations=[],
        fallback_target_url="https://system.gotsport.com/org_event/events/51783",
    )

    assert signals is None


def test_a_challenge_page_that_links_back_to_the_event_is_still_a_challenge():
    """The gate must key on the event's own links, not on any `group=` substring.

    A challenge page carrying a `returnUrl` back to the event would otherwise
    slip through the gate that protects the successful render.
    """
    html = (
        "<html><body>Please verify to continue"
        "<form action='/verify_captchas?returnUrl=/org_event/events/51783%3Fgroup%3D1'>"
        "</form></body></html>"
    )

    signals = _extract_captcha_signals_from_parts(
        html=html,
        final_url="https://api.zenrows.com/v1/",
        zr_final_url="https://system.gotsport.com/org_event/events/51783/verify_captchas/new",
        redirect_locations=[],
        fallback_target_url="https://system.gotsport.com/org_event/events/51783",
    )

    assert signals is not None, "a form target is not a division link"


# -------- a challenge must never be swallowed by a catch-all ---------------


def _routed_methods_that_swallow_a_challenge() -> list[str]:
    """Methods routing through the seam whose catch-all would eat the challenge.

    Derived from the class body rather than listed, because the defect this
    guards against is a *new* routed call site landing inside an existing
    ``except Exception``. A hand-written list cannot fail for the site it omits,
    and that is exactly how ten sites acquired the problem at once.
    """
    import pathlib
    import re

    src = pathlib.Path(GotsportScraper.__module__.replace(".", "/") + ".py")
    if not src.exists():  # installed rather than in-tree
        import inspect

        src = pathlib.Path(inspect.getsourcefile(GotsportScraper))
    lines = src.read_text(encoding="utf-8").splitlines()
    start = next(i for i, l in enumerate(lines) if l.startswith("class GotsportScraper"))

    bounds: dict[str, list[int]] = {}
    cur = None
    for i in range(start, len(lines)):
        m = re.match(r"    def (\w+)\(", lines[i])
        if m:
            if cur:
                bounds[cur][1] = i
            cur = m.group(1)
            bounds[cur] = [i, len(lines)]
    if cur:
        bounds[cur][1] = len(lines)

    offenders = []
    for name, (lo, hi) in bounds.items():
        body = lines[lo:hi]
        if not any("_fetch_event_html(" in l for l in body):
            continue
        if name == "_fetch_event_html":
            continue
        arms = [l.strip() for l in body if re.match(r"\s+except ", l)]
        broad = any("except Exception" in a or a.startswith("except:") for a in arms)
        reraises = any("EventCaptchaGatedError" in a for a in arms)
        if broad and not reraises:
            offenders.append(name)
    return sorted(offenders)


def test_no_routed_fetch_lets_a_catch_all_eat_the_challenge():
    """A swallowed challenge is worse than a raised one: it looks like an empty event.

    `scrape_games_from_schedule_pages` re-raises `EventCaptchaGatedError` so the
    event is not marked scraped. Routing a fetch into a method whose catch-all
    swallows it defeats that: earlier pages' games are returned, the event is
    recorded as successfully scraped, and the missing fixtures are invisible.
    Retrying it is no better — a challenge does not clear on a retry and each
    attempt bills a render.
    """
    offenders = _routed_methods_that_swallow_a_challenge()

    assert offenders == [], (
        "these route through _fetch_event_html but would swallow the challenge; "
        f"add `except EventCaptchaGatedError: raise` above the catch-all: {offenders}"
    )


def test_a_challenge_mid_walk_is_not_reported_as_an_empty_page(monkeypatch, tmp_path):
    """The concrete shape: a schedule page challenged after the landing page passed."""
    monkeypatch.chdir(tmp_path)
    scraper = _scraper(monkeypatch)
    challenge = b"<html><body>Please verify to continue</body></html>"
    recorder = _PreparedRecorder(200, body=challenge)
    scraper.render_session = recorder

    with pytest.raises(EventCaptchaGatedError):
        scraper._parse_games_from_schedule_page(
            SCHEDULE_URL, "51783", event_name="Test", since_date=None
        )
