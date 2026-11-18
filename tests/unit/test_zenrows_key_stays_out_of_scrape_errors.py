"""The ZenRows key must not survive into a stored or logged scrape error.

A request to the ZenRows API endpoint sends the key as a query parameter, and `requests`
quotes the request's path and query in a request error's message and the full URL in the
HTTPError `raise_for_status()` builds from `response.url`; urllib3 logs it too, on retries
and on headers it cannot parse, before the request returns. The missing-game drainer stores the error text in
`scrape_requests.error_message`, the event resolver logs it, and Actions logs are public.

The doubles answer with what `requests` really produces: a real `Response` carrying the URL
`requests` prepares, apikey and all, or the error a real session raises quoting that URL's
path and query. The
key holds `+`, `/` and `=`, so the percent-encoded form the URL carries differs from the raw one.
"""

import ast
import logging
import re
import socket
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, Mock

import pytest
import requests
from urllib3.util.retry import Retry

ROOT = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT))

from scripts.process_missing_games import MissingGamesProcessor  # noqa: E402
from src.scrapers._zenrows import ENDPOINT, ZenRowsSession, _redacted_zenrows_get  # noqa: E402
from src.scrapers.gotsport import GotSportScraper, GotsportScraper, _zenrows_get  # noqa: E402

KEY = "zr+Key/with=chars"
ENCODED = "zr%2BKey%2Fwith%3Dchars"
TEAM_ID = 513807
LOST_CONNECTION = (requests.exceptions.ConnectionError, "Max retries exceeded")
RETRIES_EXHAUSTED = (requests.exceptions.RetryError, "Max retries exceeded (too many 429 error responses)")
BAD_RECORD_MAC = (requests.exceptions.SSLError, "[SSL: DECRYPTION_FAILED_OR_BAD_RECORD_MAC] bad record mac")


def _prepared(url, params):
    return requests.Request("GET", url, params=params).prepare()


def _club_details():
    response = Mock()
    response.status_code = 200
    response.json = Mock(return_value={"club_name": "Home FC"})
    response.raise_for_status = Mock()
    return response


class _ZenRowsAnswering:
    """Answers the ZenRows endpoint with a real Response for a status no retry absorbs."""

    def get(self, url, params=None, timeout=None):
        if "/team_ranking_data/" in url:
            return _club_details()
        response = requests.Response()
        response.status_code = 422
        response.url = _prepared(url, params).url
        return response


class _ZenRowsRaising:
    """Raises the error a real session raises for a ZenRows failure, quoting the prepared path and query."""

    def __init__(self, failure):
        self.error, self.reason = failure
        self.closed = 0

    def get(self, url, params=None, timeout=None):
        if "/team_ranking_data/" in url:
            return _club_details()
        path = _prepared(url, params).path_url
        raise self.error(f"HTTPSConnectionPool(host='api.zenrows.com', port=443): {self.reason} with url: {path}")

    def close(self):
        self.closed += 1


def _team_scraper(session, attempts=1):
    scraper = GotSportScraper(MagicMock(), provider_code="gotsport")
    scraper.use_zenrows = True
    scraper.zenrows_api_key = KEY
    scraper.session = session
    scraper.max_retries = attempts
    scraper.retry_delay = 0
    scraper.delay_min = 0
    scraper.delay_max = 0
    return scraper


def _scrape(scraper):
    return scraper.scrape_team_games(str(TEAM_ID), since_date=datetime(2026, 9, 1))


def _stored_error(session):
    """The error_message the drainer writes when a request's scrape fails."""
    processor = MissingGamesProcessor(Mock(), dry_run=False)
    processor.scrapers["gotsport"] = _team_scraper(session)
    processor.get_provider_code = Mock(return_value="gotsport")
    processor.update_request_status = Mock()
    request = {
        "id": "req-1",
        "team_id_master": "team-1",
        "team_name": "Team 1",
        "provider_id": "prov-1",
        "provider_team_id": str(TEAM_ID),
        "game_date": "2026-11-15",
    }

    assert processor.process_request(request) is False
    [failed] = [c for c in processor.update_request_status.call_args_list if c.args[1] == "failed"]
    return failed.kwargs["error_message"]


def _assert_no_key(text):
    """The text carries an apikey and every one reads exactly REDACTED, so not even part of the key is left."""
    assert KEY not in text, text
    assert ENCODED not in text, text
    values = re.findall(r"apikey=([^&\s'\")]*)", text)
    assert values and set(values) == {"REDACTED"}, text


def test_the_fixture_url_carries_the_encoded_key_and_not_the_raw_one():
    url = _prepared(ENDPOINT, {"apikey": KEY, "url": "https://system.gotsport.com/x"}).url

    assert f"apikey={ENCODED}" in url
    assert KEY not in url


