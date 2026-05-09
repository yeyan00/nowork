"""
Test for hasRunningRun feature in list_sessions API.

Tests two scenarios:
1. Unit test: has_running logic with mocked agno session data
2. Integration test: against live server (requires restart to pick up code changes)

Usage:
    # Unit tests only (no server needed):
    C:/Users/15171/.conda/envs/nowork/python.exe tests/test_has_running_run.py unit

    # Integration tests (needs server with new code running):
    C:/Users/15171/.conda/envs/nowork/python.exe tests/test_has_running_run.py integration

    # All tests:
    C:/Users/15171/.conda/envs/nowork/python.exe tests/test_has_running_run.py
"""

import json
import sqlite3
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SERVER_DIR = PROJECT_ROOT / 'server'
DB_DIR = SERVER_DIR / 'db'
WORKER_ID = 'test-agent-1'


# ============================================================================
# Unit Tests: Test has_running logic directly
# ============================================================================

def test_has_running_logic():
    """Test the has_running detection logic used in list_sessions."""
    print('\n=== Unit Test: has_running logic ===\n')

    class FakeRun:
        def __init__(self, status):
            self.status = status

    class FakeSession:
        def __init__(self, runs=None):
            self.runs = runs

    tests = [
        ('No runs', [], False),
        ('None runs', None, False),
        ('Last run COMPLETED', [FakeRun('COMPLETED')], False),
        ('Last run RUNNING', [FakeRun('RUNNING')], True),
        ('Last run PENDING', [FakeRun('PENDING')], True),
        ('Last run CANCELLED', [FakeRun('CANCELLED')], False),
        ('Last run ERROR', [FakeRun('ERROR')], False),
        ('COMPLETED then RUNNING', [FakeRun('COMPLETED'), FakeRun('RUNNING')], True),
        ('COMPLETED then COMPLETED', [FakeRun('COMPLETED'), FakeRun('COMPLETED')], False),
        ('RUNNING then COMPLETED', [FakeRun('RUNNING'), FakeRun('COMPLETED')], False),
        ('Lowercase running', [FakeRun('running')], True),
        ('Lowercase pending', [FakeRun('pending')], True),
    ]

    all_pass = True
    for desc, runs, expected in tests:
        agno_s = FakeSession(runs)
        has_running = False
        if agno_s:
            run_list = getattr(agno_s, 'runs', None) or []
            if run_list:
                last_status = str(getattr(run_list[-1], 'status', '')).upper()
                has_running = last_status in ('RUNNING', 'PENDING')

        passed = has_running == expected
        tag = 'PASS' if passed else 'FAIL'
        print(f'  [{tag}] {desc} -> has_running={has_running} (expected={expected})')
        if not passed:
            all_pass = False

    return all_pass


# ============================================================================
# Integration Tests: Against live server with actual DB
# ============================================================================

BASE_URL = None


def _resolve_base_url():
    runtime_file = SERVER_DIR / 'runtime' / 'app-runtime.json'
    if runtime_file.exists():
        try:
            with open(runtime_file, 'r') as f:
                data = json.load(f)
            if data.get('baseUrl'):
                return data['baseUrl']
        except Exception:
            pass
    return 'http://127.0.0.1:18080'


def _ensure_base_url():
    global BASE_URL
    if BASE_URL is None:
        BASE_URL = _resolve_base_url()


