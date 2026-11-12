"""Drive the real inventory/selection path, with capped and projected deferred queries."""

from copy import deepcopy
from datetime import date

from src.predictions.collection_coverage import collection_coverage
from src.predictions.prospective_fixtures import prepare_database_fixtures
from tests.unit.test_prospective_fixtures import Client, Query, client, game


class ProjectedQuery(Query):
    def select(self, fields):
        self.fields = [field.strip() for field in fields.split(",")]
        return self

    def range(self, start, end):
        assert self.orders
        self.start, self.end = start, min(end, start + 2)
        return self

    def execute(self):
        response = super().execute()
        if not self.mutation:
            response.data = [{key: row.get(key) for key in self.fields} for row in response.data]
        return response


class CoverageClient(Client):
    def table(self, name):
        return ProjectedQuery(self, name)


def mixed_pool(monkeypatch):
    # Force inventory queries through several pages and project only selected columns.
    monkeypatch.setattr("src.predictions.prospective_fixtures.PAGE_SIZE", 3)
    rows = deepcopy(client().rows)
    rows["providers"].extend([{"id": "d", "code": "demosphere"}, {"id": "h", "code": "affinity_hi"},
                              {"id": "empty", "code": "empty_provider"}])
    rows["teams"] = []
    rows["rankings_full"] = []
    rows["games"] = []
    for number in range(24):
        provider = "p" if number < 20 else "d" if number < 22 else "h"
        # All minority fixtures occur later, reproducing the actual chronological-cap omission.
        day = "2026-11-13" if number < 20 else "2026-11-14"
        home, away = f"home-{number}", f"away-{number}"
        rows["games"].append(game(id=f"game-{number:03d}", game_date=day, provider_id=provider,
                                  home_team_master_id=home, away_team_master_id=away))
        for team in (home, away):
            rows["teams"].append({"team_id_master": team, "team_name": team,
                                  "age_group": "u13" if number % 2 else "u12",
                                  "gender": "Female" if number % 3 else "Male"})
            rows["rankings_full"].append({"team_id": team, "power_score_final": .5, "status": "Active",
                                         "games_played": 3 if number % 2 else 20})
    return CoverageClient(rows)


def test_balanced_selection_covers_small_providers_without_increasing_cap(monkeypatch):
    db = mixed_pool(monkeypatch)
    before = deepcopy(db.rows)
    report = collection_coverage(db, limit=10, today=date(2026, 11, 12))
    providers = {row["provider"]: row for row in report["providers"]}
    assert providers["gotsport"]["chronological_selected"] == 10
    assert providers["demosphere"]["balanced_selected"] == 2
    assert providers["affinity_hi"]["balanced_selected"] == 2
    assert providers["gotsport"]["balanced_selected"] == 6
    assert len(report["pool_strata"]) > 3
    assert {row["rating_history_band"] for row in report["pool_strata"]} == {"1-3", "8+"}
    assert {row["gender"] for row in report["pool_strata"]} == {"Female", "Male"}
    assert {row["age_group"] for row in report["pool_strata"]} == {"u12", "u13"}
    assert report["outcome_metrics_read"] is False
    assert {row["provider"] for row in report["gaps"]} == {"empty_provider", "demosphere", "affinity_hi"}
    assert db.writes == [] and db.rows == before
    first = prepare_database_fixtures(db, limit=10, today=date(2026, 11, 12), dry_run=False)
    captured = deepcopy(db.rows["prospective_match_predictions"])
    assert first["inserted"] == 10
    assert {row["provider_code"] for row in captured} == {"gotsport", "demosphere", "affinity_hi"}
    assert len({row["fixture_key"] for row in captured}) == 10
    assert {row["fixture_payload"]["collection_policy"] for row in captured} == {"balanced_v1"}
    assert all(name == "prospective_match_predictions" for name, *_ in db.writes)


def test_selection_is_deterministic_and_never_changes_existing_forecasts(monkeypatch):
    db = mixed_pool(monkeypatch)
    prepare_database_fixtures(db, limit=10, today=date(2026, 11, 12), dry_run=False)
    saved = deepcopy(db.rows["prospective_match_predictions"])
    for row in db.rows["prospective_match_predictions"]:
        row["heuristic_prediction_status"] = "completed"
        row["heuristic_prediction"] = {"modelSignature": "different-signature", "shadowContext": {}}
    saved = deepcopy(db.rows["prospective_match_predictions"])
    prepare_database_fixtures(db, limit=10, today=date(2026, 11, 12), dry_run=False)
    assert db.rows["prospective_match_predictions"][:10] == saved
    assert len({row["source_game_id"] for row in db.rows["prospective_match_predictions"]}) == 20


def test_each_exclusion_is_reported_without_relaxing_eligibility(monkeypatch):
    db = mixed_pool(monkeypatch)
    db.rows["games"][0]["home_team_master_id"] = None
    db.rows["rankings_full"][2]["power_score_final"] = None
    db.rows["team_ranking_exclusions"] = [{"team_id_master": "home-2"}]
    report = collection_coverage(db, limit=10, today=date(2026, 11, 12))
    assert report["exclusions"]["unresolved_identity"] == 1
    assert report["exclusions"]["missing_current_rating_or_team"] == 1
    assert report["exclusions"]["excluded_team"] == 1
    assert report["new_eligible"] == 21
    assert db.writes == []
