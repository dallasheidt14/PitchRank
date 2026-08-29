"""Pin the pieces of the team-state provenance migration that fail silently.

ci.yml applies no migrations, so nothing in CI executes this SQL. These text assertions
stand in for execution, and they cover only the shapes whose loss produces no error:
a trigger WHEN clause going missing (the ledger then fires on every one of ~3,840 daily
last_scraped_at writes), a set_config's transaction-local flag flipping to false (the
actor becomes invisible to the trigger and leaks into later requests), the revert losing
its exclusion of its own rows (a second revert undoes the first), a bulk function growing
a whole-batch scan (cancelled at 8s in production, never in a test), and RLS or its policy
pair not shipping with a new table (pg_default_acl hands anon full DML on it).

Everything here resolves objects by NAME across every migration and reads the newest
definition of each. Pinning to a filename looks equivalent and is not: objects in this
repo are superseded by new migration files rather than edited in place, so a path-pinned
guard stops covering its object the moment anyone redefines it.
"""

import re
from pathlib import Path

MIGRATIONS = Path(__file__).resolve().parents[2] / "supabase" / "migrations"

AUDIT_TABLE = "team_state_audit"
QUEUE_TABLE = "team_state_review_queue"
EVENTS_TABLE = "tgs_events"
NEW_TABLES = (AUDIT_TABLE, QUEUE_TABLE, EVENTS_TABLE)

TRIGGER_FUNCTION = "log_team_state_change"
WRITE_FUNCTION = "apply_team_state"
REVERT_FUNCTION = "revert_team_states"
NEW_FUNCTIONS = (TRIGGER_FUNCTION, WRITE_FUNCTION, REVERT_FUNCTION)


def _executable(text: str) -> str:
    """`text` with -- line comments removed, leaving only SQL the server runs.

    Behavioural assertions must go through this. A substring check against
    comment-preserving text is satisfied by a commented-out clause.
    """
    return re.sub(r"--[^\n]*", "", text)


def _flat(text: str) -> str:
    return re.sub(r"\s+", " ", _executable(text)).strip()


def _migrations() -> list[Path]:
    """Every migration, oldest first: filenames are timestamp-prefixed."""
    return sorted(MIGRATIONS.glob("*.sql"))


def _balanced(sql: str, open_idx: int) -> str:
    """The parenthesised group starting at `open_idx`, quotes skipped."""
    depth = 0
    i = open_idx
    while i < len(sql):
        char = sql[i]
        if char == "'":
            i = sql.index("'", i + 1) + 1
            continue
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return sql[open_idx : i + 1]
        i += 1
    raise AssertionError("unbalanced parentheses")


def _newest(name: str, pattern: str, extract) -> str:
    """The last definition of `name` in migration order, via `extract`."""
    found = None
    for path in _migrations():
        sql = _executable(path.read_text(encoding="utf-8"))
        for match in re.finditer(pattern, sql):
            found = extract(sql, match)
    assert found is not None, f"no migration defines {name}"
    return found


def _table(name: str) -> str:
    """The newest CREATE TABLE column list for `name`."""
    pattern = rf"(?is)create\s+table\s+(?:if\s+not\s+exists\s+)?(?:public\.)?{re.escape(name)}\s*\("
    return _newest(name, pattern, lambda sql, m: _balanced(sql, sql.index("(", m.end() - 1)))


def _function(name: str) -> str:
    """The newest dollar-quoted body defined for `name`."""
    pattern = rf"(?is)create\s+or\s+replace\s+function\s+(?:public\.)?{re.escape(name)}\s*\("

    def _body(sql, match):
        start = sql.index("$$", match.end())
        return sql[start : sql.index("$$", start + 2) + 2]

    return _newest(name, pattern, _body)


def _header(name: str) -> str:
    """The newest definition of `name` from CREATE down to its body."""
    pattern = rf"(?is)create\s+or\s+replace\s+function\s+(?:public\.)?{re.escape(name)}\s*\("
    return _newest(name, pattern, lambda sql, m: sql[m.start() : sql.index("$$", m.end())])


def _split_top_level(group: str) -> list[str]:
    """The comma-separated members of a parenthesised group, one nesting level down."""
    depth = 0
    member = ""
    members = []
    for char in group[1:-1]:
        if char == "," and depth == 0:
            members.append(member.strip())
            member = ""
            continue
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        member += char
    members.append(member.strip())
    return members


