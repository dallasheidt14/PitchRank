"""Build the printable cohort sheet for a seeding roster.

One page per cohort, teams strongest first, with anything we hold no rating for
held below a rule at the foot of the page. The page is a standalone HTML
document carrying PitchRank's own type and colour, sized for Letter, so the
browser's "Save as PDF" produces the designed page rather than a screenshot of
a web app.

``power_score_final`` is the number shown, because that is what the site
publishes and what a director comparing this against a team page would see.
Ordering is within a cohort only, where ``power_score_final`` and
``power_score_true`` rank identically: the anchor that separates them is
constant for a given age group.
"""

from __future__ import annotations

import html
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from src.tournaments.roster_paste import RosterRow
from src.tournaments.roster_resolver import ResolvedTeam

__all__ = [
    "BRAND",
    "CohortSheet",
    "SheetTeam",
    "build_cohort_sheets",
    "fetch_ranking_run_date",
    "make_ratings_lookup",
    "render_sheet_html",
]

_FONT_HREF = (
    "https://fonts.googleapis.com/css2"
    "?family=Oswald:wght@500;600;700"
    "&family=DM+Sans:wght@400;500;700&display=swap"
)

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
    ranked_games: int | None = None
    status: str | None = None


@dataclass(frozen=True)
class CohortSheet:
    age_group: str
    gender: str
    rated: tuple[SheetTeam, ...]
    unrated: tuple[SheetTeam, ...]

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
) -> tuple[CohortSheet, ...]:
    """Group a resolved roster into one sheet per cohort, strongest first.

    A team we hold a rating for is shown under the name we hold, not the name
    the roster used: the two often differ, and the stored name is the one a
    director will find if they look the team up.
    """
    by_index = {item.source_index: item for item in resolved}
    grouped: dict[tuple[str, str], list[SheetTeam]] = {}
    unrated: dict[tuple[str, str], list[SheetTeam]] = {}

    for row in rows:
        cohort = (row.section_age_group, row.section_gender)
        grouped.setdefault(cohort, [])
        unrated.setdefault(cohort, [])

        team_id = _team_id_for(row, by_index.get(row.source_index), overrides)
        rating = ratings.get(team_id) if team_id else None

        if rating and rating.get("power_score_final") is not None:
            grouped[cohort].append(
                SheetTeam(
                    team_name=str(rating.get("team_name") or row.team_name_stripped),
                    club_name=str(rating.get("club_name") or row.club_raw),
                    power_score=float(rating["power_score_final"]),
                    ranked_games=rating.get("games_played"),
                    status=rating.get("status"),
                )
            )
        else:
            unrated[cohort].append(
                SheetTeam(
                    team_name=str((rating or {}).get("team_name") or row.team_name_stripped),
                    club_name=str((rating or {}).get("club_name") or row.club_raw),
                )
            )

    sheets = []
    for cohort in sorted(grouped, key=lambda key: (-_age_sort_key(key[0]), key[1])):
        rated = sorted(grouped[cohort], key=lambda team: team.power_score or 0.0, reverse=True)
        sheets.append(
            CohortSheet(
                age_group=cohort[0],
                gender=cohort[1],
                rated=tuple(rated),
                unrated=tuple(sorted(unrated[cohort], key=lambda team: team.team_name.lower())),
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
                .select("team_id,power_score_final,games_played,status")
                .in_("team_id", batch)
                .execute()
                .data
                or []
            ):
                ratings[str(row["team_id"])] = dict(row)
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


def _score(value: float | None) -> str:
    return f"{value:.3f}" if value is not None else "—"


def _rows_html(teams: Sequence[SheetTeam], *, numbered: bool) -> str:
    cells = []
    for position, team in enumerate(teams, start=1):
        flag = (
            f'<span class="flag">{html.escape(str(team.status))}</span>'
            if team.status and team.status != "Active"
            else ""
        )
        cells.append(
            "<tr>"
            f'<td class="pos">{position if numbered else "—"}</td>'
            f'<td class="team">{html.escape(team.team_name)}{flag}</td>'
            f'<td class="club">{html.escape(team.club_name)}</td>'
            f'<td class="num">{_score(team.power_score)}</td>'
            f'<td class="num">{team.ranked_games if team.ranked_games is not None else "—"}</td>'
            "</tr>"
        )
    return "".join(cells)


def _sheet_html(event_name: str, sheet: CohortSheet, *, generated_on: str, ranking_run: str) -> str:
    cohort = f"{_display_gender(sheet.gender)} {sheet.age_group.upper()}"
    unrated_block = ""
    if sheet.unrated:
        unrated_block = (
            '<div class="cut"><span>Unranked Teams</span></div>'
            '<table class="grid unrated"><tbody>'
            f"{_rows_html(sheet.unrated, numbered=False)}"
            "</tbody></table>"
            '<p class="note">These teams have no games in our ranking window, so they carry no PowerScore. '
            "Seed them by judgement, or send them for a scrape and run this again.</p>"
        )

    return f"""<section class="sheet">
 <header class="masthead">
  <div class="wordmark"><span class="mb">MatchBalance</span><span class="by">by PitchRank</span></div>
  <div class="stamp">Generated {html.escape(generated_on)}</div>
 </header>
 <h1 class="event">{html.escape(event_name)}</h1>
 <div class="facts">
  <div class="fact"><span class="label">Age group</span>
   <span class="value">{html.escape(sheet.age_group.upper())}</span></div>
  <div class="fact"><span class="label">Gender</span>
   <span class="value">{html.escape(_display_gender(sheet.gender))}</span></div>
  <div class="fact"><span class="label">Teams</span><span class="value">{sheet.total_teams}</span></div>
 </div>
 <h2 class="group">Ranked Teams<span class="count">{len(sheet.rated)}</span></h2>
 <table class="grid">
  <thead><tr>
   <th class="pos">#</th><th>Team</th><th>Club</th>
   <th class="num">PowerScore</th><th class="num">Ranked games</th>
  </tr></thead>
  <tbody>{_rows_html(sheet.rated, numbered=True)}</tbody>
 </table>
 {unrated_block}
 <footer class="foot">
  <span>{html.escape(cohort)} · {sheet.total_teams} teams</span>
  <span>Ratings as of {html.escape(ranking_run)}</span>
 </footer>
</section>"""


def render_sheet_html(
    event_name: str,
    sheets: Sequence[CohortSheet],
    *,
    generated_on: str,
    ranking_run: str,
) -> str:
    """Render every cohort into one standalone, print-ready document."""
    body = "\n".join(
        _sheet_html(event_name, sheet, generated_on=generated_on, ranking_run=ranking_run) for sheet in sheets
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{html.escape(event_name)} — MatchBalance by PitchRank</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="{_FONT_HREF}">
<style>
 @page {{ size: letter; margin: 14mm 12mm; }}
 * {{ box-sizing: border-box; }}
 body {{
   margin: 0; background: {BRAND["band"]};
   font-family: "DM Sans", -apple-system, "Segoe UI", Helvetica, Arial, sans-serif;
   color: {BRAND["ink"]}; -webkit-print-color-adjust: exact; print-color-adjust: exact;
 }}
 .sheet {{
   background: {BRAND["paper"]}; max-width: 200mm; margin: 0 auto 10mm; padding: 12mm 12mm 10mm;
 }}
 .masthead {{
   display: flex; justify-content: space-between; align-items: center;
   background: {BRAND["forest"]}; margin: -12mm -12mm 8mm; padding: 7mm 12mm;
   border-bottom: 3px solid {BRAND["yellow"]};
 }}
 .wordmark {{ display: flex; align-items: baseline; gap: 8px; }}
 .mb {{
   font-family: Oswald, "DM Sans", sans-serif; font-weight: 700; font-size: 21px;
   letter-spacing: .10em; text-transform: uppercase; color: {BRAND["paper"]};
 }}
 .by {{ font-size: 10px; letter-spacing: .18em; text-transform: uppercase; color: {BRAND["yellow"]}; }}
 .stamp {{ font-size: 10px; letter-spacing: .06em; color: #C7D6D1; }}
 .event {{
   font-family: Oswald, "DM Sans", sans-serif; font-weight: 600; font-size: 30px; line-height: 1.1;
   margin: 0 0 6mm; color: {BRAND["forest_deep"]};
 }}
 .facts {{
   display: flex; gap: 10mm; padding: 4mm 0 5mm; margin-bottom: 6mm;
   border-top: 1px solid {BRAND["rule"]}; border-bottom: 2px solid {BRAND["forest"]};
 }}
 .fact {{ display: flex; flex-direction: column; gap: 3px; }}
 .label {{
   font-size: 9px; letter-spacing: .16em; text-transform: uppercase; color: {BRAND["muted"]};
 }}
 .value {{ font-family: Oswald, sans-serif; font-weight: 600; font-size: 20px; color: {BRAND["forest"]}; }}
 table.grid {{ width: 100%; border-collapse: collapse; font-size: 11.5px; }}
 table.grid thead th {{
   text-align: left; font-size: 9px; letter-spacing: .14em; text-transform: uppercase;
   color: {BRAND["muted"]}; padding: 0 6px 5px; border-bottom: 1.5px solid {BRAND["forest"]};
 }}
 table.grid td {{ padding: 6px; border-bottom: 1px solid {BRAND["rule"]}; vertical-align: baseline; }}
 table.grid tbody tr:nth-child(even) td {{ background: #FAFCFB; }}
 .pos {{
   width: 26px; text-align: right; color: {BRAND["forest"]};
   font-family: Oswald, sans-serif; font-weight: 600;
 }}
 .team {{ font-weight: 500; }}
 .club {{ color: {BRAND["muted"]}; }}
 .num {{ text-align: right; width: 72px; font-variant-numeric: tabular-nums; }}
 thead th.num {{ text-align: right; }}
 .flag {{
   display: inline-block; margin-left: 6px; padding: 1px 5px; border-radius: 2px;
   background: {BRAND["yellow"]}; color: {BRAND["forest_deep"]};
   font-size: 8px; letter-spacing: .10em; text-transform: uppercase; font-weight: 700;
 }}
 .group {{
   font-family: Oswald, sans-serif; font-weight: 600; font-size: 12px; letter-spacing: .16em;
   text-transform: uppercase; color: {BRAND["forest"]}; margin: 0 0 3mm;
   display: flex; align-items: center; gap: 8px;
 }}
 .group .count {{
   font-family: "DM Sans", sans-serif; font-weight: 700; font-size: 9px; letter-spacing: .06em;
   background: {BRAND["forest"]}; color: {BRAND["paper"]}; border-radius: 9px; padding: 2px 7px;
 }}
 .cut {{ display: flex; align-items: center; gap: 8px; margin: 7mm 0 3mm; }}
 .cut::before, .cut::after {{ content: ""; flex: 1; border-top: 1.5px dashed {BRAND["forest"]}; }}
 .cut span {{
   font-size: 9px; letter-spacing: .16em; text-transform: uppercase;
   color: {BRAND["forest"]}; font-weight: 700;
 }}
 table.unrated td {{ color: {BRAND["muted"]}; }}
 .note {{ font-size: 9.5px; color: {BRAND["muted"]}; margin: 3mm 0 0; }}
 .foot {{
   display: flex; justify-content: space-between; margin-top: 8mm; padding-top: 3mm;
   border-top: 1px solid {BRAND["rule"]}; font-size: 9px; letter-spacing: .06em; color: {BRAND["muted"]};
 }}
 @media print {{
   body {{ background: {BRAND["paper"]}; }}
   .sheet {{ margin: 0; max-width: none; padding: 0; page-break-after: always; }}
   .sheet:last-child {{ page-break-after: auto; }}
   .masthead {{ margin: 0 0 8mm; padding: 6mm 8mm; }}
   table.grid thead {{ display: table-header-group; }}
   table.grid tr {{ page-break-inside: avoid; }}
 }}
</style>
</head>
<body>
{body}
</body>
</html>"""
