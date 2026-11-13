"""The PlayMetrics matcher, driven a game at a time.

The row's ``state_code`` scopes the fuzzy-candidate query and is written onto any
team autocreated for the row. A club spelling listed in ``STORED_CLUB_NAMES`` is
matched and filed under PitchRank's name, and on the tournament flow a team with a
likely match waits for review instead of being created. The rules are in
``src/models/playmetrics_matcher.py``.
"""

import csv
import json
from pathlib import Path
from unittest.mock import DEFAULT, MagicMock, patch

import pytest
from postgrest.exceptions import APIError

from scripts.full_club_analysis import CLUB_CANONICAL_OVERRIDES, _matches_override
from scripts.import_games_enhanced import load_games_csv, stream_games_csv
from scripts.scrape_playmetrics_league import REQUIRED_COLUMNS
from src.etl.enhanced_pipeline import EnhancedETLPipeline
from src.models.playmetrics_matcher import STORED_CLUB_NAMES, PlayMetricsGameMatcher

NO_ROWS = APIError({"code": "PGRST116", "message": "JSON object requested, multiple (or no) rows returned"})


class _Db:
    """A supabase double that refuses what postgrest refuses and records only executed calls.

    ``.single().execute()`` on zero rows raises, as postgrest does; inserts and the
    state-scoped candidate query are recorded only at ``execute()``, and an insert
    postgrest could not serialize raises. A team read by ``team_id_master`` returns
    the ``stored`` row with that id, cut to the explicit column list selected, or
    none; a read by ``id`` returns the provider code ``playmetrics``.
    """

    def __init__(self, stored=()):
        self.executed_inserts = []
        self.state_filters = []
        self.stored = list(stored)
        self.selected = "*"
        self.mock = MagicMock()
        self.mock.table.return_value.select.side_effect = self._select
        select = self.mock.table.return_value.select.return_value
        select.eq.side_effect = self._first_filter
        select.eq.return_value.eq.return_value.single.return_value.execute.side_effect = NO_ROWS
        select.eq.return_value.eq.return_value.execute.return_value.data = []
        select.eq.return_value.eq.return_value.eq.side_effect = self._scoped
        self.mock.table.return_value.insert.side_effect = self._insert

    def _select(self, columns="*", **_kwargs):
        self.selected = columns
        return DEFAULT

    def _first_filter(self, column, value):
        builder = MagicMock()
        if column == "id":
            builder.single.return_value.execute.return_value.data = {"code": "playmetrics"}
        elif column == "team_id_master":
            columns = [c.strip() for c in self.selected.split(",")]
            builder.execute.return_value.data = [
                {c: t[c] for c in columns} for t in self.stored if t["team_id_master"] == value
            ]
        else:
            return DEFAULT
        return builder

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

        def execute():
            json.dumps(payload)
            self.executed_inserts.append(payload)

        builder.execute.side_effect = execute
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


def _stored(team_name, club_name, age_group, gender, state_code="WI"):
    return {
        "team_id_master": f"stored {team_name}",
        "team_name": team_name,
        "team_name_original": None,
        "club_name": club_name,
        "age_group": age_group,
        "gender": gender,
        "state_code": state_code,
    }


def _matcher_holding(db, scope, default_state_code=None):
    """A matcher whose fuzzy pool, in the bucket ``scope`` names, holds every stored team."""
    matcher = PlayMetricsGameMatcher(db.mock, provider_id="playmetrics", default_state_code=default_state_code)
    for team in db.stored:
        matcher._candidate_cache.setdefault((scope, team["age_group"], team["gender"]), []).append(dict(team))
    return matcher


def _run_tournament(matcher, **row):
    with patch.object(matcher, "_resolve_state_from_club", return_value=("WI", "Wisconsin")) as resolve:
        result = _run(matcher, _row(state_code="", **row))
    return result, resolve


def _suggestions(db):
    """Each team the review queue received, with the stored team it suggests (None for no suggestion)."""
    return {
        p["provider_team_name"]: p["suggested_master_team_id"] for p in db.executed_inserts if "provider_team_name" in p
    }


@pytest.mark.parametrize(
    ("team_name", "playmetrics_club", "stored_club", "age_group", "gender"),
    [
        ("AFC Union U11G Premier", "RASA - AFC Union", "AFC Union", "u11", "Female"),
        (
            "Forward Madison U12 Boys Junior Academy Select",
            "Forward Madison FC Youth",
            "Forward Madison FC",
            "u12",
            "Male",
        ),
        ("U12 Boys Select", "Rush Wisconsin Southeast", "RUSH WI Southeast", "u12", "Male"),
    ],
)
def test_a_club_playmetrics_spells_differently_links_to_its_stored_team(
    team_name, playmetrics_club, stored_club, age_group, gender
):
    stored = _stored(team_name, stored_club, age_group, gender)
    db = _Db(stored=[stored])
    matcher = _matcher_holding(db, scope=None)

    result, _ = _run_tournament(
        matcher, team_name=team_name, club_name=playmetrics_club, age_group=age_group, gender=gender
    )

    assert result["home_team_master_id"] == stored["team_id_master"]
    assert team_name not in [p["team_name"] for p in _teams(db)]


