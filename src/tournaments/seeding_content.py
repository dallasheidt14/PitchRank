"""One offline content model for the operator, HTML/PDF, and Excel sheets."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Mapping, Sequence

from src.tournaments.seeding_tiers import DATA_REVIEW, NO_CURRENT_RATING, SEEDED
from src.utils.us_states import STATE_CODE_TO_NAME, state_name_to_code

if TYPE_CHECKING:
    from src.tournaments.seeding_sheet import CohortSheet, SheetTeam

CONTENT_VERSION = 6
DIRECTOR_LEGEND = (
    "Start with the numbered MatchBalance Seed order. PowerScore remains the original published-strength "
    "baseline; bars use the same 0-100 scale. Competitive Breaks mark boundaries where nearby projected "
    "matchups meaningfully worsen; the PowerScore difference is supporting context; they do not assign "
    "divisions or pools. Recommended tier breaks use practical division sizes and all potential matchups. "
    "A tier can contain multiple pools. Very-close ranges identify the same competitive "
    "neighborhood without claiming the teams are equal."
)
LIMITED_HISTORY_LEGEND = "Fewer ranked games support this score. Keep it as a starting point for placement."


@dataclass(frozen=True)
class DirectorRow:
    seed: int | None
    team: SheetTeam
    observation: str
    placement_status: str
    strength_break_after: bool = False
    power_score_seed: int | None = None
    matchbalance_seed: int | None = None
    manual_override: bool = False
    movement: str = ""
    close_range_after: str = ""
    tier_label: str = ""
    break_label: str = ""

    @property
    def score(self) -> float | None:
        return self.team.power_score * 100 if self.team.power_score is not None else None

    @property
    def evidence_note(self) -> str:
        return "Limited history" if self.seed is not None and self.team.status == "Not Enough Ranked Games" else ""

    @property
    def display_status(self) -> str:
        return " · ".join(value for value in (self.placement_status, self.evidence_note) if value)

    @property
    def state_rank(self) -> str:
        team = self.team
        if team.state_rank is None:
            return ""
        return format_state_rank(team.state, team.state_rank)

    @property
    def roster_context(self) -> tuple[str, ...]:
        team = self.team
        context = []
        if team.plays_up:
            context.append(
                f"Plays up from {team.play_up_from_age_group.upper()}"
                if team.play_up_from_age_group else "Plays up"
            )
        if team.requested_flight:
            context.append(f"Requested: {team.requested_flight}")
        if team.listed_division:
            context.append(f"Listed: {team.listed_division}")
        return tuple(context)

    @property
    def name_lines(self) -> tuple[str, ...]:
        secondary = (f"PitchRank: {self.team.pitchrank_team_name}",) if self.team.pitchrank_team_name else ()
        return (self.team.team_name, *secondary, *self.roster_context)


@dataclass(frozen=True)
class DirectorCohort:
    rows: tuple[DirectorRow, ...]
    notes: tuple[str, ...]
    guidance_summary: str = ""

    @property
    def seeded(self) -> tuple[DirectorRow, ...]:
        return tuple(row for row in self.rows if row.seed is not None)

    @property
    def unseeded(self) -> tuple[DirectorRow, ...]:
        return tuple(row for row in self.rows if row.seed is None)


def format_state_rank(state: str | None, rank: int) -> str:
    """Use one compact state label even when Compare returns a full name."""
    value = str(state or "").strip()
    code = state_name_to_code(value)
    if not code and value.upper() in STATE_CODE_TO_NAME:
        code = value.upper()
    return f"{code or value} #{rank}" if value else f"#{rank}"


def build_director_cohort(sheet: CohortSheet, operator_note: str = "") -> DirectorCohort:
    """Preserve every entrant exactly once; never infer equivalence from limits."""
    analysis = sheet.tier_analysis
    teams = (*sheet.rated, *sheet.unrated)
    by_id = {team.entrant_id: team for team in teams}
    if len(by_id) != len(teams) or (analysis is not None and "" in by_id):
        raise ValueError("Cheat sheet requires a unique entrant ID for every roster row.")
    if analysis is None:
        seeded, unseeded = sheet.rated, sheet.unrated
        statuses, markers, breaks = {}, {}, set()
    else:
        ordered = analysis.ordered_ids
        ordered_set = set(ordered)
        manual_override = bool(getattr(analysis, "manual_override", False))
        if len(ordered) != len(ordered_set) or (
            ordered_set & set(analysis.review) and not manual_override
        ):
            raise ValueError("Cheat sheet analysis contains duplicate or overlapping entrant IDs.")
        if (ordered_set | set(analysis.review)) - set(by_id):
            raise ValueError("Cheat sheet analysis contains a team outside this cohort.")
        legacy_ids = [item for tier in getattr(analysis, "tiers", ()) for item in tier.entrant_ids]
        if len(legacy_ids) != len(set(legacy_ids)) or set(legacy_ids) & set(analysis.review):
            raise ValueError("Cheat sheet legacy reference contains duplicate or overlapping entrant IDs.")
        seeded = tuple(by_id[item] for item in ordered)
        unseeded = tuple(team for team in teams if team.entrant_id not in ordered_set)
        statuses = getattr(analysis, "placement_status", {})
        breaks = {item.after_seed for item in getattr(analysis, "breaks", ())}
        markers = {seed: analysis.marker_for_seed(seed) for seed in breaks}
    baseline_sequence = (
        getattr(analysis, "baseline_order", ()) or analysis.ordered_ids
        if analysis is not None else ()
    )
    suggested_sequence = (
        getattr(analysis, "suggested_order", ()) or analysis.ordered_ids
        if analysis is not None else ()
    )
    baseline_seeds = {
        entrant_id: seed for seed, entrant_id in enumerate(baseline_sequence, 1)
    }
    matchbalance_seeds = {
        entrant_id: seed for seed, entrant_id in enumerate(suggested_sequence, 1)
    }
    close_after = {
        item.end_seed: f"Very close: seeds {item.start_seed}-{item.end_seed}"
        for item in getattr(analysis, "close_ranges", ())
    } if analysis is not None else {}
    rows = []
    guidance = getattr(analysis, "tier_guidance", {}) if analysis else {}
    divisions = guidance.get("divisions", [])
    practical = set(guidance.get("cuts", []))
    for seed, team in enumerate(seeded, 1):
        original = baseline_seeds.get(team.entrant_id)
        suggested = matchbalance_seeds.get(team.entrant_id)
        movement = ""
        if original is None:
            movement = "Manual placement"
        else:
            displayed_seed = seed if manual_override else suggested
            if displayed_seed is not None and displayed_seed != original:
                arrow = "↑" if displayed_seed < original else "↓"
                movement = f"{arrow} from PowerScore #{original}"
        if analysis is not None and manual_override and suggested != seed:
            manual_detail = f"Manual from MatchBalance #{suggested}" if suggested is not None else "Manual placement"
            movement = " · ".join(value for value in (movement, manual_detail) if value)
        status = statuses.get(team.entrant_id, SEEDED)
        tier = next((item["label"] for item in divisions
                     if item["start_seed"] <= seed <= item["end_seed"]), "")
        break_label = (
            "Recommended tier break + natural strength separation" if seed in practical and seed in breaks else
            "Recommended tier break" if seed in practical else
            "Competitive Break: natural strength separation" if seed in breaks else ""
        )
        rows.append(DirectorRow(
            seed,
            team,
            markers.get(seed, ""),
            status,
            seed in breaks or seed in practical,
            original,
            suggested,
            bool(analysis and manual_override),
            movement,
            close_after.get(seed, ""),
            tier,
            break_label,
        ))
    for team in unseeded:
        status = statuses.get(team.entrant_id) or (
            DATA_REVIEW if analysis is not None
            else NO_CURRENT_RATING
        )
        rows.append(DirectorRow(None, team, "", status))
    # The same concise guidance and full accepted roster feed every export.
    notes = []
    guidance_summary = ""
    if divisions:
        qualifier = ("Review-required compromise"
                     if guidance.get("status") == "review_required_compromise" else "Suggested tiers")
        guidance_summary = qualifier + ": " + " + ".join(str(item["size"]) for item in divisions) + " teams."
        notes.append(qualifier + ": " + "; ".join(
            f"{item['label']}: seeds {item['start_seed']}-{item['end_seed']} "
            f"({item['size']} teams; compatible pools {' + '.join(map(str, item['pool_sizes']))}; "
            f"minimum {item['minimum_games']} games)"
            for item in divisions
        ) + ". Pool memberships remain the director's decision.")
    notes.extend(guidance.get("warnings", []))
    if guidance.get("alternative_sizes"):
        alternative = guidance.get("alternative") or {}
        tradeoffs = []
        for field, label in (("worst_matchup_cost_delta", "worst matchup cost"),
                             ("pair_weighted_average_matchup_cost_delta", "average matchup cost")):
            delta = alternative.get(field)
            if delta is not None and delta != 0:
                tradeoffs.append(("lower " if delta < 0 else "higher ") + label)
        if alternative.get("additional_flight_count", 0) > 0:
            tradeoffs.append("more divisions to schedule")
        notes.append("Alternative split: " + " + ".join(map(str, guidance["alternative_sizes"]))
                     + " teams" + ("; " + ", ".join(tradeoffs) if tradeoffs else "") + ".")
    if guidance:
        notes.append("Formats use the saved MatchBalance profile; confirm game guarantees and event logistics.")
    if sheet.delivery_note:
        notes.append(sheet.delivery_note)
    if operator_note.strip():
        notes.append(operator_note.strip())
    return DirectorCohort(tuple(rows), tuple(dict.fromkeys(notes)), guidance_summary)


def export_fingerprint(
    event_name: str, sheets: Sequence[CohortSheet], *, generated_on: str, ranking_run: str,
    operator_notes: Mapping[tuple[str, str], str], analysis_version: int, policy: Mapping[str, float],
) -> str:
    """Both downloads share one identity, independent of XLSX ZIP timestamps."""
    payload = {
        "content_version": CONTENT_VERSION, "analysis_version": analysis_version,
        "event": event_name, "generated_on": generated_on, "ranking_run": ranking_run,
        "policy": dict(policy), "legend": DIRECTOR_LEGEND,
        "cohorts": [{
            "age": sheet.age_group, "gender": sheet.gender,
            "content": asdict(build_director_cohort(
                sheet, operator_notes.get((sheet.age_group, sheet.gender), ""),
            )),
        } for sheet in sheets],
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()
