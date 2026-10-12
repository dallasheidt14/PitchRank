"""What the team-cleanup review pages share: reading the teams their cards show, rendering a page
template with the cards in its script, and reading back the choices the owner saved.

A page saves each choice to its own `decisions-<run>` collection, which the ArtifactData tool reads
back either into a folder (`out_dir`, holding `decisions-<run>/<doc id>.json`) or as a JSON list
of `{"id": ..., "data": {...}}` documents. A document holds the owner's choice only: the ids it
decides come from the page's manifest.
"""

from __future__ import annotations

import hashlib
import html
import json
import re
from pathlib import Path

from scripts.find_cross_provider_duplicates import batched

TEAM_COLS = (
    "team_id_master,team_name,team_name_original,club_name,age_group,gender,state_code,provider_id,is_deprecated"
)
_PLACEHOLDER = re.compile("__TITLE__|__DATA__|__RUN__")


def fetch_teams(sb, ids) -> dict[str, dict]:
    teams = {}
    for batch in batched(ids):
        for t in sb.table("teams").select(TEAM_COLS).in_("team_id_master", batch).execute().data:
            teams[t["team_id_master"]] = t
    return teams


def card_id(run: str, key: str) -> str:
    """The run keeps a choice saved on another build from being read as this one's, and a short
    hash keeps the file a choice is saved to inside Windows' path limit."""
    return f"{run}_{hashlib.sha256(key.encode()).hexdigest()[:16]}"


def render(template: Path, records, title: str, run: str) -> str:
    # Every `<` is escaped so no provider-typed name can open or close a tag inside the script,
    # and all placeholders fill in one pass so a filled value is never read as a placeholder.
    values = {
        "__TITLE__": html.escape(title),
        "__DATA__": json.dumps(records, ensure_ascii=False).replace("<", "\\u003c"),
        "__RUN__": run,
    }
    return _PLACEHOLDER.sub(lambda m: values[m.group(0)], template.read_text(encoding="utf-8"))


def _fields(doc_id: str, content: dict) -> dict:
    if "data" in content:
        if content.get("id", doc_id) != doc_id:
            raise SystemExit(f"document {doc_id} claims to be {content['id']}")
        content = content["data"]
    return {k: v for k, v in content.items() if k != "id"}


def load_choices(path: Path, run: str) -> dict[str, dict]:
    """In a folder the filename is a document's id, and nothing inside the file can change it;
    in a listing an id may appear once."""
    if path.is_dir():
        folder = path / f"decisions-{run}" if (path / f"decisions-{run}").is_dir() else path
        files = sorted(folder.glob("*.json"))
        return {f.stem: _fields(f.stem, json.loads(f.read_text(encoding="utf-8"))) for f in files}
    choices = {}
    for doc in json.loads(path.read_text(encoding="utf-8")):
        if doc["id"] in choices:
            raise SystemExit(f"document {doc['id']} is listed twice")
        choices[doc["id"]] = _fields(doc["id"], doc)
    return choices
