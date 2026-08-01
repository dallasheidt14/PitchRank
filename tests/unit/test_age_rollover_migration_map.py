"""Pin the age-rollover migration's cohort map without a database.

The 12-branch CASE map is written out four times in the migration -- twice in the
live UPDATEs and twice inside the commented verification block. That verification
therefore compares the rolled data against a copy of the statement that produced
it, so a typo duplicated across all four reads as a clean run over permanently
mislabelled teams. These tests are the independent check the SQL cannot be.
"""

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT))

from find_queue_matches import _age_group_from_birth_year  # noqa: E402

MIGRATION = PROJECT_ROOT / "supabase" / "migrations" / "20260801000000_age_group_rollover_2026_27.sql"

# The season the roll moves teams into; a u10 in 2025-26 is a u11 in 2026-27.
ROLLOVER_SEASON_YEAR = 2026


def _sql():
    return MIGRATION.read_text(encoding="utf-8")


def _case_bodies(sql):
    """Return each CASE map, ELSE arm included, as a whitespace-normalized string.

    The capture runs to END rather than stopping at ELSE: an ``ELSE NULL`` in one
    copy would blank every unmapped label, and a comparison that ends before the
    ELSE cannot see that.
    """
    bodies = re.findall(r"WHEN 'u7'.*?END", sql, re.DOTALL)
    return [re.sub(r"\s+", " ", body).replace("b.age_group", "age_group").strip() for body in bodies]


def _executable_updates(sql):
    """Return (table, column, CASE operand) for each UPDATE outside a block comment.

    The map also appears inside the commented Step 5 verification, so a bare
    regex cannot tell a live statement from documentation — comment out the real
    UPDATE and every text assertion still passes.
    """
    live = re.sub(r"/\*.*?\*/", "", sql, flags=re.DOTALL)
    live = "\n".join(line for line in live.splitlines() if not line.lstrip().startswith("--"))
    # The CASE operand is captured too: `CASE gender` would send every selected
    # row through ELSE, making the whole migration a silent no-op while the map
    # itself still reads correctly.
    return re.findall(r"UPDATE\s+(?:public\.)?(\w+)\s+SET\s+(\w+)\s*=\s*CASE\s+(\w+)", live)


def _pairs(sql):
    return re.findall(r"WHEN '(u\d+)'\s+THEN\s+'(u\d+)'", sql)


class TestExecutableUpdates:
    """The map must be wired into live statements, not only into comments."""

    def test_both_tables_are_rolled_by_an_executable_update(self):
        updates = _executable_updates(_sql())
        assert updates == [
            ("teams", "age_group", "age_group"),
            ("rankings_full", "age_group", "age_group"),
        ], f"expected live UPDATEs setting age_group from CASE age_group on both tables, got {updates}"

    def test_source_set_is_exactly_u7_through_u18(self):
        """Pinned to a literal, not derived from the file.

        Every other structural test compares the file to itself, so a uniform
        edit — dropping u12 from all four CASE copies and both WHERE IN lists —
        satisfies all of them while silently leaving a cohort behind.
        """
        assert {source for source, _ in _pairs(_sql())} == {f"u{n}" for n in range(7, 19)}


class TestCaseMapCopies:
    def test_all_four_copies_are_identical(self):
        bodies = _case_bodies(_sql())
        assert len(bodies) == 4, f"expected 4 copies of the CASE map, found {len(bodies)}"
        assert len(set(bodies)) == 1, "the CASE map copies have drifted apart"

    def test_where_in_list_matches_the_case_sources(self):
        """Anchored to ``END WHERE`` so it reads only the two UPDATE filters -- the
        verification block also has an ``IN`` list, a deliberate subset.
        """
        sql = _sql()
        sources = {source for source, _ in _pairs(sql)}
        clauses = re.findall(r"END\s*WHERE age_group IN \(([^)]*)\)", sql)
        assert len(clauses) == 2, f"expected 2 UPDATE filters, found {len(clauses)}"
        for clause in clauses:
            assert set(re.findall(r"'(u\d+)'", clause)) == sources


class TestCaseMapContent:
    def test_u17_and_u18_both_merge_into_u19(self):
        mapping = dict(_pairs(_sql()))
        assert mapping["u17"] == "u19"
        assert mapping["u18"] == "u19"

    def test_u19_is_never_a_source(self):
        # u19 stays u19, so it must not appear on the left of the map at all.
        assert "u19" not in {source for source, _ in _pairs(_sql())}

    def test_targets_agree_with_the_python_derivation(self):
        """Cross-check the SQL against the Python fold, which is independently tested.

        A team labelled uN in the 2025-26 season was born (2025 - N + 1); running
        that birth year through the 2026-27 season must produce the SQL's target.
        """
        for source, target in _pairs(_sql()):
            source_age = int(source.removeprefix("u"))
            birth_year = 2025 - source_age + 1
            assert _age_group_from_birth_year(birth_year, ROLLOVER_SEASON_YEAR) == target, (
                f"SQL maps {source}->{target}, but birth year {birth_year} derives "
                f"{_age_group_from_birth_year(birth_year, ROLLOVER_SEASON_YEAR)}"
            )
