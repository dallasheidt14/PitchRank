import pandas as pd
import pytest

from src.rankings import data_adapter


MAX_ROWS = 1000


class _FakeResult:
    def __init__(self, data):
        self.data = data


class _FakeQuery:
    def __init__(self, client, table_name: str):
        self.client = client
        self.table_name = table_name
        self.select_columns = None
        self.offset = 0
        self.limit_end = 0
        self.in_values = []

    @property
    def not_(self):
        return self

    def select(self, columns):
        self.select_columns = columns
        if self.table_name == "games":
            self.client.last_games_select = columns
        return self

    def gte(self, *_args, **_kwargs):
        return self

    def lte(self, *_args, **_kwargs):
        return self

    def eq(self, *_args, **_kwargs):
        return self

    def order(self, *_args, **_kwargs):
        return self

    def is_(self, *_args, **_kwargs):
        return self

    def in_(self, _column, values):
        self.in_values = list(values)
        return self

    def maybe_single(self):
        return self

    def range(self, start, end):
        clone = _FakeQuery(self.client, self.table_name)
        clone.select_columns = self.select_columns
        clone.offset = start
        clone.limit_end = end
        clone.in_values = self.in_values
        return clone

    def execute(self):
        if self.table_name == "games":
            page = self.client.games_pages.get(self.offset)
            if isinstance(page, Exception):
                raise page
            return _FakeResult(page or [])

        if self.table_name == "teams":
            return _FakeResult(
                [self.client.team_rows[team_id] for team_id in self.in_values if team_id in self.client.team_rows]
            )

        if self.table_name == "providers":
            row = self.client.provider_row
            if isinstance(row, Exception):
                raise row
            # Real maybe_single().execute() returns bare None on zero rows,
            # not a response object with data=None
            if row is None:
                return None
            return _FakeResult(row)

        if self.table_name == "team_merge_map":
            rows = self.client.merge_rows
            if isinstance(rows, Exception):
                raise rows
            return _FakeResult(rows[self.offset : self.limit_end + 1])

        if self.table_name == "team_ranking_exclusions":
            rows = self.client.excluded_rows
            if isinstance(rows, Exception):
                raise rows
            # A double that served any window a caller asked for would hide a page size
            # above PostgREST's max-rows cap, which supabase/config.toml pins at 1,000.
            ordered = sorted(rows, key=lambda row: row["team_id_master"])
            window = ordered[self.offset : self.limit_end + 1]
            return _FakeResult(window[:MAX_ROWS])

        raise AssertionError(f"Unexpected table {self.table_name}")


class _FakeSupabase:
    def __init__(self, games_pages=None, team_rows=None, provider_row=None, excluded_rows=None, merge_rows=None):
        self.games_pages = games_pages or {}
        self.team_rows = team_rows or {}
        self.provider_row = provider_row
        self.excluded_rows = excluded_rows if excluded_rows is not None else []
        self.merge_rows = merge_rows if merge_rows is not None else []
        self.last_games_select = None

    def table(self, table_name: str):
        return _FakeQuery(self, table_name)


@pytest.mark.asyncio
async def test_fetch_games_for_rankings_raises_instead_of_returning_partial_snapshot(monkeypatch):
    monkeypatch.setattr(data_adapter, "retry_supabase_query", lambda query_func, **_kwargs: query_func())

    first_page = [
        {
            "id": f"game-{idx}",
            "game_date": "2026-04-01",
            "home_team_master_id": "team-home",
            "away_team_master_id": "team-away",
            "home_score": 2,
            "away_score": 1,
            "provider_id": "provider-1",
        }
        for idx in range(1000)
    ]
    fake_db = _FakeSupabase(
        games_pages={
            0: first_page,
            1000: RuntimeError("JSON could not be generated"),
        }
    )

    with pytest.raises(RuntimeError, match="partial 1,000-game snapshot"):
        await data_adapter.fetch_games_for_rankings(
            fake_db,
            today=pd.Timestamp("2026-04-14", tz="UTC"),
        )

    assert "game_uid" not in fake_db.last_games_select


