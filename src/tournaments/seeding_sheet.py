"""Build printable tournament cheat sheets, with optional matchup-based tiers.

Every accepted entrant appears once, including teams needing placement review.
Cohorts begin on fresh Letter pages; long tier tables repeat their headings.
The same standalone, offline-ready HTML powers the preview and PDF export.

The published ``power_score_final`` is displayed and sorts teams within tiers.
The matchup analysis determines tier membership and order.

A team with a valid current PowerScore can be seeded even when PitchRank has not
published a numeric rank for it. An Inactive team does not qualify: it keeps only
a stale PowerScore and sits below the line rather than appearing among current
teams with an empty rank beside its name.

State rank comes from ``state_rankings_view``. ``rankings_full.state_rank`` is
always NULL, because the views compute the published ranks.
"""

from __future__ import annotations

import base64
import html
import math
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

from src.tournaments.roster_paste import RosterRow
from src.tournaments.roster_resolver import ResolvedTeam

if TYPE_CHECKING:
    from src.tournaments.seeding_tiers import CheatSheetAnalysis, TierPolicy

__all__ = [
    "BRAND",
    "CohortSheet",
    "SheetTeam",
    "build_cohort_sheets",
    "fetch_ranking_run_date",
    "make_ratings_lookup",
    "render_sheet_html",
]

BRAND = {
    "forest": "#0B5345",
    "forest_deep": "#083E33",
    "yellow": "#F4D03F",
    "ink": "#12211D",
    "muted": "#5B6B66",
    "rule": "#D8E0DD",
    "paper": "#FFFFFF",
    "band": "#F4F7F6",
}


@dataclass(frozen=True)
class SheetTeam:
    team_name: str
    club_name: str
    power_score: float | None = None
    state_rank: int | None = None
    state: str | None = None
    status: str | None = None
    entrant_id: str = ""
    team_id_master: str | None = None
    review_reason: str | None = None
    pitchrank_team_name: str | None = None
    plays_up: bool = False
    play_up_from_age_group: str | None = None
    requested_flight: str | None = None
    listed_division: str | None = None


@dataclass(frozen=True)
class CohortSheet:
    age_group: str
    gender: str
    rated: tuple[SheetTeam, ...]
    unrated: tuple[SheetTeam, ...]
    tier_analysis: CheatSheetAnalysis | None = None

    @property
    def total_teams(self) -> int:
        return len(self.rated) + len(self.unrated)


def _display_gender(gender: str) -> str:
    return {"Male": "Boys", "Female": "Girls"}.get(gender, gender)


def _age_sort_key(age_group: str) -> int:
    digits = age_group.lower().removeprefix("u")
    return int(digits) if digits.isdigit() else 0


def _team_id_for(row: RosterRow, item: ResolvedTeam | None, overrides: Mapping[int, dict[str, Any]]) -> str | None:
    override = overrides.get(row.source_index)
    if override and override.get("team_id_master"):
        return str(override["team_id_master"])
    return (item.team_id_master if item else None) or None


def _materially_different_name(first: str, second: str) -> bool:
    """Ignore casing and punctuation when deciding whether two display names differ."""
    def comparable(value: str) -> str:
        return "".join(character for character in value.casefold() if character.isalnum())

    return bool(second.strip()) and comparable(first) != comparable(second)


def _ranked_age_group(rating: Mapping[str, Any]) -> str | None:
    age = rating.get("age")
    if isinstance(age, int) and not isinstance(age, bool) and 1 <= age <= 99:
        return f"u{age}"
    age_group = str(rating.get("age_group") or "").strip().lower().replace(" ", "")
    match = re.fullmatch(r"u?([0-9]{1,2})", age_group)
    return f"u{int(match.group(1))}" if match else None


def _play_up_from_age_group(rating: Mapping[str, Any], entered_age_group: str) -> str | None:
    ranked = _ranked_age_group(rating)
    ranked_age = _age_sort_key(ranked or "")
    entered_age = _age_sort_key(entered_age_group)
    return ranked if ranked_age and entered_age and ranked_age < entered_age else None


