"""Fixed weighted winner confirmation, separate from qualified form and score studies."""

import json
import math
import os
import re
import subprocess
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np

from src.predictions.challenger_sources import candidate_execution_paths
from src.predictions.prospective_fixtures import (
    ambiguous_pair_games,
    database_result,
    evaluation_group,
    settlement_aliases,
    strict_resolver,
)
from src.predictions.score_study import digest, serialized
from src.rankings.archive_storage import _retry_transport

KIND = "compare_weighted_winner_confirmation_v1"
ENTRYPOINT = "scripts/capture_compare_winner_study.py"
WEIGHTS = (
    "strength",
    "schedule",
    "raw_form",
    "offense_defense",
    "record",
    "evidence",
    "head_to_head",
    "common_opponents",
    "ml_directional",
)
POLICY = {
    "minimum_pairs": 1000,
    "minimum_groups": 20,
    "primary_metric": "winner_accuracy",
    "bootstrap": {"unit": "match_group", "repetitions": 10000, "seed": 20261123, "confidence": 0.95},
    "qualification": "accuracy_difference_lower_95_above_zero; log_loss_and_brier_not_worse",
    "release": "separate_review_required; insufficient_data_means_no_decision; no_automatic_promotion",
    "slices": ["age", "history", "ranked", "same_cohort"],
}


def source_identity(root: Path):
    paths = candidate_execution_paths(
        root,
        entrypoints=[
            ENTRYPOINT,
            "scripts/register_compare_winner_study.py",
            "scripts/review_compare_winner_study.py",
            "frontend/scripts/run-winner-study.ts",
            "frontend/lib/matchPredictor.ts",
            "frontend/lib/matchPredictionService.ts",
        ],
    )
    paths.add("frontend/package-lock.json")
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    hashes = {}
    for name in sorted(paths):
        raw = (root / name).read_text(encoding="utf-8").encode()
        committed = subprocess.check_output(["git", "show", f"{revision}:{name}"], cwd=root)
        if raw != committed.replace(b"\r\n", b"\n"):
            raise ValueError("Uncommitted winner-study dependency: " + name)
        hashes[name] = digest(raw)
    return {"code_revision": revision, "execution_hashes": hashes}


def validate_definition(m, *, registered_at=None):
    start, end, review = (date.fromisoformat(m[k]) for k in ("capture_start", "capture_end", "review_not_before"))
    if (
        m.get("kind") != KIND
        or m.get("schema_version") != 1
        or m.get("policy") != POLICY
        or m.get("entrypoint") != ENTRYPOINT
        or m.get("production_promotion") is not False
        or start.weekday() != 0
        or end != start + timedelta(days=27)
        or review < max(date(2027, 1, 11), end + timedelta(days=1))
    ):
        raise ValueError("Invalid fixed winner-study definition")
    for key in ("monitor_signature", "baseline_model_signature", "training_data_sha256", "research_receipt_sha256"):
        if not re.fullmatch(r"[a-f0-9]{64}", m.get(key, "")):
            raise ValueError("Missing baseline or training provenance")
    if (
        not re.fullmatch(r"[a-f0-9]{40}", m.get("code_revision", ""))
        or ENTRYPOINT not in m.get("execution_hashes", {})
        or not all(re.fullmatch(r"[a-f0-9]{64}", h) for h in m["execution_hashes"].values())
        or date.fromisoformat(m["latest_training_game"]) >= start
        or set(m.get("weights", {})) != set(WEIGHTS)
        or any(type(v) not in (float, int) or not math.isfinite(v) or not 0 <= v <= 6 for v in m["weights"].values())
        or m.get("training_evidence") != "exposed_retrospective_research_only"
    ):
        raise ValueError("Invalid committed candidate provenance")
    if registered_at and datetime.fromisoformat(registered_at.replace("Z", "+00:00")).date() >= start:
        raise ValueError("Late registration")


def registered_study(client, signature):
    record = _retry_transport(
        lambda: client.table("compare_winner_studies").select("*").eq("signature", signature).single().execute()
    ).data
    m = record["manifest"]
    validate_definition(m, registered_at=record["registered_at"])
    if digest(serialized(m).encode()) != signature:
        raise ValueError("Manifest signature differs")
    return m


