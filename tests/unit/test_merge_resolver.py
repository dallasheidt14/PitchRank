"""Exercise real merge loading across unstable, unordered page boundaries."""

import hashlib
from types import SimpleNamespace
from uuid import UUID

import pytest

from src.utils.merge_resolver import MergeResolver


class _MergeQuery:
    def __init__(self, client):
        self.client = client
        self.order_column = None
        self.bounds = None

    def select(self, columns):
        assert columns == "deprecated_team_id, canonical_team_id"
        return self

    def order(self, column):
        self.order_column = column
        return self

    def range(self, first, last):
        self.bounds = (first, last)
        return self

    def execute(self):
        self.client.calls += 1
        if self.client.fail_on_call == self.client.calls:
            raise RuntimeError("merge page unavailable")
        # Even an ORDER BY on a nonunique column leaves ties unspecified.
        # Vary physical order first; only a unique key stabilizes every page.
        rows = self.client.rows if self.client.calls % 2 else self.client.rows[::-1]
        if self.order_column:
            rows = sorted(rows, key=lambda row: row[self.order_column])
        first, last = self.bounds
        return SimpleNamespace(data=rows[first:last + 1])


class _MergeClient:
    def __init__(self, rows, fail_on_call=None):
        self.rows = rows
        self.calls = 0
        self.fail_on_call = fail_on_call

    def table(self, name):
        assert name == "team_merge_map"
        return _MergeQuery(self)


def _rows(count):
    return [
        {
            "deprecated_team_id": str(UUID(int=i + 1)),
            "canonical_team_id": str(UUID(int=100_000 + i // 3)),
        }
        for i in range(count)
    ][::-1]


@pytest.mark.parametrize("count", [1000, 1001, 2005])
def test_load_retains_every_mapping_across_page_boundaries(count):
    rows = _rows(count)
    resolver = MergeResolver(_MergeClient(rows))

    resolver.load_merge_map()

    assert resolver.merge_count == count
    assert resolver.get_deprecated_teams() == {row["deprecated_team_id"] for row in rows}
    assert all(resolver.resolve(row["deprecated_team_id"]) == row["canonical_team_id"] for row in rows)
    serialized = "".join(sorted(f"{row['deprecated_team_id']}:{row['canonical_team_id']}" for row in rows))
    assert resolver.version == hashlib.md5(serialized.encode()).hexdigest()[:8]


def test_refresh_is_complete_and_stable_when_physical_order_changes():
    rows = _rows(2005)
    client = _MergeClient(rows)
    resolver = MergeResolver(client)
    resolver.load_merge_map()
    first_version = resolver.version

    client.rows = rows[777:] + rows[:777]
    resolver.refresh()

    assert resolver.merge_count == 2005
    assert resolver.version == first_version
    assert all(resolver.resolve(row["deprecated_team_id"]) == row["canonical_team_id"] for row in rows)


def test_failed_later_page_never_exposes_a_partial_merge_map():
    resolver = MergeResolver(_MergeClient(_rows(2005), fail_on_call=2))

    resolver.load_merge_map()

    assert resolver.version == "error"
    assert resolver.merge_count == 0
    assert not resolver.has_merges
