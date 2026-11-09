"""Reading Kitman's standings files: shape guards, squad labels, local dates, played versus scheduled."""

import csv
import json
from datetime import date

import pytest

from scripts import scrape_mlsnext_kitman as scrape

SYNC_DAY = date(2026, 11, 9)


def _event(eid=1, home=(10, "U16", 100, "Alpha SC"), away=(11, "U16", 101, "Beta FC"), scores=(2, 1), completed=True,
           start="2026-09-05T13:00:00Z", tz="America/New_York", competition="League"):
    """A game as ``parse_feed`` hands it on. Like the real files, an unplayed game has no score keys at all."""
    event = {
        "id": eid,
        "start_time": start,
        "local_timezone": tz,
        "home_squad_id": home[0],
        "away_squad_id": away[0],
        "home_squad_name": home[1],
        "away_squad_name": away[1],
        "home_organisation": {"id": home[2], "name": home[3]},
        "away_organisation": {"id": away[2], "name": away[3]},
        "completed": completed,
        "competition": {"id": competition, "name": competition},
    }
    if scores:
        event["home_score"], event["away_score"] = scores
    return event


def _standings_file(**overrides):
    """A standings file in the shape the host served on 2026-11-09: one game, with invented ids and scores."""
    event = {
        "id": 5737796,
        "game_key": "26207",
        "start_time": "2026-09-05T12:00:00Z",
        "local_timezone": "America/New_York",
        "home_squad_id": 7237,
        "away_squad_id": 9729,
        "home_squad_name": "U19",
        "away_squad_name": "U19",
        "competition_id": 1607,
        "competition_bracket_id": 184,
        "completed": True,
        "home_organisation_id": 612,
        "away_organisation_id": 1438,
        "home_score": 3,
        "away_score": 1,
        "home_penalty_shootout_score": 0,
        "away_penalty_shootout_score": 0,
        "event_location_id": 10,
        "game_event_id": 1,
    }
    body = {
        "name": "League 26/27",
        "key": "mls-next-league-26-27",
        "kind": "season",
        "competition_id": 1605,
        "events": [event],
        "organisations": [{"id": 612, "name": "Toronto FC", "logo_url": "x"}, {"id": 1438, "name": "Beta FC", "logo_url": "x"}],
        "competitions": [{"id": 1605, "name": "League"}, {"id": 1607, "name": "MLS NEXT Flex"}],
        **overrides,
    }
    return json.dumps({"version": 2, "competition_season": body, "synced_at": "2026-11-09T03:00:07Z"}).encode()


def _feed(events, stem):
    """``_event`` games written out as a standings file, naming their clubs and competitions by id."""
    clubs, competitions, raw = {}, {}, []
    for event in events:
        event = dict(event)
        for side in ("home", "away"):
            club = event.pop(f"{side}_organisation")
            clubs[club["id"]] = club
            event[f"{side}_organisation_id"] = club["id"]
        competition = event.pop("competition")
        competitions[competition["id"]] = competition
        event["competition_id"] = competition["id"]
        raw.append(event)
    return _standings_file(
        key=f"{stem}-26-27", events=raw, organisations=list(clubs.values()), competitions=list(competitions.values())
    )


def test_urls_carry_the_season_suffix():
    assert scrape.feed_url("mls-next-league", 2026).endswith("/standings/mls-next-league-26-27.json")
    assert scrape.season_suffix(2099) == "99-00"


def test_each_competition_has_its_own_floor():
    assert scrape.FEEDS == (
        ("mls-next-league", "HD", {"League": 3000, "League (Pro Player Pathway)": 200, "MLS NEXT Flex": 1000}),
        ("mls-next-2-academy-division", "AD", {"Academy Division": 5000}),
    )


def test_an_html_page_served_at_status_200_is_refused():
    with pytest.raises(scrape.ScrapeError, match="not JSON"):
        scrape.parse_feed(b"<!doctype html><html></html>", "mls-next-league", 2026, floors={}, today=SYNC_DAY)


