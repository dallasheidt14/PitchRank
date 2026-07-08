"""Env-backed record-reconciliation defaults on GlickoConfig, plus the fail-closed
mutual-exclusion guard against stacking the old SOS-credit cap with the new reconciliation.

Each default_factory reads its env var at construction time, so an unset var must preserve
prod behavior (reconciliation OFF = byte-identical to prod) and explicit overrides must take
effect. RECORD_RECONCILE_ENABLED defaults OFF so a run with no env set leaves powerscore_core
untouched. __post_init__ raises when both shaping flags resolve on, so no run can produce a
doubly-shaped board that masquerades as a clean down-side test.
"""

import pytest

from src.etl.glicko_config import GlickoConfig


@pytest.mark.parametrize(
    "value,expected",
    [
        (None, False),  # unset → reconciliation OFF (prod-identical)
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
def test_record_reconcile_enabled_env_parsing(monkeypatch, value, expected):
    monkeypatch.delenv("SOS_CREDIT_CAP_ENABLED", raising=False)
    if value is None:
        monkeypatch.delenv("RECORD_RECONCILE_ENABLED", raising=False)
    else:
        monkeypatch.setenv("RECORD_RECONCILE_ENABLED", value)
    assert GlickoConfig().RECORD_RECONCILE_ENABLED is expected


@pytest.mark.parametrize(
    "var,default,override,expected",
    [
        ("RECORD_RECONCILE_DOWNPULL_K", 1.0, "1.5", 1.5),
        ("RECORD_RECONCILE_BETA", 0.8, "0.6", 0.6),
        ("RECORD_RECONCILE_R0", 0.5, "0.45", 0.45),
        ("RECORD_RECONCILE_WIN_WEIGHT", 0.7, "0.65", 0.65),
        ("RECORD_RECONCILE_GD_WEIGHT", 0.3, "0.35", 0.35),
        ("RECORD_RECONCILE_GD_CLAMP", 3.0, "2.5", 2.5),
        ("RECORD_RECONCILE_MIN_GAMES_FULL", 12.0, "9", 9.0),
    ],
)
def test_record_reconcile_float_env_parsing(monkeypatch, var, default, override, expected):
    monkeypatch.delenv("SOS_CREDIT_CAP_ENABLED", raising=False)
    monkeypatch.delenv(var, raising=False)
    assert getattr(GlickoConfig(), var) == default
    monkeypatch.setenv(var, override)
    assert getattr(GlickoConfig(), var) == expected


def test_config_raises_when_cap_and_reconcile_both_enabled(monkeypatch):
    monkeypatch.setenv("SOS_CREDIT_CAP_ENABLED", "true")
    monkeypatch.setenv("RECORD_RECONCILE_ENABLED", "true")
    with pytest.raises(ValueError):
        GlickoConfig()


def test_config_allows_reconcile_alone(monkeypatch):
    monkeypatch.delenv("SOS_CREDIT_CAP_ENABLED", raising=False)
    monkeypatch.setenv("RECORD_RECONCILE_ENABLED", "true")
    assert GlickoConfig().RECORD_RECONCILE_ENABLED is True
