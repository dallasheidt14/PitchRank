"""Pin that the browser roles cannot write the tables only the service role writes, nor call the owner-run writers.

The anon key ships in every page and any free account holds an authenticated session, so a write
privilege either one holds is a write anyone can make. The grant is what this pins. Migrations
20261121000200 and 20261121000300 revoke the writes; this replays every migration in order, as the
column-grant guard does, so a later GRANT, a GRANT TO PUBLIC, a schema-wide GRANT or a DROP and CREATE
that hands a table back to the browser roles fails here. Live check, for each table and both roles:
  SELECT has_table_privilege('anon', 'public.<table>', 'INSERT, UPDATE, DELETE, TRUNCATE');
"""

import re

from tests.unit.test_public_column_grants_migration import (
    BROWSER,
    _function_grantees,
    _live_policies,
    _ref,
    _roles,
    policy_qualifier,
    policy_roles,
    privilege_events,
)
from tests.unit.test_scrape_requests_rls_migration import _signature, _sources

WRITES = frozenset({"insert", "update", "delete", "truncate"})

SERVICE_WRITTEN_TABLES = (
    "rankings_full",
    "ranking_history",
    "team_merge_map",
    "team_social_profiles",
    "team_momentum",
    "team_trajectory",
    "game_history",
    "announcements",
)

OWNER_RUN_WRITERS = (
    "backfill_total_game_stats",
    "backfill_total_game_stats_page",
    "batch_backfill_null_scores",
    "batch_upsert_game_explainability",
    "batch_update_ml_overperformance",
)

DO_BLOCK = re.compile(r"(?is)\bdo\s+\$\$(.*?)\$\$")
GUARDED_BRANCH = re.compile(
    r"(?is)\bif\s+to_regclass\(\s*'public\.(\w+)'\s*\)\s+is\s+not\s+null\s+then(.*?)\bend\s+if\s*;"
)


def _named_writes(privileges: str) -> set[str]:
    """The write privileges a GRANT or REVOKE list names; ALL names every one."""
    if re.search(r"(?is)\ball\b", privileges):
        return set(WRITES)
    return {word.lower() for word in re.findall(r"(?is)\b(insert|update|delete|truncate)\b", privileges)}


def browser_writes(table: str) -> dict[str, set[str]]:
    """Role -> the write privileges it holds on `table` after every migration, directly or through PUBLIC.

    pg_default_acl gives anon and authenticated every privilege on a new relation, so a rebuild starts
    both over at every write, and a table no migration creates starts there too. PUBLIC is tracked on its
    own, as Postgres does: revoking a role's own grant leaves what it inherits from PUBLIC. A column-level
    grant (`UPDATE (col)`) counts as holding the privilege; a column-level revoke does not take a
    table-wide one away, so only a revoke without a column list removes it.
    """
    fresh = {"public": set(), **{role: set(WRITES) for role in BROWSER}}
    held = {grantee: set(privileges) for grantee, privileges in fresh.items()}
    for parts in privilege_events(table):
        if parts is None:
            held = {grantee: set(privileges) for grantee, privileges in fresh.items()}
            continue
        named = _named_writes(parts.group(2))
        grantees = _roles(parts.group(5))
        if parts.group(1).lower() == "grant":
            for grantee in grantees:
                held[grantee] |= named
        else:
            whole = {w for w in named if not re.search(rf"(?is)\b{w}\s*\(", parts.group(2))}
            for grantee in grantees:
                held[grantee] -= whole
    return {role: held[role] | held["public"] for role in BROWSER}


def _created_signatures(name: str) -> set[str]:
    """Every argument signature any migration creates `name` with, so a later overload is checked too."""
    pattern = re.compile(rf"(?is)\bcreate\s+(?:or\s+replace\s+)?function\s+{_ref(name)}\s*\(([^)]*)\)")
    return {_signature(match.group(1)) for _, sql in _sources() for match in pattern.finditer(sql)}


def _opens_reads_to_browser(body: str) -> bool:
    """Whether a permissive policy body lets a browser role read rows: FOR SELECT or ALL, or no FOR."""
    command = re.search(r"(?is)\bfor\s+(all|select|insert|update|delete)\b", body)
    if command and command.group(1).lower() not in {"all", "select"}:
        return False
    return policy_roles(body) != set() and policy_qualifier(body, "using") != "false"


def test_no_browser_role_can_write_a_service_written_table():
    held = {table: browser_writes(table) for table in SERVICE_WRITTEN_TABLES}
    open_tables = {table: roles for table, roles in held.items() if any(roles.values())}
    assert not open_tables, f"a browser role can write: {open_tables}"


def test_a_guarded_revoke_runs_whenever_its_table_exists():
    """The replay counts a REVOKE inside a DO block whatever its IF says, so pin each IF to its table."""
    for path, sql in _sources():
        for block in DO_BLOCK.finditer(sql):
            body = block.group(1)
            for table in SERVICE_WRITTEN_TABLES:
                revoke = rf"(?is)\brevoke\b[^;]*\bon\s+{_ref(table)}\b"
                inside = len(re.findall(revoke, body))
                if not inside:
                    continue
                assert not re.search(r"(?is)\bexception\b", body), f"{path.name}: the DO block swallows errors"
                guarded = sum(
                    len(re.findall(revoke, branch.group(2)))
                    for branch in GUARDED_BRANCH.finditer(body)
                    if branch.group(1).lower() == table
                )
                assert guarded == inside, (
                    f"{path.name}: a revoke on {table} does not run under IF to_regclass('public.{table}') IS NOT NULL"
                )


def test_the_owner_run_writers_are_closed_to_the_browser_roles():
    """They write as their owner, so their own grant is the only thing between them and the browser."""
    for name in OWNER_RUN_WRITERS:
        signatures = _created_signatures(name)
        assert signatures, f"{name} is never created"
        for signature in signatures:
            granted = _function_grantees(name, signature)
            if granted is None:
                continue
            assert not granted & {"public", *BROWSER}, f"{name}({signature}) is callable by {sorted(granted)}"


def test_no_browser_role_can_read_newsletter_subscribers():
    """The signup form inserts a row; nothing on the site reads subscribers back."""
    tree = "\n".join(sql for _, sql in _sources())
    ref = _ref("newsletter_subscribers")
    assert re.search(rf"(?is)alter\s+table\s+(?:only\s+)?{ref}\s+enable\s+row\s+level\s+security", tree)
    assert not re.search(rf"(?is)alter\s+table[^;]*{ref}\b[^;]*disable\s+row\s+level\s+security", tree), (
        "row level security is switched off, which opens every subscriber row to the browser roles' SELECT"
    )
    live = _live_policies("newsletter_subscribers")
    opened = {name: body for name, body in live.items() if _opens_reads_to_browser(body)}
    assert not opened, f"a policy lets a browser role read subscriber emails: {opened}"


def test_a_signed_out_visitor_can_still_subscribe():
    """The signup route inserts with the anon key, so its grant and an insert policy that admits it must stay."""
    assert "insert" in browser_writes("newsletter_subscribers")["anon"], "the anon key lost INSERT on subscribers"
    admits_anon = [
        name
        for name, body in _live_policies("newsletter_subscribers").items()
        if re.search(r"(?is)\bfor\s+insert\b", body)
        and (policy_roles(body) is None or policy_roles(body) & {"public", "anon"})
        and (policy_qualifier(body, r"with\s+check") or policy_qualifier(body, "using")) != "false"
    ]
    assert admits_anon, "no insert policy admits the anon key, so subscribing would fail"
