"""Env-backed SCF defaults on GlickoConfig (SCF_ENABLED, SCF_FLOOR, SCF_DIVERSITY_DIVISOR).

Each default_factory reads its env var at construction time, so an unset var must
preserve prod behavior (SCF on, floor 0.4, divisor 4.0) and explicit overrides must
take effect. For SCF_ENABLED these cases hold regardless of the truthy-parse idiom;
the ambiguous values ("" / "off" / typos) are intentionally not pinned here while
that idiom is under review.
"""

import pytest

from src.etl.glicko_config import GlickoConfig


@pytest.mark.parametrize(
    "value,expected",
    [
        (None, True),  # unset → SCF on (prod default preserved)
        ("true", True),
        ("True", True),
        ("1", True),
        ("yes", True),
        ("false", False),
        ("False", False),
        ("FALSE", False),
        ("0", False),
        ("no", False),
        (" false ", False),  # surrounding whitespace tolerated
    ],
)
def test_scf_enabled_env_parsing(monkeypatch, value, expected):
    if value is None:
        monkeypatch.delenv("SCF_ENABLED", raising=False)
    else:
        monkeypatch.setenv("SCF_ENABLED", value)
    assert GlickoConfig().SCF_ENABLED is expected


@pytest.mark.parametrize(
    "value,expected",
    [
        (None, 0.4),  # unset → prod floor preserved
        ("0.4", 0.4),
        ("0.55", 0.55),
        ("0.6", 0.6),
        ("0.7", 0.7),
    ],
)
def test_scf_floor_env_parsing(monkeypatch, value, expected):
    if value is None:
        monkeypatch.delenv("SCF_FLOOR", raising=False)
    else:
        monkeypatch.setenv("SCF_FLOOR", value)
    assert GlickoConfig().SCF_FLOOR == expected


@pytest.mark.parametrize(
    "value,expected",
    [
        (None, 4.0),  # unset → prod divisor preserved
        ("4.0", 4.0),
        ("5.0", 5.0),
        ("6.5", 6.5),
    ],
)
def test_scf_diversity_divisor_env_parsing(monkeypatch, value, expected):
    if value is None:
        monkeypatch.delenv("SCF_DIVERSITY_DIVISOR", raising=False)
    else:
        monkeypatch.setenv("SCF_DIVERSITY_DIVISOR", value)
    assert GlickoConfig().SCF_DIVERSITY_DIVISOR == expected
