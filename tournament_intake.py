"""MatchBalance · Backtest Intake — Streamlit triage app.

Sibling Streamlit app to ``dashboard.py``. Stands up the cohort-intake
triage surface for a tournament event: scrape new event URLs, resume
existing events from ``reports/``, and view per-cohort readiness for
backtest runs.
"""

from __future__ import annotations

import contextlib
import html
import json
import logging
import os
import re
import sys
import uuid
from collections.abc import Callable, Iterator, Mapping
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from config.settings import (
    PROJECT_NAME,
    SUPABASE_SERVICE_ROLE_KEY,
    SUPABASE_URL,
    VERSION,
)
from scripts.backtest_tournament_event import _derive_pool_sizes
from src.scrapers.gotsport import EventCaptchaGatedError
from src.scrapers.provider import (
    UnsupportedProviderError,
    get_provider_scraper,
)
from src.tournaments.division_render import render_division_container
from src.tournaments.event_team_matcher import (
    EventTeamSearchQuery,
    enrich_registry_rows_with_matcher,
    search_event_team_in_db,
)
from src.tournaments.reports import (
    ReportCardError,
    render_html,
)
from src.tournaments.reports.ui import (
    derive_export_filenames,
    ensure_report_card,
    format_run_label,
    format_run_timestamp,
    project_audit_row,
    safe_read_comparison_json,
    zip_run_csvs,
)
from src.tournaments.bracket_report import (
    KnockoutMatch,
    PoolTable,
    TierReport,
    build_tier_reports,
)
from src.tournaments.storage.game_results import read_game_results
from src.tournaments.run_orchestrator import (
    ProgressEvent,
    execute_run,
    override_in_cohort,
    preflight,
)
from src.tournaments.seeding_optimizer import (
    normalize_age_group,
    normalize_gender_label,
)
from src.utils.team_name_utils import US_STATES
from src.tournaments.storage import (
    CohortConstraints,
    CohortStructure,
    DivisionStructure,
    EventMetadata,
    RegistryPersistResult,
    RunLockError,
    RunStateError,
    ScenarioLockError,
    SchemaVersionError,
    TeamRegistryEntry,
    acquire_scenario_lock,
    append_override,
    build_registry_entries,
    check_games_import_status,
    check_local_results_coverage,
    compute_frozen_medians,
    derive_structure_from_raw_scrape,
    ensure_scenario,
    event_key,
    intake_dir,
    list_runs,
    list_scenarios,
    load_overrides,
    load_raw_scrape,
    parse_event_key,
    persist_registry_for_scenario,
    read_constraints,
    read_event_metadata,
    read_frozen_medians,
    read_registry,
    read_structure,
    rekey_unknown_directories,
    reports_dir,
    write_constraints,
    write_event_metadata,
    write_frozen_medians,
    write_structure,
)
from src.tournaments.storage import (
    run_dir as _run_dir,
)
from src.tournaments.storage._io import read_json, utc_now_iso
from src.tournaments.triage import (
    _STRENGTH_MODES,
    SOURCE_EXPLICIT,
    SOURCE_PREFIX,
    SOURCE_STALE,
    ProjectedTeamState,
    _classify_team_state,
    _is_placeholder_team,
    _is_play_up,
    build_override_record,
    project_overrides,
    registry_provider_id,
    resolve_division_assignment,
)
from supabase import create_client

logger = logging.getLogger(__name__)

# Page configuration
st.set_page_config(
    page_title="MatchBalance · Backtest Intake",
    page_icon="⚽",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# Title and version
st.title("⚽ MatchBalance · Backtest Intake")
st.caption(f"Version {VERSION} | Powered by {PROJECT_NAME}")


# Disabled-mode contract — pinned by tests against silent re-enablement.
_DISABLED_MODES: tuple[str, ...] = ("seeding",)

# Sentinel option for the per-row Assign division selectbox: forces the
# operator to pick a real division when the resolver has no signal
# (``source="none"``) before any override is written.
_DIV_ASSIGN_SENTINEL = "— pick to confirm —"


# Database connection helper
@st.cache_resource
def get_database():
    """Get cached database connection"""
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        return None
    try:
        return create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
    except Exception as e:
        st.error(f"Failed to connect to database: {e}")
        return None


def _resolve_intake_mode(requested: str) -> str:
    """Coerce a requested intake mode to a shipped one.

    Seeding mode is reserved for a later shell; requests for it fall back
    to backtest. Pinned by ``test_tournament_intake_helpers`` so a future
    refactor can't silently re-enable seeding.
    """
    if requested in _DISABLED_MODES:
        return "backtest"
    return requested


def _display_gender(canonical: str) -> str:
    """Translate canonical optimizer vocabulary to layout-v4 display labels.

    Storage and the seeding optimizer keep canonical "Male"/"Female"; the UI
    edge surfaces "Boys"/"Girls" to match the mockup.
    """
    if canonical == "Male":
        return "Boys"
    if canonical == "Female":
        return "Girls"
    return canonical


@st.cache_data(ttl=10)
def _resume_options() -> list[tuple[str, str]]:
    """Scan ``reports/`` for resumable events and return ``[(label, event_key)]``.

    Filters dirs whose name parses via ``parse_event_key`` and whose
    ``intake/event_metadata.json`` round-trips. Unreadable entries are
    dropped silently. Cached briefly so the dropdown stays responsive
    without masking newly scraped events.
    """
    root = reports_dir()
    if not root.exists():
        return []
    options: list[tuple[str, str]] = []
    for entry in sorted(root.iterdir()):
        if not entry.is_dir():
            continue
        try:
            parse_event_key(entry.name)
        except ValueError:
            continue
        try:
            meta = read_event_metadata(entry.name)
        except (FileNotFoundError, SchemaVersionError):
            continue
        season = meta.season_year if meta.season_year is not None else "unknown"
        label = f"{meta.event_name} ({season})"
        options.append((label, entry.name))
    return options


def _scrape_lock_path(key: str) -> Path:
    """Return the cross-tab scrape advisory-lock path for an event_key.

    Routes through ``intake_dir`` so the storage layer's ``_validate_segment``
    runs centrally (defense-in-depth against a caller passing an unvalidated
    key).
    """
    return intake_dir(key) / ".scrape.lock"


def _build_platform_lock_pair() -> tuple[Callable[[int], None], Callable[[int], None]]:
    """Build ``(lock_fn, unlock_fn)`` for the current platform.

    Mirrors ``src.tournaments.storage.scenario._build_platform_lock_pair``;
    duplicated here to keep the cross-tab scrape lock independent of the
    per-scenario lock semantics (different lockfile, different acquire
    contract).
    """
    if sys.platform == "win32":
        import msvcrt

        def lock_fn(fd: int) -> None:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)

        def unlock_fn(fd: int) -> None:
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        def lock_fn(fd: int) -> None:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

        def unlock_fn(fd: int) -> None:
            fcntl.flock(fd, fcntl.LOCK_UN)

    return lock_fn, unlock_fn


_LOCK_FN, _UNLOCK_FN = _build_platform_lock_pair()


class _ScrapeLockContended(RuntimeError):
    """Raised when ``_acquire_scrape_lock`` finds another tab already scraping."""


@contextlib.contextmanager
def _acquire_scrape_lock(key: str) -> Iterator[None]:
    """Acquire the per-event cross-tab scrape lock at ``intake/.scrape.lock``.

    Single-attempt non-blocking acquire — contention raises
    ``_ScrapeLockContended``. The lockfile is purely a presence/lock
    primitive; never read or written for state (matches the no-IO contract
    in ``storage/scenario.py``).
    """
    lock_path = _scrape_lock_path(key)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR)
    locked = False
    try:
        try:
            _LOCK_FN(fd)
        except (BlockingIOError, OSError) as exc:
            raise _ScrapeLockContended(f"scrape already running for {key}: {exc}") from exc
        locked = True
        yield
    finally:
        if locked:
            try:
                _UNLOCK_FN(fd)
            except OSError:
                pass
        try:
            os.close(fd)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Cohort tint + grouping helpers
# ---------------------------------------------------------------------------


@st.cache_data(ttl=60)
def _check_games_import_cached(
    event_name: str,
    team_ids: frozenset[str],
    _supabase: Any,
) -> str:
    """``check_games_import_status`` wrapper with a hashable cache key.

    The leading underscore on ``_supabase`` tells ``st.cache_data`` not to
    hash the client. ``team_ids`` is a frozenset so cache keys are stable
    across reruns.
    """
    return check_games_import_status(event_name, list(team_ids), supabase_client=_supabase)


def _scrape_state_counts(records: list[dict[str, Any]]) -> dict[str, int]:
    """Single-pass tally of ``canonical.scraper_state`` across records."""
    counts = {"alias_written": 0, "review_queued": 0, "unresolved": 0}
    for rec in records:
        state = (rec.get("canonical") or {}).get("scraper_state") or "unresolved"
        counts[state] = counts.get(state, 0) + 1
    return counts


