"""Private live-model review and SOS qualification. No formula or ranking writes."""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from datetime import date, timedelta

import pandas as pd

from src.predictions.compare_benchmark import paired_event_interval
from src.predictions.evaluation_reporting import compute_evaluation_summary, outcome_log_losses
from src.predictions.prospective_fixtures import database_result, paged, settlement_aliases, strict_resolver

ARMS = ("0", "0.5", "1", "1.5")


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def validate_prediction(p):
    values = [p.get(k) for k in ("winProbabilityA", "drawProbability", "winProbabilityB", "blowout4PlusProbability")]
    if any(type(v) not in (float, int) or not math.isfinite(v) or not 0 <= v <= 1 for v in values):
        raise ValueError("Incomplete probability/risk outputs")
    if abs(sum(values[:3]) - 1) > 1e-9:
        raise ValueError("Probabilities do not sum to one")
    for value in (
        p.get("expectedMargin"),
        p.get("expectedScore", {}).get("teamA"),
        p.get("expectedScore", {}).get("teamB"),
    ):
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError("Incomplete goal outputs")


def coverage_rows(client, signature):
    return list(paged(lambda: client.rpc("compare_monitor_coverage", {"p_signature": signature})))


def review_rows(client, signature, *, preview=False):
    offset = 0
    while True:
        rows = (
            client.rpc("compare_monitor_review", {"p_signature": signature, "p_offset": offset, "p_preview": preview})
            .execute()
            .data
            or []
        )
        yield from rows
        if len(rows) < 1000:
            break
        offset += 1000


def collect_review(client, signature, *, dry_run=True):
    """The server omits sealed payloads; never query their source scores here."""
    counts, coverage, records = Counter(), Counter(), []
    resolver = aliases = None
    rows = list(review_rows(client, signature, preview=dry_run))
    for row in rows:
        counts["captured"] += 1
        coverage[(row["game_date"], row["provider"], "open" if row["open"] else "sealed_or_future")] += 1
        if not row["open"]:
            if row.get("fixture") is not None or row.get("payload") is not None:
                raise ValueError("Server exposed a sealed forecast")
            counts["sealed_or_future"] += 1
            continue
        if dry_run:
            counts["reviewable"] += 1
            continue
        if resolver is None:
            resolver = strict_resolver(client)
            aliases = settlement_aliases(resolver)
        fixture, payload = row["fixture"], row["payload"]
        result, reversed_scores, reason = database_result(client, fixture, resolver, aliases)
        audit = (
            client.rpc(
                "audit_compare_monitor_result",
                {
                    "p_baseline": row["baseline_forecast_id"],
                    "p_signature": signature,
                    "p_status": reason,
                    "p_result": result,
                },
            )
            .execute()
            .data
        )
        if audit:
            counts["result_revisions"] += 1
        if result is None:
            counts[reason] += 1
            continue
        if set(payload.get("variants", {})) != set(ARMS):
            raise ValueError("Missing paired SOS variants")
        for prediction in payload["variants"].values():
            validate_prediction(prediction)
        scores = [result["home_score"], result["away_score"]]
        if reversed_scores:
            scores.reverse()
        records.append({**row, "scores": scores, "actual_game_id": result["id"]})
        counts["settled"] += 1
    return (
        records,
        {
            "counts": dict(counts),
            "coverage": [
                {"day": day, "provider": provider, "status": status, "games": number}
                for (day, provider, status), number in sorted(coverage.items())
            ],
        },
        rows,
    )


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def band(value, cuts, labels):
    if not finite(value):
        return "unknown"
    return next((label for cut, label in zip(cuts, labels) if value < cut), labels[-1])


