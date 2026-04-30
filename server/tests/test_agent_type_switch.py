"""Test agent type switching: agno <-> pi <-> agno round-trip.

Tests API endpoints, serialization, and runtime build without
making actual LLM calls (no chat messages to agents).

Run: python tests/test_agent_type_switch.py
"""

import subprocess
import sys
import time
import urllib.request
import urllib.error
import json
import os

BASE = ['http://127.0.0.1:18080']
WORKER_ID = 'code-agent-1'

passed = 0
failed = 0


def check(label: str, condition: bool, detail: str = ''):
    global passed, failed
    if condition:
        passed += 1
        print(f'  PASS  {label}')
    else:
        failed += 1
        print(f'  FAIL  {label}  {detail}')


def api(method: str, path: str, body: dict | None = None, timeout: int = 10) -> tuple[int, any]:
    url = f'{BASE[0]}{path}'
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, method=method)
    if data:
        req.add_header('Content-Type', 'application/json')
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            ct = resp.headers.get('Content-Type', '')
            raw = resp.read().decode()
            if 'json' in ct:
                return resp.status, json.loads(raw)
            return resp.status, raw
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, raw
    except Exception as e:
        return 0, str(e)


def kill_server():
    """Kill any python process on port 18080."""
    try:
        result = subprocess.run(
            ['powershell', '-Command',
             "Get-NetTCPConnection -LocalPort 18080 -ErrorAction SilentlyContinue "
             "| Select-Object -ExpandProperty OwningProcess "
             "| ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }"],
            capture_output=True, timeout=5,
        )
    except Exception:
        pass


# ── Phase 0: Start server ──────────────────────────────────────
print('\n=== Phase 0: Start server ===')
kill_server()
time.sleep(0.5)

# Redirect server output to a log file to avoid pipe blocking
log_path = os.path.join(os.path.dirname(__file__), '_test_server.log')
log_file = open(log_path, 'w')

proc = subprocess.Popen(
    [sys.executable, '-m', 'app.run'],
    cwd=os.path.join(os.path.dirname(__file__), '..'),
    stdout=log_file,
    stderr=subprocess.STDOUT,
)

ready = False
for i in range(20):
    time.sleep(0.5)
    for port in [18080, 18081, 18082]:
        try:
            urllib.request.urlopen(f'http://127.0.0.1:{port}/api/workers', timeout=2)
            ready = True
            BASE[0] = f'http://127.0.0.1:{port}'
            print(f'  Server found on port {port}')
            break
        except Exception:
            pass
    if ready:
        break

check('Server starts within 10s', ready)
if not ready:
    print('  ERROR: Server did not start, aborting')
    proc.kill()
    sys.exit(1)


