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

CONTENT_VERSION = 21

REVIEW_LABELS = {
    "ratings_outdated": "Waiting for updated rankings",
    "invalid_team_metadata": "Correct team age or gender",
    "identity_review": "Confirm this team's identity",
    "team_not_found": "Confirm this team's identity",
    "duplicate_entry": "Check duplicate roster entries",
    "game_records_review": "Check duplicate game records",
    "metadata_conflict": "PitchRank data needs review",
    "data_review": "PitchRank data needs review",
}
LIMITED_HISTORY_LEGEND = (
    "Limited history: We have too few usable recent results to confidently judge this team's level. "
    "Please check recent results or ask the coach before assigning a division. "
    'This means "take a closer look," not "this is a weak team."'
)


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
    recommendation_reason: str = ""

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
    def director_review_reason(self) -> str:
        """Translate known operational conditions without hiding unknown review warnings."""
        reason = self.team.review_reason or ""
        kind = self.team.review_kind
        if kind == "ratings_outdated" or reason.startswith("Waiting for updated rankings."):
            return ("Team details were corrected, but its rating has not been updated. "
                    "We cannot recommend a placement yet.")
        if self.placement_status == NO_CURRENT_RATING or kind == "no_current_rating":
            if self.team.status == "Inactive" or reason.startswith(
                ("Inactive rating;", "PitchRank marks this team inactive.")
            ):
                return ("We do not have enough recent results to recommend a placement. "
                        "Please check recent results or ask the coach about the team's level.")
            return ("Not enough data to recommend a placement. "
                    "Please check recent results or ask the coach about the team's level.")
        return reason

    @property
    def placement_explanation(self) -> str:
        director_reason = self.director_review_reason
        if director_reason and director_reason != self.team.review_reason:
            return director_reason
        if self.recommendation_reason.startswith(self.display_status):
            return self.recommendation_reason
        return ". ".join(value for value in (self.display_status, self.recommendation_reason) if value)

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
        if team.plays_up and team.play_up_from_age_group:
            context.append(f"Plays up from {team.play_up_from_age_group.upper()}")
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
    director_notes: tuple[str, ...] = ()
    format_notes: tuple[str, ...] = ()
    review_teams: tuple[str, ...] = ()

    @property
    def coverage_summary(self) -> str:
        summary = f"{len(self.seeded)} teams ranked"
        if self.unseeded:
            summary += f" · {len(self.unseeded)} need placement"
        return summary

    @property
    def seeded(self) -> tuple[DirectorRow, ...]:
        return tuple(row for row in self.rows if row.seed is not None)

    @property
    def unseeded(self) -> tuple[DirectorRow, ...]:
        return tuple(row for row in self.rows if row.seed is None)


