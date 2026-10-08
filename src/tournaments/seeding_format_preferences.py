"""Optional event preferences, resolved independently for each cohort."""

from dataclasses import replace
from typing import Mapping

from src.tournaments.seeding_format_library import FormatProfile, FormatTemplate

PREFERENCE_DEFAULTS = {
    "minimum_games": None,
    "maximum_games": None,
    "repeat_opponents": "allowed",
    "playoffs": "any",
}


def validate_preferences(values: Mapping) -> dict:
    if not isinstance(values, Mapping) or set(values) - set(PREFERENCE_DEFAULTS):
        raise ValueError("Unknown tournament format preference.")
    result = dict(values)
    for field in ("minimum_games", "maximum_games"):
        value = result.get(field)
        if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value < 1):
            raise ValueError("Game limits must be positive whole numbers or unspecified.")
    if result.get("repeat_opponents", "allowed") not in {"allowed", "prohibited"}:
        raise ValueError("Choose whether repeat opponents are allowed or prohibited.")
    if result.get("playoffs", "any") not in {"any", "required", "excluded"}:
        raise ValueError("Choose no playoff preference, required, or excluded.")
    return result


def effective_preferences(pack: Mapping, cohort: str) -> dict:
    overrides = pack.get("cohort_format_preferences", {})
    if not isinstance(overrides, Mapping):
        raise ValueError("Cohort format preferences must be a mapping.")
    return {
        **validate_preferences(pack.get("format_preferences", {})),
        **validate_preferences(overrides.get(cohort, {})),
    }


def apply_preferences(profile: FormatProfile, values: Mapping | None) -> FormatProfile:
    if values is None:
        return profile
    values = validate_preferences(values)
    names = {
        "minimum_games": "required_minimum_games_per_team",
        "maximum_games": "required_maximum_games_per_team",
        "repeat_opponents": "repeat_opponents",
        "playoffs": "playoffs",
    }
    return replace(profile, **{names[key]: value for key, value in values.items()})


def practical_format_key(template: FormatTemplate) -> tuple:
    minimum = template.minimum_guaranteed_games_per_team
    distance = min(abs(minimum - 3), abs(minimum - 4)) if minimum is not None else float("inf")
    return (
        0 if minimum in {3, 4} else 1,
        distance,
        template.maximum_pair_meetings if template.maximum_pair_meetings is not None else float("inf"),
        template.maximum_possible_games_per_team
        if template.maximum_possible_games_per_team is not None
        else float("inf"),
        template.total_matches if template.total_matches is not None else float("inf"),
        template.template_id,
    )


def format_exclusions(template: FormatTemplate, profile: FormatProfile) -> tuple[str, ...]:
    reasons = []
    minimum, maximum = template.minimum_guaranteed_games_per_team, template.maximum_possible_games_per_team
    if profile.required_minimum_games_per_team is not None:
        if minimum is None or minimum < profile.required_minimum_games_per_team:
            reasons.append(
                f"Guarantees {minimum if minimum is not None else 'unknown'} games; "
                f"minimum required is {profile.required_minimum_games_per_team}."
            )
    if profile.required_maximum_games_per_team is not None:
        if maximum is None or maximum > profile.required_maximum_games_per_team:
            reasons.append(
                f"May require {maximum if maximum is not None else 'unknown'} games; "
                f"maximum allowed is {profile.required_maximum_games_per_team}."
            )
    if profile.repeat_opponents == "prohibited" and template.maximum_pair_meetings != 1:
        reasons.append("Repeat opponents are possible or not established as absent.")
    has_playoffs = template.championship_type != "standings_only"
    if profile.playoffs == "required" and not has_playoffs:
        reasons.append("Playoffs are required.")
    if profile.playoffs == "excluded" and has_playoffs:
        reasons.append("Playoffs are excluded.")
    return tuple(reasons)


def format_summary(template: FormatTemplate) -> dict:
    minimum, maximum = template.minimum_guaranteed_games_per_team, template.maximum_possible_games_per_team
    label = template.display_name or template.preliminary_play_type.replace("_", " ").capitalize()
    games = f"{minimum} games each" if minimum == maximum else f"{minimum} guaranteed; up to {maximum} games"
    details = [label, games]
    if template.total_matches is not None:
        details.append(f"{template.total_matches} matches total")
    if template.maximum_pair_meetings and template.maximum_pair_meetings > 1:
        details.append(f"opponents may meet up to {template.maximum_pair_meetings} times")
    details.append("no playoffs" if template.championship_type == "standings_only" else "includes playoffs")
    details.extend(template.unequal_pool_requirements)
    return {
        "template_id": template.template_id,
        "pool_sizes": list(template.pool_sizes),
        "minimum_games": minimum,
        "maximum_games": maximum,
        "total_matches": template.total_matches,
        "maximum_pair_meetings": template.maximum_pair_meetings,
        "display_name": label,
        "advancement": template.advancement_description,
        "pool_description": (
            "no preliminary pools"
            if template.preliminary_play_type == "knockout"
            else "compatible pools " + " + ".join(map(str, template.pool_sizes))
        ),
        "unequal_game_concerns": list(template.unequal_pool_requirements),
        "summary": "; ".join(details),
    }
