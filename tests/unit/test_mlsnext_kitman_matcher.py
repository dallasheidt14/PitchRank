"""The Kitman matcher resolves teams only through mlsnext_kitman aliases."""

import inspect
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from scripts import build_mlsnext_kitman_games_csv as build
from scripts import import_games_enhanced as importer
from src.etl import enhanced_pipeline
from src.models import mlsnext_kitman_keys as keys
from src.models.mlsnext_kitman_matcher import PROVIDER_CODE, MlsNextKitmanGameMatcher
from tests.unit.test_enhanced_pipeline_fixture_score_fill import _DB, _import_pipeline

PROVIDER = "prov-kitman"


def _matcher(cache=None):
    matcher = MlsNextKitmanGameMatcher(MagicMock(), provider_id=PROVIDER, alias_cache=cache or {}, dry_run=True)
    matcher._validate_team_age_group = lambda *a, **k: True
    return matcher


def test_cached_alias_resolves():
    matcher = _matcher({"5747:2026": {"team_id_master": "T1", "match_method": "direct_id", "review_status": "approved"}})
    result = matcher._match_team(PROVIDER, "5747:2026", "Club U13 HD", "u13", "Male")
    assert (result["matched"], result["team_id"], result["method"]) == (True, "T1", "direct_id")


def test_unlinked_team_never_fuzzy_matches_or_creates():
    matcher = _matcher()
    matcher._match_by_provider_id = lambda *a, **k: None
    matcher._match_by_alias = MagicMock(side_effect=AssertionError("name alias must not run"))
    matcher._fuzzy_match_team = MagicMock(side_effect=AssertionError("fuzzy must not run"))
    matcher._create_alias = MagicMock(side_effect=AssertionError("must not write"))
    result = matcher._match_team(PROVIDER, "999:2026", "Club U13 HD", "u13", "Male")
    assert result == {"matched": False, "team_id": None, "method": None, "confidence": 0.0}


def test_a_blank_id_is_unmatched():
    assert _matcher()._match_team(PROVIDER, "", "Club U13 HD", "u13", "Male")["matched"] is False


def test_provider_code_is_the_seeded_one():
    assert PROVIDER_CODE == "mlsnext_kitman"


def test_pipeline_selects_the_kitman_matcher_with_dry_run():
    source = inspect.getsource(enhanced_pipeline)
    branch = source.split('elif self.provider_code.lower() == "mlsnext_kitman":', 1)[1].split("elif ", 1)[0]
    assert "MlsNextKitmanGameMatcher(" in branch
    assert "dry_run=self.dry_run" in branch


class _TeamsTable:
    """``teams`` as PostgREST serves ``_validate_team_age_group``'s read: an unknown column is refused, filters and
    the selected columns apply at execute(), and only ``.single()`` answers with one row, raising unless exactly
    one matches."""

    COLUMNS = {"id", "team_id_master", "age_group", "gender"}

    def __init__(self, rows):
        self.rows, self.read = rows, []

    def table(self, name):
        self.name, self.filters, self.columns, self.one = name, [], [], False
        return self

    def select(self, columns):
        self.columns = [c.strip() for c in columns.split(",")]
        return self

    def eq(self, field, value):
        self.filters.append((field, value))
        return self

    def single(self):
        self.one = True
        return self

    def execute(self):
        self.read.append((self.name, tuple(self.filters)))
        if self.name != "teams" or not {*self.columns, *(f for f, _ in self.filters)} <= self.COLUMNS:
            raise RuntimeError("column does not exist")
        found = [{c: r[c] for c in self.columns} for r in self.rows if all(r[f] == v for f, v in self.filters)]
        if not self.one:
            return SimpleNamespace(data=found)
        if len(found) != 1:
            raise RuntimeError("JSON object requested, multiple (or no) rows returned")
        return SimpleNamespace(data=found[0])


