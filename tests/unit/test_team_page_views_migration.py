"""Pin the parts of the team_page_views migration that fail silently.

ci.yml applies no migrations, so nothing in CI executes this SQL and nothing else
reads it. These text assertions stand in for execution, and they cover the shapes
whose loss produces no error anywhere:

  - RLS or a policy not shipping, since pg_default_acl hands anon full DML on every
    new public relation in this project;
  - the REVOKE going missing, since RLS does not cover the TRUNCATE in that grant;
  - a GRANT to authenticated appearing, which is the specific mistake an earlier
    revision of this migration made. Letting the browser insert its own rows makes
    /api/track-team-view optional: any signed-in account, free tier included, can
    POST straight to the Data API and skip the premium check;
  - the viewed_at index going missing, leaving the daily enqueue's only read to
    scan a table that grows by one row per page view;
  - the user_id index going missing, leaving the ON DELETE CASCADE from auth.users
    to scan that same table on every account deletion.

Everything resolves by NAME across every migration and reads the newest definition.
Pinning to a filename looks equivalent and is not: objects here are superseded by
new migration files rather than edited in place.
"""

import re
from pathlib import Path

MIGRATIONS = Path(__file__).resolve().parents[2] / "supabase" / "migrations"

TABLE = "team_page_views"
SEQUENCE = f"{TABLE}_id_seq"


def _executable(text: str) -> str:
    """`text` with -- line comments removed, leaving only SQL the server runs.

    Every assertion goes through this. A substring check against comment-preserving
    text is satisfied by a commented-out clause — and this migration's comments
    discuss the very grants the tests below assert are absent.
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


def test_the_table_is_created():
    assert re.search(
        rf"(?is)create\s+table\s+(?:if\s+not\s+exists\s+)?(?:public\.)?{TABLE}\s*\(", _tree()
    ), f"{TABLE} is never created"


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
        f"the service-role policy no longer grants the route and the daily job access: {allow}"
    )


def test_the_default_table_and_sequence_grants_are_revoked():
    """RLS governs SELECT/INSERT/UPDATE/DELETE and not TRUNCATE, so the deny-all
    policy leaves the TRUNCATE in pg_default_acl's grant to anon untouched. The
    sequence needs its own REVOKE — a table-level one does not reach it."""
    tree = _flat("\n".join(p.read_text(encoding="utf-8") for p in _migrations()))

    assert f"REVOKE ALL ON public.{TABLE} FROM anon, authenticated;" in tree
    assert f"REVOKE ALL ON SEQUENCE public.{SEQUENCE} FROM anon, authenticated;" in tree


def test_nothing_grants_the_table_or_its_sequence_to_a_browser_role():
    """The security property this table exists under: the route is the only writer.

    A GRANT here would restore the bypass an earlier revision shipped — a free-tier
    account inserting directly through PostgREST, skipping requirePremium and the
    rate limit, with team_id_master constrained by nothing.
    """
    grants = re.findall(
        rf"(?is)grant\s+[^;]*\bon\b[^;]*\b(?:{TABLE}|{SEQUENCE})\b[^;]*;", _tree()
    )
    offending = [g for g in grants if re.search(r"(?i)\bto\b[^;]*\b(anon|authenticated)\b", g)]

    assert not offending, (
        f"{TABLE} is granted to a browser-reachable role, which makes the premium "
        f"check in /api/track-team-view bypassable: {offending}"
    )


def test_the_daily_enqueue_read_is_indexed():
    assert re.search(
        rf"(?is)create\s+index\s+(?:if\s+not\s+exists\s+)?\S+\s+on\s+(?:public\.)?"
        rf"{TABLE}\s*\(\s*viewed_at\s+desc\s*\)",
        _tree(),
    ), "the (viewed_at DESC) index the daily window scan reads is missing"


def test_the_cascade_column_is_indexed():
    """Postgres does not index a referencing column for you, so without this every
    account deletion sequential-scans an append-only table."""
    assert re.search(
        rf"(?is)create\s+index\s+(?:if\s+not\s+exists\s+)?\S+\s+on\s+(?:public\.)?"
        rf"{TABLE}\s*\(\s*user_id\s*\)",
        _tree(),
    ), "the (user_id) index backing the ON DELETE CASCADE is missing"


def test_nothing_later_reshapes_the_table_behind_these_guards():
    """These guards read the migration text, not the live table. This repo evolves
    tables by ALTERing them in later migrations and CI applies none, so a later
    statement would satisfy every assertion above while the database no longer
    matches. Fail the moment one appears, so whoever writes it widens the guards.
    """
    tree = _tree()

    for verb, pattern, allowed in (
        ("ALTER TABLE", rf"(?is)alter\s+table\s+(?:if\s+exists\s+)?(?:public\.)?{TABLE}\b", 1),
        ("DROP INDEX", rf"(?is)drop\s+index\s+[^;]*{TABLE}", 0),
    ):
        hits = re.findall(pattern, tree)
        assert len(hits) <= allowed, (
            f"{verb} on {TABLE} appeared in a migration; these guards read only its "
            f"original definition and no longer describe the live table: {hits}"
        )
