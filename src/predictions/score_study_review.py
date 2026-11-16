"""Evaluate registered score-only pairs after server release; never select a new candidate."""

import math
from collections import Counter, defaultdict

import numpy as np
from storage3.exceptions import StorageApiError

from src.predictions.prospective_fixtures import ambiguous_pair_games, evaluation_group
from src.predictions.score_challenger import CANDIDATES, OUTCOME_FIELDS, score_candidate
from src.predictions.score_study import POLICY, digest, serialized
from src.predictions.score_study_capture import registered_study
from src.rankings.archive_storage import _retry_transport


def released_rows(client, signature, *, preview=True):
    after = None
    while True:
        page = _retry_transport(lambda: client.rpc("compare_score_review", {
            "p_signature": signature, "p_after": after, "p_preview": preview, "p_limit": 500,
        }).execute()).data or []
        if not page:
            return
        yield from page
        if preview or not page[0]["open"] or len(page) < 500:
            return
        last = page[-1]["baseline_forecast_id"]
        if after is not None and last <= after:
            raise ValueError("Score review cursor did not advance")
        after = last


def _paired_interval(rows, arm):
    groups = defaultdict(lambda: [0.0, 0])
    for row in rows:
        difference = (row["metrics"][arm]["mean_absolute_goals_per_team"]
                      - row["metrics"]["baseline"]["mean_absolute_goals_per_team"])
        groups[row["group"]][0] += difference
        groups[row["group"]][1] += 1
    values = np.array([groups[key] for key in sorted(groups)])
    if len(values) < 2:
        return {"difference": None, "interval_95": None, "one_sided_p": None}
    rng = np.random.default_rng(20261123)
    means = []
    for start in range(0, 10000, 100):
        indices = rng.integers(0, len(values), size=(min(100, 10000-start), len(values)))
        means.extend((values[indices, 0].sum(axis=1) / values[indices, 1].sum(axis=1)).tolist())
    return {"difference": float(values[:, 0].sum()/values[:, 1].sum()),
            "interval_95": np.quantile(means, [0.025, 0.975]).tolist(),
            "one_sided_p": float((1 + np.count_nonzero(np.array(means) >= 0))/10001)}


