"""Structured team-name distinction extraction.

Shared between ``find_fuzzy_duplicate_teams.py`` (masters-vs-masters dedup)
and ``find_queue_matches.py`` (review-queue matching). Both scripts need
the same answer to "are these two team names structurally compatible
duplicates?" — same colors, directions, programs, age tokens, etc.

Extracted here so the queue matcher gets the same discriminating signal
the dedup step has had since the structured-distinction refactor.
"""

from __future__ import annotations

import re

# Two-level path idiom: parent for sibling scripts, grandparent for src.utils.
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.utils.team_name_utils import _canonicalize_age_token

# ── Colors ──────────────────────────────────────────────────────────
TEAM_COLORS = frozenset(
    {
        "red",
        "blue",
        "white",
        "black",
        "gold",
        "grey",
        "gray",
        "green",
        "orange",
        "purple",
        "yellow",
        "navy",
        "maroon",
        "silver",
        "pink",
        "sky",
        "royal",
        "crimson",
    }
)

# ── Directions (full words + abbreviations → canonical) ─────────────
DIRECTION_CANONICAL = {
    "north": "north",
    "south": "south",
    "east": "east",
    "west": "west",
    "central": "central",
    "n": "north",
    "s": "south",
    "e": "east",
    "w": "west",
    "nw": "northwest",
    "ne": "northeast",
    "sw": "southwest",
    "se": "southeast",
    "nth": "north",
    "sth": "south",
}

# ── Programs / leagues ──────────────────────────────────────────────
PROGRAM_WORDS = frozenset(
    {
        "academy",
        "premier",
        "select",
        "elite",
        "ecnl",
        "ecrl",
        "npl",
        "ga",
        "rl",
        "comp",
        "recreational",
        "tal",
        "stxcl",
        "dpl",
        "scdsl",
        "next",
        "copa",
        "nal",
        "reserve",
        "classic",
        "division",
        "fdl",
        "pre",  # qualifier in PRE-ECNL
        "regional",  # alternate name for RL (ECNL Regional League)
    }
)

# ── Location / region codes (sub-club branches) ────────────────────
LOCATION_CODES = frozenset(
    {
        # Texas sub-regions
        "ctx",
        "ntx",
        "stx",
        "etx",
        "wtx",
        # AZ sub-regions
        "phx",
        "sev",
        "wv",
        "ev",
        # CA sub-regions
        "sm",
        "av",
        "mv",
        "le",
        "hb",
        "nb",
        "lb",
        "oc",
        "ie",
        "sfv",
        # General location codes (within-club branches)
        "cp",
        "wc",
        "up",
        "rc",
        "go",
        "sl",
        "tw",
        "tt",
        "cy",
    }
)

# ── Noise words (never differentiate teams) ─────────────────────────
NOISE_WORDS = frozenset(
    {
        "fc",
        "sc",
        "sa",
        "ac",
        "cf",
        "fcs",
        "ysa",
        "soccer",
        "club",
        "futbol",
        "football",
        "youth",
        "boys",
        "girls",
        "the",
        "of",
        "and",
        # NOTE: standalone "b"/"g"/"m"/"f" removed — they are team letters
        # (e.g. "Team A" vs "Team B"), not gender markers. Age+gender combos
        # like "B2014" or "G15" are handled by AGE_PATTERN.
    }
)

# US state codes — not differentiating (just the team's state)
US_STATES = frozenset(
    {
        "al",
        "ak",
        "az",
        "ar",
        "ca",
        "co",
        "ct",
        "de",
        "fl",
        "ga",
        "hi",
        "id",
        "il",
        "in",
        "ia",
        "ks",
        "ky",
        "la",
        "me",
        "md",
        "ma",
        "mi",
        "mn",
        "ms",
        "mo",
        "mt",
        "ne",
        "nv",
        "nh",
        "nj",
        "nm",
        "ny",
        "nc",
        "nd",
        "oh",
        "ok",
        "or",
        "pa",
        "ri",
        "sc",
        "sd",
        "tn",
        "tx",
        "ut",
        "vt",
        "va",
        "wa",
        "wv",
        "wi",
        "wy",
        "dc",
    }
)

