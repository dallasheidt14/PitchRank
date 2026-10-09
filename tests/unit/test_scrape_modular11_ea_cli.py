"""run() drives page fetch, roster filter, per-team schedules and CSVs; failures leave no files."""

import csv
from datetime import date
from pathlib import Path

import pytest

from scripts import scrape_modular11_ea as ea

FIX = Path(__file__).resolve().parent.parent / "fixtures" / "modular11_ea"


class _Resp:
    def __init__(self, body: bytes):
        self.content, self.status_code = body, 200

    def raise_for_status(self):
        pass


class _Session:
    def __init__(self, page: bytes):
        self.page, self.calls = page, []

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append((url, dict(params or {})))
        if url == ea.EA_PAGE_URL:
            return _Resp(self.page)
        path = FIX / f"team_{params['team']}_p1.html"
        return _Resp(path.read_bytes() if path.exists() else b"No data available.")


def test_season_bounds_rolls_on_aug_1():
    assert ea.season_bounds(date(2026, 7, 31)) == ("2025-08-01 00:00:00", "2026-07-31 23:59:59")
    assert ea.season_bounds(date(2026, 8, 1)) == ("2026-08-01 00:00:00", "2027-07-31 23:59:59")


def test_run_writes_one_age(tmp_path):
    session = _Session((FIX / "ea_page.html").read_bytes())
    counts = ea.run("u13", tmp_path, session, date(2026, 10, 4), sleep=lambda s: None)
    teams = list(csv.DictReader((tmp_path / "u13" / "teams.csv").open(encoding="utf-8")))
    assert {t["age_group"] for t in teams} == {"u13"}
    assert len(teams) == counts["teams"] == len([c for c in session.calls if c[0] == ea.MATCHES_URL])
    flyte = next(t for t in teams if t["provider_team_id"] == "9176")
    assert flyte["display_name"] == "FLYTE SC Blue- Inland Empire" and flyte["gender"] == "Male"
    assert flyte["name_tier"] == "EA"
    games = list(csv.DictReader((tmp_path / "u13" / "games.csv").open(encoding="utf-8")))
    assert counts["games"] == len(games) == 39
    assert {t["season"] for t in teams} == {"2026"}
    assert all(g["home_key"] == f"{g['home_team_id']}:2026" for g in games if g["home_team_id"])
    assert all(g["away_key"] == (f"{g['away_team_id']}:2026" if g["away_team_id"] else "") for g in games)


def test_failure_exits_1_and_writes_nothing(tmp_path, monkeypatch):
    page = (FIX / "ea_page.html").read_bytes().replace(b"dependencies:", b"gone:")
    monkeypatch.setattr(ea, "_new_session", lambda: _Session(page))
    assert ea.main(["--age", "u13", "--out-dir", str(tmp_path)]) == 1
    assert not (tmp_path / "u13").exists()


def test_female_row_fails_the_run(tmp_path):
    flipped = (FIX / "team_7343_p1.html").read_bytes().replace(b"MALE", b"FEMALE", 1)
    session = _Session((FIX / "ea_page.html").read_bytes())
    real_get = session.get

    def get(url, params=None, headers=None, timeout=None):
        if params and params.get("team") == "7343":
            session.calls.append((url, dict(params)))
            return _Resp(flipped)
        return real_get(url, params=params, headers=headers, timeout=timeout)

    session.get = get
    with pytest.raises(ea.ScrapeError, match="FEMALE"):
        ea.run("u13", tmp_path, session, date(2026, 10, 4), sleep=lambda s: None)
    assert not (tmp_path / "u13").exists()