def build_cohort_sheets(
    rows: Sequence[RosterRow],
    resolved: Sequence[ResolvedTeam],
    overrides: Mapping[int, dict[str, Any]],
    ratings: Mapping[str, dict[str, Any]],
    *,
    tier_analyses: Mapping[tuple[str, str], CheatSheetAnalysis] | None = None,
) -> tuple[CohortSheet, ...]:
    """Group a resolved roster into one sheet per cohort, strongest first.

    The registration name stays primary because it is the name a tournament
    director has on their event roster. A materially different PitchRank name
    is retained as secondary identity context.
    """
    if len({row.source_index for row in rows}) != len(rows):
        raise ValueError("Each roster row must have a unique source index.")
    by_index = {item.source_index: item for item in resolved}
    grouped: dict[tuple[str, str], list[SheetTeam]] = {}
    unrated: dict[tuple[str, str], list[SheetTeam]] = {}

    for row in rows:
        cohort = (row.section_age_group, row.section_gender)
        grouped.setdefault(cohort, [])
        unrated.setdefault(cohort, [])

        team_id = _team_id_for(row, by_index.get(row.source_index), overrides)
        rating = ratings.get(team_id) if team_id else None

        rating = rating or {}
        score = rating.get("power_score_final")
        score = float(score) if isinstance(score, (int, float)) and not isinstance(score, bool) else None
        if score is not None and (not math.isfinite(score) or not 0 <= score <= 1):
            score = None
        analysis = (tier_analyses or {}).get(cohort)
        registered_name = row.registered_name
        pitchrank_name = str(rating.get("team_name") or "").strip()
        team = SheetTeam(
            team_name=registered_name,
            club_name=str(row.club_raw or rating.get("club_name") or ""),
            pitchrank_team_name=(
                pitchrank_name if _materially_different_name(registered_name, pitchrank_name) else None
            ),
            power_score=score,
            state_rank=rating.get("rank_in_state_final"),
            state=str(rating["state"]).strip() if rating.get("state") else None,
            status=rating.get("status"),
            entrant_id=str(row.source_index),
            team_id_master=team_id,
            review_reason=analysis.review.get(str(row.source_index)) if analysis else None,
            plays_up=bool(row.has_star_marker),
            play_up_from_age_group=_play_up_from_age_group(rating, row.section_age_group),
            requested_flight=str(getattr(row, "requested_flight", "") or "").strip() or None,
            listed_division=str(getattr(row, "listed_division", "") or "").strip() or None,
        )
        if score is not None and rating.get("status") != "Inactive":
            grouped[cohort].append(team)
        else:
            unrated[cohort].append(team)

    sheets = []
    for cohort in sorted(grouped, key=lambda key: (-_age_sort_key(key[0]), key[1])):
        analysis = (tier_analyses or {}).get(cohort)
        by_seed = (
            {entrant_id: position for position, entrant_id in enumerate(analysis.ordered_ids, 1)}
            if analysis else {}
        )
        rated = sorted(
            grouped[cohort],
            key=lambda team: (
                0 if team.review_reason else 1,
                by_seed.get(team.entrant_id, 10**9),
                -(team.power_score if team.power_score is not None else -1.0),
                team.team_name.casefold(),
                team.entrant_id,
            ),
        )
        sheets.append(
            CohortSheet(
                age_group=cohort[0],
                gender=cohort[1],
                rated=tuple(rated),
                unrated=tuple(sorted(unrated[cohort], key=lambda team: team.team_name.lower())),
                tier_analysis=analysis,
            )
        )
    return tuple(sheets)


def make_ratings_lookup(supabase_client: Any) -> Callable[[Sequence[str]], dict[str, dict[str, Any]]]:
    """Fetch published ratings for a set of teams, batched under the URI limit."""

    def lookup(team_ids: Sequence[str]) -> dict[str, dict[str, Any]]:
        wanted = [team_id for team_id in dict.fromkeys(team_ids) if team_id]
        ratings: dict[str, dict[str, Any]] = {}

        for start in range(0, len(wanted), 100):
            batch = wanted[start : start + 100]
            for row in (
                supabase_client.table("rankings_full")
                .select("team_id,power_score_final,rank_in_cohort_final,status")
                .in_("team_id", batch)
                .execute()
                .data
                or []
            ):
                ratings[str(row["team_id"])] = dict(row)
            for row in (
                supabase_client.table("state_rankings_view")
                .select("team_id_master,rank_in_state_final,state")
                .in_("team_id_master", batch)
                .execute()
                .data
                or []
            ):
                ratings.setdefault(str(row["team_id_master"]), {}).update(
                    {"rank_in_state_final": row.get("rank_in_state_final"), "state": row.get("state")}
                )
            for row in (
                supabase_client.table("teams")
                .select("team_id_master,team_name,club_name,age_group")
                .in_("team_id_master", batch)
                .execute()
                .data
                or []
            ):
                ratings.setdefault(str(row["team_id_master"]), {}).update(
                    {
                        "team_name": row.get("team_name"),
                        "club_name": row.get("club_name"),
                        "age_group": row.get("age_group"),
                    }
                )

        return ratings

    return lookup


