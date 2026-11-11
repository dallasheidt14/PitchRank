from copy import deepcopy
from datetime import date
from types import SimpleNamespace

import pytest

from src.predictions.prospective_fixtures import prepare_database_fixtures, database_result, strict_resolver
from scripts.settle_prospective_match_predictions import _fetch_rows, settle_rows


class Client:
    """Deferred queries with real filtering, ordering, row caps and conflict handling."""
    def __init__(self, rows):
        self.rows = deepcopy(rows)
        self.writes = []
        self.reads = []

    def table(self, name):
        return Query(self, name)


class Query:
    def __init__(self, client, table):
        self.client, self.name = client, table
        self.filters, self.orders = [], []
        self.start, self.end, self.single = 0, 999, False
        self.mutation = None

    def select(self, _):
        return self

    def eq(self, key, value):
        self.filters.append(lambda row: row.get(key) == value)
        return self

    def neq(self, key, value):
        self.filters.append(lambda row: row.get(key) is not None and row.get(key) != value)
        return self

    def gte(self, key, value):
        self.filters.append(lambda row: row.get(key) is not None and row[key] >= value)
        return self

    def lte(self, key, value):
        self.filters.append(lambda row: row.get(key) is not None and row[key] <= value)
        return self

    def in_(self, key, values):
        self.filters.append(lambda row: row.get(key) in values)
        return self

    def order(self, key, desc=False):
        self.orders.append((key, desc))
        return self

    def range(self, start, end):
        self.start, self.end = start, min(end, start + 999)
        return self

    def maybe_single(self):
        self.single = True
        return self

    def upsert(self, rows, *, on_conflict, ignore_duplicates):
        assert ignore_duplicates is True
        self.mutation = ("insert", rows, on_conflict)
        return self

    def update(self, payload):
        self.mutation = ("update", payload)
        return self

    def execute(self):
        rows = self.client.rows.setdefault(self.name, [])
        found = [row for row in rows if all(test(row) for test in self.filters)]
        for key, desc in reversed(self.orders):
            found.sort(key=lambda row: str(row.get(key)), reverse=desc)
        found = found[self.start:self.end + 1]
        if self.mutation:
            self.client.writes.append((self.name, deepcopy(self.mutation), deepcopy(found)))
            if self.mutation[0] == "insert":
                _, values, key = self.mutation
                held = {row[key] for row in rows}
                found = [deepcopy(row) for row in values if row[key] not in held]
                rows.extend(found)
            else:
                for row in found:
                    row.update(self.mutation[1])
        else:
            self.client.reads.append((self.name, self.start, self.end))
        if self.single:
            assert len(found) <= 1
            return SimpleNamespace(data=deepcopy(found[0])) if found else None
        return SimpleNamespace(data=deepcopy(found))


def game(**updates):
    return {"id": "g1", "game_date": "2026-11-12", "home_team_master_id": "old-a",
            "away_team_master_id": "b", "provider_id": "p", "home_score": None,
            "away_score": None, "is_excluded": False, "competition": "League", "source_url": None, **updates}


def client(*games):
    return Client({"games": list(games or [game()]),
                   "providers": [{"id": "p", "code": "gotsport"}],
                   "team_merge_map": [{"deprecated_team_id": "old-a", "canonical_team_id": "a"}],
                   "teams": [{"team_id_master": team, "team_name": team, "age_group": "u13", "gender": "Male"}
                             for team in ("a", "b")],
                   "rankings_full": [{"team_id": team, "power_score_final": .5, "status": "Active"}
                                     for team in ("a", "b")],
                   "team_ranking_exclusions": [], "prospective_match_predictions": []})


def prepare(db, **kwargs):
    return prepare_database_fixtures(db, today=date(2026, 11, 11), **kwargs)


def test_database_intake_dry_run_resolves_aliases_and_writes_nothing():
    db = client()
    assert prepare(db)["selected"] == 1
    assert db.writes == []
    result = prepare(db, dry_run=False)
    assert result["inserted"] == 1
    stored = db.rows["prospective_match_predictions"][0]
    assert stored["home_team_master_id"] == "a"
    assert stored["fixture_payload"]["source_snapshot"]["home_team_master_id"] == "old-a"
    assert stored["source_event_id"] is None
    assert stored["evaluation_group_kind"] == "inferred_competition_week"
    assert stored["home_provider_team_id"] is None
    stored["heuristic_prediction_status"] = "completed"
    stored["heuristic_prediction"] = {"untouched": True}
    assert prepare(db, dry_run=False)["selected"] == 0
    assert stored["heuristic_prediction"] == {"untouched": True}


@pytest.mark.parametrize("changes", [
    {"home_score": 0}, {"away_score": 0}, {"game_date": "2026-11-11"},
    {"game_date": "2026-11-19"}, {"is_excluded": True}, {"home_team_master_id": None},
    {"away_team_master_id": None}, {"away_team_master_id": "a"},
])
def test_intake_rejects_each_eligibility_violation(changes):
    assert prepare(client(game(**changes)))["selected"] == 0


def test_intake_holds_ambiguous_twins_but_keeps_verified_rematches():
    first, second = game(), game(id="g2")
    assert prepare(client(first, second))["selected"] == 0
    first["source_url"] = "https://example.com/games/123"
    second["source_url"] = "https://example.com/games/456"
    assert prepare(client(first, second))["selected"] == 2
    second["provider_id"] = "other-provider"
    assert prepare(client(first, second))["selected"] == 0


