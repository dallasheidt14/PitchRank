"""Production fallback profiles are explicit; no historical forecast is rewritten."""
from copy import deepcopy
import json

import pytest
from tests.integration.test_compare_monitoring import monitor, capture  # noqa: F401
from tests.integration.test_prospective_ledger import database, forecast  # noqa: F401

psycopg2 = pytest.importorskip('psycopg2')


def runtime_monitor(monitor):
    connection, row, game, old_signature, original = monitor
    with connection.cursor() as cursor:
        cursor.execute('SELECT manifest FROM compare_monitoring_models WHERE signature=%s', (old_signature,))
        definition = cursor.fetchone()[0]
        calibration = {key: None for key in ('probability', 'margin', 'outcome', 'confidence')}
        calibration['ageGroups'] = {}
        profile = {
            'origin': 'https://www.pitchrank.io/api/match-prediction',
            'algorithm_hash': 'b' * 64, 'calibration_sha256': 'e' * 64, 'calibration': calibration,
            'input_source_hash': 'f' * 64,
        }
        definition['runtime_profile'] = profile
        cursor.execute('SELECT register_compare_monitor(%s)', (json.dumps(definition),))
        signature = cursor.fetchone()[0]
    payload = deepcopy(original)
    payload['runtime_profile'] = profile
    payload['runtime_observation'] = {'deployment_revision': 'f' * 40, 'observed_at': payload['reference_time']}
    payload['context']['calibration'] = calibration
    return connection, row, game, signature, payload


def test_verified_defaults_keep_the_earlier_capture(monitor):
    assert capture(monitor)
    connection = monitor[0]
    with connection.cursor() as cursor:
        cursor.execute('SELECT payload_sha256 FROM compare_monitoring_forecasts WHERE baseline_forecast_id=%s AND monitor_signature=%s', (monitor[1], monitor[3]))
        original_hash = cursor.fetchone()[0]
    current = runtime_monitor(monitor)
    assert capture(current)
    assert current[3] != monitor[3]
    with connection.cursor() as cursor:
        cursor.execute('SELECT payload_sha256 FROM compare_monitoring_forecasts WHERE baseline_forecast_id=%s AND monitor_signature=%s', (monitor[1], monitor[3]))
        assert cursor.fetchone()[0] == original_hash


def test_unverified_null_calibration_is_refused(monitor):
    payload = deepcopy(monitor[4])
    payload['context']['calibration']['margin'] = None
    with pytest.raises(psycopg2.Error, match='Complete frozen calibration'):
        capture(monitor, payload)


@pytest.mark.parametrize('change', ['missing', 'changed', 'stale', 'revision', 'profile'])
def test_runtime_provenance_enforced_at_capture(monitor, change):
    current = runtime_monitor(monitor)
    payload = deepcopy(current[4])
    if change == 'missing':
        del payload['context']['calibration']['outcome']
    elif change == 'changed':
        payload['context']['calibration']['outcome'] = {}
    elif change == 'stale':
        payload['runtime_observation']['observed_at'] = '2000-01-01T00:00:00Z'
    elif change == 'revision':
        payload['runtime_observation']['deployment_revision'] = 'wrong'
    else:
        payload.pop('runtime_profile')
    with pytest.raises(psycopg2.Error, match='Production runtime differs'):
        capture(current, payload)