def fetch_ranking_run_date(supabase_client: Any) -> str:
    """When the ratings on the sheet were last calculated.

    Printed on the page because a director reading it weeks later needs to know
    how stale the numbers are.
    """
    rows = (
        supabase_client.table("rankings_full")
        .select("last_calculated")
        .order("last_calculated", desc=True)
        .limit(1)
        .execute()
        .data
        or []
    )
    stamp = rows[0].get("last_calculated") if rows else None
    return str(stamp)[:10] if stamp else "unknown"


def _state_rank(team: SheetTeam) -> str:
    if team.state_rank is None:
        return "—"
    return f"{team.state} #{team.state_rank}" if team.state else f"#{team.state_rank}"


def _score(value: float | None) -> str:
    # Match the website's published 0-100 presentation.
    return f"{value * 100:.1f}" if value is not None else "-"


def _status_label(status: str | None) -> str:
    return {
        "Not Enough Ranked Games": "",
        "Inactive": "No current ranking",
    }.get(str(status or "").strip(), str(status or "").strip())


def _tier_options(numbers: Sequence[int]) -> str:
    labels = [f"Tier {number}" for number in numbers]
    if len(labels) < 2:
        return "".join(labels)
    return ", ".join(labels[:-1]) + f" or {labels[-1]}"


@lru_cache(maxsize=1)
def _font_css() -> str:
    """Embed installed brand fonts so the downloaded HTML is also offline-ready."""
    font_root = Path(__file__).resolve().parents[2] / "frontend" / "node_modules" / "@fontsource"
    rules = []
    for family, package, weight in (("DM Sans", "dm-sans", 400), ("DM Sans", "dm-sans", 700),
                                    ("Oswald", "oswald", 600)):
        source = font_root / package / "files" / f"{package}-latin-{weight}-normal.woff2"
        if source.is_file():
            encoded = base64.b64encode(source.read_bytes()).decode("ascii")
            rules.append(
                f'@font-face {{ font-family: "{family}"; font-style: normal; font-weight: {weight}; '
                f'src: url(data:font/woff2;base64,{encoded}) format("woff2"); }}'
            )
    return "\n".join(rules)


def _rows_html(
    teams: Sequence[SheetTeam], *, numbered: bool, start: int = 1,
    placement_notes: Mapping[str, str] | None = None,
) -> str:
    cells = []
    for position, team in enumerate(teams, start=start):
        status = _status_label(team.status)
        flag = (
            f'<span class="flag">{html.escape(status)}</span>'
            if status and status != "Active" else ""
        )
        note = (placement_notes or {}).get(team.entrant_id) or team.review_reason or ""
        note_class = "placement boundary-note" if note.startswith("Boundary option") else "placement"
        pitchrank_name = (
            f'<span class="pitchrank-name">PitchRank: {html.escape(team.pitchrank_team_name)}</span>'
            if team.pitchrank_team_name else ""
        )
        if team.plays_up and team.play_up_from_age_group:
            play_up = (
                f'<span class="play-up">Plays up from '
                f'{html.escape(team.play_up_from_age_group.upper())}</span>'
            )
        elif team.plays_up:
            play_up = '<span class="play-up">Plays up</span>'
        else:
            play_up = ""
        flight_context = ""
        if team.requested_flight:
            flight_context += f'<span class="flight">Requested: {html.escape(team.requested_flight)}</span>'
        if team.listed_division:
            flight_context += f'<span class="flight">Listed: {html.escape(team.listed_division)}</span>'
        cells.append(
            f'<tr data-entrant="{html.escape(team.entrant_id, quote=True)}">'
            f'<td class="pos">{position if numbered else "-"}</td>'
            f'<td class="team">{html.escape(team.team_name)}{play_up}{flag}{pitchrank_name}'
            f'<span class="club">{html.escape(team.club_name)}</span></td>'
            f'<td class="num score">{_score(team.power_score)}{flight_context}</td>'
            f'<td class="num state">{html.escape(_state_rank(team))}</td>'
            f'<td class="{note_class}">{html.escape(note)}</td></tr>'
        )
    return "".join(cells)


