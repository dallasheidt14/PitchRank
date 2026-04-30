"""Gotsport tier-section parser.

**Wire format** — for any non-trivially-tiered Gotsport event, the landing
page enumerates each per-tier ``[Schedule]`` / ``[Results]`` link pair
carrying a ``?group=<numeric_id>`` query parameter, with the human-readable
cohort+tier label in a sibling ``<b>`` tag two parents up. Per-tier
membership lives at ``schedules?group=<gid>`` subpages, where each team
surfaces as a ``?team=<digits>`` anchor. (Verified hit rate: 333/333
distinct group IDs across 8 fetchable events; one event in nine serves a
reCAPTCHA challenge instead — captcha rate is budgeted, not assumed away.)

This module ships the **Phase 0** two-stage pipeline that consumes those
two formats:

1. **Discovery** — ``extract_tier_catalog`` walks ``?group=`` anchors and
   resolves each to a ``RawTierLabel`` (cohort age + gender + tier
   residue, with provenance).
2. **Membership** — ``enrich_teams_with_tiers`` (the impure orchestrator)
   subfetches each in-scope tier's ``?team=`` anchors and joins them back
   to ``EventTeam`` rows, returning ``dict[provider_team_id, EnrichmentResult]``.

The pure helpers (``strip_cohort_prefix``, ``parse_cohort_identity``,
``extract_tier_catalog``, ``parse_team_ids_from_subpage``) take primitive
inputs and have unit tests against committed fixtures with no network.
The orchestrator takes a ``subpage_fetcher`` callable so tests inject
canned ``FetchedSubpage`` instances; live wiring constructs them from a
``requests.Response``.

The module imports only from ``event_team`` (hermetic), ``_age_normalization``
(hermetic), ``team_utils`` (hermetic), ``intake_journal`` (hermetic), and
stdlib + bs4 — never from ``gotsport.py``. ``EventCaptchaGatedError`` is
lazy-imported inside the orchestrator's captcha-detect branch to avoid the
circular-import the Shell 02 ``gotsport.py → gotsport_tier_parser`` import
direction will create.

See ``architecture_age_pattern_drift.md`` — this is a 5th age-pattern site.
"""

from __future__ import annotations

import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal, Optional

from bs4 import BeautifulSoup

from src.scrapers._age_normalization import normalize_age
from src.scrapers.event_team import EventTeam  # noqa: F401  (re-export for callers)
from src.tournaments.storage.event_key import intake_dir
from src.utils import team_utils

# Captcha-detection + EventCaptchaGatedError are lazy-imported inside the
# orchestrator's per-subfetch branch — Shell 02 introduces a
# ``gotsport.py → gotsport_tier_parser.py`` import direction, and a
# top-level reverse import here would deadlock at module load. The Shell 01
# Step 12 lazy-import discipline gate enforces zero top-level imports from
# ``src.scrapers.gotsport`` in this file.

logger = logging.getLogger(__name__)


__all__ = [
    "EnrichmentResult",
    "EventTeamMembershipCollisionError",
    "FetchedSubpage",
    "INVERSE_COLLISION_STRICT_MODE",
    "IN_SCOPE_AGES",
    "MEMBERSHIP_AMBIGUOUS",
    "MEMBERSHIP_NONE",
    "MEMBERSHIP_SUBPAGE",
    "MICRO_OUT_OF_SCOPE_AGES",
    "OUTCOME_EMPTY_RESIDUE",
    "OUTCOME_MATCHED",
    "OUTCOME_UNENRICHED",
    "OUTCOME_UNKNOWN_PREFIX",
    "RawTierLabel",
    "SOURCE_LANDING",
    "SOURCE_NONE",
    "TierDiscoverySource",
    "TierMembershipSource",
    "TierParseOutcome",
    "TierSubfetchError",
    "UNKNOWN_PREFIX_GATE_THRESHOLD",
    "enrich_teams_with_tiers",
    "extract_tier_catalog",
    "parse_cohort_identity",
    "parse_team_ids_from_subpage",
    "strip_cohort_prefix",
]


# ---------------------------------------------------------------------------
# Type aliases + named constants. Mirror ``triage.py:351-359``'s
# Literal-paired-with-named-constants idiom so callers can branch on the
# constants below instead of bare string literals (typo-safe).
# ---------------------------------------------------------------------------