def _argument_types(name: str) -> str:
    """`name`'s declared argument types, as the identity arguments an ACL names them."""
    header = _header(name)
    arguments = _split_top_level(_balanced(header, header.index("(")))
    return ", ".join(argument.split()[1] for argument in arguments if argument)


def _trigger(name: str) -> str:
    """The newest CREATE TRIGGER statement for `name`."""
    pattern = rf"(?is)create\s+trigger\s+{re.escape(name)}\b"
    return _newest(name, pattern, lambda sql, m: sql[m.start() : sql.index(";", m.end()) + 1])


def _statements(pattern: str) -> list[str]:
    """Every statement across the tree whose opening matches `pattern`."""
    out = []
    for path in _migrations():
        sql = _executable(path.read_text(encoding="utf-8"))
        for match in re.finditer(pattern, sql):
            out.append(sql[match.start() : sql.index(";", match.end()) + 1])
    return out


# --------------------------------------------------------------------------- #
# The two triggers (one trigger cannot be created at all — WHEN cannot read OLD
# on INSERT — so the failure this guards is someone dropping a WHEN clause)
# --------------------------------------------------------------------------- #


def test_update_trigger_fires_only_when_the_state_or_its_provenance_changes():
    """All three columns, because a write that only re-sources a state it agrees with
    would otherwise succeed unlogged — and none of the three is on the hot path."""
    assert re.search(
        r"(?is)after\s+update\s+on\s+(?:public\.)?teams\s+for\s+each\s+row\s+"
        r"when\s+\(\s*OLD\.state_code IS DISTINCT FROM NEW\.state_code"
        r" OR OLD\.state_source IS DISTINCT FROM NEW\.state_source"
        r" OR OLD\.state_confidence IS DISTINCT FROM NEW\.state_confidence\s*\)",
        _flat(_trigger("log_team_state_update")),
    ), "the UPDATE trigger's WHEN clause changed"


def test_insert_trigger_fires_only_for_a_state_bearing_row():
    assert re.search(
        r"(?is)after\s+insert\s+on\s+(?:public\.)?teams\s+for\s+each\s+row\s+"
        r"when\s+\(\s*NEW\.state_code\s+IS\s+NOT\s+NULL\s*\)",
        _flat(_trigger("log_team_state_insert")),
    ), "the INSERT trigger lost its WHEN clause and now fires on every teams insert"


def test_both_triggers_call_the_one_trigger_function():
    for trigger in ("log_team_state_update", "log_team_state_insert"):
        assert f"public.{TRIGGER_FUNCTION}()" in _flat(_trigger(trigger))


def test_the_ledger_has_exactly_one_writer():
    """R12 wants one row per write. A second INSERT anywhere doubles the ledger."""
    inserts = _statements(rf"(?is)insert\s+into\s+(?:public\.)?{AUDIT_TABLE}\b")
    assert len(inserts) == 1, f"expected the trigger to be the only ledger writer, found {len(inserts)}"
    assert f"INSERT INTO public.{AUDIT_TABLE}" in _flat(_function(TRIGGER_FUNCTION))


def test_the_trigger_falls_back_to_the_role_name_and_external():
    """Writes that do not come through the write function are still logged (R13)."""
    body = _flat(_function(TRIGGER_FUNCTION))
    assert "COALESCE(NULLIF(current_setting('pitchrank.action', true), ''), 'external')" in body
    assert "COALESCE(NULLIF(current_setting('pitchrank.actor', true), ''), current_user::text)" in body


def test_the_trigger_reads_old_only_on_update():
    """OLD is unassigned in an INSERT trigger and reading a field of it raises. Without
    the TG_OP guard every INSERT into teams fails — starting with the discovery path,
    which has created 66,380 of them — and only in production."""
    body = _flat(_function(TRIGGER_FUNCTION))
    guarded = body[body.index("IF TG_OP = 'UPDATE' THEN") : body.index("END IF;")]
    for read in (
        "v_old_state_code := OLD.state_code;",
        "v_old_source := OLD.state_source;",
        "v_old_confidence := OLD.state_confidence;",
    ):
        assert read in guarded, f"{read} is not inside the TG_OP guard"
    assert "OLD." not in body[body.index("END IF;") :], "OLD is read outside the TG_OP guard"


