"""Pin the parts of the team_cleanup_spot_checks migration that fail silently.

ci.yml applies no migrations, so these text assertions stand in for executing the SQL. Without the two unique
indexes a run's sample can be picked twice or hold one merge twice; without the judged check a verdict can
stand with no time; without RLS with its policies and the REVOKE, pg_default_acl leaves anon free to rewrite
the verdicts, and RLS alone still leaves TRUNCATE.

Definitions resolve by name across every migration, newest wins.
"""

import os
import re
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from scripts.team_cleanup.spot_check import SAMPLE_SIZE, SPOT_CHECKS_TABLE, SPOT_VERDICTS  # noqa: E402
from tests.unit.test_team_cleanup_cards_migration import _flat, _newest_statement, _tree  # noqa: E402

TABLE = "team_cleanup_spot_checks"
NAMED = rf'(?:"?public"?\.)?"?{TABLE}"?\b'


def _create_table() -> str:
    return _flat(_newest_statement(rf"(?is)create\s+table\s+(?:if\s+not\s+exists\s+)?{NAMED}\s*\("))


def test_the_loop_writes_the_table_the_migration_creates():
    assert SPOT_CHECKS_TABLE == TABLE


def test_a_spot_check_s_columns_carry_the_not_nulls_and_references_its_readers_rely_on():
    table = _create_table()

    for column in (
        "id UUID PRIMARY KEY DEFAULT gen_random_uuid(),",
        "run_id TEXT NOT NULL REFERENCES team_cleanup_runs (run_id),",
        "position SMALLINT NOT NULL CHECK (position BETWEEN 1 AND 10),",
        "card_id TEXT NOT NULL REFERENCES team_cleanup_cards (card_id),",
        "picked_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),",
        "verdict TEXT CHECK (verdict IN ('right', 'wrong')),",
        "note TEXT CHECK (char_length(note) <= 2000),",
        "judged_by_user_id UUID REFERENCES auth.users (id) ON DELETE SET NULL,",
    ):
        assert column in table, f"the spot-checks table no longer declares {column}"


def test_the_loop_s_sample_size_and_verdicts_are_the_ones_the_table_takes():
    assert SAMPLE_SIZE == 10
    assert SPOT_VERDICTS == ("right", "wrong")


def test_a_verdict_stands_exactly_when_it_has_a_time():
    assert (
        "CONSTRAINT team_cleanup_spot_checks_judged_is_whole CHECK ((verdict IS NULL) = (judged_at IS NULL))"
    ) in _create_table()


def test_a_run_s_sample_holds_each_position_and_each_merge_once():
    for name, columns in (("position", "(run_id, position)"), ("card", "(run_id, card_id)")):
        index = _flat(
            _newest_statement(
                rf"(?is)create\s+unique\s+index\s+(?:if\s+not\s+exists\s+)?uq_team_cleanup_spot_checks_{name}\b"
            )
        )

        assert f"ON {TABLE} {columns};" in index


def test_row_level_security_is_enabled():
    assert re.search(rf"(?is)alter\s+table\s+(?:only\s+)?{NAMED}\s+enable\s+row\s+level\s+security", _tree())


def test_the_deny_all_policy_covers_anon_and_authenticated():
    deny = _flat(_newest_statement(rf'(?is)create\s+policy\s+"{TABLE}_deny_all"'))

    assert f"ON {TABLE} FOR ALL TO anon, authenticated USING (false) WITH CHECK (false)" in deny


def test_the_service_role_policy_is_on_the_spot_checks():
    allow = _flat(_newest_statement(rf'(?is)create\s+policy\s+"{TABLE}_service_role_all"'))

    assert f"ON {TABLE} FOR ALL TO service_role USING (true) WITH CHECK (true)" in allow


def test_the_default_table_grant_is_revoked():
    assert f"REVOKE ALL ON public.{TABLE} FROM anon, authenticated;" in _flat(_tree())


def test_nothing_grants_the_table_to_a_browser_role():
    named = re.findall(rf"(?is)grant\s+[^;]*\bon\b[^;]*\b{TABLE}\b[^;]*;", _tree())
    schema_wide = re.findall(r"(?is)grant\s+[^;]*\bon\s+all\s+tables\s+in\s+schema\s+public[^;]*;", _tree())
    offending = [g for g in named + schema_wide if re.search(r"(?i)\bto\b[^;]*\b(anon|authenticated|public)\b", g)]

    assert not offending, f"{TABLE} is reachable by a browser role: {offending}"


def test_nothing_later_reshapes_the_table_behind_these_guards():
    """These guards read the original definition; any ALTER beyond enabling RLS, DROP or re-CREATE fails here
    first."""
    tree = _tree()

    for verb, pattern, allowed in (
        ("CREATE TABLE", rf"(?is)create\s+table\s+(?:if\s+not\s+exists\s+)?{NAMED}", 1),
        ("DROP TABLE", rf"(?is)drop\s+table\s+(?:if\s+exists\s+)?{NAMED}", 0),
        ("ALTER TABLE", rf"(?is)alter\s+table\s+(?:if\s+exists\s+)?(?:only\s+)?{NAMED}", 1),
        ("DROP POLICY", rf'(?is)drop\s+policy\s+[^;]*"{TABLE}_', 2),
        ("DROP INDEX", r"(?is)drop\s+index\s+[^;]*uq_team_cleanup_spot_checks", 0),
    ):
        hits = re.findall(pattern, tree)
        assert len(hits) <= allowed, f"{verb} on {TABLE} appeared in a migration: {hits}"
