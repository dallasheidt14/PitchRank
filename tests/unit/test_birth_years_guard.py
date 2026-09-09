"""A birth year separates cohorts; an age label does not.

U19 holds 2008 and 2009 at once, so no age-token comparison at any strictness
separates "G09" from "2008". Every fuzzy team matcher in this repo scores names
by similarity and compares colors, directions, programs, squad numbers and coach
names -- none of them compared birth year, which is why "Stateline SC-2011G
Bears" was linked to "Stateline SC-2013G Bears" at 0.957.

This pins the two things that make the guard safe to run unattended:

  1. The extractor's semantics, notation by notation. It reads the RAW name --
     normalize_team_name's "<2 digits> boys|girls" rule rewrites "08/07 Girls" to
     "08/2007", turning a band label into a single wrong year.

  2. The false-refusal budget, measured against merges that were kept. Subset
     semantics refuse 6 of ~2,900 human-approved merges; requiring equality
     refuses 55. The budget test is what stops a future re-tightening to equality.
"""

import unicodedata
from pathlib import Path

import pytest

from src.utils.team_name_utils import birth_years, birth_years_conflict

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    "name,expected",
    [
        # Plain and gender-affixed, both orders. "14B" is the house GotSport form.
        ("2011", {2011}),
        ("B2011", {2011}),
        ("2011B", {2011}),
        ("G2011", {2011}),
        ("11G", {2011}),
        ("14B", {2014}),
        ("Surf SC Elite '09", {2009}),
        # Band labels carry BOTH years -- the season runs Aug-Jul, so one band
        # straddles two calendar birth years and either end may name the team.
        ("B08/07", {2007, 2008}),
        ("2013/14", {2013, 2014}),
        ("B2016/17", {2016, 2017}),
        ("Team 08/07 Girls", {2007, 2008}),
        # An adjacent Boys/Girls marks a two-digit number as a year, either order.
        ("Club 12 Boys", {2012}),
        ("Club Boys 12", {2012}),
        ("NB AJAX 08 Girls White", {2008}),
        ("Victory SC 07/08/09 Boys", {2007, 2008, 2009}),
        # ...but only when the gender word stands alone. Without real word
        # boundaries the branch reads a year out of any word ending or starting
        # in "boys"/"girls".
        ("Cowboys 12 Red", set()),
        ("Club 12 Boysenberry", set()),
        # U-ages are cohort labels, not birth years: what they mean depends on the
        # season that wrote them, so they must contribute nothing.
        ("GU18/19", set()),
        ("U14", set()),
        ("14U", set()),
        # A band label is one token however it is spelled, so no half of it may
        # survive to be read as a year by a later pass.
        ("PDA-SCP U13/14 Girls", set()),
        ("Green Army U17/18/19B", set()),
        ("LMSC U16-19B Navy", set()),
        ("Century United Under 10 Boys Gold", set()),
        ("Erie FC Under 14/15 Girls", set()),
        ("Radnor Soccer Club U 17 Girls Black", set()),
        ("GSA U13/14B Grey", set()),
        # The spelled-out and spaced forms are the two that can swallow an
        # ordinary word: "Thunder 12" ends in "under", and a club initial ending
        # in U ("MK MU") reads as a U-age unless the token must start a word.
        ("Thunder 12 Boys", {2012}),
        ("MK MU 12 Boys", {2012}),
        # A birth-year band standing beside a U-age is still a birth-year band.
        ("Seacoast United - U14G -12/13 Nal", {2012, 2013}),
        ("MK MU U15/16G Blue 2010/11", {2010, 2011}),
        # The label must stop at the first thing that is not part of it. Run on
        # into a four-digit year and the band swallows "/20", leaving "11".
        ("McLean Youth Soccer U15/2011 Green", {2011}),
        ("GAVILANES FC U2012", {2012}),
        # Single-digit ages and an affix without a band, both of which a band
        # case cannot exercise on its own.
        ("Milwaukee U9/10 Boys", set()),
        ("Vc Fusion U-12G", set()),
        ("GU13 Girls Academy", set()),
        # A game format is a squad size: "11v11" is not a 2011 team. The spaced
        # spelling only survives if the format goes before the U-age does —
        # strip the U-age first and "U13/11" leaves a "v 11" nothing recognises.
        ("U19 OSC Girls 11v11", set()),
        ("Club U13/11 v 11 Boys", set()),
        ("Boys 11s Elite", {2011}),
        # A bare two-digit number is a squad number until something marks it a year.
        ("Arsenal 11 B", set()),
        ("6/7 Grinch Unit", set()),
    ],
)
def test_birth_years_notation(name, expected):
    assert birth_years(name) == expected


