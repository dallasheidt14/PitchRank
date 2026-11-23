"""Pin the parts of the missing_game_clicks migrations that fail silently.

ci.yml applies no migrations to this table, so these text assertions stand in for execution.
They cover the shapes whose loss produces no error anywhere:

  - RLS or a policy not shipping, since pg_default_acl hands anon full DML on every new public
    relation in this project, and a browser could then forge or erase clicks;
  - the REVOKE going missing or naming one role, since RLS does not cover the TRUNCATE in that
    grant;
  - a GRANT to a browser role appearing later;
  - a column the route writes or the investigation reads changing shape;
  - reported_at gaining a default or losing its backfill cutoff, either of which marks clicks
    reported that no email covered.

Statements resolve by name across every migration. Not detected: a grant issued from dynamic SQL
(`EXECUTE format(...)` inside a DO block) and a browser role granted membership in `service_role`.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tests.unit.test_matchbalance_leads_migration import (  # noqa: E402
    _executable,
    _flat,
    _migrations,
    _newest_statement,
    _tree,
)

ROUTE = ROOT / "frontend" / "app" / "api" / "scrape-missing-game" / "route.ts"

TABLE = "missing_game_clicks"
MIGRATION = "20261117120000_add_missing_game_clicks.sql"
REPORTED_MIGRATION = "20261123120000_add_missing_game_clicks_reported_at.sql"

BROWSER_ROLES = {"public", "anon", "authenticated"}

# public.x, public."x", "public"."x" or bare x — pg_dump and hand-written SQL differ.
TABLE_REF = rf'(?:"?public"?\s*\.\s*)?"?{TABLE}"?'

COLUMNS = {
    "id": "UUID PRIMARY KEY DEFAULT gen_random_uuid()",
    "team_id_master": "UUID NOT NULL",
    "game_date": "DATE NOT NULL",
    "clicked_at": "TIMESTAMPTZ NOT NULL DEFAULT NOW()",
    "scrape_request_id": "UUID",
    "reported_at": "TIMESTAMPTZ",
}


def _columns() -> dict[str, str]:
    """The columns its CREATE TABLE and every ADD COLUMN declare; the guards below keep any other
    ALTER out."""
    create = _newest_statement(rf"(?is)create\s+table\s+(?:if\s+not\s+exists\s+)?{TABLE_REF}\s*\(")
    body = create[create.index("(") + 1 : create.rindex(")")]
    columns = {part.split(None, 1)[0]: part.split(None, 1)[1] for part in (p.strip() for p in body.split(",")) if part}
    added = rf"(?is)alter\s+table\s+{TABLE_REF}\s+add\s+column\s+(?:if\s+not\s+exists\s+)?(\w+)\s+([^;]+);"
    for match in re.finditer(added, _tree()):
        columns[match.group(1)] = " ".join(match.group(2).split())
    return columns


def test_the_table_has_exactly_the_columns_the_route_writes_and_the_investigation_reads():
    assert {name: d.upper() for name, d in _columns().items()} == {n: d.upper() for n, d in COLUMNS.items()}
    assert "REFERENCES" not in " ".join(_columns().values()).upper(), f"{TABLE} must not hold a row in place"


def test_every_column_the_route_inserts_exists_and_every_other_one_fills_itself():
    """The route logs a refused insert and answers success, so a key the table lacks, or a NOT NULL
    column the route leaves out, loses every click without an error anyone sees."""
    route = ROUTE.read_text(encoding="utf-8")
    insert = re.search(r"\.from\('missing_game_clicks'\)\s*\.insert\(\{(?P<body>[^}]*)\}\)", route)
    assert insert is not None, "the route no longer inserts a missing_game_clicks row in one object literal"
    keys = set(re.findall(r"(\w+)\s*:", insert.group("body")))

    assert keys == {"team_id_master", "game_date", "scrape_request_id"}, keys
    columns = _columns()
    assert keys <= set(columns), f"the route writes columns the table lacks: {keys - set(columns)}"
    unwritten = {
        name: d
        for name, d in columns.items()
        if name not in keys and re.search(r"(?i)not null|primary key", d) and "DEFAULT" not in d.upper()
    }
    assert not unwritten, f"NOT NULL columns the route leaves out with no default: {unwritten}"


def test_the_migration_holds_only_the_statements_this_guard_reads():
    """The guards below read named statements, so a further statement in this file (an ALTER
    TABLE dropping a default, say) would change the table with every one of them still green."""
    sql = _executable((ROOT / "supabase" / "migrations" / MIGRATION).read_text(encoding="utf-8"))
    kinds = [" ".join(stmt.split()[:5]).upper() for stmt in sql.split(";") if stmt.strip()]

    assert kinds == [
        "CREATE TABLE IF NOT EXISTS",
        "CREATE INDEX IF NOT EXISTS",
        "COMMENT ON TABLE MISSING_GAME_CLICKS IS",
        "ALTER TABLE MISSING_GAME_CLICKS ENABLE ROW",
        'DROP POLICY IF EXISTS "MISSING_GAME_CLICKS_DENY_ALL"',
        'CREATE POLICY "MISSING_GAME_CLICKS_DENY_ALL" ON MISSING_GAME_CLICKS',
        'COMMENT ON POLICY "MISSING_GAME_CLICKS_DENY_ALL" ON',
        'DROP POLICY IF EXISTS "MISSING_GAME_CLICKS_SERVICE_ROLE_ALL"',
        'CREATE POLICY "MISSING_GAME_CLICKS_SERVICE_ROLE_ALL" ON MISSING_GAME_CLICKS',
        'COMMENT ON POLICY "MISSING_GAME_CLICKS_SERVICE_ROLE_ALL" ON',
        "REVOKE ALL ON PUBLIC.MISSING_GAME_CLICKS FROM",
    ], kinds


def test_reported_at_is_added_nullable_and_stamped_only_on_clicks_already_emailed():
    """The report emails every click whose reported_at is NULL. A default would stamp every new
    click as it is written, and a backfill without its cutoff would stamp clicks no email covered;
    either way those clicks are never emailed."""
    sql = _executable((ROOT / "supabase" / "migrations" / REPORTED_MIGRATION).read_text(encoding="utf-8"))
    statements = [_flat(stmt) for stmt in sql.split(";") if stmt.strip()]

    assert statements == [
        "ALTER TABLE missing_game_clicks ADD COLUMN IF NOT EXISTS reported_at TIMESTAMPTZ",
        "UPDATE missing_game_clicks SET reported_at = NOW() "
        "WHERE reported_at IS NULL AND clicked_at < '2026-11-23 15:00:00+00'",
    ], statements


def test_row_level_security_is_enabled():
    assert re.search(rf"(?is)alter\s+table\s+{TABLE_REF}\s+enable\s+row\s+level\s+security\s*;", _tree()), (
        f"{TABLE} ships without RLS, which leaves both policies inert"
    )


def test_the_deny_all_policy_covers_anon_and_authenticated():
    deny = _flat(_newest_statement(rf'(?is)create\s+policy\s+"{TABLE}_deny_all"'))

    assert "TO anon, authenticated USING (false) WITH CHECK (false)" in deny, deny


def test_the_service_role_policy_exists():
    allow = _flat(_newest_statement(rf'(?is)create\s+policy\s+"{TABLE}_service_role_all"'))

    assert "TO service_role USING (true) WITH CHECK (true)" in allow, allow


def test_the_default_table_grant_is_revoked_from_both_browser_roles():
    revoke = _newest_statement(rf"(?is)\brevoke\s+all\s+on\s+(?:table\s+)?{TABLE_REF}\b")
    roles = re.split(r"(?i)\bfrom\b", revoke)[-1]

    for role in ("anon", "authenticated"):
        assert re.search(rf"(?i)\b{role}\b", roles), f"the REVOKE does not name {role}: {revoke}"


def test_no_statement_in_any_migration_reopens_the_table():
    tree = _tree()

    grants = [
        _flat(match.group(0))
        for match in re.finditer(rf"(?is)\bgrant\s+[^;]*?\bon\s+(?:table\s+)?{TABLE_REF}\b[^;]*(?:;|\Z)", tree)
    ]
    reaching = [g for g in grants if re.search(r"(?i)\b(public|anon|authenticated)\b", re.split(r"(?i)\bto\b", g)[-1])]
    assert not reaching, f"{TABLE} is granted to a browser role: {reaching}"

    assert not re.search(
        rf"(?is)alter\s+table\s+(?:only\s+|if\s+exists\s+)*{TABLE_REF}\s+disable\s+row\s+level\s+security", tree
    ), f"a migration disables row level security on {TABLE}"

    for policy in (f"{TABLE}_deny_all", f"{TABLE}_service_role_all"):
        events = [
            match.group(1).lower()
            for match in re.finditer(rf'(?is)\b(create|alter|drop)\s+policy\s+(?:if\s+exists\s+)?"{policy}"', tree)
        ]
        assert events and events[-1] == "create" and "alter" not in events, (
            f"{policy} is altered or dropped after it is created: {events}"
        )


def test_nothing_later_touches_the_table_behind_these_guards():
    """These guards read migration text, not the live table. Fail as soon as a further file
    mentions the table, so whoever writes it widens these guards deliberately."""
    touching = [
        path.name for path in _migrations() if re.search(rf"(?i){TABLE}", _executable(path.read_text(encoding="utf-8")))
    ]

    assert touching == [MIGRATION, REPORTED_MIGRATION], f"{TABLE} is referenced by an unguarded migration: {touching}"


def test_no_later_schema_wide_grant_reaches_a_browser_role():
    names = [path.name for path in _migrations()]
    later = _migrations()[names.index(MIGRATION) + 1 :]

    offending = []
    for path in later:
        sql = _executable(path.read_text(encoding="utf-8"))
        for match in re.finditer(
            r"(?is)\bgrant\b[^;]*?\bon\s+all\s+tables\s+in\s+schema\s+(?P<schemas>.*?)\s+to\s+(?P<roles>[^;]*)(?:;|\Z)",
            sql,
        ):
            schemas = {name.strip().strip('"').lower() for name in match.group("schemas").split(",")}
            roles = {role.lower() for role in re.findall(r"(?i)\b(public|anon|authenticated)\b", match.group("roles"))}
            if "public" in schemas and roles & BROWSER_ROLES:
                offending.append(f"{path.name}: {_flat(match.group(0))}")

    assert not offending, f"a later migration grants every public table to a browser role: {offending}"