@pytest.mark.parametrize(
    "body",
    [
        {"events": [_event()], "linked_competition_seasons": [{"key": "mls-next-league-26-27"}]},
        {"competition_season": {"key": "mls-next-league-26-27", "events": None}},
        {"competition_season": None},
        [_event()],
    ],
    ids=["schedule shape", "null events", "null season", "top-level array"],
)
def test_a_file_with_no_events_array_is_refused(body):
    with pytest.raises(scrape.ScrapeError, match="no events array"):
        scrape.parse_feed(json.dumps(body).encode(), "mls-next-league", 2026, floors={}, today=SYNC_DAY)


@pytest.mark.parametrize("key", ["mls-next-league-25-26", None], ids=["last season", "no key"])
def test_a_feed_for_another_season_is_refused(key):
    with pytest.raises(scrape.ScrapeError, match="not mls-next-league-26-27"):
        scrape.parse_feed(_standings_file(key=key), "mls-next-league", 2026, floors={}, today=SYNC_DAY)


def test_a_season_key_is_escaped_in_the_refusal():
    with pytest.raises(scrape.ScrapeError) as refused:
        scrape.parse_feed(_standings_file(key="x\n::error::forged"), "mls-next-league", 2026, floors={}, today=SYNC_DAY)
    assert "\n" not in str(refused.value)


def test_a_file_synced_eight_days_ago_is_read():
    events = scrape.parse_feed(_standings_file(), "mls-next-league", 2026, floors={}, today=date(2026, 11, 17))
    assert len(events) == 1


def test_a_file_synced_nine_days_ago_is_refused():
    with pytest.raises(scrape.ScrapeError, match="last synced 2026-11-09, over 8 days ago"):
        scrape.parse_feed(_standings_file(), "mls-next-league", 2026, floors={}, today=date(2026, 11, 18))


@pytest.mark.parametrize("synced_at", [None, "not a time"], ids=["null", "text"])
def test_a_file_with_an_unreadable_sync_time_is_refused(synced_at):
    file = json.loads(_standings_file())
    file["synced_at"] = synced_at
    with pytest.raises(scrape.ScrapeError, match="unreadable synced_at"):
        scrape.parse_feed(json.dumps(file).encode(), "mls-next-league", 2026, floors={}, today=SYNC_DAY)


def test_a_file_with_no_sync_time_is_refused():
    file = json.loads(_standings_file())
    del file["synced_at"]
    with pytest.raises(scrape.ScrapeError, match="unreadable synced_at"):
        scrape.parse_feed(json.dumps(file).encode(), "mls-next-league", 2026, floors={}, today=SYNC_DAY)


def test_a_truncated_feed_is_refused():
    with pytest.raises(scrape.ScrapeError, match="1 readable MLS NEXT Flex events is below the floor of 2"):
        scrape.parse_feed(_standings_file(), "mls-next-league", 2026, floors={"MLS NEXT Flex": 2}, today=SYNC_DAY)


@pytest.mark.parametrize("kept, lost", [("League", "MLS NEXT Flex"), ("MLS NEXT Flex", "League")])
def test_a_file_that_lost_one_competition_is_refused_though_the_other_clears_its_floor(kept, lost):
    body = _feed([_event(competition=kept)], "mls-next-league")
    with pytest.raises(scrape.ScrapeError, match=f"0 readable {lost} events"):
        scrape.parse_feed(body, "mls-next-league", 2026, floors={"League": 1, "MLS NEXT Flex": 1}, today=SYNC_DAY)


@pytest.mark.parametrize(
    "clubs",
    [
        [],
        None,
        [{"id": "612", "name": "Toronto FC"}, {"id": "1438", "name": "Beta FC"}],
        [{"club_id": 612, "name": "Toronto FC"}, {"club_id": 1438, "name": "Beta FC"}],
        [{"id": 612, "name": "Toronto FC"}],
        [{"id": 1438, "name": "Beta FC"}],
    ],
    ids=["empty", "null", "ids as strings", "id key renamed", "away club lost", "home club lost"],
)
def test_a_file_whose_clubs_cannot_be_found_is_refused(clubs):
    with pytest.raises(scrape.ScrapeError, match="0 readable MLS NEXT Flex events"):
        scrape.parse_feed(_standings_file(organisations=clubs), "mls-next-league", 2026, floors={"MLS NEXT Flex": 1}, today=SYNC_DAY)


