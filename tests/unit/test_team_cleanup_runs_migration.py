"""Pin the parts of team_cleanup_runs's migrations that fail silently.

ci.yml applies no migrations, so these text assertions stand in for executing the SQL. Without the
one-open-run index two weekly runs can both be open, and without its predicate a finished run
blocks the next; without the whole-lease check a holder left with no expiry can never be taken
over; without both RLS with its policies and the REVOKE, pg_default_acl leaves anon free to take or
clear an applier's lease, and RLS alone still leaves TRUNCATE.

Definitions resolve by name across every migration, newest wins.
"""

import re
from pathlib import Path

MIGRATIONS = Path(__file__).resolve().parents[2] / "supabase" / "migrations"

TABLE = "team_cleanup_runs"


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


def test_a_run_s_status_is_one_of_the_six():
    assert (
        "status TEXT NOT NULL CHECK (status IN ('proposing', 'reviewing', 'applying', 'second_lap', 'done', "
        "'abandoned'))"
    ) in _create_table()


def test_a_run_id_is_a_dated_scope_like_the_store_s_folders():
    """The id names a folder in the run store, which refuses anything else as a path."""
    assert "CHECK (run_id ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}-[a-z0-9]+(-[a-z0-9]+)*$')" in _create_table()


def test_a_lease_is_a_holder_and_an_expiry_together():
    assert "CHECK ((lease_holder IS NULL) = (lease_expires_at IS NULL))" in _create_table()


def test_only_one_run_is_open():
    index = _flat(_newest_statement(r"(?is)create\s+unique\s+index\s+(?:if\s+not\s+exists\s+)?uq_team_cleanup_runs"))

    assert (f"ON {TABLE} ((true)) WHERE status IN ('proposing', 'reviewing', 'applying', 'second_lap');") in index, (
        f"the index no longer allows exactly one open run, or counts a closed one: {index}"
    )


def test_the_database_keeps_updated_at():
    """The lease writes do not stamp updated_at themselves."""
    trigger = _flat(_newest_statement(r"(?is)create\s+trigger\s+update_team_cleanup_runs_updated_at"))

    assert f"BEFORE UPDATE ON public.{TABLE} FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();" in trigger


def test_the_owner_s_done_is_a_time_and_who_marked_it_together():
    """The applier reads owner_done_at to know a page is finished; a time without who set it, the
    owner or the Sunday deadline, could not be told apart in the run's record."""
    columns = _flat(_newest_statement(rf"(?is)alter\s+table\s+(?:public\.)?{TABLE}\s+add\s+column"))
    whole = _flat(_newest_statement(r"(?is)add\s+constraint\s+team_cleanup_runs_owner_done_is_whole"))

    assert "ADD COLUMN IF NOT EXISTS owner_done_at TIMESTAMPTZ," in columns
    assert "ADD COLUMN IF NOT EXISTS owner_done_by TEXT CHECK (owner_done_by IN ('owner', 'deadline'));" in columns
    assert "CHECK ((owner_done_at IS NULL) = (owner_done_by IS NULL));" in whole


def test_the_owner_s_done_check_is_dropped_before_it_is_added_and_never_after():
    """A hand-applied migration runs again; the drop lets the add succeed the second time, and a drop
    after the newest add would leave the table with no check at all."""
    drop = r"(?is)drop\s+constraint\s+if\s+exists\s+team_cleanup_runs_owner_done_is_whole\s*;"
    add = r"(?is)add\s+constraint\s+team_cleanup_runs_owner_done_is_whole\b"
    tree = _tree()

    adds = list(re.finditer(add, tree))
    assert adds, "no migration adds the owner's-done check"
    drops_before = [m for m in re.finditer(drop, tree) if m.start() < adds[-1].start()]
    drops_after = [
        m for m in re.finditer(r"(?is)drop\s+constraint[^;]*owner_done_is_whole", tree) if m.start() > adds[-1].start()
    ]

    assert drops_before, "the owner's-done check is added with no drop of that name before it"
    assert not drops_after, "a later statement drops the owner's-done check the newest migration added"


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
    """The loop takes its lease with the service role."""
    revokes = re.findall(rf"(?is)revoke\s+[^;]*\bon\b[^;]*\b{TABLE}\b[^;]*;", _tree())
    schema_wide = re.findall(r"(?is)revoke\s+[^;]*\bon\s+all\s+tables\s+in\s+schema\s+public[^;]*;", _tree())
    offending = [r for r in revokes + schema_wide if re.search(r"(?i)\bfrom\b[^;]*\bservice_role\b", r)]

    assert not offending, f"{TABLE} is revoked from service_role, which the loop leases it with: {offending}"


def test_nothing_later_reshapes_the_table_behind_these_guards():
    """These guards read migration text and CI applies none, so a later ALTER, DROP or re-CREATE
    could leave them green against a table that no longer matches; fail on the first one so its
    author widens them."""
    tree = _tree()

    for verb, pattern, allowed in (
        ("CREATE TABLE", rf"(?is)create\s+table\s+(?:if\s+not\s+exists\s+)?(?:public\.)?{TABLE}\b", 1),
        ("DROP TABLE", rf"(?is)drop\s+table\s+(?:if\s+exists\s+)?(?:public\.)?{TABLE}\b", 0),
        # Enabling RLS, then the owner's-done columns, the drop of their check and its re-add.
        ("ALTER TABLE", rf'(?is)alter\s+table\s+(?:if\s+exists\s+)?(?:only\s+)?(?:"?public"?\.)?"?{TABLE}"?\b', 4),
        ("DROP POLICY", rf'(?is)drop\s+policy\s+[^;]*"{TABLE}_', 2),
        ("DROP INDEX", r"(?is)drop\s+index\s+[^;]*uq_team_cleanup_runs", 0),
        ("DROP TRIGGER", r"(?is)drop\s+trigger\s+[^;]*update_team_cleanup_runs_updated_at", 1),
        ("DROP FUNCTION", r"(?is)drop\s+function\s+[^;]*\bupdate_updated_at_column\b", 0),
    ):
        hits = re.findall(pattern, tree)
        assert len(hits) <= allowed, (
            f"{verb} on {TABLE} appeared in a migration; these guards do not cover it "
            f"and may no longer describe the live table: {hits}"
        )
