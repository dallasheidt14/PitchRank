"""The report must find a game stored twice through the same queries production would answer."""

from datetime import date
from types import SimpleNamespace

from scripts import report_double_stored_games as report

GOTSPORT = "prov-gotsport"
AFC = "5b6b37ce-031b-4e77-83eb-9a5b4e667c2f"
GREMIO = "b54514dc-0454-4c7f-932b-7aa644a69efc"
OTHER = "0a1b2c3d-0000-4000-8000-000000000000"
TODAY = date(2026, 10, 16)
DAY = "2026-10-15"
PROVIDER_ID_UID = f"gotsport:{DAY}:471854:483752"
MASTER_UID = f"gotsport:{DAY}:{AFC}:{GREMIO}"


def _game(uid, home, away, home_score, away_score, day=DAY, excluded=False, provider=GOTSPORT):
    return {
        "id": f"id-{uid}",
        "game_uid": uid,
        "game_date": day,
        "home_team_master_id": home,
        "away_team_master_id": away,
        "home_score": home_score,
        "away_score": away_score,
        "provider_id": provider,
        "is_excluded": excluded,
    }


class _Query:
    """Select double: applies eq, orders by id, honours range, projects the selected columns."""

    def __init__(self, db, table):
        self._db, self._table = db, table
        self._columns, self._predicates, self._range, self._single = None, [], None, False

    def select(self, columns):
        self._columns = [c.strip() for c in columns.split(",")]
        return self

    def eq(self, field, value):
        self._predicates.append(lambda r: r.get(field) == value)
        return self

    def order(self, field):
        assert field == "id", field
        return self

    def range(self, start, end):
        self._range = (start, end)
        return self

    def single(self):
        self._single = True
        return self

    def __getattr__(self, name):
        raise AssertionError(f"the report must only read; unmodeled builder method {name!r}")

    def execute(self):
        self._db.executed.append(self._table)
        source = self._db.games if self._table == "games" else [{"id": GOTSPORT, "code": "gotsport"}]
        rows = sorted((r for r in source if all(p(r) for p in self._predicates)), key=lambda r: r["id"])
        if self._range:
            rows = rows[self._range[0] : self._range[1] + 1]
        data = [{c: r[c] for c in self._columns} for r in rows]
        return SimpleNamespace(data=data[0] if self._single else data)


class _DB:
    def __init__(self, games):
        self.games = games
        self.executed = []

    def table(self, name):
        assert name in ("games", "providers"), name
        return _Query(self, name)


def _scan(games, days=2):
    return report.scan(_DB(games), "gotsport", days, today=TODAY)


def test_a_provider_id_row_and_its_master_id_twin_are_found():
    pairs = _scan([_game(PROVIDER_ID_UID, GREMIO, AFC, 13, 0), _game(MASTER_UID, GREMIO, AFC, 8, 0)])

    [pair] = pairs
    assert (pair["date"], pair["kind"], pair["provider_id_uid"]) == (DAY, "different", True)


def test_the_same_result_read_from_the_other_side_is_identical():
    [pair] = _scan([_game(PROVIDER_ID_UID, GREMIO, AFC, 8, 0), _game(MASTER_UID, AFC, GREMIO, 0, 8)])

    assert pair["kind"] == "identical"


def test_scores_flipped_between_home_and_away_are_reversed():
    [pair] = _scan([_game(PROVIDER_ID_UID, GREMIO, AFC, 1, 7), _game(MASTER_UID, GREMIO, AFC, 7, 1)])

    assert pair["kind"] == "reversed"


def test_excluded_unscored_other_provider_and_other_pair_rows_are_not_paired():
    games = [
        _game(PROVIDER_ID_UID, GREMIO, AFC, 13, 0),
        _game(f"{MASTER_UID}:a", GREMIO, AFC, 8, 0, excluded=True),
        _game(f"{MASTER_UID}:b", GREMIO, AFC, None, None),
        _game(f"{MASTER_UID}:c", GREMIO, AFC, 8, 0, provider="prov-other"),
        _game(f"{MASTER_UID}:d", GREMIO, OTHER, 8, 0),
        _game(f"{MASTER_UID}:e", GREMIO, AFC, 8, 0, day="2026-10-13"),
    ]

    assert _scan(games, days=4) == []


def test_pagination_reads_every_row_of_a_busy_day(monkeypatch):
    monkeypatch.setattr(report, "PAGE_SIZE", 2)
    games = [_game(f"gotsport:{DAY}:{n}", f"{n:08d}-0000-4000-8000-000000000000", OTHER, 1, 0) for n in range(5)]
    games += [_game(PROVIDER_ID_UID, GREMIO, AFC, 13, 0), _game(MASTER_UID, GREMIO, AFC, 8, 0)]

    pairs = _scan(games)

    assert [p["kind"] for p in pairs] == ["different"]


def test_the_report_counts_each_kind_and_lists_provider_id_rows():
    pairs = _scan([_game(PROVIDER_ID_UID, GREMIO, AFC, 13, 0), _game(MASTER_UID, GREMIO, AFC, 8, 0)])

    summary = report.summarize(pairs, 45)

    assert "| Two different scores | 1 |" in summary
    assert "| **Total** | **1** |" in summary
    assert PROVIDER_ID_UID in summary