TierDiscoverySource = Literal["landing", "none"]
TierMembershipSource = Literal["subpage", "ambiguous_multi_tier", "none"]
TierParseOutcome = Literal["matched", "unknown_prefix", "empty_residue", "unenriched"]

SOURCE_LANDING: TierDiscoverySource = "landing"
SOURCE_NONE: TierDiscoverySource = "none"

MEMBERSHIP_SUBPAGE: TierMembershipSource = "subpage"
MEMBERSHIP_AMBIGUOUS: TierMembershipSource = "ambiguous_multi_tier"
MEMBERSHIP_NONE: TierMembershipSource = "none"

OUTCOME_MATCHED: TierParseOutcome = "matched"
OUTCOME_UNKNOWN_PREFIX: TierParseOutcome = "unknown_prefix"
OUTCOME_EMPTY_RESIDUE: TierParseOutcome = "empty_residue"
OUTCOME_UNENRICHED: TierParseOutcome = "unenriched"


# ---------------------------------------------------------------------------
# Frozen vocabularies. PitchRank only ranks U10–U19 (U18 merges into U19);
# U6–U9 are known-out-of-scope micro cohorts; the orchestrator skips
# subfetches for them. Unknown-prefix gate at 10% per spec (the threshold
# fires when too many landing labels fail to parse — surfaces drift).
# ---------------------------------------------------------------------------

IN_SCOPE_AGES: frozenset[str] = frozenset({"u10", "u11", "u12", "u13", "u14", "u15", "u16", "u17", "u19"})
MICRO_OUT_OF_SCOPE_AGES: frozenset[str] = frozenset({"u6", "u7", "u8", "u9"})
UNKNOWN_PREFIX_GATE_THRESHOLD: float = 0.10
INVERSE_COLLISION_STRICT_MODE: bool = False


# ---------------------------------------------------------------------------
# Frozen value objects. Mirror ``triage.py:362-387`` — frozen dataclass
# with a Literal-typed source/outcome discriminator. ``FetchedSubpage``
# carries enough context for captcha detection without coupling to
# ``requests.Response``.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RawTierLabel:
    """Output of the discovery pass — one entry per distinct ``?group=<id>``."""

    group_id: int
    raw_label: str  # The sibling-<b> text verbatim (e.g., "U13 Boys Red")
    cohort_age_group: Optional[str]  # Lowercase per CANONICAL_AGE_GROUPS; None for HS / unknown-prefix
    cohort_gender: Optional[str]  # "M" / "F" / None for ambiguous (Coed, no gender suffix)
    tier_residue: Optional[str]  # Residue after strip_cohort_prefix; None for empty_residue
    parse_outcome: TierParseOutcome


@dataclass(frozen=True)
class EnrichmentResult:
    """Output of the orchestrator — one entry per provider_team_id that resolved to a tier."""

    group_name: Optional[str]
    group_id: Optional[int]
    tier_discovery_source: TierDiscoverySource
    tier_membership_source: TierMembershipSource
    tier_parse_outcome: TierParseOutcome


@dataclass(frozen=True)
class FetchedSubpage:
    """Carries enough context for captcha detection without coupling to
    ``requests.Response``. Live wiring constructs this from the response;
    tests inject a synthetic instance with a canned body."""

    html: str
    final_url: str  # response.url after redirects
    zr_final_url: Optional[str]  # response.headers.get("Zr-Final-Url") — ZenRows origin URL
    redirect_locations: list[str]  # [hr.headers.get("Location", "") for hr in response.history]


# ---------------------------------------------------------------------------
# Exception types. Mirror ``EventCaptchaGatedError`` shape at
# ``gotsport.py:634-658`` — top-level, keyword-only ``__init__``, named
# attributes, formatted message in ``super().__init__()``.
# ---------------------------------------------------------------------------


