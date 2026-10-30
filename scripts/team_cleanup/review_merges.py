#!/usr/bin/env python3
"""Review a weekly team-cleanup run's duplicate pairs before its merges page is built.

This is Step 5 of the merging-duplicate-teams skill, run unattended: reviewers judge every pair from its
evidence, so the owner sees only the pairs they could not settle. The first run queues the review into
<run>/merges/review/; each run then reviews up to RUN_SLICES of the slices still queued, the rest waiting
for the next run:

  BRIEF.md, CONFIRM.md,     the reviewers' briefs, from assets/, with this season's cohorts and the lookup
  RECHECK.md
  skill/                    the reviewers' rules: the merging-duplicate-teams skill's text as the run's checkout
                            held it, SKILL.md and references/, and VERSION naming which
  slice_NN.json             up to 50 pairs, in the order the page's caps keep them, each labelled
  slice_NN.md               their evidence
  slice_NN_review.json      each pair with its final verdict (merge, hold or reject) and swap, which
                            pages.py routes by
  answers/                  a folder per reviewer (slice_NN-review/, slice_NN-confirm/, slice_NN-recheck/)
                            holding what it reads and the one answer it writes, the failed attempts, and every
                            reviewer's log

The review takes the pairs the page would show that need one (page_caps.merges.review a week); the rest wait
for a later week. A reviewer is headless Claude Code (`claude -p`) working in its own folder: it loads none of
the user's settings, MCP servers or memory, reads only its folder and scripts/team_cleanup/, writes only its one
answer, runs no program but the read-only lookups (review_lookup.py), and its environment holds only the public
database key. A merge of a pair an earlier run's review held goes to a second reviewer who assumes it is wrong,
since a held pair comes back every week and one lucky run could otherwise merge it, and each reject to one with
the opposite prior; neither sees the first one's answer, and a merge it does not confirm, or a reject it does not
uphold, becomes a hold. A slice whose reviewer fails is retried on the next run; after three failed attempts, a
slice whose review never came back is all holds, and one whose second reviewers never came back holds the merges
and rejects they did not answer, so the week goes on.

Without --execute it reads the pairs and says what it would do, writing nothing.

    python scripts/team_cleanup/review_merges.py --run 2026-10-28-all --stage merges
    python scripts/team_cleanup/review_merges.py --run 2026-10-28-all --stage merges --execute
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys
from collections import Counter, defaultdict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import httpx
from postgrest.exceptions import APIError

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.find_cross_provider_duplicates import batched, get_client, page  # noqa: E402
from scripts.fix_band_cohorts import SEASON_START  # noqa: E402
from scripts.team_cleanup.decisions import MERGES, DecisionsUnavailable, resolve_execute  # noqa: E402
from scripts.team_cleanup.pages import Selection, buildable, load_caps, merge_signals, select, teams_of  # noqa: E402
from scripts.team_cleanup.pairs import HOLD, MERGE, REJECT, VERDICTS  # noqa: E402
from scripts.team_cleanup.review_lookup import GAME_COLS, TEAM_COLS, event_of, label  # noqa: E402
from scripts.team_cleanup.run_store import (  # noqa: E402
    BUSY,
    MERGE_REVIEW_KEYS,
    REVIEW,
    REVIEW_DIR,
    REVIEW_SUFFIX,
    check_reviews,
    read_run,
    refused,
    reporting_busy,
    stage_due,
    stage_progress,
    store_dir,
)
from scripts.team_cleanup.sure import sure_because  # noqa: E402
from src.tournaments.storage._io import read_json, write_json  # noqa: E402

ASSETS = Path(__file__).resolve().parent / "assets"
BRIEFS = {
    "BRIEF.md": ASSETS / "merge_review_brief.md",
    "CONFIRM.md": ASSETS / "merge_confirm_brief.md",
    "RECHECK.md": ASSETS / "merge_recheck_brief.md",
}
SKILLS = ROOT / ".claude" / "skills"
MERGE_SKILL = "merging-duplicate-teams"
SKILL_DIR = "skill"
VERSION_FILE = "VERSION"
ANSWERS_DIR = "answers"
ATTEMPTS_FILE = "attempts.json"
READS = {"review": ("BRIEF.md",), "confirm": ("BRIEF.md", "CONFIRM.md"), "recheck": ("BRIEF.md", "RECHECK.md")}
OUTPUT = {"review": "verdicts.json", "confirm": "confirm.json", "recheck": "recheck.json"}
SLICE_PAIRS = 50
PARALLEL = 10
ATTEMPTS = 3
REVIEWER_TIMEOUT_SECONDS = 40 * 60
# Slices one run reviews: one wave, each slice reviewed, its merges confirmed and its rejects rechecked, stays inside
# the autopilot step's four hours even at the reviewer timeout, so no run is stopped with its reviewers still at work;
# the rest wait for the next run.
RUN_SLICES = PARALLEL
MODEL = "opus"
LOOKUP = (Path(__file__).resolve().parent / "review_lookup.py").as_posix()
# The lookup's own folder is a working directory too: with reads outside them blocked, Claude Code also
# refuses a Bash command naming a script outside them.
LOOKUP_DIR = Path(LOOKUP).parent.as_posix()
SETTINGS = json.dumps({"permissions": {"blockReadsOutsideWorkingDirectories": True}})
# What Windows and Claude Code need to start, and the public key the lookups read with; no other secret.
REVIEWER_ENV = (
    "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "PATH", "PATHEXT", "COMSPEC", "TEMP", "TMP", "USERPROFILE", "HOMEDRIVE",
    "HOMEPATH", "HOME", "APPDATA", "LOCALAPPDATA", "PROGRAMDATA", "PROGRAMFILES", "PROGRAMFILES(X86)", "USERNAME",
    "COMPUTERNAME", "OS", "PROCESSOR_ARCHITECTURE", "NUMBER_OF_PROCESSORS", "LANG", "CLAUDE_CONFIG_DIR",
    "SUPABASE_URL", "SUPABASE_KEY",
)  # fmt: skip
SIBLINGS_SHOWN = 15
LAST_GAMES_SHOWN = 5


def reviewable(store: Path, run_id: str, stage: str = MERGES) -> Path:
    """The stage's folder, while its review is queued, or while its page may still be built."""
    progress = stage_progress(store, run_id, stage)
    if progress.next_step is not None and progress.next_step.name == REVIEW.name:
        return stage_due(store, read_run(store, run_id), stage, (REVIEW.name,))
    return buildable(store, run_id, stage)


