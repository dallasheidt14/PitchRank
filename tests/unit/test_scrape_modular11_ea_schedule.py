"""EA schedule pages: row parsing, 1-indexed paging, empty schedules, UTF-8 bodies."""

from pathlib import Path

import pytest
import requests

from scripts.scrape_modular11_ea import MATCHES_URL, ScrapeError, fetch_team_schedule, parse_schedule_page

FIX = Path(__file__).resolve().parent.parent / "fixtures" / "modular11_ea"
EMPTY = b" No data available. "


def _fixture(name: str) -> str:
    return (FIX / name).read_bytes().decode("utf-8")


class _Resp:
    def __init__(self, body: bytes, status: int = 200):
        self.content = body
        self.status_code = status

    @property
    def text(self):
        # requests guesses ISO-8859-1 for an HTML body served without a charset
        return self.content.decode("iso-8859-1")

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code}")


class _Session:
    """Serves bodies by open_page and records url, params, headers and timeout of every call."""

    def __init__(self, pages: dict[int, bytes]):
        self.pages = pages
        self.calls = []

    def get(self, url, params=None, headers=None, timeout=None, **kw):
        self.calls.append({"url": url, "params": dict(params or {}), "headers": headers, "timeout": timeout})
        return _Resp(self.pages[int(params["open_page"])])


def _paged(current: int, total: int) -> bytes:
    return f"<div></div><span>{current} page out of {total}</span>".encode("utf-8")


def test_parses_played_and_tbd_rows():
    rows, total = parse_schedule_page(_fixture("team_7343_p1.html"), expected_page=1)
    assert total == 1 and len(rows) == 20
    first = next(r for r in rows if r.match_no == "122957")
    assert (first.home_name, first.home_academy, first.away_academy) == ("FLYTE SC- Inland Empire", "1408", "101")
    assert (first.home_score, first.away_score) == (6, 0)
    assert first.game_date == "2026-09-12" and first.bracket == "EA" and first.gender == "MALE"
    later = next(r for r in rows if r.match_no == "123251")
    assert (later.home_score, later.away_score) == (None, None)


def test_intra_club_row_keeps_both_names():
    rows, _ = parse_schedule_page(_fixture("team_7343_p1.html"), expected_page=1)
    derby = next(r for r in rows if r.match_no == "123269")
    assert derby.home_academy == derby.away_academy == "1408"
    assert {derby.home_name, derby.away_name} == {"FLYTE SC Blue- Inland Empire", "FLYTE SC- Inland Empire"}


def test_no_data_is_zero_games():
    assert parse_schedule_page(EMPTY.decode(), expected_page=1) == ([], 0)


def test_markerless_body_raises():
    with pytest.raises(ScrapeError, match="page out of"):
        parse_schedule_page("<html>maintenance</html>", expected_page=1)


def test_wrong_current_page_raises():
    with pytest.raises(ScrapeError, match="asked for page 2"):
        parse_schedule_page(_paged(1, 3).decode(), expected_page=2)


def test_fetch_requests_pages_one_through_n_exactly():
    session = _Session({1: _paged(1, 3), 2: _paged(2, 3), 3: _paged(3, 3)})
    fetch_team_schedule(session, "7343", "2026-08-01 00:00:00", "2027-07-31 23:59:59", sleep=lambda s: None)
    assert [c["params"]["open_page"] for c in session.calls] == [1, 2, 3]
    call = session.calls[0]
    assert call["url"] == MATCHES_URL
    assert call["params"]["team"] == "7343" and call["params"]["tournament"] == "27"
    assert call["params"]["start_date"] == "2026-08-01 00:00:00"
    assert call["timeout"] == 30 and "User-Agent" in call["headers"]


def test_fetch_empty_team_makes_one_call():
    session = _Session({1: EMPTY})
    assert fetch_team_schedule(session, "1", "a", "b", sleep=lambda s: None) == []
    assert len(session.calls) == 1


def test_fetch_decodes_utf8_names():
    body = (FIX / "team_7343_p1.html").read_bytes().replace(b"ALBION SC San Diego", "Atlético SD".encode("utf-8"))
    session = _Session({1: body})
    rows = fetch_team_schedule(session, "7343", "a", "b", sleep=lambda s: None)
    assert any(r.away_name == "Atlético SD" for r in rows)