class EventTeamMembershipCollisionError(Exception):
    """Raised when a per-event uniqueness invariant is violated.

    ``mode='forward'``: a single ``?group=<id>`` resolves to two different
    ``(cohort, tier)`` pairs across the landing page's anchor walk.
    ``mode='inverse'``: a single ``team_id`` appears in two different
    ``?group=`` subpages. Forward is always raised; inverse is gated on
    ``INVERSE_COLLISION_STRICT_MODE`` (default ``False`` — log and proceed).
    """

    def __init__(
        self,
        *,
        event_id: str,
        mode: Literal["forward", "inverse"],
        group_id: Optional[int] = None,
        team_id: Optional[str] = None,
        conflicting_cohorts: tuple[tuple[Optional[str], Optional[str]], ...] = (),
        conflicting_tier_residues: tuple[str, ...] = (),
        conflicting_group_ids: tuple[int, ...] = (),
        details: str = "",
    ):
        self.event_id = event_id
        self.mode = mode
        self.group_id = group_id
        self.team_id = team_id
        self.conflicting_cohorts = conflicting_cohorts
        self.conflicting_tier_residues = conflicting_tier_residues
        self.conflicting_group_ids = conflicting_group_ids
        self.details = details
        msg = f"event {event_id} {mode} collision"
        if group_id is not None:
            msg += f" group_id={group_id}"
        if team_id is not None:
            msg += f" team_id={team_id}"
        if details:
            msg += f": {details}"
        super().__init__(msg)


class TierSubfetchError(Exception):
    """Raised when a per-tier ``?group=<id>/schedules`` subfetch fails for
    non-captcha reasons (HTTP 4xx/5xx, parse exception, malformed HTML)."""

    def __init__(
        self,
        *,
        event_id: str,
        group_id: int,
        subpage_url: str,
        underlying_kind: Literal["http_error", "parse_error", "malformed_html"],
        details: str = "",
    ):
        self.event_id = event_id
        self.group_id = group_id
        self.subpage_url = subpage_url
        self.underlying_kind = underlying_kind
        self.details = details
        super().__init__(
            f"event {event_id} group {group_id} subfetch failed ({underlying_kind}): {subpage_url} — {details}"
        )


# ---------------------------------------------------------------------------
# Cohort-prefix regex tuple. First-match-wins; each regex is start-anchored
# (``^\s*<form>``) so partial overlaps cannot cross-match. ``re.IGNORECASE``
# everywhere so uppercase fixture labels (events 49371, 49407) match
# the same forms as standard casing. See spec for full form table.
# ---------------------------------------------------------------------------

_COHORT_PREFIX_FORMS: tuple[re.Pattern, ...] = (
    # Form 11. Glued (e.g., "U9B Premier", "U10B Elite") — must precede Form 1.
    re.compile(r"^\s*U-?\d{1,2}[BG](?:\s+|$)", re.IGNORECASE),
    # Form 7. Mixed-age — both explicit ("U16/U15 Girls Reyna") AND implicit
    # second-U ("U18/19 Girls Blue", verified on event 42433). The second U
    # is optional via ``U?-?``.
    re.compile(r"^\s*U-?\d{1,2}/U?-?\d{1,2}(?:\s+(?:Boys|Girls|Co-?Ed))?(?:\s+|$)", re.IGNORECASE),
    # Form 5. Reverse-token (e.g., "12U Boys Red", "11U BOYS GOLD A DIVISION", "17/19U BOYS").
    re.compile(r"^\s*\d{1,2}(?:/\d{1,2})?U(?:\s+(?:Boys|Girls|Co-?Ed))?(?:\s+|$)", re.IGNORECASE),
    # Form 4. Birth-year (e.g., "B2017 Gold", "B2010/11 Silver", "G2015 Silver").
    re.compile(r"^\s*[BG]\d{4}(?:/\d{2})?(?:\s+|$)", re.IGNORECASE),
    # Form 1/2/3/9. Standard U-prefix with optional gender (covers hyphen Form 2,
    # bare Form 3, lowercase Form 9 via re.IGNORECASE).
    re.compile(r"^\s*U-?\d{1,2}(?:\s+(?:Boys|Girls|Co-?Ed))?(?:\s+|$)", re.IGNORECASE),
    # Form 10. High School.
    re.compile(
        r"^\s*(?:Varsity|JV|9th-Grade|10th-Grade|11th-Grade|12th-Grade)\s+(?:Boys|Girls|Co-?Ed)(?:\s+|$)",
        re.IGNORECASE,
    ),
)
_FORMAT_TOKEN_RE = re.compile(r"\s*\(\d{1,2}[Vv]\d{1,2}\)\s*$", re.IGNORECASE)
_GROUP_ANCHOR_HREF_RE = re.compile(r"/schedules\?(?:[^&]*&)*group=(\d+)")
_TEAM_ANCHOR_HREF_RE = re.compile(r"\bteam=(\d+)")  # mirrors gotsport.py:2575


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def strip_cohort_prefix(text: str) -> tuple[str, str, TierParseOutcome]:
    """Match the first cohort form in ``_COHORT_PREFIX_FORMS`` against ``text``.

    Returns ``(prefix_span, residue, outcome)``:

    - ``matched``: prefix recognized, residue non-empty.
    - ``empty_residue``: prefix recognized, no tier residue (e.g., ``"U10"``).
    - ``unknown_prefix``: no form matched; logs WARNING and treats the full
      text as residue. Drives the unknown-prefix gate metric.

    The format-token suffix (``(NvN)``) is stripped from residue when present.
    """
    for pattern in _COHORT_PREFIX_FORMS:
        m = pattern.match(text)
        if not m:
            continue
        prefix_span = m.group(0)
        rest = text[m.end() :]
        rest = _FORMAT_TOKEN_RE.sub("", rest)
        rest = rest.strip()
        if not rest:
            return (prefix_span, "", OUTCOME_EMPTY_RESIDUE)
        return (prefix_span, rest, OUTCOME_MATCHED)
    logger.warning("unknown_cohort_prefix: text=%r", text)
    return ("", text, OUTCOME_UNKNOWN_PREFIX)