@pytest.mark.parametrize(
    "competitions",
    [[], None, [{"id": "1607", "name": "MLS NEXT Flex"}]],
    ids=["empty", "null", "ids as strings"],
)
def test_a_file_whose_competitions_cannot_be_found_is_refused(competitions):
    with pytest.raises(scrape.ScrapeError, match="0 readable MLS NEXT Flex events"):
        scrape.parse_feed(_standings_file(competitions=competitions), "mls-next-league", 2026, floors={"MLS NEXT Flex": 1}, today=SYNC_DAY)


def test_a_game_reads_its_clubs_and_competition_from_the_lists_beside_it():
    events = scrape.parse_feed(_standings_file(), "mls-next-league", 2026, floors={"MLS NEXT Flex": 1}, today=SYNC_DAY)
    squads, games, unreadable = scrape.build([("HD", events)], 2026)
    assert unreadable == {}
    assert squads["7237"] == scrape.Squad("7237", "612", "Toronto FC", "u19", "HD")
    assert squads["9729"] == scrape.Squad("9729", "1438", "Beta FC", "u19", "HD")
    assert (games[0]["competition"], games[0]["home_score"], games[0]["away_score"]) == ("MLS NEXT Flex", 3, 1)


@pytest.mark.parametrize(
    "club_id, club_name, kept, lost, keys",
    [
        (612, "Toronto FC", "7237", "9729", ("7237:2026", "")),
        (1438, "Beta FC", "9729", "7237", ("", "9729:2026")),
    ],
    ids=["away club missing", "home club missing"],
)
def test_one_club_the_list_does_not_hold_is_left_out_and_reported(club_id, club_name, kept, lost, keys):
    clubs = [{"id": club_id, "name": club_name}]
    events = scrape.parse_feed(_standings_file(organisations=clubs), "mls-next-league", 2026, floors={}, today=SYNC_DAY)
    squads, games, unreadable = scrape.build([("HD", events)], 2026)
    assert set(squads) == {kept} and unreadable == {lost: "squad id missing or club not found"}
    assert (games[0]["home_key"], games[0]["away_key"]) == keys


def test_one_competition_the_list_does_not_hold_leaves_that_games_label_blank():
    competitions = [{"id": 1605, "name": "League"}]
    events = scrape.parse_feed(_standings_file(competitions=competitions), "mls-next-league", 2026, floors={}, today=SYNC_DAY)
    _, games, _ = scrape.build([("HD", events)], 2026)
    assert (games[0]["status"], games[0]["competition"]) == ("played", "")


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


@pytest.mark.parametrize(
    "label",
    ["U17b", "U17 B", "U17BB", "U17C", "U16 AD*", "U19 AD**", "U16 AD Inactive", "U12", "U18", "", "U16\n", "U１６", "U16 ad"],
)
def test_a_label_that_is_not_a_board_age_is_left_out_and_reported(label):
    event = _event(home=(30, label, 300, "Odd FC"))
    squads, games, unreadable = scrape.build([("HD", [event])], 2026)
    assert "30" not in squads and "30" in unreadable
    assert games[0]["home_key"] == "" and games[0]["home_squad_id"] == ""


def test_a_b_squad_is_its_own_squad_on_the_base_age_board():
    event = _event(home=(30, "U17B", 300, "FC Dallas"), away=(31, "U17", 301, "Alpha SC"))
    squads, games, unreadable = scrape.build([("HD", [event])], 2026)
    assert unreadable == {}
    assert squads["30"] == scrape.Squad("30", "300", "FC Dallas", "u17", "HD", "B")
    assert squads["30"].display_name == "FC Dallas U17 HD II"
    assert squads["31"].suffix == "" and squads["31"].display_name == "Alpha SC U17 HD"
    assert (games[0]["age_group"], games[0]["home_key"], games[0]["away_key"]) == ("u17", "30:2026", "31:2026")


