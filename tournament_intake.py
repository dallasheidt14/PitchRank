"""MatchBalance · Backtest Intake — Streamlit triage app.

Sibling Streamlit app to ``dashboard.py``. Stands up the cohort-intake
triage surface for a tournament event: scrape new event URLs, resume
existing events from ``reports/``, and view per-cohort readiness for
backtest runs.
"""

from __future__ import annotations

import contextlib
import html
import os
import sys
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import streamlit as st

from config.settings import (
    PROJECT_NAME,
    SUPABASE_SERVICE_ROLE_KEY,
    SUPABASE_URL,
    VERSION,
)
from src.scrapers.gotsport import EventCaptchaGatedError
from src.scrapers.provider import (
    UnsupportedProviderError,
    get_provider_scraper,
)
from src.tournaments.division_render import render_division_container
from src.tournaments.event_team_matcher import (
    EventTeamSearchQuery,
    search_event_team_in_db,
)
from src.tournaments.seeding_optimizer import (
    normalize_age_group,
    normalize_gender_label,
)
from src.tournaments.storage import (
    ScenarioLockError,
    SchemaVersionError,
    acquire_scenario_lock,
    append_override,
    check_games_import_status,
    compute_frozen_medians,
    ensure_scenario,
    event_key,
    intake_dir,
    list_runs,
    load_overrides,
    load_raw_scrape,
    parse_event_key,
    read_event_metadata,
    read_frozen_medians,
    read_registry,
    read_structure,
    rekey_unknown_directories,
    reports_dir,
    write_event_metadata,
    write_frozen_medians,
)
from src.tournaments.storage._io import utc_now_iso
from src.tournaments.triage import (
    _STRENGTH_MODES,
    ProjectedTeamState,
    _classify_team_state,
    _is_placeholder_team,
    _is_play_up,
    build_override_record,
    project_overrides,
)
from supabase import create_client

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
) -> tuple[str, str]:
    """Combine the ``scraper_state`` tint with the games-import override.

    Override rules:
    - ``not_imported`` → red "games gap".
    - ``partial`` → amber "games gap" (downgrade green; preserve red note).
    - ``complete`` → keep the scraper_state-derived tint.
    """
    base_level, base_note = _scraper_tint(records)
    team_ids = frozenset(
        str(canon["team_id_master"])
        for rec in records
        for canon in (rec.get("canonical") or {},)
        if canon.get("scraper_state") == "alias_written" and canon.get("team_id_master")
    )
    if not team_ids or supabase_client is None:
        return base_level, base_note
    try:
        games_state = _check_games_import_cached(event_name, team_ids, supabase_client)
    except Exception:  # noqa: BLE001 — Supabase failure shouldn't crash the page
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
    write_event_metadata(key, meta)

    try:
        with _acquire_scrape_lock(key):
            st.session_state._scrape_in_progress = True
            try:
                with st.spinner("Scraping cohorts (this may take 1-3 min)..."):
                    scraper.fetch_teams_by_cohort(url)
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


def _render_event_banner(meta: Any, records: list[dict[str, Any]]) -> None:
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
        st.caption("(snapshot/model metadata — coming soon)")

    st.divider()


