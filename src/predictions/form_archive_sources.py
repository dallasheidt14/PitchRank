"""Resolve frozen input witnesses against archives authenticated during this run."""

from __future__ import annotations

import json
import subprocess
from collections import Counter
from copy import deepcopy
from datetime import timedelta
from pathlib import Path

from src.predictions.archive_inputs import RegisteredArchive
from src.predictions.form_policy import CALIBRATION_SNAPSHOT_FILES, PINNED_MODEL_SIGNATURE
from src.predictions.form_research import digest, finite, match_start, replay_reference_time, timestamp


def frozen_coverage(row: dict) -> dict:
    payload = row.get("heuristic_prediction")
    context = payload.get("shadowContext", {}) if isinstance(payload, dict) else {}
    context = context if isinstance(context, dict) else {}
    teams = [context.get(key, {}) for key in ("teamAInput", "teamBInput")]
    teams = [team if isinstance(team, dict) else {} for team in teams]
    age = teams[0].get("age")
    age_label = str(int(age)) if finite(age) and age > 0 and int(age) == age else "unknown"
    gender = {"m": "Male", "male": "Male", "f": "Female", "female": "Female"}.get(
        str(teams[0].get("gender") or "").lower(), "unknown",
    )
    evidence = context.get("frozenEvidence")
    games = evidence.get("games") if isinstance(evidence, dict) else None
    band = "unknown"
    if isinstance(games, list) and all(isinstance(game, dict) for game in games) and all(
        isinstance(team.get("team_id_master"), str) for team in teams
    ):
        counts = [sum(team["team_id_master"] in (game.get("home_team_master_id"), game.get("away_team_master_id"))
                      for game in games) for team in teams]
        count = min(counts)
        band = "0" if count == 0 else "1-3" if count < 4 else "4-7" if count < 8 else "8+"
    return {"provider": str(row.get("provider_code") or "unknown"),
            "cohort": "u" + age_label + "|" + gender, "history_band": band}


def _source_checks(rows: list[dict], root: Path) -> list[dict]:
    command = ["node", "--import", (root / "frontend/node_modules/tsx/dist/loader.mjs").as_uri(),
               str(root / "frontend/scripts/verify-compare-source.ts"), "-", "-"]
    run = subprocess.run(command, input=json.dumps(rows, allow_nan=False), capture_output=True, text=True,
                         cwd=root, check=True, timeout=180)
    result = json.loads(run.stdout)
    if result.get("schema_version") != 1 or not isinstance(result.get("receipts"), list):
        raise ValueError("Unexpected source verifier response")
    receipts = result["receipts"]
    if len(receipts) != len(rows) or any(receipt.get("id") != row.get("id") for receipt, row in zip(receipts, rows)):
        raise ValueError("Source receipts do not cover the exact ordered archive rows")
    return receipts


def _binding_key(binding: dict) -> tuple:
    if set(binding) != {"manifest_sha256", "response_sha256", "row_number", "ledger_id"}:
        raise ValueError("Incomplete archive member binding")
    if type(binding["row_number"]) is not int or binding["row_number"] < 0:
        raise ValueError("Invalid archive member position")
    return tuple(binding[key] for key in ("manifest_sha256", "response_sha256", "row_number", "ledger_id"))