@pytest.mark.asyncio
async def test_fetch_games_for_rankings_uses_id_when_game_uid_is_not_selected(monkeypatch):
    monkeypatch.setattr(data_adapter, "retry_supabase_query", lambda query_func, **_kwargs: query_func())

    fake_db = _FakeSupabase(
        games_pages={
            0: [
                {
                    "id": "game-1",
                    "game_date": "2026-04-01",
                    "home_team_master_id": "team-home",
                    "away_team_master_id": "team-away",
                    "home_score": 3,
                    "away_score": 2,
                    "provider_id": "provider-1",
                }
            ]
        },
        team_rows={
            "team-home": {
                "team_id_master": "team-home",
                "age_group": "u12",
                "gender": "Male",
                "is_deprecated": False,
                "league": None,
            },
            "team-away": {
                "team_id_master": "team-away",
                "age_group": "u12",
                "gender": "Male",
                "is_deprecated": False,
                "league": None,
            },
        },
    )

    result = await data_adapter.fetch_games_for_rankings(
        fake_db,
        today=pd.Timestamp("2026-04-14", tz="UTC"),
    )

    assert len(result) == 2
    assert set(result["game_id"]) == {"game-1"}
    assert "game_uid" not in fake_db.last_games_select


@pytest.mark.asyncio
async def test_fetch_games_for_rankings_raises_when_provider_lookup_fails(monkeypatch):
    monkeypatch.setattr(data_adapter, "retry_supabase_query", lambda query_func, **_kwargs: query_func())

    fake_db = _FakeSupabase(games_pages={0: []}, provider_row=RuntimeError("connection reset"))

    with pytest.raises(RuntimeError, match="refusing to fall back"):
        await data_adapter.fetch_games_for_rankings(
            fake_db,
            provider_filter="gotsport",
            today=pd.Timestamp("2026-04-14", tz="UTC"),
        )


@pytest.mark.asyncio
async def test_fetch_games_for_rankings_raises_when_provider_filter_matches_nothing(monkeypatch):
    monkeypatch.setattr(data_adapter, "retry_supabase_query", lambda query_func, **_kwargs: query_func())

    fake_db = _FakeSupabase(games_pages={0: []}, provider_row=None)

    with pytest.raises(RuntimeError, match="matched no provider"):
        await data_adapter.fetch_games_for_rankings(
            fake_db,
            provider_filter="gotsport",
            today=pd.Timestamp("2026-04-14", tz="UTC"),
        )


@pytest.mark.asyncio
async def test_fetch_games_for_rankings_drops_self_games(monkeypatch):
    monkeypatch.setattr(data_adapter, "retry_supabase_query", lambda query_func, **_kwargs: query_func())

    fake_db = _FakeSupabase(
        games_pages={
            0: [
                {
                    "id": "game-self",
                    "game_date": "2026-04-01",
                    "home_team_master_id": "team-a",
                    "away_team_master_id": "team-a",
                    "home_score": 1,
                    "away_score": 1,
                    "provider_id": "provider-1",
                },
                {
                    "id": "game-real",
                    "game_date": "2026-04-02",
                    "home_team_master_id": "team-a",
                    "away_team_master_id": "team-b",
                    "home_score": 2,
                    "away_score": 0,
                    "provider_id": "provider-1",
                },
            ]
        },
        team_rows={
            "team-a": {
                "team_id_master": "team-a",
                "age_group": "u12",
                "gender": "Male",
                "is_deprecated": False,
                "league": None,
            },
            "team-b": {
                "team_id_master": "team-b",
                "age_group": "u12",
                "gender": "Male",
                "is_deprecated": False,
                "league": None,
            },
        },
    )

    result = await data_adapter.fetch_games_for_rankings(
        fake_db,
        today=pd.Timestamp("2026-04-14", tz="UTC"),
    )

    assert set(result["game_id"]) == {"game-real"}
    assert len(result) == 2


def _game(game_id, home, away):
    return {
        "id": game_id,
        "game_date": "2026-04-01",
        "home_team_master_id": home,
        "away_team_master_id": away,
        "home_score": 2,
        "away_score": 1,
        "provider_id": "provider-1",
    }


def _u16_team(team_id):
    return {"team_id_master": team_id, "age_group": "u16", "gender": "Male", "is_deprecated": False, "league": None}


