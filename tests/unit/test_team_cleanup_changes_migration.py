"""Pin the parts of the team_cleanup_changes migration that fail silently.

ci.yml applies no migrations, so these text assertions stand in for executing the SQL. Without the
one-row-per-change index a retried ledger write records a change twice; without the run reference a
change can name a run that never existed; without both RLS with its policies and the REVOKE,
pg_default_acl leaves anon free to rewrite or erase the record of what the loop changed, and RLS
alone still leaves TRUNCATE.

Definitions resolve by name across every migration, newest wins.
"""

import re
from pathlib import Path

MIGRATIONS = Path(__file__).resolve().parents[2] / "supabase" / "migrations"

TABLE = "team_cleanup_changes"


def _executable(text: str) -> str:
    """`text` with -- line and /* */ block comments removed, so a commented-out statement never
    satisfies a substring check."""
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
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


def test_a_change_names_a_run_that_exists():
    assert "run_id TEXT NOT NULL REFERENCES team_cleanup_runs (run_id)," in _create_table()


def test_a_change_s_stage_is_one_of_the_five():
    assert "stage TEXT NOT NULL CHECK (stage IN ('reconcile', 'clubs', 'states', 'ages', 'merges'))," in _create_table()


def test_a_change_is_recorded_once():
    """NULLs never collide in a unique index, so the index holds only while new_value is required."""
    index = _flat(_newest_statement(r"(?is)create\s+unique\s+index\s+(?:if\s+not\s+exists\s+)?uq_team_cleanup_changes"))

    assert f"ON {TABLE} (run_id, stage, team_id_master, field, new_value);" in index, (
        f"the index no longer keeps a retried ledger write from recording a change twice: {index}"
    )
    assert "new_value TEXT NOT NULL," in _create_table()


def test_row_level_security_is_enabled():
    assert re.search(rf"(?is)alter\s+table\s+(?:public\.)?{TABLE}\s+enable\s+row\s+level\s+security", _tree()), (
        f"{TABLE} ships without RLS, which leaves both policies inert"
    )


def test_the_deny_all_policy_covers_anon_and_authenticated():
    deny = _flat(_newest_statement(rf'(?is)create\s+policy\s+"{TABLE}_deny_all"'))

    assert "TO anon, authenticated USING (false) WITH CHECK (false)" in deny, (
        f"the deny-all policy no longer refuses both browser roles: {deny}"
    )


def test_the_service_role_policy_exists():
    allow = _flat(_newest_statement(rf'(?is)create\s+policy\s+"{TABLE}_service_role_all"'))

    assert "TO service_role USING (true) WITH CHECK (true)" in allow, (
        f"the service-role policy no longer grants the loop access: {allow}"
    )


def test_the_default_table_grant_is_revoked():
    """RLS governs SELECT/INSERT/UPDATE/DELETE and not TRUNCATE, so the deny-all policy
    leaves the TRUNCATE in pg_default_acl's grant to anon untouched."""
    assert f"REVOKE ALL ON public.{TABLE} FROM anon, authenticated;" in _flat(_tree())


def test_nothing_grants_the_table_to_a_browser_role():
    named = re.findall(rf"(?is)grant\s+[^;]*\bon\b[^;]*\b{TABLE}\b[^;]*;", _tree())
    schema_wide = re.findall(r"(?is)grant\s+[^;]*\bon\s+all\s+tables\s+in\s+schema\s+public[^;]*;", _tree())
    offending = [g for g in named + schema_wide if re.search(r"(?i)\bto\b[^;]*\b(anon|authenticated|public)\b", g)]

    assert not offending, f"{TABLE} is reachable by a browser role: {offending}"


def test_nothing_revokes_the_table_from_the_service_role():
    revokes = re.findall(rf"(?is)revoke\s+[^;]*\bon\b[^;]*\b{TABLE}\b[^;]*;", _tree())
    schema_wide = re.findall(r"(?is)revoke\s+[^;]*\bon\s+all\s+tables\s+in\s+schema\s+public[^;]*;", _tree())
    offending = [r for r in revokes + schema_wide if re.search(r"(?i)\bfrom\b[^;]*\bservice_role\b", r)]

    assert not offending, f"{TABLE} is revoked from service_role, which the applier records changes with: {offending}"


def test_nothing_later_reshapes_the_table_behind_these_guards():
    """These guards read migration text and CI applies none, so a later ALTER, DROP or re-CREATE
    could leave them green against a table that no longer matches; fail on the first one so its
    author widens them."""
    tree = _tree()

    for verb, pattern, allowed in (
        ("CREATE TABLE", rf"(?is)create\s+table\s+(?:if\s+not\s+exists\s+)?(?:public\.)?{TABLE}\b", 1),
        ("DROP TABLE", rf"(?is)drop\s+table\s+(?:if\s+exists\s+)?(?:public\.)?{TABLE}\b", 0),
        ("ALTER TABLE", rf"(?is)alter\s+table\s+(?:if\s+exists\s+)?(?:public\.)?{TABLE}\b", 1),
        ("DROP POLICY", rf'(?is)drop\s+policy\s+[^;]*"{TABLE}_', 2),
        ("DROP INDEX", r"(?is)drop\s+index\s+[^;]*(?:uq|idx)_team_cleanup_changes", 0),
    ):
        hits = re.findall(pattern, tree)
        assert len(hits) <= allowed, (
            f"{verb} on {TABLE} appeared in a migration; these guards read only its "
            f"original definition and no longer describe the live table: {hits}"
        )
