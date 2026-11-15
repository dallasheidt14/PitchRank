"""Export relies on open past dates forming a prefix, including active study seals."""
import pytest

from tests.integration.test_prospective_ledger import database  # noqa: F401


@pytest.mark.parametrize("kind", ["form", "sos", "calibration"])
def test_open_history_dates_form_a_prefix_with_an_active_confirmation(database, kind):
    connection, _ = database
    connection.autocommit = False
    try:
        with connection.cursor() as cursor:
            if kind == "form":
                cursor.execute("""INSERT INTO compare_challenger_manifests VALUES (
                    %s,'{}',clock_timestamp(),
                    (now() AT TIME ZONE 'UTC')::date-7,
                    (now() AT TIME ZONE 'UTC')::date+20)""", ("f" * 64,))
            elif kind == "sos":
                cursor.execute("""INSERT INTO compare_monitoring_models VALUES (
                    %s,'{}',clock_timestamp(),CURRENT_DATE-35,CURRENT_DATE-8)""", ("f" * 64,))
                cursor.execute("""INSERT INTO compare_sos_selections VALUES (
                    %s,0.5,'{}',clock_timestamp(),
                    (now() AT TIME ZONE 'UTC')::date-7,
                    (now() AT TIME ZONE 'UTC')::date+20)""", ("f" * 64,))
            else:
                cursor.execute("""INSERT INTO compare_calibration_experiments VALUES (
                    %s,'test','test',clock_timestamp(),
                    (now() AT TIME ZONE 'UTC')::date-14,
                    (now() AT TIME ZONE 'UTC')::date-8,
                    (now() AT TIME ZONE 'UTC')::date-7,
                    (now() AT TIME ZONE 'UTC')::date+20,'{}')""", ("f" * 64,))
            cursor.execute("""SELECT day::date, compare_monitor_results_open(day::date)
                FROM generate_series((now() AT TIME ZONE 'UTC')::date-400,
                  (now() AT TIME ZONE 'UTC')::date-1,interval '1 day') day ORDER BY day""")
            flags = [opened for _, opened in cursor.fetchall()]
            assert len(flags) == 400 and any(flags)
            assert flags == sorted(flags, reverse=True)
            assert flags[-7:] == [False] * 7
    finally:
        connection.rollback()
        connection.autocommit = True