# --- choosing the pairs -----------------------------------------------------------------------------


def review_pairs(sb, folder: Path, cap: int) -> tuple[list[dict], Selection]:
    """The pairs the page shows that need a review, in the order its caps keep them, up to ``cap``: not one the
    rules already settle (a provably safe pair whose retiring row still holds no games)."""
    chosen = select(sb, folder, MERGES)
    signals = merge_signals(sb, folder, chosen)
    return [p for p in chosen.shown if not sure_because(MERGES, p, signals)][:cap], chosen


# --- the evidence pack ------------------------------------------------------------------------------


def _fetch(sb, table: str, cols: str, column: str, ids, order: str) -> list[dict]:
    rows = []
    for batch in batched(sorted(set(ids))):
        rows += page(lambda b=batch: sb.table(table).select(cols).in_(column, b), order)
    return rows


def adjacent_days(mine: dict[str, set], theirs: dict[str, set]) -> list[str]:
    """The days one row played and the other played the day before or after, in another event."""
    found = set()
    for day, events in mine.items():
        for step in (-1, 1):
            other = (date.fromisoformat(day) + timedelta(days=step)).isoformat()
            if other in theirs and events != theirs[other]:
                found.add(day)
    return sorted(found)


def evidence_blocks(sb, pairs: list[dict], chosen: Selection) -> list[str]:
    """Each pair's evidence as a reviewer reads it, in the pairs' order. Games are counted as the card counts them:
    merge-resolved, an excluded game apart, and a game a row played against itself only as self-play."""
    merge_map, canonical = chosen.merge_map, chosen.canonical
    providers = {p["id"]: p["code"] for p in sb.table("providers").select("id,code").execute().data}
    ids = {team for p in pairs for team in teams_of(p)}
    teams = {t["team_id_master"]: t for t in _fetch(sb, "teams", TEAM_COLS, "team_id_master", ids, "team_id_master")}
    read_ids = ids | {d for d in merge_map if canonical(d) in ids}
    games = {}
    for side in ("home_team_master_id", "away_team_master_id"):
        for g in _fetch(sb, "games", GAME_COLS, side, read_ids, "id"):
            games[g["id"]] = g
    aliases = defaultdict(list)
    alias_cols = "id,team_id_master,provider_id,provider_team_id"
    for a in _fetch(sb, "team_alias_map", alias_cols, "team_id_master", ids, "id"):
        aliases[a["team_id_master"]].append(f"{providers.get(a['provider_id'], '?')}:{a['provider_team_id']}")
    # A row that already absorbed another cohort's registration is two squads before this merge adds a third.
    absorbed, absorbed_name = defaultdict(list), {}
    for t in _fetch(sb, "teams", TEAM_COLS, "team_id_master", read_ids - ids, "team_id_master"):
        absorbed_name[t["team_id_master"]] = t["team_name_original"] or t["team_name"]
        absorbed[canonical(t["team_id_master"])].append(absorbed_name[t["team_id_master"]])

    played, self_play = defaultdict(list), Counter()
    opponents = set()
    for g in games.values():
        home, away = canonical(g["home_team_master_id"]), canonical(g["away_team_master_id"])
        if home and home == away:
            self_play[home] += 1
            continue
        for me, raw, them, mine, theirs, registration in (
            (home, g["home_team_master_id"], away, g["home_score"], g["away_score"], g["home_provider_id"]),
            (away, g["away_team_master_id"], home, g["away_score"], g["home_score"], g["away_provider_id"]),
        ):
            if me in ids:
                played[me].append(
                    {"date": g["game_date"], "opponent": them, "score": f"{mine}-{theirs}", "event": event_of(g),
                     "excluded": g["is_excluded"], "registration": registration, "via": None if raw == me else raw}
                )  # fmt: skip
                if them:
                    opponents.add(them)
    others = {
        t["team_id_master"]: t for t in _fetch(sb, "teams", TEAM_COLS, "team_id_master", opponents, "team_id_master")
    }
    clubs = {t["club_name"] for t in teams.values() if t["club_name"]}
    siblings = defaultdict(list)
    for batch in batched(sorted(clubs), 40):
        live = page(
            lambda b=batch: sb.table("teams").select(TEAM_COLS).in_("club_name", b).eq("is_deprecated", False),
            "team_id_master",
        )
        for t in live:
            siblings[(t["club_name"], t["age_group"], t["gender"], t["state_code"])].append(t)

    counted = {team: [g for g in played[team] if not g["excluded"]] for team in ids}
    events_on = {team: defaultdict(set) for team in ids}
    for team in ids:
        for g in counted[team]:
            events_on[team][g["date"]].add(g["event"])

    def game_line(g: dict) -> str:
        opponent = json.dumps(label(others.get(g["opponent"])))
        return f"     {g['date']} vs {opponent} {g['score']} {json.dumps(g['event'])}"

    def row_lines(role: str, team_id: str, shared: list[str]) -> list[str]:
        t = teams.get(team_id)
        if t is None:
            return [f"{role}: row not found"]
        mine = counted[team_id]
        dates = sorted(g["date"] for g in mine)
        span = f"{dates[0][:7]}..{dates[-1][:7]}" if dates else "none"
        events = Counter(g["event"] for g in mine if g["event"]).most_common(4)
        cohorts = Counter(
            f"{others[g['opponent']]['age_group']}/{(others[g['opponent']]['gender'] or '?')[:1]}"
            for g in mine
            if g["opponent"] in others
        ).most_common(4)
        registrations_on = defaultdict(set)
        for g in mine:
            if g["registration"]:
                registrations_on[g["date"]].add(g["registration"])
        doubled = sorted(d for d, on in events_on[team_id].items() if len(on) > 1)
        split = sorted(d for d, on in registrations_on.items() if len(on) > 1)
        events_of_day = {d: " / ".join(json.dumps(e) for e in sorted(events_on[team_id][d])) for d in doubled[:3]}
        lines = [
            f"{role}: {json.dumps(t['team_name'])} | registered: {json.dumps(t['team_name_original'])} "
            f"| club: {json.dumps(t['club_name'])} | {providers.get(t['provider_id'], '?')}:{t['provider_team_id']} "
            f"| stored {t['age_group']} {t['gender']} {t['state_code']} "
            f"| aliases: {', '.join(aliases[team_id]) or '-'}",
            f"   games {len(mine)} (this season {sum(g['date'] >= SEASON_START for g in mine)}, "
            f"excluded {len(played[team_id]) - len(mine)}) {span} | self-play {self_play[team_id]} "
            f"| events: {'; '.join(f'{json.dumps(e)} x{n}' for e, n in events) or '-'} "
            f"| opponent cohorts: {', '.join(f'{c} x{n}' for c, n in cohorts) or '-'}",
            f"   merged into it earlier: {'; '.join(json.dumps(name) for name in absorbed[team_id]) or 'none'} "
            f"| days it played in two events: {len(doubled)} "
            + "; ".join(f"{d} ({events})" for d, events in events_of_day.items())
            + f" | days two of its registrations played: {len(split)} {split[:3]}",
        ]
        # Step 4's test for a day in question reads its games: the same opponent and score is one game recorded
        # twice, and a game that came in with a row merged earlier belongs to that row.
        questioned = set(doubled[:3]) | set(shared)
        if questioned:
            lines.append("   its games on those days and the shared dates:")
        for g in sorted((g for g in mine if g["date"] in questioned), key=lambda g: (g["date"], g["event"])):
            via = f" | via {json.dumps(absorbed_name.get(g['via'], g['via']))}" if g["via"] else ""
            lines.append(f"{game_line(g)} | registration {g['registration'] or '-'}{via}")
        lines.append("   last games:")
        lines += [game_line(g) for g in sorted(mine, key=lambda g: g["date"])[-LAST_GAMES_SHOWN:]]
        return lines

    blocks = []
    for p in pairs:
        merge, keep = p["merge_id"], p["keep_id"]
        shared = sorted(set(events_on[merge]) & set(events_on[keep]))
        adjacent = adjacent_days(events_on[merge], events_on[keep])
        faced = {team: {g["opponent"] for g in counted[team] if g["opponent"]} for team in (merge, keep)}
        union = faced[merge] | faced[keep]
        overlap = f"{len(faced[merge] & faced[keep]) / len(union):.2f}" if faced[merge] and faced[keep] else "none"
        head_to_head = sum(1 for g in counted[merge] if g["opponent"] == keep)
        mates = []
        for t in (teams.get(merge), teams.get(keep)):
            if t is None:
                continue
            for s in siblings.get((t["club_name"], t["age_group"], t["gender"], t["state_code"]), []):
                if s["team_id_master"] not in (merge, keep) and s not in mates:
                    mates.append(s)
        blocks.append(
            "\n".join(
                [
                    f"## {p['pair']} merge_id={merge} keep_id={keep}",
                    f"doorway {p['doorway']} {p.get('tier') or ''} | squad key: {json.dumps(p.get('squad_key'))} "
                    f"| club: {json.dumps(p['club'])}",
                    *row_lines("RETIRE", merge, shared[:4]),
                    *row_lines("KEEP", keep, shared[:4]),
                    f"head-to-head {head_to_head} | shared dates {len(shared)} {shared[:4]} "
                    f"| adjacent-day different events {adjacent[:4]} | opponent overlap {overlap}",
                    "other live rows of the club in this cohort: "
                    + (
                        "; ".join(
                            f"{json.dumps(s['team_name'])} (last played {str(s['last_played_at'])[:10]})"
                            for s in mates[:SIBLINGS_SHOWN]
                        )
                        or "none"
                    ),
                    "",
                ]
            )
        )
    return blocks