# Age/year patterns
AGE_PATTERN = re.compile(r"\b(20\d{2})\b|'(\d{2})(?:/(\d{2}))?|\b[Uu]-?(\d{1,2})\b|\b(\d{1,2})[Uu]\b")


def _tokenize(name: str) -> list[str]:
    """Split name into lowercase tokens, splitting on spaces, hyphens, underscores, and dots."""
    if not name:
        return []
    # Replace hyphens, underscores, dots, slashes with spaces first so "TFA-OC" → "TFA OC"
    normalized = re.sub(r"[-_./]", " ", name.lower())
    return [w.strip("()[]'*") for w in normalized.split() if w.strip("()[]'*")]


def extract_distinctions(name: str, club_name: str = "") -> dict:
    """Extract every distinguishing feature from a team name.

    Returns dict with:
        colors        : frozenset of color words
        directions    : frozenset of canonical direction words
        programs      : frozenset of program/league words
        team_number   : str or None  (1, 2, i, ii, …)
        location_codes: frozenset of short location/region codes
        state_codes   : frozenset of US state codes
        squad_words   : frozenset of remaining differentiating words (mascots, etc.)
        age_tokens    : tuple of canonical age tokens (e.g. 'u14')
        secondary_nums: tuple of numbers appearing AFTER the first age token
    """
    empty = {
        "colors": frozenset(),
        "directions": frozenset(),
        "programs": frozenset(),
        "team_number": None,
        "location_codes": frozenset(),
        "state_codes": frozenset(),
        "squad_words": frozenset(),
        "age_tokens": (),
        "secondary_nums": (),
    }
    if not name:
        return empty

    tokens = _tokenize(name)

    # Strip club name words so they don't become phantom squad_words
    # e.g. "Fever United 2014 Mee" with club "Fever United" → drop "fever"
    # But NEVER strip PROGRAM_WORDS — they carry tier/league meaning even
    # when they overlap with the club name (e.g. "academy" in
    # "Charlotte Soccer Academy" is also the ECNL Academy tier).
    if club_name:
        club_tokens = set(_tokenize(club_name)) - NOISE_WORDS - PROGRAM_WORDS
        tokens = [t for t in tokens if t not in club_tokens]

    colors = set()
    directions = set()
    programs = set()
    location_codes = set()
    state_codes = set()
    team_number = None
    classified = set()  # indices of tokens already assigned a role

    # ── Pass 1: classify known token types ──
    for idx, tok in enumerate(tokens):
        if tok in TEAM_COLORS:
            colors.add(tok)
            classified.add(idx)
        elif tok in DIRECTION_CANONICAL:
            directions.add(DIRECTION_CANONICAL[tok])
            classified.add(idx)
        elif tok in PROGRAM_WORDS:
            programs.add(tok)
            classified.add(idx)
        elif tok in LOCATION_CODES:
            location_codes.add(tok)
            classified.add(idx)
        elif tok in NOISE_WORDS:
            classified.add(idx)
        elif tok in US_STATES:
            state_codes.add(tok)
            classified.add(idx)
        elif re.fullmatch(r"(i{1,3}|iv|v|vi{0,3})", tok):
            team_number = tok
            classified.add(idx)
        elif re.fullmatch(r"[1-9]|10", tok):
            team_number = tok
            classified.add(idx)

    # ── Pass 2: extract canonical age tokens; mask age spans for secondary_nums ──
    age_tokens = []
    age_spans = []
    for m in AGE_PATTERN.finditer(name):
        canonical = _canonicalize_age_token(m.group(0).lower().strip("'"))
        if canonical is not None:
            age_tokens.append(canonical)
        age_spans.append((m.start(), m.end()))

    masked_chars = list(name)
    for start, end in age_spans:
        for i in range(start, min(end, len(masked_chars))):
            masked_chars[i] = " "
    masked = "".join(masked_chars)
    secondary_nums = []
    if age_spans:
        first_end = age_spans[0][1]
        secondary_nums = re.findall(r"\d+", masked[first_end:])

    # ── Pass 3: classify age-token indices ──
    for idx, tok in enumerate(tokens):
        if idx in classified:
            continue
        age_gender_match = re.fullmatch(r"(\d{1,4})u?[bgmf]|[bgmf](\d{1,4})u?|u(\d{1,2})[bgmf]", tok)
        if age_gender_match:
            canonical = _canonicalize_age_token(tok)
            if canonical is not None:
                age_tokens.append(canonical)
            classified.add(idx)
        elif re.fullmatch(r"20\d{2}", tok) or re.fullmatch(r"\d{2}/\d{2}", tok):
            classified.add(idx)
        elif re.fullmatch(r"u-?\d{1,2}|\d{1,2}u", tok) and _canonicalize_age_token(tok) is not None:
            classified.add(idx)
        elif re.fullmatch(r"\d+m?", tok):
            classified.add(idx)

    # ── Pass 4: remaining unclassified tokens → squad words or location codes ──
    squad_words = set()
    for idx, tok in enumerate(tokens):
        if idx in classified:
            continue
        if not tok:
            continue
        if not tok.isalpha() and not tok.isdigit() and len(tok) >= 2:
            squad_words.add(tok)
            continue
        if not tok.isalpha():
            continue
        if len(tok) == 1:
            squad_words.add(tok)
        elif 2 <= len(tok) <= 3:
            location_codes.add(tok)
        elif len(tok) >= 4:
            squad_words.add(tok)

    # ── Normalize program equivalences ──
    if "rl" in programs:
        programs.add("ecnl")  # RL always implies ECNL RL

    return {
        "colors": frozenset(colors),
        "directions": frozenset(directions),
        "programs": frozenset(programs),
        "team_number": team_number,
        "location_codes": frozenset(location_codes),
        "state_codes": frozenset(state_codes),
        "squad_words": frozenset(squad_words),
        "age_tokens": tuple(sorted(set(age_tokens))),
        "secondary_nums": tuple(secondary_nums),
    }


