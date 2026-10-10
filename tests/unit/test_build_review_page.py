"""Tests for the merging-duplicate-teams review page: the builder and the choice collector.

The page's saved choices feed a destructive merge, so these pin the three things that decide
what gets merged: which row each card calls the survivor, that a choice contributes only its
decision and swap while team ids come from the builder's manifest, and that nothing a provider
typed into a team name can break out of the page's script.

The page's own save logic runs only in a browser and is not tested here: Playwright is not a
dependency of this repo.
"""

import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT))

from tests.unit.test_find_cross_provider_duplicates import _Supabase  # noqa: E402
from tests.unit.test_team_cleanup_carry_forward import _Writable  # noqa: E402

SKILL = ROOT / ".claude" / "skills" / "merging-duplicate-teams"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, SKILL / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


brp = _load("build_review_page")
crd = _load("collect_review_decisions")

RUN = "20260924T000000Z-abc123"
A = "aaaaaaaa-0000-4000-8000-000000000001"
B = "bbbbbbbb-0000-4000-8000-000000000002"
C = "aaaaaaaa-0000-4000-8000-000000000003"
OLD = "cccccccc-0000-4000-8000-000000000004"


def team(tid, name, *, age="u12", gender="Male", deprecated=False, provider="prov-gs"):
    return {
        "team_id_master": tid, "team_name": name, "team_name_original": None, "club_name": "Colorado EDGE",
        "age_group": age, "gender": gender, "state_code": "CO", "provider_id": provider, "is_deprecated": deprecated,
    }


def vetted(age="u12", gender="Male", state="CO", club="Colorado EDGE"):
    return {"age_group": age, "gender": gender, "state_code": state, "club_name": club}


def game(gid, home, away, date, *, is_excluded=False):
    return {"id": gid, "home_team_master_id": home, "away_team_master_id": away,
            "game_date": date, "is_excluded": is_excluded}


def evidence(games=(), merge_map=None, tracked=(A, B, C)):
    canonical = brp.resolver(merge_map or {})
    return canonical, brp.build_evidence(list(games), [], canonical, list(tracked))


def pair(merge_id, keep_id, status="held", reason=""):
    return {"merge_id": merge_id, "keep_id": keep_id, "status": status, "reason": reason}


def records_for(pairs, teams, games=(), merge_map=None):
    tracked = sorted({t for p in pairs for t in (p["merge_id"], p["keep_id"])})
    canonical, ev = evidence(games, merge_map, tracked=tracked)
    return brp.build_records(pairs, teams, canonical, ev, {"prov-gs": "gotsport"}, RUN)


# --- input ---------------------------------------------------------------------------------


def test_the_squad_key_shape_passes_through():
    assert brp.normalise(pair(A, B, "rejected", "leagues differ")) == pair(A, B, "rejected", "leagues differ")


@pytest.mark.parametrize(
    "record, status",
    [
        ({"tier": brp.REJECTED_TIER, "rejected_reason": "same day"}, "rejected"),
        ({"tier": "2_both_have_games"}, "proposed"),
        ({}, "held"),
    ],
)
def test_each_record_shape_gets_its_status(record, status):
    got = brp.normalise({"merge_id": A, "keep_id": B, **record})
    assert got["status"] == status
    assert got["reason"] == record.get("rejected_reason", "")


def test_an_unknown_status_is_refused():
    with pytest.raises(SystemExit):
        brp.normalise(pair(A, B, "<b>maybe</b>"))


# --- records -------------------------------------------------------------------------------


def test_the_first_row_is_merged_away_and_the_second_stays():
    teams = {A: team(A, "U12B Grey"), B: team(B, "Skyline 15B Grey")}
    records, _ = records_for([pair(A, B, reason="two providers")], teams)
    assert [r["team_id"] for r in records[0]["rows"]] == [A, B]
    assert records[0]["reason"] == "two providers"
    assert re.fullmatch(rf"{RUN}_[0-9a-f]{{16}}", records[0]["id"])


def test_distinct_pairs_get_distinct_ids():
    teams = {A: team(A, "Gold"), B: team(B, "Gold 2"), C: team(C, "Gold 3")}
    records, _ = records_for([pair(A, B), pair(C, B)], teams)
    assert len({r["id"] for r in records}) == 2


