"""Pin the parts of the team_cleanup_decisions migration that fail silently.

ci.yml applies no migrations, so these text assertions stand in for executing the SQL. Without the
index two contradictory active decisions on one pair can both stand, and without its predicate a
superseded decision blocks its successor; without RLS, the policies or the REVOKE, pg_default_acl
leaves anon free to erase the owner's decisions.

Definitions resolve by name across every migration, newest wins.
"""

import re
from pathlib import Path

MIGRATIONS = Path(__file__).resolve().parents[2] / "supabase" / "migrations"

TABLE = "team_cleanup_decisions"


def _executable(text: str) -> str:
    """Drop -- comments, so prose in a header can never satisfy an assertion about the SQL."""
    return re.sub(r"--[^\n]*", "", text)


def _flat(text: str) -> str:
    return re.sub(r"\s+", " ", _executable(text)).strip()


def _migrations() -> list[Path]:
    """Every migration, oldest first: filenames are timestamp-prefixed."""
    return sorted(MIGRATIONS.glob("*.sql"))


def _tree() -> str:
    return "\n".join(_executable(p.read_text(encoding="utf-8")) for p in _migrations())


def _newest_statement(pattern: str) -> str:
    """The last statement matching `pattern`, in migration order."""
    found = None
    for path in _migrations():
        sql = _executable(path.read_text(encoding="utf-8"))
        for match in re.finditer(pattern, sql):
            found = sql[match.start() : sql.index(";", match.end()) + 1]
    assert found is not None, f"no migration contains {pattern}"
    return re.sub(r"\s+", " ", found).strip()


def _create_table() -> str:
    return _flat(_newest_statement(rf"(?is)create\s+table\s+(?:if\s+not\s+exists\s+)?(?:public\.)?{TABLE}\s*\("))


def test_a_decision_is_one_of_the_tables_four():
    assert "decision TEXT NOT NULL CHECK (decision IN ('keep_separate', 'dont_apply', 'apply', 'unsure'))" in (
        _create_table()
    )


def test_a_merge_decision_names_both_teams():
    assert "CHECK (stage <> 'merges' OR other_team_id IS NOT NULL)" in _create_table()


def test_a_pair_is_two_different_teams():
    assert "CHECK (other_team_id IS DISTINCT FROM team_id_master)" in _create_table()


def test_a_merge_decision_s_key_is_its_sorted_pair():
    """The one-active-decision index compares keys as text, so a pair spelled in the other order
    would hold a second active decision."""
    assert (
        "CHECK ( stage <> 'merges' OR subject_key = LEAST(team_id_master::text COLLATE \"C\", "
        "other_team_id::text COLLATE \"C\") || '|' || GREATEST(team_id_master::text COLLATE \"C\", "
        "other_team_id::text COLLATE \"C\") )"
    ) in _create_table()


def test_keep_separate_is_only_ever_a_merge_decision():
    """The scanners read keep_separate rows without filtering on stage, relying on this."""
    assert "CHECK (decision <> 'keep_separate' OR stage = 'merges')" in _create_table()


def test_a_decision_can_be_superseded_rather_than_deleted():
    assert "superseded_at TIMESTAMPTZ," in _create_table()


def test_only_one_decision_per_subject_is_active():
    index = _flat(
        _newest_statement(r"(?is)create\s+unique\s+index\s+(?:if\s+not\s+exists\s+)?uq_team_cleanup_decisions_active")
    )

    assert f"ON {TABLE} (stage, subject_key) WHERE superseded_at IS NULL;" in index, (
        f"without the predicate a superseded decision blocks its successor; without the index two "
        f"active decisions on one pair can disagree: {index}"
    )


def test_row_level_security_is_enabled():
    assert re.search(
        rf"(?is)alter\s+table\s+(?:public\.)?{TABLE}\s+enable\s+row\s+level\s+security", _tree()
    ), f"{TABLE} ships without RLS, which leaves both policies inert"


def test_the_deny_all_policy_covers_anon_and_authenticated():
    deny = _flat(_newest_statement(rf'(?is)create\s+policy\s+"{TABLE}_deny_all"'))

    assert "TO anon, authenticated USING (false) WITH CHECK (false)" in deny, (
        f"the deny-all policy no longer refuses both browser roles: {deny}"
    )


def test_the_service_role_policy_exists():
    allow = _flat(_newest_statement(rf'(?is)create\s+policy\s+"{TABLE}_service_role_all"'))

    assert "TO service_role USING (true) WITH CHECK (true)" in allow, (
        f"the service-role policy no longer grants the scripts access: {allow}"
    )


def test_the_default_table_grant_is_revoked():
    """RLS governs SELECT/INSERT/UPDATE/DELETE and not TRUNCATE, so the deny-all policy
    leaves the TRUNCATE in pg_default_acl's grant to anon untouched."""
    assert f"REVOKE ALL ON public.{TABLE} FROM anon, authenticated;" in _flat(_tree())


def test_nothing_grants_the_table_to_a_browser_role():
    named = re.findall(rf"(?is)grant\s+[^;]*\bon\b[^;]*\b{TABLE}\b[^;]*;", _tree())
    schema_wide = re.findall(r"(?is)grant\s+[^;]*\bon\s+all\s+tables\s+in\s+schema\s+public[^;]*;", _tree())
    offending = [
        g for g in named + schema_wide if re.search(r"(?i)\bto\b[^;]*\b(anon|authenticated|public)\b", g)
    ]

    assert not offending, f"{TABLE} is reachable by a browser role: {offending}"


def test_nothing_revokes_the_table_from_the_service_role():
    """The scanners read this table with the service role and refuse to scan without it."""
    revokes = re.findall(rf"(?is)revoke\s+[^;]*\bon\b[^;]*\b{TABLE}\b[^;]*;", _tree())
    schema_wide = re.findall(r"(?is)revoke\s+[^;]*\bon\s+all\s+tables\s+in\s+schema\s+public[^;]*;", _tree())
    offending = [r for r in revokes + schema_wide if re.search(r"(?i)\bfrom\b[^;]*\bservice_role\b", r)]

    assert not offending, f"{TABLE} is revoked from service_role, which the scanners read it with: {offending}"


def test_nothing_later_reshapes_the_table_behind_these_guards():
    """These guards read the migration text, not the live table, and CI applies none. A later
    ALTER would satisfy every assertion above while the database no longer matches, so fail the
    moment one appears and make whoever writes it widen the guards."""
    tree = _tree()

    for verb, pattern, allowed in (
        ("ALTER TABLE", rf"(?is)alter\s+table\s+(?:if\s+exists\s+)?(?:public\.)?{TABLE}\b", 1),
        ("DROP POLICY", rf'(?is)drop\s+policy\s+[^;]*"{TABLE}_', 2),
        ("DROP INDEX", r"(?is)drop\s+index\s+[^;]*uq_team_cleanup_decisions_active", 0),
    ):
        hits = re.findall(pattern, tree)
        assert len(hits) <= allowed, (
            f"{verb} on {TABLE} appeared in a migration; these guards read only its "
            f"original definition and no longer describe the live table: {hits}"
        )
