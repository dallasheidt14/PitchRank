"""Fixed prospective research definitions, independent of model execution or storage."""

from __future__ import annotations

import re
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timedelta, timezone

from src.predictions.form_policy import (
    FORM_CANDIDATES,
    FORM_HALF_LIVES,
    FORM_HISTORY_SIZE,
    FORM_OPPONENT_CAP,
    FORM_RESIDUAL_CLIP,
    PINNED_MODEL_SIGNATURE,
    PINNED_REVISION,
    ResearchPolicy,
)

FORM_STUDY_KIND = "compare_form_study"
FORM_CONFIGURATION = {
    "history_size": FORM_HISTORY_SIZE, "residual_clip": FORM_RESIDUAL_CLIP,
    "calendar_half_lives": list(FORM_HALF_LIVES), "opponent_weight_cap": FORM_OPPONENT_CAP,
    "normalization_and_coefficient": "collecting_predictor_unchanged",
    "missing_expectations": "neutral_and_reduce_usable_sample",
    "capped_shrinkage": "distinct_usable_opponents", "ml_trend_ablation": "development_only",
}
SELECTION = {"primary": "development_log_loss", "tie_breaker": "development_brier", "simplicity": list(FORM_CANDIDATES)}
CONFIRMATION = {
    "weeks": 4, "start": "next_complete_utc_monday_after_registration", "minimum_paired_settled": 1000,
    "minimum_groups": 20, "lower_brier": True, "upper_95_group_bootstrap_log_loss_delta_below_zero": True,
    "complete_risk_outputs": True,
}


def utc_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Study timestamps must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def prospective_policy(registered_at: str) -> ResearchPolicy:
    day = utc_timestamp(registered_at).date()
    start = day + timedelta(days=7 - day.weekday())
    return ResearchPolicy(
        development_start=start.isoformat(), development_end=(start + timedelta(days=27)).isoformat(),
        evaluation_start=(start + timedelta(days=28)).isoformat(),
        evaluation_end=(start + timedelta(days=55)).isoformat(),
    )


def study_definition(registered_at: str, research_sources: dict[str, str]) -> dict:
    policy = prospective_policy(registered_at)
    return deepcopy({
        "schema_version": 1, "kind": FORM_STUDY_KIND, "study_key": "compare-form-" + policy.development_start,
        "predictor_revision": PINNED_REVISION, "baseline_model_signature": PINNED_MODEL_SIGNATURE,
        "policy": asdict(policy), "candidates": list(FORM_CANDIDATES), "form_configuration": FORM_CONFIGURATION,
        "selection": SELECTION, "prospective_confirmation": CONFIRMATION,
        "require_authoritative_inputs": True, "evaluation_sealed_until_end": True,
        "production_promotion": False, "research_sources": research_sources,
    })


def validate_study_definition(definition: dict, *, registered_at: str | None = None) -> ResearchPolicy:
    try:
        policy = ResearchPolicy(**definition["policy"])
        sources = definition["research_sources"]
        if not isinstance(sources, dict) or not sources or any(
            not isinstance(name, str) or not isinstance(sha, str) or not re.fullmatch(r"[a-f0-9]{64}", sha)
            for name, sha in sources.items()
        ):
            raise ValueError("Study requires exact research source hashes")
        reference = registered_at or policy.development_start + "T00:00:00+00:00"
        if registered_at is None:
            reference = (utc_timestamp(reference) - timedelta(days=1)).isoformat()
        if definition != study_definition(reference, sources):
            raise ValueError("Study definition differs from the fixed prospective policy")
        return policy
    except (KeyError, TypeError) as error:
        raise ValueError("Missing or invalid form study definition") from error