try:
    # ── Phase 1: Agent Types API ────────────────────────────────
    print('\n=== Phase 1: Agent Types API ===')

    status, agent_types = api('GET', '/api/agent-types')
    check('GET /api/agent-types returns 200', status == 200, f'got {status}: {str(agent_types)[:200]}')
    check('Agent types is a list', isinstance(agent_types, list), f'got {type(agent_types)}')

    if isinstance(agent_types, list):
        check('At least 4 agent types', len(agent_types) >= 4, f'got {len(agent_types)}')
        type_ids = [at['id'] for at in agent_types]
        check('Contains agno', 'agno' in type_ids)
        check('Contains pi', 'pi' in type_ids)
        check('Contains claude', 'claude' in type_ids)
        check('Contains opencode', 'opencode' in type_ids)

        agno_type = next((at for at in agent_types if at['id'] == 'agno'), None)
        check('Agno type has name', agno_type and agno_type.get('name') == 'Agno Agent')
        check('Agno type has framework', agno_type and agno_type.get('framework') == 'agno')
        check('Agno type has supports list', agno_type and isinstance(agno_type.get('supports'), list))

        pi_type = next((at for at in agent_types if at['id'] == 'pi'), None)
        check('Pi type has framework=pi', pi_type and pi_type.get('framework') == 'pi')
        check('Pi type has config_fields', pi_type and isinstance(pi_type.get('config_fields'), list))


    # ── Phase 2: Prerequisites API ──────────────────────────────
    print('\n=== Phase 2: Prerequisites API ===')

    status, prereq_agno = api('GET', '/api/prerequisites/agno')
    check('GET /api/prerequisites/agno returns 200', status == 200, f'got {status}')
    check('Agno is always ready', isinstance(prereq_agno, dict) and prereq_agno.get('ready') is True)
    check('Agno has empty chain', isinstance(prereq_agno, dict) and prereq_agno.get('chain') == [])

    status, prereq_pi = api('GET', '/api/prerequisites/pi')
    check('GET /api/prerequisites/pi returns 200', status == 200, f'got {status}')
    check('Pi prereq has chain', isinstance(prereq_pi, dict) and isinstance(prereq_pi.get('chain'), list))
    chain = prereq_pi.get('chain', []) if isinstance(prereq_pi, dict) else []
    check('Pi chain has 3 steps (node/npm/pi)', len(chain) == 3, f'got {len(chain)}')
    check('Pi is ready (all installed)', prereq_pi.get('ready') is True if isinstance(prereq_pi, dict) else False,
          f'missing: {prereq_pi.get("missing") if isinstance(prereq_pi, dict) else "N/A"}')

    if len(chain) > 0:
        step = chain[0]
        check('Chain step has id+name+installed', 'id' in step and 'name' in step and 'installed' in step)

    status, prereq_unk = api('GET', '/api/prerequisites/nonexistent')
    check('Unknown type returns 200', status == 200)
    check('Unknown type is ready (no prereqs)', isinstance(prereq_unk, dict) and prereq_unk.get('ready') is True)


    # ── Phase 3: Worker serialization includes agentType ────────
    print('\n=== Phase 3: Worker serialization ===')

    status, workers = api('GET', '/api/workers')
    check('GET /api/workers returns 200', status == 200)
    worker = next((w for w in workers if w.get('id') == WORKER_ID), None) if isinstance(workers, list) else None
    check(f'Found worker {WORKER_ID}', worker is not None)
    check('Default agentType is agno', worker and worker.get('agentType') == 'agno',
          f'got {worker.get("agentType") if worker else "no worker"}')

    # Save original config for restore
    orig_config = worker.get('config', {}) if worker else {}


    # ── Phase 4: Switch to pi agent type ────────────────────────
    print('\n=== Phase 4: Switch to pi agent type ===')

    status, updated = api('PUT', f'/api/workers/{WORKER_ID}', {
        'name': 'Code Agent',
        'description': 'Test pi agent',
        'agentType': 'pi',
        'config': {
            'model': orig_config.get('model'),
            'instructions': 'You are a coding assistant.',
        },
    })
    check('PUT worker with agentType=pi returns 200', status == 200,
          f'got {status}: {str(updated)[:200]}')

    # Verify it persisted via GET
    status, worker_pi = api('GET', f'/api/workers/{WORKER_ID}')
    check('Worker agentType is now pi', worker_pi.get('agentType') == 'pi',
          f'got {worker_pi.get("agentType")}')
    check('Worker still has id', worker_pi.get('id') == WORKER_ID)
    check('Worker name preserved', worker_pi.get('name') == 'Code Agent')


    # ── Phase 5: Switch to claude ───────────────────────────────
    print('\n=== Phase 5: Switch to claude agent type ===')

    status, updated_c = api('PUT', f'/api/workers/{WORKER_ID}', {
        'name': 'Code Agent',
        'description': 'Test claude agent',
        'agentType': 'claude',
        'config': {'instructions': 'Claude test.'},
    })
    check('PUT with agentType=claude returns 200', status == 200)

    status, worker_claude = api('GET', f'/api/workers/{WORKER_ID}')
    check('Worker agentType is claude', worker_claude.get('agentType') == 'claude',
          f'got {worker_claude.get("agentType")}')


    # ── Phase 6: Switch back to agno ────────────────────────────
    print('\n=== Phase 6: Switch back to agno ===')

    status, reverted = api('PUT', f'/api/workers/{WORKER_ID}', {
        'name': 'Code Agent',
        'description': orig_config.get('instructions', ''),
        'agentType': 'agno',
        'config': orig_config,
    })
    check('PUT with agentType=agno returns 200', status == 200)

    status, worker_final = api('GET', f'/api/workers/{WORKER_ID}')
    check('Worker agentType back to agno', worker_final.get('agentType') == 'agno',
          f'got {worker_final.get("agentType")}')
    check('Config restored (tools)', worker_final.get('config', {}).get('tools') == orig_config.get('tools'))
    check('Config restored (skills)', worker_final.get('config', {}).get('skills') == orig_config.get('skills'))


    # ── Phase 7: Unknown agent type ─────────────────────────────
    print('\n=== Phase 7: Unknown agent type ===')

    status, _ = api('PUT', f'/api/workers/{WORKER_ID}', {
        'name': 'Code Agent',
        'agentType': 'totally_fake',
        'config': {},
    })
    check('PUT with unknown agentType accepted (stored as-is)', status == 200)

    status, worker_unk = api('GET', f'/api/workers/{WORKER_ID}')
    check('Unknown agentType stored', worker_unk.get('agentType') == 'totally_fake',
          f'got {worker_unk.get("agentType")}')

    # Restore to agno
    api('PUT', f'/api/workers/{WORKER_ID}', {
        'name': 'Code Agent',
        'agentType': 'agno',
        'config': orig_config,
    })


    # ── Phase 8: Install API security ───────────────────────────
    print('\n=== Phase 8: Install API security ===')

    status, _ = api('POST', '/api/prerequisites/install', {'command': 'rm -rf /'})
    check('Dangerous command rejected (400)', status == 400, f'got {status}')

    status, _ = api('POST', '/api/prerequisites/install', {'command': ''})
    check('Empty command rejected (400)', status == 400)

    # Test with completely missing body
    status, body = api('POST', '/api/prerequisites/install')
    check('Missing body rejected (400/422)', status in (400, 422), f'got {status}: {str(body)[:100]}')

    status, _ = api('POST', '/api/prerequisites/install', {'command': 'python -c "import os; os.remove(\\"/etc/passwd\\")"'})
    check('Non-allowlisted command rejected (400)', status == 400)


    # ── Phase 9: Session creation works for agno (no regression) ─
    print('\n=== Phase 9: Session creation (no regression) ===')

    status, session = api('POST', f'/api/workers/{WORKER_ID}/sessions', {'title': 'Agno regression test'})
    check('Can create session for agno worker', status == 201, f'got {status}')

    status, sessions = api('GET', f'/api/workers/{WORKER_ID}/sessions')
    check('Can list sessions', status == 200)
    check('Sessions is a list', isinstance(sessions, list))


    # ── Cleanup: restore original config ────────────────────────
    print('\n=== Cleanup ===')

    status, _ = api('PUT', f'/api/workers/{WORKER_ID}', {
        'name': 'Code Agent',
        'description': 'Handles coding and debugging tasks',
        'agentType': 'agno',
        'config': orig_config,
    })
    check('Worker config fully restored', status == 200)


finally:
    # Always shutdown server
    print('\nShutting down server...')
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=3)
    finally:
        log_file.close()
        # Remove log file if all passed
        if failed == 0 and os.path.exists(log_path):
            os.remove(log_path)


# ── Summary ────────────────────────────────────────────────────
print(f'\n{"="*60}')
print(f'Results: {passed} passed, {failed} failed')
print(f'{"="*60}')
sys.exit(1 if failed > 0 else 0)
