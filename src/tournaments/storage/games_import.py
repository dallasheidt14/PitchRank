"""Games-import status helper for the per-cohort run pre-flight gate.

Spec §7 validation requires "Games coverage < 100%" surfacing as a blocker
in backtest mode. This helper produces the three-state classification the
UI consumes; the actual gate enforcement lives in Shell 04 (display) and
Shell 06 (run pre-flight).

Classification rules are conservative for v1 — final tuning of the
"complete" criterion can move into Shell 06 if the binary check proves too
strict in practice.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Literal

__all__ = [
    "GamesImportStatus",
    "check_games_import_status",
]


GamesImportStatus = Literal["not_imported", "partial", "complete"]


def check_games_import_status(
    event_name: str,
    registered_team_ids: Iterable[str],
    *,
    supabase_client: Any,
) -> GamesImportStatus:
    """Bin the games-coverage state for a tournament event.

    - 0 rows in ``games`` for ``event_name`` → ``"not_imported"``.
    - At least one game per ``team_id_master`` in ``registered_team_ids``
      → ``"complete"``.
    - Otherwise → ``"partial"``.

    Excluded games (``is_excluded=True``) are ignored — they aren't part of
    the rankings pipeline and would inflate coverage falsely.
    """
    response = (
        supabase_client.table("games")
        .select("home_team_master_id,away_team_master_id")
        .eq("event_name", event_name)
        .eq("is_excluded", False)
        .execute()
    )
    rows = response.data or []
    if not rows:
        return "not_imported"

    teams_with_games: set[str] = set()
    for row in rows:
        for column in ("home_team_master_id", "away_team_master_id"):
            value = row.get(column)
            if value:
                teams_with_games.add(str(value))

    registered = {str(team_id) for team_id in registered_team_ids if team_id}
    if registered and registered.issubset(teams_with_games):
        return "complete"
    return "partial"
