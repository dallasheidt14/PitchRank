"""Execute archive index and private-storage protections in disposable PostgreSQL."""

from datetime import datetime
from pathlib import Path

import pytest

psycopg2 = pytest.importorskip("psycopg2")
from psycopg2 import sql  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]

from src.predictions.archive_inputs import ARCHIVE_INVENTORY_QUERY  # noqa: E402


@pytest.fixture(scope="module")
def archive_database(postgres_database):
    with postgres_database("input_archive_test_") as (connection, parameters):
        with connection.cursor() as cursor:
            cursor.execute("""
                CREATE SCHEMA storage;
                CREATE TABLE storage.buckets (id text PRIMARY KEY, name text, public boolean);
                CREATE TABLE storage.objects (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), bucket_id text, name text);
                ALTER TABLE storage.buckets ENABLE ROW LEVEL SECURITY;
                ALTER TABLE storage.objects ENABLE ROW LEVEL SECURITY;
                GRANT USAGE ON SCHEMA storage TO anon, authenticated, service_role;
                GRANT ALL ON storage.buckets, storage.objects TO anon, authenticated, service_role;
                CREATE POLICY existing_permissive_buckets ON storage.buckets FOR ALL USING (true) WITH CHECK (true);
                CREATE POLICY existing_permissive_objects ON storage.objects FOR ALL USING (true) WITH CHECK (true);
                ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO anon, authenticated, service_role;
            """)
            migration = ROOT / "supabase/migrations/20261112000000_archive_prediction_inputs.sql"
            cursor.execute(migration.read_text(encoding="utf-8"))
            cursor.execute(migration.read_text(encoding="utf-8"))  # A hand-applied migration can be replayed safely.
            cursor.execute("INSERT INTO storage.buckets VALUES ('other','other',false)")
            cursor.execute(
                "INSERT INTO storage.objects (bucket_id,name) "
                "VALUES ('other','visible'),('prediction-input-archives','private')"
            )
        yield connection, parameters


@pytest.fixture(scope="module")
def database(archive_database):
    return archive_database[0]


def insert(cursor, sha):
    cursor.execute(
        """
        INSERT INTO prediction_input_archives (
          manifest_sha256,source_revision,manifest_path,capture_started_at,capture_finished_at,object_count,recorded_at
        ) VALUES (%s,%s,%s,clock_timestamp()-interval '2 seconds',clock_timestamp()-interval '1 second',1,'2000-01-01')
        RETURNING recorded_at > clock_timestamp()-interval '1 minute'
    """,
        (sha, "a" * 40, f"runs/{sha}/manifest.json"),
    )


def test_inventory_statement_returns_one_read_only_snapshot_above_the_rest_page_limit(archive_database):
    database, parameters = archive_database
    writer = psycopg2.connect(**parameters)
    hidden_sha, visible_sha = f"{9001:064x}", f"{9002:064x}"
    try:
        with writer.cursor() as cursor:
            insert(cursor, hidden_sha)
        with database.cursor() as cursor:
            insert(cursor, visible_sha)
            cursor.execute("""
                INSERT INTO prediction_input_archives (
                    manifest_sha256,source_revision,manifest_path,capture_started_at,capture_finished_at,object_count
                ) SELECT lpad(to_hex(n),64,'0'),repeat('a',40),'runs/'||lpad(to_hex(n),64,'0')||'/manifest.json',
                         clock_timestamp()-interval '2 seconds',clock_timestamp()-interval '1 second',1
                  FROM generate_series(10000,11000) n;
            """)

            def snapshot():
                cursor.execute("BEGIN READ ONLY")
                try:
                    cursor.execute(ARCHIVE_INVENTORY_QUERY)
                    read_only, observed_at, records = cursor.fetchone()
                    assert read_only == "on"
                    assert all(datetime.fromisoformat(row["recorded_at"]) <= observed_at for row in records)
                    identifiers = [row["manifest_sha256"] for row in records]
                    assert identifiers == sorted(identifiers)
                    return set(identifiers)
                finally:
                    cursor.execute("ROLLBACK")

            before = snapshot()
            assert {f"{i:064x}" for i in range(10000,11001)} <= before
            assert visible_sha in before and hidden_sha not in before
            writer.commit()
            after = snapshot()
            assert after == before | {hidden_sha}
    finally:
        writer.rollback()
        writer.close()


