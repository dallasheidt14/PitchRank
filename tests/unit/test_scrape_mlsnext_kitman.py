"""Reading Kitman's schedule files: shape guards, squad labels, local dates, played versus scheduled."""

import csv
import json
from datetime import date

import pytest

from scripts import scrape_mlsnext_kitman as scrape


def _event(eid=1, home=(10, "U16", 100, "Alpha SC"), away=(11, "U16", 101, "Beta FC"), scores=(2, 1), completed=True,
           start="2026-09-05T13:00:00Z", tz="America/New_York", competition="League"):
    return {
        "id": eid,
        "start_time": start,
        "local_timezone": tz,
        "home_squad_id": home[0],
        "away_squad_id": away[0],
        "home_squad_name": home[1],
        "away_squad_name": away[1],
        "home_organisation": {"id": home[2], "name": home[3]},
        "away_organisation": {"id": away[2], "name": away[3]},
        "home_score": scores[0] if scores else None,
        "away_score": scores[1] if scores else None,
        "completed": completed,
        "competition": {"id": 1, "name": competition},
    }


def _feed(events, stem="mls-next-league", season=2026):
    return json.dumps(
        {"events": events, "linked_competition_seasons": [{"key": f"{stem}-26-27"}], "synced_at": "x"}
    ).encode()


def test_urls_carry_the_season_suffix():
    assert scrape.feed_url("mls-next-league", 2026).endswith("/schedule/mls-next-league-26-27.json")
    assert scrape.season_suffix(2099) == "99-00"


def test_an_html_page_served_at_status_200_is_refused():
    with pytest.raises(scrape.ScrapeError, match="not JSON"):
        scrape.parse_feed(b"<!doctype html><html></html>", "mls-next-league", 2026, floor=1)


def test_a_feed_for_another_season_is_refused():
    body = json.dumps({"events": [_event()], "linked_competition_seasons": [{"key": "mls-next-league-25-26"}]}).encode()
    with pytest.raises(scrape.ScrapeError, match="not mls-next-league-26-27"):
        scrape.parse_feed(body, "mls-next-league", 2026, floor=1)


def test_a_truncated_feed_is_refused():
    with pytest.raises(scrape.ScrapeError, match="below the floor"):
        scrape.parse_feed(_feed([_event()]), "mls-next-league", 2026, floor=2)


def test_events_come_back_when_the_feed_is_sound():
    assert len(scrape.parse_feed(_feed([_event(), _event(2)]), "mls-next-league", 2026, floor=2)) == 2


def test_the_local_date_follows_the_games_own_timezone():
    late_pacific = _event(start="2026-09-06T03:30:00Z", tz="America/Los_Angeles")
    assert scrape.local_date(late_pacific) == "2026-09-05"
    assert scrape.local_date(_event(start="2026-09-06T03:30:00Z", tz="America/New_York")) == "2026-09-05"
    assert scrape.local_date(_event(start="2026-09-06T05:30:00Z", tz="America/New_York")) == "2026-09-06"


def test_an_unreadable_start_raises():
    with pytest.raises(scrape.ScrapeError):
        scrape.local_date({"id": 9, "start_time": "not a time", "local_timezone": "America/New_York"})


def test_squads_and_a_played_game_are_built():
    squads, games, unreadable = scrape.build([("HD", [_event()])], 2026)
    assert unreadable == {}
    assert squads["10"] == scrape.Squad("10", "100", "Alpha SC", "u16", "HD")
    assert squads["10"].display_name == "Alpha SC U16 HD"
    game = games[0]
    assert (game["status"], game["game_date"], game["home_key"], game["away_key"]) == ("played", "2026-09-05", "10:2026", "11:2026")
    assert (game["home_score"], game["away_score"], game["division"], game["competition"]) == (2, 1, "HD", "League")


def test_an_academy_label_must_carry_ad_and_a_homegrown_label_must_not():
    ad = _event(home=(20, "U14 AD", 200, "Gamma"), away=(21, "U14 AD", 201, "Delta"))
    squads, _, unreadable = scrape.build([("AD", [ad])], 2026)
    assert squads["20"].division == "AD" and squads["20"].display_name == "Gamma U14 AD"
    squads, _, unreadable = scrape.build([("HD", [ad])], 2026)
    assert squads == {} and set(unreadable) == {"20", "21"}
    assert "disagrees with the HD feed" in unreadable["20"]


@pytest.mark.parametrize("label", ["U17B", "U16 AD*", "U12", "U18", "", "U16\n", "U１６", "U16 ad"])
def test_a_label_that_is_not_a_board_age_is_left_out_and_reported(label):
    event = _event(home=(30, label, 300, "Odd FC"))
    squads, games, unreadable = scrape.build([("HD", [event])], 2026)
    assert "30" not in squads and "30" in unreadable
    assert games[0]["home_key"] == "" and games[0]["home_squad_id"] == ""


