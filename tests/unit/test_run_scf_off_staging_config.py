"""Effective-config guard on the SCF staging driver.

_force_scf_env sets the SCF dials in-process (after dotenv load); _assert_effective_config
aborts the run (SystemExit) if a freshly constructed GlickoConfig does not resolve to the
requested dials — the guard against a stray .env.local value winning over the forced one.
These pin the abort contract and the force->assert round-trip without touching the DB/engine.
"""

import pytest

from scripts.run_scf_off_staging import _assert_effective_config, _force_scf_env
from src.etl.glicko_config import GlickoConfig


def _clear_scf_env(monkeypatch):
    # monkeypatch tracks each var so its teardown removes whatever _force_scf_env adds.
    for key in (
        "SCF_ENABLED",
        "SCF_FLOOR",
        "SCF_DIVERSITY_DIVISOR",
        "SOS_CREDIT_CAP_ENABLED",
        "SOS_CREDIT_MAX",
        "RECORD_RECONCILE_ENABLED",
        "RECORD_RECONCILE_DOWNPULL_K",
        "RECORD_RECONCILE_BETA",
        "RECORD_RECONCILE_R0",
        "RECORD_RECONCILE_WIN_WEIGHT",
        "RECORD_RECONCILE_GD_WEIGHT",
    ):
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


def test_force_then_assert_sos_credit_cap_roundtrip(monkeypatch):
    _clear_scf_env(monkeypatch)
    _force_scf_env("off", 0.4, 4.0, "on", 0.18)
    # SCF off + cap on at 0.18 resolves to exactly the requested dials, so no SystemExit.
    _assert_effective_config("off", 0.4, 4.0, "on", 0.18)


def test_assert_aborts_on_sos_credit_cap_enabled_mismatch(monkeypatch):
    _clear_scf_env(monkeypatch)
    monkeypatch.setenv("SCF_ENABLED", "false")
    monkeypatch.setenv("SOS_CREDIT_CAP_ENABLED", "false")
    with pytest.raises(SystemExit):
        _assert_effective_config("off", 0.4, 4.0, "on", 0.15)


def test_assert_aborts_on_sos_credit_max_mismatch(monkeypatch):
    _clear_scf_env(monkeypatch)
    monkeypatch.setenv("SCF_ENABLED", "false")
    monkeypatch.setenv("SOS_CREDIT_CAP_ENABLED", "true")
    monkeypatch.setenv("SOS_CREDIT_MAX", "0.15")
    with pytest.raises(SystemExit):
        _assert_effective_config("off", 0.4, 4.0, "on", 0.25)


def test_assert_cap_off_skips_max_check(monkeypatch):
    _clear_scf_env(monkeypatch)
    _force_scf_env("off", 0.4, 4.0, "off", 0.15)
    # cap off asserts only SOS_CREDIT_CAP_ENABLED is False; the max is not constrained.
    _assert_effective_config("off", 0.4, 4.0, "off", 0.99)


def test_force_then_assert_record_reconcile_roundtrip(monkeypatch):
    _clear_scf_env(monkeypatch)
    _force_scf_env("off", 0.4, 4.0, "off", 0.15, "on", 0.7, 0.6, 0.45, 0.65)
    # SCF off + cap off + reconcile on resolves to exactly the requested reconcile dials.
    _assert_effective_config("off", 0.4, 4.0, "off", 0.15, "on", 0.7, 0.6, 0.45, 0.65)


def test_assert_aborts_when_cap_and_reconcile_both_on(monkeypatch):
    _clear_scf_env(monkeypatch)
    # Belt-and-suspenders for the GlickoConfig guard: the harness must refuse a doubly-shaped board.
    with pytest.raises(SystemExit):
        _assert_effective_config("off", 0.4, 4.0, "on", 0.15, "on", 1.0)


def test_assert_aborts_on_record_reconcile_enabled_mismatch(monkeypatch):
    _clear_scf_env(monkeypatch)
    monkeypatch.setenv("SCF_ENABLED", "false")
    monkeypatch.setenv("RECORD_RECONCILE_ENABLED", "false")
    with pytest.raises(SystemExit):
        _assert_effective_config("off", 0.4, 4.0, "off", 0.15, "on", 1.0)


def test_assert_aborts_on_record_downpull_k_mismatch(monkeypatch):
    _clear_scf_env(monkeypatch)
    monkeypatch.setenv("SCF_ENABLED", "false")
    monkeypatch.setenv("RECORD_RECONCILE_ENABLED", "true")
    monkeypatch.setenv("RECORD_RECONCILE_DOWNPULL_K", "1.0")
    with pytest.raises(SystemExit):
        _assert_effective_config("off", 0.4, 4.0, "off", 0.15, "on", 1.5)


def test_assert_reconcile_off_skips_dial_checks(monkeypatch):
    _clear_scf_env(monkeypatch)
    _force_scf_env("off", 0.4, 4.0, "off", 0.15, "off", 9.0)
    # reconcile off asserts only RECORD_RECONCILE_ENABLED is False; the dials are not constrained.
    _assert_effective_config("off", 0.4, 4.0, "off", 0.15, "off", 9.9)


def test_force_pins_non_cli_reconcile_dials_to_defaults(monkeypatch):
    _clear_scf_env(monkeypatch)
    # A stray non-CLI reconcile dial in .env.local must not survive into a swept run: _force_scf_env
    # clears the dials it does not expose so they resolve to GlickoConfig's code defaults, keeping the
    # board and the cache fingerprint deterministic.
    monkeypatch.setenv("RECORD_RECONCILE_WIN_MIDPOINT", "0.99")
    monkeypatch.setenv("RECORD_RECONCILE_MIN_GAMES_FULL", "3")
    _force_scf_env("off", 0.4, 4.0, "off", 0.15, "on", 1.0)
    cfg = GlickoConfig()
    assert cfg.RECORD_RECONCILE_WIN_MIDPOINT == 0.5
    assert cfg.RECORD_RECONCILE_MIN_GAMES_FULL == 12.0
