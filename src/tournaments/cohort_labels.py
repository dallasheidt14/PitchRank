"""Read a division label or roster heading into the cohorts and genders it names.

Pure parsing: no HTTP, no Supabase, no Streamlit. One grammar decides what
``B2013/2014``, ``U13 B`` or ``Boys 2012`` means everywhere in intake.

Two tiers, U-ages first:

1. U-ages (``U14``, ``14U``, ``BU14``, ``U14M``, ``Under 15``, ``U 15``).
2. Birth years: single years (``B2013``, ``14B``, ``Boys 2012``) and two-year
   bands, a band counting as its younger year (``2013/2014`` and ``13/14`` are
   U13). Every year in the label counts, so two that disagree name two cohorts.

U-ages win when a label carries both, because ``U12G (AUG 1, 2014 - JULY 31,
2015)`` names its own cohort and the years are the band it spans. A label naming
two cohorts or two genders reports both; nothing here guesses.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from src.scrapers._age_normalization import normalize_age
from src.utils import team_utils

__all__ = ["LabelReading", "ascii_dashes", "normalize_label", "read_label"]

# One grammar reads every age expression: a run is an age with an optional
# gender letter at either end (`BU12`, `U-12`, `U12B`, `U14M`, `12U`, `12UB`,
# `B2015`), continued by `/` or `-` into further numbers (`U15/16`, `17/19U`,
# `B2017/18`). A single grammar is what keeps `17/19U` from reading as one
# cohort: an age the pattern does not reach is an age the multi-cohort check
# cannot count.
AGE_RUN = re.compile(
    r"\b(?P<lead>[BGMF])?"
    r"(?P<body>(?:U-?)?[0-9]{1,4}(?:\s*[/\-‐-―]\s*(?:U-?)?[0-9]{1,4})*)"
    r"(?P<tail_u>U)?(?P<tail>[BGMF])?\b",
    re.IGNORECASE,
)
RUN_NUMBER = re.compile(r"[0-9]{1,4}")
EARLIEST_BIRTH_YEAR = 1990
# Two-digit birth years are read as 2000s; every board sits well inside that.
COMPACT_YEAR_CENTURY = 2000
# A two-year pair younger than this names a season (`2025-2026`), not a band.
_YOUNGEST_BAND_AGE = 7

# A second gender letter joined to a glued one (`U11B/G`).
_JOINED_LETTER = re.compile(r"\s*/\s*([BGMF])\b(?![0-9])", re.IGNORECASE)
# A gender letter standing on its own right after a U-age (`U13 B D1`, `U11 B/G`).
# A letter glued to a digit (`B2`, a bracket) is not one.
_STANDING_LETTER = re.compile(r"\s+([BGMF])(?:\s*/\s*([BGMF]))?\b(?![0-9])", re.IGNORECASE)
_SPACED_U = re.compile(r"\b(?:under|u)\s+(?=[0-9])", re.IGNORECASE)
# The word itself is ASCII: under IGNORECASE a Unicode fold (`ſ`, `ı`, `İ`) would
# match a word the lookup table below has no key for. The boundaries stay
# Unicode-aware, so `Menü` is not `Men`.
_GENDER_WORD = re.compile(
    r"\b(?a:(males?|females?|boys?|girls?|men|women|coed|co-ed|mixed))\b", re.IGNORECASE
)
_GENDER_WORDS = {
    "male": ("Male",),
    "males": ("Male",),
    "boy": ("Male",),
    "boys": ("Male",),
    "men": ("Male",),
    "female": ("Female",),
    "females": ("Female",),
    "girl": ("Female",),
    "girls": ("Female",),
    "women": ("Female",),
    "coed": ("Male", "Female"),
    "co-ed": ("Male", "Female"),
    "mixed": ("Male", "Female"),
}
_GENDER_LETTERS = {"B": "Male", "M": "Male", "G": "Female", "F": "Female"}
_WORD = re.compile(r"[^\W_]+")


@dataclass(frozen=True)
class LabelReading:
    """Everything a label names, before any caller decides what to trust.

    ``cohorts`` holds off-board ages as their own literal (``u9``, ``u20``) and a
    birth year outside U7-U19 as ``by<year>``, so a caller can tell "an age we
    do not board" from "a label nobody can read".
    """

    cohorts: frozenset[str]
    genders: frozenset[str]
    has_u_age: bool
    birth_years: frozenset[int]
    """Years the label names, a band counting as its younger year."""
    gender_is_firm: bool
    """True when a glued letter or a word names the gender, or two standing
    letters do (`U11 B/G`); a lone standing letter (`U12 B`) may be a bracket."""
    gender_from_word: bool
    """True when a word (``Boys``, ``Coed``) names the gender, not only a letter."""
    leftover: tuple[str, ...]
    """Words the reading did not consume, in order."""

    @property
    def cohort(self) -> str:
        """The one cohort named, or empty when the label names none or several."""
        return next(iter(self.cohorts)) if len(self.cohorts) == 1 else ""

    @property
    def gender(self) -> str:
        """The one gender named, or empty when the label names none or both."""
        return next(iter(self.genders)) if len(self.genders) == 1 else ""


@dataclass(frozen=True)
class _Run:
    kind: str
    cohorts: frozenset[str]
    genders: frozenset[str]
    years: frozenset[int]
    span: tuple[int, int]
    standing_genders: frozenset[str] = frozenset()
    standing_span: tuple[int, int] | None = None


def normalize_label(label: str) -> str:
    """Compose accents, fold dashes and join a spaced `U 15` / `Under 15`."""
    return _SPACED_U.sub("U", ascii_dashes(unicodedata.normalize("NFC", str(label or ""))))


def read_label(label: str, *, season: int | None = None) -> LabelReading:
    """Read ``label`` against ``season`` (the current soccer season by default)."""
    season = team_utils._soccer_season_year() if season is None else season
    text = normalize_label(label)
    runs = [_read_run(match, text, season) for match in AGE_RUN.finditer(text)]
    counted = [run for run in runs if run.kind != "none"]
    u_age_cohorts = {cohort for run in counted if run.kind == "u_age" for cohort in run.cohorts}
    year_cohorts = {cohort for run in counted if run.kind == "birth_year" for cohort in run.cohorts}

    consumed = [False] * len(text)

    def consume(start: int, end: int) -> None:
        consumed[start:end] = [True] * (end - start)

    firm: set[str] = {gender for run in counted for gender in run.genders}
    for run in counted:
        consume(*run.span)
    worded = False
    for word in _GENDER_WORD.finditer(text):
        firm |= set(_GENDER_WORDS[word.group(1).lower()])
        worded = True
        consume(*word.span())
    standing = {gender for run in counted for gender in run.standing_genders}
    if not firm:
        # A standing letter is the gender only when nothing firmer named one;
        # otherwise it is left as a word, since it may be a bracket.
        for run in counted:
            if run.standing_span:
                consume(*run.standing_span)

    return LabelReading(
        cohorts=frozenset(u_age_cohorts or year_cohorts),
        genders=frozenset(firm or standing),
        has_u_age=bool(u_age_cohorts),
        birth_years=frozenset(year for run in counted for year in run.years),
        gender_is_firm=bool(firm) or len(standing) > 1,
        gender_from_word=worded,
        leftover=tuple(word.group() for word in _WORD.finditer(text) if not consumed[word.start()]),
    )


def _read_run(match: re.Match, text: str, season: int) -> _Run:
    """One age expression's cohorts, and its gender letters when it is an age at all."""
    body = match.group("body")
    digits = RUN_NUMBER.findall(body)
    numbers = [int(number) for number in digits]
    letters = {letter.upper() for letter in (match.group("lead"), match.group("tail")) if letter}
    has_u = bool(match.group("tail_u")) or "u" in body.lower()
    span = match.span()
    if letters:
        joined = _JOINED_LETTER.match(text, match.end())
        if joined:
            letters.add(joined.group(1).upper())
            span = (span[0], joined.end())

    if numbers and numbers[0] >= EARLIEST_BIRTH_YEAR:
        century = (numbers[0] // 100) * 100
        years = [number if number >= EARLIEST_BIRTH_YEAR else century + number for number in numbers]
        return _year_run(match.group(0), years, letters, season, span)
    compact = digits and all(len(number) == 2 for number in digits)
    band = len(numbers) == 2 and abs(numbers[0] - numbers[1]) == 1
    if not has_u and compact and (letters or band):
        # `14B` names a birth year, not an age: 2014 is U13, not U14. The `U` is
        # the only thing separating the two forms, and two digits keep a bracket
        # (`B2`) from reading as one. A single year needs a gender letter, which
        # keeps `Flight 14` from becoming a cohort; a band (`13/14`) does not.
        years = [COMPACT_YEAR_CENTURY + number for number in numbers]
        return _year_run(match.group(0), years, letters, season, span)
    if has_u:
        standing = _STANDING_LETTER.match(text, span[1])
        standing_letters = {letter.upper() for letter in standing.groups() if letter} if standing else set()
        # `normalize_age` owns the U18->U19 merge; an age outside its u6-u19 range
        # keeps the label's own literal (`u20`, `u5`) instead of collapsing to nothing.
        return _Run(
            "u_age",
            frozenset(normalize_age(number) or f"u{number}" for number in numbers),
            _genders(letters),
            frozenset(),
            span,
            _genders(standing_letters),
            standing.span() if standing else None,
        )
    return _Run("none", frozenset(), frozenset(), frozenset(), span)


def _year_run(run_text: str, years: list[int], letters: set[str], season: int, span: tuple[int, int]) -> _Run:
    """A two-year band is one cohort by its younger year; other years map one by one."""
    if len(years) == 2 and abs(years[0] - years[1]) == 1:
        younger = team_utils.extract_band_birth_year(run_text, current_year=season)
        if younger == max(years):
            cohort = team_utils.calculate_age_group_from_band(younger, current_year=season)
            return _Run(
                "birth_year", frozenset({(cohort or f"by{younger}").lower()}), _genders(letters),
                frozenset({younger}), span,
            )
        if season - max(years) + 1 < _YOUNGEST_BAND_AGE:
            return _Run("none", frozenset(), frozenset(), frozenset(), span)
    cohorts = frozenset(
        (team_utils.calculate_age_group_from_birth_year(year, current_year=season) or f"by{year}").lower()
        for year in years
    )
    return _Run("birth_year", cohorts, _genders(letters), frozenset(years), span)


def _genders(letters: set[str]) -> frozenset[str]:
    return frozenset(_GENDER_LETTERS[letter] for letter in letters)


def ascii_dashes(label: str) -> str:
    """Fold every dash to ASCII so one grammar reads them all.

    A dash the pattern does not reach (the minus sign in `U13−14`) leaves the
    second age unattached, and an unattached age is invisible to the multi-cohort
    check.
    """
    return "".join("-" if _is_dash(ch) else ch for ch in str(label or ""))


def _is_dash(ch: str) -> bool:
    """Does the character's Unicode name say HYPHEN, DASH or MINUS?

    Category ``Pd`` misses three a GotSport label can carry: MINUS SIGN (``Sm``),
    SOFT HYPHEN (``Cf``) and HYPHEN BULLET (``Po``). The character's name decides
    instead.
    """
    name = unicodedata.name(ch, "")
    return any(word in name for word in ("HYPHEN", "DASH", "MINUS"))