def accuracy_report(records):
    coverage, paired, seen = Counter(), [], set()
    pair_members = defaultdict(list)
    for row in records:
        pair_members[(row["game_date"], tuple(row["payload"]["team_pair"]))].append(row)
    ambiguous = set()
    for members in pair_members.values():
        sources = {row["source_game_id"]: row for row in members}
        if len(sources)>1 and ambiguous_pair_games([row["fixture_payload"]["source_snapshot"]
                                                   for row in sources.values()]):
            ambiguous.update(sources)
    for row in sorted(records, key=lambda r: (r["captured_at"], r["baseline_forecast_id"])):
        if row["source_game_id"] in ambiguous:
            coverage["ambiguous_same_pair_day"] += 1
            continue
        # Every output arm uses the same physical source row, in its original orientation.
        if row["source_game_id"] in seen:
            coverage["duplicate_source_removed"] += 1
            continue
        seen.add(row["source_game_id"])
        result = row["result"]
        if result is None or any(type(result.get(key)) is not int or result[key] < 0
                                 for key in ("home_score", "away_score")):
            coverage["missing_or_changed_exact_source_result"] += 1
            continue
        snapshot = row["fixture_payload"]["source_snapshot"]
        group_kind, group, event = evaluation_group(row["provider"], {**snapshot, "game_date": row["game_date"]})
        if row.get("group_kind") != group_kind or row.get("group") != group or row.get("source_event_id") != event:
            coverage["unverified_group"] += 1
            continue
        p = row["payload"]
        baseline = p["candidates"]["baseline"]["prediction"]
        a, b = result["home_score"], result["away_score"]
        actual_winner = "team_a" if a>b else "team_b" if b>a else "draw"
        metrics = {}
        for arm in CANDIDATES:
            stored = p["candidates"][arm]["prediction"]
            replay = score_candidate(baseline, p["learned_rates"], candidate=arm, eligibility=p["eligibility"])
            if any(stored[field] != baseline[field] for field in OUTCOME_FIELDS):
                raise ValueError("Frozen score arm changed winner forecasts")
            for field in ("expectedScore", "expectedGoals", "expectedMargin", "blowout4PlusProbability"):
                def equal(x, y):
                    if isinstance(x, dict) and isinstance(y, dict):
                        return x.keys() == y.keys() and all(equal(x[k], y[k]) for k in x)
                    return abs(x-y) <= 1e-12 if type(x) in (int, float) and type(y) in (int, float) else x == y
                if not equal(stored[field], replay.prediction[field]):
                    raise ValueError("Score replay differs from the immutable capture")
            sa, sb = (stored["expectedScore"][key] for key in ("teamA", "teamB"))
            probability = float(replay.matrix[a, b]) if max(a, b) < len(replay.matrix) else 0.0
            metrics[arm] = {
                "mean_absolute_goals_per_team": (abs(sa-a)+abs(sb-b))/2,
                "exact_score_rate": int((sa, sb) == (a, b)), "margin_mae": abs((sa-sb)-(a-b)),
                "score_log_loss": -math.log(max(1e-15, probability)),
                "four_goal_brier": (stored["blowout4PlusProbability"]-int(abs(a-b)>=4))**2,
                "winner_accuracy": int(stored["predictedWinner"] == actual_winner),
            }
        count = min(p["training_games"])
        paired.append({"group": group, "group_kind": group_kind, "eligibility": p["eligibility"], "metrics": metrics,
                       "cohort": "|".join(p["cohort_pair"]),
                       "training_history": "0" if count==0 else "1-3" if count<4 else "4-7" if count<8 else "8+"})
        coverage[p["eligibility"]] += 1
    groups = len({row["group"] for row in paired})
    sufficient = len(paired)>=1000 and groups>=20
    metrics = {arm: {key: float(np.mean([r["metrics"][arm][key] for r in paired]))
                     for key in paired[0]["metrics"][arm]} for arm in CANDIDATES} if paired else {}
    intervals = {arm: _paired_interval(paired, arm) for arm in CANDIDATES[1:]}
    ranked = sorted(intervals, key=lambda arm: intervals[arm]["one_sided_p"] or 1.0)
    accepted = True
    for index, arm in enumerate(ranked):
        p = intervals[arm]["one_sided_p"]
        accepted = accepted and p is not None and p <= 0.05/(2-index)
        intervals[arm]["holm_significant"] = accepted
    slices = {}
    for field in ("eligibility", "cohort", "training_history"):
        slices[field] = {}
        for label in sorted({r[field] for r in paired}):
            members = [r for r in paired if r[field] == label]
            slices[field][label] = {"matches": len(members), "metrics": {
                arm: {key: float(np.mean([r["metrics"][arm][key] for r in members]))
                      for key in members[0]["metrics"][arm]} for arm in CANDIDATES}}
    return {"status": "ready_for_release_review" if sufficient else "insufficient_data",
            "paired_matches": len(paired), "groups": groups, "coverage": dict(coverage),
            "group_provenance": dict(Counter(r["group_kind"] for r in paired)),
            "metrics": metrics, "paired_goal_error": intervals, "slices": slices,
            "policy": POLICY, "production_promotion": False,
            "decision": "Separate release review required; no adoption decision from an insufficient sample",
            "limitations": ["Competition/week groups are inferred when no event ID is verified.",
                            "Recurring teams can remain dependent across groups.",
                            "A posting site is provenance, never a model input or an explanation of an outcome."]}


def review_scores(client, signature, *, dry_run=True):
    registered_study(client, signature)
    rows = list(released_rows(client, signature, preview=dry_run))
    if not rows or dry_run or not rows[0]["open"]:
        return {"status": "coverage_only", "dry_run": dry_run, "release": rows,
                "coverage": _retry_transport(lambda: client.rpc("compare_score_coverage", {
                    "p_signature": signature}).execute()).data or [], "production_promotion": False}
    return {"study_signature": signature, "dry_run": False, **accuracy_report(rows)}


def preserve_report(client, signature, report, *, dry_run=True):
    raw = serialized(report).encode()
    key = f"compare-score-studies/reports/{signature}/{digest(raw)}.json"
    if not dry_run:
        bucket = client.storage.from_("prediction-input-archives")

        def upload():
            try:
                bucket.upload(key, raw, {"content-type": "application/json", "upsert": "false"})
            except StorageApiError as error:
                if error.code not in {"Duplicate", "ResourceAlreadyExists"}:
                    raise

        _retry_transport(upload)
        if _retry_transport(lambda: bucket.download(key)) != raw:
            raise ValueError("Private report readback differs")
    return {"published": not dry_run, "object": key, "sha256": digest(raw)}