def test_server_sets_availability_and_preserves_first_registration(database):
    sha = "1" * 64
    with database.cursor() as cursor:
        cursor.execute("SET ROLE service_role")
        try:
            insert(cursor, sha)
            assert cursor.fetchone()[0] is True
            cursor.execute("SELECT recorded_at FROM prediction_input_archives WHERE manifest_sha256=%s", (sha,))
            before = cursor.fetchone()[0]
            cursor.execute(
                """
                INSERT INTO prediction_input_archives SELECT * FROM prediction_input_archives
                WHERE manifest_sha256=%s ON CONFLICT (manifest_sha256) DO NOTHING
            """,
                (sha,),
            )
            cursor.execute("SELECT recorded_at FROM prediction_input_archives WHERE manifest_sha256=%s", (sha,))
            assert cursor.fetchone()[0] == before
        finally:
            cursor.execute("RESET ROLE")


@pytest.mark.parametrize("role", ["anon", "authenticated"])
def test_browser_roles_cannot_read_index_or_private_objects_even_with_other_permissive_policies(database, role):
    with database.cursor() as cursor:
        cursor.execute(sql.SQL("SET ROLE {}").format(sql.Identifier(role)))
        try:
            with pytest.raises(psycopg2.errors.InsufficientPrivilege):
                cursor.execute("SELECT * FROM prediction_input_archives")
            cursor.execute("SELECT id FROM storage.buckets ORDER BY id")
            assert cursor.fetchall() == [("other",)]
            cursor.execute("SELECT name FROM storage.objects ORDER BY name")
            assert cursor.fetchall() == [("visible",)]
            with pytest.raises(psycopg2.errors.InsufficientPrivilege):
                cursor.execute(
                    "INSERT INTO storage.objects (bucket_id,name) VALUES ('prediction-input-archives','forged')"
                )
        finally:
            cursor.execute("RESET ROLE")


def test_even_owner_cannot_modify_or_delete_registered_archive(database):
    with database.cursor() as cursor:
        insert(cursor, "4" * 64)
        assert cursor.fetchone()[0] is True
        for statement in (
            "UPDATE prediction_input_archives SET source_revision=repeat('f',40)",
            "DELETE FROM prediction_input_archives",
        ):
            with pytest.raises(psycopg2.Error, match="immutable"):
                cursor.execute(statement)


def test_future_capture_date_and_forged_manifest_path_are_refused(database):
    with database.cursor() as cursor:
        for values in (
            "repeat('2',64),repeat('a',40),'runs/'||repeat('2',64)||'/manifest.json',now(),now()+interval '1 day',1",
            "repeat('3',64),repeat('a',40),'other/path',now(),now(),1",
        ):
            with pytest.raises(psycopg2.errors.CheckViolation):
                cursor.execute(
                    "INSERT INTO prediction_input_archives "
                    "(manifest_sha256,source_revision,manifest_path,"
                    "capture_started_at,capture_finished_at,object_count) "
                    "VALUES (" + values + ")"
                )


def test_disposable_database_is_removed_after_setup_failure(postgres_database):
    failed_name = None
    with pytest.raises(RuntimeError, match="seed failed"):
        with postgres_database("input_failure_test_") as (_, parameters):
            failed_name = parameters["dbname"]
            raise RuntimeError("seed failed")
    with postgres_database("input_check_test_") as (connection, _):
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM pg_database WHERE datname=%s", (failed_name,))
            assert cursor.fetchone() is None
