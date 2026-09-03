"""The operator-side stopgap that keeps a snapshot from replaying the tool's own writes.

Drives ``split`` directly: what is under test is which applies are held and why, not the
Supabase read that supplies the provenance.
"""

import json
import os
import sys

import pytest

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from scripts.hold_unsafe_state_applies import split  # noqa: E402


def apply(team_id, club, pre, proposed, tier="B"):
    return {
        "team_id": team_id, "team_name": team_id, "club_name": club, "pre_image": pre,
        "proposed": proposed, "tier": tier, "confidence": 0.9, "action": "apply", "reason": "",
    }


def test_a_lower_tier_overwriting_a_value_with_provenance_is_held():
    decisions = [apply("a", "Club FC", "WA", "NV"), apply("b", "Club FC", "WA", "NV")]
    kept, held = split(decisions, {"a": "tier_a", "b": None})

    assert [d["team_id"] for d in kept] == ["b"]
    assert [d["team_id"] for d in held] == ["a"]
    assert "tier_a" in held[0]["held_because"]


def test_tier_a_may_overwrite_its_own_record_but_not_an_operators():
    decisions = [apply("a", "Club FC", "WA", "NV", tier="A"), apply("b", "Club FC", "WA", "NV", tier="A")]
    kept, held = split(decisions, {"a": "tier_a", "b": "operator"})

    assert [d["team_id"] for d in kept] == ["a"]
    assert [d["team_id"] for d in held] == ["b"] and "operator" in held[0]["held_because"]


def test_a_club_sent_to_two_states_in_one_run_is_held_whole():
    """The two-and-two swap: excluding the team being decided leaves the other pair as the
    only meaningful state, so both pairs are told to become the other."""
    decisions = [
        apply("ca1", "RSL-AZ Yuma", "CA", "TX"), apply("ca2", "RSL-AZ Yuma", "CA", "TX"),
        apply("tx1", "RSL-AZ Yuma", "TX", "CA"), apply("tx2", "RSL-AZ Yuma", "TX", "CA"),
        apply("ok", "Steady FC", "WA", "NV"),
        # A fill on the steady club proposing a third state is not a second target: only
        # corrections can swap, so the club's one real correction still passes.
        apply("fill", "Steady FC", None, "OR"),
    ]
    kept, held = split(decisions, {})

    assert [d["team_id"] for d in kept] == ["ok", "fill"]
    assert sorted(d["team_id"] for d in held) == ["ca1", "ca2", "tx1", "tx2"]
    assert all("IMP-161" in d["held_because"] for d in held)


def test_the_script_takes_its_credentials_and_readers_from_the_tool():
    """Importing the tool is what loads root ``.env``, and its provenance reader is the
    one the apply itself uses."""
    import scripts.assign_team_states as assign
    import scripts.hold_unsafe_state_applies as hold

    assert hold.fetch_state_sources is assign.fetch_state_sources
    assert hold.club_key is assign.club_key


def test_queue_rows_and_confirms_pass_through_untouched():
    queue = {**apply("q", "Club FC", "WA", "NV"), "action": "queue"}
    confirm = {**apply("c", "Club FC", "WA", "WA", tier="A"), "action": "confirm"}
    kept, held = split([queue, confirm], {"q": "tier_a", "c": "tier_b"})

    assert kept == [queue, confirm] and held == []


def test_main_splits_a_snapshot_file_and_refuses_without_credentials(tmp_path, monkeypatch, capsys):
    """The entry point end to end: credentials checked before anything is read, the
    provenance read scoped to the applies, both files written, the summary counted."""
    import scripts.hold_unsafe_state_applies as hold

    snapshot = {
        "created_at": "2026-09-02T00:00:00+00:00",
        "decisions": [
            apply("safe", "Club FC", "WA", "NV"),
            apply("held", "Club FC", "WA", "NV"),
            {**apply("q", "Club FC", "WA", "NV"), "action": "queue"},
        ],
    }
    src = tmp_path / "in.json"
    src.write_text(json.dumps(snapshot), encoding="utf-8")
    asked = []
    monkeypatch.setattr(hold, "SUPABASE_URL", "https://example.test")
    monkeypatch.setattr(hold, "SUPABASE_KEY", "key")
    monkeypatch.setattr(hold, "create_client", lambda url, key: "client")
    monkeypatch.setattr(
        hold, "fetch_state_sources", lambda sb, ids: asked.append(sorted(ids)) or {"held": "tier_a"}
    )
    monkeypatch.setattr(sys, "argv", ["hold", str(src), str(tmp_path / "safe.json"), str(tmp_path / "held.json")])
    hold.main()

    assert asked == [["held", "safe"]]
    safe = json.loads((tmp_path / "safe.json").read_text(encoding="utf-8"))
    assert [d["team_id"] for d in safe["decisions"]] == ["safe", "q"]
    assert [d["team_id"] for d in json.loads((tmp_path / "held.json").read_text(encoding="utf-8"))] == ["held"]
    assert "kept 1 applies, 1 queue rows and 0 confirms" in capsys.readouterr().out

    monkeypatch.setattr(hold, "SUPABASE_URL", None)
    with pytest.raises(SystemExit) as exc:
        hold.main()
    assert exc.value.code == 1
    assert "Missing SUPABASE_URL" in capsys.readouterr().out
