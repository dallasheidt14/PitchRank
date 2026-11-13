"""Local evidence archives for ranking runs, frozen forecasts, and research studies.

An archive records evidence; it does not certify eligibility. During ranking
capture, recording failures are deferred until calculation finishes so they
cannot change ratings.
"""

from __future__ import annotations

import asyncio
import gzip
import hashlib
import importlib.metadata
import io
import json
import pickle
import platform
import subprocess
from contextvars import ContextVar
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ACTIVE_ARCHIVE: ContextVar[InputArchive | None] = ContextVar("ranking_input_archive", default=None)
SOURCE_PATHS = [
    "src/",
    "config/",
    "scripts/calculate_rankings.py",
    "scripts/archive_compare_forecasts.py",
    "scripts/download_compare_archive.py",
    "scripts/benchmark_compare_form.py",
    "scripts/assemble_compare_form_dataset.py",
    "scripts/register_compare_form_study.py",
    "frontend/scripts/run-form-research.ts",
    "frontend/scripts/verify-compare-source.ts",
    "frontend/public/data/calibration/",
    "frontend/lib/",
    "frontend/package-lock.json",
    "requirements.lock",
    "requirements-ranking-model.lock",
]
# These are ranking data, never application users, credentials, or billing tables.
ARCHIVED_TABLES = {
    "games",
    "teams",
    "providers",
    "team_merge_map",
    "team_ranking_exclusions",
    "ranking_history",
    "prediction_feature_history",
    "rankings_full",
    "current_rankings",
}
ARCHIVED_RPCS = {"batch_update_ml_overperformance", "batch_upsert_game_explainability"}
FORECAST_ARCHIVE_KIND = "frozen_compare_forecasts"
FORECAST_TABLE = "prospective_match_predictions"
MUTATIONS = {"insert", "update", "upsert", "delete"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def encoded(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def retry_scope():
    try:
        return asyncio.current_task()
    except RuntimeError:
        return None


def source_file_names(source_root: Path) -> list[str]:
    files = subprocess.check_output(["git", "ls-files", "-z", "--", *SOURCE_PATHS], cwd=source_root)
    names = {name.decode("utf-8") for name in files.split(b"\0") if name}
    names.add(Path(__file__).resolve().relative_to(source_root.resolve()).as_posix())
    return sorted(names)


class InputArchive:
    def __init__(self, directory: Path, source_root: Path, configuration: dict):
        self.source_root = source_root.resolve()
        self.directory = directory.resolve()
        self.directory.mkdir(parents=True, exist_ok=False)
        (self.directory / "objects").mkdir()
        self.errors: list[str] = []
        # Concurrent tasks interleave requests, so only the failing task's own next request may retire its failures.
        self.retrying: dict[asyncio.Task | None, list[dict]] = {}
        self.manifest = {
            "schema_version": 1,
            "started_at": utc_now(),
            "status": "recording",
            "eligibility_certified": False,
            "configuration": configuration,
            "source_revision": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=source_root, text=True
            ).strip(),
            "source_files": {},
            "queries": [],
            "failed_queries": [],
            "recovered_queries": [],
            "model_fits": [],
            "model_outputs": [],
            "engine_configurations": [],
            "runtime": {"python": platform.python_version(), "pandas": pd.__version__},
        }
        for package in ("numpy", "scikit-learn", "xgboost", "pyarrow"):
            try:
                self.manifest["runtime"][package] = importlib.metadata.version(package)
            except importlib.metadata.PackageNotFoundError:
                self.manifest["runtime"][package] = None
        for name in source_file_names(source_root):
            self.manifest["source_files"][name] = self.blob((source_root / name).read_bytes(), "source")

    def blob(self, raw: bytes, kind: str) -> dict:
        sha = hashlib.sha256(raw).hexdigest()
        target = self.directory / "objects" / (sha + ".gz")
        compressed = gzip.compress(raw, mtime=0)
        if target.exists():
            if gzip.decompress(target.read_bytes()) != raw:
                raise ValueError("Archive object collision")
        else:
            with target.open("xb") as handle:
                handle.write(compressed)
        return {"sha256": sha, "bytes": len(raw), "kind": kind, "object": "objects/" + target.name}

    def safely(self, kind: str, action):
        try:
            return action()
        except Exception as error:
            self.errors.append(kind + ":" + type(error).__name__)

    def query(self, table: str, calls: list, response, started: str, operation: str):
        def record():
            entry = {
                "table": table,
                "operation": operation,
                "started_at": started,
                "observed_at": utc_now(),
                "request": self.blob(encoded(calls), "query_request"),
                "response": self.blob(encoded(response.data if response is not None else None), "query_response"),
            }
            self.manifest["queries"].append(entry)
            self.retire(self.retried_by(entry))

        self.safely("query", record)

    def query_failure(self, table: str, calls: list, error_type: str, started: str, operation: str):
        failure = {
            "table": table,
            "operation": operation,
            "started_at": started,
            "observed_at": utc_now(),
            "error_type": error_type,
        }
        self.manifest["failed_queries"].append(failure)

        def record():
            failure["request"] = self.blob(encoded(calls), "query_request")
            self.retrying[retry_scope()] = self.retried_by(failure) + [failure]

        self.safely("query_failure", record)

    def retried_by(self, entry: dict) -> list[dict]:
        """Pop the task's run of identical failures just before this request; return them if this is that request."""
        failures = self.retrying.pop(retry_scope(), [])
        key = (entry["table"], entry["operation"], entry["request"]["sha256"])
        last = failures[-1] if failures else None
        return failures if last and (last["table"], last["operation"], last["request"]["sha256"]) == key else []

    def recovered(self, table: str, operation: str):
        """Retire every pending failure of this table and operation, from any task, once all such requests landed."""
        self.safely(
            "query_recovery",
            lambda: self.retire(
                [f for f in self.manifest["failed_queries"] if (f["table"], f["operation"]) == (table, operation)]
            ),
        )

    def retire(self, failures: list[dict]):
        retiring = {id(failure) for failure in failures}
        pending = self.manifest["failed_queries"]
        self.manifest["recovered_queries"].extend(failure for failure in pending if id(failure) in retiring)
        self.manifest["failed_queries"] = [failure for failure in pending if id(failure) not in retiring]

    def frame(self, frame: pd.DataFrame) -> dict:
        # Parquet retains float precision, typed dates, identifiers, and row order.
        data = io.BytesIO()
        frame.to_parquet(data, index=True)
        return self.blob(data.getvalue(), "parquet")

    def engine_configuration(self, configuration: dict):
        self.safely(
            "engine_configuration",
            lambda: self.manifest["engine_configurations"].append(
                {
                    "available_at": utc_now(),
                    "configuration": self.blob(encoded(configuration), "engine_configuration"),
                }
            ),
        )

    def model_fit(self, model, training: pd.DataFrame, cfg, features: list[str], started: str, role: str):
        def save():
            entry = {
                "role": role,
                "started_at": started,
                "trained_at": utc_now(),
                "training_cutoff": pd.to_datetime(training["date"]).max().date().isoformat(),
                "training_rows": len(training),
                "training_inputs": self.frame(training),
                "features": list(features),
                "configuration": asdict(cfg),
                "model_type": type(model).__module__ + "." + type(model).__name__,
                # Internal trusted artifacts only; never unpickle an untrusted model.
                "model": self.blob(pickle.dumps(model, protocol=5), "trusted_pickle"),
            }
            entry["fit_id"] = hashlib.sha256(encoded(entry)).hexdigest()
            self.manifest["model_fits"].append(entry)
            return entry["fit_id"]

        return self.safely("model_fit", save)

    def joint_fit(self, snapshot, cfg):
        def save():
            import numpy as np
            from scipy.sparse import save_npz

            parameters, hessian = io.BytesIO(), io.BytesIO()
            np.save(parameters, snapshot.mode, allow_pickle=False)
            save_npz(hessian, snapshot.hessian)
            entry = {
                "role": "joint_field",
                "model_type": "JointFieldSnapshot",
                "started_at": snapshot.diagnostics["started_at"],
                "trained_at": snapshot.diagnostics["finished_at"],
                "training_cutoff": pd.to_datetime(snapshot.selected_evidence["date"]).max().date().isoformat(),
                "configuration": asdict(cfg),
                "training_inputs": self.frame(snapshot.selected_evidence),
                "physical_inputs": self.frame(snapshot.physical_evidence),
                "state": self.frame(snapshot.state),
                "model": self.blob(parameters.getvalue(), "numpy"),
                "hessian": self.blob(hessian.getvalue(), "scipy_npz"),
                "diagnostics": json.loads(json.dumps(snapshot.diagnostics, default=str, allow_nan=False)),
            }
            entry["fit_id"] = hashlib.sha256(encoded(entry)).hexdigest()
            self.manifest["model_fits"].append(entry)

        self.safely("joint_fit", save)

    def model_outputs(self, frame: pd.DataFrame, cfg, fit_ids: list, kind="predicted_games"):
        self.safely(
            "model_outputs",
            lambda: self.manifest["model_outputs"].append(
                {
                    "available_at": utc_now(),
                    "kind": kind,
                    "configuration": asdict(cfg),
                    "fit_ids": fit_ids,
                    "values": self.frame(frame),
                }
            ),
        )

    def finish(self, success: bool):
        self.errors.extend("query_execution:" + failure["error_type"] for failure in self.manifest["failed_queries"])
        for name, reference in self.manifest["source_files"].items():

            def check_source(name=name, reference=reference):
                if hashlib.sha256((self.source_root / name).read_bytes()).hexdigest() != reference["sha256"]:
                    raise ValueError("Source changed during ranking capture")

            self.safely("source_integrity", check_source)
        self.manifest.update(
            {
                "finished_at": utc_now(),
                "status": "complete" if success and not self.errors else "failed",
                "errors": self.errors,
            }
        )
        with (self.directory / "manifest.json").open("xb") as handle:
            handle.write(encoded(self.manifest))
        if success and self.errors:
            raise RuntimeError("Ranking completed, but its input archive failed: " + ", ".join(self.errors))

    def wrap(self, client):
        return _ArchivedClient(client, self)


class _ArchivedClient:
    def __init__(self, client, archive: InputArchive):
        self.client, self.archive = client, archive

    def table(self, name: str):
        builder = self.client.table(name)
        forecast = (name == FORECAST_TABLE and self.archive.manifest["configuration"].get("capture_kind")
                    == FORECAST_ARCHIVE_KIND)
        return _ArchivedQuery(builder, name, self.archive) if name in ARCHIVED_TABLES or forecast else builder

    def rpc(self, name: str, params=None):
        builder = self.client.rpc(name, params)
        if name not in ARCHIVED_RPCS:
            return builder
        return _ArchivedQuery(builder, "rpc:" + name, self.archive, [["rpc", [params], {}]], "rpc")

    def __getattr__(self, name):
        return getattr(self.client, name)


class _ArchivedQuery:
    def __init__(self, builder, table: str, archive: InputArchive, calls=None, operation="select"):
        self.builder, self.table, self.archive = builder, table, archive
        self.calls, self.operation = calls or [], operation

    def execute(self):
        started = utc_now()
        try:
            response = self.builder.execute()
        except Exception as error:
            self.archive.query_failure(self.table, list(self.calls), type(error).__name__, started, self.operation)
            raise
        self.archive.query(self.table, list(self.calls), response, started, self.operation)
        return response

    def __getattr__(self, name):
        attribute = getattr(self.builder, name)
        if not callable(attribute):
            if callable(getattr(attribute, "execute", None)):
                # PostgREST's .not_ is a fluent property, not a method.
                self.calls.append([name, [], {}])
                self.builder = attribute
                return self
            return attribute

        def call(*args, **kwargs):
            builder = attribute(*args, **kwargs)
            self.calls.append([name, list(args), kwargs])
            if name in MUTATIONS:
                self.operation = name
            self.builder = builder
            return self

        return call