def _table_html(title: str, teams: Sequence[SheetTeam], *, numbered: bool, start: int = 1,
                subtitle: str = "", placement_notes: Mapping[str, str] | None = None,
                review: bool = False, cohort_label: str = "", purpose: str = "") -> str:
    summary = f'<div class="tier-description">{html.escape(subtitle)}</div>' if subtitle else ""
    purpose_html = f'<span class="tier-purpose">{html.escape(purpose)}</span>' if purpose else ""
    return (
        f'<table class="grid{" review" if review else " tier-table"}">'
        '<colgroup><col class="seed-col"><col class="team-col"><col class="score-col">'
        '<col class="state-col"><col class="notes-col"></colgroup><thead>'
        f'<tr class="tier-heading"><th colspan="5"><span class="tier-title">{html.escape(title)}</span>'
        f'{purpose_html}<span class="count">{len(teams)} {"team" if len(teams) == 1 else "teams"}</span>'
        f'<span class="cohort-tag">{html.escape(cohort_label)}</span>{summary}</th></tr>'
        '<tr class="columns"><th class="pos">Suggested seed</th><th>Team / club</th>'
        '<th class="num">PitchRank score</th><th class="num">State rank</th><th>What to know</th></tr>'
        f'</thead><tbody>{_rows_html(teams, numbered=numbered, start=start, placement_notes=placement_notes)}'
        '</tbody></table>'
    )


def _tier_tables(sheet: CohortSheet) -> tuple[str, str]:
    """Render each entrant once, retaining even incomplete analysis rows for review."""
    analysis = sheet.tier_analysis
    assert analysis is not None
    all_teams = (*sheet.rated, *sheet.unrated)
    by_id = {team.entrant_id: team for team in all_teams}
    if "" in by_id or len(by_id) != len(all_teams):
        raise ValueError("Tier sheets require a unique entrant ID for every roster row.")
    tier_ids = [entrant_id for tier in analysis.tiers for entrant_id in tier.entrant_ids]
    if len(tier_ids) != len(set(tier_ids)) or set(tier_ids) & set(analysis.review):
        raise ValueError("A team cannot appear in more than one tier or in both a tier and review.")
    if (set(tier_ids) | set(analysis.review)) - set(by_id):
        raise ValueError("Tier analysis contains teams outside this cohort. Rebuild the analysis.")

    cohort_label = f"{_display_gender(sheet.gender)} {sheet.age_group.upper()}"
    parts = []
    start = 1
    for tier in analysis.tiers:
        members = [by_id[entrant_id] for entrant_id in tier.entrant_ids]
        if not members:
            continue
        if len(members) == 1:
            description = "No close peer was found at this level. Review the guidance before finalizing."
        else:
            description = "Recommended together for the closest projected games."
        notes = {}
        for entrant_id, alternatives in analysis.borderline.items():
            if not alternatives:
                continue
            if len(alternatives) > 1:
                notes[entrant_id] = (
                    f"Boundary options: If a neighboring tier needs one more team, move this team to "
                    f"{_tier_options(alternatives)}."
                )
                continue
            target = alternatives[0]
            direction = "up" if target < tier.number else "down"
            notes[entrant_id] = (
                f"Boundary option: If Tier {target} needs one more team, move this team {direction}."
            )
        parts.append(_table_html(f"Tier {tier.number}", members, numbered=True, start=start,
                                 subtitle=description, placement_notes=notes, cohort_label=cohort_label,
                                 purpose="Strongest group" if tier.number == 1 else "Next competitive group"))
        start += len(members)

    review_teams = [team for team in all_teams if team.entrant_id not in set(tier_ids)]
    if review_teams:
        reasons = {
            team.entrant_id: analysis.review.get(team.entrant_id) or team.review_reason
            or "Placement has not been assessed."
            for team in review_teams
        }
        parts.append(_table_html("Manual placement needed", review_teams, numbered=False, review=True,
                                 subtitle="Use recent results or club input before assigning these teams to a tier.",
                                 placement_notes=reasons, cohort_label=cohort_label))
    counts = [
        f"Tier {tier.number} — {len(tier.entrant_ids)} {('team' if len(tier.entrant_ids) == 1 else 'teams')}"
        for tier in analysis.tiers if tier.entrant_ids
    ]
    if review_teams:
        counts.append(f"{len(review_teams)} need manual placement")
    summary = "Recommended starting point: " + " | ".join(counts) + "."
    return "\n".join(parts), summary