@pytest.mark.parametrize(
    ("club", "team_age", "matched"),
    [
        ("Play Up FC", "u14", True),
        ("Play Up FC", "u13", True),
        ("Play Up FC", "u12", False),
        ("Other FC", "u13", False),
        ("Other FC", "u14", True),
    ],
    ids=["listed own age", "listed one younger", "listed two younger", "unlisted one younger", "unlisted own age"],
)
def test_the_importers_own_age_check_lets_only_a_play_up_club_through_one_board_younger(
    monkeypatch, club, team_age, matched
):
    monkeypatch.setitem(keys.PLAY_UP_CLUBS, "Play Up FC", "test")
    monkeypatch.delitem(keys.PLAY_UP_CLUBS, "Other FC", raising=False)
    db = _TeamsTable([{"id": 1, "team_id_master": "T1", "age_group": team_age, "gender": "Male"}])
    cache = {"6015:2026": {"team_id_master": "T1", "match_method": "direct_id", "review_status": "approved"}}
    matcher = MlsNextKitmanGameMatcher(db, provider_id=PROVIDER, alias_cache=cache, dry_run=True)
    result = matcher._match_team(PROVIDER, "6015:2026", f"{club} U14 HD", "u14", "Male", club_name=club)
    assert (result["matched"], result["team_id"]) == ((True, "T1") if matched else (False, None))
    assert db.read and all(read == ("teams", (("team_id_master", "T1"),)) for read in db.read)


def _squad(sid, club):
    return {
        "provider_team_id": sid,
        "key": f"{sid}:2026",
        "club_name": club,
        "display_name": f"{club} U16 HD",
        "age_group": "u16",
        "division": "HD",
    }


def _played(event_id, home, away, game_date):
    return {
        "event_id": event_id,
        "game_date": game_date,
        "status": "played",
        "division": "HD",
        "competition": "League",
        "age_group": "u16",
        "home_squad_id": home,
        "away_squad_id": away,
        "home_key": f"{home}:2026",
        "away_key": f"{away}:2026",
        "home_score": "2",
        "away_score": "1",
    }


@pytest.mark.parametrize("loader", ["load_games_csv", "stream_games_csv"])
@pytest.mark.parametrize("listed", [True, False], ids=["listed", "unlisted"])
def test_a_built_import_file_reaches_a_play_up_clubs_younger_team_from_either_side(
    tmp_path, monkeypatch, loader, listed
):
    if listed:
        monkeypatch.setitem(keys.PLAY_UP_CLUBS, "Play Up FC", "test")
    else:
        monkeypatch.delitem(keys.PLAY_UP_CLUBS, "Play Up FC", raising=False)
    squads = {"10": _squad("10", "Play Up FC"), "11": _squad("11", "Other FC")}
    links = {"10:2026": "T10", "11:2026": "T11"}
    games = [_played("1", "10", "11", "2026-09-12"), _played("2", "11", "10", "2026-09-19")]
    rows, held = build.build_rows(games, squads, links, "2026-08-01", "2026-10-14", set())
    assert held == []
    build._write_csv(tmp_path / "import.csv", build.IMPORT_COLUMNS, rows)
    if loader == "load_games_csv":
        loaded = importer.load_games_csv(tmp_path / "import.csv")
    else:
        loaded = [game for batch in importer.stream_games_csv(tmp_path / "import.csv") for game in batch]
    teams = _TeamsTable(
        [
            {"id": 1, "team_id_master": "T10", "age_group": "u15", "gender": "Male"},
            {"id": 2, "team_id_master": "T11", "age_group": "u16", "gender": "Male"},
        ]
    )
    approved = {"match_method": "direct_id", "review_status": "approved"}
    cache = {key: {"team_id_master": tid, **approved} for key, tid in links.items()}
    matcher = MlsNextKitmanGameMatcher(teams, provider_id=PROVIDER, alias_cache=cache, dry_run=False)

    inserted, _ = _import_pipeline(
        monkeypatch,
        _DB([]),
        loaded,
        provider=PROVIDER_CODE,
        provider_id=PROVIDER,
        real_validation=True,
        matcher=matcher,
    )

    games = sorted(
        (g["game_date"], g["home_team_master_id"], g["away_team_master_id"], g["home_score"], g["away_score"])
        for g in inserted
    )
    play_up_team = "T10" if listed else None
    assert games == [
        ("2026-09-12", play_up_team, "T11", 2, 1),
        ("2026-09-19", "T11", play_up_team, 2, 1),
    ]
