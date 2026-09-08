"""Tests for the caller side of the total-game-stats backfill.

The RPC handles one keyset page per call and this walk feeds each page's last id
back as ``p_after``. The double records at ``execute()``, never at ``rpc()``:
postgrest-py returns a builder that does nothing until executed, so a double that
recorded at ``rpc()`` would count a page the caller built and never sent.
"""

import pytest

import scripts.calculate_rankings as calc


class _Result:
    def __init__(self, data):
        self.data = data


class _Builder:
    def __init__(self, parent, name, params):
        self._parent = parent
        self._name = name
        self._params = params

    def execute(self):
        self._parent.calls.append((self._name, self._params))
        return self._parent.answer(self._params)


class _Supabase:
    """Serves `pages` in order; raises the entries that are exceptions."""

    def __init__(self, pages):
        self._pages = list(pages)
        self.calls = []

    def rpc(self, name, params):
        return _Builder(self, name, params)

    def answer(self, _params):
        page = self._pages.pop(0)
        if isinstance(page, Exception):
            raise page
        return _Result(page)


class _Console:
    def print(self, *_args, **_kwargs):
        pass


def page(rows_changed, last_team_id):
    return [{"rows_changed": rows_changed, "last_team_id": last_team_id}]


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(calc.time, "sleep", lambda _s: None)


def test_the_walk_feeds_each_pages_last_id_back_as_p_after():
    sb = _Supabase([page(3, "id-a"), page(1, "id-b"), page(0, None)])

    changed = calc._backfill_total_game_stats(sb, _Console())

    assert changed == 4
    assert [params["p_after"] for _name, params in sb.calls] == [None, "id-a", "id-b"]


def test_the_walk_calls_the_paged_function_with_a_bounded_page():
    sb = _Supabase([page(0, None)])

    calc._backfill_total_game_stats(sb, _Console())

    name, params = sb.calls[0]
    assert name == "backfill_total_game_stats_page"
    assert params["p_batch_size"] == calc.GAME_STATS_BATCH_SIZE
    assert params["p_dry_run"] is False


def test_the_walk_never_asks_for_a_page_larger_than_the_server_budget_allows():
    """2,000 is measured against an 8s statement_timeout; a large raise needs its own look."""
    assert 0 < calc.GAME_STATS_BATCH_SIZE <= 5000


def test_an_empty_page_ends_the_walk():
    sb = _Supabase([page(2, "id-a"), []])

    changed = calc._backfill_total_game_stats(sb, _Console())

    assert changed == 2
    assert len(sb.calls) == 2


def test_a_transient_page_failure_is_retried_on_the_same_p_after():
    """A cancelled statement takes its transaction with it, so a replay cannot double-count."""
    sb = _Supabase([page(5, "id-a"), RuntimeError("57014 canceling statement"), page(4, None)])

    changed = calc._backfill_total_game_stats(sb, _Console())

    assert changed == 9
    assert [params["p_after"] for _name, params in sb.calls] == [None, "id-a", "id-a"]


def test_a_page_that_never_succeeds_raises_rather_than_reporting_a_short_count():
    """The run must not report a partial backfill as a complete one."""
    sb = _Supabase([RuntimeError("boom")] * calc.GAME_STATS_PAGE_ATTEMPTS)

    with pytest.raises(RuntimeError):
        calc._backfill_total_game_stats(sb, _Console())

    assert len(sb.calls) == calc.GAME_STATS_PAGE_ATTEMPTS