def _render_cohort_summary(
    cohorts: dict[tuple[str, str], list[dict[str, Any]]],
    sorted_keys: list[tuple[str, str]],
    *,
    event_name: str,
    supabase_client: Any,
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
) -> dict[str, list[str]]:
    """Group provider ids by division name within a cohort.

    Falls back to a single virtual ``"_unstructured"`` division when no
    ``CohortStructure`` exists yet — matches the plan's "ship before
    Shell 05" path.
    """
    if structure_for_cohort is None:
        ids = [
            str(record.get("provider_team_id") or "").strip()
            for record in cohort_records
            if record.get("provider_team_id")
        ]
        return {"_unstructured": ids}
    division_names = [division.name for division in structure_for_cohort.divisions]
    # Sort by length descending so a longer name like "Premier Elite" wins
    # over a shorter prefix like "Premier" when both could match a bracket.
    sorted_division_names = sorted(division_names, key=len, reverse=True)
    groups: dict[str, list[str]] = {name: [] for name in division_names}
    for record in cohort_records:
        bracket = str(record.get("bracket_name") or record.get("division") or "").strip()
        pid = str(record.get("provider_team_id") or "").strip()
        if not pid:
            continue
        chosen = next(
            (name for name in sorted_division_names if bracket and bracket.startswith(name)),
            division_names[0] if division_names else "_unstructured",
        )
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
    try:
        registry_rows = _load_registry_cached(event_key, scenario)
    except FileNotFoundError:
        registry_rows = []
    overrides = load_overrides(event_key, scenario)
    team_state, _cohort_state = project_overrides(overrides)

    structure_list = read_structure(event_key, scenario)
    structure_for_cohort = next(
        (c for c in structure_list if c.age_group == age and c.gender == gender),
        None,
    )

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

    division_groups = _build_division_groups(cohort_records, structure_for_cohort)

    _render_games_coverage(
        cohort_records=cohort_records,
        team_state=team_state,
        cohort_registry_by_pid=cohort_registry_by_pid,
        structure_for_cohort=structure_for_cohort,
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


def _render_games_coverage(
    *,
    cohort_records: list[dict[str, Any]],
    team_state: Any,
    cohort_registry_by_pid: dict[str, dict[str, Any]],
    structure_for_cohort: Any,
    event_name: str,
    supabase_client: Any,
) -> None:
    """Render the per-cohort games-coverage gauge above the triage split."""
    if structure_for_cohort is None:
        st.metric("Games coverage", "pending structure")
        return
    expected = sum(
        getattr(division, "expected_game_count", division.team_count) for division in structure_for_cohort.divisions
    )
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
    age: str,
    gender: str,
    event_key: str,
    scenario: str,
    supabase_client: Any,
) -> None:
    """Render the left pane: per-team rows grouped by division."""
    record_by_pid = {
        str(r.get("provider_team_id") or "").strip(): r for r in cohort_records if r.get("provider_team_id")
    }
    render_matcher_cache: dict[tuple[tuple[str, ...], str, bool], list[dict[str, Any]]] = {}
    division_names = list(division_groups.keys())

    fallback_rendered = False
    for division_name, pids in division_groups.items():

        def body(pids=pids, division_name=division_name) -> None:
            _render_division_body(
                pids=pids,
                division_name=division_name,
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

        try:
            render_division_container(division_name, body)
        except NotImplementedError:
            if not fallback_rendered:
                st.info("Enter division structure first to triage teams")
                fallback_rendered = True
            # Render the body inline so the operator can still triage.
            with st.container(border=True):
                st.markdown(f"**{division_name}**")
                body()


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
        if submitted and supabase_client is not None:
            results = _search_master_teams(
                supabase_client,
                name_query=name_query,
                club_query=club_query,
                provider_id_query=provider_id_query,
                team_id_master_query=team_id_master_query,
            )
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
) -> list[dict[str, Any]]:
    """Look up master teams matching any of the supplied fields.

    Mirrors ``dashboard.py:4596-4615``'s search structure. Filters
    placeholder rows in Python — the cross-column predicate doesn't fit
    PostgREST.
    """
    name_query = (name_query or "").strip()
    club_query = (club_query or "").strip()
    provider_id_query = (provider_id_query or "").strip()
    team_id_master_query = (team_id_master_query or "").strip()
    if not any([name_query, club_query, provider_id_query, team_id_master_query]):
        return []
    rows: list[dict[str, Any]] = []
    try:
        builder = supabase_client.table("teams").select(_TEAM_LOOKUP_COLS)
        if provider_id_query:
            rows = builder.eq("provider_team_id", provider_id_query).limit(20).execute().data or []
        elif team_id_master_query:
            rows = builder.eq("team_id_master", team_id_master_query).limit(20).execute().data or []
        elif name_query:
            rows = builder.ilike("team_name", f"%{name_query}%").limit(20).execute().data or []
        elif club_query:
            rows = builder.ilike("club_name", f"%{club_query}%").limit(20).execute().data or []
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
    for row in cohort_rows:
        pid = _registry_provider_id(row)
        team_id_master = _resolve_team_id_master(team_state.get(pid), row)
        if not team_id_master:
            continue
        bracket = str(row.get("event_team_name") or "").strip()
        chosen = next(
            (name for name in division_names if name and bracket.startswith(name)),
            division_names[0] if division_names else "_unstructured",
        )
        division_by_team_id[team_id_master] = chosen

    if not division_by_team_id:
        raise RuntimeError("No resolved teams in cohort — nothing to recompute.")

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
        )
    except Exception:  # noqa: BLE001
        st.error("Medians recomputed but audit log write failed; rerun Recompute to land the ledger entry.")


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
    st.markdown("**Ranked by power_score**")
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
        probed_age = _rankings_full_age_form(age, supabase_client)
        try:
            rankings_rows = (
                supabase_client.table("rankings_full")
                .select("team_id, powerscore_ml")
                .eq("age_group", probed_age)
                .in_("team_id", sorted(resolved_team_ids))
                .execute()
                .data
                or []
            )
        except Exception as exc:  # noqa: BLE001
            st.warning(f"rankings_full lookup failed: {exc}")
            rankings_rows = []
        for row in rankings_rows:
            team_id = str(row.get("team_id") or "")
            score = _safe_float(row.get("powerscore_ml"))
            if team_id and score is not None:
                rankings_score_by_team_id[team_id] = score
        if not rankings_rows and resolved_team_ids:
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
# Cohort containers
# ---------------------------------------------------------------------------


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
        division_count = len({r.get("bracket_name") or "" for r in records if r.get("bracket_name")})
        dot = _TINT_DOT[level]
        display_label = f"{_display_gender(gender)} {age.upper()}"
        toggle_label = (
            f"**{display_label}** · {team_count} teams · {division_count} divs · {dot} Teams ✓ · {dot} Games · {note}"
        )
        toggle_key = _cohort_toggle_key(age, gender)
        st.session_state.setdefault(toggle_key, False)
        st.toggle(toggle_label, key=toggle_key)
        if st.session_state[toggle_key]:
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
                st.button(
                    "Run backtest",
                    disabled=True,
                    help="Run wiring lands in Shell 06.",
                    key=f"run_btn_{age}_{gender}",
                )


def main() -> None:
    """Top-level render flow."""
    _init_session_state()
    supabase_client = get_database()
    _render_rekey_banner()
    _render_intake_section(supabase_client)

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
    _render_event_banner(meta, records)
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
