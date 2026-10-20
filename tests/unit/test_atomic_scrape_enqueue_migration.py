"""Guard the effective queue transaction; live PostgreSQL concurrency QA is separate."""
import re
from pathlib import Path


def latest_function(name):
    result = None
    for path in sorted((Path(__file__).resolve().parents[2] / "supabase/migrations").glob("*.sql")):
        sql = re.sub(r"/\*.*?\*/|--[^\n]*", "", path.read_text(encoding="utf-8"), flags=re.S)
        matches = list(re.finditer(rf"CREATE (?:OR REPLACE )?FUNCTION (?:public\.)?{name}\s*\([^$]+\$\$(.*?)\$\$;", sql, re.I | re.S))
        if matches:
            result = re.sub(r"\s+", " ", matches[-1][1]).lower()
    assert result, name
    return result


def test_atomic_adoption_is_durable_before_return_and_does_not_replace_source():
    sql = latest_function("enqueue_scrape_request_once")
    lock = sql.index("lock table public.scrape_requests in share row exclusive mode;")
    lookup = sql.index("from public.scrape_request_intents")
    insert = sql.index("insert into public.scrape_requests")
    receipt = sql.index("insert into public.scrape_request_intents")
    assert lock < lookup < insert < receipt < sql.rindex("return next v_row;")
    update = re.search(r"update public.scrape_requests set (.*?) where", sql)[1]
    assert update == "priority = least(priority, p_priority)"
    assert "sr.status in ('pending', 'processing') and coalesce(mm.canonical_team_id, sr.team_id_master) = v_team" in sql
    assert "where i.intent_id = p_intent_id; if found then return next v_row; return;" in sql


def test_shared_rpc_keeps_single_game_coverage_and_rejects_stale_processing_success():
    sql = latest_function("enqueue_scrape_request")
    coverage = re.search(r"if v_row.provider_id (.*?) then", sql)[0]
    assert "or (p_request_type is distinct from 'missing_game' and v_row.game_date > p_game_date)" in coverage
    assert "or p_game_date not between v_row.game_date - 90 and v_row.game_date + 90" in coverage
    stale = re.search(r"if v_row.status = 'processing'(.*?)end if;", sql)[0]
    assert "and v_row.processed_at < now() - interval '24 hours'" in stale
    assert "raise exception" in stale and "errcode = '55000'" in stale
    assert sql.index(stale) < sql.index("return v_row.id;")
