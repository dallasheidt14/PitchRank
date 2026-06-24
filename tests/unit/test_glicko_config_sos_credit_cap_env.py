"""Env-backed SOS-credit-cap defaults on GlickoConfig (SOS_CREDIT_CAP_ENABLED, SOS_CREDIT_MAX).

Each default_factory reads its env var at construction time, so an unset var must
preserve prod behavior (cap OFF = byte-identical to prod, default allowance) and
explicit overrides must take effect. SOS_CREDIT_CAP_ENABLED defaults OFF so a run with
no env set leaves powerscore_core untouched.
"""

import pytest

from src.etl.glicko_config import GlickoConfig


@pytest.mark.parametrize(
    "value,expected",
    [
        (None, False),  # unset → cap OFF (prod-identical)
        ("true", True),
        ("True", True),
        ("1", True),
        ("yes", True),
        ("false", False),
        ("False", False),
        ("FALSE", False),
        ("0", False),
        ("no", False),
        (" true ", True),  # surrounding whitespace tolerated
    ],
)
def test_sos_credit_cap_enabled_env_parsing(monkeypatch, value, expected):
    if value is None:
        monkeypatch.delenv("SOS_CREDIT_CAP_ENABLED", raising=False)
    else:
        monkeypatch.setenv("SOS_CREDIT_CAP_ENABLED", value)
    assert GlickoConfig().SOS_CREDIT_CAP_ENABLED is expected


@pytest.mark.parametrize(
    "value,expected",
    [
        (None, 0.15),  # unset → default allowance preserved
        ("0.15", 0.15),
        ("0.1", 0.1),
        ("0.2", 0.2),
        ("0.25", 0.25),
    ],
)
def test_sos_credit_max_env_parsing(monkeypatch, value, expected):
    if value is None:
        monkeypatch.delenv("SOS_CREDIT_MAX", raising=False)
    else:
        monkeypatch.setenv("SOS_CREDIT_MAX", value)
    assert GlickoConfig().SOS_CREDIT_MAX == expected