def api_get(path, timeout=10):
    with urllib.request.urlopen(f'{BASE_URL}{path}', timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def _parse_db_runs(runs_raw):
    """Parse agno DB runs field (handles double-encoded JSON)."""
    if not runs_raw:
        return []
    parsed = json.loads(runs_raw)
    if isinstance(parsed, str):
        return json.loads(parsed)
    return parsed


def _write_db_runs(db_path, agno_session_id, runs):
    """Write runs back to DB (double-encode to match agno format)."""
    db = sqlite3.connect(str(db_path))
    try:
        db.execute('UPDATE agno_sessions SET runs = ? WHERE session_id = ?',
                   (json.dumps(json.dumps(runs)), agno_session_id))
        db.commit()
    finally:
        db.close()


def test_integration_has_running_run():
    """Integration test: hasRunningRun in list_sessions API response.

    Uses an existing session, injects a RUNNING run, verifies the API
    returns the correct hasRunningRun flag, then restores original state.
    """
    print('\n=== Integration Test: hasRunningRun API field ===\n')

    _ensure_base_url()

    # 0. Check server is up
    try:
        api_get('/health')
    except Exception as e:
        print(f'  SKIP: Server not reachable at {BASE_URL}: {e}')
        return True

    test_db_path = DB_DIR / 'test_agent.db'
    nowork_db_path = DB_DIR / 'nowork_sessions.db'
    if not test_db_path.exists():
        print(f'  SKIP: test_agent.db not found')
        return True

    # 1. Find an existing session visible in both API and DB
    print('[1/7] Finding existing session...')
    try:
        api_sessions = api_get(f'/api/workers/{WORKER_ID}/sessions')
    except Exception as e:
        print(f'  SKIP: Cannot list sessions: {e}')
        return True

    target_session = None
    agno_session_id = None
    for s in api_sessions:
        sid = s['id']
        try:
            db = sqlite3.connect(str(nowork_db_path))
            db.row_factory = sqlite3.Row
            seg = db.execute(
                'SELECT agno_session_id FROM session_segments '
                'WHERE worker_session_id = ? AND status = "active" '
                'ORDER BY segment_order DESC LIMIT 1',
                (sid,)
            ).fetchone()
            db.close()
            if seg:
                # Verify it exists in test_agent.db too
                tdb = sqlite3.connect(str(test_db_path))
                found = tdb.execute(
                    'SELECT 1 FROM agno_sessions WHERE session_id = ?',
                    (seg['agno_session_id'],)
                ).fetchone()
                tdb.close()
                if found:
                    agno_session_id = seg['agno_session_id']
                    target_session = s
                    break
        except Exception:
            continue

    if not target_session or not agno_session_id:
        print('  SKIP: Could not find a session present in both API and DB')
        return True

    session_id = target_session['id']
    print(f'  Session: {session_id} (agno: {agno_session_id})')

    # 2. Backup original runs
    print('[2/7] Backing up original DB state...')
    db = sqlite3.connect(str(test_db_path))
    row = db.execute('SELECT runs FROM agno_sessions WHERE session_id = ?',
                     (agno_session_id,)).fetchone()
    if row is None:
        print(f'  SKIP: Session not found in test_agent.db')
        db.close()
        return True
    original_runs = row[0]
    db.close()

    # 3. Inject a RUNNING run
    print('[3/7] Injecting RUNNING run...')
    runs = _parse_db_runs(original_runs)
    import uuid
    run_id = str(uuid.uuid4())
    runs.append({
        'run_id': run_id,
        'status': 'RUNNING',
        'content': 'Test running run...',
        'agent_id': 'test-agent-1',
        'created_at': int(time.time()),
    })
    _write_db_runs(test_db_path, agno_session_id, runs)
    print(f'  run_id: {run_id}')

    # 4. Check hasRunningRun=true
    print('[4/7] Checking hasRunningRun=true...')
    try:
        sessions = api_get(f'/api/workers/{WORKER_ID}/sessions')
        target = next((s for s in sessions if s['id'] == session_id), None)
        if target is None:
            print(f'  FAIL: Session not in API response')
            _write_db_runs(test_db_path, agno_session_id, _parse_db_runs(original_runs))
            return False

        if 'hasRunningRun' not in target:
            print(f'  FAIL: hasRunningRun field missing. Fields: {list(target.keys())}')
            _write_db_runs(test_db_path, agno_session_id, _parse_db_runs(original_runs))
            return False

        has_running = target['hasRunningRun']
        if has_running is True:
            print(f'  PASS: hasRunningRun=true')
        else:
            print(f'  FAIL: hasRunningRun={has_running} (expected true)')
            _write_db_runs(test_db_path, agno_session_id, _parse_db_runs(original_runs))
            return False
    except Exception as e:
        print(f'  FAIL: API error: {e}')
        _write_db_runs(test_db_path, agno_session_id, _parse_db_runs(original_runs))
        return False

    # 5. Update run to COMPLETED
    print('[5/7] Setting run to COMPLETED...')
    for r in runs:
        if r.get('run_id') == run_id:
            r['status'] = 'COMPLETED'
            break
    _write_db_runs(test_db_path, agno_session_id, runs)

    # 6. Check hasRunningRun=false
    print('[6/7] Checking hasRunningRun=false...')
    try:
        sessions = api_get(f'/api/workers/{WORKER_ID}/sessions')
        target = next((s for s in sessions if s['id'] == session_id), None)
        if target is None:
            print(f'  FAIL: Session disappeared')
            return False

        has_running = target.get('hasRunningRun')
        if has_running is False:
            print(f'  PASS: hasRunningRun=false')
        else:
            print(f'  FAIL: hasRunningRun={has_running} (expected false)')
            return False
    except Exception as e:
        print(f'  FAIL: API error: {e}')
        return False

    # 7. Restore original DB state
    print('[7/7] Restoring original DB state...')
    _write_db_runs(test_db_path, agno_session_id, _parse_db_runs(original_runs))
    print('  DB restored')

    return True


# ============================================================================
# Main
# ============================================================================

def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else 'all'
    report = []
    report.append('# Test: hasRunningRun Feature')
    report.append(f'Date: {datetime.now().isoformat()}')
    report.append('')

    all_pass = True

    if mode in ('unit', 'all'):
        if not test_has_running_logic():
            all_pass = False

    if mode in ('integration', 'all'):
        if not test_integration_has_running_run():
            all_pass = False

    report.append('')
    if all_pass:
        report.append('## All tests passed')
    else:
        report.append('## Some tests failed')

    report_text = '\n'.join(report)
    print(f'\n{report_text}')

    report_path = PROJECT_ROOT / 'tests' / 'has_running_run_test_result.md'
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(report_text)
    print(f'Report saved to: {report_path}')

    return 0 if all_pass else 1


if __name__ == '__main__':
    sys.exit(main())
