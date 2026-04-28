"""Regression: the cohort CLI's request payload reads ``prediction_date``.

Shell 06 sets ``payload["prediction_date"]`` from the operator's
``meta.extras["ranking_snapshot_date"]`` in
``run_orchestrator._build_cohort_request_payload``. The cohort CLI then
falls back to ``min(game_date)`` only when the field is absent — see
``scripts/backtest_tournament_cohort.py`` near the ``prediction_date =``
assignment. Spying on the full CLI requires real Supabase, so this test
asserts the wiring at the source-code + payload-builder level and pins
the CLI's ``payload.get("prediction_date")`` consumption pattern.
"""

from __future__ import annotations

from pathlib import Path

from src.tournaments import run_orchestrator
from src.tournaments.run_orchestrator import _build_cohort_request_payload
from src.tournaments.storage import (
    EventMetadata,
    TeamRegistryEntry,
    ensure_scenario,
    write_event_metadata,
    write_registry,
    write_structure,
)
from src.tournaments.storage.structure import CohortStructure, DivisionStructure

EVENT_KEY = "gotsport__45224__2026"
SCENARIO = "default"

REPO_ROOT = Path(run_orchestrator.__file__).resolve().parents[2]


def _bootstrap(base: Path) -> None:
    ensure_scenario(EVENT_KEY, SCENARIO, base_dir=base)
    write_event_metadata(
        EVENT_KEY,
        EventMetadata(
            provider_code="gotsport",
            provider_event_id="45224",
            event_name="Phoenix Cup 2026",
            event_slug="phoenix-cup-2026",
            event_start_date="2026-05-01",
            scrape_ts="2026-04-15T00:00:00+00:00",
            season_year=2026,
        ),
        base_dir=base,
    )
    write_structure(
        EVENT_KEY,
        SCENARIO,
        [
            CohortStructure(
                age_group="u14",
                gender="Boys",
                divisions=(DivisionStructure(name="A", team_count=1, pool_sizes=(1,)),),
            )
        ],
        base_dir=base,
    )
    write_registry(
        EVENT_KEY,
        SCENARIO,
        [
            TeamRegistryEntry(
                event_registration_id="reg-1",
                event_team_name="A Alpha",
                event_age_group="u14",
                event_gender="Boys",
                resolved_gotsport_provider_team_id="pid-1",
                resolved_team_id_master="tim-1",
            )
        ],
        base_dir=base,
    )


def test_payload_carries_prediction_date_from_extras(tmp_path: Path):
    _bootstrap(tmp_path)
    payload, _fallbacks, _stale = _build_cohort_request_payload(
        EVENT_KEY,
        SCENARIO,
        "u14",
        "Boys",
        base_dir=tmp_path,
        extras={"ranking_snapshot_date": "2026-01-15"},
    )
    assert payload["prediction_date"] == "2026-01-15"


def test_cohort_cli_reads_payload_prediction_date():
    """Pin the CLI's consumer line so a future refactor can't silently break the wire.

    The cohort CLI must read ``payload.get("prediction_date")`` somewhere in
    ``main()``; the orchestrator relies on that contract.
    """
    cli_text = (REPO_ROOT / "scripts" / "backtest_tournament_cohort.py").read_text(encoding="utf-8")
    assert 'payload.get("prediction_date")' in cli_text