def test_a_league_team_whose_club_playmetrics_spells_differently_links_too():
    team_name = "Forward Madison U12 Boys Junior Academy Select"
    stored = _stored(team_name, "Forward Madison FC", "u12", "Male")
    db = _Db(stored=[stored])
    matcher = _matcher_holding(db, scope="WI", default_state_code="WI")

    result = _run(
        matcher,
        _row(
            team_name=team_name,
            club_name="Forward Madison FC Youth",
            age_group="u12",
            gender="Male",
            state_code="WI",
        ),
    )

    assert result["home_team_master_id"] == stored["team_id_master"]
    assert team_name not in [p["team_name"] for p in _teams(db)]


def test_a_stored_name_carrying_playmetrics_own_club_spelling_still_links():
    stored = _stored("RASA 2017 Lotus", "AFC Union", "u10", "Female")
    db = _Db(stored=[stored])
    matcher = _matcher_holding(db, scope=None)

    result, _ = _run_tournament(
        matcher, team_name="2017 Lotus", club_name="RASA - AFC Union", age_group="u10", gender="Female"
    )

    assert result["home_team_master_id"] == stored["team_id_master"]


@pytest.mark.parametrize("playmetrics_club", ["RASA - AFC Union", "RASA Arsenal F.C."])
def test_a_new_team_is_filed_under_the_club_name_pitchrank_stores(playmetrics_club):
    db = _Db()
    matcher = PlayMetricsGameMatcher(db.mock, provider_id="playmetrics", default_state_code=None)

    _, resolve = _run_tournament(matcher, team_name="AFC Union U13G Navy", club_name=playmetrics_club)

    created = {p["team_name"]: p["club_name"] for p in _teams(db)}
    assert created["AFC Union U13G Navy"] == "AFC Union"
    assert "AFC Union" in [c.args[0] for c in resolve.call_args_list]


# A squad named without its year scores 0.883 against the stored "RASA 2017 Lotus" under
# both scorers `_calculate_match_score` can use, so it sits in the review band in CI too.
LIKELY_MATCH = {"team_name": "Lotus", "club_name": "RASA - AFC Union", "age_group": "u10", "gender": "Female"}


def _likely_match_stored():
    return _stored("RASA 2017 Lotus", "AFC Union", "u10", "Female")


def test_a_tournament_team_with_a_likely_match_waits_for_review():
    stored = _likely_match_stored()
    db = _Db(stored=[stored])
    matcher = _matcher_holding(db, scope=None)

    result, _ = _run_tournament(matcher, **LIKELY_MATCH)

    assert result["home_team_master_id"] is None
    assert "Lotus" not in [p["team_name"] for p in _teams(db)]
    assert _suggestions(db)["Lotus"] == stored["team_id_master"]


def test_a_league_team_with_a_likely_match_is_still_created():
    stored = _likely_match_stored()
    db = _Db(stored=[stored])
    matcher = _matcher_holding(db, scope="WI", default_state_code="WI")

    _run(matcher, _row(state_code="WI", **LIKELY_MATCH))

    assert "Lotus" in [p["team_name"] for p in _teams(db)]
    assert _suggestions(db)["Lotus"] == stored["team_id_master"]


def test_a_league_row_matched_unscoped_still_creates_a_likely_match():
    # An unrecognized state matches the row unscoped, as the tournament flow does, but
    # holding a team is the tournament import's rule, not the unscoped match's.
    stored = _likely_match_stored()
    db = _Db(stored=[stored])
    matcher = _matcher_holding(db, scope=None, default_state_code="WI")

    with patch.object(matcher, "_resolve_state_from_club", return_value=(None, None)):
        _run(matcher, _row(state_code="ZZ", **LIKELY_MATCH))

    assert "Lotus" in [p["team_name"] for p in _teams(db)]


@pytest.mark.parametrize(("provider", "default_state_code"), [("playmetrics", "WI"), ("playmetrics_tournament", None)])
def test_the_pipeline_builds_the_tournament_matcher_unscoped(provider, default_state_code):
    supabase = MagicMock()
    lookup = supabase.table.return_value.select.return_value.eq.return_value.single.return_value
    lookup.execute.return_value.data = {"id": "provider-uuid"}
    pipeline = EnhancedETLPipeline(supabase, provider, dry_run=True)

    with patch("src.etl.enhanced_pipeline.call_rpc_with_fallback", return_value=[]):
        pipeline._ensure_initialized()

    assert type(pipeline.matcher) is PlayMetricsGameMatcher
    assert pipeline.matcher.default_state_code == default_state_code
    assert pipeline.matcher.dry_run is True


def test_the_weekly_club_cleanup_keeps_each_stored_club_name():
    # A cleanup rule renaming one of these clubs would leave new teams filed under
    # the retired name, which the club gate may no longer pair with the renamed rows.
    renamed = [
        (stored, canonical)
        for stored in STORED_CLUB_NAMES.values()
        for _state, kind, pattern, canonical in CLUB_CANONICAL_OVERRIDES
        if _matches_override(stored, kind, pattern) and canonical != stored
    ]

    assert renamed == []
