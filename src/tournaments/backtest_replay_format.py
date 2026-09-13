"""Determine when captured division evidence is sufficient for exact replay."""

from __future__ import annotations

from dataclasses import dataclass

from src.tournaments.schedule_simulator import (
    SUPPORTED_PLAYOFF_FORMATS,
    explicit_division_schedule_template,
)


@dataclass(frozen=True)
class ReplayFormatAssessment:
    format_code: str = ""
    reason: str = ""

    @property
    def ready(self) -> bool:
        return bool(self.format_code) and not self.reason


def assess_replay_format(division, *, manual_format: str = "") -> ReplayFormatAssessment:
    """Infer a supported replay format only when stage evidence agrees exactly."""

    if not division.pools_readable or not division.fixtures_readable:
        return ReplayFormatAssessment(reason="Pools or fixtures could not be read completely")
    pool_sizes = tuple(len(pool.members) for pool in division.pools)
    if not pool_sizes or any(size <= 0 for size in pool_sizes):
        return ReplayFormatAssessment(reason="No complete pool membership was captured")
    if any(fixture.kind == "cross_pool" for fixture in division.fixtures):
        return ReplayFormatAssessment(reason="Cross-pool scheduling needs a dedicated replay template")
    if any(fixture.kind == "unknown" for fixture in division.fixtures):
        return ReplayFormatAssessment(reason="One or more fixture stages could not be classified")
    expected_pool_games = sum(size * (size - 1) // 2 for size in pool_sizes)
    captured_pool_games = sum(fixture.kind == "pool" for fixture in division.fixtures)
    if captured_pool_games != expected_pool_games:
        return ReplayFormatAssessment(
            reason=(
                f"Captured {captured_pool_games} pool games; a full round robin for these pools "
                f"requires {expected_pool_games}"
            )
        )
    if manual_format:
        try:
            explicit_division_schedule_template(
                division_name=division.division_label or division.group_id,
                pool_sizes=pool_sizes,
                format_code=manual_format,
                actual_game_count=len(division.fixtures),
                actual_division_name=division.division_label,
            )
        except ValueError as exc:
            return ReplayFormatAssessment(reason=str(exc))
        return ReplayFormatAssessment(format_code=manual_format)
    candidates = []
    for format_code in sorted(SUPPORTED_PLAYOFF_FORMATS):
        try:
            explicit_division_schedule_template(
                division_name=division.division_label or division.group_id,
                pool_sizes=pool_sizes,
                format_code=format_code,
                actual_game_count=len(division.fixtures),
                actual_division_name=division.division_label,
            )
        except ValueError:
            continue
        candidates.append(format_code)
    if len(candidates) == 1:
        return ReplayFormatAssessment(format_code=candidates[0])
    if not candidates:
        return ReplayFormatAssessment(reason="The captured game count has no supported replay format")
    return ReplayFormatAssessment(reason="The captured evidence matches more than one replay format")