def test_the_ledger_row_maps_the_prior_values_to_the_old_columns():
    """One NEW.* substituted into an old_* column leaves R17's suppression key
    unmatchable and makes every revert restore the value it meant to undo."""
    body = _flat(_function(TRIGGER_FUNCTION))
    insert = body[body.index(f"INSERT INTO public.{AUDIT_TABLE}") : body.index("RETURN NULL")]
    columns = _split_top_level(_balanced(insert, insert.index("(")))
    values = _split_top_level(_balanced(insert, insert.index("(", insert.index("VALUES"))))
    assert dict(zip(columns, values)) == {
        "team_id_master": "NEW.team_id_master",
        "action": "COALESCE(NULLIF(current_setting('pitchrank.action', true), ''), 'external')",
        "old_state_code": "v_old_state_code",
        "new_state_code": "NEW.state_code",
        "old_source": "v_old_source",
        "new_source": "NEW.state_source",
        "old_confidence": "v_old_confidence",
        "new_confidence": "NEW.state_confidence",
        "applied_by": "COALESCE(NULLIF(current_setting('pitchrank.actor', true), ''), current_user::text)",
        "reason": "NULLIF(current_setting('pitchrank.reason', true), '')",
    }


def test_the_trigger_function_is_not_security_definer():
    """A definer function reports its own owner as the actor for every write that
    arrives without the GUCs set — the population the fallback exists to identify."""
    assert "security definer" not in _header(TRIGGER_FUNCTION).lower()


def test_every_new_function_pins_its_search_path():
    for name in NEW_FUNCTIONS:
        assert "SET search_path = ''" in _header(name), f"{name} resolves names against the caller's path"


# --------------------------------------------------------------------------- #
# The write path
# --------------------------------------------------------------------------- #


def test_the_actor_and_action_are_transaction_local():
    """set_config(..., false) is a session write: invisible to the trigger through a
    pooled connection, and left behind to mis-stamp a later request that reuses it."""
    body = _flat(_function(WRITE_FUNCTION))
    settings = re.findall(r"set_config\('([^']+)',.*?,\s*(true|false)\)", body)
    assert [name for name, _ in settings] == [
        "pitchrank.actor",
        "pitchrank.action",
        "pitchrank.reason",
    ] * 2, "the stamps are set before the write and cleared after it"
    assert {scope for _, scope in settings} == {"true"}
    assert body.index("UPDATE public.teams") < body.rindex("set_config('pitchrank.actor'")


def test_the_write_carries_its_pre_image_as_a_predicate():
    """Without it a decision recorded against one state applies to whatever the other
    weekly writers left behind."""
    body = _flat(_function(WRITE_FUNCTION))
    update = body[body.index("UPDATE public.teams") :]
    where = update[update.index("WHERE") : update.index(";")].strip()
    assert re.fullmatch(
        r"WHERE team_id_master = p_team_id "
        r"AND state_code IS NOT DISTINCT FROM p_expected_state_code::character\(2\)",
        where,
    ), f"the write's WHERE clause changed: {where}"


def test_the_write_stamps_all_three_provenance_columns():
    body = _flat(_function(WRITE_FUNCTION))
    for assignment in (
        "state_code = p_state_code",
        "state_source = p_source",
        "state_confidence = p_confidence",
        "state_assigned_at = now()",
    ):
        assert assignment in body


def test_no_write_path_guards_on_confidence():
    """A confidence guard blocks the restore R15 exists for: an earlier, lower value."""
    for name in (WRITE_FUNCTION, REVERT_FUNCTION):
        assert not re.search(r"confidence\s*[<>]", _flat(_function(name)))


# --------------------------------------------------------------------------- #
# Revert
# --------------------------------------------------------------------------- #


def test_revert_excludes_its_own_rows():
    """R16: otherwise a second date-scoped revert undoes the first one."""
    assert "AND a.action <> 'revert'" in _flat(_function(REVERT_FUNCTION))


