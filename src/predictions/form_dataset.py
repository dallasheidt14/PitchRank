"""Build versioned local datasets from registered studies and exact frozen sources."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from collections import Counter, defaultdict
from datetime import timedelta
from itertools import zip_longest
from pathlib import Path

from src.predictions.archive_inputs import (
    _registered_manifest,
    authenticate_archive,
    download_archive,
    registered_inventory,
)
from src.predictions.forecast_archive import FORECAST_FIELDS
from src.predictions.form_archive_sources import FrozenSourceIndex
from src.predictions.form_policy import PINNED_REVISION, ResearchPolicy
from src.predictions.form_research import audit_cases, digest, finite, match_start, prediction_input_error, timestamp
from src.predictions.form_study import research_hashes
from src.predictions.form_study_contract import FORM_STUDY_KIND, validate_study_definition
from src.predictions.prospective_fixtures import evaluation_group, source_fixture_identity
from src.rankings.input_archive import FORECAST_ARCHIVE_KIND, FORECAST_TABLE, source_file_names

ROOT = Path(__file__).resolve().parents[2]
SETTLEMENT_FIELDS = (FORECAST_FIELDS + ",evaluation_status,actual_game_id,"
                     "actual_home_score,actual_away_score,actual_outcome")
RESULT_FIELDS = ("id,game_date,home_team_master_id,away_team_master_id,provider_id,source_url,"
                 "home_score,away_score,is_excluded")
CASE_BATCH_SIZE = 200


def assert_registered_checkout(study) -> ResearchPolicy:
    manifest = study.manifest
    if manifest.get("configuration", {}).get("capture_kind") != FORM_STUDY_KIND:
        raise ValueError("Expected a separately registered Compare form study")
    definition = manifest["configuration"]["study_definition"]
    policy = validate_study_definition(definition, registered_at=study.recorded_at)
    current = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    dirty = subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True).strip()
    if dirty or current != manifest["source_revision"]:
        raise ValueError("Use a clean checkout of the registered research revision")
    actual = research_hashes((name, (ROOT / name).read_bytes()) for name in source_file_names(ROOT))
    if actual != definition["research_sources"]:
        raise ValueError("Research code differs from the registered study")
    return policy


def _selected_rows(client, table: str, fields: str, ids: list[str], key: str) -> dict:
    result = {}
    for start in range(0, len(ids), 100):
        rows = (client.table(table).select(fields).in_(key, ids[start:start + 100])
                .order(key).range(0, 999).execute().data or [])
        for row in rows:
            if row[key] in result or row[key] not in ids[start:start + 100]:
                raise ValueError("Result lookup did not return the requested unique source identities")
            result[row[key]] = row
    return result


def _result_error(raw: dict, settled: dict | None, game: dict | None) -> str | None:
    if not settled or settled.get("evaluation_status") != "settled":
        return "unsettled_result"
    if digest({key: settled.get(key) for key in FORECAST_FIELDS.split(",")}) != digest(raw):
        return "completed_forecast_changed"
    if settled.get("actual_game_id") != raw["source_game_id"] or not game or game["id"] != raw["source_game_id"]:
        return "not_exact_source_settlement"
    snapshot = raw.get("fixture_payload", {}).get("source_snapshot", {})
    if not snapshot or any(game.get(key) != snapshot.get(key) for key in (
        "game_date", "home_team_master_id", "away_team_master_id", "provider_id", "source_url",
    )):
        return "result_source_identity_changed"
    if game.get("is_excluded") is not False:
        return "excluded_result"
    scores = [settled.get("actual_home_score"), settled.get("actual_away_score")]
    if (not all(finite(score) and score >= 0 and int(score) == score for score in scores)
            or scores != [game.get("home_score"), game.get("away_score")]):
        return "invalid_or_changed_actual_scores"
    outcome = "team_a" if scores[0] > scores[1] else "team_b" if scores[1] > scores[0] else "draw"
    if settled.get("actual_outcome") != outcome:
        return "conflicting_actual_outcome"
    return None


class _Groups:
    def __init__(self):
        self.parents = {}

    def root(self, value):
        parent = self.parents.setdefault(value, value)
        if parent != value:
            self.parents[value] = self.root(parent)
        return self.parents[value]

    def join(self, values):
        roots = sorted({self.root(value) for value in values})
        for root in roots[1:]:
            self.parents[root] = roots[0]


def grouped_members(members: list[dict]) -> tuple[list[dict], Counter, dict]:
    aliases_by_day, groups, exclusions = defaultdict(_Groups), _Groups(), Counter()
    for meta in members:
        aliases = aliases_by_day[meta["game_date"]]
        aliases.join(meta["team_a_ids"])
        aliases.join(meta["team_b_ids"])
    candidates, duplicate_keys, reasons = [], defaultdict(list), {}
    for meta in members:
        aliases = aliases_by_day[meta["game_date"]]
        snapshot = meta["fixture_payload"].get("source_snapshot", {})
        kind, key, event = evaluation_group(meta["provider_code"], {**snapshot, "game_date": meta["game_date"]})
        declared_kind, declared_key = meta["evaluation_group_kind"], meta["evaluation_group_key"]
        if declared_kind == "event":
            valid = kind == "event" and event == meta["source_event_id"] and key == declared_key
        else:
            valid = (declared_kind == "inferred_competition_week" and not meta["source_event_id"]
                     and isinstance(declared_key, str) and declared_key.startswith(meta["provider_code"] + ":")
                     and declared_key.endswith(key.rsplit(":", 1)[-1]))
        if not valid:
            exclusions["unverified_evaluation_group"] += 1
            reasons[meta["source_game_id"]] = "unverified_evaluation_group"
            continue
        home, away = [aliases.root(meta[key]) for key in ("home_team_master_id", "away_team_master_id")]
        if home == away:
            exclusions["conflicting_team_mapping"] += 1
            reasons[meta["source_game_id"]] = "conflicting_team_mapping"
            continue
        node = "fixture:" + meta["source_game_id"]
        pair = digest([meta["game_date"], sorted([home, away])])
        groups.join([node, "group:" + declared_key, "pair:" + pair])
        identity = source_fixture_identity(snapshot)
        if identity:
            physical = digest([meta["game_date"], identity])
            groups.join([node, "source:" + physical])
            duplicate_keys[physical].append(meta)
        candidates.append({**meta, "group_kind": declared_kind, "_group_node": node,
                           "_normalised_home": home, "_normalised_away": away})
    excluded = set()
    duplicate_members = {}
    for duplicates in duplicate_keys.values():
        aliases = aliases_by_day[duplicates[0]["game_date"]]
        ordered = sorted(duplicates, key=lambda meta: (
            timestamp(meta["heuristic_predicted_at"]), meta["source_game_id"],
        ))
        pairs = {tuple(sorted([aliases.root(meta["home_team_master_id"]),
                               aliases.root(meta["away_team_master_id"])])) for meta in duplicates}
        if len(pairs) > 1:
            excluded.update(meta["source_game_id"] for meta in ordered)
            reasons.update({meta["source_game_id"]: "ambiguous_duplicate_source" for meta in ordered})
            exclusions["ambiguous_duplicate_source"] += len(ordered)
            continue
        duplicate_members[ordered[0]["source_game_id"]] = [{
            "source_game_id": meta["source_game_id"],
            "home_first": aliases.root(meta["home_team_master_id"]) < aliases.root(meta["away_team_master_id"]),
        } for meta in ordered]
        excluded.update(meta["source_game_id"] for meta in ordered[1:])
        reasons.update({meta["source_game_id"]: "duplicate_physical_fixture" for meta in ordered[1:]})
    exclusions["duplicate_physical_fixture"] += len(excluded) - exclusions["ambiguous_duplicate_source"]
    return [{**meta, "event_group": groups.root(meta["_group_node"]),
             "duplicate_sources": duplicate_members.get(meta["source_game_id"], [])}
            for meta in candidates if meta["source_game_id"] not in excluded], exclusions, reasons


def _fixture(meta: dict, settled: dict | None) -> dict:
    return {**{key: meta[key] for key in (
        "source_game_id", "game_date", "home_team_master_id", "away_team_master_id", "event_group", "group_kind",
    )}, **meta["coverage"],
        **({"home_score": settled["actual_home_score"], "away_score": settled["actual_away_score"]} if settled else {})}


def _write_json(path: Path, value) -> None:
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, allow_nan=False)
        handle.write("\n")


def paired_cases(sources, all_members, members, ledger, results, closed, exclusions, coverage):
    by_source = {member["source_game_id"]: member for member in all_members}
    for meta in members:
        raw = sources.record(meta["binding"])
        settled = ledger.get(meta["id"]) if closed else None
        case = sources.case_inputs(meta["binding"])
        case.update(predictor_revision=PINNED_REVISION, fixture=_fixture(meta, None))
        reason = prediction_input_error(case, meta["game_date"], sources)
        label = "|".join(case["fixture"][key] for key in ("provider", "cohort", "history_band"))
        if reason:
            exclusions[reason] += 1
            coverage[(label, reason)] += 1
            continue
        reason = _result_error(raw, settled, results.get(meta["source_game_id"])) if closed else None
        if closed and not reason and len(meta["duplicate_sources"]) > 1:
            duplicate_scores = set()
            for duplicate in meta["duplicate_sources"]:
                other = by_source[duplicate["source_game_id"]]
                other_raw = sources.record(other["binding"])
                other_settled = ledger.get(other["id"])
                if _result_error(other_raw, other_settled, results.get(other["source_game_id"])) is None:
                    scores = (other_settled["actual_home_score"], other_settled["actual_away_score"])
                    duplicate_scores.add(scores if duplicate["home_first"] else scores[::-1])
            if len(duplicate_scores) > 1:
                reason = "conflicting_duplicate_result"
        if reason:
            exclusions[reason] += 1
            coverage[(label, reason)] += 1
            continue
        case["fixture"] = _fixture(meta, settled)
        coverage[(label, "verified_inputs")] += 1
        yield case


def _inventory(client, project_url, access_token, study, policy):
    inventory = registered_inventory(project_url, access_token)
    if study.manifest_sha256 not in {record["manifest_sha256"] for record in inventory["archives"]}:
        raise ValueError("Registered study is missing from the consistent source inventory")
    closed = timestamp(inventory["as_of"]) >= match_start(policy.evaluation_end) + timedelta(days=1)
    headers = []
    for record in inventory["archives"]:
        if timestamp(record["recorded_at"]) >= match_start(policy.evaluation_end):
            continue
        _, manifest, _ = _registered_manifest(client, record["manifest_sha256"])
        if manifest.get("configuration", {}).get("capture_kind") == FORECAST_ARCHIVE_KIND:
            headers.append(record)
    return inventory, closed, sorted(headers, key=lambda row: (
        timestamp(row["recorded_at"]), row["manifest_sha256"],
    ))


def _members_and_results(client, sources, policy, closed):
    all_members = [meta for meta in sources.preferred_members()
                   if policy.development_start <= meta["game_date"] <= policy.evaluation_end]
    members, exclusions, group_reasons = grouped_members(all_members)
    ledger, results = {}, {}
    if closed:
        ledger = _selected_rows(client, FORECAST_TABLE, SETTLEMENT_FIELDS, [meta["id"] for meta in all_members], "id")
        results = _selected_rows(client, "games", RESULT_FIELDS, [meta["source_game_id"] for meta in all_members], "id")
    coverage = Counter()
    by_source = {member["source_game_id"]: member for member in all_members}
    for source, reason in group_reasons.items():
        info = by_source[source]["coverage"]
        coverage[("|".join(info[key] for key in ("provider", "cohort", "history_band")), reason)] += 1
    return all_members, members, ledger, results, exclusions, coverage


def assemble_dataset(
    client, project_url: str, access_token: str, study_directory: Path, output: Path | None = None,
    *, dry_run: bool = True,
) -> dict:
    if not dry_run and output is None:
        raise ValueError("Dataset assembly requires a new output directory")
    study = authenticate_archive(client, study_directory)
    policy = assert_registered_checkout(study)
    inventory, closed, headers = _inventory(client, project_url, access_token, study, policy)
    report = {"study_manifest_sha256": study.manifest_sha256, "server_observed_at": inventory["as_of"],
              "forecast_archives": len(headers), "evaluation_closed": closed, "dataset_written": False,
              "production_promotion": False}
    if dry_run:
        return report
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    (output / "archives").mkdir()
    (output / "cases").mkdir()
    download_archive(client, study.manifest_sha256, output / "study", dry_run=False)
    archives = []
    for position, record in enumerate(headers):
        # Keep hash identities in the manifest; repeating them in paths exceeds Windows path limits.
        directory = output / "archives" / f"{position:05d}"
        archives.append(download_archive(client, record["manifest_sha256"], directory,
                                         dry_run=False, return_verified=True))
    sources = FrozenSourceIndex(archives, ROOT)
    all_members, members, ledger, results, exclusions, coverage = _members_and_results(client, sources, policy, closed)
    parts, batch = [], []

    def save_batch():
        if not batch:
            return
        relative = f"cases/part-{len(parts):05d}.jsonl"
        with (output / relative).open("x", encoding="utf-8") as handle:
            for case in batch:
                handle.write(json.dumps(case, separators=(",", ":"), allow_nan=False) + "\n")
        parts.append({"file": relative, "sha256": hashlib.sha256((output / relative).read_bytes()).hexdigest(),
                      "cases": len(batch)})
        batch.clear()

    for case in paired_cases(sources, all_members, members, ledger, results, closed, exclusions, coverage):
        case["dataset_member"] = {"file": f"cases/part-{len(parts):05d}.jsonl", "line": len(batch)}
        batch.append(case)
        if len(batch) == CASE_BATCH_SIZE:
            save_batch()
    save_batch()
    _write_json(output / "inventory.json", inventory)
    _write_json(output / "outcomes.json", {"ledger": ledger, "games": results})
    manifest = {"schema_version": 1, "kind": "registered_compare_form_dataset", **report,
                "dataset_written": True, "research_revision": study.manifest["source_revision"],
                "archives": [archive.manifest_sha256 for archive in archives], "parts": parts,
                "inventory_sha256": hashlib.sha256((output / "inventory.json").read_bytes()).hexdigest(),
                "outcomes_sha256": hashlib.sha256((output / "outcomes.json").read_bytes()).hexdigest(),
                "qualification_requires_live_reauthentication": True,
                "coverage_unit": "unique_source_fixtures_after_frozen_record_deduplication",
                "source_exclusions": dict(sources.exclusions), "exclusions": dict(exclusions),
                "source_coverage_unit": "archived_forecast_rows_before_source_deduplication",
                "source_coverage": [{"provider": provider, "cohort": cohort, "history_band": band,
                                     "status": status, "rows": count}
                                    for (provider, cohort, band, status), count in sorted(sources.coverage.items())],
                "coverage": [{"slice": label, "status": status, "cases": count}
                             for (label, status), count in sorted(coverage.items())]}
    _write_json(output / "dataset.json", manifest)
    return {**report, "dataset_written": True, "cases": sum(part["cases"] for part in parts),
            "exclusions": dict(exclusions), "evaluation": "not_performed"}


def dataset_cases(directory: Path, manifest: dict):
    root = directory.resolve()
    seen = set()
    for part in manifest["parts"]:
        relative = part["file"]
        if relative in seen or not re.fullmatch(r"cases/part-[0-9]{5,}\.jsonl", relative):
            raise ValueError("Invalid or duplicate dataset case part")
        seen.add(relative)
        path = (root / relative).resolve()
        if path.parent != root / "cases" or hashlib.sha256(path.read_bytes()).hexdigest() != part["sha256"]:
            raise ValueError("Dataset case part failed integrity verification")
        count = 0
        with path.open(encoding="utf-8") as handle:
            for position, line in enumerate(handle):
                case = json.loads(line)
                if case.get("dataset_member") != {"file": relative, "line": position}:
                    raise ValueError("Dataset case member coordinates changed")
                count += 1
                yield case
        if count != part["cases"]:
            raise ValueError("Dataset case count differs from its manifest")


def verified_dataset(client, project_url: str, access_token: str, directory: Path):
    """Rebuild the complete eligible cohort from live authority before inspecting accuracy."""
    manifest = json.loads((directory / "dataset.json").read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1 or manifest.get("kind") != "registered_compare_form_dataset":
        raise ValueError("Unknown form dataset schema")
    study = authenticate_archive(client, directory / "study")
    policy = assert_registered_checkout(study)
    if (manifest.get("study_manifest_sha256") != study.manifest_sha256
            or manifest.get("research_revision") != study.manifest["source_revision"]):
        raise ValueError("Dataset does not match its registered study")
    inventory, closed, headers = _inventory(client, project_url, access_token, study, policy)
    if not closed:
        return {"status": "evaluation_sealed", "server_observed_at": inventory["as_of"],
                "production_promotion": False}, None
    if manifest.get("evaluation_closed") is not True:
        raise ValueError("Assemble a fresh dataset after the evaluation window closes")
    for name in ("inventory", "outcomes"):
        raw = (directory / (name + ".json")).read_bytes()
        if hashlib.sha256(raw).hexdigest() != manifest.get(name + "_sha256"):
            raise ValueError("Dataset source snapshot failed integrity verification")
    expected_archives = [record["manifest_sha256"] for record in headers]
    if manifest.get("archives") != expected_archives:
        raise ValueError("Dataset must include the complete registered forecast source inventory")
    archives = [authenticate_archive(client, directory / "archives" / f"{position:05d}")
                for position in range(len(expected_archives))]
    if [archive.manifest_sha256 for archive in archives] != expected_archives:
        raise ValueError("Dataset archive folders do not match the complete registered inventory")
    sources = FrozenSourceIndex(archives, ROOT)
    all_members, members, ledger, results, exclusions, coverage = _members_and_results(client, sources, policy, True)
    outcomes = json.loads((directory / "outcomes.json").read_text(encoding="utf-8"))
    if digest(outcomes) != digest({"ledger": ledger, "games": results}):
        raise ValueError("Settlements changed; assemble a fresh dataset before the evaluation")

    def verified_cases():
        expected = paired_cases(sources, all_members, members, ledger, results, True, exclusions, coverage)
        for case, actual in zip_longest(expected, dataset_cases(directory, manifest)):
            if case is None or actual is None or digest(case) != digest({
                key: value for key, value in actual.items() if key != "dataset_member"
            }):
                raise ValueError(
                    "Dataset must contain every verified case exactly once, without edited labels or inputs"
                )
            yield actual

    eligible, audit = audit_cases(verified_cases(), policy, sources, retain_inputs=False)
    return {"status": audit["status"], "audit": audit, "server_observed_at": inventory["as_of"],
            "study_manifest_sha256": study.manifest_sha256, "production_promotion": False}, (
        manifest, policy, sources, eligible,
    )
