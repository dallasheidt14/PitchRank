"""Pin the parts of the matchbalance_leads migration that fail silently.

ci.yml applies no migrations, so nothing in CI executes this SQL and nothing else
reads it. These text assertions stand in for execution, and they cover the shapes
whose loss produces no error anywhere:

  - RLS or a policy not shipping, since pg_default_acl hands anon full DML on every
    new public relation in this project;
  - the REVOKE going missing or naming one role, since RLS does not cover the
    TRUNCATE in that grant;
  - a GRANT to a browser role appearing. /api/matchbalance-inquiry is public by
    design and its guards are its whole defence, so a browser-reachable grant lets
    anyone holding the anon key skip them, or read back every director's contact
    details.

Statements resolve by name across every migration; the last two tests use this file's
name only to find what comes after it. Not detected: a grant issued from
dynamic SQL (`EXECUTE format(...)` inside a DO block) and a browser role granted
membership in `service_role`.
"""

import re
from pathlib import Path

MIGRATIONS = Path(__file__).resolve().parents[2] / "supabase" / "migrations"

TABLE = "matchbalance_leads"
TRIGGER_FN = f"update_{TABLE}_updated_at"

BROWSER_ROLES = {"public", "anon", "authenticated"}

# public.x, public."x", "public"."x" or bare x — pg_dump and hand-written SQL differ.
TABLE_REF = rf'(?:"?public"?\s*\.\s*)?"?{TABLE}"?'


def _executable(text: str) -> str:
    """`text` with -- line and /* */ block comments removed.

    Every assertion goes through this. A substring check against comment-preserving
    text is satisfied by a commented-out clause — and this migration's comments
    discuss the very grants the tests below assert are absent.
    """
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
    return _newest_statement(
        rf"(?is)create\s+table\s+(?:if\s+not\s+exists\s+)?{TABLE_REF}\s*\("
    )


def _column(create: str, name: str) -> str:
    """One column definition from the CREATE TABLE, up to its separating comma."""
    match = re.search(rf"(?i)[(,]\s*{name}\s+([^,]*?)\s*(?=,|\);)", create)
    assert match is not None, f"{TABLE} has no {name} column: {create}"
    return match.group(1)


def test_the_table_has_every_column_the_route_writes():
    create = _create_table()

    expected = {
        "id": "UUID PRIMARY KEY DEFAULT gen_random_uuid()",
        "created_at": "TIMESTAMPTZ NOT NULL DEFAULT NOW()",
        "updated_at": "TIMESTAMPTZ NOT NULL DEFAULT NOW()",
        "name": "TEXT NOT NULL",
        "email": "TEXT NOT NULL",
        "organization": "TEXT NOT NULL",
        "tournament_name": "TEXT NOT NULL",
        "event_dates": "TEXT NOT NULL",
        "team_count": "INTEGER",
        "bracket_review_date": "DATE",
        "event_url": "TEXT",
        "request_type": "TEXT NOT NULL",
        "notes": "TEXT",
        "source_ip_masked": "TEXT",
        "status": "TEXT NOT NULL DEFAULT 'new'",
    }

    for name, definition in expected.items():
        assert _column(create, name).upper() == definition.upper(), (
            f"{TABLE}.{name} is no longer `{definition}`: {_column(create, name)}"
        )


def test_row_level_security_is_enabled():
    assert re.search(
        rf"(?is)alter\s+table\s+{TABLE_REF}\s+enable\s+row\s+level\s+security\s*;", _tree()
    ), f"{TABLE} ships without RLS, which leaves both policies inert"


def test_the_deny_all_policy_covers_anon_and_authenticated():
    deny = _flat(_newest_statement(rf'(?is)create\s+policy\s+"{TABLE}_deny_all"'))

    assert "TO anon, authenticated USING (false) WITH CHECK (false)" in deny, (
        f"the deny-all policy no longer refuses both browser roles: {deny}"
    )


def test_the_service_role_policy_exists():
    allow = _flat(_newest_statement(rf'(?is)create\s+policy\s+"{TABLE}_service_role_all"'))

    assert "TO service_role USING (true) WITH CHECK (true)" in allow, (
        f"the service-role policy no longer grants the route and the Leads page access: {allow}"
    )


def test_the_default_table_grant_is_revoked_from_both_browser_roles():
    """RLS governs SELECT/INSERT/UPDATE/DELETE and not TRUNCATE, so the deny-all
    policy leaves the TRUNCATE in pg_default_acl's grant to anon untouched."""
    revoke = _newest_statement(rf"(?is)\brevoke\s+all\s+on\s+(?:table\s+)?{TABLE_REF}\b")
    roles = re.split(r"(?i)\bfrom\b", revoke)[-1]

    for role in ("anon", "authenticated"):
        assert re.search(rf"(?i)\b{role}\b", roles), f"the REVOKE does not name {role}: {revoke}"


def test_updated_at_is_maintained_by_a_trigger():
    tree = _tree()

    assert re.search(
        rf"CREATE OR REPLACE FUNCTION\s+(?:public\.)?{TRIGGER_FN}\(\).*?\$\$.*?\$\$\s*"
        r"LANGUAGE plpgsql\s+SET search_path = ''",
        tree,
        re.S,
    ), f"{TRIGGER_FN} is missing or no longer pins an empty search_path"

    trigger = _newest_statement(rf"(?is)create\s+trigger\s+{TRIGGER_FN}\b")
    assert re.search(
        rf"(?i)BEFORE UPDATE ON {TABLE_REF} FOR EACH ROW EXECUTE FUNCTION {TRIGGER_FN}\(\)",
        trigger,
    ), f"the updated_at trigger no longer fires before each update: {trigger}"


def test_no_statement_in_any_migration_reopens_the_table():
    """The checks above read the statements that lock the table down, so a GRANT,
    DISABLE ROW LEVEL SECURITY or policy drop appended after them in the same file
    would leave every one green. So fail on any browser-role GRANT or DISABLE ROW LEVEL
    SECURITY anywhere in the tree, and require each policy's last event to be its CREATE."""
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
    """These guards read migration text, not the live table, and CI applies no SQL. A
    later column change, an unquoted policy change or a redefined trigger function would
    satisfy every assertion above while the database no longer matches. Fail as soon as a
    second file mentions the table, so whoever writes it widens these guards deliberately.

    Unanchored on purpose: a redefinition of the trigger function names the table only
    inside its own identifier."""
    touching = [
        path.name
        for path in _migrations()
        if re.search(rf"(?i){TABLE}", _executable(path.read_text(encoding="utf-8")))
    ]

    assert touching == ["20260916120000_create_matchbalance_leads.sql"], (
        f"{TABLE} is referenced by more than its own migration; these guards read only "
        f"that file and no longer describe the live table: {touching}"
    )


def test_no_later_schema_wide_grant_reaches_a_browser_role():
    """A schema-wide grant never names the table, so the test above cannot see it, and
    `TO PUBLIC` reopens access without naming a browser role or the table either."""
    names = [path.name for path in _migrations()]
    later = _migrations()[names.index("20260916120000_create_matchbalance_leads.sql") + 1 :]

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

    assert not offending, (
        f"a later migration grants every public table to a browser role, which reaches "
        f"{TABLE}: {offending}"
    )