def _director_guidance(analysis: Any) -> list[str]:
    """Turn model diagnostics into concise actions for the customer PDF."""
    guidance = []
    for index, boundary in enumerate(analysis.boundaries, 1):
        upper_ids = analysis.tiers[index - 1].entrant_ids
        lower_ids = analysis.tiers[index].entrant_ids
        has_boundary_option = any(
            index + 1 in analysis.borderline.get(entrant_id, ()) for entrant_id in upper_ids
        ) or any(index in analysis.borderline.get(entrant_id, ()) for entrant_id in lower_ids)
        if "Clear separation" in boundary:
            guidance.append(
                f"Keep Tier {index} and Tier {index + 1} separate when possible; "
                "projected results show a meaningful competitive gap."
            )
        elif "Ranking/matchup order conflict" in boundary:
            guidance.append(
                f"PitchRank score and the matchup forecast disagree at the Tier {index} / Tier {index + 1} line. "
                "Review recent results or club input before finalizing those teams."
            )
        elif "Overlapping matchups" in boundary:
            if has_boundary_option:
                guidance.append(
                    f"Tier {index} and Tier {index + 1} are close. If pool sizes require a change, "
                    "use the team marked Boundary option."
                )
            else:
                guidance.append(
                    f"Tier {index} and Tier {index + 1} have similar projected matchups, but no automatic "
                    "team move is recommended. Use recent results or club input if the format requires a change."
                )
        else:
            guidance.append(str(boundary))
    for warning in analysis.warnings:
        if "there is no within-tier matchup to assess" in warning:
            tier = warning.split(" has one team", 1)[0]
            guidance.append(
                f"{tier} has one team. Place it with the closest available group after considering "
                "recent results or club input."
            )
        elif "low outcome confidence" in warning:
            # This diagnostic helps the operator inspect the model, but it does
            # not give a director a different placement action from the tiers.
            continue
        elif "strength-order exception" in warning:
            # Keep minor prediction/ranking reversals in the operator review.
            # The customer action is already expressed by the tier line and
            # any boundary option beside it.
            continue
        elif "exceeds the matchup limits" in warning:
            tier = warning.split(" exceeds", 1)[0]
            guidance.append(f"{tier} includes a potentially uneven matchup. Review that group before finalizing.")
        else:
            guidance.append(str(warning))
    return guidance


def _cheat_sheet_tables(sheet: CohortSheet) -> tuple[str, str]:
    analysis = sheet.tier_analysis
    cohort = f"{_display_gender(sheet.gender)} {sheet.age_group.upper()}"
    all_teams = (*sheet.rated, *sheet.unrated)
    by_id = {team.entrant_id: team for team in all_teams}
    if len(by_id) != len(all_teams) or "" in by_id:
        raise ValueError("Cheat sheet requires a unique entrant ID for every roster row.")
    if analysis is not None:
        ordered_ids = list(analysis.ordered_ids)
        if len(ordered_ids) != len(set(ordered_ids)) or set(ordered_ids) & set(analysis.review):
            raise ValueError("Cheat sheet analysis contains duplicate or overlapping entrant IDs.")
        if set(analysis.review) - set(by_id):
            raise ValueError("Cheat sheet analysis contains a team outside this cohort.")
        legacy_ids = [entrant_id for tier in getattr(analysis, "tiers", ()) for entrant_id in tier.entrant_ids]
        if len(legacy_ids) != len(set(legacy_ids)) or set(legacy_ids) & set(analysis.review):
            raise ValueError("Cheat sheet legacy reference contains duplicate or overlapping entrant IDs.")
    if analysis is None:
        seeded = list(sheet.rated)
        unseeded = list(sheet.unrated)
        markers = {}
        statuses = {}
    else:
        seeded = [by_id[entrant_id] for entrant_id in analysis.ordered_ids if entrant_id in by_id]
        seeded_ids = set(analysis.ordered_ids)
        unseeded = [team for team in all_teams if team.entrant_id not in seeded_ids]
        if hasattr(analysis, "marker_for_seed"):
            markers = {
                entrant_id: analysis.marker_for_seed(seed)
                for seed, entrant_id in enumerate(analysis.ordered_ids, 1)
            }
            statuses = getattr(analysis, "placement_status", {})
        else:
            markers = {}
            statuses = {entrant_id: "Seeded" for entrant_id in analysis.ordered_ids}
            statuses.update({entrant_id: "Data review required" for entrant_id in analysis.review})
    notes = {}
    for seed, team in enumerate(seeded, 1):
        marker = markers.get(team.entrant_id, "")
        notes[team.entrant_id] = marker
    tables = _table_html(
        "Suggested seed order", seeded, numbered=True, cohort_label=cohort,
        subtitle=(
            "Teams remain in published PowerScore order. Strength markers show competitive "
            "differences and close ranges."
        ),
        placement_notes=notes,
    )
    if unseeded:
        review_notes = {
            team.entrant_id: statuses.get(team.entrant_id) or team.review_reason or "Placement has not been assessed."
            for team in unseeded
        }
        tables += _table_html(
            "Unseeded teams", unseeded, numbered=False, review=True, cohort_label=cohort,
            subtitle="These accepted teams are preserved, but PitchRank cannot place them in the seed order.",
            placement_notes=review_notes,
        )
    summary = f"{len(seeded)} seeded in published order · {len(unseeded)} held for placement review."
    return tables, summary


