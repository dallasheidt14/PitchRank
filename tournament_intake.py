"""MatchBalance · Backtest Intake — Streamlit triage app.

Sibling Streamlit app to ``dashboard.py``. Stands up the cohort-intake
triage surface for a tournament event: scrape new event URLs, resume
existing events from ``reports/``, and view per-cohort readiness for
backtest runs.
"""

from __future__ import annotations

import contextlib
import os
import sys
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
from src.tournaments.seeding_optimizer import (
    normalize_age_group,
    normalize_gender_label,
)
from src.tournaments.storage import (
    SchemaVersionError,
    check_games_import_status,
    ensure_scenario,
    event_key,
    intake_dir,
    load_raw_scrape,
    parse_event_key,
    read_event_metadata,
    rekey_unknown_directories,
    reports_dir,
    write_event_metadata,
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
        label = f"{_display_gender(gender)} {age.upper()}"
        col = cohort_cols[i % cols_per_row]
        with col:
            st.markdown(
                f"<div style='text-align:center;padding:8px 4px;"
                f"border:{active_width} solid {active_border};border-radius:6px;"
                f"background:{bg}'>"
                f"<div style='font-weight:600;font-size:11px;color:#6b7280'>{label}</div>"
                f"<div style='font-size:18px;font-weight:600;margin:2px 0'>{len(records)}</div>"
                f"<div style='font-size:10px;color:{text}'>● {note}</div>"
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


def _render_cohort_containers(
    cohorts: dict[tuple[str, str], list[dict[str, Any]]],
    sorted_keys: list[tuple[str, str]],
    tints: dict[tuple[str, str], tuple[str, str]],
) -> None:
    """Render one collapsible container per cohort with placeholder bodies."""
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
                st.button(
                    "Run backtest",
                    disabled=True,
                    help="Run wiring not yet available.",
                    key=f"run_btn_{age}_{gender}",
                )
                st.caption("(triage + structure inputs coming soon)")


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
    tints = _render_cohort_summary(
        cohorts,
        sorted_keys,
        event_name=meta.event_name,
        supabase_client=supabase_client,
    )
    _render_cohort_containers(cohorts, sorted_keys, tints)


if __name__ == "__main__":
    main()