def test_intake_pages_beyond_local_row_cap_and_does_not_use_scored_twin():
    games = [game(id=str(i), source_url=f"https://example.com/games/{i}") for i in range(1005)]
    db = client(*games)
    assert prepare(db, limit=500)["eligible"] == 1005
    assert ("games", 1000, 1999) in db.reads
    db = client(game(), game(id="scored", home_score=2, away_score=1))
    assert prepare(db)["selected"] == 0


def fixture(db):
    prepare(db, dry_run=False)
    row = db.rows["prospective_match_predictions"][0]
    row.update(id="forecast", evaluation_status="pending_result")
    return row


def test_settlement_uses_source_id_and_reorients_scores_after_merge():
    db = client()
    row = fixture(db)
    db.rows["games"][0].update(home_team_master_id="b", away_team_master_id="a", home_score=1, away_score=3)
    result, reversed_orientation, source = database_result(db, row, strict_resolver(db))
    assert result["id"] == "g1"
    assert reversed_orientation is True
    assert source == "source_game_id"
    db.writes.clear()
    assert settle_rows(supabase=db, status="unsettled", limit=5000, as_of="2026-11-13")["settled"] == 1
    assert db.writes == []
    settle_rows(supabase=db, status="unsettled", limit=5000, dry_run=False, as_of="2026-11-13")
    stored = db.rows["prospective_match_predictions"][0]
    assert stored["actual_home_score"] == 3
    assert stored["actual_away_score"] == 1


@pytest.mark.parametrize(("changes", "reason"), [
    ({"game_date": "2026-11-13"}, "fixture_changed"),
    ({"home_team_master_id": "c"}, "fixture_changed"),
    ({"provider_id": "different"}, "fixture_changed"),
    ({"source_url": "https://example.com/games/456"}, "fixture_changed"),
    ({"is_excluded": True}, "excluded_result"),
    ({"home_score": None}, "result_not_found"),
])
def test_settlement_holds_changed_or_unfinished_fixture(changes, reason):
    db = client()
    row = fixture(db)
    db.rows["games"][0].update({"home_score": 2, "away_score": 1, **changes})
    assert database_result(db, row, strict_resolver(db))[2] == reason


def test_missing_source_response_is_held_instead_of_aborting_settlement():
    db = client()
    row = fixture(db)
    db.rows["games"] = []
    assert database_result(db, row, strict_resolver(db))[2] == "source_missing"
    assert settle_rows(supabase=db, status="unsettled", limit=20, as_of="2026-11-13")["held"] == 1


def test_retries_rotate_by_last_update_instead_of_starving_older_results():
    db = client()
    db.rows["prospective_match_predictions"] = [
        {"id": "new-missing", "game_date": "2026-11-13", "evaluation_status": "result_not_found",
         "updated_at": "2026-11-14T10:00:00Z"},
        {"id": "old-ready", "game_date": "2026-11-12", "evaluation_status": "pending_result",
         "updated_at": "2026-11-13T10:00:00Z"},
    ]
    assert _fetch_rows(db, "unsettled", 1, "2026-11-14")[0]["id"] == "old-ready"
    db.rows["prospective_match_predictions"][1]["updated_at"] = "2026-11-15T10:00:00Z"
    assert _fetch_rows(db, "unsettled", 1, "2026-11-15")[0]["id"] == "new-missing"


def test_intake_cli_does_not_turn_zero_into_the_default(monkeypatch):
    from scripts import prepare_prospective_match_predictions as cli
    monkeypatch.setattr(cli, "_supabase_client", lambda: client())
    monkeypatch.setattr("sys.argv", ["prepare", "--database", "--limit", "0", "--execute"])
    with pytest.raises(ValueError, match="between 1 and 500"):
        cli.main()


def test_settlement_builds_reverse_aliases_once_for_the_batch(monkeypatch):
    from src.predictions import prospective_fixtures as source
    db = client(game(source_url="https://example.com/games/1"), game(id="g2", source_url="https://example.com/games/2"))
    prepare(db, dry_run=False)
    for index, row in enumerate(db.rows["prospective_match_predictions"]):
        row.update(id=str(index), evaluation_status="pending_result")
    for row in db.rows["games"]:
        row.update(home_score=2, away_score=1)
    resolver = strict_resolver(db)
    original = resolver.get_deprecated_teams
    calls = []
    def counted():
        calls.append(True)
        return original()
    monkeypatch.setattr(resolver, "get_deprecated_teams", counted)
    monkeypatch.setattr(source, "strict_resolver", lambda _: resolver)
    assert settle_rows(supabase=db, status="unsettled", limit=20, as_of="2026-11-13")["settled"] == 2
    assert len(calls) == 1


def test_new_alias_exclusion_and_duplicate_are_respected_at_settlement():
    db = client()
    row = fixture(db)
    db.rows["games"][0].update(home_score=2, away_score=1)
    db.rows["team_ranking_exclusions"] = [{"team_id_master": "old-a"}]
    assert database_result(db, row, strict_resolver(db))[2] == "excluded_result"
    db.rows["team_ranking_exclusions"] = []
    db.rows["games"].append(game(id="twin", home_score=2, away_score=1))
    assert database_result(db, row, strict_resolver(db))[2] == "ambiguous_result"