def parse_cohort_identity(prefix_span: str) -> Optional[tuple[str, Optional[str]]]:
    """Extract ``(age_lowercase, gender)`` from a recognized prefix span.

    Returns ``None`` when the prefix is HS (Form 10) or when ``normalize_age``
    rejects the derived age. Reads ``team_utils.CURRENT_YEAR`` at call time
    (module-style import) so monkeypatch-based tests can override the season
    year — see the import comment at the top of this module.
    """
    if not prefix_span:
        return None

    # Form 11 (glued, e.g., "U10B"): match BEFORE Form 1 since the ``B`` would
    # otherwise be eaten by the optional gender in Form 1.
    m = re.match(r"^\s*U-?(\d{1,2})([BG])", prefix_span, re.IGNORECASE)
    if m:
        return _resolve_cohort(int(m.group(1)), gender_letter=m.group(2))

    # Form 7 (mixed-age, e.g., "U16/U15 Girls" OR "U18/19 Girls"): pick
    # younger age via int-min (string-min would lex-compare and break
    # "U16/U9" → "16"). Second U is optional, matching the regex above.
    m = re.match(
        r"^\s*U-?(\d{1,2})/U?-?(\d{1,2})(?:\s+(Boys|Girls|Co-?Ed))?",
        prefix_span,
        re.IGNORECASE,
    )
    if m:
        younger = min(int(m.group(1)), int(m.group(2)))
        return _resolve_cohort(younger, gender_word=m.group(3))

    # Form 5 (reverse-token, e.g., "12U Boys" or "17/19U BOYS"): pick younger
    # for slash forms.
    m = re.match(r"^\s*(\d{1,2})(?:/(\d{1,2}))?U(?:\s+(Boys|Girls|Co-?Ed))?", prefix_span, re.IGNORECASE)
    if m:
        if m.group(2):
            age_int = min(int(m.group(1)), int(m.group(2)))
        else:
            age_int = int(m.group(1))
        return _resolve_cohort(age_int, gender_word=m.group(3))

    # Form 4 (birth-year, e.g., "B2017", "G2015"): age = season_year − birth + 1.
    m = re.match(r"^\s*([BG])(\d{4})(?:/\d{2})?", prefix_span, re.IGNORECASE)
    if m:
        birth_year = int(m.group(2))
        age_int = team_utils.CURRENT_YEAR - birth_year + 1
        return _resolve_cohort(age_int, gender_letter=m.group(1))

    # Form 1/2/3/9 (standard U-prefix with optional gender word).
    m = re.match(r"^\s*U-?(\d{1,2})(?:\s+(Boys|Girls|Co-?Ed))?", prefix_span, re.IGNORECASE)
    if m:
        return _resolve_cohort(int(m.group(1)), gender_word=m.group(2))

    # Form 10 (HS) and any other recognized-but-cohort-less prefix.
    return None


def _resolve_cohort(
    age_int: int,
    *,
    gender_letter: Optional[str] = None,
    gender_word: Optional[str] = None,
) -> Optional[tuple[str, Optional[str]]]:
    """Build the ``(age, gender)`` tuple. Returns ``None`` if age is out of band."""
    age_key = normalize_age(age_int)
    if age_key is None:
        return None
    if gender_letter:
        gender = "M" if gender_letter.upper() == "B" else "F"
    elif gender_word:
        head = gender_word.lower()[0]
        gender = "M" if head == "b" else "F" if head == "g" else None
    else:
        gender = None
    return (age_key, gender)


