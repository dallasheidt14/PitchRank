"""Tournament schedule replay helpers for exact-format cohort backtests.

This module sits on top of the seeding optimizer. The optimizer decides which
teams should land in each division/pool. The schedule simulator then replays a
real tournament format against that optimized placement so we can compare:

- actual completed tournament goal differential
- simulated goal differential under the optimized grouping

The current inference intentionally targets the formats we have already seen in
the beta fixtures:

- 2 pools of 4 -> pool round robin + final
- 2 pools of 3 -> pool round robin + crossover semis + final + 3rd place
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import median
from typing import Any, Callable, Sequence

from src.tournaments.seeding_optimizer import DivisionAssignment, SeedableTeam

PredictionFn = Callable[[SeedableTeam, SeedableTeam], Any]


@dataclass(frozen=True)
class DivisionScheduleTemplate:
    division_name: str
    actual_division_name: str | None
    pool_sizes: tuple[int, ...]
    pool_play_format: str
    playoff_format: str
    actual_game_count: int | None = None
    inference_notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "division_name": self.division_name,
            "actual_division_name": self.actual_division_name,
            "pool_sizes": list(self.pool_sizes),
            "pool_play_format": self.pool_play_format,
            "playoff_format": self.playoff_format,
            "actual_game_count": self.actual_game_count,
            "inference_notes": list(self.inference_notes),
        }


@dataclass(frozen=True)
class SimulatedMatch:
    division_name: str
    stage: str
    pool_name: str | None
    home_team_id: str
    away_team_id: str
    home_team_name: str
    away_team_name: str
    predicted_winner: str
    home_score: int
    away_score: int
    goal_differential: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "division_name": self.division_name,
            "stage": self.stage,
            "pool_name": self.pool_name,
            "home_team_id": self.home_team_id,
            "away_team_id": self.away_team_id,
            "home_team_name": self.home_team_name,
            "away_team_name": self.away_team_name,
            "predicted_winner": self.predicted_winner,
            "home_score": self.home_score,
            "away_score": self.away_score,
            "goal_differential": self.goal_differential,
        }


@dataclass(frozen=True)
class DivisionSimulation:
    division_name: str
    template: DivisionScheduleTemplate
    match_count: int
    average_goal_differential: float
    median_goal_differential: float
    close_game_rate: float
    blowout_3plus_rate: float
    blowout_5plus_rate: float
    draw_rate: float
    matches: tuple[SimulatedMatch, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "division_name": self.division_name,
            "template": self.template.to_dict(),
            "match_count": self.match_count,
            "average_goal_differential": self.average_goal_differential,
            "median_goal_differential": self.median_goal_differential,
            "close_game_rate": self.close_game_rate,
            "blowout_3plus_rate": self.blowout_3plus_rate,
            "blowout_5plus_rate": self.blowout_5plus_rate,
            "draw_rate": self.draw_rate,
            "matches": [match.to_dict() for match in self.matches],
        }


@dataclass(frozen=True)
class TournamentScheduleSimulation:
    match_count: int
    average_goal_differential: float
    median_goal_differential: float
    close_game_rate: float
    blowout_3plus_rate: float
    blowout_5plus_rate: float
    draw_rate: float
    divisions: tuple[DivisionSimulation, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "match_count": self.match_count,
            "average_goal_differential": self.average_goal_differential,
            "median_goal_differential": self.median_goal_differential,
            "close_game_rate": self.close_game_rate,
            "blowout_3plus_rate": self.blowout_3plus_rate,
            "blowout_5plus_rate": self.blowout_5plus_rate,
            "draw_rate": self.draw_rate,
            "divisions": [division.to_dict() for division in self.divisions],
        }


def _pair_count(team_count: int) -> int:
    return max(0, int(team_count) * max(0, int(team_count) - 1) // 2)


def infer_division_schedule_template(
    *,
    division_name: str,
    pool_sizes: Sequence[int],
    actual_game_count: int | None,
    actual_division_name: str | None = None,
) -> DivisionScheduleTemplate:
    pool_sizes = tuple(int(size) for size in pool_sizes)
    pool_round_robin_games = sum(_pair_count(size) for size in pool_sizes)
    notes: list[str] = []

    if actual_game_count is None:
        notes.append("No actual game count provided; replay will use pool round robin only.")
        return DivisionScheduleTemplate(
            division_name=division_name,
            actual_division_name=actual_division_name,
            pool_sizes=pool_sizes,
            pool_play_format="round_robin",
            playoff_format="none",
            actual_game_count=None,
            inference_notes=tuple(notes),
        )

    extra_games = int(actual_game_count) - pool_round_robin_games
    playoff_format = "none"

    if extra_games < 0:
        notes.append(
            f"Actual game count {actual_game_count} is below pool round-robin minimum {pool_round_robin_games}; "
            "falling back to pool-only replay."
        )
    elif extra_games == 0:
        playoff_format = "none"
    elif len(pool_sizes) == 2 and extra_games == 1:
        playoff_format = "pool_winners_final"
    elif len(pool_sizes) == 2 and extra_games == 3:
        playoff_format = "cross_semis_final"
    elif len(pool_sizes) == 2 and extra_games == 4:
        playoff_format = "cross_semis_final_third"
    elif len(pool_sizes) == 1 and extra_games == 1:
        playoff_format = "one_pool_final"
    else:
        notes.append(
            f"Unsupported playoff shape for pool_sizes={list(pool_sizes)} and extra_games={extra_games}; "
            "falling back to pool-only replay."
        )

    return DivisionScheduleTemplate(
        division_name=division_name,
        actual_division_name=actual_division_name,
        pool_sizes=pool_sizes,
        pool_play_format="round_robin",
        playoff_format=playoff_format,
        actual_game_count=int(actual_game_count),
        inference_notes=tuple(notes),
    )


def _round_half_up(value: float) -> int:
    if math.isnan(value) or math.isinf(value):
        return 0
    return max(0, int(math.floor(value + 0.5)))


def _winner_consistent_score(predicted_winner: str, raw_score_a: float, raw_score_b: float) -> tuple[int, int]:
    score_a = _round_half_up(float(raw_score_a))
    score_b = _round_half_up(float(raw_score_b))

    if predicted_winner == "team_a" and score_a <= score_b:
        score_a = score_b + 1
    elif predicted_winner == "team_b" and score_b <= score_a:
        score_b = score_a + 1
    elif predicted_winner == "draw" and score_a != score_b:
        tied_score = _round_half_up((float(raw_score_a) + float(raw_score_b)) / 2.0)
        score_a = tied_score
        score_b = tied_score

    return score_a, score_b


def _simulate_match(
    *,
    division_name: str,
    stage: str,
    pool_name: str | None,
    home_team: SeedableTeam,
    away_team: SeedableTeam,
    predict_fn: PredictionFn,
) -> SimulatedMatch:
    prediction = predict_fn(home_team, away_team)
    raw_score_a = float(prediction.expected_score["teamA"])
    raw_score_b = float(prediction.expected_score["teamB"])
    home_score, away_score = _winner_consistent_score(prediction.predicted_winner, raw_score_a, raw_score_b)

    return SimulatedMatch(
        division_name=division_name,
        stage=stage,
        pool_name=pool_name,
        home_team_id=home_team.team_id,
        away_team_id=away_team.team_id,
        home_team_name=home_team.team_name,
        away_team_name=away_team.team_name,
        predicted_winner=str(prediction.predicted_winner),
        home_score=home_score,
        away_score=away_score,
        goal_differential=abs(home_score - away_score),
    )


def _update_pool_standings(
    standings: dict[str, dict[str, Any]],
    match: SimulatedMatch,
    home_team: SeedableTeam,
    away_team: SeedableTeam,
) -> None:
    home_row = standings[home_team.team_id]
    away_row = standings[away_team.team_id]

    home_row["gf"] += int(match.home_score)
    home_row["ga"] += int(match.away_score)
    home_row["gd"] += int(match.home_score) - int(match.away_score)
    away_row["gf"] += int(match.away_score)
    away_row["ga"] += int(match.home_score)
    away_row["gd"] += int(match.away_score) - int(match.home_score)

    if match.home_score > match.away_score:
        home_row["points"] += 3
        home_row["wins"] += 1
        away_row["losses"] += 1
    elif match.home_score < match.away_score:
        away_row["points"] += 3
        away_row["wins"] += 1
        home_row["losses"] += 1
    else:
        home_row["points"] += 1
        away_row["points"] += 1
        home_row["draws"] += 1
        away_row["draws"] += 1


def _rank_pool_teams(pool_teams: Sequence[SeedableTeam], standings: dict[str, dict[str, Any]]) -> list[SeedableTeam]:
    def sort_key(team: SeedableTeam) -> tuple[float, float, float, float, str]:
        row = standings[team.team_id]
        return (
            -float(row["points"]),
            -float(row["gd"]),
            -float(row["gf"]),
            -float(team.power_score),
            team.team_name.lower(),
        )

    return sorted(pool_teams, key=sort_key)


def _summarize_matches(matches: Sequence[SimulatedMatch]) -> tuple[int, float, float, float, float, float, float]:
    if not matches:
        return 0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0

    margins = [int(match.goal_differential) for match in matches]
    match_count = len(margins)
    return (
        match_count,
        float(sum(margins) / match_count),
        float(median(margins)),
        float(sum(1 for margin in margins if margin <= 1) / match_count),
        float(sum(1 for margin in margins if margin >= 3) / match_count),
        float(sum(1 for margin in margins if margin >= 5) / match_count),
        float(sum(1 for margin in margins if margin == 0) / match_count),
    )


def simulate_division_schedule(
    division: DivisionAssignment,
    template: DivisionScheduleTemplate,
    predict_fn: PredictionFn,
) -> DivisionSimulation:
    pool_rankings: list[list[SeedableTeam]] = []
    simulated_matches: list[SimulatedMatch] = []

    for pool in division.pools:
        standings = {
            team.team_id: {
                "points": 0,
                "gd": 0,
                "gf": 0,
                "ga": 0,
                "wins": 0,
                "draws": 0,
                "losses": 0,
            }
            for team in pool.teams
        }

        pool_teams = list(pool.teams)
        for left_index in range(len(pool_teams)):
            for right_index in range(left_index + 1, len(pool_teams)):
                home_team = pool_teams[left_index]
                away_team = pool_teams[right_index]
                match = _simulate_match(
                    division_name=division.name,
                    stage="Pool",
                    pool_name=pool.name,
                    home_team=home_team,
                    away_team=away_team,
                    predict_fn=predict_fn,
                )
                simulated_matches.append(match)
                _update_pool_standings(standings, match, home_team, away_team)

        pool_rankings.append(_rank_pool_teams(pool_teams, standings))

    if template.playoff_format == "pool_winners_final" and len(pool_rankings) >= 2:
        simulated_matches.append(
            _simulate_match(
                division_name=division.name,
                stage="Final",
                pool_name=None,
                home_team=pool_rankings[0][0],
                away_team=pool_rankings[1][0],
                predict_fn=predict_fn,
            )
        )
    elif template.playoff_format in {"cross_semis_final", "cross_semis_final_third"} and len(pool_rankings) >= 2:
        semi_a = _simulate_match(
            division_name=division.name,
            stage="Semi Final A",
            pool_name=None,
            home_team=pool_rankings[0][0],
            away_team=pool_rankings[1][1],
            predict_fn=predict_fn,
        )
        semi_b = _simulate_match(
            division_name=division.name,
            stage="Semi Final B",
            pool_name=None,
            home_team=pool_rankings[1][0],
            away_team=pool_rankings[0][1],
            predict_fn=predict_fn,
        )
        simulated_matches.extend([semi_a, semi_b])

        final_home = pool_rankings[0][0] if semi_a.home_score >= semi_a.away_score else pool_rankings[1][1]
        final_away = pool_rankings[1][0] if semi_b.home_score >= semi_b.away_score else pool_rankings[0][1]
        simulated_matches.append(
            _simulate_match(
                division_name=division.name,
                stage="Final",
                pool_name=None,
                home_team=final_home,
                away_team=final_away,
                predict_fn=predict_fn,
            )
        )

        if template.playoff_format == "cross_semis_final_third":
            third_home = pool_rankings[1][1] if semi_a.home_score >= semi_a.away_score else pool_rankings[0][0]
            third_away = pool_rankings[0][1] if semi_b.home_score >= semi_b.away_score else pool_rankings[1][0]
            simulated_matches.append(
                _simulate_match(
                    division_name=division.name,
                    stage="Third Place",
                    pool_name=None,
                    home_team=third_home,
                    away_team=third_away,
                    predict_fn=predict_fn,
                )
            )
    elif template.playoff_format == "one_pool_final" and pool_rankings and len(pool_rankings[0]) >= 2:
        simulated_matches.append(
            _simulate_match(
                division_name=division.name,
                stage="Final",
                pool_name=None,
                home_team=pool_rankings[0][0],
                away_team=pool_rankings[0][1],
                predict_fn=predict_fn,
            )
        )

    (
        match_count,
        average_goal_differential,
        median_goal_differential,
        close_game_rate,
        blowout_3plus_rate,
        blowout_5plus_rate,
        draw_rate,
    ) = _summarize_matches(simulated_matches)

    return DivisionSimulation(
        division_name=division.name,
        template=template,
        match_count=match_count,
        average_goal_differential=average_goal_differential,
        median_goal_differential=median_goal_differential,
        close_game_rate=close_game_rate,
        blowout_3plus_rate=blowout_3plus_rate,
        blowout_5plus_rate=blowout_5plus_rate,
        draw_rate=draw_rate,
        matches=tuple(simulated_matches),
    )


def simulate_tournament_schedule(
    divisions: Sequence[DivisionAssignment],
    templates: dict[str, DivisionScheduleTemplate],
    predict_fn: PredictionFn,
) -> TournamentScheduleSimulation:
    division_summaries = tuple(
        simulate_division_schedule(
            division=division,
            template=templates[division.name],
            predict_fn=predict_fn,
        )
        for division in divisions
    )

    all_matches = [match for division in division_summaries for match in division.matches]
    (
        match_count,
        average_goal_differential,
        median_goal_differential,
        close_game_rate,
        blowout_3plus_rate,
        blowout_5plus_rate,
        draw_rate,
    ) = _summarize_matches(all_matches)

    return TournamentScheduleSimulation(
        match_count=match_count,
        average_goal_differential=average_goal_differential,
        median_goal_differential=median_goal_differential,
        close_game_rate=close_game_rate,
        blowout_3plus_rate=blowout_3plus_rate,
        blowout_5plus_rate=blowout_5plus_rate,
        draw_rate=draw_rate,
        divisions=division_summaries,
    )
