"""Reproducible, cohort-scoped inputs for an operator's seeding sheet pack."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from typing import Any

from src.tournaments.compare_predictor_bridge import ComparePrediction
from src.tournaments.roster_paste import RosterRow
from src.tournaments.roster_resolver import ResolvedTeam
from src.tournaments.seeding_predictions import _parse_batch
from src.tournaments.seeding_tiers import TierAnalysis, TierEntrant, TierPolicy, build_tiers

PACK_SCHEMA_VERSION = 2
_AGE_GROUP = re.compile(r"^u[1-9][0-9]?$")
_LEGACY_UNAVAILABLE_REASONS = {
    "Two roster entries resolve to the same team; verify the matches.": (
        "Two roster entries appear to be the same team. Confirm both team matches before seeding."
    ),
    "Current ranking data unavailable; placement review required.": (
        "Confirm the club and team match. Then use recent results or club input before seeding."
    ),
}


def _valid_cohort(age_group: str, gender: str) -> bool:
    return bool(_AGE_GROUP.fullmatch(age_group)) and gender in {"Male", "Female"}


def cohort_key(age_group: str, gender: str) -> str:
    return f"{age_group}|{gender}"


def cohort_label(key: str) -> str:
    age, gender = key.split("|", 1)
    gender_label = {"Male": "Boys", "Female": "Girls"}.get(gender, "Unspecified gender")
    return " ".join((age.upper() or "Unspecified age", gender_label))


def available_cohorts(rows: Sequence[RosterRow]) -> tuple[str, ...]:
    keys = {cohort_key(row.section_age_group, row.section_gender) for row in rows}
    return tuple(sorted(keys, key=lambda key: (
        int(key.split("|", 1)[0][1:]) if _AGE_GROUP.fullmatch(key.split("|", 1)[0]) else 0,
        key.split("|", 1)[1],
    )))


def team_ids_by_row(
    rows: Sequence[RosterRow], resolved: Sequence[ResolvedTeam], overrides: Mapping[int, dict[str, Any]],
) -> dict[str, str | None]:
    if len({row.source_index for row in rows}) != len(rows):
        raise ValueError("Each roster row must have a unique source index.")
    if len({item.source_index for item in resolved}) != len(resolved):
        raise ValueError("Each roster row must have at most one team resolution.")
    outcomes = {item.source_index: item for item in resolved}
    return {
        str(row.source_index): (
            (overrides.get(row.source_index) or {}).get("team_id_master")
            or getattr(outcomes.get(row.source_index), "team_id_master", None)
        )
        for row in rows
    }


def duplicate_identity_rows(
    rows: Sequence[RosterRow], resolved: Sequence[ResolvedTeam], overrides: Mapping[int, dict[str, Any]],
) -> dict[int, tuple[int, ...]]:
    """Map every same-cohort duplicate identity to its full roster group."""
    identities = team_ids_by_row(rows, resolved, overrides)
    groups: dict[tuple[str, str, str], list[int]] = {}
    for row in rows:
        entrant_id = str(row.source_index)
        team_id = identities.get(entrant_id)
        if team_id:
            groups.setdefault(
                (row.section_age_group, row.section_gender, str(team_id).casefold()), []
            ).append(row.source_index)
    return {
        source_index: tuple(entrants)
        for entrants in groups.values()
        if len(entrants) > 1
        for source_index in entrants
    }


def roster_fingerprint(
    rows: Sequence[RosterRow], resolved: Sequence[ResolvedTeam], overrides: Mapping[int, dict[str, Any]],
) -> str:
    """An identity/cohort edit invalidates every derived prediction and export."""
    records = []
    for row in rows:
        record = asdict(row)
        # Empty provenance fields were absent from legacy saved packs.
        for key in ("registration_id", "provider_team_id", "intake_issue"):
            if not record[key]:
                record.pop(key)
        records.append(record)
    payload = {"rows": records, "team_ids": team_ids_by_row(rows, resolved, overrides)}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def prediction_request(
    rows: Sequence[RosterRow], resolved: Sequence[ResolvedTeam], overrides: Mapping[int, dict[str, Any]],
    selected: Sequence[str],
) -> dict[str, dict[str, str]]:
    wanted = set(selected)
    if not wanted or not wanted.issubset(available_cohorts(rows)):
        raise ValueError("Select at least one cohort from this roster.")
    ids = team_ids_by_row(rows, resolved, overrides)
    request: dict[str, dict[str, str]] = {key: {} for key in selected}
    seen: dict[str, set[str]] = {key: set() for key in request}
    for row in rows:
        key = cohort_key(row.section_age_group, row.section_gender)
        team_id = ids[str(row.source_index)]
        if key in wanted and team_id and _valid_cohort(row.section_age_group, row.section_gender):
            # Duplicate registrations stay in the roster for explicit placement
            # review, but Compare needs only one representative of a canonical
            # team. Sending both would ask it to predict a team against itself.
            identity_key = str(team_id).casefold()
            if identity_key in seen[key]:
                continue
            seen[key].add(identity_key)
            request[key][str(row.source_index)] = str(team_id)
    return request


def make_pack(
    rows: Sequence[RosterRow], resolved: Sequence[ResolvedTeam], overrides: Mapping[int, dict[str, Any]],
    selected: Sequence[str], batch: Any, ratings: Mapping[str, dict[str, Any]],
) -> dict[str, Any]:
    """Capture the exact forecasts and ratings; reopening makes no fresh queries."""
    request = prediction_request(rows, resolved, overrides, selected)
    requested_ids = {team_id for entrants in request.values() for team_id in entrants.values()}
    pack = {
        "schema_version": PACK_SCHEMA_VERSION,
        "roster_fingerprint": roster_fingerprint(rows, resolved, overrides),
        "selected_cohorts": list(dict.fromkeys(selected)),
        "generated_at": batch.generated_at,
        "ratings_as_of": batch.ratings_as_of,
        "predictor_sha256": batch.predictor_sha256,
        "teams": batch.teams,
        "unavailable": batch.unavailable,
        "ratings": {key: dict(value) for key, value in ratings.items() if key in requested_ids},
        "predictions": {
            key: [{"entrant_a": a, "entrant_b": b, **asdict(value)} for (a, b), value in sorted(pairs.items())]
            for key, pairs in batch.predictions.items()
        },
        "policy": asdict(TierPolicy()),
        "manual_groups": {},
        "operator_notes": {},
    }
    _snapshot_predictions(pack, request)
    # A saved forecast must not share mutable nested dictionaries with a batch
    # or ratings cache that can later be refreshed in the same operator session.
    return json.loads(json.dumps(pack, ensure_ascii=False, allow_nan=False))


def pack_matches(
    pack: Any, rows: Sequence[RosterRow], resolved: Sequence[ResolvedTeam],
    overrides: Mapping[int, dict[str, Any]], selected: Sequence[str] | None = None,
) -> bool:
    if not isinstance(pack, dict) or pack.get("schema_version") != PACK_SCHEMA_VERSION:
        return False
    saved_selection = pack.get("selected_cohorts")
    if (
        not isinstance(saved_selection, list)
        or not saved_selection
        or any(not isinstance(key, str) for key in saved_selection)
        or len(set(saved_selection)) != len(saved_selection)
        or not set(saved_selection).issubset(available_cohorts(rows))
    ):
        return False
    return (
        pack.get("roster_fingerprint") == roster_fingerprint(rows, resolved, overrides)
        and (selected is None or set(saved_selection) == set(selected))
    )


def _snapshot_predictions(
    pack: dict[str, Any], request: dict[str, dict[str, str]],
) -> dict[str, dict[tuple[str, str], ComparePrediction]]:
    """Apply the live bridge's coverage and forecast contract again on reload."""
    if not re.fullmatch(r"[0-9a-f]{64}", str(pack.get("predictor_sha256") or "")):
        raise ValueError("Seeding snapshot is missing its predictor identity.")
    for section in ("teams", "unavailable", "predictions"):
        if not isinstance(pack.get(section), dict) or set(pack[section]) != set(request):
            raise ValueError(f"Seeding snapshot has incomplete {section} cohort coverage.")
    if not isinstance(pack.get("ratings"), dict) or any(
        not isinstance(value, dict) for value in pack["ratings"].values()
    ):
        raise ValueError("Seeding snapshot has invalid ratings.")
    for section in ("manual_groups", "operator_notes"):
        if not isinstance(pack.get(section, {}), dict) or not set(pack.get(section, {})).issubset(request):
            raise ValueError(f"Seeding snapshot has invalid {section} cohort coverage.")
    if any(not isinstance(note, str) for note in pack.get("operator_notes", {}).values()):
        raise ValueError("Seeding snapshot has invalid placement notes.")
    try:
        result = _parse_batch({
            "schema_version": 1,
            "generated_at": pack.get("generated_at"),
            "ratings_as_of": pack.get("ratings_as_of"),
            "cohorts": {
                key: {section: pack[section][key] for section in ("teams", "unavailable", "predictions")}
                for key in request
            },
        }, request, str(pack.get("predictor_sha256") or ""))
    except (TypeError, KeyError, AttributeError) as exc:
        raise ValueError("Seeding snapshot has malformed forecast data; rebuild the matchup tiers.") from exc
    for teams in result.teams.values():
        counts = Counter(team["team_id_master"] for team in teams.values())
        if any(count > 1 for count in counts.values()):
            raise ValueError("Seeding snapshot contains duplicate canonical teams; verify the roster matches.")
    return result.predictions


