"""Env-backed SCF_ENABLED default on GlickoConfig.

The default_factory reads SCF_ENABLED at construction time, so an unset var must
preserve prod behavior (SCF on) and explicit off-values must disable it. These
cases hold regardless of the truthy-parse idiom; the ambiguous values ("" / "off"
/ typos) are intentionally not pinned here while that idiom is under review.
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
