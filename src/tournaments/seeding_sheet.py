"""Build printable tournament cheat sheets, with optional matchup-based tiers.

Every accepted entrant appears once, including teams needing placement review.
Cohorts begin on fresh Letter pages; long tier tables repeat their headings.
The same standalone, offline-ready HTML powers the preview and PDF export.

The published ``power_score_final`` is displayed and sorts teams within tiers.
The matchup analysis determines tier membership and order.

A team counts as ranked when PitchRank publishes a rank for it. An Inactive team
does not qualify: it is left out of the ranking views entirely and keeps only a
stale PowerScore, with neither a national nor a state rank. Such a team sits
below the line with its score still shown, rather than appearing among ranked
teams with an empty rank beside its name.

State rank comes from ``state_rankings_view``. ``rankings_full.state_rank`` is
always NULL, because the views compute the published ranks.
"""

from __future__ import annotations

import base64
import html
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

from src.tournaments.roster_paste import RosterRow
from src.tournaments.roster_resolver import ResolvedTeam

if TYPE_CHECKING:
    from src.tournaments.seeding_tiers import TierAnalysis, TierPolicy

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


@dataclass(frozen=True)
class CohortSheet:
    age_group: str
    gender: str
    rated: tuple[SheetTeam, ...]
    unrated: tuple[SheetTeam, ...]
    tier_analysis: TierAnalysis | None = None

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