def _published_score(team: dict[str, Any]) -> float | None:
    score = team.get("power_score_final")
    if (
        isinstance(score, bool)
        or not isinstance(score, (int, float))
        or not math.isfinite(score)
        or not 0 <= score <= 1
    ):
        return None
    return float(score)


def _review_reason(row: RosterRow, team: dict[str, Any], unavailable: str | None, identity: str | None) -> str | None:
    if not _valid_cohort(row.section_age_group, row.section_gender):
        return "Confirm the listed age group and gender before seeding."
    if not identity:
        return "Confirm the club, team name, and age group before seeding."
    if unavailable:
        return _LEGACY_UNAVAILABLE_REASONS.get(unavailable, unavailable)
    if not team:
        return "Current PitchRank data is unavailable. Confirm the team match before seeding."
    if team.get("status") == "Inactive":
        return "No current ranking. Use recent results or club input."
    if _published_score(team) is None:
        return "No current PitchRank score. Use recent results or club input."
    expected_gender = "M" if row.section_gender == "Male" else "F"
    if team.get("gender") not in {expected_gender, "B" if expected_gender == "M" else "G"}:
        return "The matched team may be in a different gender group. Confirm before seeding."
    age = team.get("age")
    if isinstance(age, bool) or not isinstance(age, int) or not 1 <= age <= 99:
        return "Confirm the team's age before seeding."
    if age > int(row.section_age_group[1:]):
        return "The matched team may be older than this age group. Confirm eligibility before seeding."
    # Younger entrants may intentionally play up. The tournament heading
    # controls their placement, while Compare uses their actual recorded age.
    return None


