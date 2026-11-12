"""The historical form policy remains fixed; future studies register separate windows."""

from dataclasses import dataclass

PINNED_REVISION = "866f30c73a84524028b9fe8e55b3108ec8d544fc"
PINNED_MODEL_SIGNATURE = "1718e7be40328a18901f93df30ed31f99581b7b481af71de9277f700462dde05"
FORM_HISTORY_SIZE = 8
FORM_RESIDUAL_CLIP = 4.0
FORM_HALF_LIVES = (30, 60)
FORM_OPPONENT_CAP = 1.0
FORM_CANDIDATES = (
    "baseline", "form_off", "residual_sequence",
    *(f"residual_{days}" for days in FORM_HALF_LIVES),
    *(f"residual_{days}_capped" for days in FORM_HALF_LIVES),
)
INPUT_ROLES = frozenset({
    "team_a_snapshot", "team_b_snapshot", "calibration_margin", "calibration_outcome",
    "calibration_age_groups", "calibration_probability", "calibration_confidence",
})
CALIBRATION_ROLES = {
    "calibration_margin": "margin_parameters_v2.json",
    "calibration_outcome": "heuristic_outcome_calibration.json",
    "calibration_age_groups": "age_group_parameters.json",
    "calibration_probability": "probability_parameters.json",
    "calibration_confidence": "confidence_parameters_v2.json",
}


@dataclass(frozen=True)
class ResearchPolicy:
    development_start: str = "2026-08-17"
    development_end: str = "2026-10-11"
    evaluation_start: str = "2026-10-12"
    evaluation_end: str = "2026-11-08"
    minimum_games: int = 1000
    minimum_groups: int = 20
    seed: int = 20261111
    bootstrap_samples: int = 1000
    predictor_revision: str = PINNED_REVISION