def register_study(client, m, root, *, dry_run=True):
    validate_definition(m)
    identity = source_identity(root)
    if any(identity[key] != m[key] for key in identity):
        raise ValueError("Committed source differs")
    signature = digest(serialized(m).encode())
    if not dry_run:
        saved = _retry_transport(
            lambda: client.rpc("register_compare_winner_study", {"p_manifest": serialized(m)}).execute()
        ).data
        if saved != signature or registered_study(client, signature) != m:
            raise ValueError("Registration readback differs")
    return {
        "dry_run": dry_run,
        "study_signature": signature,
        "registered": not dry_run,
        "capture_start": m["capture_start"],
        "capture_end": m["capture_end"],
        "review_not_before": m["review_not_before"],
    }


def replay(rows, m, root):
    cases = []
    for row in rows:
        parent = row["parent_payload"]
        if (
            row["monitor_signature"] != m["monitor_signature"]
            or parent["model_signature"] != m["baseline_model_signature"]
            or parent["receipt"].get("aa_parity") is not True
            or row["game_date"] <= m["latest_training_game"]
        ):
            raise ValueError("Wrong frozen baseline or training cutoff")
        cases.append(
            {
                "context": parent["context"],
                "prediction": parent["prediction"],
                "reference_time": parent["reference_time"],
            }
        )
    command = [
        "node",
        "--import",
        (root / "frontend/node_modules/tsx/dist/loader.mjs").as_uri(),
        str(root / "frontend/scripts/run-winner-study.ts"),
    ]
    result = subprocess.run(
        command,
        input=serialized({"cases": cases, "weights": m["weights"]}),
        text=True,
        capture_output=True,
        cwd=root,
        env={**os.environ, "TSX_DISABLE_CACHE": "1"},
        timeout=240,
        check=True,
    )
    outputs = json.loads(result.stdout)
    if len(outputs) != len(rows):
        raise ValueError("Incomplete replay batch")
    return outputs


def winner_payload(row, m, output, signature):
    if output["receipt"].get("aa_parity") is not True or output["receipt"].get("baseline_replay") is not True:
        raise ValueError("Unverified baseline parity")
    c = row["parent_payload"]["context"]
    a, b = c["teamAInput"], c["teamBInput"]
    count = min(a.get("games_played", 0), b.get("games_played", 0))
    return {
        "schema_version": 1,
        "study_signature": signature,
        "baseline_payload_sha256": row["parent_payload_sha256"],
        "code_revision": m["code_revision"],
        "execution_hashes": m["execution_hashes"],
        "weights": m["weights"],
        "receipt": output["receipt"],
        "candidates": {
            "baseline": {"prediction": row["parent_payload"]["prediction"]},
            "weighted": {"prediction": output["prediction"]},
        },
        "team_pair": sorted([a["team_id_master"], b["team_id_master"]]),
        "slices": {
            "age": f"{a['age']}|{b['age']}",
            "same_cohort": str((a["age"], a["gender"]) == (b["age"], b["gender"])),
            "history": "0" if count == 0 else "1-3" if count < 4 else "4-7" if count < 8 else "8+",
            "ranked": str(
                all(t.get("status") == "Active" and t.get("rank_in_cohort_final") is not None for t in (a, b))
            ),
        },
    }