@pytest.mark.asyncio
async def test_fetch_games_for_rankings_drops_every_game_an_excluded_team_played(monkeypatch):
    monkeypatch.setattr(data_adapter, "retry_supabase_query", lambda query_func, **_kwargs: query_func())

    fake_db = _FakeSupabase(
        games_pages={
            0: [
                _game("game-excluded-home", "team-english", "team-us-a"),
                _game("game-excluded-away", "team-us-b", "team-english"),
                _game("game-kept", "team-us-a", "team-us-b"),
            ]
        },
        team_rows={t: _u16_team(t) for t in ("team-english", "team-us-a", "team-us-b")},
        excluded_rows=[{"team_id_master": "team-english"}],
    )

    result = await data_adapter.fetch_games_for_rankings(
        fake_db,
        today=pd.Timestamp("2026-04-14", tz="UTC"),
    )

    assert set(result["game_id"]) == {"game-kept"}
    assert len(result) == 2


@pytest.mark.asyncio
async def test_fetch_games_for_rankings_reads_exclusions_past_the_first_page(monkeypatch):
    monkeypatch.setattr(data_adapter, "retry_supabase_query", lambda query_func, **_kwargs: query_func())

    fake_db = _FakeSupabase(
        games_pages={
            0: [_game("game-excluded", "z-team-english", "team-us-a"), _game("game-kept", "team-us-a", "team-us-b")]
        },
        team_rows={t: _u16_team(t) for t in ("z-team-english", "team-us-a", "team-us-b")},
        # "z-team-english" sorts after every filler, so only a second page reaches it.
        excluded_rows=[{"team_id_master": f"team-other-{idx:04d}"} for idx in range(1000)]
        + [{"team_id_master": "z-team-english"}],
    )

    result = await data_adapter.fetch_games_for_rankings(
        fake_db,
        today=pd.Timestamp("2026-04-14", tz="UTC"),
    )

    assert set(result["game_id"]) == {"game-kept"}


class _FakeMergeResolver:
    def __init__(self, merge_map, version="test"):
        self._merge_map = merge_map
        self.has_merges = bool(merge_map)
        self._version = version
        self._loaded = True

    def resolve(self, team_id):
        return self._merge_map.get(str(team_id), str(team_id))

    def resolve_dataframe(self, df, columns):
        for column in columns:
            df[column] = df[column].astype(str).map(lambda v: self._merge_map.get(v, v))
        return df

    def get_deprecated_teams(self):
        return set(self._merge_map)

    @property
    def merge_count(self):
        return len(self._merge_map)

    @property
    def version(self):
        return self._version


@pytest.mark.asyncio
async def test_a_merged_alias_of_an_excluded_team_stays_excluded(monkeypatch):
    """Games keep the deprecated id, so the filter must see them after resolution."""
    monkeypatch.setattr(data_adapter, "retry_supabase_query", lambda query_func, **_kwargs: query_func())

    fake_db = _FakeSupabase(
        games_pages={
            0: [
                _game("game-via-alias", "team-english-old", "team-us-a"),
                _game("game-kept", "team-us-a", "team-us-b"),
            ]
        },
        team_rows={t: _u16_team(t) for t in ("team-english-old", "team-english", "team-us-a", "team-us-b")},
        excluded_rows=[{"team_id_master": "team-english"}],
    )

    result = await data_adapter.fetch_games_for_rankings(
        fake_db,
        today=pd.Timestamp("2026-04-14", tz="UTC"),
        merge_resolver=_FakeMergeResolver({"team-english-old": "team-english"}),
    )

    assert set(result["game_id"]) == {"game-kept"}


@pytest.mark.asyncio
async def test_an_excluded_team_merged_into_another_team_stays_excluded(monkeypatch):
    """The list holds the id that was listed; a later merge moves its games to the survivor."""
    monkeypatch.setattr(data_adapter, "retry_supabase_query", lambda query_func, **_kwargs: query_func())

    fake_db = _FakeSupabase(
        games_pages={
            0: [
                _game("game-now-under-survivor", "team-english", "team-us-a"),
                _game("game-kept", "team-us-a", "team-us-b"),
            ]
        },
        team_rows={t: _u16_team(t) for t in ("team-english", "team-survivor", "team-us-a", "team-us-b")},
        excluded_rows=[{"team_id_master": "team-english"}],
    )

    result = await data_adapter.fetch_games_for_rankings(
        fake_db,
        today=pd.Timestamp("2026-04-14", tz="UTC"),
        merge_resolver=_FakeMergeResolver({"team-english": "team-survivor"}),
    )

    assert set(result["game_id"]) == {"game-kept"}