def test_revert_restores_the_oldest_row_per_team():
    """R15: a batch that wrote a team twice must return it to its pre-batch state."""
    body = _flat(_function(REVERT_FUNCTION))
    assert "ROW_NUMBER() OVER ( PARTITION BY b.team_id_master ORDER BY b.applied_at, b.id ) AS rn" in body
    assert "WHERE s.rn = 1" in body


def test_revert_is_driven_from_the_caller_in_pages():
    """An RPC gets 8 seconds and cannot extend its own budget, so the walk is the
    caller's: the page takes a cursor and the call returns the next one."""
    header = _header(REVERT_FUNCTION)
    assert "p_after uuid DEFAULT NULL" in header
    assert re.search(r"p_batch_size integer DEFAULT \d+", header), "a NULL default is LIMIT NULL"
    assert "RETURNS TABLE (rows_changed integer, last_team_id uuid)" in _flat(header)

    body = _flat(_function(REVERT_FUNCTION))
    assert "WHERE p_after IS NULL OR b.team_id_master > p_after" in body, (
        "the page ignores its cursor, so the caller rewrites the same rows forever"
    )
    assert "ORDER BY b.team_id_master LIMIT p_batch_size" in body


def test_revert_pages_before_it_windows():
    """Both windows run over one page of ledger rows. Applying the limit after them
    makes every call sort the whole batch, which is the work the 8s budget cannot take
    on a batch large enough to need paging in the first place."""
    body = _flat(_function(REVERT_FUNCTION))
    assert body.index("LIMIT p_batch_size") < body.index("ROW_NUMBER() OVER"), (
        "the page limit is applied after the windowing it exists to bound"
    )
    assert "JOIN page_teams pt ON pt.team_id_master = b.team_id_master" in body


def test_revert_refuses_a_scope_that_would_silently_revert_nothing():
    """Each of these reports success over an empty page rather than failing."""
    body = _flat(_function(REVERT_FUNCTION))
    guard = body[body.index("IF p_applied_by") : body.index("END IF;")]
    for term in (
        "p_applied_by IS NULL",
        "p_applied_after IS NULL",
        "p_applied_before IS NULL",
        "COALESCE(p_reverted_by, '') = ''",
        "COALESCE(p_batch_size, 0) < 1",
    ):
        assert term in guard, f"{term} is not refused"
    assert "RAISE EXCEPTION" in guard


def test_revert_advances_its_cursor_on_every_paged_row():
    """v_last is the page's last id, not the last id changed: a page where nothing
    was written must still carry the walk forward, or the caller stops early."""
    body = _flat(_function(REVERT_FUNCTION))
    assert "LEFT JOIN public.teams t" in body, "an inner join drops vanished teams out of the page"
    assert body.index("v_last := v_row.team_id_master;") < body.index("IF p_dry_run THEN")


def test_revert_writes_through_the_write_function():
    """So the restore is itself logged, and by the same actor/action mechanism."""
    body = _flat(_function(REVERT_FUNCTION))
    assert f"public.{WRITE_FUNCTION}(" in body
    assert "'revert'," in body


def test_revert_skips_a_team_another_writer_has_moved_since():
    """The pre-image is the state the BATCH left, never the team's current state. Passing
    the current state makes the guard match itself, and a revert then overwrites whatever
    the weekly writers did in the meantime with a value the operator never saw."""
    body = _flat(_function(REVERT_FUNCTION))
    assert (
        "LAST_VALUE(b.new_state_code) OVER ( PARTITION BY b.team_id_master "
        "ORDER BY b.applied_at, b.id ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING "
        ") AS batch_state_code"
    ) in body, "LAST_VALUE without that frame returns the batch's first write, not its last"
    assert "v_row.batch_state_code::text," in body
    assert "t.state_code" not in body[body.index("LOOP") :], "the loop reads a live state again"


def test_the_dry_run_counts_what_the_write_would_do():
    """One test, computed once in SQL, so the two branches cannot drift apart."""
    body = _flat(_function(REVERT_FUNCTION))
    assert (
        "(t.team_id_master IS NOT NULL AND t.state_code IS NOT DISTINCT FROM "
        "p.batch_state_code) AS restorable"
    ) in body
    assert "IF v_row.restorable THEN" in body