def _sheet_html(
    event_name: str, sheet: CohortSheet, *, generated_on: str, ranking_run: str,
    policy: TierPolicy | None = None, operator_note: str = "",
) -> str:
    cohort = f"{_display_gender(sheet.gender)} {sheet.age_group.upper()}"
    analysis = sheet.tier_analysis
    tables, summary = _cheat_sheet_tables(sheet)
    guidance = list(getattr(analysis, "notes", ()) if analysis is not None else ())
    if operator_note.strip():
        guidance.append(operator_note.strip())
    notes = ""
    if guidance:
        items = "".join(f"<li>{html.escape(value)}</li>" for value in dict.fromkeys(guidance))
        notes = f'<aside class="guidance"><h2>Director notes</h2><ul>{items}</ul></aside>'
    explanation = (
        "Strength breaks describe competitive differences; they do not assign divisions or pools. "
        "Use the continuous seed order and close ranges to support the director's chosen arrangement. "
        "PitchRank score already adjusts for age, so a younger team playing up can be compared here. "
        "State rank is that team's rank within its own PitchRank age and gender group."
    )
    diagnostics = ""
    if analysis is not None and getattr(analysis, "diagnostics", ()):
        diagnostics = (
            '<details class="diagnostics"><summary>Analysis details</summary><ul>'
            + "".join(f"<li>{html.escape(value)}</li>" for value in getattr(analysis, "diagnostics", ()))
            + "</ul></details>"
        )
    guide = f"""<section class="seed-guide">
  <div class="recommendation">{html.escape(summary)}</div>
  <p class="method">{html.escape(explanation)}</p>
  <div class="guide-grid">
   <div class="guide-step"><strong>Seed order</strong>
    <span>Start with the published order, then use tournament judgement for final placement.</span></div>
   <div class="guide-step"><strong>Strength breaks</strong>
    <span>A marker identifies a meaningful difference between neighboring seeds.</span></div>
   <div class="guide-step"><strong>Close ranges</strong>
    <span>Close teams can be distributed across pools when the chosen format needs balance.</span></div>
  </div>
 </section>"""
    return f"""<section class="sheet">
 <header class="masthead">
  <div class="wordmark"><span class="mb">MatchBalance</span><span class="by">by PitchRank</span></div>
  <div class="stamp">Generated {html.escape(generated_on)}</div>
 </header>
 <div class="kicker">Tournament seeding guide</div>
 <h1 class="event">{html.escape(event_name)}</h1>
 <div class="facts">
  <div class="fact"><span class="label">Age group</span>
   <span class="value">{html.escape(sheet.age_group.upper())}</span></div>
  <div class="fact"><span class="label">Gender</span>
   <span class="value">{html.escape(_display_gender(sheet.gender))}</span></div>
  <div class="fact"><span class="label">Accepted teams</span><span class="value">{sheet.total_teams}</span></div>
  <div class="fact freshness"><span class="label">Ratings as of</span>
   <span class="value">{html.escape(ranking_run)}</span></div>
 </div>
 {guide}
 {tables}
 {notes}
 {diagnostics}
 <footer class="foot"><span>{html.escape(cohort)} | {sheet.total_teams} teams</span>
  <span>MatchBalance by PitchRank</span></footer>
</section>"""