def extract_tier_catalog(soup: BeautifulSoup, *, event_id: str) -> dict[int, RawTierLabel]:
    """Walk the landing page's ``?group=<id>`` anchors and build a per-gid catalog.

    Inline forward-collision detection (per spec): if two anchors carry the
    same ``group_id`` but resolve to different ``(cohort, tier_residue)``,
    raises ``EventTeamMembershipCollisionError(mode="forward")``. A
    Schedule + Results pair sharing both gid and label is a legitimate
    dedupe — first-encountered wins.

    Anchors carrying obvious noise labels (``"Schedule"`` / ``"Results"``) or
    no usable sibling-``<b>`` are silently skipped.
    """
    catalog: dict[int, RawTierLabel] = {}
    anchors = soup.find_all("a", href=_GROUP_ANCHOR_HREF_RE)
    for anchor in anchors:
        href = anchor.get("href", "")
        m = _GROUP_ANCHOR_HREF_RE.search(href)
        if not m:
            continue
        group_id = int(m.group(1))
        parent = anchor.find_parent()
        row = parent.find_parent() if parent else None
        if row is None:
            continue
        b_tag = row.find("b")
        if b_tag is None:
            continue
        raw_label = b_tag.get_text(" ", strip=True)
        if raw_label.lower() in {"schedule", "results"}:
            continue

        prefix_span, residue, outcome = strip_cohort_prefix(raw_label)
        cohort = parse_cohort_identity(prefix_span)
        new_label = RawTierLabel(
            group_id=group_id,
            raw_label=raw_label,
            cohort_age_group=cohort[0] if cohort else None,
            cohort_gender=cohort[1] if cohort else None,
            tier_residue=residue or None,
            parse_outcome=outcome,
        )

        existing = catalog.get(group_id)
        if existing is None:
            catalog[group_id] = new_label
            continue

        existing_sig = (existing.cohort_age_group, existing.cohort_gender, existing.tier_residue)
        new_sig = (new_label.cohort_age_group, new_label.cohort_gender, new_label.tier_residue)
        if existing_sig == new_sig:
            # Schedule + Results pair sharing the same label — legitimate dedupe.
            continue
        # Genuine forward collision.
        raise EventTeamMembershipCollisionError(
            event_id=event_id,
            mode="forward",
            group_id=group_id,
            conflicting_cohorts=(
                (existing.cohort_age_group, existing.cohort_gender),
                (new_label.cohort_age_group, new_label.cohort_gender),
            ),
            conflicting_tier_residues=(existing.tier_residue or "", new_label.tier_residue or ""),
            details=f"raw_labels=({existing.raw_label!r}, {new_label.raw_label!r})",
        )

    return catalog


def parse_team_ids_from_subpage(html: str) -> set[str]:
    """Extract every ``?team=<digits>`` anchor on a per-tier subpage.

    Returns a deduped set of decimal strings (matches the upstream
    ``team_id`` shape used in ``EventTeam.team_id``).
    """
    soup = BeautifulSoup(html, "html.parser")
    out: set[str] = set()
    for anchor in soup.find_all("a", href=_TEAM_ANCHOR_HREF_RE):
        href = anchor.get("href", "") or ""
        m = _TEAM_ANCHOR_HREF_RE.search(href)
        if m:
            out.add(m.group(1))
    return out


# ---------------------------------------------------------------------------
# Artifact writers. Mirror ``gotsport.py:920-948`` (``_write_captcha_artifact``)
# and ``intake_journal.py:326-341`` (``write_removed_teams_artifact``).
# Both write ``reports/<event_key>/intake/<artifact>.json`` next to the
# existing intake artifacts produced by the scrape pipeline.
# ---------------------------------------------------------------------------


def _write_intake_artifact(
    event_key: str,
    *,
    filename: str,
    payload: dict,
    log_msg: str,
    base_dir: Path | str = "reports",
) -> Path:
    """Shared write path for ``tier_parse_metrics.json`` + abort artifacts.

    Routes through ``intake_dir`` so the ``event_key`` is validated as a
    single path segment (``_validate_segment`` rejects ``"../etc"``-style
    payloads), preventing path-traversal escapes from the reports root.
    """
    path = intake_dir(event_key, base_dir=base_dir) / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    logger.info(log_msg, path)
    return path