def capture_winners(client, signature, root, *, dry_run=True, limit=500):
    if not 1 <= limit <= 500:
        raise ValueError("Limit must be between 1 and 500")
    m = registered_study(client, signature)
    identity = source_identity(root)
    if any(identity[key] != m[key] for key in identity):
        raise ValueError("Capture source differs")
    summary = {"dry_run": dry_run, "selected": 0, "validated": 0, "captured": 0, "already_captured": 0, "errors": {}}
    errors, after = Counter(), None
    scan_limit = min(5000, limit * 10)
    while summary["selected"] < scan_limit and summary["validated"] < limit:
        rows = (
            _retry_transport(
                lambda: client.rpc(
                    "compare_winner_capture_queue",
                    {
                        "p_signature": signature,
                        "p_after": after,
                        "p_limit": min(limit - summary["validated"], scan_limit - summary["selected"]),
                    },
                ).execute()
            ).data
            or []
        )
        if not rows:
            break
        for row in rows:
            cursor = row["baseline_forecast_id"]
            if after is not None and cursor <= after:
                raise ValueError("Capture cursor did not advance")
            after = cursor
            summary["selected"] += 1
            try:
                output = replay([row], m, root)[0]
                payload = winner_payload(row, m, output, signature)
                if not dry_run:
                    saved = _retry_transport(
                        lambda: client.rpc(
                            "freeze_compare_winner_forecast",
                            {
                                "p_signature": signature,
                                "p_baseline": cursor,
                                "p_payload": serialized(payload),
                            },
                        ).execute()
                    ).data
                    stored = _retry_transport(
                        lambda: (
                            client.table("compare_winner_forecasts")
                            .select("payload,payload_sha256,captured_at")
                            .eq("study_signature", signature)
                            .eq("baseline_forecast_id", cursor)
                            .single()
                            .execute()
                        )
                    ).data
                    if stored["payload"] != payload or stored["payload_sha256"] != digest(serialized(payload).encode()):
                        raise ValueError("Capture readback differs")
                    summary["captured" if saved else "already_captured"] += 1
                summary["validated"] += 1
            except Exception as error:
                errors[type(error).__name__] += 1
    summary["scan_limit_reached"] = summary["selected"] >= scan_limit
    summary["errors"] = dict(errors)
    summary["coverage"] = (
        _retry_transport(lambda: client.rpc("compare_winner_coverage", {"p_signature": signature}).execute()).data or []
    )
    return summary


def accuracy_report(records):
    coverage, pairs, seen = Counter(), [], set()
    members = defaultdict(list)
    for r in records:
        members[(r["game_date"], tuple(r["payload"]["team_pair"]))].append(r)
    ambiguous = set()
    for rows in members.values():
        sources = {r["source_game_id"]: r for r in rows}
        if len(sources) > 1 and ambiguous_pair_games(
            [r["fixture_payload"]["source_snapshot"] for r in sources.values()]
        ):
            ambiguous.update(sources)
    for row in sorted(records, key=lambda r: (r["captured_at"], r["baseline_forecast_id"])):
        if row["source_game_id"] in seen or row["source_game_id"] in ambiguous:
            coverage["duplicate_or_ambiguous_source"] += 1
            continue
        seen.add(row["source_game_id"])
        result = row["result"]
        if not result or any(type(result.get(k)) is not int or result[k] < 0 for k in ("home_score", "away_score")):
            coverage["missing_or_changed_exact_source_result"] += 1
            continue
        group_kind, group, event = evaluation_group(
            row["provider"], {**row["fixture_payload"]["source_snapshot"], "game_date": row["game_date"]}
        )
        if (group_kind, group, event) != (row["group_kind"], row["group"], row["source_event_id"]):
            coverage["unverified_group"] += 1
            continue
        a, b = result["home_score"], result["away_score"]
        actual = "team_a" if a > b else "team_b" if b > a else "draw"
        index = ["team_a", "draw", "team_b"].index(actual)
        metrics = {}
        for arm in ("baseline", "weighted"):
            p = row["payload"]["candidates"][arm]["prediction"]
            probs = [p[k] for k in ("winProbabilityA", "drawProbability", "winProbabilityB")]
            metrics[arm] = {
                "winner_accuracy": int(p["predictedWinner"] == actual),
                "log_loss": -math.log(max(1e-15, probs[index])),
                "brier": sum((prob - int(i == index)) ** 2 for i, prob in enumerate(probs)),
                "four_goal_brier": (p["blowout4PlusProbability"] - int(abs(a - b) >= 4)) ** 2,
                "margin_mae": abs(p["expectedMargin"] - (a - b)),
                "draw_probability": p["drawProbability"],
                "draw_rate": int(a == b),
            }
        pairs.append({"group": group, "group_kind": group_kind, "metrics": metrics, **row["payload"]["slices"]})

    def means(rows):
        return (
            {
                arm: {key: float(np.mean([r["metrics"][arm][key] for r in rows])) for key in rows[0]["metrics"][arm]}
                for arm in ("baseline", "weighted")
            }
            if rows
            else {}
        )

    groups = defaultdict(lambda: [0.0, 0])
    for row in pairs:
        groups[row["group"]][0] += (
            row["metrics"]["weighted"]["winner_accuracy"] - row["metrics"]["baseline"]["winner_accuracy"]
        )
        groups[row["group"]][1] += 1
    interval = None
    if len(groups) >= 2:
        values = np.array([groups[k] for k in sorted(groups)])
        rng, samples = np.random.default_rng(20261123), []
        for _ in range(100):
            draw = values[rng.integers(0, len(values), size=(100, len(values)))]
            samples.extend((draw[:, :, 0].sum(axis=1) / draw[:, :, 1].sum(axis=1)).tolist())
        interval = np.quantile(samples, [0.025, 0.975]).tolist()
    metrics = means(pairs)
    sufficient = len(pairs) >= 1000 and len(groups) >= 20
    qualified = bool(
        sufficient
        and interval
        and interval[0] > 0
        and all(metrics["weighted"][k] <= metrics["baseline"][k] for k in ("log_loss", "brier"))
    )
    return {
        "status": "qualified_for_release_review"
        if qualified
        else "criteria_not_met"
        if sufficient
        else "insufficient_data",
        "paired_matches": len(pairs),
        "groups": len(groups),
        "coverage": dict(coverage),
        "metrics": metrics,
        "accuracy_difference_interval_95": interval,
        "group_provenance": dict(Counter(r["group_kind"] for r in pairs)),
        "slices": {
            field: {
                label: {"matches": len(rows := [r for r in pairs if r[field] == label]), "metrics": means(rows)}
                for label in sorted({r[field] for r in pairs})
            }
            for field in POLICY["slices"]
        },
        "policy": POLICY,
        "production_promotion": False,
        "limitations": [
            "Inferred groups are labeled; recurring teams may remain dependent across groups.",
            "Posting sites are provenance, never causal explanations of results.",
            "Adverse subgroup and four-goal risk results require separate release review.",
        ],
    }