@pytest.mark.parametrize("gone_side", [0, 1])
@pytest.mark.parametrize("how", ["missing", "deprecated", "merged but live"])
def test_a_pair_whose_row_is_gone_in_effect_is_left_out(gone_side, how):
    gone = (A, B)[gone_side]
    teams = {A: team(A, "Gold"), B: team(B, "Gold 2")}
    merge_map = {}
    if how == "missing":
        del teams[gone]
    elif how == "deprecated":
        teams[gone] = team(gone, "Gone", deprecated=True)
    else:
        merge_map = {gone: OLD}
    records, skipped = records_for([pair(A, B)], teams, merge_map=merge_map)
    assert records == [] and len(skipped) == 1 and gone in skipped[0]


def test_the_two_directions_of_one_pair_get_different_ids():
    teams = {A: team(A, "Gold"), B: team(B, "Gold 2")}
    forward, _ = records_for([pair(A, B)], teams)
    backward, _ = records_for([pair(B, A)], teams)
    assert forward[0]["id"] != backward[0]["id"]


def test_a_pair_listed_twice_in_either_direction_appears_once():
    records, skipped = records_for([pair(A, B), pair(B, A)], {A: team(A, "Gold"), B: team(B, "Gold 2")})
    assert len(records) == 1 and skipped == [f"{B} -> {A}: listed more than once"]


def test_cards_run_held_then_rejected_then_proposed_and_are_numbered_after_sorting():
    ids = [f"{i:08x}-0000-4000-8000-00000000000{i}" for i in range(1, 7)]
    teams = {t: team(t, f"Team {n}") for n, t in enumerate(ids)}
    pairs = [pair(ids[0], ids[1], "proposed"), pair(ids[2], ids[3], "rejected"), pair(ids[4], ids[5], "held")]
    records, _ = records_for(pairs, teams)
    assert [(r["n"], r["status"]) for r in records] == [(1, "held"), (2, "rejected"), (3, "proposed")]


def test_game_facts_follow_merges_and_keep_excluded_games_apart():
    games = [
        game("g1", OLD, "o1", "2026-03-01"),           # held under a row merged into B
        game("g2", B, "o2", "2026-09-10"),
        game("g3", B, "o3", "2026-05-01", is_excluded=True),
    ]
    records, _ = records_for([pair(A, B)], {A: team(A, "Gold"), B: team(B, "Gold 2")}, games, {OLD: B})
    merge, keep = records[0]["rows"]
    assert (keep["games"], keep["excluded"], keep["first"], keep["last"]) == (2, 1, "2026-03-01", "2026-09-10")
    assert (merge["games"], merge["first"]) == (0, None)


# --- page ----------------------------------------------------------------------------------


def _embedded(page):
    return page.split("const PAIRS = ", 1)[1].split(";\n", 1)[0]


def test_no_provider_name_can_open_or_close_a_tag_inside_the_script():
    rows = [{"team_id": A, "name": "x</script><b>y"}, {"team_id": B, "name": "<!--<script>"}]
    records = [{"id": f"{RUN}_{A}_{B}", "n": 1, "status": "held", "reason": "", "rows": rows}]
    page = brp.render(records, "Review", RUN)
    data = _embedded(page)
    assert "<" not in data
    assert json.loads(data) == records
    assert page.count("</script>") == 1


def test_the_title_is_escaped_and_never_read_as_a_placeholder():
    page = brp.render([], "A <b>& __DATA__", RUN)
    assert "<title>A &lt;b&gt;&amp; __DATA__</title>" in page
    assert page.count("const PAIRS = ") == 1
    assert not re.search(r"__(TITLE|RUN)__", page)


def test_the_page_keeps_each_run_s_choices_in_its_own_collection():
    assert f'const COLLECTION = "decisions-{RUN}";' in brp.render([], "Review", RUN)


def test_the_page_never_saves_a_team_id():
    template = brp.TEMPLATE.read_text(encoding="utf-8")
    writer = template[template.index("async function write"):template.index("buildPage();")]
    assert "merge_id" not in writer and "keep_id" not in writer and "team_id" not in writer


