"""Effective-config guard on the SCF staging driver.

_force_scf_env sets the SCF dials in-process (after dotenv load); _assert_effective_config
aborts the run (SystemExit) if a freshly constructed GlickoConfig does not resolve to the
requested dials — the guard against a stray .env.local value winning over the forced one.
These pin the abort contract and the force->assert round-trip without touching the DB/engine.
"""

import pytest

from scripts.run_scf_off_staging import _assert_effective_config, _force_scf_env


def _clear_scf_env(monkeypatch):
    # monkeypatch tracks each var so its teardown removes whatever _force_scf_env adds.
    for key in ("SCF_ENABLED", "SCF_FLOOR", "SCF_DIVERSITY_DIVISOR"):
        monkeypatch.delenv(key, raising=False)


def test_force_then_assert_roundtrip(monkeypatch):
    _clear_scf_env(monkeypatch)
    _force_scf_env("on", 0.65, 4.0)
    # The forced env resolves to exactly the requested dials, so no SystemExit.
    _assert_effective_config("on", 0.65, 4.0)


def test_assert_aborts_on_floor_mismatch(monkeypatch):
    _clear_scf_env(monkeypatch)
    monkeypatch.setenv("SCF_ENABLED", "true")
    monkeypatch.setenv("SCF_FLOOR", "0.4")
    monkeypatch.setenv("SCF_DIVERSITY_DIVISOR", "4.0")
    with pytest.raises(SystemExit):
        _assert_effective_config("on", 0.55, 4.0)


def test_assert_aborts_on_divisor_mismatch(monkeypatch):
    _clear_scf_env(monkeypatch)
    monkeypatch.setenv("SCF_ENABLED", "true")
    monkeypatch.setenv("SCF_FLOOR", "0.6")
    monkeypatch.setenv("SCF_DIVERSITY_DIVISOR", "4.0")
    with pytest.raises(SystemExit):
        _assert_effective_config("on", 0.6, 5.0)


def test_assert_aborts_on_enabled_mismatch(monkeypatch):
    _clear_scf_env(monkeypatch)
    monkeypatch.setenv("SCF_ENABLED", "false")
    with pytest.raises(SystemExit):
        _assert_effective_config("on", 0.4, 4.0)


def test_assert_off_mode_skips_dial_checks(monkeypatch):
    _clear_scf_env(monkeypatch)
    _force_scf_env("off", 0.4, 4.0)
    # off mode asserts only SCF_ENABLED is False; floor/divisor are not constrained.
    _assert_effective_config("off", 0.99, 9.0)