def render_sheet_html(
    event_name: str, sheets: Sequence[CohortSheet], *, generated_on: str, ranking_run: str,
    policy: TierPolicy | None = None,
    operator_notes: Mapping[tuple[str, str], str] | None = None,
) -> str:
    """Render a selected cohort pack; each cohort starts a fresh printed page."""
    try:
        ranking_run = datetime.fromisoformat(ranking_run.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        pass
    body = "\n".join(
        _sheet_html(event_name, sheet, generated_on=generated_on, ranking_run=ranking_run,
                    policy=policy, operator_note=(operator_notes or {}).get((sheet.age_group, sheet.gender), ""))
        for sheet in sheets
    )
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(event_name)} - MatchBalance by PitchRank</title>
<style>
 {_font_css()}
 @page {{ size: letter; margin: 12mm 12mm 16mm; }}
 * {{ box-sizing: border-box; }}
 body {{ margin: 0; background: {BRAND["band"]}; font-family: "DM Sans", "Segoe UI", Arial, sans-serif;
 color: {BRAND["ink"]}; -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
 .sheet {{ background: white; max-width: 215.9mm; margin: 0 auto 10mm; padding: 12mm; }}
 .masthead {{ display: flex; justify-content: space-between; align-items: center; gap: 5mm;
 background: {BRAND["forest"]}; padding: 5mm 6mm; border-bottom: 3px solid {BRAND["yellow"]}; margin-bottom: 6mm; }}
 .wordmark {{ display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap; }}
 .mb {{ font-family: Oswald, "Arial Narrow", sans-serif; font-weight: 600; font-size: 23px;
 letter-spacing: .045em; text-transform: uppercase; color: white; }}
 .by {{ font-size: 9px; text-transform: uppercase; letter-spacing: .11em; color: {BRAND["yellow"]}; }}
 .stamp {{ font-size: 9px; color: white; white-space: nowrap; }}
 .kicker {{ font-size: 9px; letter-spacing: .15em; text-transform: uppercase; color: {BRAND["muted"]}; }}
 .event {{ font-family: Oswald, "Arial Narrow", sans-serif; font-size: 30px; font-weight: 600;
 line-height: 1.2; margin: 2mm 0 5mm; color: {BRAND["forest_deep"]}; overflow-wrap: anywhere; }}
 .facts {{ display: flex; gap: 10mm; border-top: 1px solid {BRAND["rule"]}; border-bottom: 2px solid {BRAND["forest"]};
 padding: 3mm 0; margin-bottom: 3mm; }}
 .fact {{ display: flex; flex-direction: column; gap: 2px; }}
 .label {{ font-size: 9px; text-transform: uppercase; letter-spacing: .10em; color: {BRAND["muted"]}; }}
 .value {{ font-family: Oswald, sans-serif; font-size: 21px; font-weight: 600; color: {BRAND["forest"]}; }}
 .freshness {{ margin-left: auto; }}
 .freshness .value {{ font-family: "DM Sans", sans-serif; font-size: 13px; padding-top: 6px; }}
 .summary {{ font-size: 11px; line-height: 1.5; margin: 0 0 5mm; }}
 .seed-guide {{ border: 1px solid {BRAND["rule"]}; border-left: 4px solid {BRAND["yellow"]};
 background: {BRAND["band"]}; padding: 3mm 4mm; margin: 0 0 4mm; }}
 .recommendation {{ font-family: Oswald, "Arial Narrow", sans-serif; font-size: 14px; font-weight: 600;
 color: {BRAND["forest_deep"]}; margin-bottom: 2mm; }}
 .seed-guide h2 {{ font-size: 11px; color: {BRAND["forest"]}; margin: 0 0 2mm; }}
 .guide-grid {{ display: flex; gap: 3mm; }}
 .guide-step {{ flex: 1; min-width: 0; border-left: 1px solid {BRAND["rule"]}; padding-left: 3mm; }}
 .guide-step:first-child {{ border-left: 0; padding-left: 0; }}
 .guide-step strong {{ display: block; font-size: 9px; line-height: 1.25; color: {BRAND["forest_deep"]}; }}
 .guide-step span {{ display: block; margin-top: 1mm; font-size: 8.5px; line-height: 1.3;
 color: {BRAND["muted"]}; }}
 .guide-foot {{ font-size: 8.5px; color: {BRAND["muted"]}; margin: 2mm 0 0; }}
 .manual-guide {{ font-size: 10px; line-height: 1.45; color: {BRAND["muted"]}; margin: 0; }}
 table.grid {{ width: 100%; border-collapse: collapse; table-layout: fixed; font-size: 11.5px; margin: 0 0 5mm; }}
 table.review {{ break-inside: avoid-page; page-break-inside: avoid; }}
 .seed-col {{ width: 10%; }} .team-col {{ width: 39%; }} .score-col {{ width: 15%; }}
 .state-col {{ width: 13%; }} .notes-col {{ width: 23%; }}
 .tier-heading th {{ text-align: left; border-top: 2px solid {BRAND["forest"]};
 border-bottom: 1px solid {BRAND["forest_deep"]}; padding: 7px; background: {BRAND["forest"]}; }}
 .tier-title {{ font-family: Oswald, sans-serif; font-size: 17px; color: white; }}
 .tier-purpose {{ margin-left: 8px; font-size: 9px; font-weight: 700; letter-spacing: .04em;
 text-transform: uppercase; color: {BRAND["yellow"]}; }}
 .count {{ margin-left: 10px; font-size: 10px; font-weight: 400; color: #DDEAE6; }}
 .cohort-tag {{ float: right; font-size: 9px; font-weight: 400; color: #DDEAE6; padding-top: 3px; }}
 .tier-description {{ margin-top: 3px; font-size: 9px; font-weight: 400; line-height: 1.4; color: #EAF3F0; }}
 .columns th {{ text-align: left; font-size: 8px; text-transform: uppercase; letter-spacing: .035em;
 padding: 7px 6px; border-bottom: 1px solid {BRAND["forest"]}; color: {BRAND["muted"]};
 background: #F0F5F3; }}
 table.grid td {{ padding: 5px 6px; border-bottom: 1px solid {BRAND["rule"]}; vertical-align: top;
 line-height: 1.35; overflow-wrap: anywhere; }}
 .pos {{ text-align: center; font-weight: 700; color: {BRAND["forest"]}; font-variant-numeric: tabular-nums; }}
 .team {{ font-weight: 700; }}
 .pitchrank-name {{ display: block; font-size: 9px; font-weight: 400; color: {BRAND["forest"]}; margin-top: 2px; }}
 .club {{ display: block; font-size: 9px; font-weight: 400; color: {BRAND["muted"]}; margin-top: 2px; }}
 .num {{ text-align: center; font-variant-numeric: tabular-nums; }}
 .columns th.num, .columns th.pos {{ text-align: center; }}
 .score {{ font-weight: 700; }}
 .flight {{ display: block; margin-top: 2px; font-size: 8px; line-height: 1.25; font-weight: 400;
 color: {BRAND["muted"]}; }}
 .state, .placement {{ font-size: 9.5px; }}
 .placement {{ color: {BRAND["muted"]}; }}
 .boundary-note {{ color: {BRAND["forest_deep"]}; font-weight: 700; background: #FFF9DB; }}
 .flag {{ display: inline-block; margin-left: 5px; border: 1px solid {BRAND["rule"]}; border-radius: 2px;
 padding: 1px 3px; font-size: 8px; font-weight: 400; }}
 .play-up {{ display: inline-block; margin-left: 5px; border-radius: 2px; background: #E6F2EF;
 color: {BRAND["forest_deep"]}; padding: 1px 4px; font-size: 8px; font-weight: 700; }}
 .review .tier-heading th {{ border-top: 2px solid {BRAND["yellow"]}; border-bottom-color: #D8C56A;
 background: #FFF8D9; }}
 .review .tier-title {{ color: {BRAND["forest_deep"]}; }}
 .review .count, .review .cohort-tag, .review .tier-description {{ color: {BRAND["muted"]}; }}
 .guidance {{ border: 1px solid #E7DB9A; border-left: 3px solid {BRAND["yellow"]};
 background: #FFFCED; padding: 3mm 4mm; margin: 4mm 0; }}
 .guidance h2 {{ font-size: 11px; color: {BRAND["forest"]}; margin: 0 0 2mm; }}
 .guidance ul {{ margin: 0; padding-left: 4mm; font-size: 10px; line-height: 1.5; }}
 .guidance li {{ margin-bottom: 1.5mm; }}
 .diagnostics {{ margin: 4mm 0; font-size: 9px; color: {BRAND["muted"]}; }}
 .diagnostics summary {{ cursor: pointer; color: {BRAND["forest"]}; font-weight: 700; }}
 .diagnostics ul {{ margin: 2mm 0 0; padding-left: 5mm; line-height: 1.45; }}
 .method {{ font-size: 9px; line-height: 1.5; color: {BRAND["muted"]}; margin: 0 0 4mm; }}
 .foot {{ display: flex; justify-content: space-between; gap: 5mm; border-top: 1px solid {BRAND["rule"]};
 margin-top: 4mm; padding-top: 3mm; font-size: 9px; color: {BRAND["muted"]}; }}
 @media print {{
 body {{ background: white; }}
 .sheet {{ max-width: none; margin: 0; padding: 0; break-after: page; }}
 .sheet:last-child {{ break-after: auto; }}
 .foot {{ display: none; }}
 table.grid thead {{ display: table-header-group; }}
 table.grid tr {{ break-inside: avoid; page-break-inside: avoid; }}
 .masthead, .facts, .seed-guide, .guide-step, .guidance li, .foot {{ break-inside: avoid; }}
 .event, .kicker, .summary, .seed-guide h2, .guidance h2 {{ break-after: avoid; }}
 p {{ orphans: 3; widows: 3; }}
 }}
</style></head><body>{body}</body></html>"""
