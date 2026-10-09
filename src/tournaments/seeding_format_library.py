"""Versioned tournament-format metadata for automatic MatchBalance suggestions.

The library describes exact pool/playoff variants that a competitive flight may
use. It does not schedule games, assign teams to pools, change seed order, or
claim that a reference rule is current for a named event.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Mapping

from src.tournaments.seeding_format_mechanics import calculate_format_games

FORMAT_LIBRARY_SCHEMA_VERSION = 2
DEFAULT_LIBRARY_PATH = (
    Path(__file__).resolve().parents[2] / "config" / "matchbalance_format_library.json"
)
LEGACY_LIBRARY_PATH = DEFAULT_LIBRARY_PATH.with_name("matchbalance_format_library_v1.json")

ENABLED = "enabled"
REFERENCE_ONLY = "reference_only"
BLOCKED = "blocked"
AVAILABILITY_STATUSES = frozenset({ENABLED, REFERENCE_ONLY, BLOCKED})

PRELIMINARY_PLAY_TYPES = frozenset(
    {
        "round_robin",
        "crossover",
        "mixed_round_robin",
        "mixed_round_robin_and_crossover",
        "double_round_robin", "partial_round_robin", "partial_crossover",
        "league_phase", "knockout",
    }
)
CHAMPIONSHIP_TYPES = frozenset(
    {"final", "semifinals_final", "standings_only", "knockout"}
)


@dataclass(frozen=True)
class FormatSourceDocument:
    source_id: str
    title: str
    sha256: str
    location: str
    verification_status: str
    note: str


@dataclass(frozen=True)
class MatchBalanceRecommendationPolicy:
    policy_id: str
    version: int
    status: str
    description: str
    selection_steps: tuple[str, ...]
    numerical_tie_relative_tolerance: float
    numerical_tie_absolute_tolerance: float
    provenance_status: str


@dataclass(frozen=True)
class FormatTemplate:
    template_id: str
    version: int
    team_count: int
    pool_sizes: tuple[int, ...]
    preliminary_play_type: str
    advancement_description: str
    championship_type: str
    minimum_guaranteed_games_per_team: int | None
    maximum_possible_games_per_team: int | None
    unequal_pool_requirements: tuple[str, ...]
    operational_requirements: tuple[str, ...]
    unresolved_assumptions: tuple[str, ...]
    source_id: str
    source_section: str
    rule_year: str | None
    provenance_status: str
    availability_status: str
    blocked_reason: str | None
    display_name: str = ""
    playing_structure: Mapping[str, Any] | None = None
    total_matches: int | None = None
    maximum_pair_meetings: int | None = None


@dataclass(frozen=True)
class FormatSourceIssue:
    issue_id: str
    source_entry: str
    status: str
    reason: str


@dataclass(frozen=True)
class FormatProfile:
    profile_id: str
    version: int
    display_name: str
    status: str
    is_default: bool
    template_ids: tuple[str, ...]
    preferred_template_ids_by_team_count: Mapping[int, str]
    recommendation_policy_id: str
    required_minimum_games_per_team: int | None
    operational_restrictions: tuple[str, ...]
    format_preferences: tuple[str, ...]
    max_candidate_structures: int
    provenance_status: str
    source_note: str
    unresolved_assumptions: tuple[str, ...]
    required_maximum_games_per_team: int | None = None
    repeat_opponents: str = "allowed"
    playoffs: str = "any"
    format_selection: str = "legacy_preference"
    exact_search_enabled: bool = False
    maximum_search_states: int = 1000000


@dataclass(frozen=True)
class TemplateValidation:
    template_id: str
    availability_status: str
    usable_in_profiles: bool
    errors: tuple[str, ...]
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class ProfileValidation:
    profile_id: str
    valid: bool
    errors: tuple[str, ...]
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class FormatLibraryValidation:
    valid: bool
    library_errors: tuple[str, ...]
    template_results: tuple[TemplateValidation, ...]
    profile_results: tuple[ProfileValidation, ...]
    source_issues: tuple[FormatSourceIssue, ...]


@dataclass(frozen=True)
class FormatLibrary:
    schema_version: int
    library_id: str
    library_version: str
    source_documents: tuple[FormatSourceDocument, ...]
    recommendation_policies: tuple[MatchBalanceRecommendationPolicy, ...]
    templates: tuple[FormatTemplate, ...]
    source_issues: tuple[FormatSourceIssue, ...]
    profiles: tuple[FormatProfile, ...]
    source_path: Path
    source_sha256: str
    source_coverage: tuple[Mapping[str, Any], ...] = field(default_factory=tuple)

    @property
    def templates_by_id(self) -> dict[str, FormatTemplate]:
        return {item.template_id: item for item in self.templates}

    @property
    def profiles_by_id(self) -> dict[str, FormatProfile]:
        return {item.profile_id: item for item in self.profiles}

    @property
    def policies_by_id(self) -> dict[str, MatchBalanceRecommendationPolicy]:
        return {item.policy_id: item for item in self.recommendation_policies}


def _tuple_of_text(value: Any) -> tuple[str, ...]:
    return tuple(str(item) for item in (value or ()))


def _optional_int(value: Any) -> int | None:
    return None if value is None else int(value)


def _load_template(payload: Mapping[str, Any]) -> FormatTemplate:
    return FormatTemplate(
        template_id=str(payload["template_id"]),
        version=int(payload["version"]),
        team_count=int(payload["team_count"]),
        pool_sizes=tuple(int(item) for item in payload["pool_sizes"]),
        preliminary_play_type=str(payload["preliminary_play_type"]),
        advancement_description=str(payload["advancement_description"]),
        championship_type=str(payload["championship_type"]),
        minimum_guaranteed_games_per_team=_optional_int(
            payload.get("minimum_guaranteed_games_per_team")
        ),
        maximum_possible_games_per_team=_optional_int(
            payload.get("maximum_possible_games_per_team")
        ),
        unequal_pool_requirements=_tuple_of_text(
            payload.get("unequal_pool_requirements")
        ),
        operational_requirements=_tuple_of_text(
            payload.get("operational_requirements")
        ),
        unresolved_assumptions=_tuple_of_text(payload.get("unresolved_assumptions")),
        source_id=str(payload["source_id"]),
        source_section=str(payload["source_section"]),
        rule_year=(
            str(payload["rule_year"]) if payload.get("rule_year") is not None else None
        ),
        provenance_status=str(payload["provenance_status"]),
        availability_status=str(payload["availability_status"]),
        blocked_reason=(
            str(payload["blocked_reason"])
            if payload.get("blocked_reason") is not None
            else None
        ),
        display_name=str(payload.get("display_name", "")),
        playing_structure=payload.get("playing_structure"),
        total_matches=_optional_int(payload.get("total_matches")),
        maximum_pair_meetings=_optional_int(payload.get("maximum_pair_meetings")),
    )


def _load_profile(payload: Mapping[str, Any]) -> FormatProfile:
    preferences = {
        int(team_count): str(template_id)
        for team_count, template_id in (
            payload.get("preferred_template_ids_by_team_count") or {}
        ).items()
    }
    return FormatProfile(
        profile_id=str(payload["profile_id"]),
        version=int(payload["version"]),
        display_name=str(payload["display_name"]),
        status=str(payload["status"]),
        is_default=bool(payload.get("is_default")),
        template_ids=_tuple_of_text(payload.get("template_ids")),
        preferred_template_ids_by_team_count=preferences,
        recommendation_policy_id=str(payload["recommendation_policy_id"]),
        required_minimum_games_per_team=_optional_int(
            payload.get("required_minimum_games_per_team")
        ),
        operational_restrictions=_tuple_of_text(
            payload.get("operational_restrictions")
        ),
        format_preferences=_tuple_of_text(payload.get("format_preferences")),
        max_candidate_structures=int(payload["max_candidate_structures"]),
        provenance_status=str(payload["provenance_status"]),
        source_note=str(payload["source_note"]),
        unresolved_assumptions=_tuple_of_text(payload.get("unresolved_assumptions")),
        required_maximum_games_per_team=_optional_int(payload.get("required_maximum_games_per_team")),
        repeat_opponents=str(payload.get("repeat_opponents", "allowed")),
        playoffs=str(payload.get("playoffs", "any")),
        format_selection=str(payload.get("format_selection", "legacy_preference")),
        exact_search_enabled=bool(payload.get("exact_search_enabled", False)),
        maximum_search_states=int(payload.get("maximum_search_states", 1000000)),
    )


def load_format_library(path: Path | None = None) -> FormatLibrary:
    """Load the checked-in format library without contacting external sources."""
    source_path = (path or DEFAULT_LIBRARY_PATH).resolve()
    source_bytes = source_path.read_bytes()
    payload = json.loads(source_bytes.decode("utf-8"))
    return parse_format_library(payload, source_path=source_path, source_bytes=source_bytes)


def parse_format_library(
    payload: Mapping[str, Any], *, source_path: Path = DEFAULT_LIBRARY_PATH,
    source_bytes: bytes | None = None,
) -> FormatLibrary:
    """Validate a frozen library using the same contract as the checked-in source."""
    if source_bytes is None:
        source_bytes = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()
    library = FormatLibrary(
        schema_version=int(payload["schema_version"]),
        library_id=str(payload["library_id"]),
        library_version=str(payload["library_version"]),
        source_documents=tuple(
            FormatSourceDocument(**item) for item in payload["source_documents"]
        ),
        recommendation_policies=tuple(
            MatchBalanceRecommendationPolicy(
                **{
                    **item,
                    "selection_steps": _tuple_of_text(item.get("selection_steps")),
                }
            )
            for item in payload["recommendation_policies"]
        ),
        templates=tuple(_load_template(item) for item in payload["templates"]),
        source_issues=tuple(
            FormatSourceIssue(**item) for item in payload.get("source_issues", ())
        ),
        profiles=tuple(_load_profile(item) for item in payload["profiles"]),
        source_path=source_path,
        source_sha256=hashlib.sha256(source_bytes).hexdigest(),
        source_coverage=tuple(payload.get("source_coverage", ())),
    )
    validation = validate_format_library(library)
    if not validation.valid:
        issues = "; ".join(
            (*validation.library_errors,)
            + tuple(
                f"{item.template_id}: {error}"
                for item in validation.template_results
                for error in item.errors
            )
            + tuple(
                f"{item.profile_id}: {error}"
                for item in validation.profile_results
                for error in item.errors
            )
        )
        raise ValueError(f"Invalid MatchBalance format library: {issues}")
    return library


def _duplicate_values(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(sorted({item for item in values if values.count(item) > 1}))


def _validate_template(
    template: FormatTemplate, source_ids: set[str]
) -> TemplateValidation:
    errors: list[str] = []
    warnings: list[str] = []
    if not template.template_id.strip():
        errors.append("Template ID is empty.")
    if template.version < 1:
        errors.append("Template version must be positive.")
    if template.team_count < 2:
        errors.append("Flight team count must be at least two.")
    if not template.pool_sizes or any(size < 2 for size in template.pool_sizes):
        errors.append("Every template needs non-singleton positive pool sizes.")
    if sum(template.pool_sizes) != template.team_count:
        errors.append(
            f"Pool sizes total {sum(template.pool_sizes)}, not flight count "
            f"{template.team_count}."
        )
    if template.preliminary_play_type not in PRELIMINARY_PLAY_TYPES:
        errors.append(
            f"Unsupported preliminary-play type {template.preliminary_play_type!r}."
        )
    if template.championship_type not in CHAMPIONSHIP_TYPES:
        errors.append(f"Unsupported championship type {template.championship_type!r}.")
    minimum = template.minimum_guaranteed_games_per_team
    maximum = template.maximum_possible_games_per_team
    if minimum is not None and minimum < 0:
        errors.append("Minimum guaranteed games cannot be negative.")
    if maximum is not None and maximum < 0:
        errors.append("Maximum possible games cannot be negative.")
    if minimum is not None and maximum is not None and minimum > maximum:
        errors.append("Minimum guaranteed games exceed maximum possible games.")
    if template.availability_status == ENABLED and template.version >= 2 and template.playing_structure is None:
        errors.append("Enabled v2 templates require an explicit playing structure.")
    if template.playing_structure is not None:
        try:
            calculated = calculate_format_games(template.team_count, template.playing_structure)
            expected = (calculated.minimum_games, calculated.maximum_games,
                        calculated.total_matches, calculated.maximum_pair_meetings)
            declared = (minimum, maximum, template.total_matches, template.maximum_pair_meetings)
            if expected != declared:
                errors.append("Game counts disagree with the playing structure: "
                              f"calculated {expected}, declared {declared}.")
            if calculated.has_playoffs != (template.championship_type != "standings_only"):
                errors.append("Playoff declaration disagrees with the playing structure.")
        except (ValueError, TypeError, KeyError) as exc:
            errors.append(f"Invalid playing structure: {exc}")
    if template.source_id not in source_ids:
        errors.append(f"Unknown source document {template.source_id!r}.")
    if template.availability_status not in AVAILABILITY_STATUSES:
        errors.append(
            f"Unknown availability status {template.availability_status!r}."
        )
    if template.availability_status == ENABLED:
        if template.blocked_reason:
            errors.append("An enabled template cannot have a blocked reason.")
        if template.unresolved_assumptions:
            errors.append("An enabled template cannot have unresolved format mechanics.")
    elif not template.blocked_reason:
        errors.append("A non-enabled template requires a reason.")
    if minimum is None:
        warnings.append("Minimum guaranteed games are unknown.")
    if maximum is None:
        warnings.append("Maximum possible games are unknown.")
    return TemplateValidation(
        template_id=template.template_id,
        availability_status=template.availability_status,
        usable_in_profiles=not errors and template.availability_status == ENABLED,
        errors=tuple(errors),
        warnings=tuple(warnings),
    )


def validate_format_library(library: FormatLibrary) -> FormatLibraryValidation:
    """Validate counts, exact mechanics, references, profiles, and defaults."""
    library_errors: list[str] = []
    if library.schema_version not in {1, FORMAT_LIBRARY_SCHEMA_VERSION}:
        library_errors.append(
            f"Unsupported schema version {library.schema_version}; expected "
            f"{FORMAT_LIBRARY_SCHEMA_VERSION}."
        )

    source_ids = tuple(item.source_id for item in library.source_documents)
    template_ids = tuple(item.template_id for item in library.templates)
    profile_ids = tuple(item.profile_id for item in library.profiles)
    policy_ids = tuple(item.policy_id for item in library.recommendation_policies)
    for label, values in (
        ("source document", source_ids),
        ("template", template_ids),
        ("profile", profile_ids),
        ("recommendation policy", policy_ids),
    ):
        duplicates = _duplicate_values(values)
        if duplicates:
            library_errors.append(
                f"Duplicate {label} ID(s): {', '.join(duplicates)}."
            )

    templates = {item.template_id: item for item in library.templates}
    template_results = tuple(
        _validate_template(item, set(source_ids)) for item in library.templates
    )
    usable = {
        item.template_id
        for item in template_results
        if item.usable_in_profiles
    }
    profiles: list[ProfileValidation] = []
    for profile in library.profiles:
        errors: list[str] = []
        warnings: list[str] = []
        if profile.version < 1:
            errors.append("Profile version must be positive.")
        if profile.status != ENABLED:
            errors.append("Only enabled profiles can be resolved for recommendations.")
        if not profile.template_ids:
            errors.append("Profile has no format templates.")
        if len(set(profile.template_ids)) != len(profile.template_ids):
            errors.append("Profile repeats a template ID.")
        unknown = tuple(
            item for item in profile.template_ids if item not in templates
        )
        if unknown:
            errors.append(f"Unknown profile template(s): {', '.join(unknown)}.")
        unusable = tuple(
            item
            for item in profile.template_ids
            if item in templates and item not in usable
        )
        if unusable:
            errors.append(
                f"Profile includes non-enabled template(s): {', '.join(unusable)}."
            )
        if profile.recommendation_policy_id not in set(policy_ids):
            errors.append(
                f"Unknown recommendation policy {profile.recommendation_policy_id!r}."
            )
        if profile.max_candidate_structures < 1:
            errors.append("Candidate-structure limit must be positive.")
        if profile.maximum_search_states < 1:
            errors.append("Exact-search state limit must be positive.")
        if profile.repeat_opponents not in {"allowed", "prohibited"}:
            errors.append("Repeat-opponent preference must be allowed or prohibited.")
        if profile.playoffs not in {"any", "required", "excluded"}:
            errors.append("Playoff preference must be any, required or excluded.")
        if profile.format_selection not in {"practical_default", "legacy_preference"}:
            errors.append("Unknown format-selection policy.")
        for value in (profile.required_minimum_games_per_team, profile.required_maximum_games_per_team):
            if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value < 1):
                errors.append("Game preferences must be positive integers or unspecified.")
        for team_count, template_id in (
            profile.preferred_template_ids_by_team_count.items()
        ):
            template = templates.get(template_id)
            if template_id not in profile.template_ids:
                errors.append(
                    f"Preferred template {template_id!r} is not enabled by the profile."
                )
            elif template is not None and template.team_count != team_count:
                errors.append(
                    f"Preferred template {template_id!r} has {template.team_count} "
                    f"teams, not {team_count}."
                )
        enabled_counts = {
            templates[item].team_count
            for item in profile.template_ids
            if item in templates
        }
        missing_preferences = enabled_counts - set(
            profile.preferred_template_ids_by_team_count
        )
        if missing_preferences:
            warnings.append(
                "No preferred template for team count(s): "
                + ", ".join(str(item) for item in sorted(missing_preferences))
                + "."
            )
        profiles.append(
            ProfileValidation(
                profile_id=profile.profile_id,
                valid=not errors,
                errors=tuple(errors),
                warnings=tuple(warnings),
            )
        )

    default_profiles = tuple(item for item in library.profiles if item.is_default)
    if len(default_profiles) != 1:
        library_errors.append(
            "Exactly one MatchBalance default format profile is required."
        )
    valid = (
        not library_errors
        and all(not item.errors for item in template_results)
        and all(item.valid for item in profiles)
    )
    return FormatLibraryValidation(
        valid=valid,
        library_errors=tuple(library_errors),
        template_results=template_results,
        profile_results=tuple(profiles),
        source_issues=library.source_issues,
    )


def resolve_format_profile(
    library: FormatLibrary, profile_id: str | None = None
) -> FormatProfile:
    """Apply explicit-profile precedence, then the one library default."""
    if profile_id is not None:
        profile = library.profiles_by_id.get(profile_id)
        if profile is None:
            raise ValueError(f"Unknown MatchBalance format profile: {profile_id!r}")
        return profile
    defaults = tuple(item for item in library.profiles if item.is_default)
    if len(defaults) != 1:  # pragma: no cover - enforced by library validation
        raise ValueError("The format library does not have exactly one default profile")
    return defaults[0]


def profile_templates(
    library: FormatLibrary, profile: FormatProfile
) -> tuple[FormatTemplate, ...]:
    """Return enabled profile templates in declared deterministic order."""
    templates = library.templates_by_id
    return tuple(templates[template_id] for template_id in profile.template_ids)


def format_library_payload(
    library: FormatLibrary, validation: FormatLibraryValidation | None = None
) -> dict[str, Any]:
    """Return a JSON-ready provenance and validation snapshot."""
    result = {
        "schema_version": library.schema_version,
        "library_id": library.library_id,
        "library_version": library.library_version,
        "source_path": str(library.source_path),
        "source_sha256": library.source_sha256,
        "source_documents": [asdict(item) for item in library.source_documents],
        "recommendation_policies": [
            asdict(item) for item in library.recommendation_policies
        ],
        "templates": [asdict(item) for item in library.templates],
        "source_issues": [asdict(item) for item in library.source_issues],
        "profiles": [asdict(item) for item in library.profiles],
        "source_coverage": list(library.source_coverage),
    }
    if validation is not None:
        result["validation"] = asdict(validation)
    return result