@pytest.mark.asyncio
async def test_a_caller_with_no_resolver_still_excludes_a_merged_away_team(monkeypatch):
    """compute_rankings_with_ml's fallback and Layer 13's pass no resolver, and an exclusion
    that skipped resolution there would rank the survivor again."""
    monkeypatch.setattr(data_adapter, "retry_supabase_query", lambda query_func, **_kwargs: query_func())

    fake_db = _FakeSupabase(
        games_pages={
            0: [
                _game("game-now-under-survivor", "team-survivor", "team-us-a"),
                _game("game-kept", "team-us-a", "team-us-b"),
            ]
        },
        team_rows={t: _u16_team(t) for t in ("team-survivor", "team-us-a", "team-us-b")},
        excluded_rows=[{"team_id_master": "team-english"}],
        merge_rows=[{"deprecated_team_id": "team-english", "canonical_team_id": "team-survivor"}],
    )

    result = await data_adapter.fetch_games_for_rankings(
        fake_db,
        today=pd.Timestamp("2026-04-14", tz="UTC"),
    )

    assert set(result["game_id"]) == {"game-kept"}


@pytest.mark.asyncio
async def test_a_failed_merge_map_read_stops_the_run_rather_than_passing_as_no_merges(monkeypatch):
    """MergeResolver swallows its own read failure and then reports no merges, which would
    skip the expansion above and rank a merged-away excluded team again."""
    monkeypatch.setattr(data_adapter, "retry_supabase_query", lambda query_func, **_kwargs: query_func())

    fake_db = _FakeSupabase(
        games_pages={0: [_game("game-kept", "team-us-a", "team-us-b")]},
        team_rows={t: _u16_team(t) for t in ("team-us-a", "team-us-b")},
        excluded_rows=[{"team_id_master": "team-english"}],
    )

    with pytest.raises(RuntimeError, match="Merge map failed to load"):
        await data_adapter.fetch_games_for_rankings(
            fake_db,
            today=pd.Timestamp("2026-04-14", tz="UTC"),
            merge_resolver=_FakeMergeResolver({}, version="error"),
        )


@pytest.mark.asyncio
async def test_a_failed_merge_map_read_is_not_raised_when_nothing_is_excluded(monkeypatch):
    """Runs with an empty list are unaffected: this guard is about resolving the list."""
    monkeypatch.setattr(data_adapter, "retry_supabase_query", lambda query_func, **_kwargs: query_func())

    fake_db = _FakeSupabase(
        games_pages={0: [_game("game-kept", "team-us-a", "team-us-b")]},
        team_rows={t: _u16_team(t) for t in ("team-us-a", "team-us-b")},
    )

    result = await data_adapter.fetch_games_for_rankings(
        fake_db,
        today=pd.Timestamp("2026-04-14", tz="UTC"),
        merge_resolver=_FakeMergeResolver({}, version="error"),
    )

    assert set(result["game_id"]) == {"game-kept"}


@pytest.mark.asyncio
async def test_fetch_games_for_rankings_raises_when_the_exclusion_list_cannot_be_read(monkeypatch):
    monkeypatch.setattr(data_adapter, "retry_supabase_query", lambda query_func, **_kwargs: query_func())

    fake_db = _FakeSupabase(
        games_pages={0: [_game("game-kept", "team-us-a", "team-us-b")]},
        team_rows={t: _u16_team(t) for t in ("team-us-a", "team-us-b")},
        excluded_rows=RuntimeError("Could not find the table 'public.team_ranking_exclusions'"),
    )

    with pytest.raises(RuntimeError, match="refusing to rank without the exclusion list"):
        await data_adapter.fetch_games_for_rankings(
            fake_db,
            today=pd.Timestamp("2026-04-14", tz="UTC"),
        )


def test_batch_fetch_rows_raises_after_exhausted_retries(monkeypatch):
    calls = {"count": 0}

    def fake_retry(query_func, **_kwargs):
        calls["count"] += 1
        if calls["count"] == 2:
            raise RuntimeError("server disconnected")
        return _FakeResult([{"team_id_master": "team-1"}])

    monkeypatch.setattr(data_adapter, "retry_supabase_query", fake_retry)

    # 150 values -> two batches of 100; the second batch fails and must
    # propagate instead of returning the partial first batch
    with pytest.raises(RuntimeError, match="server disconnected"):
        data_adapter.batch_fetch_rows(
            _FakeSupabase(),
            "teams",
            "team_id_master",
            "team_id_master",
            [f"team-{idx}" for idx in range(150)],
        )