def review_winners(client, signature, root, *, dry_run=True):
    m = registered_study(client, signature)
    identity = source_identity(root)
    if any(identity[key] != m[key] for key in identity):
        raise ValueError("Review source differs from registered analysis")
    rows, after = [], None
    while True:
        page = (
            _retry_transport(
                lambda: client.rpc(
                    "compare_winner_review",
                    {"p_signature": signature, "p_after": after, "p_preview": dry_run, "p_limit": 500},
                ).execute()
            ).data
            or []
        )
        if not page and rows:
            break
        if not page or dry_run or not page[0]["open"]:
            return {
                "status": "coverage_only",
                "release": page,
                "coverage": _retry_transport(
                    lambda: client.rpc("compare_winner_coverage", {"p_signature": signature}).execute()
                ).data
                or [],
                "production_promotion": False,
            }
        rows.extend(page)
        if len(page) < 500:
            break
        last = page[-1]["baseline_forecast_id"]
        if after is not None and last <= after:
            raise ValueError("Review cursor did not advance")
        after = last
    # Only the released branch loads the canonical alias graph or scans target-day games.
    resolver = strict_resolver(client)
    aliases = settlement_aliases(resolver)
    for row in rows:
        if row["result"] is None:
            continue
        snapshot = row["fixture_payload"]["source_snapshot"]
        fixture = {**row, **{key: snapshot.get(key) for key in ("home_team_master_id", "away_team_master_id")}}
        game, reversed_orientation, reason = _retry_transport(
            lambda: database_result(client, fixture, resolver, aliases)
        )
        if (
            reason != "source_game_id"
            or reversed_orientation
            or game is None
            or any(game.get(key) != snapshot.get(key) for key in ("home_team_master_id", "away_team_master_id"))
            or any(game.get(key) != row["result"].get(key) for key in ("home_score", "away_score"))
        ):
            row["result"] = None
    return {
        "study_signature": signature,
        **accuracy_report(rows),
        "capture_coverage": _retry_transport(
            lambda: client.rpc("compare_winner_coverage", {"p_signature": signature}).execute()
        ).data
        or [],
    }
