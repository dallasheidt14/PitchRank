"""Up to ten of a cleanup run's automatic merges, for the owner to mark right or wrong.

When a run closes, its summary email lists a sample of the merges the reviewers cleared and the automatic lane
applied, drawn from those whose card the review page published; a merge the rules settled with no reviewer, or one
undone since, is not in the pool. The sample is drawn
from the run's id, so drawing it again picks the same merges, and team_cleanup_spot_checks holds it once. The owner
marks each right or wrong on the review page, whose count of clean weeks decides when page_caps.merges.auto may
double.
"""

from __future__ import annotations

import html
from pathlib import Path
from random import Random

from postgrest.exceptions import APIError

from scripts.find_cross_provider_duplicates import batched, page
from scripts.team_cleanup.decisions import CHANGES_TABLE, MERGES, TABLE_MISSING
from scripts.team_cleanup.pairs import MERGE, as_chosen, review_choice
from scripts.team_cleanup.run_store import AUTO, LANE_CARDS, MANIFEST_FILE, stage_dir
from src.tournaments.storage._io import read_json

SPOT_CHECKS_TABLE = "team_cleanup_spot_checks"
CARDS_TABLE = "team_cleanup_cards"
SAMPLE_SIZE = 10
SPOT_VERDICTS = ("right", "wrong")
UNIQUE_VIOLATION = "23505"
TEAM_URL = "https://www.pitchrank.io/teams/"
REVIEW_URL = "https://www.pitchrank.io/mission-control/cleanup#spot-check"


def cleared(manifest: dict) -> dict[str, tuple[str, str]]:
    """(retired, kept) of each pair of the automatic lane the reviewers cleared, turned the way they chose, by
    card id."""
    merges = {}
    for card_id, pair in manifest[LANE_CARDS[AUTO]].items():
        if (pair.get("review") or {}).get("verdict") == MERGE:
            chosen = as_chosen({**pair, "swap": review_choice(pair)["swap"]})
            merges[card_id] = (chosen["merge_id"], chosen["keep_id"])
    return merges


def pick(run_id: str, cards: list[str]) -> list[str]:
    return Random(f"spot-check:{run_id}").sample(cards, min(SAMPLE_SIZE, len(cards)))


def held_merges(sb, run_id: str) -> set[tuple[str, str]]:
    """(retired, kept) of each merge the run applied and has not undone."""
    rows = page(
        lambda: (
            sb.table(CHANGES_TABLE)
            .select("team_id_master,new_value")
            .eq("run_id", run_id)
            .eq("stage", MERGES)
            .is_("reverted_at", "null")
        ),
        "id",
    )
    return {(row["team_id_master"], row["new_value"]) for row in rows}


def load_or_pick(sb, store: Path, run_id: str, execute: bool) -> list[str]:
    """The run's sample in its order: the one already filed, else a new draw, filed unless this is a dry run."""
    filed = _filed(sb, run_id)
    if filed:
        return filed
    manifest_path = stage_dir(store, run_id, MERGES) / MANIFEST_FILE
    if not manifest_path.exists():
        return []
    merges = cleared(read_json(manifest_path))
    held = held_merges(sb, run_id) if merges else set()
    candidates = sorted(card for card, merge in merges.items() if merge in held)
    published = published_cards(sb, candidates)
    sample = pick(run_id, [card for card in candidates if card in published])
    if not sample:
        return []
    if not execute:
        print(f"DRY RUN -- would file {len(sample)} automatic merge(s) of run {run_id} for the spot-check")
        return sample
    rows = [{"run_id": run_id, "position": n, "card_id": card} for n, card in enumerate(sample, 1)]
    try:
        sb.table(SPOT_CHECKS_TABLE).insert(rows).execute()
    except APIError as exc:
        if exc.code != UNIQUE_VIOLATION:
            raise
        return _filed(sb, run_id)
    return sample


def _filed(sb, run_id: str) -> list[str]:
    rows = sb.table(SPOT_CHECKS_TABLE).select("position,card_id").eq("run_id", run_id).order("position").execute()
    return [row["card_id"] for row in rows.data]


def published_cards(sb, card_ids: list[str]) -> set[str]:
    found = set()
    for batch in batched(card_ids):
        rows = sb.table(CARDS_TABLE).select("card_id").in_("card_id", batch).execute().data
        found.update(row["card_id"] for row in rows)
    return found


def read_cards(sb, card_ids: list[str]) -> dict[str, dict]:
    cards = {}
    for batch in batched(card_ids):
        rows = sb.table(CARDS_TABLE).select("card_id,card,swap").in_("card_id", batch).execute().data
        cards.update({row["card_id"]: row for row in rows})
    return cards


def _team(side: dict) -> str:
    facts = [side.get("club"), side.get("state"), " ".join(filter(None, (side.get("age"), side.get("gender"))))]
    facts += [side.get("provider")]
    return f"{side['games']} games; " + ", ".join(html.escape(fact) for fact in facts if fact)


def sample_html(card_ids: list[str], cards: dict[str, dict]) -> str:
    """Each merge as the summary email lists it: the kept team linked, the merged team's facts, since its own
    page now opens the kept one, and the reviewers' reason."""
    items = []
    for card_id in card_ids:
        row = cards[card_id]
        card = row["card"]
        kept, merged = (card["merge"], card["keep"]) if row["swap"] else (card["keep"], card["merge"])
        items.append(
            f'<li><a href="{TEAM_URL}{html.escape(kept["team_id"])}">{html.escape(kept["name"] or "(no name)")}</a> '
            f"({_team(kept)}) kept, with {html.escape(merged['name'] or '(no name)')} ({_team(merged)}) merged "
            f"into it.<br>{html.escape(card['why'])}</li>"
        )
    return (
        f"<p>Spot-check: {len(card_ids)} of the automatic merges the reviewers cleared. Mark each right or wrong "
        f'on the <a href="{REVIEW_URL}">review page</a>.</p><ol>{"".join(items)}</ol>'
    )


def sample_section(sb, store: Path, run_id: str, execute: bool) -> str:
    """The summary email's spot-check, empty when the run merged nothing the reviewers cleared. Any other failure
    to read or file it raises, so the summary waits for a tick that can include it."""
    try:
        sample = load_or_pick(sb, store, run_id, execute)
    except APIError as exc:
        if exc.code == TABLE_MISSING:
            return f"<p>No spot-check: {SPOT_CHECKS_TABLE} does not exist yet; apply its migration.</p>"
        raise
    return sample_html(sample, read_cards(sb, sample)) if sample else ""