def _scraper_tint(records: list[dict[str, Any]]) -> tuple[str, str]:
    """Map a cohort's records to ``(level, note)`` from ``scraper_state`` alone.

    ``level`` is one of ``"green" / "amber" / "red"``. ``note`` is the
    layout-v4 short status string ("ready" / "X review" / "X ext").
    """
    counts = _scrape_state_counts(records)
    n_unresolved = counts["unresolved"]
    n_review = counts["review_queued"]
    total = sum(counts.values())
    if n_unresolved >= max(1, total // 2):
        return "red", "mostly ext"
    if n_unresolved:
        return "red", f"{n_unresolved} ext"
    if n_review:
        return "amber", f"{n_review} review"
    return "green", "ready"


def _cohort_tint(
    records: list[dict[str, Any]],
    *,
    event_name: str,
    supabase_client: Any,
    event_key_value: str | None = None,
) -> tuple[str, str]:
    """Combine the ``scraper_state`` tint with the games-coverage override.

    Backtest mode reads ``intake/game_results.jsonl`` (scraped directly
    from gotsport schedule pages by ``enrich_event_with_schedule``), so
    coverage status is a local file check — no Supabase round-trip.

    Override rules:
    - ``not_imported`` → red "games gap".
    - ``partial`` → amber "games gap" (downgrade green; preserve red note).
    - ``complete`` → keep the scraper_state-derived tint.
    """
    base_level, base_note = _scraper_tint(records)
    if event_key_value is None:
        return base_level, base_note
    provider_team_ids = frozenset(
        str(rec.get("provider_team_id") or "")
        for rec in records
        if rec.get("provider_team_id")
    )
    if not provider_team_ids:
        return base_level, base_note
    try:
        games_state = _cached_local_coverage(event_key_value, tuple(sorted(provider_team_ids)))
    except Exception:  # noqa: BLE001 — file-read failure shouldn't crash the page
        return base_level, base_note
    if games_state == "not_imported":
        return "red", "games gap"
    if games_state == "partial":
        if base_level == "red":
            return base_level, base_note
        return "amber", "games gap"
    return base_level, base_note


_TINT_BG = {"green": "#f0fdf4", "amber": "#fffbeb", "red": "#fef2f2"}
_TINT_BORDER = {"green": "#bbf7d0", "amber": "#fde68a", "red": "#fecaca"}
_TINT_TEXT = {"green": "#16a34a", "amber": "#d97706", "red": "#dc2626"}
_TINT_DOT = {"green": "🟢", "amber": "🟡", "red": "🔴"}


def _cohort_toggle_key(age: str, gender: str) -> str:
    """Return the per-cohort expansion session-state key.

    Single source of truth so the summary-strip highlight check and the
    cohort-container toggle render bind to the same key.
    """
    return f"_cohort_expanded_{age}_{gender}"


def _cohort_sort_key(cohort: tuple[str, str]) -> tuple[int, str]:
    """Sort ``(age, gender)`` cohorts oldest → youngest, female before male."""
    age, gender = cohort
    age_n = int(age.removeprefix("u")) if age.startswith("u") else 0
    return (-age_n, gender)


def _group_cohorts(
    records: list[dict[str, Any]],
) -> dict[tuple[str, str], list[dict[str, Any]]]:
    """Group records by ``(normalized_age, normalized_gender)`` cohort."""
    cohorts: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for rec in records:
        age_raw = rec.get("cohort_age_group") or ""
        gender_raw = rec.get("cohort_gender") or ""
        try:
            age = normalize_age_group(age_raw)
        except ValueError:
            continue
        gender = normalize_gender_label(gender_raw)
        cohorts.setdefault((age, gender), []).append(rec)
    return cohorts


# ---------------------------------------------------------------------------
# Structure-input validation (Shell 05)
# ---------------------------------------------------------------------------


_V1_KNOCKOUT_TEMPLATES: tuple[str, ...] = ("ROUND_ROBIN", "F_ONLY", "SF_F", "SF_F_3P")
_V2_KNOCKOUT_TEMPLATES: tuple[str, ...] = ("QF_SF_F", "QF_SF_F_3P", "CROSSOVER_F", "CUSTOM")
_ALL_KNOCKOUT_TEMPLATES: tuple[str, ...] = _V1_KNOCKOUT_TEMPLATES + _V2_KNOCKOUT_TEMPLATES

# (extra_games_after_round_robin, allowed_pool_counts) — list of allowed
# pairs per template. ``F_ONLY`` accepts BOTH ``pool_winners_final`` (2
# pools, 1 extra) AND ``one_pool_final`` (1 pool, 1 extra).
# ``ROUND_ROBIN`` accepts any pool count with zero extras (``allowed_pool_counts``
# of ``None`` means "any pool count").
_KNOCKOUT_VALIDATION: dict[str, list[tuple[int, frozenset[int] | None]]] = {
    "ROUND_ROBIN": [(0, None)],
    "F_ONLY": [(1, frozenset({2})), (1, frozenset({1}))],
    "SF_F": [(3, frozenset({2}))],
    "SF_F_3P": [(4, frozenset({2}))],
}

_KNOCKOUT_LABELS: dict[str, str] = {
    "ROUND_ROBIN": "Round robin only",
    "F_ONLY": "Final only",
    "SF_F": "SF → F",
    "SF_F_3P": "SF → F + 3rd place",
    "QF_SF_F": "QF → SF → F",
    "QF_SF_F_3P": "QF → SF → F + 3rd place",
    "CROSSOVER_F": "Crossover → Final",
    "CUSTOM": "Custom",
}

_REMATCH_SCOPES: tuple[str, ...] = ("same_event", "same_season", "prior_weekend")


def _knockout_format_label(template: str) -> str:
    """Streamlit ``format_func`` label — appends a v2 marker for unbuilt templates."""
    base = _KNOCKOUT_LABELS.get(template, template)
    if template in _V2_KNOCKOUT_TEMPLATES:
        return f"{base} — coming in v2"
    return base


def _validate_knockout_format(template: str, pool_sizes: tuple[int, ...]) -> str | None:
    """Return ``None`` when the template fits the pool structure, else an error string.

    v2 templates always fail with a "coming in v2" message. For v1 templates,
    the ``_KNOCKOUT_VALIDATION`` table lists allowed ``(extra_games,
    allowed_pool_counts)`` pairs; the function returns ``None`` as soon as the
    operator's ``pool_count`` matches one. Run the simulator-parity test
    (``tests/unit/test_structure_validation.py``) to keep this table aligned
    with ``infer_division_schedule_template``.
    """
    if template in _V2_KNOCKOUT_TEMPLATES:
        return f"'{template}' is a v2 template; pick a v1 template or wait for v2."
    rules = _KNOCKOUT_VALIDATION.get(template)
    if rules is None:
        return f"'{template}' is not a recognized knockout template."
    pool_count = len(pool_sizes)
    allowed_counts: set[int] = set()
    for _extras, allowed_pools in rules:
        if allowed_pools is None:
            return None
        if pool_count in allowed_pools:
            return None
        allowed_counts.update(allowed_pools)
    return f"'{template}' requires pool count in {sorted(allowed_counts)}; got {pool_count} pools."


def _default_snapshot(event_start_date: str | None) -> date:
    """Default ``ranking_snapshot_date`` is the day before kickoff (or today)."""
    if event_start_date:
        try:
            return date.fromisoformat(event_start_date) - timedelta(days=1)
        except ValueError:
            pass
    return date.today()


# ---------------------------------------------------------------------------
# Render flow
# ---------------------------------------------------------------------------


def _init_session_state() -> None:
    """Lazy-initialize page-level session state keys."""
    if "event_key" not in st.session_state:
        st.session_state.event_key = None
    if "scenario_name" not in st.session_state:
        st.session_state.scenario_name = "default"
    if "intake_mode" not in st.session_state:
        st.session_state.intake_mode = "backtest"
    if "_scrape_in_progress" not in st.session_state:
        st.session_state._scrape_in_progress = False
    if "current_run_id_by_cohort" not in st.session_state:
        st.session_state.current_run_id_by_cohort = {}
    st.session_state.setdefault("_reviewer_email", "")


def _render_rekey_banner() -> None:
    """Run ``rekey_unknown_directories`` once per session and surface results."""
    if st.session_state.get("_rekey_done"):
        return
    st.session_state._rekey_done = True
    result = rekey_unknown_directories()
    if result.completed:
        st.success(f"Migrated {len(result.completed)} event(s) to season-stamped keys.")
    if result.failed:
        items = ", ".join(f"{k} ({why})" for k, why in result.failed)
        st.warning(f"{len(result.failed)} event(s) need manual season_year fix: {items}")
    if result.unmigrated:
        items = ", ".join(result.unmigrated)
        st.warning(f"{len(result.unmigrated)} event(s) pending metadata (no event_metadata.json yet): {items}")


def _render_intake_section(supabase_client: Any) -> None:
    """Render the top Intake card (3-column control row)."""
    st.markdown("### Intake")
    in_progress = st.session_state._scrape_in_progress
    c1, c2, c3 = st.columns([2, 2, 1])

    with c1:
        st.text_input(
            "Scrape new event URL",
            key="scrape_url",
            placeholder="https://system.gotsport.com/org_event/events/45224",
            disabled=in_progress,
        )
        scrape_clicked = st.button(
            "Scrape",
            type="primary",
            disabled=(not st.session_state.get("scrape_url")) or in_progress,
        )

    with c2:
        options = _resume_options()
        if options:
            keys = [k for _, k in options]
            label_by_key = {k: label for label, k in options}
            current_key = st.session_state.event_key
            current_index = keys.index(current_key) if current_key in label_by_key else None
            selected_key = st.selectbox(
                "Resume existing",
                options=keys,
                index=current_index,
                format_func=lambda k: label_by_key.get(k, k),
                placeholder="Select an event...",
                disabled=in_progress,
                key="resume_choice",
            )
            if selected_key is not None and selected_key != st.session_state.event_key:
                st.session_state.event_key = selected_key
                st.rerun()
        else:
            st.selectbox(
                "Resume existing",
                options=[],
                placeholder="(no events available)",
                disabled=True,
                key="resume_choice",
            )

    with c3:
        requested = st.radio(
            "Mode",
            options=["backtest", "seeding"],
            index=0,
            horizontal=True,
            help="Seeding mode coming later",
            disabled=in_progress,
            key="intake_mode_widget",
        )
        st.caption("🚧 seeding coming in a later shell")
        resolved = _resolve_intake_mode(requested or "backtest")
        if resolved != requested:
            st.warning("Seeding mode is not yet available — staying on backtest.")
        st.session_state.intake_mode = resolved

    if scrape_clicked:
        _run_scrape(st.session_state.scrape_url, supabase_client)


def _show_captcha_error(exc: EventCaptchaGatedError) -> None:
    """Surface CAPTCHA gate details to the operator."""
    st.error(
        f"Event is CAPTCHA-gated. Solve at {exc.captcha_url} "
        f"(sitekey={exc.sitekey or '?'}); artifact saved at {exc.artifact_path}."
    )


def _persist_registry_after_scrape(
    event_key_value: str,
    scenario_active: str,
    supabase_client: Any,
    *,
    base_dir: Path | str = "reports",
) -> list[RegistryPersistResult]:
    """Translate the just-written ``intake/raw_scrape.jsonl`` into per-scenario
    ``event_team_registry.csv`` files.

    Sourcing the registry from the journal (rather than from the scraper's
    return value) keeps the ``ProviderScraper`` ABC scenario-blind. The
    journal is fully compacted by the time this runs — ``journal.compact()``
    fires synchronously inside ``fetch_teams_by_cohort`` and inside the
    event-tier ``_acquire_scrape_lock``, before this helper is invoked.

    The matcher cache lives in this single ``enrich_registry_rows_with_matcher``
    call; the per-scenario fan-out below operates on already-enriched
    entries. Threading the cache into the per-scenario loop would re-run the
    matcher per scenario for no benefit (per memory
    ``gotcha_matcher_cache_load_bearing.md``).

    Returns one ``RegistryPersistResult`` per scenario; the caller (the
    Streamlit ``_run_scrape``) renders them via
    ``_render_registry_persist_results`` after ``st.rerun()``.
    """
    journal_records = load_raw_scrape(event_key_value, base_dir=base_dir)
    fresh_entries = build_registry_entries(journal_records)
    # Backtest mode: the past tournament's bracket layout is recoverable
    # from the journal itself, so the operator should not have to author
    # group_structure_summary.csv by hand. We derive it once (with pool
    # sizes if pool_assignments.json was written by the enricher) and
    # write per-scenario inside the existing lock — but only when the
    # file is absent, to preserve operator edits in forward-looking
    # scenarios.
    from src.tournaments.storage.pool_assignments import read_pool_assignments

    pools_by_group = read_pool_assignments(event_key_value, base_dir=base_dir)
    derived_structure = derive_structure_from_raw_scrape(
        journal_records, pools_by_group_id=pools_by_group
    )

    if supabase_client is None:
        logger.warning(
            "supabase_client is None; persisting registry without matcher enrichment "
            "(every matcher_* column will be '')"
        )
        enriched_entries: list[TeamRegistryEntry] = fresh_entries
    else:
        matcher_cache: dict[tuple[tuple[str, ...], str, bool], list[dict[str, Any]]] = {}
        enriched_rows, _status_counts = enrich_registry_rows_with_matcher(
            supabase_client,
            [e.to_row() for e in fresh_entries],
            cache=matcher_cache,
        )
        enriched_entries = [TeamRegistryEntry.from_row(r) for r in enriched_rows]

    scenarios = list_scenarios(event_key_value, base_dir=base_dir)
    if not scenarios:
        raise RuntimeError(
            f"ensure_scenario must precede _persist_registry_after_scrape; "
            f"got empty scenario list for event_key={event_key_value!r} "
            f"(active={scenario_active!r})"
        )

    results: list[RegistryPersistResult] = []
    for scenario in scenarios:
        try:
            with acquire_scenario_lock(event_key_value, scenario, base_dir=base_dir, timeout=2.0):
                results.append(
                    persist_registry_for_scenario(event_key_value, scenario, enriched_entries, base_dir=base_dir)
                )
                structure_csv = (
                    Path(base_dir)
                    / event_key_value
                    / "scenarios"
                    / scenario
                    / "group_structure_summary.csv"
                )
                if not structure_csv.exists() and derived_structure:
                    write_structure(event_key_value, scenario, derived_structure, base_dir=base_dir)
        except ScenarioLockError:
            results.append(
                RegistryPersistResult(
                    scenario=scenario,
                    written=False,
                    row_count=0,
                    dropped_pids=[],
                    lock_contention=True,
                    error="locked by another tab",
                )
            )
        except Exception as exc:  # noqa: BLE001 — partial-success contract
            logger.exception("persist_registry_for_scenario failed for scenario=%s", scenario)
            results.append(
                RegistryPersistResult(
                    scenario=scenario,
                    written=False,
                    row_count=0,
                    dropped_pids=[],
                    lock_contention=False,
                    error=str(exc),
                )
            )
    return results


def _render_registry_persist_results() -> None:
    """Surface per-scenario registry-persistence outcomes after ``st.rerun()``.

    ``_run_scrape`` stashes the result list on ``st.session_state`` BEFORE
    calling ``st.rerun()`` because Streamlit discards transient widgets
    (``st.error`` / ``st.warning`` / ``st.info``) on the next script run.
    The renderer dispatches on ``lock_contention: bool`` (NOT on the ``error``
    string contents) — the dataclass discriminator is the contract.

    Clears the session-state slot after rendering so messages don't re-render
    on every subsequent rerun.
    """
    results: list[RegistryPersistResult] = st.session_state.get("_last_registry_persist_results", [])
    if not results:
        return
    for r in results:
        if r.written:
            suffix = f" (dropped {len(r.dropped_pids)} orphan pid(s))" if r.dropped_pids else ""
            st.info(f"Registry written for scenario '{r.scenario}': {r.row_count} rows{suffix}")
        elif r.lock_contention:
            st.warning(f"Scenario '{r.scenario}' was locked by another tab — registry not refreshed for that scenario.")
        else:
            st.error(
                f"Scenario '{r.scenario}' failed to persist registry: {r.error}. "
                f"Click Scrape to retry — the registry is regenerable."
            )
    st.session_state.pop("_last_registry_persist_results", None)


def _run_scrape(url: str, supabase_client: Any) -> None:
    """Wire the Scrape button to ``get_provider_scraper(...)`` in-process."""
    try:
        scraper = get_provider_scraper(url, supabase_client)
    except UnsupportedProviderError as exc:
        st.error(f"Unsupported provider URL: {exc}")
        return

    try:
        with st.spinner("Fetching event metadata..."):
            meta = scraper.fetch_event_metadata(url)
    except EventCaptchaGatedError as exc:
        _show_captcha_error(exc)
        return

    key = event_key(meta.provider_code, meta.provider_event_id, meta.season_year)
    ensure_scenario(key, st.session_state.scenario_name)
    # Preserve an existing operator-set / non-fallback event_name across
    # rescrapes. Gotsport's org_event landing page doesn't expose the real
    # tournament name in <title> or <h1>, so fetch_event_metadata falls back
    # to "Event {id}". Without this guard, every rescrape would silently
    # rewrite "SC Del Sol Presidents Day Tournament" → "Event 42433" and
    # break the games-import-status lookup that joins on event_name.
    fallback_name = f"Event {meta.provider_event_id}"
    if meta.event_name == fallback_name:
        try:
            existing = read_event_metadata(key)
            if existing.event_name and existing.event_name != fallback_name:
                meta = replace(meta, event_name=existing.event_name)
        except (FileNotFoundError, SchemaVersionError):
            pass
    write_event_metadata(key, meta)

    try:
        with _acquire_scrape_lock(key):
            st.session_state._scrape_in_progress = True
            try:
                with st.spinner("Scraping cohorts (this may take 1-3 min)..."):
                    scraper.fetch_teams_by_cohort(url)
                with st.spinner("Capturing schedule (pools + games + standings)..."):
                    # Best-effort schedule enrichment — runs BEFORE registry
                    # persistence so derive_structure_from_raw_scrape can
                    # populate pool_sizes on the first write. Single fetch
                    # pass per tier produces three artifacts:
                    # pool_assignments.json, game_results.jsonl,
                    # standings.jsonl. Failure here logs but does not
                    # block: backtest still works at bracket level even
                    # with empty pool_sizes / game_results.
                    try:
                        from src.scrapers.gotsport_pool_enricher import enrich_event_with_schedule

                        enrich_event_with_schedule(
                            key,
                            load_raw_scrape(key),
                            fetcher=lambda gid: scraper.fetch_schedule_html(meta.provider_event_id, gid),
                        )
                    except Exception:  # noqa: BLE001
                        logger.exception("schedule enrichment failed; backtest will lack pool/game data")
                with st.spinner("Persisting team registry..."):
                    persist_results = _persist_registry_after_scrape(
                        key, st.session_state.scenario_name, supabase_client
                    )
                    st.session_state._last_registry_persist_results = persist_results
            finally:
                st.session_state._scrape_in_progress = False
    except _ScrapeLockContended:
        st.error("This event is already being scraped in another tab — wait for it to finish and reload.")
        return
    except EventCaptchaGatedError as exc:
        _show_captcha_error(exc)
        return

    st.session_state.event_key = key
    _resume_options.clear()
    st.rerun()


_COHORT_LABEL_RE = re.compile(r"^U(\d+)\s+(Boys|Girls)\b", re.IGNORECASE)


def _summarize_played_games(games: list[Any]) -> dict[str, int | float | None]:
    """Aggregate played games into ``games / goals / avg_margin`` totals.

    Skips games with either score ``None`` (unplayed). Returns ``None``
    for ``avg_margin`` when the played-games count is zero so the caller
    can render a placeholder.
    """
    played = [g for g in games if g.home_score is not None and g.away_score is not None]
    if not played:
        return {"games": 0, "goals": 0, "avg_margin": None}
    goals = sum((g.home_score or 0) + (g.away_score or 0) for g in played)
    margin = sum(abs((g.home_score or 0) - (g.away_score or 0)) for g in played)
    return {"games": len(played), "goals": goals, "avg_margin": margin / len(played)}


def _games_by_cohort(games: list[Any]) -> dict[tuple[str, str], list[Any]]:
    """Bucket played games by ``(age, gender)`` parsed from ``division_label``.

    Labels gotsport doesn't render in the canonical ``"U<n> <Boys|Girls> ..."``
    form fall into ``("Other", "Other")`` so the totals still account for them.
    """
    bucketed: dict[tuple[str, str], list[Any]] = {}
    for game in games:
        match = _COHORT_LABEL_RE.match(game.division_label or "")
        if match:
            key = (f"U{match.group(1)}", match.group(2).capitalize())
        else:
            key = ("Other", "Other")
        bucketed.setdefault(key, []).append(game)
    return bucketed


def _render_event_goal_summary(event_key: str) -> None:
    """Tournament-wide and per-cohort goal totals from ``game_results.jsonl``.

    No-ops when the local artifact is absent (e.g. partial scrapes or
    pre-enricher events) so the page header stays clean.
    """
    try:
        games = _cached_game_results(event_key)
    except (FileNotFoundError, SchemaVersionError):
        return
    if not games:
        return
    totals = _summarize_played_games(games)
    if not totals["games"]:
        return
    st.markdown("**Tournament goal totals**")
    cols = st.columns(3)
    cols[0].metric("Games played", totals["games"])
    cols[1].metric("Total goals", totals["goals"])
    cols[2].metric(
        "Avg margin",
        f"{totals['avg_margin']:.2f}" if totals["avg_margin"] is not None else "—",
    )
    by_cohort = _games_by_cohort(games)
    if not by_cohort:
        return
    rows: list[dict[str, Any]] = []
    for (age, gender), cohort_games in sorted(
        by_cohort.items(),
        key=lambda kv: (-(int(kv[0][0][1:]) if kv[0][0].startswith("U") else -1), kv[0][1]),
    ):
        cohort_totals = _summarize_played_games(cohort_games)
        rows.append(
            {
                "Cohort": f"{gender} {age}",
                "Games": cohort_totals["games"],
                "Goals": cohort_totals["goals"],
                "Avg margin": (
                    f"{cohort_totals['avg_margin']:.2f}"
                    if cohort_totals["avg_margin"] is not None
                    else "—"
                ),
            }
        )
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
    st.divider()


def _render_event_banner(
    meta: Any,
    records: list[dict[str, Any]],
    *,
    event_key: str,
    scenario: str,
) -> None:
    """Render the event banner + counts for the loaded event."""
    st.markdown(f"### {meta.event_name}")
    st.caption(
        f"Provider: {meta.provider_code} · Event ID: {meta.provider_event_id} · "
        f"Season: {meta.season_year or '—'} · Last scrape: {meta.scrape_ts}"
    )

    counts = _scrape_state_counts(records)
    review = counts["review_queued"]

    col1, col2, col3 = st.columns(3)
    col1.metric("Teams", len(records))
    col2.metric(
        "Ready",
        counts["alias_written"],
        delta=f"{review} review" if review else None,
    )
    col3.metric("Unresolved", counts["unresolved"])

    with st.expander("⚙ run details", expanded=False):
        _render_advanced_settings(meta, event_key=event_key, scenario=scenario)

    st.divider()


def _render_cohort_summary(
    cohorts: dict[tuple[str, str], list[dict[str, Any]]],
    sorted_keys: list[tuple[str, str]],
    *,
    event_name: str,
    supabase_client: Any,
    event_key_value: str | None = None,
) -> dict[tuple[str, str], tuple[str, str]]:
    """Render the cohort summary strip + totals row.

    Returns the per-cohort tint map so the cohort container headers can
    reuse it without recomputing.
    """
    tints: dict[tuple[str, str], tuple[str, str]] = {
        cohort: _cohort_tint(
            cohorts[cohort],
            event_name=event_name,
            supabase_client=supabase_client,
            event_key_value=event_key_value,
        )
        for cohort in sorted_keys
    }

    header_left, header_right = st.columns([5, 1])
    with header_left:
        st.markdown("#### Registered teams by cohort")
    with header_right:
        if st.button("↻ refresh status", help="Re-check games-import coverage"):
            _check_games_import_cached.clear()
            st.rerun()

    if not sorted_keys:
        st.info("No cohorts yet — scrape an event to populate this strip.")
        return tints

    cols_per_row = min(len(sorted_keys), 9)
    cohort_cols = st.columns(cols_per_row)
    for i, cohort in enumerate(sorted_keys):
        age, gender = cohort
        records = cohorts[cohort]
        level, note = tints[cohort]
        bg = _TINT_BG[level]
        border = _TINT_BORDER[level]
        text = _TINT_TEXT[level]
        is_active = bool(st.session_state.get(_cohort_toggle_key(age, gender), False))
        active_border = "#2563eb" if is_active else border
        active_width = "2px" if is_active else "1px"
        label = html.escape(f"{_display_gender(gender)} {age.upper()}")
        safe_note = html.escape(note)
        col = cohort_cols[i % cols_per_row]
        with col:
            st.markdown(
                f"<div style='text-align:center;padding:8px 4px;"
                f"border:{active_width} solid {active_border};border-radius:6px;"
                f"background:{bg}'>"
                f"<div style='font-weight:600;font-size:11px;color:#6b7280'>{label}</div>"
                f"<div style='font-size:18px;font-weight:600;margin:2px 0'>{len(records)}</div>"
                f"<div style='font-size:10px;color:{text}'>● {safe_note}</div>"
                f"</div>",
                unsafe_allow_html=True,
            )

    n_boys = sum(len(records) for (_, gender), records in cohorts.items() if gender == "Male")
    n_girls = sum(len(records) for (_, gender), records in cohorts.items() if gender == "Female")
    n_ready = sum(1 for level, _ in tints.values() if level == "green")

    t1, t2, t3, t4 = st.columns(4)
    t1.metric("Boys", n_boys)
    t2.metric("Girls", n_girls)
    t3.metric("Cohorts ready", f"{n_ready} / {len(sorted_keys)}")
    t4.metric(
        "Play-up %",
        "—",
        help="Available once registry materialization ships.",
    )

    st.divider()
    return tints


# ---------------------------------------------------------------------------
# Triage UI — left pane (team rows) + right pane (power ranking)
# ---------------------------------------------------------------------------


_RANK_COLS = (
    "team_id, team_name, club_name, age_group, gender, state_code, "
    "games_played, off_norm, def_norm, sos_norm, perf_centered, ml_norm, "
    "powerscore_ml"
)
_TEAM_LOOKUP_COLS = "team_id_master, team_name, club_name, age_group, gender, state_code, provider_team_id"

def _invalidate_auto_recompute(age: str, gender: str) -> None:
    """Clear the auto-recompute flag for one cohort so the next render re-fires.

    Each link click adds a new resolved team to the cohort; the existing
    medians are now slightly stale. Re-fires happen lazily next time the
    cohort expander is rendered, not synchronously, so the click handler
    stays cheap.
    """
    st.session_state.pop(f"_auto_recomputed_{age}_{gender}", None)


def _is_backtest_mode() -> bool:
    """``True`` when the page is showing a previously-played event for
    backtest validation (the structure is gotsport's, not operator-authored).

    Backtest mode hides every surface that would mutate ``CohortStructure``
    — Add division, Apply, ✕ Remove, Apply pool sizes — because the
    structure is recovered from ``raw_scrape.jsonl`` via
    ``derive_structure_from_raw_scrape`` and editing it would create a
    divergence between the scraped reality and the run's payload. Seeding
    mode (operator authoring a fresh tournament) keeps the editor.
    """
    return st.session_state.get("intake_mode", "backtest") == "backtest"


def _flash_link_success(team_name: str, master_team_name: str | None, *, scroll_anchor: str | None = None) -> None:
    """Queue a toast notification to render on the next page run.

    ``st.rerun()`` discards anything emitted in the current frame, so we
    stash the message in session_state and let ``_render_pending_flashes``
    surface it after the rerun. Uses ``st.toast`` rather than a top-of-page
    banner so confirmation is visible regardless of scroll position — the
    operator is usually scrolled deep into a cohort when they click
    Use this team / Accept and never sees a top banner.

    ``scroll_anchor`` (optional) is the DOM id the post-rerun page should
    auto-scroll to — typically the operator's cohort container header,
    so the page lands roughly where they were instead of jumping to the
    bottom (which Streamlit does when the per-team expander collapses
    and shortens the page).
    """
    pending = st.session_state.setdefault("_link_flash_messages", [])
    target = master_team_name or "master DB"
    pending.append(f"Linked {team_name} → {target}")
    if scroll_anchor:
        st.session_state["_scroll_to_anchor"] = scroll_anchor


def _render_pending_flashes() -> None:
    """Drain queued link-success messages, then restore scroll state.

    Streamlit reruns reset the page to whatever the rendered document
    height happens to be, which lands the operator at the bottom when
    an expander above their viewport collapses (per-team triage drawers
    do this on every link click). To fix it we attach a one-shot listener
    on the parent window that saves ``scrollY`` to sessionStorage as the
    operator scrolls, then restore it on every render — unless a link
    click queued an anchor target, in which case we scroll there instead.
    """
    pending = st.session_state.pop("_link_flash_messages", [])
    for msg in pending:
        st.toast(msg, icon="✅")
    anchor = st.session_state.pop("_scroll_to_anchor", None)
    anchor_js = repr(anchor) if anchor else "null"
    components.html(
        f"""
        <script>
        (function() {{
            const KEY = 'pitchrank_scroll_y';
            const win = window.parent;
            const doc = win.document;
            // One-shot listener: save scroll position (debounced) so a
            // future rerun can restore it. Guard prevents stacking
            // listeners across iframe re-mounts.
            if (!win.__pitchrank_scroll_handler__) {{
                win.__pitchrank_scroll_handler__ = function() {{
                    clearTimeout(win.__pitchrank_save_timer__);
                    win.__pitchrank_save_timer__ = setTimeout(function() {{
                        try {{ sessionStorage.setItem(KEY, win.scrollY); }} catch (e) {{}}
                    }}, 80);
                }};
                win.addEventListener('scroll', win.__pitchrank_scroll_handler__, {{ passive: true }});
            }}
            // Restore — anchor target wins, fall back to saved offset.
            setTimeout(function() {{
                const anchorId = {anchor_js};
                if (anchorId) {{
                    const target = doc.getElementById(anchorId);
                    if (target) {{
                        target.scrollIntoView({{ behavior: 'auto', block: 'start' }});
                        return;
                    }}
                }}
                try {{
                    const saved = sessionStorage.getItem(KEY);
                    if (saved !== null) win.scrollTo(0, parseInt(saved, 10));
                }} catch (e) {{}}
            }}, 60);
        }})();
        </script>
        """,
        height=0,
    )


def _cohort_anchor_id(age: str, gender: str) -> str:
    return f"cohort-anchor-{age}-{gender}".replace(" ", "-")


_AGE_GROUP_OPTIONS: tuple[str, ...] = ("Any", "u10", "u11", "u12", "u13", "u14", "u15", "u16", "u17", "u19")
_GENDER_OPTIONS: tuple[str, ...] = ("Any", "Male", "Female")
_US_STATE_OPTIONS: tuple[str, ...] = ("Any",) + tuple(sorted(s.upper() for s in US_STATES))


def _filter_value(selected: str) -> str | None:
    """Translate ``"Any"`` → ``None`` for a selectbox-derived filter."""
    return None if selected == "Any" else selected


def _default_index(options: tuple[str, ...], value: str | None) -> int:
    """Locate ``value`` in ``options`` for a selectbox default; ``0`` (Any) on miss."""
    if value and value in options:
        return options.index(value)
    return 0


def _render_reviewer_email_input() -> None:
    """Render the page-level reviewer-email gate.

    All triage write actions read ``st.session_state._reviewer_email`` and
    stay disabled until it's populated. Mirrors ``dashboard.py:699``
    (``rq_reviewer_email``) and ``dashboard.py:5746`` (``dd_reviewer_email``).
    """
    st.text_input(
        "Your email (required to save triage actions)",
        key="_reviewer_email",
        placeholder="dallas@example.com",
        help="Triage write actions stay disabled until this is set.",
    )


@st.cache_data(ttl=10)
def _load_registry_cached(event_key: str, scenario: str) -> list[dict[str, str]]:
    """Cache the per-scenario registry as plain dicts for stable cache keys."""
    entries = read_registry(event_key, scenario)
    return [entry.to_row() for entry in entries]


@st.cache_data(ttl=300)
def _rankings_full_age_form(age: str, _supabase: Any) -> str:
    """Probe the canonical ``age_group`` casing in ``rankings_full``.

    Memory ``gotcha_age_group_format.md`` flags the lowercase/uppercase
    divergence; sample five rows whose digits match ``age`` and pick the
    majority casing. Returns ``age`` unchanged if no rows come back so the
    right-pane caller can surface the empty-result warning loudly.
    """
    if _supabase is None:
        return age
    try:
        rows = (
            _supabase.table("rankings_full").select("age_group").ilike("age_group", age).limit(5).execute().data or []
        )
    except Exception:  # noqa: BLE001 — probe failure surfaces in caller
        return age
    if not rows:
        return age
    casings = [str(row.get("age_group") or "") for row in rows if row.get("age_group")]
    if not casings:
        return age
    # Majority pick.
    counts: dict[str, int] = {}
    for casing in casings:
        counts[casing] = counts.get(casing, 0) + 1
    return max(counts, key=counts.get)


@st.cache_data(ttl=60, show_spinner=False)
def _cached_game_results(event_key: str) -> list[Any]:
    """60s-cached wrapper around ``read_game_results``.

    Disk-bound on miss (parses ~700-line JSONL for a typical event); the
    streamlit reruns hammered this every interaction. Goal-summary,
    bracket-render, and cohort-tint coverage check all share the same
    cached list now. Stays in lock-step with the on-disk artifact via the
    short TTL — re-scrapes show up within 60s without an explicit clear.
    """
    return read_game_results(event_key)


@st.cache_data(ttl=60, show_spinner=False)
def _cached_local_coverage(event_key: str, provider_team_ids_key: tuple[str, ...]) -> str:
    """60s-cached wrapper around ``check_local_results_coverage``.

    The team-id key is a sorted tuple so the cache slot is stable across
    reruns — a frozenset hashes by identity in some Streamlit versions.
    """
    return check_local_results_coverage(event_key, list(provider_team_ids_key))


@st.cache_data(ttl=60, show_spinner=False)
def _cached_tier_reports(event_key: str, group_ids_key: tuple[str, ...]) -> list[TierReport]:
    """60s-cached wrapper around ``build_tier_reports``.

    Each cohort calls with a stable sorted tuple of ``group_id`` strings;
    the same tier set hits cache across reruns until a re-scrape rolls
    in or 60s passes.
    """
    return build_tier_reports(event_key, list(group_ids_key))


@st.cache_data(ttl=60)
def _cohort_rankings_score_map(age: str, gender: str, _supabase: Any) -> dict[str, float]:
    """Cache the ``(age, gender) → {team_id_master: powerscore_ml}`` map.

    Reused by Shell 04's right pane and Shell 05's pool preview so we hit
    Supabase once per cohort per minute. Operators can short-circuit the
    TTL with the ``↻ refresh ranking scores`` button (renders next to the
    right pane).
    """
    if _supabase is None:
        return {}
    probed_age = _rankings_full_age_form(age, _supabase)
    try:
        rows = (
            _supabase.table("rankings_full")
            .select("team_id, powerscore_ml")
            .eq("age_group", probed_age)
            .eq("gender", normalize_gender_label(gender))
            .execute()
            .data
            or []
        )
    except Exception:  # noqa: BLE001 — Supabase failure surfaces in caller
        return {}
    out: dict[str, float] = {}
    for row in rows:
        team_id = row.get("team_id")
        score = _safe_float(row.get("powerscore_ml"))
        if team_id and score is not None:
            out[str(team_id)] = score
    return out


@st.cache_data(ttl=10)
def _load_cohort_inputs(
    event_key: str,
    scenario: str,
    age: str,
    gender: str,
) -> tuple[CohortStructure | None, CohortConstraints]:
    """Read the per-cohort ``CohortStructure`` + ``CohortConstraints`` once.

    Wraps both ``read_structure`` and ``read_constraints`` in
    ``try/except FileNotFoundError`` so a fresh scenario without
    ``group_structure_summary.csv`` / ``constraints.json`` renders the
    bootstrap path without crashing. Cache invalidated explicitly via
    ``_load_cohort_inputs.clear()`` before every ``st.rerun()`` after a
    persist.
    """
    try:
        cohorts = read_structure(event_key, scenario)
    except FileNotFoundError:
        cohorts = []
    structure_for_cohort = next(
        (c for c in cohorts if c.age_group == age and c.gender == gender),
        None,
    )

    try:
        existing_constraints = read_constraints(event_key, scenario)
    except FileNotFoundError:
        existing_constraints = []
    constraints_for_cohort = next(
        (c for c in existing_constraints if c.cohort_age_group == age and c.cohort_gender == gender),
        None,
    )
    if constraints_for_cohort is None:
        constraints_for_cohort = CohortConstraints(cohort_age_group=age, cohort_gender=gender)
    return structure_for_cohort, constraints_for_cohort


def _query_from_registry_row(row: dict[str, Any]) -> EventTeamSearchQuery | None:
    """Build an ``EventTeamSearchQuery`` from a registry row.

    Returns ``None`` when neither ``event_age_group`` nor ``display_age_group``
    is set — ``normalize_age_group("")`` would crash the matcher otherwise.
    Mirrors ``scripts/backtest_tournament_event.py._matcher_query_from_registry_row``.
    """
    age = str(row.get("event_age_group") or row.get("display_age_group") or "").strip()
    if not age:
        return None
    return EventTeamSearchQuery(
        event_team_name=str(row.get("event_team_name") or "").strip(),
        event_age_group=age,
        event_gender=str(row.get("event_gender") or row.get("display_gender") or "").strip(),
        event_club_name=str(row.get("event_club_name") or "").strip() or None,
        search_age_group=str(row.get("search_age_group") or "").strip() or None,
        provider_team_id=str(row.get("resolved_gotsport_provider_team_id") or "").strip() or None,
    )


def _registry_provider_id(entry_row: dict[str, Any]) -> str:
    """Resolve the per-row provider key (resolved gotsport id or registration id)."""
    primary = str(entry_row.get("resolved_gotsport_provider_team_id") or "").strip()
    if primary:
        return primary
    return str(entry_row.get("event_registration_id") or "").strip()


def _build_division_groups(
    cohort_records: list[dict[str, Any]],
    structure_for_cohort: Any,
    team_state: Mapping[str, ProjectedTeamState] | None = None,
) -> dict[str, list[str]]:
    """Group provider ids by division name within a cohort.

    Falls back to a single virtual ``"_unstructured"`` division when no
    ``CohortStructure`` exists yet — matches the plan's "ship before
    Shell 05" path.

    ``team_state`` must be the projection of the same overrides ledger
    that the surrounding render is reading; passing ``None`` (or an empty
    mapping) reverts to prefix-only routing — kept as a safe default for
    tests / callers that don't exercise the override path.
    """
    if structure_for_cohort is None:
        ids = [
            str(record.get("provider_team_id") or "").strip()
            for record in cohort_records
            if record.get("provider_team_id")
        ]
        return {"_unstructured": ids}
    division_names = [division.name for division in structure_for_cohort.divisions]
    groups: dict[str, list[str]] = {name: [] for name in division_names}
    state = team_state or {}
    for record in cohort_records:
        pid = str(record.get("provider_team_id") or "").strip()
        if not pid:
            continue
        # Gotsport's ``group_name`` IS the division name (verbatim:
        # "Red", "White", "Capelli Sport+ Southwest"), so it's the
        # authoritative source when available. Fall back to the
        # name-prefix heuristic on bracket_name / division only when
        # group_name is absent (legacy / non-gotsport records).
        group_name = str(record.get("group_name") or "").strip()
        if group_name and group_name in division_names:
            groups[group_name].append(pid)
            continue
        bracket = str(record.get("bracket_name") or record.get("division") or "").strip()
        resolution = resolve_division_assignment(state.get(pid), bracket, division_names=division_names)
        if resolution.source in (SOURCE_EXPLICIT, SOURCE_PREFIX, SOURCE_STALE) and resolution.name:
            chosen = resolution.name
        else:
            chosen = division_names[0] if division_names else "_unstructured"
        groups.setdefault(chosen, []).append(pid)
    return groups


def _batch_load_resolved_teams(
    supabase_client: Any,
    team_id_masters: set[str],
) -> dict[str, dict[str, Any]]:
    """One-shot batch fetch of resolved teams keyed by ``team_id_master``."""
    if supabase_client is None or not team_id_masters:
        return {}
    try:
        rows = (
            supabase_client.table("teams")
            .select(_TEAM_LOOKUP_COLS)
            .in_("team_id_master", sorted(team_id_masters))
            .execute()
            .data
            or []
        )
    except Exception as exc:  # noqa: BLE001 — Supabase failure shouldn't crash render
        st.warning(f"Resolved-team lookup failed: {exc}")
        return {}
    return {str(row["team_id_master"]): row for row in rows if row.get("team_id_master")}


# Triage-state → UI lookups. Module-level so the four states are defined
# in one place and the lookup is a constant-time dict access.
_STATE_DOT: dict[str, str] = {
    "resolved": "✓",
    "candidates": "⚠",
    "placeholder": "⚠",
    "external": "✗",
    "unknown": "❓",
}
_STATE_ACTION_LABEL: dict[str, str] = {
    "resolved": "view",
    "candidates": "review",
    "placeholder": "fix",
    "external": "edit",
    "unknown": "check",
}
_STATE_TINT_LEVEL: dict[str, str] = {
    "resolved": "green",
    "external": "amber",
}


def _state_tint_level(state: str) -> str:
    """Resolve a triage state's tint level. Defaults to ``red`` for blockers."""
    return _STATE_TINT_LEVEL.get(state, "red")


def _resolve_team_id_master(
    projected: ProjectedTeamState | None,
    registry_row: dict[str, Any] | None,
) -> str | None:
    """Pick the authoritative ``team_id_master`` for a triaged team.

    Override projection wins over the registry snapshot — the registry's
    ``resolved_team_id_master`` reflects scrape-time matcher state, while
    the projection reflects the operator's latest accept/fix override.
    """
    if projected and projected.team_id_master:
        return projected.team_id_master
    if registry_row and registry_row.get("resolved_team_id_master"):
        return str(registry_row["resolved_team_id_master"])
    return None


def _safe_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _render_triage(
    cohort_records: list[dict[str, Any]],
    *,
    age: str,
    gender: str,
    event_key: str,
    scenario: str,
    event_name: str,
    supabase_client: Any,
) -> None:
    """Top-level triage orchestrator for one expanded cohort."""
    _auto_recompute_if_needed(
        event_key=event_key,
        scenario=scenario,
        age=age,
        gender=gender,
        supabase_client=supabase_client,
    )
    try:
        registry_rows = _load_registry_cached(event_key, scenario)
    except FileNotFoundError:
        registry_rows = []
    overrides = load_overrides(event_key, scenario)
    team_state, _cohort_state = project_overrides(overrides)

    structure_for_cohort, current_constraints = _load_cohort_inputs(event_key, scenario, age, gender)

    registry_by_pid = {_registry_provider_id(row): row for row in registry_rows if _registry_provider_id(row)}
    cohort_provider_ids = {
        str(record.get("provider_team_id") or "").strip() for record in cohort_records if record.get("provider_team_id")
    }
    cohort_registry_by_pid = {pid: row for pid, row in registry_by_pid.items() if pid in cohort_provider_ids}

    team_id_masters: set[str] = set()
    for pid in cohort_provider_ids:
        team_id = _resolve_team_id_master(team_state.get(pid), cohort_registry_by_pid.get(pid))
        if team_id:
            team_id_masters.add(team_id)
    resolved_team_by_id = _batch_load_resolved_teams(supabase_client, team_id_masters)

    division_groups = _build_division_groups(cohort_records, structure_for_cohort, team_state)

    _render_games_coverage(
        cohort_records=cohort_records,
        team_state=team_state,
        cohort_registry_by_pid=cohort_registry_by_pid,
        structure_for_cohort=structure_for_cohort,
        event_key=event_key,
        event_name=event_name,
        supabase_client=supabase_client,
    )

    left_col, right_col = st.columns([3, 2])
    with left_col:
        _render_triage_left_pane(
            cohort_records=cohort_records,
            registry_by_pid=cohort_registry_by_pid,
            team_state=team_state,
            resolved_team_by_id=resolved_team_by_id,
            division_groups=division_groups,
            structure_for_cohort=structure_for_cohort,
            age=age,
            gender=gender,
            event_key=event_key,
            scenario=scenario,
            supabase_client=supabase_client,
        )
    with right_col:
        _render_triage_right_pane(
            team_state=team_state,
            resolved_team_by_id=resolved_team_by_id,
            registry_by_pid=cohort_registry_by_pid,
            division_groups=division_groups,
            age=age,
            gender=gender,
            event_key=event_key,
            scenario=scenario,
            supabase_client=supabase_client,
        )

    _render_constraints_panel(
        age=age,
        gender=gender,
        event_key=event_key,
        scenario=scenario,
        current_constraints=current_constraints,
    )


def _render_games_coverage(
    *,
    cohort_records: list[dict[str, Any]],
    team_state: Any,
    cohort_registry_by_pid: dict[str, dict[str, Any]],
    structure_for_cohort: Any,
    event_key: str,
    event_name: str,
    supabase_client: Any,
) -> None:
    """Render the per-cohort games-coverage gauge above the triage split.

    Backtest mode reads ``intake/game_results.jsonl`` via the 60s-cached
    ``_cached_local_coverage`` — zero Supabase round-trips. Seeding mode
    falls back to ``_check_games_import_cached`` (legacy ``games`` table
    query) since seeding events haven't been played yet and there's no
    local artifact to read.
    """
    if structure_for_cohort is None:
        st.metric("Games coverage", "pending structure")
        return
    expected = sum(
        getattr(division, "expected_game_count", division.team_count) for division in structure_for_cohort.divisions
    )
    if _is_backtest_mode():
        provider_team_ids = {
            str(rec.get("provider_team_id") or "").strip()
            for rec in cohort_records
            if rec.get("provider_team_id")
        }
        provider_team_ids.discard("")
        if not provider_team_ids:
            st.metric("Games coverage", f"unknown — 0 / {expected}")
            return
        try:
            status = _cached_local_coverage(event_key, tuple(sorted(provider_team_ids)))
        except Exception as exc:  # noqa: BLE001
            st.metric("Games coverage", f"check failed ({exc})")
            return
        st.metric("Games coverage", f"{status} — {len(provider_team_ids)} / {expected}")
        if status == "not_imported":
            st.warning(
                "No game results on disk yet — re-scrape the event to populate "
                "``intake/game_results.jsonl``."
            )
        elif status == "partial":
            st.info("Games-coverage partial; some teams have no rows in the local artifact.")
        return

    team_ids: set[str] = set()
    for record in cohort_records:
        pid = str(record.get("provider_team_id") or "").strip()
        if not pid:
            continue
        team_id = _resolve_team_id_master(team_state.get(pid), cohort_registry_by_pid.get(pid))
        if team_id:
            team_ids.add(team_id)
    if not team_ids or supabase_client is None:
        st.metric("Games coverage", f"unknown — 0 / {expected}")
        return
    try:
        status = _check_games_import_cached(event_name, frozenset(team_ids), supabase_client)
    except Exception as exc:  # noqa: BLE001
        st.metric("Games coverage", f"check failed ({exc})")
        return
    st.metric("Games coverage", f"{status} — {len(team_ids)} / {expected}")
    if status == "not_imported":
        st.warning(
            "Games not yet imported for this event — run `python scripts/scrape_specific_event.py <event_id>` first."
        )
    elif status == "partial":
        st.info("Games-coverage partial; rerun the per-event scrape to fill gaps.")


def _render_triage_left_pane(
    *,
    cohort_records: list[dict[str, Any]],
    registry_by_pid: dict[str, dict[str, Any]],
    team_state: Any,
    resolved_team_by_id: dict[str, dict[str, Any]],
    division_groups: dict[str, list[str]],
    structure_for_cohort: CohortStructure | None,
    age: str,
    gender: str,
    event_key: str,
    scenario: str,
    supabase_client: Any,
) -> None:
    """Render the left pane: division editor + per-team rows grouped by division."""
    record_by_pid = {
        str(r.get("provider_team_id") or "").strip(): r for r in cohort_records if r.get("provider_team_id")
    }
    render_matcher_cache: dict[tuple[tuple[str, ...], str, bool], list[dict[str, Any]]] = {}

    if not _is_backtest_mode():
        _render_add_division_form(
            age=age,
            gender=gender,
            event_key=event_key,
            scenario=scenario,
            structure_for_cohort=structure_for_cohort,
            cohort_records=cohort_records,
        )

    if structure_for_cohort is None or not structure_for_cohort.divisions:
        if _is_backtest_mode():
            st.caption(
                "No divisions parsed from raw_scrape for this cohort. "
                "Re-scrape the event to repopulate."
            )
        else:
            st.caption("No divisions yet for this cohort. Click + Add division to start.")
        return

    division_names = [division.name for division in structure_for_cohort.divisions]
    try:
        medians_by_division = read_frozen_medians(event_key, scenario).medians_by_division
    except FileNotFoundError:
        medians_by_division = {}

    for division in structure_for_cohort.divisions:
        pids = division_groups.get(division.name, [])
        assigned_team_count = len(pids)

        def body(division=division, pids=pids, assigned_team_count=assigned_team_count) -> None:
            _render_division_editor(
                division,
                age=age,
                gender=gender,
                event_key=event_key,
                scenario=scenario,
                assigned_team_count=assigned_team_count,
            )
            _render_division_body(
                pids=pids,
                division_name=division.name,
                division_names=division_names,
                record_by_pid=record_by_pid,
                registry_by_pid=registry_by_pid,
                team_state=team_state,
                resolved_team_by_id=resolved_team_by_id,
                render_matcher_cache=render_matcher_cache,
                age=age,
                gender=gender,
                event_key=event_key,
                scenario=scenario,
                supabase_client=supabase_client,
            )

        render_division_container(division.name, body)
        _render_pool_preview(
            division,
            age=age,
            gender=gender,
            pids=pids,
            cohort_records=cohort_records,
            team_state=team_state,
            registry_by_pid=registry_by_pid,
            medians_by_division=medians_by_division,
            supabase_client=supabase_client,
        )


def _render_division_body(
    *,
    pids: list[str],
    division_name: str,
    division_names: list[str],
    record_by_pid: dict[str, dict[str, Any]],
    registry_by_pid: dict[str, dict[str, Any]],
    team_state: Any,
    resolved_team_by_id: dict[str, dict[str, Any]],
    render_matcher_cache: dict[tuple[tuple[str, ...], str, bool], list[dict[str, Any]]],
    age: str,
    gender: str,
    event_key: str,
    scenario: str,
    supabase_client: Any,
) -> None:
    """Render the team rows for one division plus the manual-add affordance."""
    add_key = f"_add_open_{age}_{gender}_{division_name}"
    st.session_state.setdefault(add_key, False)
    if st.button(
        "+ Add team",
        key=f"_add_btn_{age}_{gender}_{division_name}",
        help="Add a team that didn't appear in the scrape",
    ):
        st.session_state[add_key] = not st.session_state[add_key]
    if st.session_state[add_key]:
        _render_manual_add_form(
            division_name=division_name,
            division_names=division_names,
            age=age,
            gender=gender,
            event_key=event_key,
            scenario=scenario,
            render_matcher_cache=render_matcher_cache,
            supabase_client=supabase_client,
        )

    for pid in pids:
        record = record_by_pid.get(pid, {"provider_team_id": pid, "canonical": {}})
        registry_row = registry_by_pid.get(pid, {})
        projected = team_state.get(pid)
        team_id_master = _resolve_team_id_master(projected, registry_row)
        resolved_team = resolved_team_by_id.get(team_id_master) if team_id_master else None
        state = _classify_team_state(record, resolved_team=resolved_team, projected=projected)

        team_name = registry_row.get("event_team_name") or record.get("team_name") or pid
        play_up = _is_play_up((resolved_team or {}).get("age_group"), cohort_age=age)
        _render_team_row(
            pid=pid,
            team_name=team_name,
            state=state,
            play_up=play_up,
            level=_state_tint_level(state),
        )

        toggle_key = f"_triage_open_{pid}"
        st.session_state.setdefault(toggle_key, False)
        if not st.session_state[toggle_key]:
            continue

        if state == "candidates":
            _render_review_expander(
                pid=pid,
                registry_row=registry_row,
                age=age,
                gender=gender,
                event_key=event_key,
                scenario=scenario,
                render_matcher_cache=render_matcher_cache,
                supabase_client=supabase_client,
            )
        elif state == "placeholder":
            _render_fix_expander(
                pid=pid,
                registry_row=registry_row,
                team_id_master=team_id_master,
                age=age,
                gender=gender,
                event_key=event_key,
                scenario=scenario,
                supabase_client=supabase_client,
            )
        elif state == "external":
            _render_external_drawer(
                pid=pid,
                registry_row=registry_row,
                projected=projected,
                division_names=division_names,
                age=age,
                gender=gender,
                event_key=event_key,
                scenario=scenario,
                supabase_client=supabase_client,
            )
        elif state == "unknown":
            st.info(f"Team {team_name}: state unknown — re-scrape or accept manually.")

        # ``candidates`` / ``placeholder`` / ``unknown`` rows must be
        # triaged via the existing review/fix flows before assignment is
        # meaningful.
        if state in ("resolved", "external") and len(division_names) > 1:
            scraped_group_name = (record_by_pid.get(pid, {}) or {}).get("group_name")
            _render_assign_division_form(
                pid=pid,
                team_name=team_name,
                projected=projected,
                division_names=division_names,
                scraped_group_name=str(scraped_group_name) if scraped_group_name else None,
                event_key=event_key,
                scenario=scenario,
            )


def _render_team_row(
    *,
    pid: str,
    team_name: str,
    state: str,
    play_up: bool,
    level: str,
) -> None:
    """Render one team row + action toggle."""
    bg = _TINT_BG[level]
    border = _TINT_BORDER[level]
    text = _TINT_TEXT[level]
    dot = _STATE_DOT.get(state, "•")
    action_label = _STATE_ACTION_LABEL.get(state, "view")
    play_up_badge = " 🆙 play-up" if play_up else ""
    toggle_key = f"_triage_open_{pid}"
    # ``team_name`` originates from scraped provider HTML; escape before
    # interpolating into a markdown block with ``unsafe_allow_html=True``.
    safe_team_name = html.escape(str(team_name))
    safe_state = html.escape(state)
    cols = st.columns([0.5, 4, 1, 1.4])
    with cols[0]:
        st.markdown(
            f"<div style='font-size:18px;color:{text};text-align:center'>{dot}</div>",
            unsafe_allow_html=True,
        )
    with cols[1]:
        st.markdown(
            f"<div style='padding:6px 8px;border:1px solid {border};border-radius:6px;"
            f"background:{bg}'>"
            f"<div style='font-weight:600;font-size:13px'>{safe_team_name}</div>"
            f"<div style='font-size:11px;color:#6b7280'>{safe_state}{play_up_badge}</div>"
            f"</div>",
            unsafe_allow_html=True,
        )
    with cols[2]:
        st.caption(state)
    with cols[3]:
        if state == "resolved":
            st.caption(f"✓ {action_label}")
        else:
            if st.button(
                action_label,
                key=f"_triage_action_{pid}",
                help=f"Open the {action_label} flow for this team",
            ):
                st.session_state[toggle_key] = not st.session_state.get(toggle_key, False)
                st.rerun()


def _render_review_expander(
    *,
    pid: str,
    registry_row: dict[str, Any],
    age: str,
    gender: str,
    event_key: str,
    scenario: str,
    render_matcher_cache: dict[tuple[tuple[str, ...], str, bool], list[dict[str, Any]]],
    supabase_client: Any,
) -> None:
    """Render the candidates → match-acceptance flow."""
    name = registry_row.get("event_team_name") or pid
    reviewer_email = st.session_state.get("_reviewer_email", "")
    write_disabled = not reviewer_email
    with st.expander(f"Review {name}", expanded=True):
        if supabase_client is None:
            st.warning("Database unavailable — cannot run live matcher.")
            return
        query = _query_from_registry_row(registry_row)
        if query is None:
            st.warning(
                "Registry row is missing age group; cannot run live matcher. Re-scrape this event before triaging."
            )
            return
        try:
            result = search_event_team_in_db(
                supabase_client,
                query,
                limit=3,
                cache=render_matcher_cache,
            )
        except Exception as exc:  # noqa: BLE001
            st.error(f"Matcher failed: {exc}")
            return
        if not result.matches:
            st.info("No DB candidates — mark this team external if it doesn't exist.")
        for rank, match in enumerate(result.matches, start=1):
            cols = st.columns([3, 1, 1, 1])
            with cols[0]:
                st.markdown(
                    f"**{match.get('team_name', '?')}** · {match.get('club_name') or '—'} · "
                    f"{match.get('age_group', '')}/{match.get('gender', '')}"
                )
                st.caption(f"score={match.get('score', 0):.3f} · reason={match.get('score_reason', '?')}")
            with cols[1]:
                with st.popover("details"):
                    st.json(match)
            with cols[2]:
                st.metric("score", f"{match.get('score', 0):.2f}")
            with cols[3]:
                if st.button(
                    "Accept",
                    key=f"_accept_{pid}_{rank}",
                    disabled=write_disabled,
                ):
                    append_override(
                        event_key,
                        scenario,
                        build_override_record(
                            ts=utc_now_iso(),
                            actor=reviewer_email,
                            scope="team",
                            type="accept_match",
                            team_ref=pid,
                            before={
                                "state": "candidates",
                                "best_score": result.best_score,
                                "second_score": result.second_score,
                            },
                            after={
                                "state": "resolved",
                                "team_id_master": match.get("team_id_master"),
                                "match_rank": rank,
                            },
                            reason=f"operator-accepted match #{rank}",
                        ),
                    )
                    _load_registry_cached.clear()
                    _invalidate_auto_recompute(age, gender)
                    _flash_link_success(
                        name,
                        match.get("team_name"),
                        scroll_anchor=_cohort_anchor_id(age, gender),
                    )
                    st.session_state[f"_triage_open_{pid}"] = False
                    st.rerun()
        st.markdown("---")
        st.markdown("**Not the right team? Search the master DB:**")
        cohort_age_default = age if age in _AGE_GROUP_OPTIONS else None
        cohort_gender_default = normalize_gender_label(gender)
        with st.form(f"_review_search_{pid}"):
            search_cols = st.columns([2, 1, 1, 1])
            with search_cols[0]:
                name_query = st.text_input("Team name", key=f"_review_name_{pid}")
            with search_cols[1]:
                club_query = st.text_input("Club", key=f"_review_club_{pid}")
            with search_cols[2]:
                provider_id_query = st.text_input("Provider id", key=f"_review_pid_{pid}")
            with search_cols[3]:
                team_id_master_query = st.text_input("team_id_master", key=f"_review_tim_{pid}")
            filter_cols = st.columns([1, 1, 1, 1])
            with filter_cols[0]:
                age_choice = st.selectbox(
                    "Age",
                    options=_AGE_GROUP_OPTIONS,
                    index=_default_index(_AGE_GROUP_OPTIONS, cohort_age_default),
                    key=f"_review_age_{pid}",
                )
            with filter_cols[1]:
                gender_choice = st.selectbox(
                    "Gender",
                    options=_GENDER_OPTIONS,
                    index=_default_index(_GENDER_OPTIONS, cohort_gender_default),
                    key=f"_review_gender_{pid}",
                )
            with filter_cols[2]:
                state_choice = st.selectbox(
                    "State",
                    options=_US_STATE_OPTIONS,
                    index=0,
                    key=f"_review_state_{pid}",
                )
            search_submitted = st.form_submit_button("Search master DB")
        results_key = f"_review_search_results_{pid}"
        if search_submitted and supabase_client is not None:
            st.session_state[results_key] = _search_master_teams(
                supabase_client,
                name_query=name_query,
                club_query=club_query,
                provider_id_query=provider_id_query,
                team_id_master_query=team_id_master_query,
                age_group_filter=_filter_value(age_choice),
                gender_filter=_filter_value(gender_choice),
                state_code_filter=_filter_value(state_choice),
            )
        # Render results out of session_state so the per-hit buttons survive
        # the rerun caused by clicking them. ``st.form_submit_button`` only
        # returns True on the run it was clicked; without persistence, the
        # next rerun would drop the results block and the per-hit click
        # would never reach its handler.
        search_results = st.session_state.get(results_key)
        if search_results is not None:
            if not search_results:
                st.info("No matches.")
            for hit in search_results:
                hit_cols = st.columns([4, 1])
                with hit_cols[0]:
                    st.markdown(f"**{hit.get('team_name')}** · {hit.get('club_name') or '—'}")
                    st.caption(
                        f"{hit.get('age_group', '')} / {hit.get('gender', '')} · "
                        f"team_id_master={hit.get('team_id_master')}"
                    )
                with hit_cols[1]:
                    if st.button(
                        "Use this team",
                        key=f"_review_use_{pid}_{hit.get('team_id_master')}",
                        disabled=write_disabled,
                    ):
                        append_override(
                            event_key,
                            scenario,
                            build_override_record(
                                ts=utc_now_iso(),
                                actor=reviewer_email,
                                scope="team",
                                type="accept_match",
                                team_ref=pid,
                                before={
                                    "state": "candidates",
                                    "best_score": result.best_score,
                                    "second_score": result.second_score,
                                },
                                after={
                                    "state": "resolved",
                                    "team_id_master": hit.get("team_id_master"),
                                    "match_rank": "manual_search",
                                },
                                reason="operator-picked DB team via manual search",
                            ),
                        )
                        _load_registry_cached.clear()
                        _invalidate_auto_recompute(age, gender)
                        st.session_state.pop(results_key, None)
                        _flash_link_success(
                            name,
                            hit.get("team_name"),
                            scroll_anchor=_cohort_anchor_id(age, gender),
                        )
                        st.session_state[f"_triage_open_{pid}"] = False
                        st.rerun()
        if st.button(
            "Mark external (reject all)",
            key=f"_mark_ext_{pid}",
            disabled=write_disabled,
        ):
            append_override(
                event_key,
                scenario,
                build_override_record(
                    ts=utc_now_iso(),
                    actor=reviewer_email,
                    scope="team",
                    type="mark_external",
                    team_ref=pid,
                    before={"state": "candidates"},
                    after={"state": "external"},
                    reason="rejected all DB candidates",
                ),
            )
            _load_registry_cached.clear()
            st.session_state[f"_triage_open_{pid}"] = False
            st.rerun()


def _render_fix_expander(
    *,
    pid: str,
    registry_row: dict[str, Any],
    team_id_master: str | None,
    age: str,
    gender: str,
    event_key: str,
    scenario: str,
    supabase_client: Any,
) -> None:
    """Render the placeholder → real-team search flow."""
    name = registry_row.get("event_team_name") or pid
    reviewer_email = st.session_state.get("_reviewer_email", "")
    write_disabled = not reviewer_email
    with st.expander(f"Fix placeholder {name}", expanded=True):
        with st.form(f"_fix_{pid}"):
            name_query = st.text_input("Team name", key=f"_fix_name_{pid}")
            club_query = st.text_input("Club name", key=f"_fix_club_{pid}")
            provider_id_query = st.text_input("Provider team id", key=f"_fix_pid_{pid}")
            team_id_master_query = st.text_input("team_id_master", key=f"_fix_tim_{pid}")
            submitted = st.form_submit_button("Search")
        results_key = f"_fix_search_results_{pid}"
        if submitted and supabase_client is not None:
            st.session_state[results_key] = _search_master_teams(
                supabase_client,
                name_query=name_query,
                club_query=club_query,
                provider_id_query=provider_id_query,
                team_id_master_query=team_id_master_query,
            )
        results = st.session_state.get(results_key)
        if results is not None:
            if not results:
                st.info("No matches.")
            for hit in results:
                cols = st.columns([4, 1])
                with cols[0]:
                    st.markdown(f"**{hit.get('team_name')}** · {hit.get('club_name') or '—'}")
                    st.caption(
                        f"{hit.get('age_group', '')} / {hit.get('gender', '')} · "
                        f"team_id_master={hit.get('team_id_master')}"
                    )
                with cols[1]:
                    if st.button(
                        "Use this team",
                        key=f"_fix_use_{pid}_{hit.get('team_id_master')}",
                        disabled=write_disabled,
                    ):
                        append_override(
                            event_key,
                            scenario,
                            build_override_record(
                                ts=utc_now_iso(),
                                actor=reviewer_email,
                                scope="team",
                                type="fix_match",
                                team_ref=pid,
                                before={
                                    "state": "placeholder",
                                    "team_id_master": team_id_master,
                                },
                                after={
                                    "state": "resolved",
                                    "team_id_master": hit.get("team_id_master"),
                                },
                                reason="operator picked DB team",
                            ),
                        )
                        _load_registry_cached.clear()
                        _invalidate_auto_recompute(age, gender)
                        st.session_state.pop(results_key, None)
                        _flash_link_success(
                            name,
                            hit.get("team_name"),
                            scroll_anchor=_cohort_anchor_id(age, gender),
                        )
                        st.session_state[f"_triage_open_{pid}"] = False
                        st.rerun()
        if st.button(
            "Mark external instead",
            key=f"_fix_mark_ext_{pid}",
            disabled=write_disabled,
        ):
            append_override(
                event_key,
                scenario,
                build_override_record(
                    ts=utc_now_iso(),
                    actor=reviewer_email,
                    scope="team",
                    type="mark_external",
                    team_ref=pid,
                    before={
                        "state": "placeholder",
                        "team_id_master": team_id_master,
                    },
                    after={
                        "state": "external",
                        "manual_override_assume_resolved_without_db": True,
                    },
                    reason="placeholder — externalized",
                ),
            )
            _load_registry_cached.clear()
            st.session_state[f"_triage_open_{pid}"] = False
            st.rerun()


def _search_master_teams(
    supabase_client: Any,
    *,
    name_query: str,
    club_query: str,
    provider_id_query: str,
    team_id_master_query: str,
    age_group_filter: str | None = None,
    gender_filter: str | None = None,
    state_code_filter: str | None = None,
) -> list[dict[str, Any]]:
    """Look up master teams matching any of the supplied fields.

    Mirrors ``dashboard.py:4596-4615``'s search structure. Filters
    placeholder rows in Python — the cross-column predicate doesn't fit
    PostgREST. The optional ``age_group_filter`` / ``gender_filter`` /
    ``state_code_filter`` AND together with whichever primary search
    column is active; supplying only filters (no name/club/id) returns
    the first 20 teams matching the filter set.
    """
    name_query = (name_query or "").strip()
    club_query = (club_query or "").strip()
    provider_id_query = (provider_id_query or "").strip()
    team_id_master_query = (team_id_master_query or "").strip()
    age_group_filter = (age_group_filter or "").strip() or None
    gender_filter = (gender_filter or "").strip() or None
    state_code_filter = (state_code_filter or "").strip() or None
    if not any(
        [
            name_query,
            club_query,
            provider_id_query,
            team_id_master_query,
            age_group_filter,
            gender_filter,
            state_code_filter,
        ]
    ):
        return []
    rows: list[dict[str, Any]] = []
    try:
        # ``is_deprecated=False`` is the canonical predicate for "active
        # team" everywhere else in the codebase (calculator.py:2570,
        # data_adapter.py:312); search must honor it so deprecated /
        # merged-away rows never resurface as Accept candidates.
        builder = supabase_client.table("teams").select(_TEAM_LOOKUP_COLS).eq("is_deprecated", False)
        if age_group_filter:
            builder = builder.eq("age_group", age_group_filter)
        if gender_filter:
            builder = builder.eq("gender", gender_filter)
        if state_code_filter:
            builder = builder.eq("state_code", state_code_filter)
        if provider_id_query:
            rows = builder.eq("provider_team_id", provider_id_query).limit(20).execute().data or []
        elif team_id_master_query:
            rows = builder.eq("team_id_master", team_id_master_query).limit(20).execute().data or []
        elif name_query:
            rows = builder.ilike("team_name", f"%{name_query}%").limit(20).execute().data or []
        elif club_query:
            rows = builder.ilike("club_name", f"%{club_query}%").limit(20).execute().data or []
        else:
            rows = builder.limit(20).execute().data or []
    except Exception as exc:  # noqa: BLE001
        st.error(f"Search failed: {exc}")
        return []
    # Filter placeholders in Python via the canonical predicate. Prefix
    # filtering would also drop legit teams whose name happens to start
    # with ``unknown_`` (rare, but the canonical predicate is the source
    # of truth and is essentially free to call).
    return [
        row for row in rows if not _is_placeholder_team(row.get("team_name"), str(row.get("provider_team_id") or ""))
    ]


def _render_external_drawer(
    *,
    pid: str,
    registry_row: dict[str, Any],
    projected: ProjectedTeamState | None,
    division_names: list[str],
    age: str,
    gender: str,
    event_key: str,
    scenario: str,
    supabase_client: Any,
) -> None:
    """Render the external-team edit drawer + recompute-medians action."""
    name = registry_row.get("event_team_name") or pid
    reviewer_email = st.session_state.get("_reviewer_email", "")
    write_disabled = not reviewer_email
    prior_seed = (projected.manual_seed_group if projected else None) or (
        division_names[0] if division_names else "_unstructured"
    )
    prior_strength = (projected.strength_mode if projected else None) or "median"
    prior_power = projected.manual_power_score if projected else None
    prior_note = (projected.note if projected else None) or ""
    with st.expander(f"External team: {name}", expanded=True):
        with st.form(f"_external_{pid}"):
            seed_options = division_names or ["_unstructured"]
            seed_index = seed_options.index(prior_seed) if prior_seed in seed_options else 0
            manual_seed_group = st.selectbox(
                "Manual seed group",
                options=seed_options,
                index=seed_index,
                key=f"_ext_seed_{pid}",
            )
            mode_index = _STRENGTH_MODES.index(prior_strength) if prior_strength in _STRENGTH_MODES else 0
            strength_mode = st.radio(
                "Strength mode",
                options=_STRENGTH_MODES,
                index=mode_index,
                horizontal=True,
                key=f"_ext_mode_{pid}",
                help=(
                    "median: derive from cohort medians · "
                    "manual: enter a power_score · "
                    "exclude: skip during ranking (Report Card semantics finalized in a later shell)"
                ),
            )
            manual_power_score = st.number_input(
                "Manual power_score",
                value=float(prior_power) if prior_power is not None else 0.0,
                step=0.1,
                format="%.2f",
                disabled=(strength_mode != "manual"),
                key=f"_ext_score_{pid}",
            )
            note = st.text_area("Note", value=prior_note, key=f"_ext_note_{pid}")
            submitted = st.form_submit_button("Save", disabled=write_disabled)
        if submitted and reviewer_email:
            after = {
                "state": "external",
                "manual_seed_group": manual_seed_group,
                "strength_mode": strength_mode,
                "note": note,
            }
            if strength_mode == "manual":
                after["manual_power_score"] = float(manual_power_score)
            # Re-load overrides at submit time so a Streamlit rerun between
            # render and submit doesn't put a stale ``before`` snapshot in
            # the audit ledger.
            fresh_team_state, _ = project_overrides(load_overrides(event_key, scenario))
            fresh_projected = fresh_team_state.get(pid)
            append_override(
                event_key,
                scenario,
                build_override_record(
                    ts=utc_now_iso(),
                    actor=reviewer_email,
                    scope="team",
                    type="edit_external",
                    team_ref=pid,
                    before=_external_before(fresh_projected),
                    after=after,
                    reason="operator edit external",
                ),
            )
            _load_registry_cached.clear()
            st.session_state[f"_triage_open_{pid}"] = False
            st.rerun()
        st.divider()
        st.markdown("**Actually in our DB? Search and re-link:**")
        cohort_age_default = age if age in _AGE_GROUP_OPTIONS else None
        cohort_gender_default = normalize_gender_label(gender)
        with st.form(f"_external_relink_{pid}"):
            relink_cols = st.columns([2, 1, 1, 1])
            with relink_cols[0]:
                relink_name = st.text_input("Team name", key=f"_ext_relink_name_{pid}")
            with relink_cols[1]:
                relink_club = st.text_input("Club", key=f"_ext_relink_club_{pid}")
            with relink_cols[2]:
                relink_pid = st.text_input("Provider id", key=f"_ext_relink_pid_{pid}")
            with relink_cols[3]:
                relink_tim = st.text_input("team_id_master", key=f"_ext_relink_tim_{pid}")
            relink_filter_cols = st.columns([1, 1, 1, 1])
            with relink_filter_cols[0]:
                relink_age = st.selectbox(
                    "Age",
                    options=_AGE_GROUP_OPTIONS,
                    index=_default_index(_AGE_GROUP_OPTIONS, cohort_age_default),
                    key=f"_ext_relink_age_{pid}",
                )
            with relink_filter_cols[1]:
                relink_gender = st.selectbox(
                    "Gender",
                    options=_GENDER_OPTIONS,
                    index=_default_index(_GENDER_OPTIONS, cohort_gender_default),
                    key=f"_ext_relink_gender_{pid}",
                )
            with relink_filter_cols[2]:
                relink_state = st.selectbox(
                    "State",
                    options=_US_STATE_OPTIONS,
                    index=0,
                    key=f"_ext_relink_state_{pid}",
                )
            relink_submitted = st.form_submit_button("Search master DB")
        relink_results_key = f"_ext_relink_results_{pid}"
        if relink_submitted and supabase_client is not None:
            st.session_state[relink_results_key] = _search_master_teams(
                supabase_client,
                name_query=relink_name,
                club_query=relink_club,
                provider_id_query=relink_pid,
                team_id_master_query=relink_tim,
                age_group_filter=_filter_value(relink_age),
                gender_filter=_filter_value(relink_gender),
                state_code_filter=_filter_value(relink_state),
            )
        relink_results = st.session_state.get(relink_results_key)
        if relink_results is not None:
            if not relink_results:
                st.info("No matches.")
            for hit in relink_results:
                hit_cols = st.columns([4, 1])
                with hit_cols[0]:
                    st.markdown(f"**{hit.get('team_name')}** · {hit.get('club_name') or '—'}")
                    st.caption(
                        f"{hit.get('age_group', '')} / {hit.get('gender', '')} · "
                        f"team_id_master={hit.get('team_id_master')}"
                    )
                with hit_cols[1]:
                    if st.button(
                        "Use this team",
                        key=f"_ext_relink_use_{pid}_{hit.get('team_id_master')}",
                        disabled=write_disabled,
                    ):
                        # Append-only ledger: writing accept_match after mark_external
                        # flips the projection back to resolved (latest wins per
                        # team_ref). Capture the prior external state in ``before``
                        # so audit retains the round-trip.
                        append_override(
                            event_key,
                            scenario,
                            build_override_record(
                                ts=utc_now_iso(),
                                actor=reviewer_email,
                                scope="team",
                                type="accept_match",
                                team_ref=pid,
                                before=_external_before(projected),
                                after={
                                    "state": "resolved",
                                    "team_id_master": hit.get("team_id_master"),
                                    "match_rank": "manual_search",
                                },
                                reason="operator re-linked external team to DB via manual search",
                            ),
                        )
                        _load_registry_cached.clear()
                        _invalidate_auto_recompute(age, gender)
                        st.session_state.pop(relink_results_key, None)
                        _flash_link_success(
                            name,
                            hit.get("team_name"),
                            scroll_anchor=_cohort_anchor_id(age, gender),
                        )
                        st.session_state[f"_triage_open_{pid}"] = False
                        st.rerun()
        st.divider()
        if st.button(
            "Recompute medians",
            key=f"_recompute_{pid}",
            disabled=write_disabled,
            help=(
                "Affects every external team in this cohort, not just this one. "
                "Re-derives medians from current resolved teams."
            ),
        ):
            _trigger_recompute(
                event_key=event_key,
                scenario=scenario,
                age=age,
                gender=gender,
                supabase_client=supabase_client,
                reviewer_email=reviewer_email,
            )


def _external_before(projected: ProjectedTeamState | None) -> dict[str, Any]:
    """Capture the prior external-team state for the override ``before``."""
    if projected is None:
        return {"state": "external"}
    return {
        "state": projected.state,
        "manual_seed_group": projected.manual_seed_group,
        "strength_mode": projected.strength_mode,
        "manual_power_score": projected.manual_power_score,
        "note": projected.note,
    }


def _render_assign_division_form(
    *,
    pid: str,
    team_name: str,
    projected: ProjectedTeamState | None,
    division_names: list[str],
    scraped_group_name: str | None = None,
    event_key: str,
    scenario: str,
) -> None:
    """Form-wrapped per-team Assign division selectbox.

    Renders only when the cohort has multiple divisions and the team is
    in a state where assignment is meaningful (``resolved`` or
    ``external``). Default selection priority:

    1. ``resolve_division_assignment`` when it returns explicit / prefix /
       stale-with-fallback (operator-confirmed or prefix-derived).
    2. ``scraped_group_name`` (the gotsport tier the team actually played
       in, from ``raw_scrape.jsonl``) when the resolver returns no signal
       AND the scraped tier is one of the cohort's divisions. Skips the
       SENTINEL "pick one" prompt for the common case where the right
       answer is sitting in raw_scrape already.
    3. The SENTINEL when neither (1) nor (2) yields a usable name.
    """
    reviewer_email = st.session_state.get("_reviewer_email", "")
    write_disabled = not reviewer_email
    resolution = resolve_division_assignment(projected, team_name, division_names=division_names)
    if resolution.name is None:
        if scraped_group_name and scraped_group_name in division_names:
            options = list(division_names)
            index = options.index(scraped_group_name)
        else:
            # ``source`` is either SOURCE_NONE (no signal) or SOURCE_STALE with
            # no prefix-resolved fallback — both cases require operator pick.
            options = [_DIV_ASSIGN_SENTINEL, *division_names]
            index = 0
    else:
        options = list(division_names)
        index = options.index(resolution.name) if resolution.name in options else 0

    with st.expander(f"Assign division for {team_name}", expanded=False):
        if resolution.source == SOURCE_STALE:
            st.warning(
                f"Prior assignment '{projected.assigned_division_name if projected else ''}' is no longer "
                "in this cohort's structure — re-confirm or pick a different division."
            )
        with st.form(f"_div_assign_form_{pid}", clear_on_submit=False):
            selected = st.selectbox(
                "Division",
                options=options,
                index=index,
                key=f"_div_assign_{pid}",
                help="Operator-confirmed division; overrides the prefix heuristic.",
            )
            submitted = st.form_submit_button("Save assignment", disabled=write_disabled)
        if not submitted:
            return
        if selected == _DIV_ASSIGN_SENTINEL:
            return  # operator clicked Save without picking; no-op
        # Re-read overrides at submit time so a Streamlit rerun between
        # render and submit doesn't put a stale ``before`` snapshot in
        # the audit ledger (matches ``_render_external_drawer``).
        fresh_team_state, _ = project_overrides(load_overrides(event_key, scenario))
        fresh_projected = fresh_team_state.get(pid)
        prior_assigned = fresh_projected.assigned_division_name if fresh_projected else None
        if selected == prior_assigned:
            return  # already-explicit re-pick of same value; avoid redundant audit records
        append_override(
            event_key,
            scenario,
            build_override_record(
                ts=utc_now_iso(),
                actor=reviewer_email,
                scope="team",
                type="assign_division",
                team_ref=pid,
                before={"assigned_division_name": prior_assigned},
                after={"assigned_division_name": selected},
                reason="",
            ),
        )
        # Drop widget key — sentinel is removed from options after the flip,
        # which would crash Streamlit if session_state still held it.
        st.session_state.pop(f"_div_assign_{pid}", None)
        _load_registry_cached.clear()
        st.rerun()


def _auto_recompute_if_needed(
    *,
    event_key: str,
    scenario: str,
    age: str,
    gender: str,
    supabase_client: Any,
) -> None:
    """Quietly fire ``_recompute_medians_inner`` on first cohort expansion.

    The right-pane "median pending — click Recompute" annotation is a
    friction point for operators: external teams in the cohort have no
    score until medians have been computed, but the operator has to find
    the button buried in an external-team drawer and click it once per
    cohort. We auto-fire it on first cohort open per session, gated on:

    - ``reviewer_email`` set (the audit override needs a non-empty actor)
    - Not already auto-fired this session for this cohort
    - No staging run in progress (mirrors the manual ``_trigger_recompute``
      precondition; recompute under an active run could race)

    Any expected failure (no resolved teams, lock contention, audit-write
    failure) is swallowed — the operator can still click Recompute manually
    if they want to retry. Side effects: writes ``frozen_medians.json`` +
    appends a ``recompute_medians`` audit override.
    """
    reviewer_email = st.session_state.get("_reviewer_email", "")
    if not reviewer_email or supabase_client is None:
        return
    flag_key = f"_auto_recomputed_{age}_{gender}"
    if st.session_state.get(flag_key):
        return
    try:
        with acquire_scenario_lock(event_key, scenario, timeout=2.0):
            staging = [
                name for name in list_runs(event_key, scenario, completed_only=False) if name.endswith(".tmp")
            ]
            if staging:
                return
            _recompute_medians_inner(
                event_key=event_key,
                scenario=scenario,
                age=age,
                gender=gender,
                supabase_client=supabase_client,
                reviewer_email=reviewer_email,
            )
    except (ScenarioLockError, RuntimeError):
        # Lock contention or "No resolved teams in cohort" — both are
        # benign at auto-fire time. The manual button still surfaces the
        # error if the operator triggers it explicitly.
        return
    st.session_state[flag_key] = True


def _trigger_recompute(
    *,
    event_key: str,
    scenario: str,
    age: str,
    gender: str,
    supabase_client: Any,
    reviewer_email: str,
) -> None:
    """Run the medians recompute with lock + audit-write ordering."""
    if supabase_client is None:
        st.error("Database unavailable — cannot recompute medians.")
        return
    with st.spinner("Recomputing medians..."):
        try:
            with acquire_scenario_lock(event_key, scenario, timeout=2.0):
                staging = [
                    name for name in list_runs(event_key, scenario, completed_only=False) if name.endswith(".tmp")
                ]
                if staging:
                    raise RuntimeError("Recompute disabled while a run is active")
                _recompute_medians_inner(
                    event_key=event_key,
                    scenario=scenario,
                    age=age,
                    gender=gender,
                    supabase_client=supabase_client,
                    reviewer_email=reviewer_email,
                )
        except ScenarioLockError:
            st.error("Scenario is locked by another process — try again shortly.")
            return
        except RuntimeError as exc:
            st.error(str(exc))
            return
    st.success("Medians recomputed.")
    _load_registry_cached.clear()
    st.rerun()


def _recompute_medians_inner(
    *,
    event_key: str,
    scenario: str,
    age: str,
    gender: str,
    supabase_client: Any,
    reviewer_email: str,
) -> None:
    """Read rankings_full, bucket by division, persist medians + audit."""
    overrides = load_overrides(event_key, scenario)
    team_state, _cohort_state = project_overrides(overrides)
    structure_list = read_structure(event_key, scenario)
    structure_for_cohort = next(
        (c for c in structure_list if c.age_group == age and c.gender == gender),
        None,
    )
    division_names = [d.name for d in structure_for_cohort.divisions] if structure_for_cohort else []

    registry_rows = _load_registry_cached(event_key, scenario)
    cohort_rows = [
        row for row in registry_rows if row.get("event_age_group") == age and row.get("event_gender") == gender
    ]
    division_by_team_id: dict[str, str] = {}
    stale_team_names: list[str] = []
    for row in cohort_rows:
        pid = _registry_provider_id(row)
        team_id_master = _resolve_team_id_master(team_state.get(pid), row)
        if not team_id_master:
            continue
        bracket = str(row.get("event_team_name") or "").strip()
        if not division_names:
            # No structure for this cohort — bucket every team under the
            # virtual ``_unstructured`` division (mirrors the prior fallback
            # behavior at this site).
            division_by_team_id[team_id_master] = "_unstructured"
            continue
        resolution = resolve_division_assignment(team_state.get(pid), bracket, division_names=division_names)
        if resolution.source in (SOURCE_EXPLICIT, SOURCE_PREFIX):
            division_by_team_id[team_id_master] = resolution.name or division_names[0]
        elif resolution.source == SOURCE_STALE:
            # Skip stale-assigned teams from the medians: bucketing into
            # the prefix-resolved division would contaminate medians with
            # values the operator explicitly de-assigned. Surface via UI
            # warning so the operator re-assigns before re-running.
            stale_team_names.append(bracket or pid)
        else:  # SOURCE_NONE
            division_by_team_id[team_id_master] = division_names[0]

    if not division_by_team_id:
        raise RuntimeError("No resolved teams in cohort — nothing to recompute.")

    if stale_team_names:
        st.warning(
            f"Medians recomputed without {len(stale_team_names)} stale-assigned team(s) — "
            "re-confirm assignments before treating new medians as authoritative: " + ", ".join(stale_team_names)
        )

    probed_age = _rankings_full_age_form(age, supabase_client)
    rows = (
        supabase_client.table("rankings_full")
        .select("team_id, powerscore_ml")
        .eq("age_group", probed_age)
        .eq("gender", normalize_gender_label(gender))
        .in_("team_id", sorted(division_by_team_id.keys()))
        .execute()
        .data
        or []
    )
    if not rows:
        st.warning(f"rankings_full returned zero rows for {age}/{gender} — verify age_group casing.")
        return
    buckets: dict[str, list[float]] = {}
    for row in rows:
        team_id = str(row.get("team_id") or "")
        score = _safe_float(row.get("powerscore_ml"))
        division = division_by_team_id.get(team_id)
        if score is None or not division:
            continue
        buckets.setdefault(division, []).append(score)

    if not any(buckets.values()):
        st.warning("Recompute produced no median samples — preserving prior medians.")
        return

    try:
        prior = read_frozen_medians(event_key, scenario).medians_by_division
    except FileNotFoundError:
        prior = {}

    medians = compute_frozen_medians(buckets)
    write_frozen_medians(event_key, scenario, medians)
    try:
        append_override(
            event_key,
            scenario,
            build_override_record(
                ts=utc_now_iso(),
                actor=reviewer_email,
                scope="cohort",
                type="recompute_medians",
                team_ref=f"{age}_{gender}",
                before={"medians_by_division": dict(prior)},
                after={"medians_by_division": dict(medians.medians_by_division)},
                reason="operator recompute",
            ),
            _already_locked=True,
        )
    except Exception:  # noqa: BLE001
        st.error("Medians recomputed but audit log write failed; rerun Recompute to land the ledger entry.")


def _persist_structure(
    event_key: str,
    scenario: str,
    cohorts: list[CohortStructure],
) -> bool:
    """Write structure under a scenario lock; surface contention as ``st.error``.

    Returns ``True`` on a successful write. Callers branch on the boolean to
    decide whether to ``st.success`` + ``st.rerun`` (writes-succeeded path) or
    skip those side effects (lock contended).
    """
    try:
        with acquire_scenario_lock(event_key, scenario, timeout=2.0):
            write_structure(event_key, scenario, cohorts)
        return True
    except ScenarioLockError:
        st.error("Another tab is editing this scenario; try again shortly.")
        return False


def _persist_constraint(
    event_key: str,
    scenario: str,
    age: str,
    gender: str,
    field: str,
    widget_key: str,
) -> None:
    """``on_change`` callback: read ``st.session_state[widget_key]`` and persist.

    Mirrors the dashboard's per-widget callback pattern (cf. Update Team State
    form). Untouched cohort entries pass through verbatim — never re-emitted
    with synthesized defaults — so editing one cohort can't silently rewrite
    another's constraints. Lock contention surfaces inline; the post-callback
    rerun renders the error.
    """
    new_value = st.session_state.get(widget_key)
    try:
        with acquire_scenario_lock(event_key, scenario, timeout=2.0):
            try:
                existing = read_constraints(event_key, scenario)
            except FileNotFoundError:
                existing = []
            updated: list[CohortConstraints] = []
            replaced = False
            for entry in existing:
                if entry.cohort_age_group == age and entry.cohort_gender == gender:
                    updated.append(replace(entry, **{field: new_value}))
                    replaced = True
                else:
                    updated.append(entry)
            if not replaced:
                updated.append(
                    CohortConstraints(
                        cohort_age_group=age,
                        cohort_gender=gender,
                        **{field: new_value},
                    )
                )
            write_constraints(event_key, scenario, updated)
    except ScenarioLockError:
        st.error("Another tab is editing this scenario; try again shortly.")
        return
    _load_cohort_inputs.clear()


def _render_manual_add_form(
    *,
    division_name: str,
    division_names: list[str],
    age: str,
    gender: str,
    event_key: str,
    scenario: str,
    render_matcher_cache: dict[tuple[tuple[str, ...], str, bool], list[dict[str, Any]]],
    supabase_client: Any,
) -> None:
    """Render the +Add team form for one division."""
    reviewer_email = st.session_state.get("_reviewer_email", "")
    write_disabled = not reviewer_email
    form_key = f"_add_form_{age}_{gender}_{division_name}"
    with st.form(form_key):
        mode = st.radio(
            "Mode",
            options=("DB-match", "External"),
            horizontal=True,
            key=f"_add_mode_{age}_{gender}_{division_name}",
        )
        team_name = st.text_input("Team name", key=f"_add_name_{age}_{gender}_{division_name}")
        club_name = st.text_input("Club name", key=f"_add_club_{age}_{gender}_{division_name}")
        provider_team_id = st.text_input(
            "Provider team id (optional)",
            key=f"_add_pid_{age}_{gender}_{division_name}",
        )
        seed_options = division_names or [division_name]
        seed_index = seed_options.index(division_name) if division_name in seed_options else 0
        manual_seed_group = st.selectbox(
            "Manual seed group",
            options=seed_options,
            index=seed_index,
            help="Reassign before submit if you meant a different division",
            key=f"_add_seed_{age}_{gender}_{division_name}",
        )
        note = st.text_area("Note (External mode)", key=f"_add_note_{age}_{gender}_{division_name}")
        submitted = st.form_submit_button("Add", disabled=write_disabled)
    if not (submitted and reviewer_email):
        return
    # UUID-derived ids avoid collision (two operators adding the same team)
    # and key pollution (raw input flowing into widget keys / paths).
    event_registration_id = uuid.uuid4().hex[:16]
    team_ref = f"manual_{event_registration_id}"
    if mode == "DB-match":
        if supabase_client is None:
            st.warning("Database unavailable — cannot run live matcher.")
            return
        result = search_event_team_in_db(
            supabase_client,
            EventTeamSearchQuery(
                event_team_name=team_name,
                event_age_group=age,
                event_gender=gender,
                event_club_name=club_name or None,
                provider_team_id=provider_team_id or None,
            ),
            limit=3,
            cache=render_matcher_cache,
        )
        if not result.matches:
            st.info("No DB matches — switch to External mode if this team isn't in the DB.")
            return
        # First match is auto-accepted for v1; richer pick-list lands in a later shell.
        best = result.matches[0]
        append_override(
            event_key,
            scenario,
            build_override_record(
                ts=utc_now_iso(),
                actor=reviewer_email,
                scope="team",
                type="manual_add",
                team_ref=team_ref,
                before={},
                after={
                    "state": "resolved",
                    "team_id_master": best.get("team_id_master"),
                    "manual_seed_group": manual_seed_group,
                    "cohort_age_group": age,
                    "cohort_gender": gender,
                    "team_name": team_name,
                    "club_name": club_name,
                },
                reason="manual add — DB match",
            ),
        )
    else:  # External mode
        append_override(
            event_key,
            scenario,
            build_override_record(
                ts=utc_now_iso(),
                actor=reviewer_email,
                scope="team",
                type="manual_add",
                team_ref=team_ref,
                before={},
                after={
                    "state": "external",
                    "manual_seed_group": manual_seed_group,
                    "strength_mode": "median",
                    "note": note,
                    "cohort_age_group": age,
                    "cohort_gender": gender,
                    "team_name": team_name,
                    "club_name": club_name,
                },
                reason="manual add — external",
            ),
        )
    _load_registry_cached.clear()
    st.session_state[f"_add_open_{age}_{gender}_{division_name}"] = False
    st.rerun()


def _render_triage_right_pane(
    *,
    team_state: Any,
    resolved_team_by_id: dict[str, dict[str, Any]],
    registry_by_pid: dict[str, dict[str, Any]],
    division_groups: dict[str, list[str]],
    age: str,
    gender: str,
    event_key: str,
    scenario: str,
    supabase_client: Any,
) -> None:
    """Render the right pane: power ranking with Grouped/Flat toggle."""
    header_left, header_right = st.columns([4, 1])
    with header_left:
        st.markdown("**Ranked by power_score**")
    with header_right:
        if st.button(
            "↻ refresh ranking scores",
            key=f"_refresh_rank_{age}_{gender}",
            help="Cache TTL is 60 seconds; click to refetch immediately.",
        ):
            _cohort_rankings_score_map.clear()
            st.rerun()
    view_key = f"_rank_view_{age}_{gender}"
    view = st.radio(
        "View",
        options=("Grouped", "Flat"),
        index=0,
        horizontal=True,
        key=view_key,
        label_visibility="collapsed",
    )

    division_by_pid: dict[str, str] = {}
    for division_name, pids in division_groups.items():
        for pid in pids:
            division_by_pid[pid] = division_name

    rank_rows = _build_rank_rows(
        team_state=team_state,
        registry_by_pid=registry_by_pid,
        division_by_pid=division_by_pid,
        age=age,
        gender=gender,
        event_key=event_key,
        scenario=scenario,
        supabase_client=supabase_client,
    )

    if not rank_rows:
        st.info("No ranked teams yet.")
        return

    if view == "Grouped":
        rank_rows.sort(key=lambda r: (r["division"], -(r["score"] or -1e9)))
        prior_division: str | None = None
        for index, row in enumerate(rank_rows, start=1):
            if prior_division is not None and row["division"] != prior_division:
                st.markdown("<hr style='border-style:dashed'/>", unsafe_allow_html=True)
            _render_rank_row(index, row)
            prior_division = row["division"]
    else:
        rank_rows.sort(key=lambda r: -(r["score"] if r["score"] is not None else -1e9))
        for index, row in enumerate(rank_rows, start=1):
            _render_rank_row(index, row)


def _build_rank_rows(
    *,
    team_state: Any,
    registry_by_pid: dict[str, dict[str, Any]],
    division_by_pid: dict[str, str],
    age: str,
    gender: str,
    event_key: str,
    scenario: str,
    supabase_client: Any,
) -> list[dict[str, Any]]:
    """Build rank rows for the cohort: resolved+placeholder from rankings_full,
    externals from frozen medians or manual scores."""
    rows: list[dict[str, Any]] = []
    cohort_pids = set(division_by_pid.keys())

    resolved_team_ids: set[str] = set()
    pid_by_team_id: dict[str, str] = {}
    for pid in cohort_pids:
        projected = team_state.get(pid)
        registry_row = registry_by_pid.get(pid, {})
        # Externals don't show in rankings_full; their score comes from frozen medians.
        if projected and projected.state == "external":
            continue
        team_id_master = _resolve_team_id_master(projected, registry_row)
        if team_id_master:
            resolved_team_ids.add(team_id_master)
            pid_by_team_id[team_id_master] = pid

    rankings_score_by_team_id: dict[str, float] = {}
    if resolved_team_ids and supabase_client is not None:
        rankings_score_by_team_id = _cohort_rankings_score_map(age, gender, supabase_client)
        if not rankings_score_by_team_id:
            st.warning(f"rankings_full returned zero rows for {age}/{gender} — verify age_group casing.")

    # Hoist frozen-medians read above the per-team loop. Each external
    # team needs the medians map; reading per row would re-parse the JSON
    # on every iteration.
    try:
        medians_by_division = read_frozen_medians(event_key, scenario).medians_by_division
    except FileNotFoundError:
        medians_by_division = {}

    for pid in cohort_pids:
        projected = team_state.get(pid)
        registry_row = registry_by_pid.get(pid, {})
        division = division_by_pid.get(pid, "_unstructured")
        team_name = registry_row.get("event_team_name") or pid
        marker = ""
        score: float | None = None
        if projected and projected.state == "external":
            if projected.strength_mode == "exclude":
                continue
            if projected.strength_mode == "manual":
                score = projected.manual_power_score
                marker = "★"
            else:  # median or None
                seed_group = projected.manual_seed_group
                score = medians_by_division.get(seed_group) if seed_group else None
                marker = "★"
        else:
            team_id_master = _resolve_team_id_master(projected, registry_row)
            if team_id_master:
                score = rankings_score_by_team_id.get(team_id_master)
            if projected and projected.state == "placeholder":
                marker = "⚠"

        rows.append(
            {
                "pid": pid,
                "team_name": team_name,
                "division": division,
                "score": score,
                "marker": marker,
            }
        )
    return rows


def _render_rank_row(index: int, row: dict[str, Any]) -> None:
    """Render one ranked-team row in the right pane."""
    cols = st.columns([0.5, 3, 1, 0.5])
    with cols[0]:
        st.caption(f"{index}.")
    with cols[1]:
        st.markdown(f"**{row['team_name']}**")
        st.caption(row["division"])
    with cols[2]:
        score = row["score"]
        if score is None:
            st.caption("median pending — click Recompute")
        else:
            st.caption(f"{score:.2f}")
    with cols[3]:
        st.caption(row.get("marker") or "")


# ---------------------------------------------------------------------------
# Shell 05 — division structure inputs (editor + preview + add/remove)
# ---------------------------------------------------------------------------


def _read_all_cohorts(event_key: str, scenario: str) -> list[CohortStructure]:
    """Wrap ``read_structure`` so a missing CSV reads as an empty list."""
    try:
        return read_structure(event_key, scenario)
    except FileNotFoundError:
        return []


def _replace_division(
    divisions: tuple[DivisionStructure, ...],
    updated: DivisionStructure,
) -> tuple[DivisionStructure, ...]:
    """Swap the matching-name division in a tuple, leaving siblings verbatim."""
    return tuple(updated if d.name == updated.name else d for d in divisions)


def _update_cohort_divisions(
    cohorts: list[CohortStructure],
    age: str,
    gender: str,
    transform: Callable[[tuple[DivisionStructure, ...]], tuple[DivisionStructure, ...]],
) -> list[CohortStructure]:
    """Apply ``transform`` to one cohort's divisions tuple (immutable swap).

    Untouched cohorts pass through verbatim. If ``transform`` returns an
    empty tuple, the cohort is dropped entirely (no empty-cohort rows on
    disk). If the cohort doesn't exist yet, ``transform`` is invoked with
    an empty tuple and the result becomes the new cohort.
    """
    out: list[CohortStructure] = []
    matched = False
    for cohort in cohorts:
        if cohort.age_group == age and cohort.gender == gender:
            new_divisions = transform(cohort.divisions)
            if new_divisions:
                out.append(CohortStructure(age_group=age, gender=gender, divisions=new_divisions))
            matched = True
        else:
            out.append(cohort)
    if not matched:
        new_divisions = transform(())
        if new_divisions:
            out.append(CohortStructure(age_group=age, gender=gender, divisions=new_divisions))
    return out


def _validate_division(
    *,
    team_count: int,
    pool_sizes: tuple[int, ...],
    knockout: str,
    assigned_team_count: int,
) -> list[str]:
    """Run the spec §7 blocker rules + the knockout-template check.

    Returns a list of inline error messages (empty when the form passes).
    """
    errors: list[str] = []
    if team_count < assigned_team_count:
        errors.append(f"Reassign excess teams first ({assigned_team_count} assigned).")
    if pool_sizes and sum(pool_sizes) != team_count:
        errors.append(f"Pool sizes sum {sum(pool_sizes)} ≠ team count {team_count}.")
    knockout_error = _validate_knockout_format(knockout, pool_sizes)
    if knockout_error:
        errors.append(knockout_error)
    return errors


def _serpentine_assign(
    seeds: list[tuple[str, float | None]],
    pool_count: int,
) -> list[list[tuple[str, float | None]]]:
    """Distribute ``seeds`` across ``pool_count`` pools using a naive serpentine.

    NOT the optimizer's actual seeding — this is the v1 first-look heuristic
    callers warn about in the preview caption.
    """
    pools: list[list[tuple[str, float | None]]] = [[] for _ in range(pool_count)]
    if pool_count <= 0 or not seeds:
        return pools
    forward = True
    seed_idx = 0
    while seed_idx < len(seeds):
        order = range(pool_count) if forward else range(pool_count - 1, -1, -1)
        for pool_idx in order:
            if seed_idx >= len(seeds):
                break
            pools[pool_idx].append(seeds[seed_idx])
            seed_idx += 1
        forward = not forward
    return pools


def _build_pool_preview_seeds(
    *,
    division: DivisionStructure,
    pids: list[str],
    cohort_records: list[dict[str, Any]],
    team_state: Any,
    registry_by_pid: dict[str, dict[str, Any]],
    rankings_score_map: dict[str, float],
    medians_by_division: dict[str, float],
) -> list[tuple[str, float | None]]:
    """Build the (team_name, score) seed list for one division's preview.

    Exclude-mode externals are dropped. Manual-mode externals use the
    operator-entered ``manual_power_score``. Median-mode externals fall
    back to ``frozen_medians`` keyed by ``manual_seed_group`` (default to
    this division's name when the override is silent).
    """
    record_by_pid = {
        str(record.get("provider_team_id") or "").strip(): record
        for record in cohort_records
        if record.get("provider_team_id")
    }
    seeds: list[tuple[str, float | None]] = []
    for pid in pids:
        record = record_by_pid.get(pid, {})
        registry_row = registry_by_pid.get(pid, {})
        projected = team_state.get(pid)
        team_name = registry_row.get("event_team_name") or record.get("team_name") or pid
        score: float | None = None
        if projected and projected.state == "external":
            if projected.strength_mode == "exclude":
                continue
            if projected.strength_mode == "manual":
                score = projected.manual_power_score
            else:
                seed_group = projected.manual_seed_group or division.name
                score = medians_by_division.get(seed_group)
        else:
            team_id_master = _resolve_team_id_master(projected, registry_row)
            if team_id_master:
                score = rankings_score_map.get(team_id_master)
        seeds.append((str(team_name), score))
    seeds.sort(key=lambda item: -(item[1] if item[1] is not None else -1e9))
    return seeds


def _render_division_editor(
    division: DivisionStructure,
    *,
    age: str,
    gender: str,
    event_key: str,
    scenario: str,
    assigned_team_count: int,
) -> None:
    """Render the per-division editor card + Apply / ✕ Remove submit buttons.

    In **backtest mode** the structure is gotsport-authoritative, so the
    editor degrades to a read-only summary line — operators link/assign
    teams without touching division shape. Seeding mode keeps the full
    form (pool counts, knockout template, ✕ Remove, Apply pool sizes).
    """
    if _is_backtest_mode():
        pool_sizes_chip = " / ".join(str(size) for size in division.pool_sizes) if division.pool_sizes else "—"
        knockout_chip = division.advancement or "—"
        st.caption(
            f"**{division.name}** · {division.team_count} teams · pools {pool_sizes_chip} · {knockout_chip}"
        )
        return

    base = f"{age}_{gender}_{division.name}"
    form_key = f"_div_form_{base}"

    persisted_pool_count = max(1, len(division.pool_sizes))
    teams_min = max(1, assigned_team_count)
    teams_value = max(division.team_count, teams_min)
    pools_value = min(persisted_pool_count, max(1, teams_value))
    min_pool_size = min(division.pool_sizes) if division.pool_sizes else max(1, teams_value // max(1, pools_value))
    default_pool_play = max(0, max(1, min_pool_size) - 1)

    knockout_default = division.advancement or "ROUND_ROBIN"
    if knockout_default not in _ALL_KNOCKOUT_TEMPLATES:
        knockout_default = "ROUND_ROBIN"
    knockout_index = list(_ALL_KNOCKOUT_TEMPLATES).index(knockout_default)

    # ✕ Remove sits outside the form so Enter inside any input always
    # triggers Apply (Streamlit's Enter binding follows form_submit_button
    # registration order). Plain ``st.button`` only fires on click, so the
    # plan's "Streamlit doesn't fire it on field-edit" property still holds.
    header_left, header_right = st.columns([6, 0.5])
    with header_right:
        remove_clicked = st.button(
            "✕",
            key=f"_div_remove_{base}",
            help="Remove this division",
        )

    with st.form(form_key, clear_on_submit=False):
        c_name, c_teams, c_pools, c_pgames, c_ko = st.columns([3, 1, 1, 1, 2])
        with c_name:
            st.text_input(
                "Name",
                value=division.name,
                disabled=True,
                help="Rename is deferred to a later shell",
                key=f"_div_name_{base}",
            )
        with c_teams:
            team_count_input = st.number_input(
                "Teams",
                min_value=teams_min,
                value=teams_value,
                step=1,
                key=f"_div_team_count_{base}",
            )
        with c_pools:
            pool_count_input = st.number_input(
                "Pools",
                min_value=1,
                max_value=max(1, int(team_count_input)),
                value=pools_value,
                step=1,
                key=f"_div_pool_count_{base}",
            )
        with c_pgames:
            pool_play_max = max(0, max(1, min_pool_size) - 1)
            st.number_input(
                "Pool games",
                min_value=0,
                max_value=max(0, pool_play_max),
                value=min(default_pool_play, max(0, pool_play_max)),
                step=1,
                help="Data-model only in v1; v2 wires the simulator.",
                key=f"_div_pool_games_{base}",
            )
        with c_ko:
            knockout_input = st.selectbox(
                "Knockout",
                options=_ALL_KNOCKOUT_TEMPLATES,
                index=knockout_index,
                format_func=_knockout_format_label,
                key=f"_div_knockout_{base}",
            )
        apply_clicked = st.form_submit_button(
            "Apply",
            type="primary",
            use_container_width=True,
        )

    if apply_clicked:
        new_team_count = int(team_count_input)
        new_pool_count = int(pool_count_input)
        new_pool_sizes = tuple(_derive_pool_sizes(new_team_count, new_pool_count))
        errors = _validate_division(
            team_count=new_team_count,
            pool_sizes=new_pool_sizes,
            knockout=knockout_input,
            assigned_team_count=assigned_team_count,
        )
        if errors:
            for msg in errors:
                st.error(msg)
        else:
            updated_division = DivisionStructure(
                name=division.name,
                team_count=new_team_count,
                pool_sizes=new_pool_sizes,
                advancement=knockout_input,
            )
            updated_cohorts = _update_cohort_divisions(
                _read_all_cohorts(event_key, scenario),
                age,
                gender,
                lambda divs, _new=updated_division: _replace_division(divs, _new),
            )
            if _persist_structure(event_key, scenario, updated_cohorts):
                _load_cohort_inputs.clear()
                st.success("Saved.")
                st.rerun()

    if remove_clicked:
        if assigned_team_count > 0:
            st.error("Reassign teams in this division before removing it.")
        else:
            updated_cohorts = _update_cohort_divisions(
                _read_all_cohorts(event_key, scenario),
                age,
                gender,
                lambda divs, _name=division.name: tuple(d for d in divs if d.name != _name),
            )
            if _persist_structure(event_key, scenario, updated_cohorts):
                _load_cohort_inputs.clear()
                st.rerun()

    pool_sizes_chip = " / ".join(str(size) for size in division.pool_sizes) if division.pool_sizes else "—"
    st.caption(f"Pool sizes: {pool_sizes_chip}")

    pool_sizes_form_key = f"_pool_sizes_form_{base}"
    with st.form(pool_sizes_form_key, clear_on_submit=False):
        cols_pool = st.columns([4, 1])
        with cols_pool[0]:
            pool_sizes_text = st.text_input(
                "Pool sizes (comma-separated)",
                value=", ".join(str(size) for size in division.pool_sizes),
                key=f"_div_pool_sizes_{base}",
                placeholder="e.g. 4, 4, 3",
                help="Override the auto-derived split.",
            )
        with cols_pool[1]:
            pool_sizes_clicked = st.form_submit_button("Apply pool sizes")
    if pool_sizes_clicked:
        try:
            parsed = tuple(int(token.strip()) for token in pool_sizes_text.split(",") if token.strip())
        except ValueError:
            st.error("Pool sizes must be comma-separated integers.")
            return
        if not parsed:
            st.error("Pool sizes cannot be empty.")
            return
        if sum(parsed) != division.team_count:
            st.error(f"Pool sizes sum {sum(parsed)} ≠ team count {division.team_count}.")
            return
        if division.pool_sizes and len(parsed) != len(division.pool_sizes):
            st.error(
                f"Pool count {len(parsed)} doesn't match the form's pool count "
                f"{len(division.pool_sizes)}; update Pools field via Apply first."
            )
            return
        updated_division = DivisionStructure(
            name=division.name,
            team_count=division.team_count,
            pool_sizes=parsed,
            advancement=division.advancement,
        )
        updated_cohorts = _update_cohort_divisions(
            _read_all_cohorts(event_key, scenario),
            age,
            gender,
            lambda divs, _new=updated_division: _replace_division(divs, _new),
        )
        if _persist_structure(event_key, scenario, updated_cohorts):
            _load_cohort_inputs.clear()
            st.success("Saved.")
            st.rerun()


def _render_pool_preview(
    division: DivisionStructure,
    *,
    age: str,
    gender: str,
    pids: list[str],
    cohort_records: list[dict[str, Any]],
    team_state: Any,
    registry_by_pid: dict[str, dict[str, Any]],
    medians_by_division: dict[str, float],
    supabase_client: Any,
) -> None:
    """Render the collapsed serpentine-seed preview below the division card.

    Pool count is read from the persisted ``DivisionStructure`` — operators
    must Apply the editor form for the preview to reflect a new pool count
    (Streamlit forms hold widget edits internal to the form until submit).
    """
    pool_count = max(1, len(division.pool_sizes))

    with st.expander(f"Preview pools — {division.name}", expanded=False):
        rankings_score_map = _cohort_rankings_score_map(age, gender, supabase_client)
        seeds = _build_pool_preview_seeds(
            division=division,
            pids=pids,
            cohort_records=cohort_records,
            team_state=team_state,
            registry_by_pid=registry_by_pid,
            rankings_score_map=rankings_score_map,
            medians_by_division=medians_by_division,
        )
        if not seeds:
            st.info("No teams to preview yet.")
            return
        st.caption("Preview shows naive serpentine seed; optimizer's final placement may differ.")
        pools = _serpentine_assign(seeds, pool_count)
        for idx, pool in enumerate(pools):
            st.markdown(f"**Pool {idx + 1}** ({len(pool)} teams)")
            for name, score in pool:
                score_str = f"{score:.2f}" if score is not None else "—"
                st.caption(f"• {name} ({score_str})")


def _render_add_division_form(
    *,
    age: str,
    gender: str,
    event_key: str,
    scenario: str,
    structure_for_cohort: CohortStructure | None,
    cohort_records: list[dict[str, Any]],
) -> None:
    """Render the inline ``+ Add division`` form above a cohort's division list."""
    base = f"{age}_{gender}"
    existing = structure_for_cohort.divisions if structure_for_cohort else ()
    bootstrap = not existing
    default_name = "Premier" if bootstrap else f"Division {len(existing) + 1}"

    with st.form(f"_add_div_form_{base}", clear_on_submit=True):
        cols = st.columns([4, 1])
        with cols[0]:
            new_name = st.text_input(
                "New division name",
                value=default_name,
                key=f"_add_div_name_{base}",
                placeholder="New division name",
                label_visibility="collapsed",
            )
        with cols[1]:
            submitted = st.form_submit_button("+ Add division")
    if not submitted:
        return
    name = (new_name or "").strip()
    if not name:
        st.error("Name is required.")
        return
    if name in {d.name for d in existing}:
        st.error("Division name already exists in this cohort.")
        return
    if bootstrap and name == "Premier":
        team_count = len(cohort_records)
        pool_sizes: tuple[int, ...] = (team_count,) if team_count > 0 else (0,)
    else:
        team_count = 0
        pool_sizes = (0,)
    new_division = DivisionStructure(
        name=name,
        team_count=team_count,
        pool_sizes=pool_sizes,
        advancement=None,
    )
    updated_cohorts = _update_cohort_divisions(
        _read_all_cohorts(event_key, scenario),
        age,
        gender,
        lambda divs, _new=new_division: divs + (_new,),
    )
    if _persist_structure(event_key, scenario, updated_cohorts):
        _load_cohort_inputs.clear()
        st.rerun()


def _render_constraints_panel(
    *,
    age: str,
    gender: str,
    event_key: str,
    scenario: str,
    current_constraints: CohortConstraints,
) -> None:
    """Render the per-cohort seeding-preferences panel.

    Each widget uses an ``on_change`` callback so a one-toggle change
    persists immediately — operators can't forget to click Apply on a
    single-checkbox flip. The callback wraps the write in
    ``acquire_scenario_lock`` (see ``_persist_constraint``).
    """
    base = f"{age}_{gender}"
    k_club = f"_constraint_club_{base}"
    k_coach = f"_constraint_coach_{base}"
    k_state = f"_constraint_state_{base}"
    k_scope = f"_constraint_scope_{base}"
    with st.expander("Seeding preferences", expanded=False):
        st.info("Constraints persist for Report Card metrics; v2 wires the optimizer.")
        st.checkbox(
            "Avoid same-club matchups in pool play + first KO",
            value=current_constraints.avoid_same_club_early,
            key=k_club,
            on_change=_persist_constraint,
            args=(event_key, scenario, age, gender, "avoid_same_club_early", k_club),
        )
        st.caption("(data-model only — v2 wires optimizer)")
        st.checkbox(
            "Avoid same-coach matchups (null-safe)",
            value=current_constraints.avoid_same_coach_early,
            key=k_coach,
            on_change=_persist_constraint,
            args=(event_key, scenario, age, gender, "avoid_same_coach_early", k_coach),
        )
        st.caption("(data-model only — v2 wires optimizer)")
        st.checkbox(
            "Avoid same-state in same pool",
            value=current_constraints.avoid_same_state_pool,
            key=k_state,
            on_change=_persist_constraint,
            args=(event_key, scenario, age, gender, "avoid_same_state_pool", k_state),
        )
        st.caption("(data-model only — v2 wires optimizer)")
        scope_index = (
            _REMATCH_SCOPES.index(current_constraints.rematch_avoidance_scope)
            if current_constraints.rematch_avoidance_scope in _REMATCH_SCOPES
            else 0
        )
        st.selectbox(
            "Rematch avoidance scope",
            options=_REMATCH_SCOPES,
            index=scope_index,
            key=k_scope,
            on_change=_persist_constraint,
            args=(event_key, scenario, age, gender, "rematch_avoidance_scope", k_scope),
        )
        st.caption("(data-model only — v2 wires optimizer)")


def _render_advanced_settings(
    meta: EventMetadata,
    *,
    event_key: str,
    scenario: str,
) -> None:
    """Render the event-level advanced-settings form inside the ⚙ banner expander.

    No scenario lock — ``event_metadata.json`` is per-event (not per-scenario),
    so ``acquire_scenario_lock`` would be the wrong scope. The single-file
    write is atomic via ``_io.write_json``'s ``.tmp`` + ``os.replace`` pattern;
    last-write-wins between two concurrent operators is acceptable for v1.
    """
    extras = meta.extras or {}
    prior_snapshot = extras.get("ranking_snapshot_date")
    snapshot_default: date
    if isinstance(prior_snapshot, str):
        try:
            snapshot_default = date.fromisoformat(prior_snapshot)
        except ValueError:
            snapshot_default = _default_snapshot(meta.event_start_date)
    else:
        snapshot_default = _default_snapshot(meta.event_start_date)

    with st.form(f"_advanced_settings_form_{event_key}", clear_on_submit=False):
        st.caption(f"Scenario: {scenario}")
        model_version_pin = st.text_input(
            "Model version pin",
            value=str(extras.get("model_version_pin") or "poisson_draw_gate_v1"),
            help="Frozen ranking-engine version for this run.",
        )
        ranking_snapshot_date = st.date_input(
            "Ranking snapshot date",
            value=snapshot_default,
            help="Defaults to the day before kickoff.",
        )
        st.number_input(
            "Simulation runs",
            value=1,
            disabled=True,
            help="Monte Carlo deferred to v2",
        )
        capped_gd_limit = st.number_input(
            "Capped GD limit",
            min_value=1,
            value=int(extras.get("capped_gd_limit", 3) or 3),
            step=1,
        )
        series_id_default = meta.series_id or meta.event_slug or ""
        series_id = st.text_input(
            "Series ID",
            value=str(series_id_default),
            help=(
                "Auto-populates from event_slug on first event in a series; user-set on subsequent events to link them."
            ),
        )
        preset_id = st.selectbox(
            "Balance score preset",
            options=("default",),
            index=0,
            help="Additional presets in v2.",
        )
        submitted = st.form_submit_button("Apply", type="primary")
    if not submitted:
        return
    if ranking_snapshot_date is None:
        st.error("Ranking snapshot date is required.")
        return
    new_extras = dict(extras)
    new_extras["model_version_pin"] = model_version_pin
    new_extras["ranking_snapshot_date"] = ranking_snapshot_date.isoformat()
    new_extras["capped_gd_limit"] = int(capped_gd_limit)
    new_extras["balance_score_weights"] = {"preset_id": preset_id}
    new_extras.pop("series_id", None)  # canonical home is meta.series_id
    new_meta = replace(meta, series_id=series_id or None, extras=new_extras)
    write_event_metadata(event_key, new_meta)
    st.success("Saved.")
    st.rerun()


# ---------------------------------------------------------------------------
# Cohort containers
# ---------------------------------------------------------------------------


@st.cache_data(ttl=60)
def _build_registry_by_pid(event_key: str, scenario: str) -> dict[str, Any]:
    """Cache the registry as ``provider_id → TeamRegistryEntry``.

    Cache key is ``(event_key, scenario)`` — the registry CSV is read at
    most once per scenario per minute. Intake-time changes to the registry
    surface in the audit panel within 60s; acceptable v1 staleness.

    The dict is consumed by ``override_in_cohort`` (Step 6) to filter
    scenario-level overrides down to the active cohort. Without it, every
    override of types ``assign``, ``external``, ``merge``, etc. is
    silently filtered out (the predicate returns False whenever the
    registry lookup misses).
    """
    registry = read_registry(event_key, scenario)
    return {pid: entry for entry in registry if (pid := registry_provider_id(entry))}


# Exceptions the dropdown-filter loop tolerates when probing run-dir
# metadata. A bare triple-quoted string here would be auto-rendered by
# Streamlit magic at the top of the page on every rerun — keep this as a
# `#` comment so it stays out of the UI. Covers I/O, JSON, and
# structural-shape errors so a corrupt/legacy run_metadata.json can't
# crash the previous-runs dropdown render.
_METADATA_READ_ERRORS: tuple[type[BaseException], ...] = (
    FileNotFoundError,
    json.JSONDecodeError,
    OSError,
    AttributeError,
    KeyError,
    TypeError,
    ValueError,
)


def _read_ended_at(event_key: str, scenario: str, run_id_: str) -> str | None:
    """Return ``run_metadata.json["ended_at"]`` or ``None`` if absent.

    Not cached — local file read (single ``read_json`` per call,
    sub-millisecond) and any TTL window introduces a stale-label window
    when a new run completes. Raises ``_METADATA_READ_ERRORS`` on missing
    / corrupt / shape-invalid metadata; the dropdown filter catches those
    to exclude unreadable runs.
    """
    payload = read_json(_run_dir(event_key, scenario, run_id_) / "run_metadata.json")
    return payload.get("ended_at")


def _read_optimized_score(event_key: str, scenario: str, run_id_: str) -> float | None:
    """Return ``balance_score.optimized`` from a persisted Report Card.

    Returns ``None`` when ``report_card.done`` is absent (no Report Card
    has been computed yet) or when the ``comparison.json`` is corrupt,
    schema-mismatched, or shape-invalid. The defensive read via
    ``safe_read_comparison_json`` is REQUIRED because the dropdown's
    ``format_func`` lambda calls this for EVERY visible run on every
    render — a single corrupt ``comparison.json`` in the run history
    would otherwise explode the entire dropdown.
    """
    run_dir_path = _run_dir(event_key, scenario, run_id_)
    if not (run_dir_path / "report_card.done").exists():
        return None
    card = safe_read_comparison_json(run_dir_path / "comparison.json")
    return card.balance_score.optimized if card is not None else None


def _render_cohort_completed_run(
    *,
    event_key: str,
    scenario: str,
    age: str,
    gender: str,
    run_id: str,
) -> None:
    """Render the Shell 08 completed-run surface for one cohort.

    Body order: previous-runs dropdown → lazy-load Report Card → header
    line → action row (Export HTML / CSV / JSON + Re-run) → inline iframe
    embed → collapsed override-audit panel.
    """
    # --- Previous-runs dropdown ------------------------------------------
    # Build the cohort-scoped run list and prefetch the per-run label inputs
    # in a single pass. The selectbox ``format_func`` lambda fires for every
    # visible run on every Streamlit rerun; doing dict lookups against this
    # cache keeps the dropdown render O(N) file reads instead of O(N) per
    # rerun. Skip ``_read_ended_at``-unreadable runs (corrupt/legacy) so the
    # widget never offers an option that would crash on selection.
    cohort_prefix = f"{age}_{gender.lower()}_"
    all_runs = [r for r in list_runs(event_key, scenario, completed_only=True) if r.startswith(cohort_prefix)]
    runs: list[str] = []
    label_inputs: dict[str, tuple[str | None, float | None]] = {}
    for r in reversed(all_runs):
        try:
            ended_at_value = _read_ended_at(event_key, scenario, r)
        except _METADATA_READ_ERRORS:
            continue
        label_inputs[r] = (ended_at_value, _read_optimized_score(event_key, scenario, r))
        runs.append(r)

    # Reconcile stale ``run_id`` BEFORE selectbox renders. Streamlit raises
    # ``StreamlitAPIException`` when the keyed widget's session-state value
    # is not in ``options`` — pop and rerun rather than crash.
    if not runs:
        st.session_state.current_run_id_by_cohort.pop((age, gender), None)
        st.session_state.pop(f"prev_run_select_{age}_{gender}", None)
        st.warning("No readable runs for this cohort. Click Run backtest to start fresh.")
        st.rerun()
    if run_id not in runs:
        st.session_state.current_run_id_by_cohort[(age, gender)] = runs[0]
        st.session_state.pop(f"prev_run_select_{age}_{gender}", None)
        st.rerun()

    if len(runs) > 1:
        select_key = f"prev_run_select_{age}_{gender}"
        # Synchronize the keyed widget's session-state value to the loaded
        # ``run_id`` BEFORE the widget renders — once the widget exists, its
        # session-state value takes precedence over any ``index=`` argument,
        # so the explicit pre-write is the source of truth.
        if st.session_state.get(select_key) != run_id:
            st.session_state[select_key] = run_id
        selected = st.selectbox(
            label=f"Run for {gender} {age}",
            options=runs,
            format_func=lambda r: format_run_label(r, *label_inputs[r]),
            key=select_key,
        )
        if selected != run_id:
            st.session_state.current_run_id_by_cohort[(age, gender)] = selected
            st.rerun()

    # --- Lazy compute / load ---------------------------------------------
    try:
        with st.spinner("Generating Report Card..."):
            card = ensure_report_card(event_key, scenario, run_id)
    except RunLockError:
        st.warning("Another tab is generating this run's Report Card. Reload in 30s.")
        return
    except ReportCardError as exc:
        st.error(f"Cannot load Report Card: {exc}")
        return

    # --- Header line -----------------------------------------------------
    run_dir_path = _run_dir(event_key, scenario, run_id)
    ended_at, _ = label_inputs.get(run_id, (None, None))
    if ended_at is None:
        try:
            done_payload = read_json(run_dir_path / "done.json")
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            done_payload = {}
        ended_at = done_payload.get("promoted_at")
    ended_at_display = format_run_timestamp(ended_at)
    if card.balance_score.actual is not None:
        bs_summary = f"{card.balance_score.actual:.0f} → {card.balance_score.optimized:.0f}"
    else:
        bs_summary = f"{card.balance_score.optimized:.0f} (actual n/a)"
    st.caption(f"Last run · ended {ended_at_display} · Balance Score {bs_summary}")

    # --- Action row ------------------------------------------------------
    filenames = derive_export_filenames(card)
    html_path = run_dir_path / "comparison.html"
    if html_path.exists():
        html_data: bytes = html_path.read_bytes()
    else:
        html_data = render_html(card, mode="standalone").encode("utf-8")

    c1, c2, c3, c4, _ = st.columns([1, 1, 1, 1, 2])
    with c1:
        st.download_button(
            "Export HTML",
            data=html_data,
            file_name=filenames["html"],
            mime="text/html",
            key=f"export_html_{age}_{gender}",
        )
    with c2:
        try:
            zip_data = zip_run_csvs(run_dir_path)
        except FileNotFoundError as exc:
            st.error(f"CSV export unavailable: {exc}")
        else:
            st.download_button(
                "Export CSV",
                data=zip_data,
                file_name=filenames["zip"],
                mime="application/zip",
                key=f"export_csv_{age}_{gender}",
            )
    with c3:
        st.download_button(
            "Export JSON",
            data=(run_dir_path / "comparison.json").read_bytes(),
            file_name=filenames["json"],
            mime="application/json",
            key=f"export_json_{age}_{gender}",
        )
    with c4:
        if st.button(
            "Re-run",
            key=f"rerun_{age}_{gender}",
            help="Clear this cohort's loaded run and show the Run button again.",
        ):
            st.session_state.current_run_id_by_cohort.pop((age, gender), None)
            st.session_state.pop(f"prev_run_select_{age}_{gender}", None)
            st.rerun()

    # --- Inline iframe embed ---------------------------------------------
    # ``mode="standalone"`` is required so the inline ``<style>`` block ships
    # inside the iframe; ``mode="embedded"`` returns a CSS-less fragment.
    # ``show_override_audit=False`` suppresses the in-iframe ``<details>``
    # because the outside expander below is the single source of truth.
    components.html(
        render_html(card, mode="standalone", show_override_audit=False),
        height=900,
        scrolling=True,
    )

    # --- Override audit panel --------------------------------------------
    per_run_rows = [project_audit_row(entry.record) for entry in card.override_audit]
    scenario_records = load_overrides(event_key, scenario)
    registry_by_pid = _build_registry_by_pid(event_key, scenario)
    scenario_rows = [
        project_audit_row(record)
        for record in scenario_records
        if override_in_cohort(record, age, gender, registry_by_pid)
    ]
    with st.expander(
        f"Override log · {len(per_run_rows)} per-run · {len(scenario_rows)} scenario",
        expanded=False,
    ):
        st.markdown("**Per-run overrides**")
        if per_run_rows:
            st.dataframe(pd.DataFrame(per_run_rows), width="stretch")
            st.caption("ⓘ Per-override delta_balance_score is deferred to v2.")
        else:
            st.caption("No per-run overrides applied for this cohort.")

        st.markdown("**Scenario-level overrides**")
        if scenario_rows:
            st.dataframe(pd.DataFrame(scenario_rows), width="stretch")
        else:
            st.caption("No scenario-level overrides for this cohort.")


def _render_cohort_run_control(
    *,
    event_key: str,
    scenario: str,
    age: str,
    gender: str,
    supabase_client: Any,
) -> None:
    """Render the per-cohort Run-backtest control + warnings + status block.

    Three branches:

    - A run is already loaded for this cohort → caption only; Shell 08's
      "Re-run" control clears the entry.
    - Preflight has blockers → disabled button with the blocker list as
      hover help.
    - Preflight is clean → enabled button + warning chips + scenario-lock
      notice. On click, runs synchronously via :func:`execute_run`,
      streaming PHASE/PROGRESS markers into ``st.status``.
    """
    button_key = f"run_btn_{age}_{gender}"
    cohort_run_id = st.session_state.current_run_id_by_cohort.get((age, gender))
    if cohort_run_id is not None:
        _render_cohort_completed_run(
            event_key=event_key,
            scenario=scenario,
            age=age,
            gender=gender,
            run_id=cohort_run_id,
        )
        return

    result = preflight(event_key, scenario, age, gender, supabase_client=supabase_client)
    if result.blockers:
        st.button(
            "Run backtest",
            disabled=True,
            help="\n".join(result.blockers),
            key=button_key,
        )
        return

    clicked = st.button("Run backtest", type="primary", key=button_key)
    for warning in result.warnings:
        st.caption(f"⚠ {warning}")
    st.caption("Run holds a per-scenario lock for the duration; other tabs cannot save while it runs.")
    if not clicked:
        return

    with st.status(f"Running {gender} {age} backtest", expanded=True, state="running") as status_box:

        def on_event(ev: ProgressEvent) -> None:
            # The orchestrator emits PHASE/PROGRESS events with phase set
            # (drives the status label) and buffered plain-text events with
            # phase=None (rendered as a log block).
            if ev.phase is not None:
                pct_suffix = f" · {ev.percent}%" if ev.percent is not None else ""
                status_box.update(label=f"{ev.phase}{pct_suffix}")
            elif ev.raw_line:
                st.code(ev.raw_line, language="text")

        try:
            outcome = execute_run(
                event_key,
                scenario,
                age,
                gender,
                on_event=on_event,
            )
        except ScenarioLockError as exc:
            status_box.update(label=f"Scenario locked: {exc}", state="error")
            return
        except RunStateError as exc:
            status_box.update(label=f"Cannot stage run: {exc}", state="error")
            return
        if outcome.state == "completed":
            st.session_state.current_run_id_by_cohort[(age, gender)] = outcome.run_dir.name
            status_box.update(label="Completed", state="complete")
            st.rerun()
        else:
            status_box.update(label=f"Failed: {outcome.error or 'unknown'}", state="error")


def _render_bracket_report(records: list[dict[str, Any]], *, event_key: str) -> None:
    """Render gotsport-style per-bracket standings + knockout for one cohort.

    Mirrors gotsport's per-tier standings page (the GG.docx layout): one
    blue-banner section per tier (group_id) carrying the division label,
    pool standings tables per bracket (Bracket A / Bracket B / ...), and
    a Knockout / Showcase block listing cross-pool matches with a starred
    winner score. Driven by ``intake/pool_assignments.json`` +
    ``intake/standings.jsonl`` + ``intake/game_results.jsonl``; silently
    no-ops when those artifacts are absent (e.g. partial scrapes) so the
    cohort UI never breaks on missing optional data.
    """
    group_ids = sorted({str(r["group_id"]) for r in records if r.get("group_id") is not None})
    if not group_ids:
        return
    try:
        tiers = _cached_tier_reports(event_key, tuple(group_ids))
    except (FileNotFoundError, SchemaVersionError):
        return
    for tier in tiers:
        _render_tier(tier)


def _render_tier(tier: TierReport) -> None:
    title = tier.title or f"Group {tier.group_id}"
    st.markdown(
        f"<div style='background:#2563eb;color:white;padding:6px 12px;"
        f"border-radius:4px 4px 0 0;font-weight:600;margin-top:12px'>{html.escape(title)}</div>",
        unsafe_allow_html=True,
    )
    for pool in tier.pool_play:
        _render_pool_table(pool)
    if tier.knockout:
        _render_knockout(tier.knockout)


def _render_pool_table(pool: PoolTable) -> None:
    st.markdown(
        f"<div style='background:#3b82f6;color:white;padding:4px 10px;"
        f"font-weight:600;font-size:0.9em'>Bracket {html.escape(pool.bracket_label)}</div>",
        unsafe_allow_html=True,
    )
    if not pool.rows:
        st.caption("No standings reported yet.")
        return
    df = pd.DataFrame(
        [
            {
                "Rank": s.rank,
                "Team": s.team_name,
                "MP": s.matches_played,
                "W": s.wins,
                "L": s.losses,
                "D": s.draws,
                "GF": s.goals_for,
                "GA": s.goals_against,
                "GD": s.goal_diff,
                "PTS": s.points,
            }
            for s in pool.rows
        ]
    )
    st.dataframe(df, width="stretch", hide_index=True)


def _render_knockout(matches: tuple[KnockoutMatch, ...]) -> None:
    st.markdown(
        f"<div style='background:#3b82f6;color:white;padding:4px 10px;"
        f"font-weight:600;font-size:0.9em'>Knockout / Showcase · {len(matches)} matches</div>",
        unsafe_allow_html=True,
    )
    for match in matches:
        _render_knockout_match(match)


def _render_knockout_match(match: KnockoutMatch) -> None:
    home_star = "★ " if match.winner == "home" else ""
    away_star = "★ " if match.winner == "away" else ""
    score_text = f"{match.home_score}–{match.away_score}" if match.winner != "tbd" else "vs"
    location = match.location or "TBD"
    when = " ".join(part for part in (match.date_text, match.time_text) if part) or "TBD"
    st.markdown(
        f"<div style='border:1px solid #e5e7eb;padding:8px 12px;margin:0 0 6px 0;font-size:0.9em'>"
        f"<div style='color:#6b7280;font-size:0.85em'>"
        f"Match #{html.escape(match.match_id)} · {html.escape(location)} · {html.escape(when)}"
        f"</div>"
        f"<div>{home_star}{html.escape(match.home_team_name)} "
        f"<strong>{html.escape(score_text)}</strong> "
        f"{away_star}{html.escape(match.away_team_name)}</div>"
        f"</div>",
        unsafe_allow_html=True,
    )


def _render_cohort_containers(
    cohorts: dict[tuple[str, str], list[dict[str, Any]]],
    sorted_keys: list[tuple[str, str]],
    tints: dict[tuple[str, str], tuple[str, str]],
    *,
    event_key: str,
    scenario: str,
    event_name: str,
    supabase_client: Any,
) -> None:
    """Render one collapsible container per cohort with the triage surface."""
    for cohort in sorted_keys:
        age, gender = cohort
        records = cohorts[cohort]
        level, note = tints[cohort]
        team_count = len(records)
        # Count distinct gotsport ``group_name`` values — the actual division
        # tier the team played in (Red/White/Blue/Washington/etc.). Counting
        # ``bracket_name`` instead conflates a U13 play-up's U14B bracket
        # with their natural cohort's U13B bracket and double-counts.
        division_count = len({r.get("group_name") or "" for r in records if r.get("group_name")})
        dot = _TINT_DOT[level]
        display_label = f"{_display_gender(gender)} {age.upper()}"
        toggle_label = (
            f"**{display_label}** · {team_count} teams · {division_count} divs · {dot} Teams ✓ · {dot} Games · {note}"
        )
        toggle_key = _cohort_toggle_key(age, gender)
        st.session_state.setdefault(toggle_key, False)
        st.toggle(toggle_label, key=toggle_key)
        if st.session_state[toggle_key]:
            # DOM anchor for post-link auto-scroll: when the operator clicks
            # Use this team / Accept deep inside this cohort, the rerun
            # otherwise lands them at the bottom of the page (the per-team
            # expander collapsed, shortening the page). The flash drainer
            # scrolls back to this anchor.
            st.markdown(
                f"<div id='{_cohort_anchor_id(age, gender)}'></div>",
                unsafe_allow_html=True,
            )
            with st.container(border=True):
                _render_triage(
                    records,
                    age=age,
                    gender=gender,
                    event_key=event_key,
                    scenario=scenario,
                    event_name=event_name,
                    supabase_client=supabase_client,
                )
                _render_bracket_report(records, event_key=event_key)
                _render_cohort_run_control(
                    event_key=event_key,
                    scenario=scenario,
                    age=age,
                    gender=gender,
                    supabase_client=supabase_client,
                )


def main() -> None:
    """Top-level render flow."""
    _init_session_state()
    _render_pending_flashes()
    supabase_client = get_database()
    _render_rekey_banner()
    _render_intake_section(supabase_client)
    _render_registry_persist_results()

    key = st.session_state.event_key
    if not key:
        st.info("Scrape a new event or pick one from the resume dropdown.")
        return

    try:
        meta = read_event_metadata(key)
    except (FileNotFoundError, SchemaVersionError) as exc:
        st.error(f"Cannot read event metadata for {key}: {exc}")
        return

    records = load_raw_scrape(key)
    _render_event_banner(
        meta,
        records,
        event_key=key,
        scenario=st.session_state.scenario_name,
    )
    _render_event_goal_summary(key)
    if not records:
        st.warning("No teams in this event's raw_scrape.jsonl yet.")
        return

    cohorts = _group_cohorts(records)
    sorted_keys = sorted(cohorts.keys(), key=_cohort_sort_key)
    _render_reviewer_email_input()
    tints = _render_cohort_summary(
        cohorts,
        sorted_keys,
        event_name=meta.event_name,
        supabase_client=supabase_client,
        event_key_value=key,
    )
    _render_cohort_containers(
        cohorts,
        sorted_keys,
        tints,
        event_key=key,
        scenario=st.session_state.scenario_name,
        event_name=meta.event_name,
        supabase_client=supabase_client,
    )


if __name__ == "__main__":
    main()
