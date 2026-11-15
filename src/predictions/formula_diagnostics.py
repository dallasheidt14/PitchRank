"""Score isolated formula replays only against server-released results. Never deploy."""

from __future__ import annotations

from collections import Counter

from src.predictions.compare_benchmark import paired_event_interval
from src.predictions.prospective_fixtures import database_result, settlement_aliases, strict_resolver
from src.predictions.sos_monitoring import digest, frame_for, review_rows, slices, summaries, validate_prediction

ARMS = (
    "baseline", "sos_x0", "sos_x0.5", "sos_x1.5", "fixed_sos_0.06", "fixed_sos_0.12",
    "fixed_sos_0.18", "extra_record_off",
)
MIN_MATCHES = 1000
MIN_GROUPS = 20


def released_formula_records(client, report, *, preview=True):
    """Ask the existing server gate before any result lookup; preview reads no outcomes."""
    if report.get("study") != "compare-formula-diagnostic-v1" or report.get("live_formula_changed") is not False:
        raise ValueError("Expected the isolated formula report")
    cases = {row["id"]: row for row in report["cases"]}
    if len(cases) != len(report["cases"]):
        raise ValueError("Duplicate forecast in formula report")
    counts, records = Counter(), []
    resolver = aliases = None
    for row in review_rows(client, report["model_signature"], preview=preview):
        case = cases.get(row["baseline_forecast_id"])
        if case is None:
            counts["missing_candidate_replay"] += 1
            continue
        counts["captured"] += 1
        if not row["open"]:
            if row.get("payload") is not None or row.get("fixture") is not None:
                raise ValueError("Server exposed sealed inputs")
            counts["sealed_or_future"] += 1
            continue
        if preview:
            counts["reviewable"] += 1
            continue
        payload = row["payload"]
        if digest(case["context"]) != digest(payload["context"]):
            raise ValueError("Candidate inputs differ from the captured forecast")
        variants = case["variants"]
        if set(variants) != set(ARMS):
            raise ValueError("Incomplete paired candidates")
        for result in variants.values():
            validate_prediction(result["prediction"])
            if result["prediction"].get("predictedWinner") not in ("team_a", "team_b", "draw"):
                raise ValueError("Missing emitted winner decision")
            receipt = result["receipt"]
            if receipt.get("aa_parity") is not True or receipt.get("reference_time") != payload["reference_time"]:
                raise ValueError("Unverified candidate replay")
        if digest(variants["baseline"]["prediction"]) != digest(payload["prediction"]):
            raise ValueError("Baseline differs from the captured forecast")
        if not row.get("group") or row.get("group_kind") not in ("event", "inferred_competition_week"):
            counts["missing_group"] += 1
            continue
        if resolver is None:
            resolver = strict_resolver(client)
            aliases = settlement_aliases(resolver)
        result, reversed_scores, reason = database_result(client, row["fixture"], resolver, aliases)
        if result is None:
            counts[reason] += 1
            continue
        scores = [result["home_score"], result["away_score"]]
        if reversed_scores:
            scores.reverse()
        predictions = {arm: value["prediction"] for arm, value in variants.items()}
        records.append({**row, "scores": scores, "actual_game_id": result["id"],
                        "payload": {**payload, "variants": predictions}})
        counts["settled"] += 1
    counts["missing_server_forecast"] = len(cases) - counts["captured"]
    return records, dict(counts)


def formula_accuracy_report(records, coverage):
    """One physical game per observation, shared across all candidates and orientations."""
    unique = {}
    for row in sorted(records, key=lambda r: (r["captured_at"], r["baseline_forecast_id"])):
        unique.setdefault(row["actual_game_id"], row)
    paired = list(unique.values())
    frames = {arm: frame_for(paired, arm) for arm in ARMS}
    for arm, frame in frames.items():
        frame["predicted_outcome"] = [row["payload"]["variants"][arm]["predictedWinner"] for row in paired]
    baseline = frames["baseline"]
    groups = baseline.event_group.nunique() if len(baseline) else 0
    result = {
        "status": "insufficient_data", "coverage": coverage, "paired_matches": len(paired),
        "groups": int(groups), "duplicate_observations_removed": len(records) - len(paired),
        "minimum_matches": MIN_MATCHES, "minimum_groups": MIN_GROUPS,
        "candidate_provenance": "reconstructed_from_frozen_inputs", "adoption_decision": "not_authorized",
        "metrics": None,
    }
    if len(paired) < MIN_MATCHES or groups < MIN_GROUPS:
        return result
    result["status"] = "exploratory_comparison"
    result["metrics"] = {
        arm: {"overall": summaries(frame), "slices": slices(frame),
              "paired_log_loss_difference_95": [0.0, 0.0] if arm == "baseline" else
              paired_event_interval(baseline, frame, samples=2000, seed=1449)}
        for arm, frame in frames.items()
    }
    result["group_provenance"] = dict(Counter(row["group_kind"] for row in paired))
    result["limitations"] = [
        "Exploratory reconstruction is not a registered prospective confirmation.",
        "No candidate selection or live release is authorized by this report.",
    ]
    return result