def frame_for(records, arm="1"):
    rows = []
    for row in records:
        payload = row["payload"]
        p = payload["variants"][arm]
        a, b = [payload["context"][key] for key in ("teamAInput", "teamBInput")]
        scores = row["scores"]
        sos = a["sos_norm"] - b["sos_norm"] if finite(a.get("sos_norm")) and finite(b.get("sos_norm")) else None
        power = (
            a["power_score_final"] - b["power_score_final"]
            if finite(a.get("power_score_final")) and finite(b.get("power_score_final"))
            else None
        )
        probabilities = [p["winProbabilityA"], p["drawProbability"], p["winProbabilityB"]]
        histories = [
            [
                g
                for g in payload["context"]["frozenEvidence"]["games"]
                if team["team_id_master"] in (g.get("home_team_master_id"), g.get("away_team_master_id"))
            ]
            for team in (a, b)
        ]
        ages = "/".join(sorted({str(team.get("age") or "unknown") for team in (a, b)}))
        genders = "/".join(sorted({str(team.get("gender") or "unknown") for team in (a, b)}))
        rows.append(
            {
                "actual_game_id": row["actual_game_id"],
                "game_date": row["game_date"],
                "event_group": row["group"] or "unknown",
                "group_kind": row["group_kind"],
                "provider": row["provider"],
                "age": ages,
                "gender": genders,
                "history": band(min(map(len, histories)), [4, 8], ["0-3", "4-7", "8+"]),
                "sos_gap": band(
                    abs(sos) if sos is not None else None, [0.1, 0.25], ["under_0.10", "0.10-0.25", "0.25+"]
                ),
                "rating_gap": band(
                    abs(power) if power is not None else None, [0.05, 0.15], ["under_0.05", "0.05-0.15", "0.15+"]
                ),
                "sos_form_conflict": "unknown" if sos is None else str(sos * (p["formA"] - p["formB"]) < 0),
                "confidence_band": band(
                    max(probabilities),
                    [0.5, 0.6, 0.7, 0.8, 0.9],
                    ["under_50", "50-60", "60-70", "70-80", "80-90", "90+"],
                ),
                "prob_team_a_win": probabilities[0],
                "prob_draw": probabilities[1],
                "prob_team_b_win": probabilities[2],
                "actual_outcome": "team_a" if scores[0] > scores[1] else "team_b" if scores[1] > scores[0] else "draw",
                "actual_score_a": scores[0],
                "actual_score_b": scores[1],
                "actual_margin": scores[0] - scores[1],
                "predicted_margin": p["expectedMargin"],
                "predicted_score_a": p["expectedScore"]["teamA"],
                "predicted_score_b": p["expectedScore"]["teamB"],
                "blowout_4plus_probability": p["blowout4PlusProbability"],
            }
        )
    return pd.DataFrame(rows)