def _write_metric_artifact(
    event_key: str,
    *,
    total_candidates: int,
    unknown_prefix_count: int,
    unknown_prefix_labels: list[str],
    gated: bool,
    base_dir: Path | str = "reports",
) -> Path:
    return _write_intake_artifact(
        event_key,
        filename="tier_parse_metrics.json",
        payload={
            "event_key": event_key,
            "total_candidates": total_candidates,
            "unknown_prefix_count": unknown_prefix_count,
            "unknown_prefix_labels": unknown_prefix_labels,
            "gated_at_threshold": gated,
            "threshold": UNKNOWN_PREFIX_GATE_THRESHOLD,
        },
        log_msg=f"[tier_parse_metrics] wrote %s (gated={gated})",
        base_dir=base_dir,
    )


_AbortKind = Literal[
    "http_error",
    "captcha",
    "parse_error",
    "malformed_html",
    "collision_forward",
    "collision_inverse_strict",
]


_FILENAME_RESERVED_RE = re.compile(r'[<>:"/\\|?*]')


def _safe_filename_token(run_id: str) -> str:
    """Sanitize a string for use as a filename component on every supported OS.

    Windows rejects ``<>:"/\\|?*`` (and a few NTFS-reserved names that are
    out of scope here); macOS rejects ``:``; Linux tolerates everything.
    All reserved chars collapse to ``-``, and ``+`` is rewritten to ``_``
    so ISO-8601 timezone offsets like ``+00:00`` round-trip distinguishably.
    """
    return _FILENAME_RESERVED_RE.sub("-", run_id).replace("+", "_")


def _write_abort_artifact(
    event_key: str,
    *,
    run_id: str,
    attempted_group_ids: list[int],
    completed_group_ids: list[int],
    failed_group_id: Optional[int],
    failure_kind: _AbortKind,
    details: str,
    base_dir: Path | str = "reports",
) -> Path:
    path = _write_intake_artifact(
        event_key,
        filename=f"tier_orchestrator_abort__{_safe_filename_token(run_id)}.json",
        payload={
            "event_key": event_key,
            "run_id": run_id,
            "attempted_group_ids": attempted_group_ids,
            "completed_group_ids": completed_group_ids,
            "failed_group_id": failed_group_id,
            "failure_kind": failure_kind,
            "details": details,
        },
        log_msg=f"[tier_orchestrator_abort] wrote %s (kind={failure_kind}, failed_gid={failed_group_id})",
        base_dir=base_dir,
    )
    return path


# ---------------------------------------------------------------------------
# Orchestrator. Impure — but pure-by-injection: the only side effects are
# (a) the artifact writes and (b) ``subpage_fetcher`` calls. Everything
# else operates on the soup + injected fetcher. Tests mock the fetcher.
# ---------------------------------------------------------------------------