def format_national_rank(team: SheetTeam) -> str:
    """Blank means unavailable; another ranked cohort is always identified."""
    if team.national_rank is None:
        return ""
    context = f" ({team.national_rank_context})" if team.national_rank_context else ""
    return f"#{team.national_rank:,}{context}"


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
    manual_override = bool(analysis and getattr(analysis, "manual_override", False))
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
    if guidance.get("boundary_method") == "whole_group_v1":
        breaks = {item['end_seed'] for item in divisions if item['natural_break_after']}
    ordering = getattr(analysis, "ordering_evidence", {}) if analysis else {}
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
        if status == DATA_REVIEW:
            status = REVIEW_LABELS.get(team.review_kind, "Team data needs review")
        tier = next((item["label"] for item in divisions
                     if item["start_seed"] <= seed <= item["end_seed"]), "")
        break_label = (
            "Recommended tier break + strength-band separation" if seed in practical and seed in breaks else
            "Recommended tier break" if seed in practical else
            "Competitive Break: natural strength separation" if seed in breaks else ""
        )
        detail = ordering.get("teams", {}).get(team.entrant_id, {})
        reason = detail.get("director_reason", "")
        span = ordering.get("game_sensitivity", {}).get("seed_ranges", {}).get(team.entrant_id)
        if reason and span and span[1] - span[0] >= 2:
            reason += f" Order sensitive to results (stress seeds {span[0]}-{span[1]})."
        if manual_override:
            reason = "Manual placement. " + reason
        if team.review_reason:
            reason = " ".join(value for value in (team.review_reason, reason) if value)
        if guidance.get("status") == "review_required_compromise":
            break_label = break_label.replace("Recommended tier break", "Provisional tier break — review required")
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
            reason,
        ))
    for team in unseeded:
        status = statuses.get(team.entrant_id) or (
            DATA_REVIEW if analysis is not None
            else NO_CURRENT_RATING
        )
        if status == DATA_REVIEW:
            status = REVIEW_LABELS.get(team.review_kind, "Team data needs review")
        rows.append(DirectorRow(None, team, "", status,
                                recommendation_reason=team.review_reason or "Unplaced; strength is not established."))
    # Keep full evidence alongside the concise director view of the same roster.
    notes = []
    guidance_summary = ""
    if divisions:
        qualifier = ("Review-required compromise"
                     if guidance.get("status") == "review_required_compromise" else "Suggested tiers")
        guidance_summary = qualifier + ": " + " + ".join(str(item["size"]) for item in divisions) + " teams."
        tier_notes = [
            f"{item['label']}: seeds {item['start_seed']}-{item['end_seed']} "
            + (f"({item['size']} teams; {item['selected_format']['summary']}; "
               f"{item['selected_format']['pool_description']})"
               if item.get("selected_format", {}).get("total_matches") is not None else
               f"({item['size']} teams; compatible pools {' + '.join(map(str, item['pool_sizes']))}; "
               f"minimum {item['minimum_games']} games)")
            for item in divisions
        ]
        if all(item.get("selected_format", {}).get("total_matches") is not None for item in divisions):
            notes.extend(tier_notes)
        else:
            notes.append(qualifier + ": " + "; ".join(tier_notes)
                         + ". Pool memberships remain the director's decision.")
    for warning in guidance.get("warnings", []):
        if warning.startswith("Practical division sizes avoid"):
            notes.append("This split avoids smaller divisions with a modest increase in projected mismatch risk. "
                         "Review the worst matchup and the alternative below.")
        else:
            notes.append(warning)
    ordering = getattr(analysis, "ordering_evidence", {}) if analysis else {}
    if ordering:
        guidance_summary = "Preview — " + guidance_summary
        notes.append("Preview recommendation: compares every assessed team with the whole cohort. "
                     "Prediction improvement has not yet been demonstrated on held-out events.")
        if ordering.get("prediction_model") == "results":
            notes.append("Prediction confidence has not yet been validated.")
        sensitivity = ordering.get("game_sensitivity", {})
        if sensitivity.get("games_checked"):
            notes.append("Influential-result check: tier membership changes in "
                         f"{sensitivity['changed_tier_memberships']} "
                         f"of {sensitivity['games_checked']} game-removal checks. This is not a confidence interval.")
        elif ordering.get("prediction_model") == "results":
            notes.append("No influential-result sensitivity checks were available; placement stability is untested.")
        if sensitivity.get("cluster_samples"):
            notes.append(f"Related-result stress check: tier membership changes in "
                         f"{sensitivity['cluster_changed_tier_memberships']} of {sensitivity['cluster_samples']} "
                         "team/event cluster samples. These are stress checks, not confidence intervals.")
        for entrant, detail in ordering.get("teams", {}).items():
            if detail.get("director_reason"):
                cautions = list(dict.fromkeys(detail.get("cautions", [])))
                if cautions:
                    notes.append(f"{by_id[entrant].team_name}: " + "; ".join(cautions) + ".")
                continue
            original, suggested = baseline_seeds.get(entrant), matchbalance_seeds.get(entrant)
            consequential = original is not None and suggested is not None and abs(original - suggested) >= 3
            unstable = sensitivity.get("seed_ranges", {}).get(entrant, [suggested, suggested])
            field_range = detail.get("field_sensitivity_seeds", [suggested, suggested])
            if (consequential or detail.get("limited_history") or detail.get("results", {}).get("limited")
                    or (field_range[0] is not None and field_range[1] - field_range[0] >= 2)
                    or (unstable[0] is not None and unstable[1] - unstable[0] >= 2)):
                name = by_id[entrant].team_name
                cautions = list(detail.get("cautions", []))
                if unstable[0] is not None and unstable[0] != unstable[1]:
                    cautions.append(f"Result stress checks place it between seeds {unstable[0]} and {unstable[1]}")
                notes.append(f"{name}: PowerScore #{original} to MatchBalance #{suggested}. "
                             + detail["reason"]
                             + (" " + "; ".join(cautions) + "." if cautions else ""))
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
        if alternative.get("status") == "review_required_compromise":
            tradeoffs.append("also requires mismatch review")
        elif alternative.get("status") == "passing":
            tradeoffs.append("passes competitive limits")
        notes.append("Alternative split: " + " + ".join(map(str, guidance["alternative_sizes"]))
                     + " teams" + ("; " + ", ".join(tradeoffs) if tradeoffs else "") + ".")
    if guidance:
        notes.append("Formats use the saved MatchBalance profile; confirm game guarantees and event logistics.")
    if analysis and getattr(analysis, "manual_override", False):
        notes.append("Operator-adjusted from the MatchBalance suggestion.")
    if sheet.delivery_note:
        notes.append(sheet.delivery_note)
    if operator_note.strip():
        notes.append(operator_note.strip())
    director_notes, review_teams = _concise_director_notes(sheet, rows, operator_note)
    return DirectorCohort(
        tuple(rows), tuple(dict.fromkeys(notes)), guidance_summary,
        director_notes,
        tuple(f"{item['label']} — {item['size']} teams: {compact_format(item)}" for item in divisions),
        review_teams,
    )