def test_a_b_suffix_on_an_academy_label_is_not_guessed_at():
    event = _event(home=(50, "U17B AD", 500, "Odd FC"), away=(51, "U17 AD", 501, "Even FC"))
    squads, _, unreadable = scrape.build([("AD", [event])], 2026)
    assert set(squads) == {"51"} and "is not a board age" in unreadable["50"]


def test_an_academy_label_keeps_its_age_and_takes_no_suffix():
    event = _event(home=(40, "U16 AD", 400, "Gamma"), away=(41, "U16 AD", 401, "Delta"))
    squads, _, _ = scrape.build([("AD", [event])], 2026)
    assert (squads["40"].age_group, squads["40"].division, squads["40"].suffix) == ("u16", "AD", "")
    assert squads["40"].display_name == "Gamma U16 AD"


def test_the_squads_file_carries_the_suffix(tmp_path, monkeypatch):
    league = [_event(2, home=(30, "U17B", 300, "FC Dallas"), away=(31, "U17", 301, "Alpha SC"))]
    academy = [_event(3, home=(20, "U14 AD", 200, "Gamma"), away=(21, "U14 AD", 201, "Delta"))]
    feeds = {"mls-next-league": league, "mls-next-2-academy-division": academy}
    _run(tmp_path, feeds, date(2026, 10, 1), monkeypatch)
    rows = {r["provider_team_id"]: r for r in csv.DictReader((tmp_path / "squads.csv").open(encoding="utf-8"))}
    squad = rows["30"]
    assert (squad["suffix"], squad["display_name"], squad["age_group"]) == ("B", "FC Dallas U17 HD II", "u17")
    assert (rows["31"]["suffix"], rows["31"]["display_name"]) == ("", "Alpha SC U17 HD")


def test_the_suffixed_name_survives_the_normalizer_and_stays_a_separate_squad():
    from scripts._team_distinction import should_skip_pair as merge_gate_skips_pair
    from scripts.normalize_team_names import normalize_team_name
    from src.utils.team_name_utils import resolve_distinction, should_skip_pair

    plain, suffixed, club = "FC Dallas U17 HD", "FC Dallas U17 HD II", "FC Dallas"
    assert merge_gate_skips_pair(plain, suffixed, club_name=club) is True
    assert normalize_team_name(plain) == plain and normalize_team_name(suffixed) == suffixed
    assert resolve_distinction(plain, club, None) == "hd"
    assert resolve_distinction(suffixed, club, None) == "ii|hd"
    assert should_skip_pair(plain, suffixed) is True


def test_one_squad_id_under_two_clubs_is_an_error():
    clash = _event(2, home=(10, "U16", 999, "Other FC"))
    with pytest.raises(scrape.ScrapeError, match="squad 10 seen as"):
        scrape.build([("HD", [_event(), clash])], 2026)


def test_one_squad_id_labelled_with_and_without_the_suffix_is_an_error():
    relabelled = _event(2, home=(30, "U17B", 300, "FC Dallas"))
    with pytest.raises(scrape.ScrapeError, match="squad 30 seen as"):
        scrape.build([("HD", [_event(home=(30, "U17", 300, "FC Dallas")), relabelled])], 2026)


def test_a_completed_game_with_a_missing_score_is_not_played():
    _, games, _ = scrape.build([("HD", [_event(scores=None)])], 2026)
    assert games[0]["status"] == "scheduled" and games[0]["home_score"] == ""


@pytest.mark.parametrize("missing", ["home_score", "away_score"])
def test_a_completed_game_with_one_score_is_not_played(missing):
    event = _event()
    del event[missing]
    _, games, _ = scrape.build([("HD", [event])], 2026)
    assert (games[0]["status"], games[0]["home_score"], games[0]["away_score"]) == ("scheduled", "", "")


def test_an_uncompleted_game_with_a_score_is_not_played():
    _, games, _ = scrape.build([("HD", [_event(completed=False)])], 2026)
    assert games[0]["status"] == "scheduled"