FAILURES = [_ZenRowsAnswering(), _ZenRowsRaising(LOST_CONNECTION), _ZenRowsRaising(RETRIES_EXHAUSTED)]
FAILURE_IDS = ["an error status", "no connection", "retries exhausted"]


@pytest.mark.parametrize("session", FAILURES, ids=FAILURE_IDS)
def test_the_drainer_stores_a_failed_scrape_without_the_key(session):
    _assert_no_key(_stored_error(session))


def test_a_lost_connection_is_raised_as_itself_without_its_keyed_original():
    """The original, whose message quotes the key, is not chained on for a traceback to print."""
    with pytest.raises(requests.exceptions.ConnectionError) as caught:
        _scrape(_team_scraper(_ZenRowsRaising(LOST_CONNECTION)))

    _assert_no_key(str(caught.value))
    assert caught.value.__cause__ is None and caught.value.__suppress_context__


def test_exhausted_retries_still_reach_the_retry_exhausted_branch(caplog):
    with caplog.at_level(logging.ERROR), pytest.raises(requests.exceptions.RetryError):
        _scrape(_team_scraper(_ZenRowsRaising(RETRIES_EXHAUSTED)))

    assert "gotsport 429 retry-exhausted" in caplog.text
    _assert_no_key(caplog.text)


def test_a_bad_record_mac_still_resets_the_session(monkeypatch):
    session = _ZenRowsRaising(BAD_RECORD_MAC)
    scraper = _team_scraper(session, attempts=2)
    monkeypatch.setattr("src.scrapers.gotsport.time.sleep", lambda _s: None)
    scraper._init_http_session = Mock(return_value=session)

    with pytest.raises(requests.exceptions.SSLError) as caught:
        _scrape(scraper)

    assert session.closed == 1
    scraper._init_http_session.assert_called_once()
    _assert_no_key(str(caught.value))