def compact_format(division: Mapping) -> str:
    selected = division.get("selected_format", {})
    pools = selected.get("pool_sizes", division.get("pool_sizes", []))
    minimum = selected.get("minimum_games", division.get("minimum_games"))
    maximum = selected.get("maximum_games")
    parts = [selected.get("display_name") or "Playing format"]
    if "includes playoffs" in selected.get("summary", "") and not any(
            word in parts[0].lower() for word in ("final", "playoff", "knockout")):
        parts.append("includes playoffs")
    if len(pools) > 1:
        parts.append("pools " + " + ".join(map(str, pools)))
    if minimum is not None:
        if maximum is None:
            parts.append(f"at least {minimum} games; maximum not specified")
        else:
            parts.append(f"{minimum} games each" if minimum == maximum else
                         f"{minimum} guaranteed, up to {maximum} games")
    if selected.get("total_matches") is not None:
        parts.append(f"{selected['total_matches']} matches")
    if (selected.get("maximum_pair_meetings") or 0) > 1:
        parts.append("repeat opponents possible")
    if selected.get("unequal_game_concerns"):
        parts.append("unequal preliminary games — confirm scheduling and standings rules")
    return "; ".join(parts)


def _concise_director_notes(sheet, rows, operator_note):
    analysis = sheet.tier_analysis
    guidance = getattr(analysis, "tier_guidance", {}) if analysis else {}
    ordering = getattr(analysis, "ordering_evidence", {}) if analysis else {}
    notes = []
    if guidance.get("status") == "review_required_compromise":
        notes.append("Matchup review needed: this split still includes potentially uneven games.")
    # Keep unfamiliar warnings visible rather than silently losing a new blocker.
    summarized = ("Review-required compromise:", "A passing alternative", "Practical division sizes avoid",
                  "Limited or unknown playing history", "Worst remaining mismatch:")
    for warning in guidance.get("warnings", []):
        if not warning.startswith(summarized) and "teams assessed in the tier order" not in warning:
            notes.append(warning)
    names = {row.team.entrant_id: row.team.team_name for row in rows}
    risks = guidance.get("risky_pairings", [])
    if risks:
        worst_warning = next((w for w in guidance.get("warnings", [])
                              if w.startswith("Worst remaining mismatch:")), "")
        if worst_warning:
            notes.append(worst_warning.replace("Worst remaining mismatch:", "Review this matchup:")
                         .replace("expected absolute goal difference", "projected goal gap")
                         .replace("four-goal margin probability", "chance of a 4+ goal margin"))
        else:
            for pair in risks:
                notes.append("Review this matchup: " + " vs ".join(names[item] for item in pair["entrant_ids"]) + ".")
    limited = []
    uncertain = []
    sensitivity = ordering.get("game_sensitivity", {})
    for row in rows:
        if row.seed is None:
            continue
        if row.placement_status != SEEDED:
            reason = row.director_review_reason or row.placement_status
            notes.append(f"{row.team.team_name}: {reason.rstrip('.')}.")
        detail = ordering.get("teams", {}).get(row.team.entrant_id, {})
        if row.evidence_note or row.team.entrant_id in getattr(analysis, "limited_history", ()):
            limited.append(row.team.team_name)
        for caution in detail.get("cautions", []):
            if caution.startswith("Field sensitivity:"):
                continue
            if "Limited playing history" in caution:
                limited.append(row.team.team_name)
            elif caution.startswith("No shared results connect this team"):
                notes.append(f"{row.team.team_name}: We have little evidence comparing this team with "
                             "the rest of the field. Please check its placement.")
            else:
                notes.append(f"{row.team.team_name}: {caution.rstrip('.')}.")
        span = ordering.get("game_sensitivity", {}).get("seed_ranges", {}).get(row.team.entrant_id)
        if span and span[1] - span[0] >= 2:
            uncertain.append(row.team.team_name)
    if not limited and any(w.startswith("Limited or unknown playing history") for w in guidance.get("warnings", [])):
        notes.append(LIMITED_HISTORY_LEGEND)
    if uncertain or sensitivity.get("changed_tier_memberships") or sensitivity.get("cluster_changed_tier_memberships"):
        notes.append("Some placements depend on a small number of results. "
                     "Please review close placements before finalizing.")
    if analysis and getattr(analysis, "manual_override", False):
        notes.append("Operator-adjusted from the MatchBalance suggestion.")
    if sheet.delivery_note:
        notes.append(sheet.delivery_note)
    if operator_note.strip():
        notes.append(operator_note.strip())
    return tuple(dict.fromkeys(notes)), tuple(dict.fromkeys(limited))


