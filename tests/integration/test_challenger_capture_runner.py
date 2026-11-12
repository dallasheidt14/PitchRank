"""Authenticate a frozen archive, replay real TypeScript, and persist its generated payload through PostgreSQL."""

import json
import shutil
import subprocess
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.benchmark_compare_form import run_predictor
from src.predictions.archive_inputs import authenticate_archive
from src.predictions.challenger_capture import (
    candidate_definition, candidate_execution_paths, capture_candidate, source_identity,
)
from src.predictions.form_archive_sources import FrozenSourceIndex
from src.predictions.form_policy import CALIBRATION_SNAPSHOT_FILES, PINNED_MODEL_SIGNATURE, PINNED_REVISION
from src.rankings.archive_storage import publish_archive
from src.rankings.input_archive import InputArchive, utc_now
from tests.challenger_fixtures import qualification_report
from tests.integration.test_challenger_ledger import database, forecast, register  # noqa: F401
from tests.integration.test_form_study_registration import registration_repo  # noqa: F401
from tests.unit.test_ranking_archive_storage import FakeServer

psycopg2 = pytest.importorskip("psycopg2")
from psycopg2 import sql
from psycopg2.extras import Json

ROOT = Path(__file__).resolve().parents[2]
LOADER = ROOT / "frontend/node_modules/tsx/dist/loader.mjs"


class DatabaseClient:
    def __init__(self, connection): self.connection = connection
    def table(self, table): return DatabaseQuery(self.connection, table)
    def rpc(self, name, params):
        assert name == "freeze_compare_challenger"
        def execute():
            with self.connection.cursor() as cursor:
                cursor.execute("SELECT freeze_compare_challenger(%s,%s,%s)", (
                    params["p_baseline_forecast_id"], params["p_candidate_signature"], params["p_payload"],
                ))
                return SimpleNamespace(data=cursor.fetchone()[0])
        return SimpleNamespace(execute=execute)


class DatabaseQuery:
    def __init__(self, connection, table):
        self.connection, self.table = connection, table
        self.fields, self.filters, self.values, self.orders = ["*"], [], [], []
        self.start, self.end, self.one = 0, 999, False
    def select(self, fields): self.fields = fields.split(","); return self
    def condition(self, field, operator, value):
        self.filters.append(sql.SQL("{} " + operator + " %s").format(sql.Identifier(field)))
        self.values.append(value)
        return self
    def eq(self, field, value): return self.condition(field, "=", value)
    def gte(self, field, value): return self.condition(field, ">=", value)
    def lte(self, field, value): return self.condition(field, "<=", value)
    def order(self, field): self.orders.append(sql.Identifier(field)); return self
    def range(self, first, last): self.start, self.end = first, last; return self
    def single(self): self.one = True; return self
    def execute(self):
        projection = sql.SQL("*") if self.fields == ["*"] else sql.SQL(",").join(map(sql.Identifier, self.fields))
        statement = sql.SQL("SELECT to_jsonb(q) FROM (SELECT {} FROM {} WHERE {} ORDER BY {} OFFSET %s LIMIT %s) q").format(
            projection, sql.Identifier(self.table),
            sql.SQL(" AND ").join(self.filters) if self.filters else sql.SQL("true"),
            sql.SQL(",").join(self.orders) if self.orders else sql.SQL("1"),
        )
        with self.connection.cursor() as cursor:
            cursor.execute(statement, [*self.values, self.start, self.end - self.start + 1])
            rows = [row[0] for row in cursor.fetchall()]
        if self.one: assert len(rows) == 1
        return SimpleNamespace(data=rows[0] if self.one else rows)