def should_skip_pair(name_a: str, name_b: str, club_name: str = "", *, require_age_token_match: bool = True) -> bool:
    """Return True when extracted distinctions differ — different teams.

    Colors, directions, programs, team numbers, location codes, squad words,
    and age tokens must all match. State codes only differentiate if BOTH
    sides carry them.

    ``require_age_token_match`` controls how strict the age-token check is.
    Default ``True`` (masters dedup): age tokens must match exactly. Pass
    ``False`` when the caller has already filtered candidates by age via a
    DB query — then we only treat differing age tokens as a mismatch when
    both names actually carry one (mirrors the state-code rule). Without
    this relaxation, queue rows like "CCV Stars 12 Girls North Orange"
    (no AGE_PATTERN match) get wrongly skipped against valid masters that
    carry "2012" in their names.
    """
    da = extract_distinctions(name_a, club_name=club_name)
    db = extract_distinctions(name_b, club_name=club_name)

    if da["colors"] != db["colors"]:
        return True
    if da["directions"] != db["directions"]:
        return True
    if da["programs"] != db["programs"]:
        return True
    if da["team_number"] != db["team_number"]:
        return True
    if da["location_codes"] != db["location_codes"]:
        return True
    if da["squad_words"] != db["squad_words"]:
        return True
    if require_age_token_match:
        if da["age_tokens"] != db["age_tokens"]:
            return True
    else:
        if da["age_tokens"] and db["age_tokens"] and da["age_tokens"] != db["age_tokens"]:
            return True
    if da["secondary_nums"] != db["secondary_nums"]:
        return True
    if da["state_codes"] and db["state_codes"] and da["state_codes"] != db["state_codes"]:
        return True

    return False