def test_the_page_writes_the_fields_the_collector_reads():
    template = brp.TEMPLATE.read_text(encoding="utf-8")
    assert "{decision: null, swap: false, note: \"\"," in template
    assert "save(p.id, {decision:" in template and "save(p.id, {swap:" in template and "save(p.id, {note:" in template


def test_the_manifest_records_each_pair_s_direction_and_both_teams_as_shown():
    rows = [{"team_id": A, "name": "Gone"}, {"team_id": B, "name": "Stays"}]
    teams = {A: team(A, "Gone", age="u13"), B: {**team(B, "Stays"), "state_code": "WY", "club_name": "Edge"}}
    m = brp.manifest([{"id": f"{RUN}_{A}_{B}", "rows": rows}], teams, "Review", RUN)
    assert m["pairs"] == {f"{RUN}_{A}_{B}": {
        "merge_id": A, "keep_id": B, "merge_name": "Gone", "keep_name": "Stays",
        "merge_as_vetted": vetted(age="u13"), "keep_as_vetted": vetted(state="WY", club="Edge"),
    }}


def test_main_writes_the_page_and_its_manifest_from_the_database(tmp_path, monkeypatch):
    db = _Supabase({
        "providers": [{"id": "prov-gs", "code": "gotsport"}],
        "teams": [team(A, "U12B Grey"), team(B, "Skyline 15B Grey")],
        "games": [game("g1", OLD, "o1", "2026-03-01"), game("g2", A, "o2", "2026-09-10")],
        "team_merge_map": [{"id": "m1", "deprecated_team_id": OLD, "canonical_team_id": B}],
    }, cap=1000)
    monkeypatch.setattr(brp, "get_client", lambda: db)
    pairs = tmp_path / "pairs.json"
    pairs.write_text(json.dumps([pair(A, B, reason="two providers")]))
    out = tmp_path / "review.html"
    monkeypatch.setattr(sys, "argv", ["prog", "--pairs", str(pairs), "--title", "Review", "--out", str(out)])
    assert brp.main() == 0
    records = json.loads(_embedded(out.read_text(encoding="utf-8")))
    assert [(r["team_id"], r["games"]) for r in records[0]["rows"]] == [(A, 1), (B, 1)]
    assert records[0]["reason"] == "two providers"
    manifest = json.loads((tmp_path / "review.html.manifest.json").read_text())
    assert list(manifest["pairs"]) == [records[0]["id"]] and records[0]["id"].startswith(manifest["run"] + "_")
    assert manifest["pairs"][records[0]["id"]]["keep_id"] == B
    assert manifest["pairs"][records[0]["id"]]["keep_as_vetted"] == vetted()


# --- collecting the owner's choices --------------------------------------------------------


P1, P2, P3 = (f"{RUN}_{digit * 16}" for digit in "123")


def _manifest():
    return {"run": RUN, "pairs": {
        P1: {"merge_id": A, "keep_id": B, "merge_name": "A", "keep_name": "B"},
        P2: {"merge_id": C, "keep_id": B, "merge_name": "C", "keep_name": "B"},
        P3: {"merge_id": OLD, "keep_id": B, "merge_name": "Old", "keep_name": "B"},
    }}


@pytest.mark.parametrize("swap, expected", [(False, (A, B, "A", "B")), (True, (B, A, "B", "A"))])
def test_a_merge_takes_its_direction_from_the_manifest_and_the_swap(swap, expected):
    result = crd.collect(_manifest(), {P1: {"decision": "merge", "swap": swap}})
    assert [(m["merge_id"], m["keep_id"], m["merge_name"], m["keep_name"]) for m in result["merges"]] == [expected]


def test_merges_sharing_one_survivor_are_kept():
    result = crd.collect(_manifest(), {P1: {"decision": "merge"}, P2: {"decision": "merge"}})
    assert [(m["merge_id"], m["keep_id"]) for m in result["merges"]] == [(A, B), (C, B)]