@pytest.mark.parametrize(
    "name_a,name_b,conflict",
    [
        # The links this guard exists to refuse.
        ("Stateline SC-2011G Bears", "Stateline SC-2013G Bears", True),
        ("Surf SC Elite '09", "Surf SC Elite '08", True),
        ("EPIC SC 2008 Dash", "EPIC SC 2009 Dash", True),
        # Subset, not equality: the same team written from one end of its band.
        ("Dallas Texans ECNL B08/07", "Dallas Texans ECNL 2008", False),
        ("2013/14 Lobos Rush Gold", "2013 Lobos Rush Gold", False),
        # Bands that merely OVERLAP are still distinct teams sharing one year.
        ("club 08/07", "club 06/07", True),
        # A club whose own name carries a year supplies a shared year for free;
        # subset still separates these, which is why overlap is not the test.
        ("Union 2010 FC 2009", "Union 2010 FC 2008", True),
        # Genuine formatting duplicates must survive.
        ("Rangers FC - 2017 White", "Rangers FC 2017 White", False),
        # Silent where it cannot see: no year stated on one side means no verdict.
        ("Rush U18", "Rush U19", False),
        ("FC Dallas Red", "FC Dallas 2009 Red", False),
    ],
)
def test_birth_years_conflict(name_a, name_b, conflict):
    assert birth_years_conflict(name_a, name_b) is conflict
    assert birth_years_conflict(name_b, name_a) is conflict


def test_conflict_is_silent_without_years_on_both_sides():
    """No year on either side is not evidence of agreement -- it is no evidence.

    26% of pending queue rows state no birth year. The guard must return False for
    them so it never becomes the only thing standing between those rows and a
    match; a separate check has to cover that population.
    """
    assert birth_years_conflict("Rangers FC White", "Rangers FC Blue") is False
    assert birth_years_conflict("", "FC Dallas 2009") is False
    assert birth_years_conflict(None, None) is False


def test_equality_semantics_would_break_the_band_convention():
    """Pins WHY this is subset rather than equality.

    Equality refuses 55 of 2,929 kept human merges against 6 for subset, because
    a band label and a single-year label for the same team are not equal sets.
    """
    band, single = birth_years("Dallas Texans ECNL B08/07"), birth_years("Dallas Texans ECNL 2008")
    assert band != single, "the two notations are genuinely different sets"
    assert single < band, "and the single year is a subset, which is what makes them compatible"
    assert birth_years_conflict("Dallas Texans ECNL B08/07", "Dallas Texans ECNL 2008") is False


def test_source_holds_no_mangled_escape():
    """A `\\b` that lost its backslash becomes 0x08 and silently matches nothing.

    _GENDER_WORD shipped that way and never matched a real name; the branch read
    as live code and as a passing import.

    Scanning source bytes rather than compiled patterns is deliberate.
    Reflection reaches only names bound directly to a `re.Pattern`, so it misses
    patterns held as strings in a list, patterns nested inside a container, every
    inline literal in a function body, and comments -- and one of the bytes this
    bug left behind was in a comment.

    The scope is read out of the lint job's own argument list rather than
    restated here, because the same mangled comment had been copied from
    `team_name_utils` into `scripts/`, and a guard naming one module cannot fail
    for the copy. `frontend/lib` is added on top: it is not Python, so the lint
    job never names it, and it carried one of these bytes too.

    Tab, newline and carriage return are excluded as ordinary source whitespace.
    Every escape a lost backslash produces (`\\a \\b \\f \\v \\0`) is a control
    character outside that set, so the defect class is still fully covered.
    """
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    lint = next(line for line in workflow.splitlines() if "ruff check" in line)
    targets = [ROOT / arg for arg in lint.split("ruff check", 1)[1].split() if not arg.startswith("-")]
    assert len(targets) >= 5, f"read only {targets} out of the lint job -- its command changed"

    targets.append(ROOT / "frontend" / "lib")

    def walk(target):
        if target.is_file():
            return [target]
        return [path for ext in ("py", "ts", "tsx") for path in target.rglob(f"*.{ext}")]

    sources = sorted(path for target in targets for path in walk(target))
    assert len(sources) > 100, f"only {len(sources)} sources found -- the layout moved"

    offenders = [
        f"{path.relative_to(ROOT).as_posix()}:{text.count(chr(10), 0, i) + 1}: {char!r}"
        for path in sources
        for text in [path.read_text(encoding="utf-8", errors="replace")]
        for i, char in enumerate(text)
        if unicodedata.category(char) == "Cc" and char not in "\t\n\r"
    ]
    assert not offenders
