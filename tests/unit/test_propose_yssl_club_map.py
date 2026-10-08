"""Unit tests for the one-time YSSL club map proposal."""

from pathlib import Path

from scripts import propose_yssl_club_map as p

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "yssl"


def test_reads_club_names_from_the_club_list():
    clubs = p.club_names((FIXTURES / "clublinks.html").read_text(encoding="utf-8"))
    assert len(clubs) == 136
    assert clubs[0] == ("AAC", "AAC EAGLES CHICAGO")


def test_exact_after_normalizing_is_auto_decided():
    rows = p.propose_rows(
        [("WZD", "WCOB FC"), ("BRB", "BERBER CITY FC")], ["Wcob FC", "Berber City FC", "Eclipse Select Soccer Club"]
    )
    assert [(r["yssl_code"], r["pitchrank_club_name"], r["decided_by"]) for r in rows] == [
        ("BRB", "Berber City FC", "auto-exact"),
        ("WZD", "Wcob FC", "auto-exact"),
    ]


def test_anything_else_is_left_undecided_with_candidates():
    rows = p.propose_rows([("ECL", "ECLIPSE")], ["Eclipse Select Soccer Club", "Pegasus FC"])
    assert (rows[0]["pitchrank_club_name"], rows[0]["decided_by"]) == ("", "")
    assert rows[0]["note"] == "candidates: Eclipse Select Soccer Club"


def test_a_prefix_is_never_auto_decided():
    rows = p.propose_rows([("RSN", "RUSH NORTH")], ["Chicago Rush North Shore", "Chicago Rush Soccer Club"])
    assert rows[0]["decided_by"] == ""
