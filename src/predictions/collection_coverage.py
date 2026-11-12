"""Outcome-blind collection denominators and sampling gaps, independent of model evaluation."""

from collections import Counter

from src.predictions.form_archive_sources import frozen_coverage
from src.predictions.prospective_fixtures import database_fixture_inventory, select_fixture_candidates

STRATUM_FIELDS = ("provider", "age_group", "gender", "rating_history_band")


def selection_counts(selected):
    counts = Counter(tuple(row["fixture_payload"]["collection_stratum"][key] for key in STRATUM_FIELDS)
                     for _, row in selected)
    return [{**dict(zip(STRATUM_FIELDS, key)), "selected": count} for key, count in sorted(counts.items())]


def collection_coverage(client, *, limit=500, today=None):
    if type(limit) is not int or not 1 <= limit <= 500:
        raise ValueError("limit must be between 1 and 500")
    candidates, inventory, forecasts = database_fixture_inventory(client, today=today)
    comparisons = {policy: selection_counts(select_fixture_candidates(candidates, limit, policy))
                   for policy in ("chronological", "balanced")}
    provider_counts = {provider: Counter() for provider in inventory["providers"]}
    for label, counts in inventory["strata"].items():
        provider_counts.setdefault(label[0], Counter()).update(counts)
    for policy, selected in comparisons.items():
        for row in selected:
            provider_counts[row["provider"]][policy + "_selected"] += row["selected"]
    saved, statuses = Counter(), Counter()
    for row in forecasts:
        status = row.get("heuristic_prediction_status") or "unknown"
        statuses[status] += 1
        if status != "completed":
            continue
        payload = row.get("heuristic_prediction") or {}
        signature = str(payload.get("modelSignature") or "unknown")
        coverage = frozen_coverage(row)
        saved[(signature, coverage["provider"], coverage["cohort"], coverage["history_band"])] += 1
    gaps = []
    for provider, counts in sorted(provider_counts.items()):
        if not counts["seen"]:
            gaps.append({"provider": provider, "reason": "no_stored_upcoming_fixtures"})
        elif not counts["eligible"] and not counts["already_recorded"]:
            gaps.append({"provider": provider, "reason": "all_stored_fixtures_excluded", "counts": dict(counts)})
        elif counts["eligible"] and not counts["chronological_selected"]:
            gaps.append({"provider": provider, "reason": "chronological_cap_misses_eligible_provider",
                         "eligible_new": counts["eligible"], "balanced_selected": counts["balanced_selected"]})
    count_fields = {"seen", "eligible", "already_recorded", "chronological_selected", "balanced_selected"}
    count_fields.update(key for counts in provider_counts.values() for key in counts)
    return {
        "schema_version": 1, "window_start": inventory["window_start"], "window_end": inventory["window_end"],
        "outcome_metrics_read": False, "capture_limit": limit,
        "new_eligible": len(candidates), "exclusions": inventory["skipped"],
        "providers": [{"provider": provider, **{key: counts[key] for key in sorted(count_fields)}}
                      for provider, counts in sorted(provider_counts.items())],
        "pool_strata": [{**dict(zip(STRATUM_FIELDS, key)), **counts}
                        for key, counts in sorted(inventory["strata"].items())],
        "selection_comparison": comparisons,
        "saved_statuses": dict(statuses),
        "saved_strata": [{"model_signature": key[0], "provider": key[1], "cohort": key[2],
                          "usable_history_band": key[3], "forecasts": count} for key, count in sorted(saved.items())],
        "gaps": gaps,
        "limitations": [
            "The denominator is stored upcoming fixtures, not all youth soccer fixtures.",
            "Balanced sampling increases coverage of small strata; it is not a national random sample.",
            "Pool history uses the smaller current rating games_played count; saved history uses frozen usable games. "
            "These are different measures.",
            "Providers without stored upcoming fixtures need fixture intake work, not relaxed identity/rating checks.",
            "No scores, candidate accuracy, or sealed study results are inspected by this report.",
        ],
    }
