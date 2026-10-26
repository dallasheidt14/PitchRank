"""A duplicate pair as the owner's review pages show and collect it: each row's side of the card, the
swap that flips which row survives, the checks a page's chosen merges must pass before any is
applied, and the Keep separate rows its choices record."""

from __future__ import annotations

from collections import Counter

from scripts.team_cleanup.decisions import keep_separate_row, page_built_at
from scripts.team_cleanup.review_page import team_block
from scripts.team_cleanup.vetted import KEEP_AS_VETTED, MERGE_AS_VETTED

SWAPPED = {
    "merge_id": "keep_id",
    "keep_id": "merge_id",
    "merge_name": "keep_name",
    "keep_name": "merge_name",
    MERGE_AS_VETTED: KEEP_AS_VETTED,
    KEEP_AS_VETTED: MERGE_AS_VETTED,
}


def swapped(pair: dict) -> dict:
    """The pair with the other row surviving."""
    return {SWAPPED.get(key, key): value for key, value in pair.items()}


def as_chosen(pair: dict) -> dict:
    """The pair the way round the owner chose: swapped where the card says so."""
    return swapped(pair) if pair.get("swap") else pair


def side(tid, teams, ev, providers) -> dict:
    return {"team_id": tid, **team_block(teams[tid], ev, providers)}


def refuse_conflicts(merges: list[dict]) -> None:
    """A team merged into two survivors, or merged away while also a survivor, makes the applier
    drop or chain those merges, so the owner's cluster decision would not land as chosen."""
    retired = Counter(m["merge_id"] for m in merges)
    clash = [m for m in merges if retired[m["merge_id"]] > 1 or m["keep_id"] in retired]
    if clash:
        lines = "\n".join(f"  {m['merge_name']} -> {m['keep_name']}" for m in clash)
        raise SystemExit(f"these merges disagree about which team survives; settle the cluster on the page:\n{lines}")


def refuse_kept_apart_joins(merges: list[dict], separate: list[dict]) -> None:
    """Two merges into one survivor can join a pair the same page keeps separate, and the applier
    cannot refuse that until the page's Keep separate choices are recorded."""
    group: dict[str, str] = {}

    def root(team_id: str) -> str:
        while group.get(team_id, team_id) != team_id:
            team_id = group[team_id]
        return team_id

    for m in merges:
        group[root(m["merge_id"])] = root(m["keep_id"])
    joined = [p for p in separate if root(p["merge_id"]) == root(p["keep_id"])]
    if joined:
        lines = "\n".join(f"  {p['merge_name']} / {p['keep_name']}" for p in joined)
        raise SystemExit(f"these merges would join teams the page keeps separate; settle them on the page:\n{lines}")


def page_keep_separate_rows(manifest: dict, result: dict) -> list[dict]:
    """A page's documents carry no trustworthy time of their own, so a decision is dated by the
    page's build."""
    decided_at, source = page_built_at(manifest), f"page:{manifest['run']}"
    rows = []
    for pair_id in result["by_decision"]["separate"]:
        pair, note = manifest["pairs"][pair_id], (result["notes"].get(pair_id) or "").strip()
        rows.append(keep_separate_row(pair["merge_id"], pair["keep_id"], note, decided_at, source))
    return rows
