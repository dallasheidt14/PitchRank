"""Round-robin pool-play assignments per gotsport tier.

Sibling artifact to ``intake/raw_scrape.jsonl``. Lives in the intake tier
(scenario-shared) because the pool layout is a property of the scraped
event, not of any forward-looking seeding scenario.

Schema (one file per event)::

    {
      "schema_version": 1,
      "pools_by_group_id": {
        "365847": [
          {"label": "A", "bracket_id": "501350", "provider_team_ids": ["3194980", ...]},
          {"label": "B", "bracket_id": "501351", "provider_team_ids": [...]}
        ],
        ...
      }
    }

The outer key is gotsport's tier ``group_id`` (already on each
``raw_scrape.jsonl`` record), so callers can look up pool data per tier
without re-walking the scrape.
"""

from __future__ import annotations

from pathlib import Path

from src.scrapers.gotsport_pool_parser import PoolAssignment
from src.tournaments.storage._io import read_versioned_json, write_json
from src.tournaments.storage.event_key import intake_dir
from src.tournaments.storage.schema_version import stamp_schema_version

__all__ = [
    "read_pool_assignments",
    "write_pool_assignments",
]


def _pool_assignments_path(event_key: str, *, base_dir: Path | str) -> Path:
    return intake_dir(event_key, base_dir=base_dir) / "pool_assignments.json"


def read_pool_assignments(
    event_key: str,
    *,
    base_dir: Path | str = "reports",
) -> dict[str, list[PoolAssignment]]:
    """Return ``{group_id: [PoolAssignment, ...]}`` for the event.

    Returns an empty dict when the file does not exist (callers treat
    pool data as optional — backtests without pool assignments still run
    at the bracket level).
    """
    path = _pool_assignments_path(event_key, base_dir=base_dir)
    if not path.exists():
        return {}
    payload = read_versioned_json(path)
    pools_by_group: dict[str, list[PoolAssignment]] = {}
    for group_id, raw_pools in (payload.get("pools_by_group_id") or {}).items():
        pools_by_group[str(group_id)] = [
            PoolAssignment(
                label=str(entry["label"]),
                bracket_id=str(entry["bracket_id"]),
                provider_team_ids=tuple(str(pid) for pid in entry.get("provider_team_ids") or ()),
            )
            for entry in raw_pools
        ]
    return pools_by_group


def write_pool_assignments(
    event_key: str,
    pools_by_group_id: dict[str, list[PoolAssignment]],
    *,
    base_dir: Path | str = "reports",
) -> None:
    """Persist ``pool_assignments.json`` with the schema-version stamp."""
    path = _pool_assignments_path(event_key, base_dir=base_dir)
    payload = stamp_schema_version(
        {
            "pools_by_group_id": {
                str(group_id): [
                    {
                        "label": p.label,
                        "bracket_id": p.bracket_id,
                        "provider_team_ids": list(p.provider_team_ids),
                    }
                    for p in pools
                ]
                for group_id, pools in pools_by_group_id.items()
            }
        }
    )
    write_json(path, payload)