def test_no_function_tries_to_extend_its_own_timeout():
    """SET LOCAL statement_timeout in a function body is inert — the timer is armed
    once per top-level command. backfill_total_game_stats carries one and is cancelled
    on every production run."""
    for name in NEW_FUNCTIONS:
        assert "statement_timeout" not in _flat(_function(name)).lower()


def test_the_dry_run_writes_nothing():
    body = _flat(_function(REVERT_FUNCTION))
    dry_branch = body[body.index("IF p_dry_run THEN") : body.index("ELSIF")]
    assert "UPDATE" not in dry_branch.upper().replace("UPDATED", "")
    assert WRITE_FUNCTION not in dry_branch


# --------------------------------------------------------------------------- #
# Tables
# --------------------------------------------------------------------------- #


def test_the_ledger_records_the_confidence_it_replaces():
    """R15 names confidence restoration as its hard case, so old_confidence is not
    symmetry — it is the only place the prior value survives."""
    columns = _flat(_table(AUDIT_TABLE))
    for column in ("old_state_code", "new_state_code", "old_source", "new_source",
                   "old_confidence", "new_confidence", "applied_at", "applied_by", "reason"):
        assert column in columns


def test_the_ledger_admits_the_actions_its_readers_key_on():
    """'revert' is R16's exclusion and R17's suppression key; 'external' is every
    write that never reaches the write function, which is most of them."""
    columns = _flat(_table(AUDIT_TABLE))
    action_check = columns[columns.index("action TEXT NOT NULL") :]
    for action in ("'fill'", "'correct'", "'approve'", "'revert'", "'external'"):
        assert action in action_check[: action_check.index(")")]


def test_the_queue_does_not_borrow_the_match_queues_confidence_check():
    """team_match_review_queue constrains confidence to >= 0.75 AND < 0.90, which
    rejects both confidences this queue holds — 0.90 and 0.95."""
    columns = _flat(_table(QUEUE_TABLE))
    assert "0.75" not in columns
    assert "0.90" not in columns
    assert "confidence NUMERIC(3,2) NOT NULL CHECK (confidence >= 0 AND confidence <= 1)" in columns


def test_the_queues_suppression_key_cannot_be_null():
    """A NULL proposed_state_code never matches itself, so a rejected row would be
    re-raised on every sweep and the suppression would be silently defeated."""
    columns = _flat(_table(QUEUE_TABLE))
    assert "proposed_state_code CHAR(2) NOT NULL" in columns


def test_every_new_table_ships_with_rls_and_both_policies():
    """pg_default_acl grants anon arwdDxtm on every new public relation here, which is
    how two earlier audit tables reached the security advisory."""
    tree = "\n".join(_executable(p.read_text(encoding="utf-8")) for p in _migrations())
    for table in NEW_TABLES:
        assert re.search(
            rf"(?is)alter\s+table\s+(?:public\.)?{table}\s+enable\s+row\s+level\s+security", tree
        ), f"{table} ships without RLS"
        deny = _flat(_newest(
            f"{table}_deny_all",
            rf'(?is)create\s+policy\s+"{table}_deny_all"',
            lambda sql, m: sql[m.start() : sql.index(";", m.end()) + 1],
        ))
        assert "TO anon, authenticated USING (false) WITH CHECK (false)" in deny
        allow = _flat(_newest(
            f"{table}_service_role_all",
            rf'(?is)create\s+policy\s+"{table}_service_role_all"',
            lambda sql, m: sql[m.start() : sql.index(";", m.end()) + 1],
        ))
        assert "TO service_role USING (true) WITH CHECK (true)" in allow


def test_every_new_function_is_service_role_only():
    """The default ACL grants EXECUTE to PUBLIC, anon and authenticated. Each statement
    is matched against the signature the function actually declares, because an ACL that
    names a signature nothing has is accepted here and raises 42883 on apply."""
    tree = _flat("\n".join(p.read_text(encoding="utf-8") for p in _migrations()))
    for name in NEW_FUNCTIONS:
        signature = f"public.{name}({_argument_types(name)})"
        assert f"REVOKE EXECUTE ON FUNCTION {signature} FROM PUBLIC, anon, authenticated" in tree, (
            f"{name} is still executable by anon"
        )
        assert f"GRANT EXECUTE ON FUNCTION {signature} TO service_role" in tree, (
            f"{name} is not executable by the role that runs it"
        )
