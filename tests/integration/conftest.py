"""Disposable local PostgreSQL databases, including cleanup after setup failure."""

import os
from contextlib import contextmanager
from uuid import uuid4

import pytest


@pytest.fixture(scope="module")
def postgres_database():
    psycopg2 = pytest.importorskip("psycopg2")
    from psycopg2 import sql

    url = os.getenv("PROSPECTIVE_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set PROSPECTIVE_TEST_DATABASE_URL to a disposable local PostgreSQL service")
    parameters = psycopg2.extensions.parse_dsn(url)
    if parameters.get("host") not in {"127.0.0.1", "localhost", "::1"}:
        pytest.fail("Migration execution tests only accept local PostgreSQL")

    @contextmanager
    def create(prefix):
        admin = psycopg2.connect(**parameters)
        admin.autocommit = True
        name, connection, created = prefix + uuid4().hex, None, False
        try:
            with admin.cursor() as cursor:
                for role in ("anon", "authenticated", "service_role"):
                    cursor.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (role,))
                    if not cursor.fetchone():
                        cursor.execute(sql.SQL("CREATE ROLE {}").format(sql.Identifier(role)))
                cursor.execute("ALTER ROLE service_role BYPASSRLS")
                cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
                created = True
            database_parameters = {**parameters, "dbname": name}
            connection = psycopg2.connect(**database_parameters)
            connection.autocommit = True
            yield connection, database_parameters
        finally:
            if connection is not None:
                connection.close()
            try:
                if created:
                    with admin.cursor() as cursor:
                        cursor.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))
            finally:
                admin.close()

    return create