def enrich_teams_with_tiers(
    soup: BeautifulSoup,
    teams_by_bracket: dict[str, list[EventTeam]],  # noqa: ARG001 — Shell 02 will consume this
    *,
    event_id: str,
    event_key: str,
    run_id: str,
    subpage_fetcher: Callable[[int], FetchedSubpage],
    max_concurrent_subfetches: int = 1,
    base_dir: Path | str = "reports",
) -> dict[str, EnrichmentResult]:
    """Two-stage tier-enrichment pipeline.

    Stage 1 (discovery) walks the landing soup to build a catalog of
    ``?group=<id> → RawTierLabel`` entries. Stage 2 (membership) calls
    ``subpage_fetcher`` for each in-scope ``group_id`` and joins the
    returned ``?team=<id>`` sets back into ``dict[team_id, EnrichmentResult]``.

    On any abort path (forward collision, captcha, http error, parse
    error, malformed html, strict-mode inverse collision), writes an
    ``tier_orchestrator_abort__<run_id>.json`` artifact under
    ``base_dir/<event_key>/intake/`` AND re-raises the typed exception.
    The metrics artifact (``tier_parse_metrics.json``) is written
    immediately after discovery — ALWAYS — so the unknown-prefix gate
    signal surfaces regardless of run outcome.

    ``teams_by_bracket`` is reserved for Shell 02 (it'll cross-reference
    against EventTeam rows). Shell 01 returns the per-team_id enrichment
    dict and lets the caller (``fetch_teams_by_cohort``) join it in.
    """
    # 1. Discovery.
    try:
        catalog = extract_tier_catalog(soup, event_id=event_id)
    except EventTeamMembershipCollisionError as exc:
        _write_abort_artifact(
            event_key,
            run_id=run_id,
            attempted_group_ids=[],
            completed_group_ids=[],
            failed_group_id=exc.group_id,
            failure_kind="collision_forward",
            details=str(exc),
            base_dir=base_dir,
        )
        raise
    except Exception as exc:  # noqa: BLE001 — defensive; ensures artifact written before propagation
        _write_abort_artifact(
            event_key,
            run_id=run_id,
            attempted_group_ids=[],
            completed_group_ids=[],
            failed_group_id=None,
            failure_kind="parse_error",
            details=f"unexpected exception in extract_tier_catalog: {type(exc).__name__}: {exc}",
            base_dir=base_dir,
        )
        raise

    # 2. In-scope filter + unknown-prefix metric. The two non-skip branches
    # (in-scope U10..U19, unknown/HS-fall-through) BOTH subfetch — only the
    # known-out-of-scope micro cohorts (u6..u9) get dropped. Single predicate
    # captures that semantics directly.
    in_scope_catalog: dict[int, RawTierLabel] = {
        label.group_id: label for label in catalog.values() if label.cohort_age_group not in MICRO_OUT_OF_SCOPE_AGES
    }

    unknown_prefix_labels = [
        lbl.raw_label for lbl in in_scope_catalog.values() if lbl.parse_outcome == OUTCOME_UNKNOWN_PREFIX
    ]
    unknown_prefix_count = len(unknown_prefix_labels)
    total_candidates = len(in_scope_catalog)
    gated = (unknown_prefix_count / total_candidates) > UNKNOWN_PREFIX_GATE_THRESHOLD if total_candidates > 0 else False

    # 3. Write metrics artifact IMMEDIATELY — before any subfetch.
    _write_metric_artifact(
        event_key,
        total_candidates=total_candidates,
        unknown_prefix_count=unknown_prefix_count,
        unknown_prefix_labels=unknown_prefix_labels,
        gated=gated,
        base_dir=base_dir,
    )

    if total_candidates == 0:
        return {}

    # 4. Membership pass.
    attempted_group_ids = list(in_scope_catalog.keys())
    completed_group_ids: list[int] = []
    results_by_gid: dict[int, set[str]] = {}

    def _process_one(gid: int) -> tuple[int, set[str]]:
        subpage_url = f"https://system.gotsport.com/org_event/events/{event_id}/schedules?group={gid}"
        try:
            fetched = subpage_fetcher(gid)
        except Exception as exc:
            _write_abort_artifact(
                event_key,
                run_id=run_id,
                attempted_group_ids=attempted_group_ids,
                completed_group_ids=list(completed_group_ids),
                failed_group_id=gid,
                failure_kind="http_error",
                details=f"{type(exc).__name__}: {exc}",
                base_dir=base_dir,
            )
            raise TierSubfetchError(
                event_id=event_id,
                group_id=gid,
                subpage_url=subpage_url,
                underlying_kind="http_error",
                details=f"{type(exc).__name__}: {exc}",
            ) from exc

        # Lazy import — see top-of-module note about the Shell 02 circular dep.
        from src.scrapers.gotsport import _extract_captcha_signals_from_parts

        signals = _extract_captcha_signals_from_parts(
            html=fetched.html,
            final_url=fetched.final_url,
            zr_final_url=fetched.zr_final_url,
            redirect_locations=fetched.redirect_locations,
            fallback_target_url=subpage_url,
        )
        if signals is not None:
            abort_path = _write_abort_artifact(
                event_key,
                run_id=run_id,
                attempted_group_ids=attempted_group_ids,
                completed_group_ids=list(completed_group_ids),
                failed_group_id=gid,
                failure_kind="captcha",
                details=f"captcha_url={signals.get('captcha_url')!r} sitekey={signals.get('sitekey')!r}",
                base_dir=base_dir,
            )
            # Lazy import to avoid the gotsport.py → gotsport_tier_parser.py
            # circular-import that Shell 02 will create.
            from src.scrapers.gotsport import EventCaptchaGatedError

            raise EventCaptchaGatedError(
                provider_event_id=event_id,
                captcha_url=signals.get("captcha_url", subpage_url),
                sitekey=signals.get("sitekey"),
                artifact_path=abort_path,
            )

        try:
            team_ids = parse_team_ids_from_subpage(fetched.html)
        except Exception as exc:  # noqa: BLE001 — bs4 / regex failure
            _write_abort_artifact(
                event_key,
                run_id=run_id,
                attempted_group_ids=attempted_group_ids,
                completed_group_ids=list(completed_group_ids),
                failed_group_id=gid,
                failure_kind="parse_error",
                details=f"{type(exc).__name__}: {exc}",
                base_dir=base_dir,
            )
            raise TierSubfetchError(
                event_id=event_id,
                group_id=gid,
                subpage_url=subpage_url,
                underlying_kind="parse_error",
                details=f"{type(exc).__name__}: {exc}",
            ) from exc

        label = in_scope_catalog[gid]
        if not team_ids and label.parse_outcome != OUTCOME_EMPTY_RESIDUE:
            # Empty teams when the residue claimed a real tier — likely a
            # parse failure on the subpage. Empty-residue cohorts (single-tier)
            # genuinely may have zero teams.
            _write_abort_artifact(
                event_key,
                run_id=run_id,
                attempted_group_ids=attempted_group_ids,
                completed_group_ids=list(completed_group_ids),
                failed_group_id=gid,
                failure_kind="malformed_html",
                details=f"zero ?team= anchors found at gid={gid} but residue={label.tier_residue!r}",
                base_dir=base_dir,
            )
            raise TierSubfetchError(
                event_id=event_id,
                group_id=gid,
                subpage_url=subpage_url,
                underlying_kind="malformed_html",
                details=f"zero ?team= anchors; residue={label.tier_residue!r}",
            )

        return gid, team_ids

    if max_concurrent_subfetches > 1:
        with ThreadPoolExecutor(max_workers=max_concurrent_subfetches) as pool:
            future_to_gid = {pool.submit(_process_one, gid): gid for gid in attempted_group_ids}
            try:
                for fut in as_completed(future_to_gid):
                    gid, team_ids = fut.result()
                    results_by_gid[gid] = team_ids
                    completed_group_ids.append(gid)
            except Exception:
                for fut in future_to_gid:
                    fut.cancel()
                raise
    else:
        for gid in attempted_group_ids:
            _gid, team_ids = _process_one(gid)
            results_by_gid[_gid] = team_ids
            completed_group_ids.append(_gid)

    # 5. Inverse-collision check. Iterate in CATALOG insertion order so
    # under concurrency the "FIRST gid wins" tie-break is deterministic
    # against document order, not future-completion order.
    team_to_gids: dict[str, list[int]] = {}
    for gid in attempted_group_ids:
        for team_id in results_by_gid.get(gid, ()):
            team_to_gids.setdefault(team_id, []).append(gid)

    inverse_collision_teams: set[str] = set()
    for team_id, gids in team_to_gids.items():
        if len(gids) > 1:
            inverse_collision_teams.add(team_id)
            logger.warning("tier_inverse_collision: team_id=%s, group_ids=%s", team_id, gids)
            if INVERSE_COLLISION_STRICT_MODE:
                _write_abort_artifact(
                    event_key,
                    run_id=run_id,
                    attempted_group_ids=attempted_group_ids,
                    completed_group_ids=list(completed_group_ids),
                    failed_group_id=None,
                    failure_kind="collision_inverse_strict",
                    details=f"team_id={team_id} appeared in group_ids={gids}",
                    base_dir=base_dir,
                )
                raise EventTeamMembershipCollisionError(
                    event_id=event_id,
                    mode="inverse",
                    team_id=team_id,
                    conflicting_group_ids=tuple(gids),
                )

    # 6. Build enrichment dict (first-write-wins on dict keys to honor
    # catalog order — iterating attempted_group_ids in catalog insertion
    # order means the FIRST gid that contains a team_id sticks).
    enrichment: dict[str, EnrichmentResult] = {}
    for gid in attempted_group_ids:
        label = in_scope_catalog[gid]
        for team_id in results_by_gid.get(gid, ()):
            if team_id in enrichment:
                continue
            membership = MEMBERSHIP_AMBIGUOUS if team_id in inverse_collision_teams else MEMBERSHIP_SUBPAGE
            enrichment[team_id] = EnrichmentResult(
                group_name=label.tier_residue,
                group_id=label.group_id,
                tier_discovery_source=SOURCE_LANDING,
                tier_membership_source=membership,
                tier_parse_outcome=label.parse_outcome,
            )

    return enrichment
