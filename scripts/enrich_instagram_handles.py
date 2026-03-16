#!/usr/bin/env python3
"""
Discover Instagram handles for PitchRank teams via Google search (Serper.dev).

Generates multiple site:instagram.com search query variations per team,
scores candidate handles against team identity (club name, birth year, gender),
and upserts results into team_social_profiles with a confidence score.

Confidence thresholds:
    >= 0.85  auto_approved  (high-confidence match, stored immediately)
    0.60-0.84  needs_review  (plausible, queued for human verification)
    < 0.60   rejected        (not stored — too low signal)

Requires SERPER_API_KEY environment variable.
Get your key at https://serper.dev (free tier: 2,500 queries/month).

Examples:
    python3 scripts/enrich_instagram_handles.py --dry-run
    python3 scripts/enrich_instagram_handles.py --dry-run --limit 20
    python3 scripts/enrich_instagram_handles.py --limit 500 --min-power-score 0.70
    python3 scripts/enrich_instagram_handles.py --state TX --workers 3
    python3 scripts/enrich_instagram_handles.py --re-check --limit 100
    python3 scripts/enrich_instagram_handles.py --age-group u14 --gender F --dry-run
    python3 scripts/enrich_instagram_handles.py --dry-run --top-n-per-cohort 10 --limit 25
    python3 scripts/enrich_instagram_handles.py --top-n-per-cohort 10 --workers 3

Phase 1 (club handles — recommended first):
    python3 scripts/enrich_instagram_handles.py --phase 1 --dry-run --limit 20
    python3 scripts/enrich_instagram_handles.py --phase 1 --workers 3
    python3 scripts/enrich_instagram_handles.py --phase 1 --state TX --workers 3

Phase 2 (team-specific handles — run after Phase 1):
    python3 scripts/enrich_instagram_handles.py --phase 2 --dry-run --top-n-per-cohort 10 --limit 25
    python3 scripts/enrich_instagram_handles.py --phase 2 --top-n-per-cohort 10 --workers 3
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import sys
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, DefaultDict, Dict, List, Optional, Set, Tuple

import requests
from dotenv import load_dotenv
from supabase import create_client


# ──────────────────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────────────────

PLATFORM = "instagram"

AUTO_APPROVE_THRESHOLD = 0.85
NEEDS_REVIEW_THRESHOLD = 0.60

# Suffix words stripped when building a "short" club name for additional queries
CLUB_SUFFIXES: Set[str] = {
    "sc", "fc", "sa", "fa", "united", "soccer", "club", "academy",
    "sporting", "athletic", "athletics", "association", "youth",
    "select", "af", "ac", "football",
}

# Tier / division words common in youth soccer
TIER_WORDS: Set[str] = {
    "ecnl", "rl", "elite", "pre", "premier", "select", "classic",
    "npl", "dpl", "ga", "hd", "ad", "flagship", "national",
}

# Instagram pages that are system paths, not team accounts
INSTAGRAM_SYSTEM_PAGES: Set[str] = {
    "explore", "accounts", "p", "reel", "stories", "tv", "direct",
    "ar", "about", "legal", "privacy", "help", "press", "api",
    "download", "lite", "web", "tags", "locations", "directory",
    "contact", "login", "signup", "challenge", "embed",
}

GENDER_WORDS: Dict[str, List[str]] = {
    "Female": ["girls", "girl", "womens", "women", "ladies", "lady", "female"],
    "Male": ["boys", "boy", "mens", "men", "male"],
}

GENDER_ABBRS: Dict[str, str] = {
    "Female": "g",
    "Male": "b",
}

INSTAGRAM_HANDLE_RE = re.compile(r"instagram\.com/([A-Za-z0-9_.]+)(?:[/?#]|$)")


# ──────────────────────────────────────────────────────────────────────────────
# Text / scoring helpers  (stdlib only — no extra dependencies)
# ──────────────────────────────────────────────────────────────────────────────

def _normalize_text(text: str) -> str:
    """Lowercase, keep only alphanumeric and spaces."""
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _tokens(text: str) -> Set[str]:
    return set(_normalize_text(text).split())


def _token_coverage(club_name: str, candidate: str) -> float:
    """
    Fraction of meaningful club name tokens that appear in candidate.
    Uses "coverage" rather than Jaccard so extra tokens in the handle
    (year, gender, tier) don't drag the score down.
    """
    club_toks = {t for t in _tokens(club_name) if len(t) > 1}
    if not club_toks:
        return 0.0
    cand_toks = _tokens(candidate)
    return len(club_toks & cand_toks) / len(club_toks)


def _string_similarity(a: str, b: str) -> float:
    """Token-sorted SequenceMatcher ratio — stdlib difflib, no extra deps."""
    a_s = " ".join(sorted(_tokens(a)))
    b_s = " ".join(sorted(_tokens(b)))
    if not a_s or not b_s:
        return 0.0
    return difflib.SequenceMatcher(None, a_s, b_s).ratio()


def _meaningful_club_tokens(club_name: str) -> Set[str]:
    """Club name tokens with generic suffixes (fc, sc, academy, etc.) removed."""
    all_toks = {t for t in _tokens(club_name) if len(t) > 1}
    meaningful = {t for t in all_toks if t not in CLUB_SUFFIXES}
    return meaningful if meaningful else all_toks


def _club_score(club_name: str, handle: str, title: str, team_name: str = "") -> float:
    """How well does the candidate match the club/team name? 0.0–1.0.

    The club_name MUST have a meaningful signal (excluding generic suffixes
    like fc/sc/academy) in the handle/title before team_name can boost the
    score.  This prevents cross-club false positives where the handle belongs
    to a different club but shares a bracket/division name
    (e.g. beachfc_ecnl_rl_b08_07 matching "FC Arizona / ECNL RL B08/07").
    """
    candidate = f"{handle} {title}"

    # Standard coverage + similarity using full club name (for final score)
    coverage = _token_coverage(club_name, candidate)
    similarity = _string_similarity(club_name, handle)
    club_base = max(coverage, similarity)

    # Gate check uses only meaningful tokens (no generic suffixes)
    meaningful = _meaningful_club_tokens(club_name)
    cand_toks = _tokens(candidate)
    meaningful_coverage = (
        len(meaningful & cand_toks) / len(meaningful) if meaningful else 0.0
    )

    CLUB_GATE = 0.30
    if team_name and team_name.lower() != club_name.lower() and meaningful_coverage >= CLUB_GATE:
        team_coverage = _token_coverage(team_name, candidate)
        team_similarity = _string_similarity(team_name, handle)
        return max(club_base, team_coverage, team_similarity)

    return club_base


def _year_score(
    birth_year: Optional[int], handle: str, title: str, snippet: str
) -> float:
    """Presence of birth-year markers in handle / title / snippet. 0.0–1.0."""
    if not birth_year:
        return 0.5  # Neutral — we can't penalise what we don't know

    year_full = str(birth_year)            # "2011"
    year_short = year_full[-2:]            # "11"
    combined = f"{handle} {title} {snippet}".lower()

    if year_full in combined:
        return 1.0
    # Combined gender-year patterns: g11, 11g, b11, 11b
    if re.search(rf"\b[gb]{year_short}\b|\b{year_short}[gb]\b", combined):
        return 0.95
    # Year short as standalone word
    if re.search(rf"\b{year_short}\b", combined):
        return 0.80
    # Age-group string: u11, u-11
    if re.search(rf"\bu[\-]?{year_short}\b", combined):
        return 0.75
    return 0.0


def _gender_score(
    gender: str,
    birth_year: Optional[int],
    handle: str,
    title: str,
    snippet: str,
) -> float:
    """Presence / absence of gender markers. Returns 0.0 if opposite gender found."""
    combined = f"{handle} {title} {snippet}".lower()
    word_markers = GENDER_WORDS.get(gender, [])
    abbr = GENDER_ABBRS.get(gender, "")
    opposite = GENDER_WORDS.get("Male" if gender == "Female" else "Female", [])

    # Hard penalty if opposite gender word is detected
    for word in opposite:
        if re.search(rf"\b{re.escape(word)}\b", combined):
            return 0.0

    # Full word match (girls, boys, womens…)
    for word in word_markers:
        if re.search(rf"\b{re.escape(word)}\b", combined):
            return 1.0

    # Abbreviation inside year pattern: g11, 11g, b11, 11b
    if birth_year and abbr:
        ys = str(birth_year)[-2:]
        yf = str(birth_year)
        pattern = rf"{abbr}{ys}|{ys}{abbr}|{abbr}{yf}|{yf}{abbr}"
        if re.search(pattern, combined):
            return 0.90

    # Standalone abbreviation — weaker signal
    if abbr and re.search(rf"\b{abbr}\b", combined):
        return 0.60

    return 0.5  # Neutral — no marker detected either way


def _tier_score(
    team_name: str, club_name: str, handle: str, title: str, snippet: str
) -> float:
    """Match tier/division words between team and candidate. 0.0–1.0."""
    combined = f"{handle} {title} {snippet}".lower()
    team_combined = f"{team_name} {club_name}".lower()
    team_tiers = {t for t in TIER_WORDS if t in team_combined}
    cand_tiers = {t for t in TIER_WORDS if t in combined}

    if not team_tiers:
        return 0.5        # No tier in team name — neutral regardless
    if team_tiers & cand_tiers:
        return 1.0        # Matching tier word found
    if cand_tiers:
        return 0.20       # Different tier present — mild penalty
    return 0.35           # Team has tier, candidate doesn't mention it


# ──────────────────────────────────────────────────────────────────────────────
# InstagramScorer
# ──────────────────────────────────────────────────────────────────────────────

def _handle_identity_score(
    club_name: str,
    birth_year: Optional[int],
    gender: str,
    team_name: str,
    handle: str,
) -> float:
    """Substring decomposition of the handle against the three core identity
    signals: club abbreviation, birth year, and distinction (coach/color/tier).

    Instagram handles are concatenated strings (e.g. ccv2013gaaspire) so
    token-based matching misses them entirely.  This function checks whether
    the handle encodes the team identity as substrings.

    Returns 1.0 when club + year + distinction are all present,
    graded down for partial matches.  Returns 0.0 when nothing matches.
    """
    h = handle.lower().replace("_", "").replace(".", "")

    # ── Club identity ────────────────────────────────────────────────────
    club_initials = QueryGenerator._club_initials(club_name).lower()
    club_short = QueryGenerator._short_club(club_name).lower().replace(" ", "")
    has_club = False
    if club_initials and len(club_initials) >= 2 and club_initials in h:
        has_club = True
    if not has_club and len(club_short) >= 3 and club_short in h:
        has_club = True
    if not has_club:
        meaningful = _meaningful_club_tokens(club_name)
        for tok in meaningful:
            if len(tok) >= 3 and tok in h:
                has_club = True
                break

    # ── Birth year ───────────────────────────────────────────────────────
    has_year = False
    if birth_year:
        yf = str(birth_year)
        ys = yf[-2:]
        if yf in h or ys in h:
            has_year = True

    # ── Distinction (the team-specific part: Elite, Aspire, Red, etc.) ──
    suffix = QueryGenerator._team_suffix(team_name, club_name)
    dist = QueryGenerator._distinction(suffix, birth_year, gender)
    dist_tokens = [t.lower() for t in dist.split() if len(t) >= 3]
    has_dist = any(t in h for t in dist_tokens) if dist_tokens else False

    if has_club and has_year and has_dist:
        return 1.0
    if has_club and has_year:
        return 0.65
    if has_club and has_dist:
        return 0.55
    if has_club:
        return 0.30
    return 0.0


class InstagramScorer:
    """
    Score an Instagram search result against a team's identity fields.

    Two scoring paths are combined:
      1. Token-based scoring (club_score, year, gender, tier) — works well
         when the search title/snippet contain readable text.
      2. Handle identity decomposition — substring matching against the
         concatenated handle itself (e.g. ccv2013gaaspire → CCV+2013+aspire).

    The final confidence is the max of both paths, so a handle that clearly
    encodes club+year+distinction auto-approves even if the title is generic.
    """

    @staticmethod
    def score(
        handle: str,
        title: str,
        snippet: str,
        team: Dict[str, Any],
    ) -> Dict[str, Any]:
        club = (team.get("club_name") or team.get("team_name") or "").strip()
        birth_year: Optional[int] = team.get("birth_year")
        gender: str = (team.get("gender") or "").strip()
        team_name: str = (team.get("team_name") or "").strip()

        cs = _club_score(club, handle, title, team_name)
        ys = _year_score(birth_year, handle, title, snippet)
        gs = _gender_score(gender, birth_year, handle, title, snippet)
        ts = _tier_score(team_name, club, handle, title, snippet)

        token_conf = cs * 0.40 + ys * 0.25 + gs * 0.20 + ts * 0.15

        # Handle substring decomposition (catches concatenated handles)
        hi = _handle_identity_score(club, birth_year, gender, team_name, handle)

        confidence = round(max(token_conf, hi), 3)

        return {
            "confidence": confidence,
            "club_score": round(cs, 3),
            "year_score": round(ys, 3),
            "gender_score": round(gs, 3),
            "tier_score": round(ts, 3),
            "handle_identity": round(hi, 3),
            "handle": handle,
        }


# ──────────────────────────────────────────────────────────────────────────────
# QueryGenerator
# ──────────────────────────────────────────────────────────────────────────────

class QueryGenerator:
    """
    Generate site:instagram.com search query variations for a team.

    Covers the inconsistent naming patterns seen in youth soccer accounts:
      - Full year vs. short year: "2011" vs "11"
      - Gender word vs. abbreviation: "girls" vs "g"
      - Club full name vs. short name (no SC/FC/Academy suffix)
      - Combined gender+year patterns: g11, 11g, G2011
      - State + year for disambiguation
    """

    @staticmethod
    def _short_club(club_name: str) -> str:
        # Split on whitespace only (no normalizer) to keep token count stable,
        # check suffix membership via .lower() to preserve original casing.
        tokens = club_name.split()
        kept = [t for t in tokens if t.lower() not in CLUB_SUFFIXES]
        return " ".join(kept) if kept else club_name

    _LOCATION_WORDS: Set[str] = {
        "north", "south", "east", "west", "central", "northern", "southern",
        "eastern", "western", "northeast", "northwest", "southeast", "southwest",
        "valley", "bay", "coast", "county", "region", "area", "metro",
    }

    @classmethod
    def _club_initials(cls, club_name: str) -> str:
        """Extract the abbreviated club identity used in handles.
        'RSL Arizona North' → 'rsl'   (first token is already an abbreviation)
        'NEFC'              → 'nefc'  (single short token)
        'Phoenix Premier FC'→ 'pp'    (first letters of non-suffix words)
        Returns '' if result would be <2 chars.
        """
        tokens = club_name.split()
        skip = CLUB_SUFFIXES | cls._LOCATION_WORDS
        kept = [t for t in tokens if t.lower() not in skip]
        if not kept:
            kept = tokens

        first = kept[0]
        if first.isupper() or len(first) <= 4:
            return first.lower()

        parts = [t[0].lower() for t in kept if len(t) > 1]
        initials = "".join(parts)
        return initials if len(initials) >= 2 else ""

    @staticmethod
    def _team_suffix(team_name: str, club_name: str) -> str:
        """Extract the team-specific part of team_name that isn't in club_name.
        e.g. club='Phoenix United Futbol Club', team='Phoenix United 2015 Elite'
             → '2015 Elite'
        """
        if not team_name or not club_name:
            return ""
        club_toks = {t.lower() for t in club_name.split()}
        suffix_toks = [t for t in team_name.split() if t.lower() not in club_toks]
        return " ".join(suffix_toks).strip()

    @staticmethod
    def _distinction(suffix: str, birth_year: Optional[int], gender: str) -> str:
        """Extract the team distinction from the suffix — the part that isn't
        year or gender.  This is the coach name, color, tier, sub-team, etc.

        '2015 Elite'           → 'Elite'
        '2015 AChacon Pre-MLS Next' → 'AChacon Pre-MLS Next'
        'Southeast 2015 Red'   → 'Southeast Red'
        '2015B'                → ''
        """
        if not suffix:
            return ""
        year_strs: Set[str] = set()
        if birth_year:
            yf = str(birth_year)
            ys = yf[-2:]
            year_strs = {yf, ys, f"{ys}b", f"{ys}g", f"b{ys}", f"g{ys}",
                         f"{yf}b", f"{yf}g", f"b{yf}", f"g{yf}"}
        gender_strs = set()
        for words in GENDER_WORDS.values():
            gender_strs.update(w.lower() for w in words)
        gender_strs.update(GENDER_ABBRS.values())

        skip = year_strs | gender_strs | {"#1", "#2", "#3", "#4", "#5"}
        parts = [t for t in suffix.split() if t.lower().rstrip(".,") not in skip]
        return " ".join(parts).strip()

    @classmethod
    def generate(cls, team: Dict[str, Any]) -> List[str]:
        club = (team.get("club_name") or team.get("team_name") or "").strip()
        team_name = (team.get("team_name") or "").strip()
        birth_year: Optional[int] = team.get("birth_year")
        gender: str = (team.get("gender") or "").strip()
        state_code: str = (team.get("state_code") or "").strip().lower()

        if not club:
            return []

        club_short = cls._short_club(club)
        year_full = str(birth_year) if birth_year else ""
        year_short = year_full[-2:] if len(year_full) == 4 else ""
        g_word = GENDER_WORDS.get(gender, [""])[0]   # "girls" / "boys"
        g_abbr = GENDER_ABBRS.get(gender, "")         # "g" / "b"
        suffix = cls._team_suffix(team_name, club)     # "2015 Elite", "2015 Conroy", etc.
        dist = cls._distinction(suffix, birth_year, gender)  # "Elite", "AChacon", "Red", etc.

        queries: List[str] = []

        # ── Team-name queries (highest priority) ────────────────────────────
        if team_name and team_name.lower() != club.lower() and len(team_name) > 4:
            queries.append(f'site:instagram.com "{team_name}"')

        # ── Distinction queries (club + distinction + year) ─────────────────
        # The distinction is what makes this team unique: coach name, color,
        # tier (Elite, Black, Red, ECNL, etc.)
        if dist:
            queries.append(f'site:instagram.com "{club_short}" "{dist}" {year_full}')
            if year_short:
                queries.append(f'site:instagram.com "{club_short}" {year_short} {dist}')
            queries.append(f'site:instagram.com "{club_short}" "{dist}"')

        # Full suffix as fallback (less targeted)
        if suffix and suffix != dist:
            queries.append(f'site:instagram.com "{club_short}" "{suffix}"')

        # ── Year + gender patterns ──────────────────────────────────────────
        if year_full and g_word:
            queries.append(f'site:instagram.com "{club_short}" "{year_full} {g_word}"')

        if year_short and g_abbr:
            queries.append(f'site:instagram.com "{club_short}" "{g_abbr}{year_short}"')

        # ── Abbreviation patterns (rslaz15boys, nefcma14g, etc.) ─────────
        initials = cls._club_initials(club)
        if initials and year_short:
            state_lc = state_code.lower() if state_code else ""
            if state_lc and g_word:
                queries.append(
                    f'site:instagram.com {initials} {state_lc} {year_short} {g_word}'
                )
            if g_word:
                queries.append(
                    f'site:instagram.com {initials} {year_short} {g_word}'
                )

        # ── Year only (some accounts omit gender) ─────────────────────────
        if year_full:
            queries.append(f'site:instagram.com "{club_short}" {year_full}')

        # ── Fallback: club name with "soccer" keyword ─────────────────────
        queries.append(f'site:instagram.com "{club}" soccer')

        # De-duplicate while preserving order; cap at 12
        seen: Set[str] = set()
        unique: List[str] = []
        for q in queries:
            if q not in seen:
                seen.add(q)
                unique.append(q)
        return unique[:12]


# ──────────────────────────────────────────────────────────────────────────────
# ClubQueryGenerator  (Phase 1 — club-level, no year/gender)
# ──────────────────────────────────────────────────────────────────────────────

class ClubQueryGenerator:
    """
    Generate site:instagram.com query variations for a club name only.
    Used in Phase 1 where we want the main club account, not a team-specific one.
    Queries are deliberately broader — no birth year or gender signals.
    """

    @classmethod
    def generate(cls, club_name: str, state_code: str = "") -> List[str]:
        club_short = QueryGenerator._short_club(club_name)
        state = state_code.lower() if state_code else ""

        queries: List[str] = [
            f'site:instagram.com "{club_name}"',
            f'site:instagram.com "{club_name}" soccer',
        ]

        if club_short.lower() != club_name.lower():
            queries.append(f'site:instagram.com "{club_short}" soccer club')
            queries.append(f'site:instagram.com "{club_short}" youth soccer')

        if state:
            queries.append(f'site:instagram.com "{club_name}" {state}')

        # FC / SC suffix variants for clubs that use them inconsistently
        queries.append(f'site:instagram.com "{club_name}" fc OR sc')

        seen: Set[str] = set()
        unique: List[str] = []
        for q in queries:
            if q not in seen:
                seen.add(q)
                unique.append(q)
        return unique[:7]


# ──────────────────────────────────────────────────────────────────────────────
# SerperClient
# ──────────────────────────────────────────────────────────────────────────────

class SerperClient:
    """
    Thin wrapper around the Serper.dev Google Search JSON API.
    One instance per thread — each maintains its own requests.Session.

    API docs: https://serper.dev/api
    Pricing:  ~$0.001/query on paid plans; 2,500 free queries on signup.
    """

    BASE_URL = "https://google.serper.dev/search"

    def __init__(self, api_key: str, timeout: int = 15, delay_seconds: float = 0.5):
        self.api_key = api_key
        self.timeout = timeout
        self.delay_seconds = delay_seconds
        self.session = requests.Session()
        self.session.headers.update(
            {"X-API-KEY": api_key, "Content-Type": "application/json"}
        )

    def search(self, query: str, num_results: int = 5) -> List[Dict[str, Any]]:
        """
        Execute a Google search and return the organic results list.
        Returns [] on any error (error is swallowed — caller checks for empty).
        A {"_error": msg} sentinel is used if the caller needs to distinguish
        API errors from "no results".
        """
        time.sleep(self.delay_seconds)
        try:
            resp = self.session.post(
                self.BASE_URL,
                json={"q": query, "num": num_results, "gl": "us"},
                timeout=self.timeout,
            )
            if resp.status_code == 429:
                # Rate-limited: back off and surface as error
                time.sleep(5)
                return [{"_error": "rate_limited"}]
            resp.raise_for_status()
            return resp.json().get("organic", [])
        except Exception as e:
            return [{"_error": str(e)}]


# ──────────────────────────────────────────────────────────────────────────────
# Handle extraction
# ──────────────────────────────────────────────────────────────────────────────

def extract_instagram_handle(url: str) -> Optional[str]:
    """Extract @handle from an Instagram URL. Returns None for system pages."""
    if not url:
        return None
    m = INSTAGRAM_HANDLE_RE.search(url)
    if not m:
        return None
    handle = m.group(1).rstrip("/").lower()
    if not handle or len(handle) < 2:
        return None
    if handle in INSTAGRAM_SYSTEM_PAGES:
        return None
    return handle


# ──────────────────────────────────────────────────────────────────────────────
# Supabase helpers  (same patterns as backfill_missing_club_names.py)
# ──────────────────────────────────────────────────────────────────────────────

def load_env() -> None:
    env_local = Path(".env.local")
    if env_local.exists():
        load_dotenv(env_local, override=True)
    else:
        load_dotenv()


def get_supabase():
    url = os.getenv("SUPABASE_URL") or os.getenv("NEXT_PUBLIC_SUPABASE_URL")
    key = (
        os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        or os.getenv("SUPABASE_SERVICE_KEY")
        or os.getenv("SUPABASE_KEY")
    )
    if not url or not key:
        raise ValueError(
            "Missing Supabase credentials. Need SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY."
        )
    return create_client(url, key)


def fetch_already_processed_ids(
    supabase, re_check: bool, phase: int = 1
) -> Set[str]:
    """
    Return team_ids that already have a finalized record for this phase.
    Phase 1 checks for existing club-level handles.
    Phase 2 checks for existing team-level handles.
    With --re-check: only skip 'confirmed' (re-runs needs_review).
    """
    statuses = ["confirmed"] if re_check else ["auto_approved", "confirmed"]
    profile_level = "club" if phase == 1 else "team"
    page_size = 1000
    offset = 0
    ids: Set[str] = set()
    while True:
        rows = (
            supabase.table("team_social_profiles")
            .select("team_id")
            .eq("platform", PLATFORM)
            .eq("profile_level", profile_level)
            .in_("review_status", statuses)
            .range(offset, offset + page_size - 1)
            .execute()
            .data
            or []
        )
        for r in rows:
            if r.get("team_id"):
                ids.add(r["team_id"])
        if len(rows) < page_size:
            break
        offset += page_size
    return ids


def fetch_all_club_handles(supabase) -> Set[str]:
    """
    Fetch every handle stored as a club-level profile (Phase 1 results).
    Returns a flat set of handles.  Phase 2 excludes ANY search result
    whose handle is in this set, regardless of which team we're searching
    for — club handles are never valid team-specific results.
    """
    handles: Set[str] = set()
    page_size = 1000
    offset = 0
    while True:
        rows = (
            supabase.table("team_social_profiles")
            .select("handle")
            .eq("platform", PLATFORM)
            .eq("profile_level", "club")
            .range(offset, offset + page_size - 1)
            .execute()
            .data
            or []
        )
        for r in rows:
            if r.get("handle"):
                handles.add(r["handle"].lower())
        if len(rows) < page_size:
            break
        offset += page_size
    return handles


def fetch_ranked_team_ids(supabase, min_power_score: float) -> Optional[Set[str]]:
    """
    Return set of active team_ids with power_score_final >= threshold.
    Returns None when min_power_score == 0 (no filter applied).
    """
    if min_power_score <= 0:
        return None
    page_size = 1000
    offset = 0
    ids: Set[str] = set()
    while True:
        rows = (
            supabase.table("rankings_full")
            .select("team_id")
            .gte("power_score_final", min_power_score)
            .eq("status", "Active")
            .range(offset, offset + page_size - 1)
            .execute()
            .data
            or []
        )
        for r in rows:
            if r.get("team_id"):
                ids.add(r["team_id"])
        if len(rows) < page_size:
            break
        offset += page_size
    return ids


def fetch_power_scores(supabase, team_ids: List[str]) -> Dict[str, float]:
    """Map team_id → power_score_final for sort-by-importance. Missing = 0.0."""
    scores: Dict[str, float] = {}
    for i in range(0, len(team_ids), 500):
        batch = team_ids[i : i + 500]
        rows = (
            supabase.table("rankings_full")
            .select("team_id,power_score_final")
            .in_("team_id", batch)
            .execute()
            .data
            or []
        )
        for r in rows:
            tid = r.get("team_id")
            ps = r.get("power_score_final")
            if tid and ps is not None:
                scores[tid] = float(ps)
    return scores


def fetch_teams_to_enrich(
    supabase,
    args: argparse.Namespace,
    already_done: Set[str],
    rank_filter_ids: Optional[Set[str]],
) -> List[Dict[str, Any]]:
    """
    Paginate teams table with optional filters.
    Excludes deprecated teams and teams already processed.
    """
    page_size = 1000
    offset = 0
    rows: List[Dict[str, Any]] = []
    seen: Set[str] = set()

    while True:
        query = (
            supabase.table("teams")
            .select(
                "team_id_master,team_name,club_name,birth_year,gender,age_group,state_code"
            )
            .eq("is_deprecated", False)
        )
        if args.state:
            query = query.eq("state_code", args.state.upper())
        if args.gender:
            g = (
                "Male"
                if args.gender.upper() in ("M", "MALE", "B", "BOYS")
                else "Female"
            )
            query = query.eq("gender", g)
        if args.age_group:
            ag = re.sub(r"[^0-9]", "", args.age_group)
            if ag:
                query = query.ilike("age_group", f"%{ag}%")

        batch = query.range(offset, offset + page_size - 1).execute().data or []
        if not batch:
            break

        for r in batch:
            tid = r.get("team_id_master")
            if not tid or tid in seen:
                continue
            if tid in already_done:
                continue
            if rank_filter_ids is not None and tid not in rank_filter_ids:
                continue
            seen.add(tid)
            rows.append(r)
            if args.limit and len(rows) >= args.limit:
                return rows

        if len(batch) < page_size:
            break
        offset += page_size

    return rows


def fetch_top_n_per_cohort_ids(
    supabase,
    top_n: int,
    already_done: Set[str],
    state_filter: Optional[str] = None,
    age_filter: Optional[str] = None,
    gender_filter: Optional[str] = None,
    national: bool = False,
) -> Tuple[List[str], Dict[str, int]]:
    """
    Select the top N teams by power_score_final within every cohort.

    Cohort grouping:
      - Default: (state_code, age_group, gender)
      - national=True: (age_group, gender) — top N nationally regardless of state

    Optional filters narrow to a specific state, age group, or gender.

    Returns:
        (ordered_team_ids, cohort_counts)
        ordered_team_ids: sorted by power_score desc within each cohort,
                          then cohorts sorted alphabetically
        cohort_counts: { "u14|Female": 100, ... } for summary logging
    """
    page_size = 1000
    offset = 0
    all_rows: List[Dict[str, Any]] = []

    while True:
        query = (
            supabase.table("rankings_full")
            .select("team_id,power_score_final,age_group,gender,state_code")
            .eq("status", "Active")
            .not_.is_("power_score_final", "null")
        )
        if not national:
            query = query.not_.is_("state_code", "null")
        if state_filter:
            query = query.eq("state_code", state_filter.upper())
        if age_filter:
            norm = age_filter.lower().replace("u", "")
            query = query.eq("age_group", f"u{norm}")
        if gender_filter:
            query = query.eq("gender", gender_filter)
        rows = query.range(offset, offset + page_size - 1).execute().data or []
        all_rows.extend(rows)
        if len(rows) < page_size:
            break
        offset += page_size

    # Group into cohorts — national mode ignores state
    cohorts: DefaultDict[Tuple[str, ...], List[Dict[str, Any]]] = defaultdict(list)
    for r in all_rows:
        tid = r.get("team_id")
        if not tid or tid in already_done:
            continue
        age = (r.get("age_group") or "").strip().lower()
        gender = (r.get("gender") or "").strip()
        if not age or not gender:
            continue
        if national:
            cohorts[(age, gender)].append(r)
        else:
            state = (r.get("state_code") or "").strip().upper()
            if state:
                cohorts[(state, age, gender)].append(r)

    # Take top N per cohort, ordered by power_score desc
    selected_ids: List[str] = []
    cohort_counts: Dict[str, int] = {}
    for cohort_key in sorted(cohorts.keys()):
        group = sorted(
            cohorts[cohort_key],
            key=lambda x: x.get("power_score_final") or 0.0,
            reverse=True,
        )
        top = group[:top_n]
        for r in top:
            selected_ids.append(r["team_id"])
        cohort_label = "|".join(cohort_key)
        cohort_counts[cohort_label] = len(top)

    return selected_ids, cohort_counts


def fetch_teams_by_ids(supabase, team_ids: List[str]) -> List[Dict[str, Any]]:
    """
    Efficiently fetch team identity fields for a known list of team_ids.
    Uses batched .in_() queries (500 IDs per call) instead of full table scan.
    """
    rows: List[Dict[str, Any]] = []
    for i in range(0, len(team_ids), 500):
        batch = team_ids[i : i + 500]
        batch_rows = (
            supabase.table("teams")
            .select(
                "team_id_master,team_name,club_name,birth_year,gender,age_group,state_code"
            )
            .in_("team_id_master", batch)
            .eq("is_deprecated", False)
            .execute()
            .data
            or []
        )
        rows.extend(batch_rows)
    return rows


def fetch_clubs_for_phase1(
    supabase,
    args: argparse.Namespace,
    already_done_team_ids: Set[str],
) -> List[Dict[str, Any]]:
    """
    Deduplicate teams by club name and return one entry per unique club.
    Each entry: {display_name, norm_name, team_ids, state_code}

    Skips any club where at least one team_id already has a club-level handle
    (Phase 1 writes to all teams in a club simultaneously, so one = all done).
    """
    page_size = 1000
    offset = 0
    club_groups: DefaultDict[str, Dict[str, Any]] = defaultdict(
        lambda: {"display_name": "", "team_ids": [], "state_counts": defaultdict(int)}
    )

    while True:
        query = (
            supabase.table("teams")
            .select("team_id_master,club_name,state_code")
            .eq("is_deprecated", False)
            .not_.is_("club_name", "null")
            .neq("club_name", "")
        )
        if args.state:
            query = query.eq("state_code", args.state.upper())

        batch = query.range(offset, offset + page_size - 1).execute().data or []
        if not batch:
            break

        for r in batch:
            tid = r.get("team_id_master")
            club = (r.get("club_name") or "").strip()
            if not tid or not club:
                continue
            norm = _normalize_text(club)
            if not norm:
                continue
            grp = club_groups[norm]
            if not grp["display_name"]:
                grp["display_name"] = club
            grp["team_ids"].append(tid)
            state = r.get("state_code") or ""
            if state:
                grp["state_counts"][state] += 1

        if len(batch) < page_size:
            break
        offset += page_size

    clubs: List[Dict[str, Any]] = []
    for norm, grp in sorted(club_groups.items()):
        team_ids = grp["team_ids"]
        # Skip entire club if any of its teams already has a club-level handle
        if any(tid in already_done_team_ids for tid in team_ids):
            continue
        state_counts = grp["state_counts"]
        state_code = max(state_counts, key=state_counts.get) if state_counts else ""
        clubs.append(
            {
                "display_name": grp["display_name"],
                "norm_name": norm,
                "team_ids": team_ids,
                "state_code": state_code,
            }
        )
        if args.limit and len(clubs) >= args.limit:
            break

    return clubs


def process_club(
    club: Dict[str, Any],
    api_key: str,
    delay: float,
) -> Tuple[Optional[str], float, str, Dict[str, Any]]:
    """
    Run Phase 1 queries for one club. Scores on club name match only.

    Returns:
        (handle | None, confidence, query_used, match_details)
    """
    display_name = club["display_name"]
    state_code = club.get("state_code", "")
    queries = ClubQueryGenerator.generate(display_name, state_code)

    client = SerperClient(api_key, delay_seconds=delay)
    candidates: Dict[str, Dict[str, Any]] = {}
    api_errors = 0

    for query in queries:
        results = client.search(query)
        for r in results:
            if "_error" in r:
                api_errors += 1
                continue
            handle = extract_instagram_handle(r.get("link", ""))
            if not handle:
                continue
            # Phase 1 confidence = club name score only
            cs = _club_score(display_name, handle, r.get("title", ""))
            existing = candidates.get(handle, {})
            if cs > existing.get("confidence", -1):
                candidates[handle] = {
                    "confidence": round(cs, 3),
                    "club_score": round(cs, 3),
                    "handle": handle,
                    "query_used": query,
                    "title": r.get("title", ""),
                    "snippet": r.get("snippet", ""),
                }

    if api_errors > 0 and not candidates:
        return None, 0.0, "", {"error": f"All {api_errors} API call(s) failed"}

    if not candidates:
        return None, 0.0, "", {}

    best = max(candidates.values(), key=lambda x: x["confidence"])
    return (
        best["handle"],
        best["confidence"],
        best["query_used"],
        {
            "club_score": best["club_score"],
            "phase": 1,
            "title": best.get("title", ""),
            "snippet": best.get("snippet", "")[:200],
        },
    )


def upsert_result(
    supabase,
    team_id: str,
    handle: str,
    confidence: float,
    query_used: str,
    match_details: Dict[str, Any],
    dry_run: bool,
    log,
    profile_level: str = "team",
) -> bool:
    """Upsert a social profile record. On conflict (team+platform+level), latest run wins."""
    if confidence >= AUTO_APPROVE_THRESHOLD:
        status = "auto_approved"
    elif confidence >= NEEDS_REVIEW_THRESHOLD:
        status = "needs_review"
    else:
        status = "rejected"

    record = {
        "team_id": team_id,
        "platform": PLATFORM,
        "handle": handle,
        "profile_url": f"https://instagram.com/{handle}",
        "confidence_score": confidence,
        "query_used": query_used,
        "match_details": json.dumps(match_details),
        "review_status": status,
        "profile_level": profile_level,
        "last_checked_at": "now()",
    }

    if dry_run:
        return True

    try:
        supabase.table("team_social_profiles").upsert(
            record,
            on_conflict="team_id,platform,profile_level",
        ).execute()
        return True
    except Exception as e:
        log(f"  ERROR upserting @{handle}: {e}")
        return False


# ──────────────────────────────────────────────────────────────────────────────
# Core per-team processing
# ──────────────────────────────────────────────────────────────────────────────

def process_team(
    team: Dict[str, Any],
    api_key: str,
    delay: float,
    club_handles: Optional[Set[str]] = None,
) -> Tuple[str, Optional[Dict[str, Any]], Optional[str]]:
    """
    Run all queries for one team and return the single best candidate.

    Args:
        club_handles: handles already stored as club-level for this team.
            Any match is excluded so Phase 2 only stores genuinely
            team-specific accounts.

    Returns:
        (team_id, best_result | None, error_msg | None)

    best_result keys: confidence, handle, query_used, club_score,
                      year_score, gender_score, tier_score, title, snippet
    """
    team_id = team["team_id_master"]
    queries = QueryGenerator.generate(team)
    if not queries:
        return (team_id, None, "No queries generated (missing club name)")

    exclude = club_handles or set()

    client = SerperClient(api_key, delay_seconds=delay)
    candidates: Dict[str, Dict[str, Any]] = {}  # handle → best scored result
    api_errors = 0

    for query in queries:
        results = client.search(query)
        for r in results:
            if "_error" in r:
                api_errors += 1
                continue
            handle = extract_instagram_handle(r.get("link", ""))
            if not handle:
                continue
            if handle in exclude:
                continue
            scored = InstagramScorer.score(
                handle,
                r.get("title", ""),
                r.get("snippet", ""),
                team,
            )
            existing = candidates.get(handle, {})
            if scored["confidence"] > existing.get("confidence", -1):
                candidates[handle] = {
                    **scored,
                    "query_used": query,
                    "title": r.get("title", ""),
                    "snippet": r.get("snippet", ""),
                }

    if api_errors > 0 and not candidates:
        return (team_id, None, f"All {api_errors} API call(s) failed")

    if not candidates:
        return (team_id, None, None)  # No Instagram results found

    best = max(candidates.values(), key=lambda x: x["confidence"])
    return (team_id, best, None)


# ──────────────────────────────────────────────────────────────────────────────
# main
# ──────────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Discover Instagram handles for PitchRank teams via Serper.dev"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview results without writing to the database",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Max teams to process (default: all eligible)",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.5,
        help="Seconds between Serper API calls per worker (default: 0.5)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=3,
        help="Concurrent workers (default: 3). Keep low to respect Serper rate limits.",
    )
    parser.add_argument(
        "--min-power-score",
        type=float,
        default=0.0,
        dest="min_power_score",
        help="Only process teams with power_score_final >= this value (default: 0 = all)",
    )
    parser.add_argument(
        "--state",
        type=str,
        default=None,
        help="Filter to a single 2-letter state code (e.g. TX, CA)",
    )
    parser.add_argument(
        "--age-group",
        type=str,
        default=None,
        dest="age_group",
        help="Filter to a single age group (e.g. u14, 14)",
    )
    parser.add_argument(
        "--gender",
        type=str,
        default=None,
        help="Filter: Male/Female or M/F/Boys/Girls",
    )
    parser.add_argument(
        "--re-check",
        action="store_true",
        dest="re_check",
        help="Re-run teams that already have needs_review results (still skips confirmed)",
    )
    parser.add_argument(
        "--phase",
        type=int,
        default=1,
        choices=[1, 2],
        help=(
            "Search phase: "
            "1 = club handles (deduplicated, no year/gender — run first, default), "
            "2 = team-specific handles (year + gender queries — run after Phase 1)"
        ),
    )
    parser.add_argument(
        "--top-n-per-cohort",
        type=int,
        default=None,
        dest="top_n_per_cohort",
        help=(
            "Select the top N teams by power_score_final within every "
            "(state × age_group × gender) cohort. "
            "Best starting point for a targeted sweep. "
            "Use with --limit to cap total teams for testing."
        ),
    )
    parser.add_argument(
        "--national",
        action="store_true",
        help=(
            "Group cohorts by (age_group × gender) instead of "
            "(state × age_group × gender).  Selects the top N teams "
            "nationally per age/gender.  Requires --top-n-per-cohort."
        ),
    )
    args = parser.parse_args()

    workers = max(1, args.workers)
    delay = args.delay

    load_env()

    serper_key = os.getenv("SERPER_API_KEY")
    if not serper_key:
        print("ERROR: SERPER_API_KEY environment variable is not set.")
        print("Get your free key at https://serper.dev")
        sys.exit(1)

    supabase = get_supabase()

    log_lock = threading.Lock()

    def log(msg: str) -> None:
        with log_lock:
            print(msg, flush=True)

    log("=== Instagram Handle Discovery ===")
    log(f"Phase:   {args.phase}  ({'club handles' if args.phase == 1 else 'team-specific handles'})")
    log(f"Mode:    {'DRY-RUN (no DB writes)' if args.dry_run else 'LIVE'}")
    log(f"Workers: {workers}  |  Delay: {delay}s/call")

    # ── Fetch exclusion list (phase-aware) ────────────────────────────────────
    log("Fetching already-processed teams...")
    already_done = fetch_already_processed_ids(supabase, args.re_check, args.phase)
    log(f"Already processed (skipping): {len(already_done):,}")

    # ══════════════════════════════════════════════════════════════════════════
    # PHASE 1 — Club handle sweep
    # Deduplicate teams by club name, search once per unique club,
    # write result to every team in that club.
    # ══════════════════════════════════════════════════════════════════════════
    if args.phase == 1:
        log("Fetching unique clubs to search...")
        clubs = fetch_clubs_for_phase1(supabase, args, already_done)

        if not clubs:
            log("No eligible clubs found. Nothing to do.")
            return

        total_teams_covered = sum(len(c["team_ids"]) for c in clubs)
        log(f"Unique clubs to search:   {len(clubs):,}")
        log(f"Teams that will be covered: {total_teams_covered:,}")
        log(f"Est. Serper queries:      ~{len(clubs) * 5:,}")
        log("")

        p1_found = 0
        p1_auto = 0
        p1_review = 0
        p1_no_result = 0
        p1_api_errors = 0
        p1_db_errors = 0

        def handle_club_result(
            club: Dict[str, Any],
            handle: Optional[str],
            confidence: float,
            query_used: str,
            details: Dict[str, Any],
        ) -> None:
            nonlocal p1_found, p1_auto, p1_review, p1_no_result, p1_api_errors, p1_db_errors

            if details.get("error"):
                p1_api_errors += 1
                if p1_api_errors <= 5:
                    log(f"  ERROR [{club['display_name'][:40]}]: {details['error']}")
                return

            if handle is None or confidence < NEEDS_REVIEW_THRESHOLD:
                p1_no_result += 1
                return

            if confidence >= AUTO_APPROVE_THRESHOLD:
                tag = "AUTO  "
                p1_auto += 1
            else:
                tag = "REVIEW"
                p1_review += 1

            p1_found += 1
            prefix = "[DRY-RUN] " if args.dry_run else ""
            n_teams = len(club["team_ids"])
            log(
                f"  {prefix}[{tag}] {club['display_name'][:45]:<45}"
                f"  @{handle:<30}  {confidence:.3f}"
                f"  → {n_teams} team(s)"
            )

            for team_id in club["team_ids"]:
                ok = upsert_result(
                    supabase,
                    team_id,
                    handle,
                    confidence,
                    query_used,
                    details,
                    args.dry_run,
                    log,
                    profile_level="club",
                )
                if not ok:
                    p1_db_errors += 1

        if workers <= 1:
            for i, club in enumerate(clubs, start=1):
                handle, confidence, query_used, details = process_club(
                    club, serper_key, delay
                )
                handle_club_result(club, handle, confidence, query_used, details)
                if i % 50 == 0:
                    log(
                        f"  Progress: {i}/{len(clubs)}"
                        f"  found={p1_found}"
                        f"  approved={p1_auto}"
                        f"  review={p1_review}"
                    )
        else:
            with ThreadPoolExecutor(max_workers=workers) as ex:
                futures = {
                    ex.submit(process_club, c, serper_key, delay): c for c in clubs
                }
                done = 0
                for future in as_completed(futures):
                    done += 1
                    club = futures[future]
                    try:
                        handle, confidence, query_used, details = future.result()
                        handle_club_result(club, handle, confidence, query_used, details)
                    except Exception as e:
                        p1_api_errors += 1
                        log(f"  Worker exception [{club['display_name'][:35]}]: {e}")
                    if done % 100 == 0:
                        log(
                            f"  Progress: {done}/{len(clubs)}"
                            f"  found={p1_found}"
                            f"  approved={p1_auto}"
                            f"  review={p1_review}"
                        )

        log("")
        log("=== Phase 1 Summary ===")
        log(f"Clubs searched:           {len(clubs):,}")
        log(f"Club handles found:       {p1_found:,}")
        log(f"  → auto_approved:        {p1_auto:,}")
        log(f"  → needs_review:         {p1_review:,}")
        log(f"No result / low-conf:     {p1_no_result:,}")
        log(f"API / worker errors:      {p1_api_errors:,}")
        log(f"DB write errors:          {p1_db_errors:,}")
        if p1_found > 0:
            pct = round(p1_found / len(clubs) * 100, 1)
            log(f"Hit rate:                 {pct}%")

        if args.dry_run:
            log("")
            log("DRY-RUN complete — no changes written to the database.")
        return  # Phase 1 done — do not fall through to Phase 2

    # ══════════════════════════════════════════════════════════════════════════
    # PHASE 2 — Team-specific handle sweep (year + gender queries)
    # ══════════════════════════════════════════════════════════════════════════

    # ── Team selection ────────────────────────────────────────────────────────
    if args.top_n_per_cohort:
        grouping = "(age_group × gender) nationally" if args.national else "(state × age_group × gender)"
        log(
            f"Cohort mode: top {args.top_n_per_cohort} teams per "
            f"{grouping} cohort..."
        )
        cohort_ids, cohort_counts = fetch_top_n_per_cohort_ids(
            supabase,
            args.top_n_per_cohort,
            already_done,
            state_filter=args.state,
            age_filter=args.age_group,
            gender_filter=args.gender,
            national=args.national,
        )
        total_cohorts = len(cohort_counts)
        total_selected = len(cohort_ids)

        log(f"Cohorts with ranked teams: {total_cohorts:,}")
        log(f"Total teams selected:      {total_selected:,}")
        sample_cohorts = sorted(cohort_counts.items())[:20]
        for cohort_key, count in sample_cohorts:
            parts = cohort_key.split("|")
            if args.national:
                log(f"  {parts[0]:<5s}  {parts[1]:<7s}  → {count} teams")
            else:
                log(f"  {parts[0]:2s}  {parts[1]:<5s}  {parts[2]:<7s}  → {count} teams")
        if len(cohort_counts) > 20:
            log(f"  ... and {len(cohort_counts) - 20} more cohorts")
        log("")

        # Apply --limit after cohort selection (keeps top teams since cohort_ids is
        # sorted by power_score desc within each cohort, then alphabetically by cohort)
        if args.limit:
            cohort_ids = cohort_ids[: args.limit]
            log(f"Capped to {args.limit:,} teams via --limit")

        if not cohort_ids:
            log("No eligible teams found. Nothing to do.")
            return

        log(f"Fetching team identity fields for {len(cohort_ids):,} selected teams...")
        teams = fetch_teams_by_ids(supabase, cohort_ids)

        # Preserve cohort selection order (already sorted by power_score within cohort)
        id_order = {tid: i for i, tid in enumerate(cohort_ids)}
        teams.sort(key=lambda t: id_order.get(t["team_id_master"], 9999))

    else:
        # Standard mode: min-power-score filter + optional state/age/gender filters
        rank_filter_ids: Optional[Set[str]] = None
        if args.min_power_score > 0:
            log(f"Fetching teams with power_score_final >= {args.min_power_score}...")
            rank_filter_ids = fetch_ranked_team_ids(supabase, args.min_power_score)
            log(f"Eligible by rank filter: {len(rank_filter_ids):,}")

        log("Fetching teams to enrich...")
        teams = fetch_teams_to_enrich(supabase, args, already_done, rank_filter_ids)
        if not teams:
            log("No eligible teams found. Nothing to do.")
            return

        # Sort highest-ranked teams first so --limit targets the best ones
        team_ids_list = [t["team_id_master"] for t in teams]
        log(f"Fetching power scores for sort order ({len(team_ids_list):,} teams)...")
        power_scores = fetch_power_scores(supabase, team_ids_list)
        teams.sort(
            key=lambda t: power_scores.get(t["team_id_master"], 0.0), reverse=True
        )

    # ── Fetch ALL club-level handles to exclude from Phase 2 results ─────────
    log("Fetching all club-level handles to exclude from team results...")
    club_handles_global = fetch_all_club_handles(supabase)
    log(f"Club handles to exclude: {len(club_handles_global):,}")

    log(f"Teams to process:    {len(teams):,}")
    log(f"Est. Serper queries: ~{len(teams) * 10:,}")
    log("")

    # ── Counters ──────────────────────────────────────────────────────────────
    found = 0
    auto_approved = 0
    needs_review = 0
    no_results = 0
    api_errors = 0
    db_errors = 0

    def handle_result(
        team: Dict[str, Any],
        best: Optional[Dict[str, Any]],
        err: Optional[str],
    ) -> None:
        nonlocal found, auto_approved, needs_review, no_results, api_errors, db_errors

        team_id = team["team_id_master"]
        club = team.get("club_name") or team.get("team_name") or ""
        label = f"{club[:30]} / {team.get('birth_year')} {team.get('gender', '')}"

        if err:
            api_errors += 1
            if api_errors <= 5:
                log(f"  ERROR [{label}]: {err}")
            return

        if best is None:
            no_results += 1
            return

        conf = best["confidence"]
        handle = best["handle"]

        # Don't store anything below the review threshold
        if conf < NEEDS_REVIEW_THRESHOLD:
            no_results += 1
            return

        if conf >= AUTO_APPROVE_THRESHOLD:
            status_tag = "AUTO  "
            auto_approved += 1
        else:
            status_tag = "REVIEW"
            needs_review += 1

        found += 1

        match_details = {
            "club_score": best["club_score"],
            "year_score": best["year_score"],
            "gender_score": best["gender_score"],
            "tier_score": best["tier_score"],
            "title": best.get("title", ""),
            "snippet": best.get("snippet", "")[:200],
        }

        prefix = "[DRY-RUN] " if args.dry_run else ""
        log(
            f"  {prefix}[{status_tag}] {label:<45}  @{handle:<30}  {conf:.3f}"
        )

        ok = upsert_result(
            supabase,
            team_id,
            handle,
            conf,
            best["query_used"],
            match_details,
            args.dry_run,
            log,
            profile_level="team",
        )
        if not ok:
            db_errors += 1

    # ── Processing loop ───────────────────────────────────────────────────────
    if workers <= 1:
        for i, team in enumerate(teams, start=1):
            team_id, best, err = process_team(
                team, serper_key, delay, club_handles=club_handles_global
            )
            handle_result(team, best, err)
            if i % 50 == 0:
                log(
                    f"  Progress: {i}/{len(teams)}"
                    f"  found={found}"
                    f"  approved={auto_approved}"
                    f"  review={needs_review}"
                )
    else:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futures = {
                ex.submit(
                    process_team, t, serper_key, delay,
                    club_handles=club_handles_global,
                ): t
                for t in teams
            }
            done = 0
            for future in as_completed(futures):
                done += 1
                team = futures[future]
                try:
                    team_id, best, err = future.result()
                    handle_result(team, best, err)
                except Exception as e:
                    api_errors += 1
                    log(f"  Worker exception: {e}")
                if done % 100 == 0:
                    log(
                        f"  Progress: {done}/{len(teams)}"
                        f"  found={found}"
                        f"  approved={auto_approved}"
                        f"  review={needs_review}"
                    )

    # ── Summary ───────────────────────────────────────────────────────────────
    log("")
    log("=== Summary ===")
    log(f"Teams processed:         {len(teams):,}")
    log(f"Handles found (stored):  {found:,}")
    log(f"  → auto_approved:       {auto_approved:,}")
    log(f"  → needs_review:        {needs_review:,}")
    log(f"No result / low-conf:    {no_results:,}")
    log(f"API / worker errors:     {api_errors:,}")
    log(f"DB write errors:         {db_errors:,}")

    if args.dry_run:
        log("")
        log("DRY-RUN complete — no changes written to the database.")


if __name__ == "__main__":
    main()