def test_one_squad_id_under_two_clubs_is_an_error():
    clash = _event(2, home=(10, "U16", 999, "Other FC"))
    with pytest.raises(scrape.ScrapeError, match="squad 10 seen as"):
        scrape.build([("HD", [_event(), clash])], 2026)


def test_a_completed_game_with_a_missing_score_is_not_played():
    _, games, _ = scrape.build([("HD", [_event(scores=None)])], 2026)
    assert games[0]["status"] == "scheduled" and games[0]["home_score"] == ""


def test_an_uncompleted_game_with_a_score_is_not_played():
    _, games, _ = scrape.build([("HD", [_event(completed=False)])], 2026)
    assert games[0]["status"] == "scheduled"


def test_a_zero_zero_game_is_played():
    _, games, _ = scrape.build([("HD", [_event(scores=(0, 0))])], 2026)
    assert (games[0]["status"], games[0]["home_score"], games[0]["away_score"]) == ("played", 0, 0)


def test_an_event_listed_in_two_files_is_one_game_and_the_first_listing_wins():
    _, games, _ = scrape.build([("HD", [_event()]), ("HD", [_event(scores=(9, 9))])], 2026)
    assert [(g["home_score"], g["away_score"]) for g in games] == [(2, 1)]


class _Response:
    def __init__(self, content):
        self.content = content

    def raise_for_status(self):
        pass


class _Session:
    def __init__(self, events_by_stem):
        self.events_by_stem, self.urls = events_by_stem, []

    def get(self, url, headers=None, timeout=None):
        self.urls.append((url, timeout, headers))
        stem = next(s for s, _, _ in scrape.FEEDS if f"/{s}-26-27.json" in url)
        return _Response(_feed(self.events_by_stem[stem], stem))


def _run(tmp_path, events_by_stem, today, monkeypatch):
    monkeypatch.setattr(scrape, "FEEDS", tuple((s, d, 1) for s, d, _ in scrape.FEEDS))
    session = _Session(events_by_stem)
    return scrape.run(tmp_path, session, today), session


def test_run_writes_squads_and_games_and_never_needs_the_database(tmp_path, monkeypatch):
    academy = _event(3, home=(20, "U14 AD", 200, "Gamma"), away=(21, "U14 AD", 201, "Delta"))
    counts, session = _run(
        tmp_path,
        {"mls-next-league": [_event()], "mls-next-flex": [_event(2, scores=None, completed=False)], "mls-next-2-academy-division": [academy]},
        date(2026, 10, 14),
        monkeypatch,
    )
    assert counts == {"squads": 4, "unreadable_squads": 0, "games": 3, "played": 2, "scheduled": 1}
    squads = list(csv.DictReader((tmp_path / "squads.csv").open(encoding="utf-8")))
    assert {(s["provider_team_id"], s["key"], s["division"], s["gender"], s["season"]) for s in squads} >= {
        ("10", "10:2026", "HD", "Male", "2026"),
        ("20", "20:2026", "AD", "Male", "2026"),
    }
    assert all(timeout == 60 and "User-Agent" in headers for _, timeout, headers in session.urls)


def test_a_season_with_no_scored_games_in_season_fails(tmp_path, monkeypatch):
    unplayed = [_event(scores=None, completed=False)]
    with pytest.raises(scrape.ScrapeError, match="no scored games"):
        _run(tmp_path, {s: unplayed for s, _, _ in scrape.FEEDS}, date(2026, 10, 14), monkeypatch)


def test_zero_scored_games_before_the_season_starts_is_fine(tmp_path, monkeypatch):
    unplayed = [_event(scores=None, completed=False)]
    counts, _ = _run(tmp_path, {s: unplayed for s, _, _ in scrape.FEEDS}, date(2026, 9, 1), monkeypatch)
    assert counts["played"] == 0


@pytest.mark.parametrize(
    "home",
    [(None, "U16", 100, "Alpha SC"), (10, "U16", None, "Alpha SC"), (10, "U16", 100, ""), (10, "U16", 100, None)],
    ids=["no squad id", "no club id", "blank club name", "no club name"],
)
def test_a_side_missing_an_id_or_a_club_name_is_left_out_and_reported(home):
    squads, games, unreadable = scrape.build([("HD", [_event(home=home)])], 2026)
    assert "10" not in squads and set(squads) == {"11"}
    assert list(unreadable.values()) == ["squad or club id missing"]
    assert (games[0]["home_key"], games[0]["away_key"]) == ("", "11:2026")


def test_an_id_less_squad_never_becomes_a_key():
    squads, games, _ = scrape.build([("HD", [_event(home=(None, "U16", 100, "Alpha SC"))])], 2026)
    assert all(squad_id != "None" for squad_id in squads) and games[0]["home_key"] == ""
