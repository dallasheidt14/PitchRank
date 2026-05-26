"""
Test that save_ranking_snapshot deduplicates team_ids before upserting.

Regression test for the bug where cross-cohort teams (same team_id, different
age_group) caused Postgres error 21000:
  "ON CONFLICT DO UPDATE command cannot affect row a second time"

Root cause: merge resolution maps deprecated teams to a canonical team_id whose
metadata wasn't in the batch fetch, so the age remap falls back to deprecated
ages, producing rows with the same team_id in different (age, gender) cohorts.
"""

import pandas as pd
import pytest

from src.rankings.ranking_history import save_ranking_snapshot


class FakeUpsertResponse:
    def __init__(self, data):
        self.data = data


class FakeUpsertBuilder:
    def __init__(self, batch_data):
        self.batch_data = batch_data

    def execute(self):
        # Check for duplicate team_ids in this batch (same check Postgres does)
        team_ids = [r["team_id"] for r in self.batch_data]
        if len(team_ids) != len(set(team_ids)):
            dupes = [t for t in set(team_ids) if team_ids.count(t) > 1]
            raise Exception(
                f"{{'message': 'ON CONFLICT DO UPDATE command cannot affect "
                f"row a second time', 'code': '21000', 'dupes': {dupes}}}"
            )
        return FakeUpsertResponse(self.batch_data)


class FakeTableBuilder:
    def __init__(self):
        self.upserted_batches = []

    def upsert(self, batch, on_conflict=None):
        self.upserted_batches.append(batch)
        return FakeUpsertBuilder(batch)


class FakeSupabase:
    def __init__(self):
        self._table_builder = FakeTableBuilder()

    def table(self, name):
        return self._table_builder


@pytest.mark.asyncio
async def test_snapshot_dedup_removes_duplicate_team_ids():
    """Duplicate team_ids in the DataFrame should be deduped before upsert."""
    # Simulate cross-cohort duplicate: same team_id, different age_group
    df = pd.DataFrame(
        {
            "team_id": ["aaa", "bbb", "aaa"],
            "age_group": ["u13", "u14", "u14"],
            "gender": ["Male", "Male", "Male"],
            "rank_in_cohort": [5, 10, 12],
            "rank_in_cohort_ml": [4, 9, 11],
            "rank_in_cohort_final": [4, 9, 11],
            "power_score_final": [0.8, 0.6, 0.5],
            "powerscore_ml": [0.82, 0.62, 0.52],
            "state_code": ["AZ", "AZ", "AZ"],
            "status": ["Active", "Active", "Active"],
        }
    )

    client = FakeSupabase()
    count = await save_ranking_snapshot(client, df)

    # Should save 2 records (aaa deduped), not 3
    assert count == 2

    # Verify no duplicate team_ids were sent to upsert
    all_records = []
    for batch in client._table_builder.upserted_batches:
        all_records.extend(batch)
    team_ids = [r["team_id"] for r in all_records]
    assert len(team_ids) == len(set(team_ids)), f"Duplicate team_ids in upsert: {team_ids}"


@pytest.mark.asyncio
async def test_snapshot_no_dedup_when_unique():
    """No records should be dropped when team_ids are already unique."""
    df = pd.DataFrame(
        {
            "team_id": ["aaa", "bbb", "ccc"],
            "age_group": ["u13", "u14", "u15"],
            "gender": ["Male", "Male", "Male"],
            "rank_in_cohort": [5, 10, 15],
            "rank_in_cohort_ml": [4, 9, 14],
            "rank_in_cohort_final": [4, 9, 14],
            "power_score_final": [0.8, 0.6, 0.4],
            "powerscore_ml": [0.82, 0.62, 0.42],
            "state_code": ["AZ", "AZ", "AZ"],
            "status": ["Active", "Active", "Active"],
        }
    )

    client = FakeSupabase()
    count = await save_ranking_snapshot(client, df)
    assert count == 3
