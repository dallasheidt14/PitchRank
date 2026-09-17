"""Pin the parts of the team_ranking_exclusions migration that fail silently.

ci.yml applies no migrations, so nothing in CI executes this SQL. These text assertions
stand in for execution, and they cover the shapes whose loss produces no error anywhere:

  - RLS or a policy not shipping, since pg_default_acl hands anon full DML on every new
    public relation in this project -- here that would let a browser add or remove teams
    from the rankings;
  - the REVOKE going missing, since RLS does not cover the TRUNCATE in that grant;
  - a GRANT to a browser role appearing.

Everything resolves by NAME across every migration and reads the newest definition.
Pinning to a filename looks equivalent and is not: objects here are superseded by new
migration files rather than edited in place.
"""

import re
from pathlib import Path

MIGRATIONS = Path(__file__).resolve().parents[2] / "supabase" / "migrations"

TABLE = "team_ranking_exclusions"


def _executable(text: str) -> str:
    """`text` with -- line comments removed, leaving only SQL the server runs.

    Every assertion goes through this. A substring check against comment-preserving text is
    satisfied by a commented-out clause — and this migration's comments discuss the very
    grants the tests below assert are absent.
    """
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


def test_the_table_is_created_keyed_on_the_team():
    create = _flat(_newest_statement(rf"(?is)create\s+table\s+(?:if\s+not\s+exists\s+)?(?:public\.)?{TABLE}\s*\("))

    assert "team_id_master UUID PRIMARY KEY" in create, (
        f"the loader reads one row per team and the script inserts by team_id_master: {create}"
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
        f"the service-role policy no longer grants the script and the ranking run access: {allow}"
    )


def test_the_default_table_grant_is_revoked():
    """RLS governs SELECT/INSERT/UPDATE/DELETE and not TRUNCATE, so the deny-all policy
    leaves the TRUNCATE in pg_default_acl's grant to anon untouched."""
    assert f"REVOKE ALL ON public.{TABLE} FROM anon, authenticated;" in _flat(_tree())


def test_nothing_grants_the_table_to_a_browser_role():
    """PUBLIC counts: anon and authenticated inherit whatever it holds, and a schema-wide
    grant reaches this table without naming it."""
    named = re.findall(rf"(?is)grant\s+[^;]*\bon\b[^;]*\b{TABLE}\b[^;]*;", _tree())
    schema_wide = re.findall(r"(?is)grant\s+[^;]*\bon\s+all\s+tables\s+in\s+schema\s+public[^;]*;", _tree())
    offending = [
        g for g in named + schema_wide if re.search(r"(?i)\bto\b[^;]*\b(anon|authenticated|public)\b", g)
    ]

    assert not offending, f"{TABLE} is reachable by a browser role: {offending}"


def test_nothing_revokes_the_table_from_the_service_role():
    """The ranking run reads this list with the service role and refuses to rank without it,
    so a revoke here stops the weekly run rather than degrading quietly."""
    revokes = re.findall(rf"(?is)revoke\s+[^;]*\bon\b[^;]*\b{TABLE}\b[^;]*;", _tree())
    schema_wide = re.findall(r"(?is)revoke\s+[^;]*\bon\s+all\s+tables\s+in\s+schema\s+public[^;]*;", _tree())
    offending = [r for r in revokes + schema_wide if re.search(r"(?i)\bfrom\b[^;]*\bservice_role\b", r)]

    assert not offending, f"{TABLE} is revoked from service_role, which the ranking run reads it with: {offending}"


def test_nothing_later_reshapes_the_table_behind_these_guards():
    """These guards read the migration text, not the live table. This repo evolves
    tables by ALTERing them in later migrations and CI applies none, so a later
    statement would satisfy every assertion above while the database no longer
    matches. Fail the moment one appears, so whoever writes it widens the guards.
    """
    tree = _tree()

    for verb, pattern, allowed in (
        ("ALTER TABLE", rf"(?is)alter\s+table\s+(?:if\s+exists\s+)?(?:public\.)?{TABLE}\b", 1),
        ("DROP POLICY", rf'(?is)drop\s+policy\s+[^;]*"{TABLE}_', 2),
    ):
        hits = re.findall(pattern, tree)
        assert len(hits) <= allowed, (
            f"{verb} on {TABLE} appeared in a migration; these guards read only its "
            f"original definition and no longer describe the live table: {hits}"
        )