class FrozenSourceIndex:
    def __init__(self, archives: list[RegisteredArchive], root: Path):
        self._archives = {archive.manifest_sha256: archive for archive in archives}
        if len(self._archives) != len(archives):
            raise ValueError("Duplicate source archives")
        self._response_key, self._response_rows = None, None
        self._members, self._by_source = {}, {}
        self.exclusions, self.coverage = Counter(), Counter()
        for archive in archives:
            members = archive.frozen_rows()
            rows = [member["record"] for member in members]
            receipts = _source_checks(rows, root)
            for member, receipt in zip(members, receipts):
                row = member["record"]
                coverage = frozen_coverage(row)
                label = tuple(coverage[key] for key in ("provider", "cohort", "history_band"))
                self.coverage[(*label, "seen")] += 1
                if receipt.get("verified") is not True or receipt.get("model_signature") != PINNED_MODEL_SIGNATURE:
                    reason = str(receipt.get("reason") or "unverified_source_record")
                    self.exclusions[reason] += 1
                    self.coverage[(*label, reason)] += 1
                    continue
                self.coverage[(*label, "verified_source")] += 1
                row, binding = member["record"], member["binding"]
                key = _binding_key(binding)
                if key in self._members:
                    raise ValueError("Duplicate archive member coordinates")
                meta = {name: row[name] for name in (
                    "id", "source_game_id", "game_date", "heuristic_predicted_at",
                )}
                context = row["heuristic_prediction"]["shadowContext"]
                meta.update(home_team_master_id=context["teamAInput"]["team_id_master"],
                            away_team_master_id=context["teamBInput"]["team_id_master"],
                            provider_code=row.get("provider_code"), source_event_id=row.get("source_event_id"),
                            evaluation_group_kind=row.get("evaluation_group_kind"),
                            evaluation_group_key=row.get("evaluation_group_key"),
                            fixture_payload=deepcopy(row.get("fixture_payload") or {}),
                            team_a_ids=sorted({context["teamAInput"]["team_id_master"],
                                               *context.get("resolvedTeamAIds", [])}),
                            team_b_ids=sorted({context["teamBInput"]["team_id_master"],
                                               *context.get("resolvedTeamBIds", [])}),
                            ages=[context["teamAInput"].get("age"), context["teamBInput"].get("age")],
                            gender=context["teamAInput"].get("gender"), coverage=coverage)
                meta.update(binding=deepcopy(binding), recorded_at=archive.recorded_at, row_sha256=digest(row),
                            expected_home_margin=row["heuristic_prediction"]["response"]["prediction"]["expectedMargin"],
                            reference_time=receipt["reference_time"], model_signature=receipt["model_signature"])
                self._members[key] = meta
                self._by_source.setdefault(row["source_game_id"], []).append(key)
        self.exclusions["conflicting_completed_forecast"] += sum(
            self._conflicting_source(source, min(self._members[key]["game_date"] for key in keys))
            for source, keys in self._by_source.items()
        )

    def _conflicting_source(self, source: str, day: str) -> bool:
        return len({self._members[key]["row_sha256"] for key in self._by_source.get(source, [])
                    if self._availability_error(self._members[key], day) is None}) > 1

    def metadata(self, binding: dict) -> dict:
        meta = self._members.get(_binding_key(binding))
        if meta is None or self._conflicting_source(meta["source_game_id"], meta["game_date"]):
            raise ValueError("Unverified or conflicting archive member")
        return deepcopy(meta)

    def preferred_members(self) -> list[dict]:
        selected = []
        for keys in self._by_source.values():
            eligible = [self._members[key] for key in keys
                        if self._availability_error(self._members[key], self._members[key]["game_date"]) is None
                        and not self._conflicting_source(self._members[key]["source_game_id"],
                                                        self._members[key]["game_date"])]
            if eligible:
                selected.append(min(eligible, key=lambda meta: (timestamp(meta["recorded_at"]),
                                                                _binding_key(meta["binding"]))))
        return deepcopy(sorted(selected, key=lambda meta: (
            timestamp(meta["recorded_at"]), meta["binding"]["manifest_sha256"],
            meta["binding"]["response_sha256"], meta["binding"]["row_number"],
        )))

    def record(self, binding: dict) -> dict:
        meta = self.metadata(binding)
        archive = self._archives[binding["manifest_sha256"]]
        queries = [query for query in archive.manifest["queries"]
                   if query["response"]["sha256"] == binding["response_sha256"]]
        if not queries:
            raise ValueError("Archive response is not bound to a frozen query")
        response_key = (archive.manifest_sha256, binding["response_sha256"])
        # Keep one verified page, rather than reparsing an entire page for each fixture.
        if self._response_key != response_key:
            self._response_rows = archive.object_json(queries[0]["response"])
            self._response_key = response_key
        try:
            row = self._response_rows[binding["row_number"]]
        except (IndexError, TypeError) as error:
            raise ValueError("Archive member no longer exists") from error
        if row.get("id") != binding["ledger_id"] or digest(row) != meta["row_sha256"]:
            raise ValueError("Archive member content changed")
        return deepcopy(row)

    @staticmethod
    def _availability_error(meta: dict, day: str) -> str | None:
        try:
            frozen, registered, cutoff = (timestamp(meta["heuristic_predicted_at"]),
                                          timestamp(meta["recorded_at"]), match_start(day))
            if frozen > registered:
                return "forecast_after_archive_registration"
            if frozen >= cutoff or registered >= cutoff:
                return "archive_not_before_match_day"
        except (KeyError, TypeError, ValueError):
            return "invalid_archive_availability"
        return None

    def expectation_for_game(self, game: dict) -> dict | None:
        source = game.get("source_game_id") or game["id"]
        if self._conflicting_source(source, game["game_date"]):
            return None
        candidates = []
        for key in self._by_source.get(source, []):
            meta = self._members[key]
            if self._availability_error(meta, game["game_date"]):
                continue
            if any(meta[name] != game[name] for name in ("game_date", "home_team_master_id", "away_team_master_id")):
                continue
            candidates.append(meta)
        if not candidates:
            return None
        meta = min(candidates, key=lambda item: (timestamp(item["recorded_at"]), _binding_key(item["binding"])))
        return {"source": "frozen", **{name: meta[name] for name in (
            "source_game_id", "game_date", "home_team_master_id", "away_team_master_id",
            "expected_home_margin", "model_signature",
        )}, "source_witness": deepcopy(meta["binding"])}

    def valid_expectation(self, expected: dict, game: dict) -> bool:
        actual = self.expectation_for_game(game)
        return actual is not None and digest(expected) == digest(actual)

    def prediction_input_error(self, case: dict, day: str) -> str | None:
        try:
            if "input_provenance" in case:
                return "mixed_archive_and_legacy_provenance"
            binding = case["source_witness"]
            meta, row = self.metadata(binding), self.record(binding)
            error = self._availability_error(meta, day)
            if error:
                return error
            fixture = case["fixture"]
            if any(fixture.get(key) != meta[key] for key in (
                "source_game_id", "game_date", "home_team_master_id", "away_team_master_id",
            )):
                return "archive_fixture_identity_mismatch"
            if timestamp(case["reference_time"]) != timestamp(meta["reference_time"]):
                return "archive_reference_time_mismatch"
            frozen = timestamp(meta["heuristic_predicted_at"])
            if not frozen < timestamp(meta["reference_time"]) + timedelta(milliseconds=1):
                return "archive_reference_tick_mismatch"
            payload, context = row["heuristic_prediction"], row["heuristic_prediction"]["shadowContext"]
            inputs = {"teamA": context["teamAInput"], "teamB": context["teamBInput"],
                      "games": context["frozenEvidence"]["games"],
                      "calibrations": {file: context["calibration"][key]
                                       for key, file in CALIBRATION_SNAPSHOT_FILES.items()}}
            if any(digest(case.get(key)) != digest(value) for key, value in inputs.items()):
                return "archive_input_content_mismatch"
            if digest(case.get("frozenPrediction")) != digest(payload["response"]["prediction"]):
                return "archive_prediction_content_mismatch"
            evidence = context["frozenEvidence"]
            if (match_start(evidence["as_of"]).date() > frozen.date()
                    or any(game["game_date"] > evidence["as_of"] or game["game_date"] >= day
                           for game in case["games"])):
                return "future_frozen_history"
            for team in (case["teamA"], case["teamB"]):
                if team.get("ratings_as_of") and timestamp(team["ratings_as_of"]) > frozen:
                    return "future_frozen_rating"
            expectations = {game.get("source_game_id") or game["id"]: expected
                            for game in case["games"] if (expected := self.expectation_for_game(game)) is not None}
            if digest(case.get("expectations", {})) != digest(expectations):
                return "archive_expectation_set_mismatch"
        except (ValueError, TypeError, KeyError):
            return "unverified_archive_witness"
        return None

    def case_inputs(self, binding: dict) -> dict:
        meta, row = self.metadata(binding), self.record(binding)
        context = row["heuristic_prediction"]["shadowContext"]
        result = {
            "source_witness": deepcopy(binding), "reference_time": replay_reference_time(meta),
            "teamA": context["teamAInput"], "teamB": context["teamBInput"], "games": context["frozenEvidence"]["games"],
            "calibrations": {file: context["calibration"][key] for key, file in CALIBRATION_SNAPSHOT_FILES.items()},
            "frozenPrediction": row["heuristic_prediction"]["response"]["prediction"],
            "expectations": {},
        }
        for game in result["games"]:
            expected = self.expectation_for_game(game)
            if expected is not None:
                result["expectations"][game.get("source_game_id") or game["id"]] = expected
        return result
