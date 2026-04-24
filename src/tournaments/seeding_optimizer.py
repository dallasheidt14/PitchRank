"""Tournament seeding optimizer for minimizing likely lopsided matchups.

This beta module uses current ranking strength as the matchup-cost signal.
It is intentionally separated from production prediction paths so the cost
model can later be swapped to a calibrated point-in-time competitive model.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from itertools import combinations
import math
from typing import Any, Callable, Iterable, Sequence


@dataclass(frozen=True)
class SeedableTeam:
    team_id: str
    team_name: str
    age_group: str
    gender: str
    power_score: float
    rank_in_cohort: float | None = None
    club_name: str | None = None
    state_code: str | None = None
    games_played: int | None = None


@dataclass(frozen=True)
class FlightSpec:
    name: str
    team_count: int


@dataclass(frozen=True)
class DivisionSpec:
    name: str
    team_count: int
    pool_sizes: tuple[int, ...] = ()
    advancement: str | None = None


@dataclass(frozen=True)
class MatchupCost:
    projected_margin: float
    competitive_probability: float
    blowout_3plus_probability: float
    blowout_5plus_probability: float
    total_cost: float


MatchupCostFn = Callable[["SeedableTeam", "SeedableTeam"], MatchupCost]


@dataclass(frozen=True)
class FlightAssignment:
    name: str
    teams: tuple[SeedableTeam, ...]
    total_pair_cost: float
    average_pair_cost: float
    average_projected_margin: float
    competitive_probability: float
    blowout_3plus_probability: float
    blowout_5plus_probability: float


@dataclass(frozen=True)
class DivisionAssignment:
    name: str
    teams: tuple[SeedableTeam, ...]
    total_pair_cost: float
    average_pair_cost: float
    average_projected_margin: float
    competitive_probability: float
    blowout_3plus_probability: float
    blowout_5plus_probability: float
    pool_sizes: tuple[int, ...]
    advancement: str | None
    pools: tuple[FlightAssignment, ...]


@dataclass(frozen=True)
class TournamentOptimizationResult:
    divisions: tuple[DivisionAssignment, ...]
    total_cost: float
    optimizer_iterations: int
    matchup_proxy: str = "strength_gap_proxy_v1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "matchup_proxy": self.matchup_proxy,
            "total_cost": self.total_cost,
            "optimizer_iterations": self.optimizer_iterations,
            "divisions": [
                {
                    "name": division.name,
                    "team_count": len(division.teams),
                    "total_pair_cost": division.total_pair_cost,
                    "average_pair_cost": division.average_pair_cost,
                    "average_projected_margin": division.average_projected_margin,
                    "competitive_probability": division.competitive_probability,
                    "blowout_3plus_probability": division.blowout_3plus_probability,
                    "blowout_5plus_probability": division.blowout_5plus_probability,
                    "pool_sizes": list(division.pool_sizes),
                    "advancement": division.advancement,
                    "pools": [
                        {
                            "name": pool.name,
                            "team_count": len(pool.teams),
                            "total_pair_cost": pool.total_pair_cost,
                            "average_pair_cost": pool.average_pair_cost,
                            "average_projected_margin": pool.average_projected_margin,
                            "competitive_probability": pool.competitive_probability,
                            "blowout_3plus_probability": pool.blowout_3plus_probability,
                            "blowout_5plus_probability": pool.blowout_5plus_probability,
                            "teams": [
                                {
                                    **asdict(team),
                                    "seed": seed_index,
                                }
                                for seed_index, team in enumerate(pool.teams, start=1)
                            ],
                        }
                        for pool in division.pools
                    ],
                    "teams": [
                        {
                            **asdict(team),
                            "seed": seed_index,
                        }
                        for seed_index, team in enumerate(division.teams, start=1)
                    ],
                }
                for division in self.divisions
            ],
        }


def normalize_gender_label(value: str) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"female", "f", "girls", "girl", "g"}:
        return "Female"
    return "Male"


def normalize_age_group(value: str) -> str:
    digits = "".join(character for character in str(value or "") if character.isdigit())
    if not digits:
        raise ValueError(f"Unable to parse age group from '{value}'")
    age_number = int(digits)
    if age_number == 18:
        age_number = 19
    return f"u{age_number}"


def normalize_team_text(value: str) -> str:
    return "".join(character for character in str(value or "").lower() if character.isalnum())


def _team_sort_key(team: SeedableTeam) -> tuple[float, float, str]:
    rank_value = float(team.rank_in_cohort) if team.rank_in_cohort is not None else float("inf")
    return (-float(team.power_score), rank_value, team.team_name.lower())


def _sigmoid(value: float) -> float:
    return 1.0 / (1.0 + math.exp(-value))


def projected_matchup_cost(team_a: SeedableTeam, team_b: SeedableTeam) -> MatchupCost:
    """Proxy matchup cost until a competitive-match model is wired in.

    The proxy leans on the current cohort strength gap. It is deliberately
    monotonic: larger strength gaps imply higher projected margin and a larger
    chance of a lopsided result.
    """

    power_gap = abs(float(team_a.power_score) - float(team_b.power_score))
    rank_gap = 0.0
    if team_a.rank_in_cohort is not None and team_b.rank_in_cohort is not None:
        rank_gap = abs(float(team_a.rank_in_cohort) - float(team_b.rank_in_cohort))

    projected_margin = min(6.0, 7.0 * power_gap + min(rank_gap / 32.0, 2.0))
    competitive_probability = _sigmoid((1.15 - projected_margin) / 0.45)
    blowout_3plus_probability = _sigmoid((projected_margin - 2.6) / 0.45)
    blowout_5plus_probability = _sigmoid((projected_margin - 4.5) / 0.40)
    total_cost = (
        projected_margin
        + (1.0 - competitive_probability)
        + (2.0 * blowout_3plus_probability)
        + (3.5 * blowout_5plus_probability)
    )
    return MatchupCost(
        projected_margin=projected_margin,
        competitive_probability=competitive_probability,
        blowout_3plus_probability=blowout_3plus_probability,
        blowout_5plus_probability=blowout_5plus_probability,
        total_cost=total_cost,
    )


def _pairwise_costs(
    teams: Sequence[SeedableTeam],
    matchup_cost_fn: MatchupCostFn = projected_matchup_cost,
) -> list[MatchupCost]:
    return [matchup_cost_fn(team_a, team_b) for team_a, team_b in combinations(teams, 2)]


def _pair_count(team_count: int) -> int:
    return max(0, int(team_count) * max(0, int(team_count) - 1) // 2)


def flight_total_cost(
    teams: Sequence[SeedableTeam],
    matchup_cost_fn: MatchupCostFn = projected_matchup_cost,
) -> float:
    return float(sum(matchup.total_cost for matchup in _pairwise_costs(teams, matchup_cost_fn=matchup_cost_fn)))


def _build_flight_assignment(
    name: str,
    teams: Sequence[SeedableTeam],
    matchup_cost_fn: MatchupCostFn = projected_matchup_cost,
) -> FlightAssignment:
    sorted_teams = tuple(sorted(teams, key=_team_sort_key))
    pairwise_costs = _pairwise_costs(sorted_teams, matchup_cost_fn=matchup_cost_fn)
    if not pairwise_costs:
        return FlightAssignment(
            name=name,
            teams=sorted_teams,
            total_pair_cost=0.0,
            average_pair_cost=0.0,
            average_projected_margin=0.0,
            competitive_probability=1.0,
            blowout_3plus_probability=0.0,
            blowout_5plus_probability=0.0,
        )

    return FlightAssignment(
        name=name,
        teams=sorted_teams,
        total_pair_cost=float(sum(item.total_cost for item in pairwise_costs)),
        average_pair_cost=float(sum(item.total_cost for item in pairwise_costs) / len(pairwise_costs)),
        average_projected_margin=float(sum(item.projected_margin for item in pairwise_costs) / len(pairwise_costs)),
        competitive_probability=float(
            sum(item.competitive_probability for item in pairwise_costs) / len(pairwise_costs)
        ),
        blowout_3plus_probability=float(
            sum(item.blowout_3plus_probability for item in pairwise_costs) / len(pairwise_costs)
        ),
        blowout_5plus_probability=float(
            sum(item.blowout_5plus_probability for item in pairwise_costs) / len(pairwise_costs)
        ),
    )


def total_tournament_cost(
    flights: Sequence[Sequence[SeedableTeam]],
    matchup_cost_fn: MatchupCostFn = projected_matchup_cost,
) -> float:
    return float(sum(flight_total_cost(flight, matchup_cost_fn=matchup_cost_fn) for flight in flights))


def _validate_flights(teams: Sequence[SeedableTeam], flights: Sequence[FlightSpec]) -> None:
    if not teams:
        raise ValueError("At least one team is required")
    if not flights:
        raise ValueError("At least one flight is required")
    requested_slots = sum(max(0, int(flight.team_count)) for flight in flights)
    if requested_slots != len(teams):
        raise ValueError(
            f"Flight sizes total {requested_slots}, but {len(teams)} teams were provided. "
            "Tournament seeding needs an exact slot count."
        )


def _pool_specs_from_division(division: DivisionSpec) -> list[FlightSpec]:
    pool_sizes = tuple(int(size) for size in division.pool_sizes if int(size) > 0)
    if not pool_sizes:
        pool_sizes = (int(division.team_count),)
    if sum(pool_sizes) != int(division.team_count):
        raise ValueError(
            f"Division '{division.name}' pool sizes sum to {sum(pool_sizes)}, "
            f"but division team_count is {division.team_count}."
        )
    return [FlightSpec(name=f"Pool {chr(65 + index)}", team_count=size) for index, size in enumerate(pool_sizes)]


def optimize_division_assignments(
    teams: Sequence[SeedableTeam],
    flights: Sequence[FlightSpec],
    *,
    max_iterations: int = 250,
    improvement_tolerance: float = 1e-9,
    matchup_cost_fn: MatchupCostFn = projected_matchup_cost,
    matchup_proxy: str = "strength_gap_proxy_v1",
) -> TournamentOptimizationResult:
    """Assign teams to flights with fixed sizes to minimize lopsided-pair cost."""

    _validate_flights(teams, flights)
    ordered_teams = sorted(teams, key=_team_sort_key)

    working_flights: list[list[SeedableTeam]] = []
    start_index = 0
    for flight in flights:
        end_index = start_index + int(flight.team_count)
        working_flights.append(list(ordered_teams[start_index:end_index]))
        start_index = end_index

    current_cost = total_tournament_cost(working_flights, matchup_cost_fn=matchup_cost_fn)
    iterations = 0

    while iterations < max_iterations:
        iterations += 1
        best_swap: tuple[int, int, int, int] | None = None
        best_new_cost = current_cost

        for left_flight_index in range(len(working_flights)):
            for right_flight_index in range(left_flight_index + 1, len(working_flights)):
                left_flight = working_flights[left_flight_index]
                right_flight = working_flights[right_flight_index]
                base_cost = flight_total_cost(left_flight, matchup_cost_fn=matchup_cost_fn) + flight_total_cost(
                    right_flight,
                    matchup_cost_fn=matchup_cost_fn,
                )

                for left_team_index in range(len(left_flight)):
                    for right_team_index in range(len(right_flight)):
                        candidate_left = list(left_flight)
                        candidate_right = list(right_flight)
                        candidate_left[left_team_index], candidate_right[right_team_index] = (
                            candidate_right[right_team_index],
                            candidate_left[left_team_index],
                        )
                        candidate_cost = flight_total_cost(
                            candidate_left,
                            matchup_cost_fn=matchup_cost_fn,
                        ) + flight_total_cost(
                            candidate_right,
                            matchup_cost_fn=matchup_cost_fn,
                        )
                        tournament_cost = current_cost - base_cost + candidate_cost
                        if tournament_cost + improvement_tolerance < best_new_cost:
                            best_new_cost = tournament_cost
                            best_swap = (
                                left_flight_index,
                                right_flight_index,
                                left_team_index,
                                right_team_index,
                            )

        if best_swap is None:
            break

        left_flight_index, right_flight_index, left_team_index, right_team_index = best_swap
        working_flights[left_flight_index][left_team_index], working_flights[right_flight_index][right_team_index] = (
            working_flights[right_flight_index][right_team_index],
            working_flights[left_flight_index][left_team_index],
        )
        current_cost = best_new_cost

    base_assignments = tuple(
        _build_flight_assignment(
            flight.name,
            working_flights[index],
            matchup_cost_fn=matchup_cost_fn,
        )
        for index, flight in enumerate(flights)
    )
    divisions = tuple(
        DivisionAssignment(
            name=assignment.name,
            teams=assignment.teams,
            total_pair_cost=assignment.total_pair_cost,
            average_pair_cost=assignment.average_pair_cost,
            average_projected_margin=assignment.average_projected_margin,
            competitive_probability=assignment.competitive_probability,
            blowout_3plus_probability=assignment.blowout_3plus_probability,
            blowout_5plus_probability=assignment.blowout_5plus_probability,
            pool_sizes=(len(assignment.teams),),
            advancement=None,
            pools=(assignment,),
        )
        for assignment in base_assignments
    )
    return TournamentOptimizationResult(
        divisions=divisions,
        total_cost=float(sum(division.total_pair_cost for division in divisions)),
        optimizer_iterations=iterations,
        matchup_proxy=matchup_proxy,
    )


def optimize_tournament_format(
    teams: Sequence[SeedableTeam],
    divisions: Sequence[DivisionSpec],
    *,
    max_iterations: int = 250,
    improvement_tolerance: float = 1e-9,
    matchup_cost_fn: MatchupCostFn = projected_matchup_cost,
    matchup_proxy: str = "strength_gap_proxy_v1",
) -> TournamentOptimizationResult:
    """Assign teams into the provided tournament format.

    The caller supplies the structure. This function only decides which teams
    should land in each division and pool to reduce likely lopsided games.
    """

    if not divisions:
        raise ValueError("At least one division format is required")

    top_level_specs = [FlightSpec(name=division.name, team_count=int(division.team_count)) for division in divisions]
    top_level_result = optimize_division_assignments(
        teams,
        top_level_specs,
        max_iterations=max_iterations,
        improvement_tolerance=improvement_tolerance,
        matchup_cost_fn=matchup_cost_fn,
        matchup_proxy=matchup_proxy,
    )

    division_assignments: list[DivisionAssignment] = []
    total_iterations = int(top_level_result.optimizer_iterations)

    for division_spec, base_assignment in zip(divisions, top_level_result.divisions, strict=False):
        pool_specs = _pool_specs_from_division(division_spec)
        if len(pool_specs) == 1:
            pools = (
                FlightAssignment(
                    name=pool_specs[0].name,
                    teams=base_assignment.teams,
                    total_pair_cost=base_assignment.total_pair_cost,
                    average_pair_cost=base_assignment.average_pair_cost,
                    average_projected_margin=base_assignment.average_projected_margin,
                    competitive_probability=base_assignment.competitive_probability,
                    blowout_3plus_probability=base_assignment.blowout_3plus_probability,
                    blowout_5plus_probability=base_assignment.blowout_5plus_probability,
                ),
            )
        else:
            pool_result = optimize_division_assignments(
                base_assignment.teams,
                pool_specs,
                max_iterations=max_iterations,
                improvement_tolerance=improvement_tolerance,
                matchup_cost_fn=matchup_cost_fn,
                matchup_proxy=matchup_proxy,
            )
            total_iterations += int(pool_result.optimizer_iterations)
            pools = tuple(
                FlightAssignment(
                    name=pool.name,
                    teams=pool.teams,
                    total_pair_cost=pool.total_pair_cost,
                    average_pair_cost=pool.average_pair_cost,
                    average_projected_margin=pool.average_projected_margin,
                    competitive_probability=pool.competitive_probability,
                    blowout_3plus_probability=pool.blowout_3plus_probability,
                    blowout_5plus_probability=pool.blowout_5plus_probability,
                )
                for pool in pool_result.divisions
            )

        total_pool_pairs = sum(_pair_count(len(pool.teams)) for pool in pools)
        if total_pool_pairs > 0:
            total_pair_cost = float(sum(pool.total_pair_cost for pool in pools))
            average_pair_cost = float(total_pair_cost / total_pool_pairs)
            average_projected_margin = float(
                sum(pool.average_projected_margin * _pair_count(len(pool.teams)) for pool in pools) / total_pool_pairs
            )
            competitive_probability = float(
                sum(pool.competitive_probability * _pair_count(len(pool.teams)) for pool in pools) / total_pool_pairs
            )
            blowout_3plus_probability = float(
                sum(pool.blowout_3plus_probability * _pair_count(len(pool.teams)) for pool in pools) / total_pool_pairs
            )
            blowout_5plus_probability = float(
                sum(pool.blowout_5plus_probability * _pair_count(len(pool.teams)) for pool in pools) / total_pool_pairs
            )
        else:
            total_pair_cost = 0.0
            average_pair_cost = 0.0
            average_projected_margin = 0.0
            competitive_probability = 1.0
            blowout_3plus_probability = 0.0
            blowout_5plus_probability = 0.0

        division_assignments.append(
            DivisionAssignment(
                name=division_spec.name,
                teams=base_assignment.teams,
                total_pair_cost=total_pair_cost,
                average_pair_cost=average_pair_cost,
                average_projected_margin=average_projected_margin,
                competitive_probability=competitive_probability,
                blowout_3plus_probability=blowout_3plus_probability,
                blowout_5plus_probability=blowout_5plus_probability,
                pool_sizes=tuple(spec.team_count for spec in pool_specs),
                advancement=division_spec.advancement,
                pools=pools,
            )
        )

    return TournamentOptimizationResult(
        divisions=tuple(division_assignments),
        total_cost=float(sum(division.total_pair_cost for division in division_assignments)),
        optimizer_iterations=total_iterations,
        matchup_proxy=matchup_proxy,
    )


def build_seedable_teams(rows: Iterable[dict[str, Any]]) -> list[SeedableTeam]:
    teams: list[SeedableTeam] = []
    for row in rows:
        power_score = row.get("power_score")
        if power_score is None:
            continue
        teams.append(
            SeedableTeam(
                team_id=str(row["team_id"]),
                team_name=str(row["team_name"]),
                age_group=normalize_age_group(str(row["age_group"])),
                gender=normalize_gender_label(str(row["gender"])),
                power_score=float(power_score),
                rank_in_cohort=float(row["rank_in_cohort"]) if row.get("rank_in_cohort") is not None else None,
                club_name=row.get("club_name"),
                state_code=row.get("state_code"),
                games_played=int(row["games_played"]) if row.get("games_played") is not None else None,
            )
        )
    return teams