# --- queueing --------------------------------------------------------------------------------------


def slice_name(n: int) -> str:
    return f"slice_{n:02d}"


def cohort_rules(season: int) -> str:
    """The brief's cohort rules for the season the review runs in, since every cohort moves up each Aug 1."""
    ages = ", ".join(f"{season - age + 1} = U{age}" for age in range(9, 18))
    u13, u12 = season - 12, season - 11
    return (
        f"**Cohort.** The {season}-{(season + 1) % 100:02d} season: birth year {ages}, {season - 17} and "
        f"{season - 18} = U19 (no U18 board), {season - 19} = U19.\n"
        f"  `{u13 % 100:02d}B` is birth year {u13}, boys, = U13. A two-year band is named by its YOUNGER year:\n"
        f"  `{u12 - 1}/{u12 % 100:02d}`, `{(u12 - 1) % 100:02d}/{u12 % 100:02d}`, `{u12}/{u12 - 1}` are all U12 "
        f"({season} - {u12} + 1); `{u13 - 1}/{u13 % 100:02d}` is U13."
    )


def render_brief(text: str, season: int) -> str:
    return text.replace("{lookup}", LOOKUP).replace("{cohorts}", cohort_rules(season))


def skill_commit(name: str) -> str:
    """The commit the checkout holds, marked when the skill's files differ from it."""
    git = ["git", "-C", str(ROOT)]
    try:
        head = subprocess.run([*git, "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True)
        edits = subprocess.run(
            [*git, "status", "--porcelain", "--", f".claude/skills/{name}"], capture_output=True, text=True, check=True
        )
    except (OSError, subprocess.CalledProcessError):
        return "an unknown commit"
    return head.stdout.strip() + (" with local edits" if edits.stdout.strip() else "")


def pack_skill(review: Path, name: str, skills: Path = SKILLS) -> str:
    """Copy the skill's text into review/skill/, SKILL.md and references/*.md but none of its scripts, in its own
    layout so its links resolve in every reviewer's folder; the version the reviewers judge by, kept in VERSION."""
    source, target = skills / name, review / SKILL_DIR
    digest = hashlib.sha256()
    for path in [source / "SKILL.md", *sorted((source / "references").glob("*.md"))]:
        relative, text = path.relative_to(source), path.read_bytes()
        (target / relative).parent.mkdir(parents=True, exist_ok=True)
        (target / relative).write_bytes(text)
        digest.update(relative.as_posix().encode() + b"\0" + text)
    version = f"{name} at {skill_commit(name)}, sha256 {digest.hexdigest()[:12]}"
    (target / VERSION_FILE).write_text(version + "\n", encoding="utf-8")
    return version


def skill_version(review: Path) -> str | None:
    path = review / SKILL_DIR / VERSION_FILE
    return path.read_text(encoding="utf-8").strip() if path.exists() else None


def held_before(folder: Path) -> set[frozenset[str]]:
    """The pairs, each as its two rows either way round, that an earlier run's review of this stage held for the
    owner, read from the run store."""
    held = set()
    for path in folder.parent.parent.glob(f"*/{folder.name}/{REVIEW_DIR}/*{REVIEW_SUFFIX}"):
        if path.parents[2].name == folder.parent.name:
            continue
        held |= {frozenset((row["merge_id"], row["keep_id"])) for row in read_json(path) if row["verdict"] == HOLD}
    return held


def queue(sb, folder: Path, cap: int) -> int:
    """Write the review's slices and briefs; the number of pairs queued. A review of no pair still leaves the
    folder, so the autopilot moves on to the page, which then has no review to route by."""
    pairs, chosen = review_pairs(sb, folder, cap)
    earlier = held_before(folder)
    labelled = [
        {**p, "pair": f"P{n:04d}", "held_before": frozenset((p["merge_id"], p["keep_id"])) in earlier}
        for n, p in enumerate(pairs, 1)
    ]
    blocks = evidence_blocks(sb, labelled, chosen)
    review = folder / REVIEW_DIR
    (review / ANSWERS_DIR).mkdir(parents=True, exist_ok=True)
    season = int(SEASON_START[:4])
    for name, source in BRIEFS.items():
        (review / name).write_text(render_brief(source.read_text(encoding="utf-8"), season), encoding="utf-8")
    pack_skill(review, MERGE_SKILL)
    for n, start in enumerate(range(0, len(labelled), SLICE_PAIRS), 1):
        name = slice_name(n)
        (review / f"{name}.md").write_text("\n".join(blocks[start : start + SLICE_PAIRS]), encoding="utf-8")
        write_json(review / f"{name}.json", labelled[start : start + SLICE_PAIRS], indent=1)
    return len(labelled)


# --- reviewing ------------------------------------------------------------------------------------


def reviewer_command(claude: str, prompt: str, output: str) -> list[str]:
    """A headless reviewer that loads none of the user's settings, MCP servers or memory, and is refused every tool
    call but these: reading its own folder and scripts/team_cleanup/, writing its one answer, and the read-only
    lookups. The answer's rule is anchored at the folder the reviewer starts in, which a `cd` does not move."""
    return [
        claude,
        "-p",
        prompt,
        "--model",
        MODEL,
        "--setting-sources",
        "",
        "--settings",
        SETTINGS,
        "--permission-mode",
        "dontAsk",
        "--tools",
        "Read,Write,Bash",
        "--allowedTools",
        "Read(./**)",
        f"Edit(/{output})",
        f"Bash(python {LOOKUP}:*)",
        "--add-dir",
        LOOKUP_DIR,
        "--strict-mcp-config",
        "--no-session-persistence",
        "--output-format",
        "text",
    ]


def reviewer_env() -> dict[str, str]:
    """The allowlisted variables, with auto memory off, since a memory write passes no permission rule and a retry
    would read it back, and every Bash command started in the reviewer's folder."""
    kept = {key: value for key, value in os.environ.items() if key.upper() in REVIEWER_ENV}
    return {
        **kept,
        "PYTHONUTF8": "1",
        "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1",
        "CLAUDE_BASH_MAINTAIN_PROJECT_WORKING_DIR": "1",
    }


def run_reviewer(command: list[str], cwd: Path, log: Path) -> int:
    """One headless reviewer, its output in ``log``; its exit code. It works in the folder's full path: Claude Code
    matches the reviewer's write permission against that, so a short (8.3) or dotted path would refuse every write."""
    with log.open("w", encoding="utf-8") as out:
        try:
            return subprocess.run(
                command,
                cwd=os.path.realpath(cwd),
                env=reviewer_env(),
                stdin=subprocess.DEVNULL,
                stdout=out,
                stderr=subprocess.STDOUT,
                timeout=REVIEWER_TIMEOUT_SECONDS,
            ).returncode
        except subprocess.TimeoutExpired:
            out.write(f"\nStopped after {REVIEWER_TIMEOUT_SECONDS} seconds.\n")
            return -1


def review_prompt(name: str) -> str:
    return (
        f"Read BRIEF.md in this folder and follow it. Your slice is {name}.md. "
        f"Write your verdicts to {OUTPUT['review']} in this folder."
    )


def recheck_prompt(name: str, labels: list[str], noun: str = "pairs") -> str:
    return (
        f"Read RECHECK.md in this folder and follow it. Recheck these {noun} from {name}.md: {', '.join(labels)}. "
        f"Write your answers to {OUTPUT['recheck']} in this folder."
    )


def confirm_prompt(name: str, labels: list[str], noun: str = "pairs") -> str:
    return (
        f"Read CONFIRM.md in this folder and follow it. Confirm or refuse these {noun} from {name}.md: "
        f"{', '.join(labels)}. Write your answers to {OUTPUT['confirm']} in this folder."
    )


def workspace(review: Path, name: str, kind: str) -> Path:
    """The reviewer's own folder: its brief, the skill it judges by when the review packed one, and its slice's
    evidence, copied in afresh, and nothing another reviewer wrote."""
    work = review / ANSWERS_DIR / f"{name}-{kind}"
    work.mkdir(parents=True, exist_ok=True)
    for source in (*READS[kind], f"{name}.md"):
        shutil.copyfile(review / source, work / source)
    if (review / SKILL_DIR).is_dir():
        shutil.rmtree(work / SKILL_DIR, ignore_errors=True)
        shutil.copytree(review / SKILL_DIR, work / SKILL_DIR)
    return work


def read_verdicts(path: Path, rows: list[dict]) -> list[dict]:
    """The reviewer's answer, one valid verdict per pair of the slice in its order, or ValueError."""
    answers = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(answers, list) or len(answers) != len(rows):
        raise ValueError(f"{path.name} does not hold one answer per pair of the slice")
    for row, answer in zip(rows, answers):
        if not isinstance(answer, dict) or any(answer.get(key) != row[key] for key in ("pair", "merge_id", "keep_id")):
            raise ValueError(f"{path.name} does not answer {row['pair']} in its place")
        reason = answer.get("reason")
        if answer.get("verdict") not in VERDICTS or not isinstance(answer.get("swap"), bool):
            raise ValueError(f"{path.name} gives {row['pair']} a verdict or swap the brief does not allow")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError(f"{path.name} gives {row['pair']} no reason")
    return answers


def read_recheck(path: Path, labels: list[str], label: str = "pair") -> dict[str, dict]:
    """A second reviewer's answer on each verdict it was given, by label, or ValueError."""
    answers = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(answers, list) or [a.get(label) if isinstance(a, dict) else None for a in answers] != labels:
        raise ValueError(f"{path.name} does not answer {', '.join(labels)} in order")
    for answer in answers:
        reason = answer.get("reason")
        if not isinstance(answer.get("upheld"), bool) or not isinstance(reason, str) or not reason.strip():
            raise ValueError(f"{path.name} gives {answer[label]} no upheld flag or no reason")
    return {answer[label]: answer for answer in answers}


def final_rows(rows: list[dict], verdicts: list[dict], seconds: dict[str, dict]) -> list[dict]:
    """Each pair with its final verdict: a merge of a pair held before that the second reviewer did not confirm, and
    a reject it did not uphold, are holds, and only a merge keeps a swap."""
    found = {MERGE: "one squad", REJECT: "two teams"}
    final = []
    for row, answer in zip(rows, verdicts):
        verdict, reason = answer["verdict"], answer["reason"].strip()
        if verdict == REJECT or merges_a_held_pair(row, answer):
            second = seconds.get(row["pair"])
            if second is None or not second["upheld"]:
                answered = f": {second['reason'].strip()}" if second else ""
                reason = f"one reviewer found {found[verdict]} ({reason}), and a second did not agree{answered}"
                verdict = HOLD
        final.append({**row, "verdict": verdict, "swap": answer["swap"] and verdict == MERGE, "reason": reason})
    return final


def held_rows(rows: list[dict], why: str) -> list[dict]:
    return [{**row, "verdict": HOLD, "swap": False, "reason": why} for row in rows]


@dataclass(frozen=True)
class Kind:
    """What one review's slices and answers carry: the keys its review copies (the run store's contract), the key
    each answer names its row by, what the second reviewers' prompts call them, how answers become review rows,
    and which answers a second reviewer must confirm before they stand (every reject is rechecked)."""

    keys: tuple[str, ...]
    label: str
    noun: str
    read_verdicts: Callable[[Path, list[dict]], list[dict]]
    final_rows: Callable[[list[dict], list[dict], dict], list[dict]]
    held_rows: Callable[[list[dict], str], list[dict]]
    confirmed: Callable[[dict, dict], bool] = lambda row, answer: False


def merges_a_held_pair(row: dict, answer: dict) -> bool:
    """A slice queued before ``held_before`` was recorded reads as no earlier hold, as its run's code reviewed it."""
    return answer["verdict"] == MERGE and row.get("held_before", False)


PAIRS = Kind(MERGE_REVIEW_KEYS, "pair", "pairs", read_verdicts, final_rows, held_rows, merges_a_held_pair)


def review_slice(
    review: Path, name: str, failures: int, claude: str, runner=run_reviewer, kind: Kind = PAIRS
) -> tuple[bool, int]:
    """Review one slice, writing its review once settled; (settled, this slice's failed attempts). An answer
    already in a reviewer's own folder is that reviewer's, so a retry reads it rather than buying it again."""
    rows = read_json(review / f"{name}.json")

    def attempt(role: str, prompt: str, read):
        nonlocal failures
        work = workspace(review, name, role)
        path = work / OUTPUT[role]
        try:
            return read(path)
        except (OSError, ValueError):
            pass
        log = review / ANSWERS_DIR / f"{name}-{role}-{failures + 1}.log"
        code = runner(reviewer_command(claude, prompt, OUTPUT[role]), work, log)
        try:
            return read(path)
        except (OSError, ValueError) as exc:
            failures += 1
            print(f"  {name}: the {role} reviewer failed (exit {code}): {exc}; see {log}")
            return None

    verdicts = attempt("review", review_prompt(name), lambda path: kind.read_verdicts(path, rows))
    if verdicts is None:
        if failures < ATTEMPTS:
            return False, failures
        held = kind.held_rows(rows, f"the automatic review failed {failures} times")
        write_json(review / f"{name}{REVIEW_SUFFIX}", held, indent=1)
        return True, failures
    seconds = {}
    rows_by_label = {row[kind.label]: row for row in rows}
    for role, needed, prompt in (
        ("confirm", kind.confirmed, confirm_prompt),
        ("recheck", lambda row, answer: answer["verdict"] == REJECT, recheck_prompt),
    ):
        labels = [answer[kind.label] for answer in verdicts if needed(rows_by_label[answer[kind.label]], answer)]
        if not labels:
            continue
        answered = attempt(
            role, prompt(name, labels, kind.noun), lambda path, labels=labels: read_recheck(path, labels, kind.label)
        )
        if answered is None and failures < ATTEMPTS:
            return False, failures
        seconds.update(answered or {})
    write_json(review / f"{name}{REVIEW_SUFFIX}", kind.final_rows(rows, verdicts, seconds), indent=1)
    return True, failures


def waiting(review: Path, keys: tuple[str, ...] = MERGE_REVIEW_KEYS) -> list[str]:
    """The slices with no review that copies them, as the run store reads them."""
    return list(check_reviews(review, keys)[0])


def review_queued(review: Path, claude: str, runner=run_reviewer, kind: Kind = PAIRS) -> list[str]:
    """Review the first RUN_SLICES waiting slices, up to PARALLEL at once; those of them still waiting afterwards."""
    attempts_path = review / ANSWERS_DIR / ATTEMPTS_FILE
    attempts = read_json(attempts_path) if attempts_path.exists() else {}
    names = waiting(review, kind.keys)[:RUN_SLICES]
    with ThreadPoolExecutor(max_workers=PARALLEL) as pool:
        results = list(
            pool.map(lambda name: review_slice(review, name, attempts.get(name, 0), claude, runner, kind), names)
        )
    for name, (_, failures) in zip(names, results):
        attempts[name] = failures
    write_json(attempts_path, attempts, indent=1)
    return [name for name, (settled, _) in zip(names, results) if not settled]


def counts(review: Path) -> Counter:
    return Counter(row["verdict"] for path in review.glob(f"*{REVIEW_SUFFIX}") for row in read_json(path))


def review_main(
    doc: str,
    stage: str,
    what: str,
    kind: Kind,
    plan: Callable[[Path, int], str],
    queue_review: Callable[[Path, int], str],
    tally: Callable[[Path], str],
) -> int:
    """A review's command: queue the stage's review on its first run, then review up to RUN_SLICES of its waiting
    slices. 0 when done, 1 while a slice waits for a retry, BUSY while slices wait for the next run."""
    ap = argparse.ArgumentParser(description=doc, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", required=True, help="The run id, e.g. 2026-11-04-all")
    ap.add_argument("--stage", required=True, choices=(stage,))
    ap.add_argument(
        "--store",
        type=Path,
        help="The run store, absolute (default: PITCHRANK_CLEANUP_DIR, else ~/pitchrank-cleanup-runs)",
    )
    ap.add_argument("--execute", action="store_true", help="Queue and run the review (default is a dry run)")
    ap.add_argument("--dry-run", action="store_true", help="Write nothing; wins over --execute")
    args = ap.parse_args()
    execute = resolve_execute(args.execute, args.dry_run)
    cannot = f"Cannot review {what} of {args.run}"
    with reporting_busy():
        try:
            store = store_dir(args.store)
            folder = reviewable(store, args.run, stage)
            review = folder / REVIEW_DIR
            if not review.exists():
                cap = load_caps(stage=stage).review
                if not execute:
                    print(f"DRY RUN -- would queue {plan(folder, cap)}")
                    return 0
                print(f"queued {queue_review(folder, cap)} for review in {review}")
            names = waiting(review, kind.keys)
            if not execute:
                now = names[:RUN_SLICES]
                listed = ", ".join(now) or "none"
                print(f"DRY RUN -- would review {len(now)} of {len(names)} waiting slice(s): {listed}")
                return 0
            claude = shutil.which("claude")
            if names and not claude:
                raise SystemExit(f"{cannot}: the claude command is not on PATH, so no reviewer can run")
            left = review_queued(review, claude, run_reviewer, kind) if names else []
        except DecisionsUnavailable as exc:
            waits = "The review waits until the owner's earlier decisions can be read."
            raise SystemExit(f"{cannot}: {exc}\n{waits}") from exc
        except (OSError, ValueError) as exc:
            raise SystemExit(f"{cannot}: {exc}") from None
        except (APIError, httpx.HTTPError) as exc:
            raise SystemExit(refused(cannot, exc, shlex.join(["python", *sys.argv]))) from None
    print(tally(review))
    if left:
        print(f"{len(left)} slice(s) wait for a retry: {', '.join(left)}")
        return 1
    later = waiting(review, kind.keys)
    if later:
        print(f"{len(later)} slice(s) wait for the next run: {', '.join(later)}")
        return BUSY
    print(f"next: build the page, pages.py --run {args.run} --stage {stage} --publish --execute")
    return 0


def main() -> int:
    def plan(folder: Path, cap: int) -> str:
        pairs, _ = review_pairs(get_client(), folder, cap)
        return f"{len(pairs)} pair(s) for review, {SLICE_PAIRS} a reviewer"

    def tally(review: Path) -> str:
        found = counts(review)
        rules = skill_version(review) or "the brief alone"
        return f"reviewed: {found[MERGE]} merge, {found[HOLD]} hold, {found[REJECT]} reject, judged by {rules}"

    def queued(folder: Path, cap: int) -> str:
        return f"{queue(get_client(), folder, cap)} pair(s)"

    return review_main(__doc__, MERGES, "the duplicate pairs", PAIRS, plan, queued, tally)


if __name__ == "__main__":
    raise SystemExit(main())