@pytest.mark.parametrize("choices", [
    {P1: {"decision": "merge", "swap": True}, P2: {"decision": "merge", "swap": True}},  # B into A and into C
    {P1: {"decision": "merge"}, P2: {"decision": "merge", "swap": True}},  # A into B, B into C
])
def test_merges_that_disagree_about_the_survivor_fail_the_run(choices):
    with pytest.raises(SystemExit, match="disagree"):
        crd.collect(_manifest(), choices)


def test_a_swap_carries_each_team_s_vetted_values_with_it():
    manifest = _manifest()
    manifest["pairs"][P1].update(merge_as_vetted=vetted(age="u13"), keep_as_vetted=vetted(age="u12"))
    [merge] = crd.collect(manifest, {P1: {"decision": "merge", "swap": True}})["merges"]
    assert (merge["merge_id"], merge["merge_as_vetted"]) == (B, vetted(age="u12"))
    assert (merge["keep_id"], merge["keep_as_vetted"]) == (A, vetted(age="u13"))


def test_ids_written_into_a_saved_choice_are_ignored():
    planted = {"decision": "merge", "merge_id": "attacker-1", "keep_id": "attacker-2"}
    assert crd.collect(_manifest(), {P1: planted})["merges"] == [
        {"merge_id": A, "keep_id": B, "merge_name": "A", "keep_name": "B"}
    ]


@pytest.mark.parametrize("pair_id", ["ghost", f"20250101T000000Z-000000_{'1' * 16}"])
def test_a_choice_for_a_pair_not_on_this_page_fails_the_run(pair_id):
    with pytest.raises(SystemExit):
        crd.collect(_manifest(), {P1: {"decision": "merge"}, pair_id: {"decision": "merge"}})


@pytest.mark.parametrize("bad", [{"decision": "unmerge"}, {"decision": "Merge"}, {"decision": "merge", "swap": []},
                                 {"decision": "merge", "swap": "true"}, {"decision": "separate", "note": 5},
                                 {"decision": "separate", "note": "different" + chr(0) + "squad"}])
def test_a_decision_or_swap_the_page_never_writes_fails_the_run(bad):
    with pytest.raises(SystemExit):
        crd.collect(_manifest(), {P1: bad})


def test_no_choices_at_all_fails_the_run():
    with pytest.raises(SystemExit):
        crd.collect(_manifest(), {})


def test_only_merges_reach_the_list_and_everything_else_is_accounted_for():
    result = crd.collect(_manifest(), {P1: {"decision": "separate", "note": "different squad"},
                                       P2: {"decision": None, "swap": True},
                                       P3: {"decision": "unsure"}})
    assert result["merges"] == []
    assert result["by_decision"] == {"merge": [], "separate": [P1], "unsure": [P3], "undecided": [P2]}
    assert result["notes"] == {P1: "different squad"}


def test_a_note_on_a_merged_pair_is_reported():
    result = crd.collect(_manifest(), {P1: {"decision": "merge", "note": "club is in Texas"}})
    assert result["notes"] == {P1: "club is in Texas"} and len(result["merges"]) == 1


def test_choices_load_from_a_listing(tmp_path):
    listing = tmp_path / "choices.json"
    docs = [{"id": P1, "data": {"decision": "merge"}}, {"id": P2, "data": {"decision": "unsure"}}]
    listing.write_text(json.dumps(docs))
    assert crd.load_choices(listing, RUN) == {P1: {"decision": "merge"}, P2: {"decision": "unsure"}}


def test_a_listing_with_a_duplicate_id_fails(tmp_path):
    listing = tmp_path / "choices.json"
    docs = [{"id": P1, "data": {"decision": "separate"}}, {"id": P1, "data": {"decision": "merge"}}]
    listing.write_text(json.dumps(docs))
    with pytest.raises(SystemExit):
        crd.load_choices(listing, RUN)


def _saved(folder, doc_id, content):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{doc_id}.json").write_text(json.dumps(content))


@pytest.mark.parametrize("nested", [True, False])
def test_choices_load_from_the_out_dir_or_its_run_folder(tmp_path, nested):
    folder = tmp_path / f"decisions-{RUN}" if nested else tmp_path
    _saved(folder, P1, {"id": P1, "data": {"decision": "merge"}})
    _saved(folder, P2, {"decision": "unsure"})
    assert crd.load_choices(tmp_path, RUN) == {P1: {"decision": "merge"}, P2: {"decision": "unsure"}}


