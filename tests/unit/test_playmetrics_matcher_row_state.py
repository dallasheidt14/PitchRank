"""The PlayMetrics league matcher scopes each game to the state on its CSV row.

The row's ``state_code`` scopes the fuzzy-candidate query and is written onto any
team autocreated for the row; the rules are in ``src/models/playmetrics_matcher.py``.
"""

import csv
from pathlib import Path
from unittest.mock import MagicMock, patch

from postgrest.exceptions import APIError

from scripts.import_games_enhanced import load_games_csv, stream_games_csv
from scripts.scrape_playmetrics_league import REQUIRED_COLUMNS
from src.models.playmetrics_matcher import PlayMetricsGameMatcher

NO_ROWS = APIError({"code": "PGRST116", "message": "JSON object requested, multiple (or no) rows returned"})


class _Db:
    """A supabase double that refuses what postgrest refuses and records only executed calls.

    ``.single().execute()`` on zero rows raises, as postgrest does; inserts and the
    state-scoped candidate query are recorded only at ``execute()``.
    """

    def __init__(self):
        self.executed_inserts = []
        self.state_filters = []
        self.mock = MagicMock()
        select = self.mock.table.return_value.select.return_value
        select.eq.return_value.eq.return_value.single.return_value.execute.side_effect = NO_ROWS
        select.eq.return_value.eq.return_value.execute.return_value.data = []
        select.eq.return_value.eq.return_value.eq.side_effect = self._scoped
        self.mock.table.return_value.insert.side_effect = self._insert

    def _scoped(self, column, value):
        builder = MagicMock()

        def execute():
            if column == "state_code":
                self.state_filters.append(value)
            return MagicMock(data=[])

        builder.execute.side_effect = execute
        return builder

    def _insert(self, payload):
        builder = MagicMock()
        builder.execute.side_effect = lambda: self.executed_inserts.append(payload)
        return builder


def _row(**overrides):
    row = {
        "provider": "playmetrics",
        "team_id": "57610",
        "team_name": "15 (U11) TFA Purple",
        "club_name": "TOR Futbol Academy",
        "opponent_id": "66258",
        "opponent_name": "15 (U11) SSL White",
        "opponent_club_name": "Seashore Soccer League",
        "age_group": "u11",
        "gender": "Male",
        "home_away": "H",
        "game_date": "2026-08-23",
        "goals_for": 2,
        "goals_against": 4,
        "state_code": "NC",
    }
    row.update(overrides)
    return row


def _teams(db):
    return [p for p in db.executed_inserts if "state_code" in p]


def _run(matcher, row):
    with (
        patch.object(matcher, "_match_by_provider_id", return_value=None),
        patch.object(matcher, "_match_by_alias", return_value=None),
    ):
        return matcher.match_game_history(row)


def test_a_row_with_a_state_scopes_the_match_and_the_new_team_to_it():
    db = _Db()
    matcher = PlayMetricsGameMatcher(db.mock, provider_id="playmetrics")

    _run(matcher, _row(state_code="NC"))

    assert db.state_filters == ["NC"]
    assert [p["state_code"] for p in _teams(db)] == ["NC", "NC"]


def test_each_team_takes_its_age_from_its_own_name_not_the_row():
    # The row's age group is the row team's; the opponent plays one year up.
    db = _Db()
    matcher = PlayMetricsGameMatcher(db.mock, provider_id="playmetrics")

    _run(
        matcher,
        _row(
            team_name="U16 Girls Academy",
            opponent_name="U15 Girls Academy",
            age_group="u16",
            gender="Female",
            state_code="CO",
        ),
    )

    assert {p["team_name"]: p["age_group"] for p in _teams(db)} == {
        "U16 Girls Academy": "u16",
        "U15 Girls Academy": "u15",
    }


def test_a_team_whose_name_states_no_age_keeps_the_rows_age():
    db = _Db()
    matcher = PlayMetricsGameMatcher(db.mock, provider_id="playmetrics")

    _run(matcher, _row(team_name="Chamoy", opponent_name="Gladiadores", age_group="u14", state_code="CO"))

    assert [p["age_group"] for p in _teams(db)] == ["u14", "u14"]


def test_a_new_team_carries_no_full_name_state():
    # A filled `state` reads as provider-reported to assign_team_states; a
    # governing-body constant is per-league evidence, not per-team.
    db = _Db()
    matcher = PlayMetricsGameMatcher(db.mock, provider_id="playmetrics")

    _run(matcher, _row(state_code="NC"))

    assert _teams(db) and all("state" not in p for p in _teams(db))


def test_a_new_team_joins_the_candidate_bucket_of_its_own_state():
    db = _Db()
    matcher = PlayMetricsGameMatcher(db.mock, provider_id="playmetrics")

    _run(matcher, _row(state_code="NC"))

    cached = matcher._candidate_cache[("NC", "u11", "Male")]
    assert [c["team_name"] for c in cached] == ["15 (U11) TFA Purple", "15 (U11) SSL White"]