def build_cohort_sheets(
    rows: Sequence[RosterRow],
    resolved: Sequence[ResolvedTeam],
    overrides: Mapping[int, dict[str, Any]],
    ratings: Mapping[str, dict[str, Any]],
    *,
    tier_analyses: Mapping[tuple[str, str], TierAnalysis] | None = None,
) -> tuple[CohortSheet, ...]:
    """Group a resolved roster into one sheet per cohort, strongest first.

    A team we hold a rating for is shown under the name we hold, not the name
    the roster used: the two often differ, and the stored name is the one a
    director will find if they look the team up.
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
        team = SheetTeam(
            team_name=str(rating.get("team_name") or row.team_name_stripped),
            club_name=str(rating.get("club_name") or row.club_raw),
            power_score=score,
            state_rank=rating.get("rank_in_state_final"),
            state=str(rating["state"]).strip() if rating.get("state") else None,
            status=rating.get("status"),
            entrant_id=str(row.source_index),
            team_id_master=team_id,
            review_reason=analysis.review.get(str(row.source_index)) if analysis else None,
        )
        if rating.get("rank_in_cohort_final") is not None and score is not None:
            grouped[cohort].append(team)
        else:
            unrated[cohort].append(team)

    sheets = []
    for cohort in sorted(grouped, key=lambda key: (-_age_sort_key(key[0]), key[1])):
        rated = sorted(grouped[cohort], key=lambda team: team.power_score or 0.0, reverse=True)
        sheets.append(
            CohortSheet(
                age_group=cohort[0],
                gender=cohort[1],
                rated=tuple(rated),
                unrated=tuple(sorted(unrated[cohort], key=lambda team: team.team_name.lower())),
                tier_analysis=(tier_analyses or {}).get(cohort),
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
                .select("team_id_master,team_name,club_name")
                .in_("team_id_master", batch)
                .execute()
                .data
                or []
            ):
                ratings.setdefault(str(row["team_id_master"]), {}).update(
                    {"team_name": row.get("team_name"), "club_name": row.get("club_name")}
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
        flag = (
            f'<span class="flag">{html.escape(str(team.status))}</span>'
            if team.status and team.status != "Active" else ""
        )
        note = (placement_notes or {}).get(team.entrant_id) or team.review_reason or ""
        cells.append(
            f'<tr data-entrant="{html.escape(team.entrant_id, quote=True)}">'
            f'<td class="pos">{position if numbered else "-"}</td>'
            f'<td class="team">{html.escape(team.team_name)}{flag}'
            f'<span class="club">{html.escape(team.club_name)}</span></td>'
            f'<td class="num score">{_score(team.power_score)}</td>'
            f'<td class="num state">{html.escape(_state_rank(team))}</td>'
            f'<td class="placement">{html.escape(note)}</td></tr>'
        )
    return "".join(cells)


def _table_html(title: str, teams: Sequence[SheetTeam], *, numbered: bool, start: int = 1,
                subtitle: str = "", placement_notes: Mapping[str, str] | None = None,
                review: bool = False, cohort_label: str = "") -> str:
    summary = f'<div class="tier-description">{html.escape(subtitle)}</div>' if subtitle else ""
    return (
        f'<table class="grid{" review" if review else ""}">'
        '<colgroup><col class="seed-col"><col class="team-col"><col class="score-col">'
        '<col class="state-col"><col class="notes-col"></colgroup><thead>'
        f'<tr class="tier-heading"><th colspan="5"><span class="tier-title">{html.escape(title)}</span>'
        f'<span class="count">{len(teams)} {"team" if len(teams) == 1 else "teams"}</span>'
        f'<span class="cohort-tag">{html.escape(cohort_label)}</span>{summary}</th></tr>'
        '<tr class="columns"><th class="pos">Seed</th><th>Team / club</th>'
        '<th class="num">PowerScore</th><th class="num">State rank</th><th>Placement notes</th></tr>'
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
            description = "One team; no within-tier matchup to assess. Review its flight placement."
        else:
            description = (
                f"Widest expected goal gap: {tier.max_expected_margin:.1f} | "
                f"Highest chance of a 4+ goal margin: {tier.max_blowout_probability:.0%}"
            )
        notes = {
            entrant_id: "Borderline: also fits " + ", ".join(f"Tier {n}" for n in alternatives) + "."
            for entrant_id, alternatives in analysis.borderline.items() if alternatives
        }
        parts.append(_table_html(f"Tier {tier.number}", members, numbered=True, start=start,
                                 subtitle=description, placement_notes=notes, cohort_label=cohort_label))
        start += len(members)

    review_teams = [team for team in all_teams if team.entrant_id not in set(tier_ids)]
    if review_teams:
        reasons = {
            team.entrant_id: analysis.review.get(team.entrant_id) or team.review_reason
            or "Placement has not been assessed."
            for team in review_teams
        }
        parts.append(_table_html("Needs placement review", review_teams, numbered=False, review=True,
                                 subtitle="These teams are included in the field but have no recommended tier.",
                                 placement_notes=reasons, cohort_label=cohort_label))
    number = len([tier for tier in analysis.tiers if tier.entrant_ids])
    summary = f"{start - 1} teams in {number} suggested {('tier' if number == 1 else 'tiers')}"
    if review_teams:
        summary += f"; {len(review_teams)} need placement review"
    summary += ". Check the tier boundaries before assigning flights or pools."
    return "\n".join(parts), summary


def _sheet_html(
    event_name: str, sheet: CohortSheet, *, generated_on: str, ranking_run: str,
    policy: TierPolicy | None = None, operator_note: str = "",
) -> str:
    cohort = f"{_display_gender(sheet.gender)} {sheet.age_group.upper()}"
    analysis = sheet.tier_analysis
    if analysis is not None:
        tables, summary = _tier_tables(sheet)
    else:
        tables = _table_html("Ranked Teams", sheet.rated, numbered=True, cohort_label=cohort)
        if sheet.unrated:
            tables += _table_html("Unranked Teams", sheet.unrated, numbered=False, review=True,
                                  subtitle="PitchRank publishes no rank for these teams. Seed them by judgement.",
                                  cohort_label=cohort)
        summary = "Teams ordered by published PowerScore. Unranked teams need placement review."
    guidance = []
    if analysis is not None:
        guidance.extend(str(value) for value in analysis.boundaries)
        guidance.extend(str(value) for value in analysis.warnings)
    if operator_note.strip():
        guidance.append(operator_note.strip())
    notes = ""
    if guidance:
        items = "".join(f"<li>{html.escape(value)}</li>" for value in dict.fromkeys(guidance))
        notes = f'<aside class="guidance"><h2>Placement guidance</h2><ul>{items}</ul></aside>'
    explanation = "PowerScore uses the published 0-100 scale. Rankings are specific to each age group and gender."
    if analysis is not None:
        explanation = (
            "Tiers compare this tournament field using expected match competitiveness, not PowerScore gaps. "
            "Predictions are estimates; tiers guide placement and do not guarantee close games."
        )
        if policy is not None:
            explanation += (
                f" Suggested limits: expected goal gap up to {policy.max_expected_margin:g}; "
                f"chance of a 4+ goal margin up to {policy.max_blowout_probability:.0%}."
            )
    return f"""<section class="sheet">
 <header class="masthead">
  <div class="wordmark"><span class="mb">MatchBalance</span><span class="by">by PitchRank</span></div>
  <div class="stamp">Generated {html.escape(generated_on)}</div>
 </header>
 <div class="kicker">Tournament seeding cheat sheet</div>
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
 <p class="summary">{html.escape(summary)}</p>
 <p class="method">{html.escape(explanation)}</p>
 {tables}
 {notes}
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
 table.grid {{ width: 100%; border-collapse: collapse; table-layout: fixed; font-size: 11.5px; margin: 0 0 5mm; }}
 .seed-col {{ width: 7%; }} .team-col {{ width: 42%; }} .score-col {{ width: 13%; }}
 .state-col {{ width: 14%; }} .notes-col {{ width: 24%; }}
 .tier-heading th {{ text-align: left; border-top: 2px solid {BRAND["forest"]};
 border-bottom: 1px solid {BRAND["rule"]};
 padding: 7px; background: {BRAND["band"]}; }}
 .tier-title {{ font-family: Oswald, sans-serif; font-size: 16px; color: {BRAND["forest_deep"]}; }}
 .count {{ margin-left: 10px; font-size: 10px; font-weight: 400; color: {BRAND["muted"]}; }}
 .cohort-tag {{ float: right; font-size: 9px; font-weight: 400; color: {BRAND["muted"]}; padding-top: 3px; }}
 .tier-description {{ margin-top: 3px; font-size: 9px; font-weight: 400; line-height: 1.4; color: {BRAND["muted"]}; }}
 .columns th {{ text-align: left; font-size: 8px; text-transform: uppercase; letter-spacing: .035em;
 padding: 7px 6px; border-bottom: 1px solid {BRAND["forest"]}; color: {BRAND["muted"]}; }}
 table.grid td {{ padding: 5px 6px; border-bottom: 1px solid {BRAND["rule"]}; vertical-align: top;
 line-height: 1.35; overflow-wrap: anywhere; }}
 .pos {{ text-align: center; font-weight: 700; color: {BRAND["forest"]}; font-variant-numeric: tabular-nums; }}
 .team {{ font-weight: 700; }}
 .club {{ display: block; font-size: 9px; font-weight: 400; color: {BRAND["muted"]}; margin-top: 2px; }}
 .num {{ text-align: center; font-variant-numeric: tabular-nums; }}
 .columns th.num, .columns th.pos {{ text-align: center; }}
 .score {{ font-weight: 700; }}
 .state, .placement {{ font-size: 9.5px; }}
 .placement {{ color: {BRAND["muted"]}; }}
 .flag {{ display: inline-block; margin-left: 5px; border: 1px solid {BRAND["rule"]}; border-radius: 2px;
 padding: 1px 3px; font-size: 8px; font-weight: 400; }}
 .review .tier-heading th {{ border-top-style: dashed; background: #FAF8EE; }}
 .guidance {{ border-left: 3px solid {BRAND["yellow"]}; padding-left: 4mm; margin: 4mm 0; }}
 .guidance h2 {{ font-size: 11px; color: {BRAND["forest"]}; margin: 0 0 2mm; }}
 .guidance ul {{ margin: 0; padding-left: 4mm; font-size: 10px; line-height: 1.5; }}
 .guidance li {{ margin-bottom: 1.5mm; }}
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
 .masthead, .facts, .guidance li, .foot {{ break-inside: avoid; }}
 .event, .kicker, .summary, .guidance h2 {{ break-after: avoid; }}
 p {{ orphans: 3; widows: 3; }}
 }}
</style></head><body>{body}</body></html>"""