def analyze_pack(
    pack: dict[str, Any], rows: Sequence[RosterRow], resolved: Sequence[ResolvedTeam],
    overrides: Mapping[int, dict[str, Any]],
) -> dict[tuple[str, str], TierAnalysis]:
    if not pack_matches(pack, rows, resolved, overrides):
        raise ValueError("The roster or team matches changed. Rebuild matchup tiers before exporting.")
    try:
        policy = TierPolicy(**pack["policy"])
    except (TypeError, KeyError) as exc:
        raise ValueError("Seeding snapshot has invalid matchup limits.") from exc
    request = prediction_request(rows, resolved, overrides, pack["selected_cohorts"])
    snapshot_predictions = _snapshot_predictions(pack, request)
    identities = team_ids_by_row(rows, resolved, overrides)
    duplicate_rows = duplicate_identity_rows(rows, resolved, overrides)
    analyses = {}
    for key in pack["selected_cohorts"]:
        cohort_rows = [row for row in rows if cohort_key(row.section_age_group, row.section_gender) == key]
        teams = pack["teams"].get(key, {})
        unavailable = pack["unavailable"].get(key, {})
        entrants = []
        for row in cohort_rows:
            entrant_id = str(row.source_index)
            team = teams.get(entrant_id, {})
            identity = identities[entrant_id]
            supplemental = pack["ratings"].get(str(identity), {}) if identity else {}
            evidence = {**supplemental, **team}
            review_reason = _review_reason(row, evidence, unavailable.get(entrant_id), identity)
            if row.source_index in duplicate_rows:
                review_reason = (
                    "Multiple roster entries resolve to the same PitchRank team. "
                    "Confirm each registration before seeding."
                )
            entrants.append(TierEntrant(
                entrant_id=entrant_id,
                team_name=str(evidence.get("team_name") or row.team_name_stripped),
                power_score=_published_score(evidence),
                review_reason=review_reason,
            ))
        analyses[tuple(key.split("|", 1))] = build_tiers(
            entrants, snapshot_predictions[key], policy=policy, manual_groups=pack.get("manual_groups", {}).get(key),
        )
    return analyses


def snapshot_ratings(pack: dict[str, Any], identities: Mapping[str, str | None]) -> dict[str, dict[str, Any]]:
    """Use the same snapshot as predictions, including newly canonicalized IDs."""
    ratings = {key: dict(value) for key, value in pack["ratings"].items()}
    for teams in pack["teams"].values():
        for entrant_id, team in teams.items():
            requested_id = identities.get(entrant_id)
            if requested_id:
                supplemental = ratings.get(str(requested_id), {})
                captured = {**supplemental, **team}
                # Compare can lack the optional state-ranking view while the
                # sheet's separate display lookup succeeds. Keep that display
                # information, without falling back for any strength metric.
                for field in ("rank_in_state_final", "state"):
                    if team.get(field) is None and supplemental.get(field) is not None:
                        captured[field] = supplemental[field]
                ratings[str(requested_id)] = captured
    return json.loads(json.dumps(ratings, ensure_ascii=False, allow_nan=False))