def test_a_later_row_reuses_the_team_the_first_row_created():
    db = _Db()
    matcher = PlayMetricsGameMatcher(db.mock, provider_id="playmetrics")
    _run(matcher, _row(state_code="NC"))
    first_id = _teams(db)[0]["team_id_master"]

    result = _run(matcher, _row(state_code="NC", team_id="90001", opponent_id="90002"))

    assert result["home_team_master_id"] == first_id
    assert len(_teams(db)) == 2


def test_a_row_with_no_state_falls_back_to_the_constructor_default():
    db = _Db()
    matcher = PlayMetricsGameMatcher(db.mock, provider_id="playmetrics", default_state_code="WI")

    _run(matcher, _row(state_code=""))

    assert db.state_filters == ["WI"]
    assert [p["state_code"] for p in _teams(db)] == ["WI", "WI"]


def test_the_row_state_does_not_leak_into_the_next_row():
    db = _Db()
    matcher = PlayMetricsGameMatcher(db.mock, provider_id="playmetrics", default_state_code="WI")

    _run(matcher, _row(state_code="NC"))
    _run(
        matcher,
        _row(
            state_code="",
            team_id="1",
            team_name="15 (U11) Bavarian Red",
            club_name="Bavarian United",
            opponent_id="2",
            opponent_name="15 (U11) Elmbrook Blue",
            opponent_club_name="Elmbrook United",
        ),
    )

    assert [p["state_code"] for p in _teams(db)] == ["NC", "NC", "WI", "WI"]


def test_a_tournament_matcher_stays_unscoped_and_asks_the_club():
    db = _Db()
    matcher = PlayMetricsGameMatcher(db.mock, provider_id="playmetrics_tournament", default_state_code=None)

    with patch.object(matcher, "_resolve_state_from_club", return_value=("OR", "Oregon")) as resolve:
        _run(matcher, _row(state_code=""))

    assert db.state_filters == []
    assert resolve.call_count == 2
    assert [p["state_code"] for p in _teams(db)] == ["OR", "OR"]


def test_a_lowercase_state_is_read_as_its_uppercase_code():
    db = _Db()
    matcher = PlayMetricsGameMatcher(db.mock, provider_id="playmetrics")

    _run(matcher, _row(state_code="nc"))

    assert db.state_filters == ["NC"]
    assert [p["state_code"] for p in _teams(db)] == ["NC", "NC"]


def test_an_unrecognized_state_is_matched_unscoped_not_defaulted(caplog):
    db = _Db()
    matcher = PlayMetricsGameMatcher(db.mock, provider_id="playmetrics", default_state_code="WI")

    with patch.object(matcher, "_resolve_state_from_club", return_value=(None, None)):
        with caplog.at_level("WARNING", logger="src.models.playmetrics_matcher"):
            _run(matcher, _row(state_code="ZZ"))

    assert db.state_filters == []
    assert [p["state_code"] for p in _teams(db)] == [None, None]
    assert "Unrecognized state_code 'ZZ'" in caplog.text


def test_an_explicit_state_argument_wins_over_the_default():
    db = _Db()
    matcher = PlayMetricsGameMatcher(db.mock, provider_id="playmetrics", default_state_code="WI")

    with (
        patch.object(matcher, "_match_by_provider_id", return_value=None),
        patch.object(matcher, "_match_by_alias", return_value=None),
    ):
        matcher._match_team(
            "playmetrics", "77", "15 (U11) TFA Purple", "u11", "Male", "TOR Futbol Academy", state_code="NC"
        )

    assert db.state_filters == ["NC"]
    assert [p["state_code"] for p in _teams(db)] == ["NC"]


def _write_scraper_csv(path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=REQUIRED_COLUMNS)
        writer.writeheader()
        blank = {c: "" for c in REQUIRED_COLUMNS}
        row = {**blank, "provider": "playmetrics", "state": "North Carolina", "state_code": "NC"}
        writer.writerow({**row, "game_date": "2026-08-23"})


def test_the_streaming_csv_loader_keeps_the_row_state(tmp_path: Path):
    # The importer builds each game dict from a column whitelist; the matcher can only
    # scope by state if that whitelist carries `state_code` through.
    path = tmp_path / "playmetrics.csv"
    _write_scraper_csv(path)

    games = [g for batch in stream_games_csv(path) for g in batch]

    assert games[0]["state_code"] == "NC"


def test_the_whole_file_csv_loader_keeps_the_row_state(tmp_path: Path):
    path = tmp_path / "playmetrics.csv"
    _write_scraper_csv(path)

    games = load_games_csv(path)

    assert games[0]["state_code"] == "NC"


def test_a_direct_match_after_a_row_uses_the_default_not_the_last_row():
    # Discovery-style callers reach _match_team without a row; the previous
    # row's state must not bleed into them.
    db = _Db()
    matcher = PlayMetricsGameMatcher(db.mock, provider_id="playmetrics", default_state_code="WI")
    _run(matcher, _row(state_code="NC"))

    with (
        patch.object(matcher, "_match_by_provider_id", return_value=None),
        patch.object(matcher, "_match_by_alias", return_value=None),
    ):
        matcher._match_team("playmetrics", "77", "15 (U11) Rush Red", "u11", "Male", "Rush Wisconsin")

    assert db.state_filters == ["NC", "WI"]
    assert [p["state_code"] for p in _teams(db)][-1] == "WI"
