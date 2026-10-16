"""Observed-game perturbations, distinct from synthetic-prediction confidence."""
import hashlib
import json
from collections import OrderedDict
from dataclasses import asdict, replace
from threading import Lock

from src.tournaments.seeding_predictions import _parse_batch
from src.tournaments.seeding_tier_guidance import build_tier_guidance
from src.tournaments.seeding_tiers import build_cheat_sheet_analysis

_CACHE: OrderedDict[str, str] = OrderedDict()
_CACHE_LOCK = Lock()


def assess_game_sensitivity(analysis, entrants, predictions, variants, policy, library, *,
                            teams, generated_at, profile_id=None, tier_names=(), format_preferences=None):
    """Reassess orders and tiers after influential-game removal and team/event resampling.

    These are stress checks, not independent samples or statistical intervals.
    All games' original observations remain in the frozen evidence manifest.
    """
    inputs = {"baseline": analysis.baseline_order, "suggested": analysis.suggested_order,
              "order": analysis.ordered_ids, "manual": analysis.manual_override, "holds": analysis.manual_holds,
              "cuts": analysis.tier_guidance.get("cuts", []), "entrants": [asdict(item) for item in entrants],
              "predictions": [[list(pair), asdict(value)] for pair, value in sorted(predictions.items())],
              "variants": variants, "policy": asdict(policy), "library": asdict(library), "teams": teams,
              "generated_at": generated_at, "profile": profile_id, "names": tier_names,
              "preferences": format_preferences}
    key = hashlib.sha256(json.dumps(inputs, sort_keys=True, allow_nan=False, default=str).encode()).hexdigest()
    with _CACHE_LOCK:
        if key in _CACHE:
            _CACHE.move_to_end(key)
            return json.loads(_CACHE[key])
    result = _calculate_sensitivity(analysis, entrants, predictions, variants, policy, library,
                                    teams=teams, generated_at=generated_at, profile_id=profile_id,
                                    tier_names=tier_names, format_preferences=format_preferences)
    with _CACHE_LOCK:
        _CACHE[key] = json.dumps(result, allow_nan=False)
        _CACHE.move_to_end(key)
        while len(_CACHE) > 16:
            _CACHE.popitem(last=False)
    return result


def _calculate_sensitivity(analysis, entrants, predictions, variants, policy, library, *,
                           teams, generated_at, profile_id, tier_names, format_preferences):
    if not isinstance(variants, list) or len(variants) > len(entrants) + 12:
        raise ValueError("Invalid observed-game sensitivity coverage")
    ids = analysis.baseline_order
    positions = {key: [index + 1] for index, key in enumerate(analysis.suggested_order)}
    changed_tiers = {"game_removal": 0, "cluster_resample": 0}
    checks = []
    seen = set()
    baseline_members = _members(analysis)
    for variant in variants:
        game_id = variant.get("omitted_game_id")
        kind = variant.get("kind", "game_removal")
        rows = variant.get("predictions")
        if (kind not in changed_tiers or not isinstance(game_id, str) or not game_id
                or game_id in seen or not isinstance(rows, list) or not rows):
            raise ValueError("Invalid observed-game sensitivity evidence")
        seen.add(game_id)
        merged = {(a, b): {"entrant_a": a, "entrant_b": b, **_prediction_dict(value)}
                  for (a, b), value in predictions.items()}
        changes = set()
        for row in rows:
            key = (row.get("entrant_a"), row.get("entrant_b"))
            if key in changes or key not in merged:
                raise ValueError("Invalid observed-game sensitivity matchup")
            merged[key] = row
            changes.add(key)
        batch = _parse_batch({"schema_version": 1, "generated_at": generated_at, "ratings_as_of": None,
                              "cohorts": {"field": {"teams": teams, "unavailable": {}, "unavailable_codes": {},
                                                    "predictions": list(merged.values())}}},
                             {"field": {key: value["team_id_master"] for key, value in teams.items()}}, "sensitivity")
        pairs = batch.predictions["field"]
        trial = build_cheat_sheet_analysis(entrants, pairs, policy, ordering_method="cohort_expected_points_v1",
                                           manual_order=analysis.ordered_ids if analysis.manual_override else None,
                                           manual_holds=analysis.manual_holds)
        trial = replace(trial, tier_guidance=build_tier_guidance(
            trial, entrants, pairs, policy, library, profile_id=profile_id, tier_names=tier_names,
            format_preferences=format_preferences,
        ))
        for index, key in enumerate(trial.suggested_order):
            if key in positions:
                positions[key].append(index + 1)
        changed = _members(trial) != baseline_members
        changed_tiers[kind] += int(changed)
        checks.append({"omitted_game_id": game_id, "kind": kind, "tier_membership_changed": changed,
                       "cuts": trial.tier_guidance.get("cuts", []), "status": trial.tier_guidance.get("status")})
    return {"method": "influential_game_and_team_event_cluster_stress",
            "games_checked": sum(item["kind"] == "game_removal" for item in checks),
            "cluster_samples": sum(item["kind"] == "cluster_resample" for item in checks),
            "changed_tier_memberships": changed_tiers["game_removal"],
            "cluster_changed_tier_memberships": changed_tiers["cluster_resample"],
            "seed_ranges": {key: [min(positions[key]), max(positions[key])] for key in ids}, "checks": checks,
            "limitation": "Influential games and twelve team/event cluster stress samples; not confidence intervals. "
                          "Unknown event labels use individual game clusters."}


def _prediction_dict(prediction):
    from dataclasses import asdict
    return asdict(prediction)


def _members(analysis):
    cuts = [0, *analysis.tier_guidance.get("cuts", []), len(analysis.ordered_ids)]
    return tuple(frozenset(analysis.ordered_ids[left:right]) for left, right in zip(cuts, cuts[1:]))