def test_a_zero_zero_game_is_played():
    _, games, _ = scrape.build([("HD", [_event(scores=(0, 0))])], 2026)
    assert (games[0]["status"], games[0]["home_score"], games[0]["away_score"]) == ("played", 0, 0)


def test_an_event_listed_twice_is_one_game_and_the_first_listing_wins():
    _, games, _ = scrape.build([("HD", [_event(), _event(scores=(9, 9))])], 2026)
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
    monkeypatch.setattr(scrape, "FEEDS", tuple((s, d, {}) for s, d, _ in scrape.FEEDS))
    session = _Session(events_by_stem)
    return scrape.run(tmp_path, session, today), session


def test_run_writes_squads_and_games_and_never_needs_the_database(tmp_path, monkeypatch):
    flex = _event(2, scores=None, completed=False, competition="MLS NEXT Flex")
    academy = _event(3, home=(20, "U14 AD", 200, "Gamma"), away=(21, "U14 AD", 201, "Delta"))
    counts, session = _run(
        tmp_path,
        {"mls-next-league": [_event(), flex], "mls-next-2-academy-division": [academy]},
        date(2026, 10, 14),
        monkeypatch,
    )
    assert counts == {"squads": 4, "unreadable_squads": 0, "games": 3, "played": 2, "scheduled": 1}
    games = {g["event_id"]: g for g in csv.DictReader((tmp_path / "games.csv").open(encoding="utf-8"))}
    assert (games["2"]["competition"], games["2"]["division"]) == ("MLS NEXT Flex", "HD")
    assert [url for url, _, _ in session.urls] == [
        "https://mls-assist.theintelligenceplatform.com/data/standings/mls-next-league-26-27.json",
        "https://mls-assist.theintelligenceplatform.com/data/standings/mls-next-2-academy-division-26-27.json",
    ]
    squads = list(csv.DictReader((tmp_path / "squads.csv").open(encoding="utf-8")))
    assert {(s["provider_team_id"], s["key"], s["division"], s["gender"], s["season"]) for s in squads} >= {
        ("10", "10:2026", "HD", "Male", "2026"),
        ("20", "20:2026", "AD", "Male", "2026"),
    }
    assert all(timeout == 60 and "User-Agent" in headers for _, timeout, headers in session.urls)


def test_a_run_refuses_a_file_below_the_real_floors_and_writes_nothing(tmp_path):
    session = _Session({"mls-next-league": [_event()], "mls-next-2-academy-division": []})
    with pytest.raises(scrape.ScrapeError, match="below the floor"):
        scrape.run(tmp_path, session, date(2026, 10, 14))
    assert not (tmp_path / "games.csv").exists()


def test_a_run_refuses_a_frozen_file_and_writes_nothing(tmp_path, monkeypatch):
    feeds = {"mls-next-league": [_event()], "mls-next-2-academy-division": []}
    with pytest.raises(scrape.ScrapeError, match="last synced"):
        _run(tmp_path, feeds, date(2026, 12, 1), monkeypatch)
    assert not (tmp_path / "games.csv").exists()


def test_main_exits_nonzero_when_a_file_is_refused(tmp_path, monkeypatch, capsys):
    class _HtmlSession:
        def get(self, url, headers=None, timeout=None):
            return _Response(b"<!doctype html><html></html>")

    monkeypatch.setattr(scrape.requests, "Session", _HtmlSession)
    assert scrape.main(["--out-dir", str(tmp_path)]) == 1
    assert "not JSON" in capsys.readouterr().err


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
    assert list(unreadable.values()) == ["squad id missing or club not found"]
    assert (games[0]["home_key"], games[0]["away_key"]) == ("", "11:2026")


def test_an_id_less_squad_never_becomes_a_key():
    squads, games, _ = scrape.build([("HD", [_event(home=(None, "U16", 100, "Alpha SC"))])], 2026)
    assert all(squad_id != "None" for squad_id in squads) and games[0]["home_key"] == ""
