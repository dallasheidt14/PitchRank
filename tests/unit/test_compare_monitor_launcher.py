"""Keep mutable operational tools outside the registered prediction checkout."""
from pathlib import Path

import yaml


def test_monitor_launcher_runs_separately_from_the_pinned_collector():
    root = Path(__file__).resolve().parents[2]
    workflow = yaml.safe_load((root / '.github/workflows/compare-live-monitoring.yml').read_text())
    steps = workflow['jobs']['monitor']['steps']
    checkouts = [s for s in steps if s.get('uses', '').startswith('actions/checkout@')]
    assert checkouts[0]['with']['ref'] == '${{ vars.COMPARE_MONITOR_REVISION || github.sha }}'
    assert checkouts[1]['with'] == {
        'ref': '${{ github.sha }}', 'path': 'monitor-tools', 'persist-credentials': False,
    }
    capture = next(s for s in steps if s.get('name') == 'Capture current Compare and frozen SOS arms')
    assert capture['working-directory'] == 'frontend'
    assert '"$GITHUB_WORKSPACE/monitor-tools/frontend/scripts/run-compare-monitoring.mjs"' in capture['run']
    assert '--limit "$LIMIT" "${MODE_ARGS[@]}"' in capture['run']
    assert steps.index(checkouts[1]) < steps.index(capture)
    assert next(s for s in steps if s.get('name', '').startswith('Verify the monitored'))['working-directory'] == 'frontend'
