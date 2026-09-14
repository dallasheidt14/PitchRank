"""Tournament schedule replay helpers for exact-format cohort backtests.

This module sits on top of the seeding optimizer. The optimizer decides which
teams should land in each division/pool. The schedule simulator then replays a
real tournament format against that optimized placement so we can compare:

- actual completed tournament goal differential
- simulated goal differential under the optimized grouping

The explicit v1 contract supports:

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

SUPPORTED_PLAYOFF_FORMATS = frozenset({"ROUND_ROBIN", "F_ONLY", "SF_F", "SF_F_3P"})
CAPTURED_GRAPH_FORMAT = "CAPTURED_GRAPH"
DEFAULT_TIEBREAK_ORDER = (
    "points",
    "goal_differential",
    "goals_for",
    "wins",
)
TIGER_TOURNAMENTS_TIEBREAK_ORDER = (
    "points",
    "head_to_head",
    "goal_differential",
    "goals_for",
    "goals_against",
)
SUPPORTED_TIEBREAK_FIELDS = frozenset(
    {*DEFAULT_TIEBREAK_ORDER, *TIGER_TOURNAMENTS_TIEBREAK_ORDER}
)
STANDARD_SCORING_POLICY = "standard_3_1_0_uncapped_goal_differential"
TIGER_TOURNAMENTS_SCORING_POLICY = "tiger_3_1_0_cap_5_goal_differential_and_goals_for"
SUPPORTED_SCORING_POLICIES = frozenset(
    {STANDARD_SCORING_POLICY, TIGER_TOURNAMENTS_SCORING_POLICY}
)


def normalize_tiebreak_order(
    tiebreak_order: Sequence[str],
    *,
    allow_empty: bool = True,
) -> tuple[str, ...]:
    """Validate the explicit tournament rule order used for pool standings."""

    normalized = tuple(str(item).strip() for item in tiebreak_order)
    if not normalized and allow_empty:
        return ()
    if (
        not normalized
        or normalized[0] != "points"
        or len(set(normalized)) != len(normalized)
        or not set(normalized).issubset(SUPPORTED_TIEBREAK_FIELDS)
    ):
        raise ValueError(
            "A verified tiebreak order must contain unique supported criteria beginning with points"
        )
    return normalized


@dataclass(frozen=True)
class DivisionScheduleTemplate:
    division_name: str
    actual_division_name: str | None
    pool_sizes: tuple[int, ...]
    pool_play_format: str
    playoff_format: str
    actual_game_count: int | None = None
    inference_notes: tuple[str, ...] = ()
    fixture_slots: tuple[dict[str, Any], ...] = ()
    tiebreak_order: tuple[str, ...] = DEFAULT_TIEBREAK_ORDER
    tiebreak_source_urls: tuple[str, ...] = ()
    scoring_policy: str = STANDARD_SCORING_POLICY
    three_team_head_to_head: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "division_name": self.division_name,
            "actual_division_name": self.actual_division_name,
            "pool_sizes": list(self.pool_sizes),
            "pool_play_format": self.pool_play_format,
            "playoff_format": self.playoff_format,
            "actual_game_count": self.actual_game_count,
            "inference_notes": list(self.inference_notes),
            "fixture_slots": [dict(item) for item in self.fixture_slots],
            "tiebreak_order": list(self.tiebreak_order),
            "tiebreak_source_urls": list(self.tiebreak_source_urls),
            "scoring_policy": self.scoring_policy,
            "three_team_head_to_head": self.three_team_head_to_head,
        }


def captured_division_schedule_template(
    *,
    division_name: str,
    actual_division_name: str | None,
    pool_sizes: Sequence[int],
    fixture_slots: Sequence[dict[str, Any]],
    tiebreak_order: Sequence[str] = (),
    tiebreak_source_urls: Sequence[str] = (),
    scoring_policy: str = "",
    three_team_head_to_head: bool = False,
) -> DivisionScheduleTemplate:
    """Build a template from the captured match-slot graph rather than a canned format."""

    normalized_pool_sizes = tuple(int(size) for size in pool_sizes)
    if not normalized_pool_sizes or any(size <= 0 for size in normalized_pool_sizes):
        raise ValueError(f"Division '{division_name}' needs positive captured pool sizes")
    slots = tuple(dict(item) for item in fixture_slots)
    if not slots:
        raise ValueError(f"Division '{division_name}' needs at least one captured fixture slot")
    allowed_refs = {
        "pool_slot",
        "pool_rank",
        "division_rank",
        "match_winner",
        "match_loser",
    }
    for index, fixture in enumerate(slots):
        for side in ("home", "away"):
            ref = fixture.get(side)
            if not isinstance(ref, dict) or str(ref.get("kind") or "") not in allowed_refs:
                raise ValueError(
                    f"Division '{division_name}' fixture slot {index + 1} has an invalid {side} reference"
                )
            if ref["kind"] in {"match_winner", "match_loser"} and int(ref["match_index"]) >= index:
                raise ValueError(
                    f"Division '{division_name}' fixture slot {index + 1} has a forward match reference"
                )
            if (
                ref["kind"] in {"match_winner", "match_loser"}
                and slots[int(ref["match_index"])].get("include_in_projection", True) is False
            ):
                raise ValueError(
                    f"Division '{division_name}' fixture slot {index + 1} references a match "
                    "that was not played"
                )
            if ref["kind"] == "division_rank" and not (
                0 <= int(ref["rank"]) < sum(normalized_pool_sizes)
            ):
                raise ValueError(
                    f"Division '{division_name}' fixture slot {index + 1} references a missing "
                    "division standings position"
                )
    try:
        normalized_tiebreak = normalize_tiebreak_order(tiebreak_order)
    except ValueError as error:
        raise ValueError(
            f"Division '{division_name}' needs a unique supported tiebreak order beginning with points"
        ) from error
    if scoring_policy not in SUPPORTED_SCORING_POLICIES:
        raise ValueError(
            f"Division '{division_name}' uses an unsupported scoring or standings modifier"
        )
    return DivisionScheduleTemplate(
        division_name=division_name,
        actual_division_name=actual_division_name,
        pool_sizes=normalized_pool_sizes,
        pool_play_format="captured_fixture_graph",
        playoff_format="captured_fixture_graph",
        actual_game_count=sum(
            slot.get("include_in_projection", True) is not False for slot in slots
        ),
        inference_notes=(),
        fixture_slots=slots,
        tiebreak_order=normalized_tiebreak,
        tiebreak_source_urls=tuple(str(url) for url in tiebreak_source_urls if str(url)),
        scoring_policy=scoring_policy,
        three_team_head_to_head=bool(three_team_head_to_head),
    )


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
    expected_goal_differential: float
    blowout_4plus_probability: float | None = None
    advancing_team_id: str | None = None
    advancement_basis: str | None = None

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
            "expected_goal_differential": self.expected_goal_differential,
            "blowout_4plus_probability": self.blowout_4plus_probability,
            "advancing_team_id": self.advancing_team_id,
            "advancement_basis": self.advancement_basis,
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
    qualification_tiebreaks: tuple[dict[str, Any], ...] = ()

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
            "qualification_tiebreaks": [dict(item) for item in self.qualification_tiebreaks],
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


def explicit_division_schedule_template(
    *,
    division_name: str,
    pool_sizes: Sequence[int],
    format_code: str | None,
    actual_game_count: int | None,
    actual_division_name: str | None = None,
) -> DivisionScheduleTemplate:
    """Build a replay template only from an operator-reviewed format code.

    Game counts are validation evidence. They never select a format.
    """

    normalized_format = str(format_code or "").strip().upper()
    if normalized_format not in SUPPORTED_PLAYOFF_FORMATS:
        raise ValueError(
            f"Division '{division_name}' needs an explicit supported format code: "
            f"{', '.join(sorted(SUPPORTED_PLAYOFF_FORMATS))}; got {format_code!r}"
        )
    normalized_pool_sizes = tuple(int(size) for size in pool_sizes)
    if not normalized_pool_sizes or any(size <= 0 for size in normalized_pool_sizes):
        raise ValueError(f"Division '{division_name}' needs positive explicit pool sizes")
    if normalized_format == "F_ONLY" and len(normalized_pool_sizes) == 1 and normalized_pool_sizes[0] < 2:
        raise ValueError(
            f"Division '{division_name}' format F_ONLY needs at least two teams in its pool"
        )
    if normalized_format in {"SF_F", "SF_F_3P"} and any(size < 2 for size in normalized_pool_sizes):
        raise ValueError(
            f"Division '{division_name}' format {normalized_format} needs at least two teams in each pool"
        )

    if normalized_format == "ROUND_ROBIN":
        playoff_format = "none"
        extra_games = 0
    elif normalized_format == "F_ONLY" and len(normalized_pool_sizes) == 1:
        playoff_format = "one_pool_final"
        extra_games = 1
    elif normalized_format == "F_ONLY" and len(normalized_pool_sizes) == 2:
        playoff_format = "pool_winners_final"
        extra_games = 1
    elif normalized_format == "SF_F" and len(normalized_pool_sizes) == 2:
        playoff_format = "cross_semis_final"
        extra_games = 3
    elif normalized_format == "SF_F_3P" and len(normalized_pool_sizes) == 2:
        playoff_format = "cross_semis_final_third"
        extra_games = 4
    else:
        raise ValueError(
            f"Division '{division_name}' format {normalized_format} does not support "
            f"{len(normalized_pool_sizes)} pool(s)"
        )

    expected_game_count = sum(_pair_count(size) for size in normalized_pool_sizes) + extra_games
    if actual_game_count is not None and int(actual_game_count) != expected_game_count:
        raise ValueError(
            f"Division '{division_name}' explicit format {normalized_format} produces "
            f"{expected_game_count} games, but the captured division contains {actual_game_count}"
        )
    return DivisionScheduleTemplate(
        division_name=division_name,
        actual_division_name=actual_division_name,
        pool_sizes=normalized_pool_sizes,
        pool_play_format="round_robin",
        playoff_format=playoff_format,
        actual_game_count=actual_game_count,
        inference_notes=(),
    )


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


def _winner_consistent_score(
    predicted_winner: str,
    raw_score_a: float,
    raw_score_b: float,
    *,
    expected_margin: float | None = None,
) -> tuple[int, int]:
    score_a = _round_half_up(float(raw_score_a))
    score_b = _round_half_up(float(raw_score_b))

    if expected_margin is not None and predicted_winner in {"team_a", "team_b"}:
        calibrated_gap = max(1, _round_half_up(abs(float(expected_margin))))
        if predicted_winner == "team_a":
            score_b = _round_half_up(float(raw_score_b))
            score_a = score_b + calibrated_gap
        else:
            score_a = _round_half_up(float(raw_score_a))
            score_b = score_a + calibrated_gap
    elif predicted_winner == "team_a" and score_a <= score_b:
        score_a = score_b + 1
    elif predicted_winner == "team_b" and score_b <= score_a:
        score_b = score_a + 1
    elif predicted_winner == "draw" and score_a != score_b:
        tied_score = _round_half_up((float(raw_score_a) + float(raw_score_b)) / 2.0)
        score_a = tied_score
        score_b = tied_score

    return score_a, score_b


def _optional_probability(prediction: Any, field: str) -> float | None:
    value = getattr(prediction, field, None)
    if value is None:
        return None
    probability = float(value)
    if not math.isfinite(probability) or not 0.0 <= probability <= 1.0:
        raise ValueError(f"{field} must be a finite probability between 0 and 1")
    return probability


def prediction_expected_margin(prediction: Any) -> float:
    """Return the one signed margin used by optimization, reporting, and replay."""

    scores = getattr(prediction, "expected_score", {}) or {}
    fallback = float(scores.get("teamA", 0.0)) - float(scores.get("teamB", 0.0))
    expected_margin = float(getattr(prediction, "expected_margin", fallback))
    if not math.isfinite(expected_margin):
        raise ValueError("expected_margin must be finite")
    if str(getattr(prediction, "predicted_winner", "")) == "draw":
        return 0.0
    return expected_margin


def prediction_expected_absolute_goal_difference(prediction: Any) -> float:
    """Return the expected observed absolute score difference for reporting."""

    value = getattr(prediction, "expected_absolute_goal_difference", None)
    if value is None:
        return abs(prediction_expected_margin(prediction))
    expected_absolute = float(value)
    if not math.isfinite(expected_absolute) or expected_absolute < 0:
        raise ValueError("expected_absolute_goal_difference must be finite and non-negative")
    return expected_absolute


def _advancement_decision(
    prediction: Any,
    home_team: SeedableTeam,
    away_team: SeedableTeam,
    home_score: int,
    away_score: int,
) -> tuple[str, str]:
    """Resolve knockout draws without depending on captured home orientation."""

    if home_score > away_score:
        return home_team.team_id, "projected_score"
    if away_score > home_score:
        return away_team.team_id, "projected_score"
    home_win = _optional_probability(prediction, "win_probability_a")
    away_win = _optional_probability(prediction, "win_probability_b")
    if home_win is not None and away_win is not None and home_win != away_win:
        return (
            (home_team.team_id, "regulation_win_probability")
            if home_win > away_win
            else (away_team.team_id, "regulation_win_probability")
        )
    if float(home_team.power_score) != float(away_team.power_score):
        return (
            (home_team.team_id, "pre_event_strength")
            if float(home_team.power_score) > float(away_team.power_score)
            else (away_team.team_id, "pre_event_strength")
        )
    return min(home_team.team_id, away_team.team_id), "stable_team_id"


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
    expected_margin = prediction_expected_margin(prediction)
    home_score, away_score = _winner_consistent_score(
        prediction.predicted_winner,
        raw_score_a,
        raw_score_b,
        expected_margin=expected_margin,
    )
    advancing_team_id, advancement_basis = _advancement_decision(
        prediction,
        home_team,
        away_team,
        home_score,
        away_score,
    )

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
        expected_goal_differential=prediction_expected_absolute_goal_difference(prediction),
        blowout_4plus_probability=_optional_probability(
            prediction, "blowout_4plus_probability"
        ),
        advancing_team_id=advancing_team_id,
        advancement_basis=advancement_basis,
    )


def _update_pool_standings(
    standings: dict[str, dict[str, Any]],
    match: SimulatedMatch,
    home_team: SeedableTeam,
    away_team: SeedableTeam,
    scoring_policy: str = STANDARD_SCORING_POLICY,
) -> None:
    home_row = standings[home_team.team_id]
    away_row = standings[away_team.team_id]

    home_row["gf"] += int(match.home_score)
    home_row["ga"] += int(match.away_score)
    home_row["gd"] += int(match.home_score) - int(match.away_score)
    away_row["gf"] += int(match.away_score)
    away_row["ga"] += int(match.home_score)
    away_row["gd"] += int(match.away_score) - int(match.home_score)

    if scoring_policy == TIGER_TOURNAMENTS_SCORING_POLICY:
        margin = int(match.home_score) - int(match.away_score)
        home_row["gd_capped"] += max(-5, min(5, margin))
        away_row["gd_capped"] += max(-5, min(5, -margin))
        home_row["gf_capped"] += min(5, int(match.home_score))
        away_row["gf_capped"] += min(5, int(match.away_score))
    else:
        home_row["gd_capped"] = home_row["gd"]
        away_row["gd_capped"] = away_row["gd"]
        home_row["gf_capped"] = home_row["gf"]
        away_row["gf_capped"] = away_row["gf"]

    if match.home_score > match.away_score:
        home_row["points"] += 3
        home_row["wins"] += 1
        away_row["losses"] += 1
        home_row["head_to_head"][away_team.team_id] = (
            home_row["head_to_head"].get(away_team.team_id, 0) + 3
        )
        away_row["head_to_head"].setdefault(home_team.team_id, 0)
    elif match.home_score < match.away_score:
        away_row["points"] += 3
        away_row["wins"] += 1
        home_row["losses"] += 1
        home_row["head_to_head"].setdefault(away_team.team_id, 0)
        away_row["head_to_head"][home_team.team_id] = (
            away_row["head_to_head"].get(home_team.team_id, 0) + 3
        )
    else:
        home_row["points"] += 1
        away_row["points"] += 1
        home_row["draws"] += 1
        away_row["draws"] += 1
        home_row["head_to_head"][away_team.team_id] = (
            home_row["head_to_head"].get(away_team.team_id, 0) + 1
        )
        away_row["head_to_head"][home_team.team_id] = (
            away_row["head_to_head"].get(home_team.team_id, 0) + 1
        )


def _tiebreak_values(
    team: SeedableTeam,
    pool_teams: Sequence[SeedableTeam],
    standings: dict[str, dict[str, Any]],
    tiebreak_order: Sequence[str],
    *,
    scoring_policy: str,
    three_team_head_to_head: bool = False,
) -> tuple[float, ...]:
    row = standings[team.team_id]
    teams_tied_on_points = {
        candidate.team_id
        for candidate in pool_teams
        if standings[candidate.team_id]["points"] == row["points"]
    }
    use_head_to_head = len(teams_tied_on_points) == 2 or (
        len(teams_tied_on_points) == 3 and three_team_head_to_head
    )
    head_to_head = (
        sum(
            int(points)
            for opponent, points in row["head_to_head"].items()
            if opponent in teams_tied_on_points
        )
        if use_head_to_head
        else 0
    )
    tiger_policy = scoring_policy == TIGER_TOURNAMENTS_SCORING_POLICY
    values = {
        "points": float(row["points"]),
        "head_to_head": float(head_to_head),
        "goal_differential": float(row["gd_capped"] if tiger_policy else row["gd"]),
        "goals_for": float(row["gf_capped"] if tiger_policy else row["gf"]),
        "goals_against": -float(row["ga"]),
        "wins": float(row["wins"]),
    }
    return tuple(values[item] for item in tiebreak_order)


def _rank_pool_teams(
    pool_teams: Sequence[SeedableTeam],
    standings: dict[str, dict[str, Any]],
    tiebreak_order: Sequence[str] = DEFAULT_TIEBREAK_ORDER,
    *,
    division_name: str = "",
    scoring_policy: str = STANDARD_SCORING_POLICY,
    three_team_head_to_head: bool = False,
) -> list[SeedableTeam]:
    def sort_key(team: SeedableTeam) -> tuple[Any, ...]:
        values = _tiebreak_values(
            team,
            pool_teams,
            standings,
            tiebreak_order,
            scoring_policy=scoring_policy,
            three_team_head_to_head=three_team_head_to_head,
        )
        return tuple(-value for value in values) + (team.team_id,)

    return sorted(pool_teams, key=sort_key)


def _rank_pool_teams_for_qualifier(
    pool_teams: Sequence[SeedableTeam],
    standings: dict[str, dict[str, Any]],
    tiebreak_order: Sequence[str],
    qualifier_rank: int,
    *,
    division_name: str,
    tiebreak_source_urls: Sequence[str],
    scoring_policy: str = STANDARD_SCORING_POLICY,
    three_team_head_to_head: bool = False,
    predict_fn: PredictionFn | None = None,
    qualification_tiebreaks: list[dict[str, Any]] | None = None,
) -> list[SeedableTeam]:
    if tiebreak_order:
        ranked = _rank_pool_teams(
            pool_teams,
            standings,
            tiebreak_order,
            division_name=division_name,
            scoring_policy=scoring_policy,
            three_team_head_to_head=three_team_head_to_head,
        )
        target = ranked[qualifier_rank]

        def published_key(team: SeedableTeam) -> tuple[float, ...]:
            return _tiebreak_values(
                team,
                pool_teams,
                standings,
                tiebreak_order,
                scoring_policy=scoring_policy,
                three_team_head_to_head=three_team_head_to_head,
            )

        tied = [team for team in ranked if published_key(team) == published_key(target)]
        if len(tied) > 1 and scoring_policy == TIGER_TOURNAMENTS_SCORING_POLICY and predict_fn:
            penalty_scores = {team.team_id: 0.0 for team in tied}
            for left_index, left in enumerate(tied):
                for right in tied[left_index + 1 :]:
                    prediction = predict_fn(left, right)
                    left_win = getattr(prediction, "win_probability_a", None)
                    right_win = getattr(prediction, "win_probability_b", None)
                    decisive_total = (
                        float(left_win) + float(right_win)
                        if left_win is not None and right_win is not None
                        else 0.0
                    )
                    if decisive_total > 0:
                        left_share = float(left_win) / decisive_total
                    elif left.power_score != right.power_score:
                        left_share = 1.0 if left.power_score > right.power_score else 0.0
                    else:
                        left_share = 0.5
                    penalty_scores[left.team_id] += left_share
                    penalty_scores[right.team_id] += 1.0 - left_share
            projected_penalty_order = sorted(
                tied,
                key=lambda team: (
                    -penalty_scores[team.team_id],
                    -float(team.power_score),
                    team.team_id,
                ),
            )
            tied_ids = {team.team_id for team in tied}
            ranked = [
                team
                for team in ranked
                if team.team_id not in tied_ids
                or team is projected_penalty_order[0]
            ]
            insertion_index = min(
                index for index, team in enumerate(ranked) if team is projected_penalty_order[0]
            )
            ranked[insertion_index : insertion_index + 1] = projected_penalty_order
            if qualification_tiebreaks is not None:
                qualification_tiebreaks.append(
                    {
                        "qualifier_rank": qualifier_rank + 1,
                        "basis": "published_penalty_kicks_projected_from_pre_event_model",
                        "tied_team_ids": sorted(tied_ids),
                        "projected_order": [team.team_id for team in projected_penalty_order],
                    }
                )
            return ranked
        if len(tied) > 1:
            raise ValueError(
                f"Division '{division_name}' still has a tie for pool rank {qualifier_rank + 1} "
                "after every verified supported tiebreak"
            )
        return ranked
    ranked = sorted(
        pool_teams,
        key=lambda team: (-float(standings[team.team_id]["points"]), team.team_id),
    )
    target_points = standings[ranked[qualifier_rank].team_id]["points"]
    tied = [team for team in ranked if standings[team.team_id]["points"] == target_points]
    if len(tied) > 1:
        source_note = (
            f" Published source: {tiebreak_source_urls[0]}"
            if tiebreak_source_urls
            else ""
        )
        raise ValueError(
            f"Division '{division_name}' produced a tie for pool rank {qualifier_rank + 1}, "
            f"but no verified tournament tiebreak order was captured.{source_note}"
        )
    return ranked


def _winner_and_loser(
    match: SimulatedMatch,
    home_team: SeedableTeam,
    away_team: SeedableTeam,
) -> tuple[SeedableTeam, SeedableTeam]:
    if match.advancing_team_id == home_team.team_id:
        return home_team, away_team
    if match.advancing_team_id == away_team.team_id:
        return away_team, home_team
    raise ValueError(f"Match in division '{match.division_name}' has no valid advancement decision")


def _empty_standings(teams: Sequence[SeedableTeam]) -> dict[str, dict[str, Any]]:
    return {
        team.team_id: {
            "points": 0,
            "gd": 0,
            "gd_capped": 0,
            "gf": 0,
            "gf_capped": 0,
            "ga": 0,
            "wins": 0,
            "draws": 0,
            "losses": 0,
            "head_to_head": {},
        }
        for team in teams
    }


def _simulate_captured_division_schedule(
    division: DivisionAssignment,
    template: DivisionScheduleTemplate,
    predict_fn: PredictionFn,
) -> DivisionSimulation:
    pools = [list(pool.teams) for pool in division.pools]
    all_teams = [team for pool in pools for team in pool]
    standings = _empty_standings(all_teams)
    prior_matches: dict[int, tuple[SimulatedMatch, SeedableTeam, SeedableTeam]] = {}
    simulated_matches: list[SimulatedMatch] = []
    qualification_tiebreaks: list[dict[str, Any]] = []

    def resolve(ref: dict[str, Any]) -> SeedableTeam:
        kind = str(ref["kind"])
        if kind == "division_rank":
            position = int(ref["rank"])
            if position < 0 or position >= len(all_teams):
                raise ValueError(
                    f"Division '{division.name}' captured fixture references a missing "
                    "division standings position"
                )
            ranked = _rank_pool_teams_for_qualifier(
                all_teams,
                standings,
                template.tiebreak_order,
                position,
                division_name=division.name,
                tiebreak_source_urls=template.tiebreak_source_urls,
                scoring_policy=template.scoring_policy,
                three_team_head_to_head=template.three_team_head_to_head,
                predict_fn=predict_fn,
                qualification_tiebreaks=qualification_tiebreaks,
            )
            return ranked[position]
        if kind in {"pool_slot", "pool_rank"}:
            pool_index = int(ref["pool_index"])
            position = int(ref["slot_index"] if kind == "pool_slot" else ref["rank"])
            if pool_index < 0 or pool_index >= len(pools):
                raise ValueError(f"Division '{division.name}' captured fixture references a missing pool")
            candidates = pools[pool_index]
            if position < 0 or position >= len(candidates):
                raise ValueError(f"Division '{division.name}' captured fixture references a missing pool position")
            if kind == "pool_rank":
                candidates = _rank_pool_teams_for_qualifier(
                    candidates,
                    standings,
                    template.tiebreak_order,
                    position,
                    division_name=division.name,
                    tiebreak_source_urls=template.tiebreak_source_urls,
                    scoring_policy=template.scoring_policy,
                    three_team_head_to_head=template.three_team_head_to_head,
                    predict_fn=predict_fn,
                    qualification_tiebreaks=qualification_tiebreaks,
                )
            return candidates[position]
        match_index = int(ref["match_index"])
        if match_index not in prior_matches:
            raise ValueError(
                f"Division '{division.name}' captured fixture references match {match_index + 1} before it was played"
            )
        match, home_team, away_team = prior_matches[match_index]
        winner, loser = _winner_and_loser(match, home_team, away_team)
        if kind == "match_winner":
            return winner
        return loser

    for match_index, slot in enumerate(template.fixture_slots):
        if slot.get("include_in_projection", True) is False:
            continue
        home_team = resolve(dict(slot["home"]))
        away_team = resolve(dict(slot["away"]))
        if home_team.team_id == away_team.team_id:
            raise ValueError(
                f"Division '{division.name}' captured fixture {match_index + 1} resolves both sides to one team"
            )
        match = _simulate_match(
            division_name=division.name,
            stage=str(slot.get("stage") or "Scheduled"),
            pool_name=str(slot.get("pool_name") or "") or None,
            home_team=home_team,
            away_team=away_team,
            predict_fn=predict_fn,
        )
        simulated_matches.append(match)
        prior_matches[match_index] = (match, home_team, away_team)
        if bool(slot.get("counts_for_standings")):
            _update_pool_standings(
                standings,
                match,
                home_team,
                away_team,
                template.scoring_policy,
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
        qualification_tiebreaks=tuple(qualification_tiebreaks),
    )


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
    if template.fixture_slots:
        return _simulate_captured_division_schedule(division, template, predict_fn)

    pool_rankings: list[list[SeedableTeam]] = []
    simulated_matches: list[SimulatedMatch] = []

    for pool in division.pools:
        standings = {
            team.team_id: {
                "points": 0,
                "gd": 0,
                "gd_capped": 0,
                "gf": 0,
                "gf_capped": 0,
                "ga": 0,
                "wins": 0,
                "draws": 0,
                "losses": 0,
                "head_to_head": {},
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
                _update_pool_standings(
                    standings,
                    match,
                    home_team,
                    away_team,
                    template.scoring_policy,
                )

        pool_rankings.append(
            _rank_pool_teams(
                pool_teams,
                standings,
                template.tiebreak_order,
                division_name=division.name,
                scoring_policy=template.scoring_policy,
                three_team_head_to_head=template.three_team_head_to_head,
            )
        )

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

        final_home, third_home = _winner_and_loser(
            semi_a, pool_rankings[0][0], pool_rankings[1][1]
        )
        final_away, third_away = _winner_and_loser(
            semi_b, pool_rankings[1][0], pool_rankings[0][1]
        )
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
