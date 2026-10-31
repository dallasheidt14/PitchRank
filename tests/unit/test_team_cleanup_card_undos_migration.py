"""Pin the parts of the team_cleanup_card_undos migration that fail silently.

ci.yml applies no migrations, so these text assertions stand in for executing the SQL. Without the one-
pending index two presses of Undo queue two undos of one card; without the handled check a request can
read done with no time, or pending with one; without RLS with its policies and the REVOKE,
pg_default_acl leaves anon free to file or erase undo requests, and RLS alone still leaves TRUNCATE.

Definitions resolve by name across every migration, newest wins.
"""

import os
import re
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from scripts.team_cleanup.advance import CARD_UNDOS_TABLE  # noqa: E402
from tests.unit.test_team_cleanup_cards_migration import _flat, _newest_statement, _tree  # noqa: E402

TABLE = "team_cleanup_card_undos"
NAMED = rf'(?:"?public"?\.)?"?{TABLE}"?\b'


def _create_table() -> str:
    return _flat(_newest_statement(rf"(?is)create\s+table\s+(?:if\s+not\s+exists\s+)?{NAMED}\s*\("))


def test_the_loop_reads_the_table_the_migration_creates():
    assert CARD_UNDOS_TABLE == TABLE


def test_a_request_s_columns_carry_the_not_nulls_and_references_its_checks_rely_on():
    table = _create_table()

    for column in (
        "id UUID PRIMARY KEY DEFAULT gen_random_uuid(),",
        "run_id TEXT NOT NULL REFERENCES team_cleanup_runs (run_id),",
        "card_id TEXT NOT NULL REFERENCES team_cleanup_cards (card_id),",
        "decline BOOLEAN NOT NULL DEFAULT true,",
        "requested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),",
        "requested_by_user_id UUID REFERENCES auth.users (id) ON DELETE SET NULL,",
        "status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'done', 'failed')),",
        "result TEXT CHECK (char_length(result) <= 2000),",
    ):
        assert column in table, f"the card undos table no longer declares {column}"


def test_a_request_is_handled_exactly_when_it_is_no_longer_pending():
    assert (
        "CONSTRAINT team_cleanup_card_undos_handled_is_whole CHECK ((status = 'pending') = (handled_at IS NULL))"
    ) in _create_table()


def test_a_card_has_at_most_one_pending_request():
    index = _flat(
        _newest_statement(r"(?is)create\s+unique\s+index\s+(?:if\s+not\s+exists\s+)?uq_team_cleanup_card_undos")
    )

    assert f"ON {TABLE} (card_id) WHERE status = 'pending';" in index


def test_row_level_security_is_enabled():
    assert re.search(rf"(?is)alter\s+table\s+(?:only\s+)?{NAMED}\s+enable\s+row\s+level\s+security", _tree())


def test_the_deny_all_policy_covers_anon_and_authenticated():
    deny = _flat(_newest_statement(rf'(?is)create\s+policy\s+"{TABLE}_deny_all"'))

    assert f"ON {TABLE} FOR ALL TO anon, authenticated USING (false) WITH CHECK (false)" in deny


def test_the_service_role_policy_is_on_the_requests():
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
        ("DROP INDEX", r"(?is)drop\s+index\s+[^;]*uq_team_cleanup_card_undos", 0),
    ):
        hits = re.findall(pattern, tree)
        assert len(hits) <= allowed, f"{verb} on {TABLE} appeared in a migration: {hits}"