def test_urllib3s_own_retry_warnings_carry_no_key(monkeypatch, caplog):
    """urllib3 logs each retry, URL and all, before the session's error reaches the scraper.

    Connections are refused locally, so no request leaves the machine.
    """

    def refuse(*_a, **_kw):
        raise ConnectionRefusedError(111, "Connection refused")

    monkeypatch.setattr("urllib3.util.connection.create_connection", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(Retry, "sleep", lambda self, response=None: None)
    scraper = _team_scraper(GotSportScraper(MagicMock(), provider_code="gotsport").session)

    with caplog.at_level(logging.WARNING), pytest.raises(requests.exceptions.ConnectionError):
        _scrape(scraper)

    zenrows_retries = [r.getMessage() for r in caplog.records if r.getMessage().startswith("Retrying")]
    zenrows_retries = [m for m in zenrows_retries if "apikey=" in m]
    assert zenrows_retries
    _assert_no_key("\n".join(zenrows_retries))
    _assert_no_key(caplog.text)


def test_urllib3s_header_parse_warning_carries_no_key(monkeypatch, caplog):
    """urllib3 logs the whole request URL on `urllib3.connection` when a reply's headers do not parse.

    The reply comes from a socket on 127.0.0.1, so no request leaves the machine.
    """
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    server.settimeout(5)

    def answer():
        conn, _addr = server.accept()
        with conn:
            conn.recv(65536)
            conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\nnot a header\r\n\r\n")

    thread = threading.Thread(target=answer, daemon=True)
    thread.start()
    monkeypatch.setattr("src.scrapers._zenrows.ENDPOINT", f"http://127.0.0.1:{server.getsockname()[1]}/v1/")
    session = requests.Session()
    session.trust_env = False

    try:
        with caplog.at_level(logging.WARNING, logger="urllib3.connection"):
            _redacted_zenrows_get(session, {"apikey": KEY, "url": "https://system.gotsport.com/x"}, timeout=5)
    finally:
        thread.join(5)
        server.close()
        session.close()

    [warning] = [r.getMessage() for r in caplog.records if r.name == "urllib3.connection"]
    assert warning.startswith("Failed to parse headers"), warning
    _assert_no_key(warning)


def test_the_event_resolver_logs_a_lost_connection_without_the_key(caplog):
    scraper = MagicMock(spec=GotsportScraper)
    scraper.session = _ZenRowsRaising(LOST_CONNECTION)
    scraper.zenrows_api_key = KEY
    scraper.timeout = 10
    scraper.delay_min = 0
    scraper.delay_max = 0
    scraper._fetch_json_via_zenrows = GotsportScraper._fetch_json_via_zenrows.__get__(scraper, GotsportScraper)
    resolve = GotsportScraper._resolve_api_team_id_from_event_page.__get__(scraper, GotsportScraper)

    with caplog.at_level(logging.WARNING):
        assert resolve("e1", "12345", None) is None

    assert "ConnectionError" in caplog.text
    _assert_no_key(caplog.text)


def test_the_event_lookup_returns_a_response_whose_url_carries_no_key():
    response = _zenrows_get(
        _ZenRowsAnswering(), KEY, "https://system.gotsport.com/api/v1/teams/1/matches?past=true", timeout=10
    )

    _assert_no_key(response.url)


@pytest.mark.parametrize(
    "session",
    [_ZenRowsAnswering(), _ZenRowsRaising(LOST_CONNECTION)],
    ids=["an error status", "no connection"],
)
def test_the_sincsports_proxy_session_leaks_no_key(session):
    proxy = ZenRowsSession(api_key=KEY)
    proxy._session = session

    try:
        text = proxy.get("https://soccer.sincsports.com/schedule.aspx?tid=X").url
    except requests.exceptions.ConnectionError as exc:
        text = str(exc)

    _assert_no_key(text)


class _ZenRowsSenders(ast.NodeVisitor):
    """Each scope that names the ZenRows endpoint, by file and qualified name."""

    URL = "https://api.zenrows.com"

    def __init__(self, path):
        self.path, self.scope, self.found = path, [], set()
        self.names = {"ENDPOINT", "_ZENROWS_ENDPOINT", "ZENROWS_ENDPOINT"}

    def _enter(self, node):
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    visit_ClassDef = visit_FunctionDef = visit_AsyncFunctionDef = _enter

    def _hit(self):
        self.found.add((self.path, ".".join(self.scope) or "<module>"))

    def visit_ImportFrom(self, node):
        self.names |= {alias.asname for alias in node.names if alias.name in self.names and alias.asname}

    def visit_Name(self, node):
        if node.id in self.names:
            self._hit()

    def visit_Attribute(self, node):
        if node.attr in self.names:
            self._hit()
        self.generic_visit(node)

    def visit_Constant(self, node):
        if isinstance(node.value, str) and node.value.startswith(self.URL):
            self._hit()


def _zenrows_senders():
    found = set()
    for path in [*ROOT.joinpath("src").rglob("*.py"), *ROOT.joinpath("scripts").rglob("*.py")]:
        visitor = _ZenRowsSenders(path.relative_to(ROOT).as_posix())
        visitor.visit(ast.parse(path.read_text(encoding="utf-8")))
        found |= visitor.found
    return found


@pytest.mark.parametrize(
    "source",
    [
        'def f(s):\n    zenrows_url = "https://api.zenrows.com/v1/"\n    return s.get(zenrows_url)',
        "def f(s):\n    return s.get(url=ENDPOINT)",
        'def f(s):\n    return s.request("GET", _zenrows.ENDPOINT)',
        "from src.scrapers._zenrows import ENDPOINT as ZR\ndef f(s):\n    return s.get(ZR)",
        'def f(s, k):\n    return s.get(f"https://api.zenrows.com/v1/?apikey={k}")',
    ],
    ids=["a local variable", "a keyword", "an attribute", "an alias", "an f-string"],
)
def test_the_sender_scan_sees_every_way_of_naming_the_endpoint(source):
    visitor = _ZenRowsSenders("x.py")
    visitor.visit(ast.parse(source))

    assert ("x.py", "f") in visitor.found


def test_every_zenrows_request_goes_through_the_redacting_get():
    """A new ZenRows sender under src/ or scripts/ that skips `_redacted_zenrows_get` fails here.

    The event-roster fetcher keeps its own redaction, `redact_secret`.
    """
    assert _zenrows_senders() == {
        ("src/scrapers/_zenrows.py", "<module>"),
        ("src/scrapers/_zenrows.py", "_redacted_zenrows_get"),
        ("src/tournaments/gotsport_event_roster.py", "_fetch_once"),
    }


def test_every_zenrows_sender_filters_every_urllib3_logger():
    """Checked per sending module in a fresh interpreter, which loads exactly what importing it loads."""
    probe = (
        "import logging, {module}\n"
        "loggers = {{n: l for n, l in logging.Logger.manager.loggerDict.items()"
        " if n.split('.')[0] == 'urllib3' and isinstance(l, logging.Logger)}}\n"
        "print(sorted(loggers))\n"
        "print(sorted(n for n, l in loggers.items()"
        " if not any(type(f).__name__ == '_RedactApiKey' for f in l.filters)))\n"
    )
    modules = sorted({path.removesuffix(".py").replace("/", ".") for path, _scope in _zenrows_senders()})
    assert "src.tournaments.gotsport_event_roster" in modules

    for module in modules:
        result = subprocess.run(
            [sys.executable, "-c", probe.format(module=module)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=120,
            check=True,
        )
        loaded, unfiltered = (ast.literal_eval(line) for line in result.stdout.splitlines()[-2:])

        assert {"urllib3.connection", "urllib3.connectionpool", "urllib3.util.retry"} <= set(loaded), module
        assert unfiltered == [], module
