"""--dry-run must reach every writer, not just the rankings_full save.

The flag set is derived from compute_all_cohorts' real signature, so a future
persist_* flag fails here until --dry-run is wired to it.
calculate_rank_changes_enabled is deliberately excluded — that path only reads.
"""

import inspect
import sys

import pandas as pd
import pytest

import scripts.calculate_rankings as calc

# Captured at import time, before any monkeypatching, from the real signature.
_PERSISTENCE_FLAGS = [
    name
    for name in inspect.signature(calc.compute_all_cohorts).parameters
    if name.startswith("persist_") or name == "save_snapshot"
]


class _FakeMergeResolver:
    has_merges = False
    merge_count = 0
    version = "test"

    def __init__(self, _supabase):
        pass

    def load_merge_map(self):
        pass


def _ranked_teams_df():
    return pd.DataFrame(
        [
            {
                "team_id": "team-1",
                "team_name": "Test FC",
                "age": "12",
                "gender": "Male",
                "powerscore_core": 0.5,
            }
        ]
    )


def _patch_environment(monkeypatch, argv):
    captured = {"save_calls": 0, "backfill_calls": 0}

    async def fake_compute_all_cohorts(**kwargs):
        captured.update(kwargs)
        return {"teams": _ranked_teams_df()}

    async def fake_save_rankings(_supabase, teams_df, **_kwargs):
        captured["save_calls"] += 1
        return len(teams_df)

    async def fake_backfill(_supabase, _console):
        captured["backfill_calls"] += 1
        return 0

    monkeypatch.setattr(calc, "compute_all_cohorts", fake_compute_all_cohorts)
    monkeypatch.setattr(calc, "save_rankings_to_supabase", fake_save_rankings)
    monkeypatch.setattr(calc, "_backfill_game_stats_python", fake_backfill)
    monkeypatch.setattr(calc, "create_client", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(calc, "MergeResolver", _FakeMergeResolver)
    monkeypatch.setenv("SUPABASE_URL", "http://localhost")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "test-key")
    monkeypatch.setattr(sys, "argv", ["calculate_rankings.py", *argv])
    return captured


def test_signature_still_exposes_the_known_flags():
    assert {"persist_game_residuals", "persist_game_explainability", "save_snapshot"} <= set(_PERSISTENCE_FLAGS)


@pytest.mark.asyncio
@pytest.mark.parametrize("argv", [["--ml"], []])
async def test_dry_run_disables_every_writer(monkeypatch, argv):
    captured = _patch_environment(monkeypatch, [*argv, "--dry-run"])

    await calc.main()

    for flag in _PERSISTENCE_FLAGS:
        assert captured[flag] is False, flag
    assert captured["save_calls"] == 0
    assert captured["backfill_calls"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("argv", [["--ml"], []])
async def test_live_run_keeps_every_writer_enabled(monkeypatch, argv):
    captured = _patch_environment(monkeypatch, argv)

    await calc.main()

    for flag in _PERSISTENCE_FLAGS:
        assert captured[flag] is True, flag
    assert captured["save_calls"] == 1
    # The faked client has no .rpc, so the live path reaches the Python fallback.
    assert captured["backfill_calls"] == 1