def export_fingerprint(
    event_name: str, sheets: Sequence[CohortSheet], *, generated_on: str, ranking_run: str,
    operator_notes: Mapping[tuple[str, str], str], analysis_version: int, policy: Mapping[str, float],
) -> str:
    """Both downloads share one identity, independent of XLSX ZIP timestamps."""
    payload = {
        "content_version": CONTENT_VERSION, "analysis_version": analysis_version,
        "event": event_name, "generated_on": generated_on, "ranking_run": ranking_run,
        "policy": dict(policy), "legend": LIMITED_HISTORY_LEGEND,
        "cohorts": [{
            "age": sheet.age_group, "gender": sheet.gender,
            "format_context_digest": (sheet.tier_analysis.tier_guidance or {}).get("format_context_digest")
            if sheet.tier_analysis else None,
            "content": asdict(build_director_cohort(
                sheet, operator_notes.get((sheet.age_group, sheet.gender), ""),
            )),
        } for sheet in sheets],
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def director_csv(sheet: CohortSheet, operator_note: str = "") -> bytes:
    """A self-describing director export; each team retains status and coverage."""
    import csv
    import io

    from src.tournaments.reports.render_csv import csv_safe

    content = build_director_cohort(sheet, operator_note)
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(["Seed", "Team", "Tier", "Tier break", "Why this placement", "Placement status",
                     "Recommendation", "Coverage", "Warnings and formats", "Roster context",
                     "PowerScore", "Record (W-L-D)", "State rank", "National rank"])
    coverage = f"{len(content.seeded)} of {len(content.rows)} teams assessed"
    for row in content.rows:
        writer.writerow([csv_safe(str(value)) if value is not None else "" for value in (
            row.seed, row.team.team_name, row.tier_label, row.break_label,
            row.placement_explanation if row.team.review_reason else row.recommendation_reason,
            row.display_status, content.guidance_summary, coverage,
            " | ".join((*content.format_notes, *content.director_notes,
                        *((LIMITED_HISTORY_LEGEND, "Teams to review: " + "; ".join(content.review_teams))
                          if content.review_teams else ()))),
            " · ".join(row.roster_context), row.score, row.team.record, row.state_rank,
            format_national_rank(row.team))])
    return stream.getvalue().encode("utf-8-sig")