def summaries(frame):
    if frame.empty:
        return compute_evaluation_summary(frame)
    result = compute_evaluation_summary(frame)
    result["expected_draw_rate"] = float(frame.prob_draw.mean())
    result["groups"] = int(frame.event_group.nunique())
    accuracy, n, z = result["winner_accuracy"], len(frame), 1.959963984540054
    center = (accuracy + z * z / (2 * n)) / (1 + z * z / n)
    width = z * math.sqrt(accuracy * (1 - accuracy) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    result["winner_accuracy_95_wilson"] = [max(0.0, center - width), min(1.0, center + width)]
    result["average_top_probability"] = float(
        frame[["prob_team_a_win", "prob_draw", "prob_team_b_win"]].max(axis=1).mean()
    )
    return result


def slices(frame):
    if frame.empty:
        return []
    output = []
    for columns in (
        ["provider"],
        ["age"],
        ["gender"],
        ["history"],
        ["confidence_band"],
        ["sos_form_conflict"],
        ["age", "gender", "rating_gap", "sos_gap"],
    ):
        for key, group in frame.groupby(columns, dropna=False):
            values = key if isinstance(key, tuple) else (key,)
            output.append({"slice": dict(zip(columns, values)), **summaries(group)})
    return output


def weekly_report(records, coverage, as_of):
    # Exact result identity is the observation unit, and the first capture wins.
    input_count = len(records)
    unique = {}
    for row in sorted(records, key=lambda r: (r["captured_at"], r["baseline_forecast_id"])):
        unique.setdefault(row["actual_game_id"], row)
    records = list(unique.values())
    frame = frame_for(records)
    week_start = (date.fromisoformat(as_of[:10]) - timedelta(days=7)).isoformat()
    recent = frame[frame.game_date >= week_start] if not frame.empty else frame
    cases = []
    if not frame.empty:
        losses = outcome_log_losses(frame)
        for i in sorted(range(len(frame)), key=lambda i: (-losses[i], str(frame.iloc[i].actual_game_id)))[:10]:
            row = frame.iloc[i]
            correct = (
                row.actual_outcome
                == ("team_a", "draw", "team_b")[
                    max(range(3), key=lambda j: row[["prob_team_a_win", "prob_draw", "prob_team_b_win"]].iloc[j])
                ]
            )
            cases.append(
                {
                    "source_game_id": str(row.actual_game_id),
                    "correct": correct,
                    "log_loss": float(losses[i]),
                    "sos_gap": row.sos_gap,
                    "rating_gap": row.rating_gap,
                    "actual_outcome": row.actual_outcome,
                }
            )
        # Include correct comparisons as well as the largest misses.
        correct_rows = frame[
            [
                r["actual_outcome"]
                == ("team_a", "draw", "team_b")[
                    max(range(3), key=lambda j: r[["prob_team_a_win", "prob_draw", "prob_team_b_win"]].iloc[j])
                ]
                for _, r in frame.iterrows()
            ]
        ]
        cases.extend(
            {
                "source_game_id": str(r.actual_game_id),
                "correct": True,
                "sos_gap": r.sos_gap,
                "rating_gap": r.rating_gap,
                "actual_outcome": r.actual_outcome,
            }
            for _, r in correct_rows.head(5).iterrows()
        )
    return {
        "schema_version": 1,
        "as_of": as_of,
        "status": "review" if records else "coverage_only",
        "production_promotion": False,
        "coverage": coverage,
        "duplicate_results": input_count - len(unique),
        "cumulative": summaries(frame),
        "last_seven_days": summaries(recent),
        "slices": slices(frame),
        "case_review": cases,
        "interpretation": (
            "Exploratory associations; schedule strength is already embedded in ratings. "
            "Small slices do not establish a cause."
        ),
    }


def evaluate_sos(records, metadata, model, selection, as_of):
    """Selection uses development only; confirmation never selects another arm."""
    start, end = model["development_start"], model["development_end"]
    groups = {}
    for row in metadata:
        groups.setdefault(row["group"], set()).add("dev" if start <= row["game_date"] <= end else "other")
    crossing = {group for group, periods in groups.items() if len(periods) > 1}
    unique = {}
    for row in sorted(records, key=lambda r: (r["captured_at"], r["baseline_forecast_id"])):
        if row["group"] and row["group"] not in crossing:
            unique.setdefault(row["actual_game_id"], row)
    development = [r for r in unique.values() if start <= r["game_date"] <= end]
    result = {
        "monitor_signature": model["signature"],
        "status": "collecting_development",
        "production_promotion": False,
        "excluded_crossing_groups": len(crossing),
    }
    if as_of[:10] <= end:
        return result
    frames = {arm: frame_for(development, arm) for arm in ARMS}
    base = frames["1"]
    binding = [
        {key: row[key] for key in ("baseline_forecast_id", "actual_game_id", "scores", "captured_at")}
        | {"payload_sha256": row.get("payload_sha256")}
        for row in development
    ]
    result.update(
        games=len(base), groups=0 if base.empty else int(base.event_group.nunique()), dataset_sha256=digest(binding)
    )
    if result["games"] < 1000 or result["groups"] < 20:
        return {**result, "status": "insufficient_development"}
    metrics = {arm: summaries(frame) for arm, frame in frames.items()}
    selected = min(
        ARMS, key=lambda arm: (metrics[arm]["log_loss"], metrics[arm]["brier_score"], abs(float(arm) - 1), float(arm))
    )
    result.update(
        metrics=metrics, selected=selected, status="retain_baseline" if selected == "1" else "selected_for_confirmation"
    )
    if not selection:
        return result
    if selection["qualification"]["dataset_sha256"] != result["dataset_sha256"]:
        return {**result, "status": "development_evidence_changed_review_required"}
    selected = str(float(selection["multiplier"])).removesuffix(".0")
    confirmation_end = selection["confirmation_end"]
    result.update(selected=selected, status="collecting_confirmation", confirmation_end=confirmation_end)
    if as_of[:10] <= confirmation_end:
        return result
    confirmation = [r for r in unique.values() if selection["confirmation_start"] <= r["game_date"] <= confirmation_end]
    baseline, candidate = [frame_for(confirmation, arm) for arm in ("1", selected)]
    if len(baseline) < 1000 or baseline.event_group.nunique() < 20:
        return {**result, "status": "insufficient_confirmation", "paired_games": len(baseline)}
    interval = paired_event_interval(baseline, candidate, samples=1000, seed=20261113)
    bs, cs = summaries(baseline), summaries(candidate)
    qualifies = cs["brier_score"] < bs["brier_score"] and interval[1] < 0
    return {
        **result,
        "status": "release_review_required" if qualifies else "retain_baseline",
        "paired_games": len(baseline),
        "confirmation_groups": int(baseline.event_group.nunique()),
        "log_loss_delta_95": interval,
        "baseline": bs,
        "candidate": cs,
        "baseline_slices": slices(baseline),
        "candidate_slices": slices(candidate),
    }


def models(client):
    return list(paged(lambda: client.table("compare_monitoring_models").select("*").order("signature")))