def test_a_saved_file_claiming_another_pair_s_id_fails(tmp_path):
    _saved(tmp_path, P1, {"decision": "separate"})
    _saved(tmp_path, "zz-unknown", {"id": P1, "data": {"decision": "merge"}})
    with pytest.raises(SystemExit):
        crd.load_choices(tmp_path, RUN)


def test_a_page_built_before_manifests_recorded_values_still_writes_its_merges(tmp_path, monkeypatch):
    manifest = tmp_path / "m.json"
    manifest.write_text(json.dumps(_manifest()))
    _saved(tmp_path / "out" / f"decisions-{RUN}", P1, {"id": P1, "data": {"decision": "merge"}})
    out = tmp_path / "vetted.json"
    argv = ["prog", "--manifest", str(manifest), "--decisions", str(tmp_path / "out"), "--out", str(out)]
    monkeypatch.setattr(sys, "argv", argv)
    assert crd.main() == 0
    assert json.loads(out.read_text()) == [{"merge_id": A, "keep_id": B, "merge_name": "A", "keep_name": "B"}]


# --- recording Keep separate ---------------------------------------------------------------


def _run_collector(tmp_path, monkeypatch, choices, *flags, db=None, service_key="service-role", manifest=None):
    manifest_path = tmp_path / "m.json"
    manifest_path.write_text(json.dumps(manifest or _manifest()))
    folder = tmp_path / "out" / f"decisions-{RUN}"
    for pair_id, data in choices.items():
        _saved(folder, pair_id, {"id": pair_id, "data": data})

    def client():
        if db is None:
            raise AssertionError("a dry run must not open the database")
        return db

    monkeypatch.setattr(crd, "get_client", client)
    if service_key:
        monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", service_key)
    else:
        monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    out = tmp_path / "vetted.json"
    argv = ["prog", "--manifest", str(manifest_path), "--decisions", str(tmp_path / "out"), "--out", str(out), *flags]
    monkeypatch.setattr(sys, "argv", argv)
    return crd.main()


CHOICES = {P1: {"decision": "separate", "note": " different squad "}, P2: {"decision": "merge"},
           P3: {"decision": "unsure"}}


@pytest.mark.parametrize("flags", [(), ("--execute", "--dry-run")])
def test_a_dry_run_records_nothing(tmp_path, monkeypatch, capsys, flags):
    assert _run_collector(tmp_path, monkeypatch, CHOICES, *flags) == 0
    assert "DRY RUN -- 1 Keep separate choice(s) not recorded" in capsys.readouterr().out


def test_execute_records_each_keep_separate_and_nothing_else(tmp_path, monkeypatch, capsys):
    db = _Writable({"team_cleanup_decisions": []})
    assert _run_collector(tmp_path, monkeypatch, CHOICES, "--execute", db=db) == 0
    assert db.inserted == [("team_cleanup_decisions", [{
        "stage": "merges", "subject_key": f"{A}|{B}", "team_id_master": A, "other_team_id": B,
        "decision": "keep_separate", "note": "different squad", "decided_at": "2026-09-24T00:00:00+00:00",
        "source": f"page:{RUN}",
    }])]
    assert (f"Undo: UPDATE team_cleanup_decisions SET superseded_at = now() WHERE source = 'page:{RUN}' "
            "AND superseded_at IS NULL;") in capsys.readouterr().out


def test_execute_leaves_a_pair_that_already_holds_a_decision(tmp_path, monkeypatch):
    standing = {"id": "d1", "stage": "merges", "subject_key": f"{A}|{B}", "superseded_at": None}
    db = _Writable({"team_cleanup_decisions": [standing]})
    assert _run_collector(tmp_path, monkeypatch, CHOICES, "--execute", db=db) == 0
    assert db.inserted == []


def test_execute_records_over_a_superseded_decision(tmp_path, monkeypatch):
    retired = {"id": "d1", "stage": "merges", "subject_key": f"{A}|{B}", "superseded_at": "2026-10-01T00:00:00+00:00"}
    db = _Writable({"team_cleanup_decisions": [retired]})
    assert _run_collector(tmp_path, monkeypatch, CHOICES, "--execute", db=db) == 0
    assert [row["subject_key"] for _, rows in db.inserted for row in rows] == [f"{A}|{B}"]


