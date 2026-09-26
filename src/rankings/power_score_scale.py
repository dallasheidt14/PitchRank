"""Versioned final age/gender mapping for published PowerScore.

This module changes only the mapping from ``power_score_true`` to the published
``power_score_final``. It does not participate in Glicko, SOS, ML, evidence
gates, publication caps, or within-cohort rank calculation.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from src.rankings.constants import AGE_TO_ANCHOR

CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "power_score_scales.json"


@dataclass(frozen=True)
class ScaleCurve:
    cap: float
    tail_start_p: float
    tail_start_score: float
    observed_max_p: float
    observed_top_score: float


@dataclass(frozen=True)
class PowerScoreScale:
    version: str
    age_aliases: dict[int, int]
    groups: dict[str, dict[int, ScaleCurve]]
    reference_snapshot: dict[str, Any]

    def canonical_age(self, age: int) -> int:
        return self.age_aliases.get(age, age)

    def curve(self, age: int, gender: str) -> ScaleCurve:
        normalized_gender = _normalize_gender_label(gender)
        canonical_age = self.canonical_age(int(age))
        try:
            return self.groups[normalized_gender][canonical_age]
        except KeyError as error:
            raise ValueError(
                f"Unsupported PowerScore scale cohort: age={age!r}, gender={gender!r}, "
                f"version={self.version!r}"
            ) from error


def _normalize_gender_label(gender: str) -> str:
    value = str(gender).strip().lower()
    if value in {"male", "m", "b", "boy", "boys"}:
        return "Male"
    if value in {"female", "f", "g", "girl", "girls"}:
        return "Female"
    raise ValueError(f"Unsupported PowerScore scale gender: {gender!r}")


def _validate_number(name: str, value: object, *, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be numeric")
    result = float(value)
    if not math.isfinite(result) or not minimum <= result <= maximum:
        raise ValueError(f"{name} must be finite and in [{minimum}, {maximum}]")
    return result


def _validate_curve(version: str, gender: str, age: int, raw: dict[str, object]) -> ScaleCurve:
    cap = _validate_number(f"{version}.{gender}.{age}.cap", raw.get("cap"), minimum=0.0, maximum=1.0)
    tail_start_p = _validate_number(
        f"{version}.{gender}.{age}.tail_start_p", raw.get("tail_start_p"), minimum=0.0, maximum=1.0
    )
    tail_start_score = _validate_number(
        f"{version}.{gender}.{age}.tail_start_score",
        raw.get("tail_start_score"),
        minimum=0.0,
        maximum=1.0,
    )
    observed_max_p = _validate_number(
        f"{version}.{gender}.{age}.observed_max_p", raw.get("observed_max_p"), minimum=0.0, maximum=1.0
    )
    observed_top_score = _validate_number(
        f"{version}.{gender}.{age}.observed_top_score",
        raw.get("observed_top_score"),
        minimum=0.0,
        maximum=1.0,
    )
    expected_tail_score = tail_start_p * AGE_TO_ANCHOR[age]
    if not math.isclose(tail_start_score, expected_tail_score, rel_tol=0.0, abs_tol=1e-12):
        raise ValueError(f"{version}.{gender}.{age} tail start must preserve the legacy age mapping")
    if not 0 < tail_start_p < observed_max_p < 1:
        raise ValueError(f"{version}.{gender}.{age} tail points must be strictly ordered inside (0, 1)")
    if not 0 < tail_start_score < observed_top_score < cap <= 1:
        raise ValueError(f"{version}.{gender}.{age} published landmarks must be strictly increasing")
    return ScaleCurve(
        cap=cap,
        tail_start_p=tail_start_p,
        tail_start_score=tail_start_score,
        observed_max_p=observed_max_p,
        observed_top_score=observed_top_score,
    )


@lru_cache(maxsize=1)
def load_power_score_scales() -> tuple[str, dict[str, PowerScoreScale]]:
    payload = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    active_version = str(payload.get("active_version", "")).strip()
    versions_raw = payload.get("versions")
    if not active_version or not isinstance(versions_raw, dict) or active_version not in versions_raw:
        raise ValueError("PowerScore scale config must name a defined active_version")

    versions: dict[str, PowerScoreScale] = {}
    for version, raw_version in versions_raw.items():
        if not isinstance(raw_version, dict):
            raise ValueError(f"Invalid PowerScore scale version {version!r}")
        aliases_raw = raw_version.get("age_aliases", {})
        if not isinstance(aliases_raw, dict):
            raise ValueError(f"Invalid age_aliases for {version!r}")
        age_aliases = {int(age): int(alias) for age, alias in aliases_raw.items()}

        groups_raw = raw_version.get("groups")
        if not isinstance(groups_raw, dict) or set(groups_raw) != {"Male", "Female"}:
            raise ValueError(f"{version!r} must define separate Male and Female groups")
        groups: dict[str, dict[int, ScaleCurve]] = {}
        for gender, ages_raw in groups_raw.items():
            if not isinstance(ages_raw, dict):
                raise ValueError(f"Invalid {gender} scale for {version!r}")
            groups[gender] = {
                int(age): _validate_curve(version, gender, int(age), curve)
                for age, curve in ages_raw.items()
                if isinstance(curve, dict)
            }
            if set(groups[gender]) != {10, 11, 12, 13, 14, 15, 16, 17, 19}:
                raise ValueError(f"{version!r}.{gender} must define U10-U17 and U19 exactly")

        reference_snapshot = raw_version.get("reference_snapshot", {})
        if not isinstance(reference_snapshot, dict):
            raise ValueError(f"Invalid reference_snapshot for {version!r}")
        versions[version] = PowerScoreScale(
            version=version,
            age_aliases=age_aliases,
            groups=groups,
            reference_snapshot=reference_snapshot,
        )
    return active_version, versions


def active_power_score_scale_version() -> str:
    return load_power_score_scales()[0]


def get_power_score_scale(version: str | None = None) -> PowerScoreScale:
    active_version, versions = load_power_score_scales()
    selected = version or active_version
    try:
        return versions[selected]
    except KeyError as error:
        raise ValueError(f"Unknown PowerScore scale version: {selected!r}") from error


def _map_curve(score: float, age: int, curve: ScaleCurve) -> float:
    if score <= curve.tail_start_p:
        return score * AGE_TO_ANCHOR[age]
    if score <= curve.observed_max_p:
        progress = (score - curve.tail_start_p) / (curve.observed_max_p - curve.tail_start_p)
        return curve.tail_start_score + progress * (curve.observed_top_score - curve.tail_start_score)

    progress = (score - curve.observed_max_p) / (1.0 - curve.observed_max_p)
    return curve.observed_top_score + progress * (curve.cap - curve.observed_top_score)


def published_power_score(power_score_true: float, age: int, gender: str, version: str | None = None) -> float:
    """Map a bounded underlying score onto the versioned published age/gender scale."""
    score = _validate_number("power_score_true", power_score_true, minimum=0.0, maximum=1.0)
    scale = get_power_score_scale(version)
    canonical_age = scale.canonical_age(int(age))
    curve = scale.curve(canonical_age, gender)
    mapped = _map_curve(score, canonical_age, curve)
    if not math.isfinite(mapped) or not 0.0 <= mapped <= curve.cap + 1e-12:
        raise ValueError(
            f"Invalid mapped PowerScore for age={age!r}, gender={gender!r}, version={scale.version!r}: {mapped}"
        )
    return min(mapped, curve.cap)


def prediction_power_score(power_score_true: float, age: int) -> float:
    """Preserve the pre-scale numeric input consumed by prediction features."""
    score = _validate_number("power_score_true", power_score_true, minimum=0.0, maximum=1.0)
    try:
        anchor = AGE_TO_ANCHOR[int(age)]
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError(f"Unsupported prediction PowerScore age: {age!r}") from error
    return min(score * anchor, anchor)


def published_power_score_cap(age: int, gender: str, version: str | None = None) -> float:
    return get_power_score_scale(version).curve(age, gender).cap
