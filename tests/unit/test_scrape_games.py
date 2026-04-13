import asyncio
import io
import threading
from types import SimpleNamespace

import pytest

from scripts.scrape_games import _bulk_log_team_scrapes, _is_placeholder_unknown_team, _scrape_team_concurrent
from src.scrapers.gotsport import TeamNotFoundError


class FakeQuery:
    def __init__(self, supabase, table_name):
        self.supabase = supabase
        self.table_name = table_name
        self.action = None
        self.payload = None
        self.filters = []

    def insert(self, payload):
        self.action = "insert"
        self.payload = payload
        return self

    def update(self, payload):
        self.action = "update"
        self.payload = payload
        return self

    def eq(self, column, value):
        self.filters.append((column, value))
        return self

    def execute(self):
        if self.action == "insert":
            self.supabase.insert_calls.append((self.table_name, self.payload))
        elif self.action == "update":
            self.supabase.update_calls.append((self.table_name, self.payload, list(self.filters)))
        return SimpleNamespace(data=[])


class FakeSupabase:
    def __init__(self):
        self.insert_calls = []
        self.update_calls = []

    def table(self, table_name):
        return FakeQuery(self, table_name)


class FakeProgress:
    def __init__(self):
        self.calls = []

    def update(self, task_id, advance):
        self.calls.append((task_id, advance))


class MissingTeamScraper:
    def scrape_team_games(self, team_id, since_date=None):
        raise TeamNotFoundError(team_id)


def test_is_placeholder_unknown_team_matches_exact_unknown_pattern():
    assert _is_placeholder_unknown_team({"team_name": "unknown_3712624", "provider_team_id": "3712624"})
    assert _is_placeholder_unknown_team({"team_name": "UNKNOWN_3712624", "provider_team_id": "3712624"})


def test_is_placeholder_unknown_team_ignores_real_team_names():
    assert not _is_placeholder_unknown_team({"team_name": "Solar SC 12G ECNL", "provider_team_id": "3712624"})
    assert not _is_placeholder_unknown_team({"team_name": "unknown_elite", "provider_team_id": "3712624"})
    assert not _is_placeholder_unknown_team({"team_name": "unknown_3712624", "provider_team_id": ""})


def test_bulk_log_team_scrapes_records_error_status_and_selective_updates():
    supabase = FakeSupabase()

    _bulk_log_team_scrapes(
        supabase,
        "provider-1",
        [
            {
                "team_id_master": "team-1",
                "games_found": 3,
                "status": "success",
                "update_last_scraped_at": True,
            },
            {
                "team_id_master": "team-2",
                "games_found": 0,
                "status": "error",
                "update_last_scraped_at": False,
            },
        ],
    )

    assert len(supabase.insert_calls) == 1
    table_name, inserted_rows = supabase.insert_calls[0]
    assert table_name == "team_scrape_log"
    assert [row["status"] for row in inserted_rows] == ["success", "error"]

    assert len(supabase.update_calls) == 1
    update_table, payload, filters = supabase.update_calls[0]
    assert update_table == "teams"
    assert payload.keys() == {"last_scraped_at"}
    assert filters == [("team_id_master", "team-1")]


@pytest.mark.asyncio
async def test_scrape_team_concurrent_downgrades_team_not_found_to_skip():
    progress = FakeProgress()
    log_buffer = []

    result = await _scrape_team_concurrent(
        semaphore=asyncio.Semaphore(1),
        scraper=MissingTeamScraper(),
        team={
            "provider_team_id": "3712624",
            "team_name": "unknown_3712624",
            "team_id_master": "team-master-1",
        },
        since_date=None,
        scrape_dates_cache={},
        file_lock=threading.Lock(),
        output_file_handle=io.StringIO(),
        log_buffer=log_buffer,
        flush_counter=[0],
        progress=progress,
        task_id="task-1",
    )

    assert result == (0, None, True)
    assert log_buffer == [
        {
            "team_id_master": "team-master-1",
            "games_found": 0,
            "status": "error",
            "update_last_scraped_at": True,
        }
    ]
    assert progress.calls == [("task-1", 1)]