def test_execute_refuses_until_the_table_exists(tmp_path, monkeypatch):
    with pytest.raises(SystemExit, match="Apply the team_cleanup_decisions migration"):
        _run_collector(tmp_path, monkeypatch, CHOICES, "--execute", db=_Writable({}))


def test_execute_needs_the_service_role_key(tmp_path, monkeypatch):
    db = _Writable({"team_cleanup_decisions": []})
    with pytest.raises(SystemExit, match="SUPABASE_SERVICE_ROLE_KEY"):
        _run_collector(tmp_path, monkeypatch, CHOICES, "--execute", db=db, service_key=None)


def test_merges_from_a_page_that_recorded_no_team_values_are_flagged(tmp_path, monkeypatch, capsys):
    assert _run_collector(tmp_path, monkeypatch, {P2: {"decision": "merge"}}) == 0
    assert "1 merge(s) carry no record of the teams as the page showed them" in capsys.readouterr().out


def test_a_merge_from_a_page_that_recorded_its_teams_carries_them_into_the_list(tmp_path, monkeypatch, capsys):
    manifest = _manifest()
    manifest["pairs"][P2].update(merge_as_vetted=vetted(age="u13"), keep_as_vetted=vetted())
    assert _run_collector(tmp_path, monkeypatch, {P2: {"decision": "merge"}}, manifest=manifest) == 0
    [merge] = json.loads((tmp_path / "vetted.json").read_text())
    assert (merge["merge_as_vetted"], merge["keep_as_vetted"]) == (vetted(age="u13"), vetted())
    assert "carry no record" not in capsys.readouterr().out


def test_execute_with_no_keep_separate_choice_opens_no_database(tmp_path, monkeypatch):
    assert _run_collector(tmp_path, monkeypatch, {P2: {"decision": "merge"}}, "--execute") == 0


def _triangle():
    """One page pairing A with C, B with C, and A with B, so merging both into C would join A and B."""
    return {"run": RUN, "pairs": {
        P1: {"merge_id": A, "keep_id": C, "merge_name": "A", "keep_name": "C"},
        P2: {"merge_id": B, "keep_id": C, "merge_name": "B", "keep_name": "C"},
        P3: {"merge_id": A, "keep_id": B, "merge_name": "A", "keep_name": "B"},
    }}


def test_merges_that_would_join_a_pair_the_page_keeps_separate_fail_the_run():
    choices = {P1: {"decision": "merge"}, P2: {"decision": "merge"}, P3: {"decision": "separate"}}
    with pytest.raises(SystemExit, match="would join teams the page keeps separate"):
        crd.collect(_triangle(), choices)


def test_a_page_keeping_apart_two_teams_that_only_one_merge_touches_passes():
    choices = {P1: {"decision": "merge"}, P2: {"decision": "unsure"}, P3: {"decision": "separate"}}
    assert [(m["merge_id"], m["keep_id"]) for m in crd.collect(_triangle(), choices)["merges"]] == [(A, C)]


def test_a_page_whose_merges_are_refused_still_records_its_keep_separate_choices(tmp_path, monkeypatch):
    db = _Writable({"team_cleanup_decisions": []})
    choices = {P1: {"decision": "merge", "swap": True}, P2: {"decision": "merge", "swap": True},
               P3: {"decision": "separate"}}
    with pytest.raises(SystemExit, match="disagree about which team survives"):
        _run_collector(tmp_path, monkeypatch, choices, "--execute", db=db)
    assert [row["subject_key"] for _, rows in db.inserted for row in rows] == ["|".join(sorted((OLD, B)))]
    assert not (tmp_path / "vetted.json").exists()


def test_a_note_is_printed_escaped(tmp_path, monkeypatch, capsys):
    hidden = chr(27) + "[1A" + chr(27) + "[2K"
    assert _run_collector(tmp_path, monkeypatch, {P1: {"decision": "separate", "note": hidden + "fine"}}) == 0
    out = capsys.readouterr().out
    assert chr(27) not in out and repr(hidden + "fine") in out