@pytest.mark.skipif(not LOADER.exists() or not shutil.which("node"), reason="Requires npm ci and Node")
def test_real_authenticated_capture_payload_is_accepted(database, forecast, registration_repo, tmp_path):
    connection, _ = database
    baseline_id, game_id, _ = forecast
    added = []
    for name in candidate_execution_paths(ROOT):
        target = registration_repo / name
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((ROOT / name).read_bytes())
            added.append(name)
    if added:
        subprocess.run(["git", "add", "--", *added], cwd=registration_repo, check=True, capture_output=True, timeout=30)
        subprocess.run(["git", "-c", "user.name=Research Test", "-c", "user.email=research@example.test",
                        "commit", "--quiet", "-m", "Include execution dependencies"],
                       cwd=registration_repo, check=True, capture_output=True, timeout=30)
    revision, hashes = source_identity(registration_repo)
    definition = candidate_definition(qualification_report(), revision, hashes, reviewed=True, qualified_sources=hashes)
    signature = register(connection, definition)
    with connection.cursor() as cursor:
        cursor.execute("SELECT confirmation_start FROM compare_challenger_manifests WHERE candidate_signature=%s", (signature,))
        day = cursor.fetchone()[0].isoformat()
        cursor.execute("SELECT home_team_master_id,away_team_master_id,provider_id FROM games WHERE id=%s", (game_id,))
        home, away, provider = map(str, cursor.fetchone())
        snapshot = {"game_date": day, "home_team_master_id": home, "away_team_master_id": away,
                    "provider_id": provider, "source_url": None}
        cursor.execute("UPDATE games SET game_date=%s WHERE id=%s", (day, game_id))
        cursor.execute("UPDATE prospective_match_predictions SET game_date=%s,provider_code='gotsport',"
                       "source_system='database_games',fixture_payload=%s WHERE id=%s",
                       (day, Json({"cohort": "u13|Male", "source_snapshot": snapshot}), baseline_id))
        cursor.execute("SELECT to_jsonb(b) FROM prospective_match_predictions b WHERE id=%s", (baseline_id,))
        row = cursor.fetchone()[0]
    sample = json.loads((ROOT / "frontend/test/fixtures/compare-baseline.json").read_text())["cases"][0]
    mapping = {"a": home, "b": away}
    for team in ("teamA", "teamB"):
        sample[team]["team_id_master"] = mapping[sample[team]["team_id_master"]]
    for game in sample["games"]:
        for key in ("home_team_master_id", "away_team_master_id"):
            game[key] = mapping.get(game[key], game[key])
    calibrations = {key: json.loads((ROOT / "frontend/public/data/calibration" / name).read_text())
                    for key, name in CALIBRATION_SNAPSHOT_FILES.items()}
    moment = utc_now()
    case = {"reference_time": moment, "fixture": {"source_game_id": game_id},
            **{key: sample[key] for key in ("teamA", "teamB", "games")}}
    initial = tmp_path / "initial"
    initial.mkdir()
    result = run_predictor({"schema_version": 1, "predictor_revision": PINNED_REVISION,
                            "calibrations": {name: calibrations[key] for key, name in CALIBRATION_SNAPSHOT_FILES.items()},
                            "cases": [case]}, initial)
    version = "heuristic_v6_canonical_evidence_v1"
    payload = {"modelVersion": version, "codeRevision": PINNED_REVISION, "modelSignature": PINNED_MODEL_SIGNATURE,
               "response": {"prediction": result["outputs"]["baseline"][0]["prediction"]}, "shadowContext": {
                   "predictorVersion": version, "teamAInput": sample["teamA"], "teamBInput": sample["teamB"],
                   "calibration": calibrations, "preOutcomeCalibration": [.4, .3, .3],
                   "frozenEvidence": {"as_of": moment[:10], "games": sample["games"]}}}
    row["heuristic_prediction"] = payload
    source = tmp_path / "source.json"
    source.write_text(json.dumps(row), encoding="utf-8")
    hasher = tmp_path / "hash.mjs"
    hasher.write_text(
        "import {readFile,writeFile} from 'node:fs/promises';import {createHash} from 'node:crypto';"
        f"import {{stableJson}} from {json.dumps((ROOT/'frontend/lib/canonicalJson.ts').as_uri())};"
        "const row=JSON.parse(await readFile(process.argv[2],'utf8'));"
        "const fields='id,fixture_key,game_date,source_game_id,provider_code,home_team_master_id,"
        "away_team_master_id,fixture_payload'.split(',');"
        "row.heuristic_prediction.inputHash=createHash('sha256').update(stableJson({"
        "fixture:Object.fromEntries(fields.map(k=>[k,row[k]])),context:row.heuristic_prediction.shadowContext})).digest('hex');"
        "await writeFile(process.argv[2],JSON.stringify(row));", encoding="utf-8",
    )
    subprocess.run(["node", "--import", LOADER.as_uri(), str(hasher), str(source)], check=True, timeout=30)
    payload = json.loads(source.read_text())["heuristic_prediction"]
    with connection.cursor() as cursor:
        cursor.execute("SELECT freeze_prospective_forecast(%s,%s,%s)", (baseline_id, version, Json(payload)))
        assert cursor.fetchone()[0]
        cursor.execute("SELECT to_jsonb(b) FROM prospective_match_predictions b WHERE id=%s", (baseline_id,))
        row = cursor.fetchone()[0]
    archive = InputArchive(tmp_path / "archive", ROOT, {"capture_kind": "frozen_compare_forecasts"})
    archive.query("prospective_match_predictions", [["select", ["*"], {}]], SimpleNamespace(data=[row]), utc_now(), "select")
    archive.finish(True)
    storage = FakeServer(recorded_at=utc_now())
    publish_archive(storage, archive.directory, dry_run=False)
    authenticated = authenticate_archive(storage, archive.directory)
    sources = FrozenSourceIndex([authenticated], ROOT)
    assert len(sources.preferred_members()) == 1 and not any(sources.exclusions.values())
    before = deepcopy(row["heuristic_prediction"])
    report = capture_candidate(DatabaseClient(connection), signature, sources, run_predictor,
                               dry_run=False, root=registration_repo)
    assert report["captured"] == 1 and not report["errors"]
    with connection.cursor() as cursor:
        cursor.execute("SELECT prediction,provenance,frozen_inputs FROM compare_challenger_forecasts WHERE baseline_forecast_id=%s",
                       (baseline_id,))
        prediction, provenance, inputs = cursor.fetchone()
        assert 0 <= prediction["blowout4PlusProbability"] <= 1
        assert provenance["aa_parity"] is True
        assert inputs["baseline_prediction"] == before
        cursor.execute("SELECT heuristic_prediction FROM prospective_match_predictions WHERE id=%s", (baseline_id,))
        assert cursor.fetchone()[0] == before
