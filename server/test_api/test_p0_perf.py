"""
Test script for P0 performance optimizations.

Validates that these APIs return correct results after refactoring:
  1. list_sessions — N+1 → batch query
  2. lint_knowledge_base — 4-pass → single-pass
  3. build_graph — 2-pass → single-pass

Usage:
  1. Start server:  python -m app.run  (in server/ directory)
  2. Run this test: python tests/test_p0_perf.py
  3. Server stays running — Ctrl+C or call stop endpoint when done.
"""

import json
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

BASE = 'http://127.0.0.1:18081'
TIMEOUT = 10

passed = 0
failed = 0


def api_get(path: str) -> dict | list:
    """GET request, return parsed JSON."""
    url = f'{BASE}{path}'
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return json.loads(resp.read().decode())


def assert_test(name: str, condition: bool, detail: str = ''):
    global passed, failed
    if condition:
        passed += 1
        print(f'  ✅ {name}')
    else:
        failed += 1
        print(f'  ❌ {name} — {detail}')


# ── Test 1: Workers list ──────────────────────────────────────────
print('\n=== Test 1: GET /api/workers ===')
try:
    workers = api_get('/api/workers')
    assert_test('returns a list', isinstance(workers, list))
    assert_test('has at least 1 worker', len(workers) >= 1, f'got {len(workers)}')

    if workers:
        w = workers[0]
        assert_test('worker has id', 'id' in w, f'keys: {list(w.keys())}')
        assert_test('worker has name', 'name' in w)
        assert_test('worker has recent', 'recent' in w)
        assert_test('worker has type', 'type' in w)

        worker_id = w['id']
        print(f'\n  Using worker: {w["name"]} ({worker_id})')
except Exception as e:
    print(f'  ❌ FAILED: {e}')
    failed += 1
    sys.exit(1)


# ── Test 2: Sessions list ─────────────────────────────────────────
print(f'\n=== Test 2: GET /api/workers/{worker_id}/sessions ===')
try:
    sessions = api_get(f'/api/workers/{worker_id}/sessions')
    assert_test('returns a list', isinstance(sessions, list))

    if sessions:
        s = sessions[0]
        assert_test('session has id', 'id' in s, f'keys: {list(s.keys())}')
        assert_test('session has workerId', 'workerId' in s)
        assert_test('session has title', 'title' in s)
        assert_test('session has updatedAt', 'updatedAt' in s)
        assert_test('session has runCount', 'runCount' in s)
        assert_test('workerId matches', s['workerId'] == worker_id,
                     f'expected {worker_id}, got {s["workerId"]}')
        print(f'  Sessions count: {len(sessions)}')
    else:
        print('  (no sessions for this worker, skipping field checks)')
except Exception as e:
    print(f'  ❌ FAILED: {e}')
    failed += 1


# ── Test 3: Knowledge bases ───────────────────────────────────────
print('\n=== Test 3: Knowledge APIs ===')
kb_id = None
try:
    kbs = api_get('/api/knowledge')
    assert_test('knowledge list returns array', isinstance(kbs, list))

    # Find a wiki-mode KB for graph/lint tests
    wiki_kb = next((kb for kb in kbs if kb.get('wiki_mode')), None)
    if wiki_kb:
        kb_id = wiki_kb['id']
        print(f'  Found wiki KB: {wiki_kb.get("name", kb_id)} ({kb_id})')
    else:
        print('  No wiki-mode KB found, skipping wiki tests')
except Exception as e:
    print(f'  ❌ FAILED: {e}')
    failed += 1


# ── Test 4: Wiki pages list ───────────────────────────────────────
if kb_id:
    print(f'\n=== Test 4: Wiki pages for {kb_id} ===')
    try:
        pages = api_get(f'/api/knowledge/{kb_id}/wiki/pages')
        assert_test('pages returns list', isinstance(pages, list))

        if pages:
            p = pages[0]
            assert_test('page has path', 'path' in p, f'keys: {list(p.keys())}')
            assert_test('page has title', 'title' in p)
            assert_test('page has type', 'type' in p)
            print(f'  Pages count: {len(pages)}')
        else:
            print('  (no pages yet)')
    except Exception as e:
        print(f'  ❌ FAILED: {e}')
        failed += 1


# ── Test 5: Wiki stats ────────────────────────────────────────────
if kb_id:
    print(f'\n=== Test 5: Wiki stats for {kb_id} ===')
    try:
        stats = api_get(f'/api/knowledge/{kb_id}/wiki/stats')
        assert_test('stats has total', 'total' in stats, f'keys: {list(stats.keys())}')
        assert_test('stats has by_type', 'by_type' in stats)
        assert_test('stats.total >= 0', stats['total'] >= 0)
        print(f'  Stats: {json.dumps(stats, indent=2)}')
    except Exception as e:
        print(f'  ❌ FAILED: {e}')
        failed += 1


# ── Test 6: Wiki lint (single-pass) ───────────────────────────────
if kb_id:
    print(f'\n=== Test 6: Wiki lint for {kb_id} ===')
    try:
        t0 = time.time()
        req = urllib.request.Request(
            f'{BASE}/api/knowledge/{kb_id}/wiki/lint',
            method='POST',
            headers={'Content-Type': 'application/json'},
            data=b'{}',
        )
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            lint = json.loads(resp.read().decode())
        elapsed = time.time() - t0

        assert_test('lint returns dict', isinstance(lint, dict))
        assert_test('lint has broken_links', 'broken_links' in lint)
        assert_test('lint has orphan_pages', 'orphan_pages' in lint)
        assert_test('lint has empty_pages', 'empty_pages' in lint)
        assert_test('lint has missing_sources', 'missing_sources' in lint)
        assert_test('lint has total_pages', 'total_pages' in lint)
        assert_test('lint has healthy', 'healthy' in lint)
        assert_test('lint completed in < 5s', elapsed < 5, f'took {elapsed:.2f}s')
        print(f'  Lint result: healthy={lint["healthy"]}, pages={lint["total_pages"]}, '
              f'broken={len(lint["broken_links"])}, orphans={len(lint["orphan_pages"])}')
        print(f'  Elapsed: {elapsed:.3f}s')
    except Exception as e:
        print(f'  ❌ FAILED: {e}')
        failed += 1


# ── Test 7: Wiki graph (single-pass) ──────────────────────────────
if kb_id:
    print(f'\n=== Test 7: Wiki graph for {kb_id} ===')
    try:
        t0 = time.time()
        graph = api_get(f'/api/knowledge/{kb_id}/wiki/graph')
        elapsed = time.time() - t0

        assert_test('graph has nodes', 'nodes' in graph)
        assert_test('graph has edges', 'edges' in graph)
        assert_test('graph has stats', 'stats' in graph)
        assert_test('nodes is list', isinstance(graph['nodes'], list))
        assert_test('edges is list', isinstance(graph['edges'], list))
        assert_test('graph completed in < 5s', elapsed < 5, f'took {elapsed:.2f}s')

        stats = graph.get('stats', {})
        assert_test('stats has total_nodes', 'total_nodes' in stats)
        assert_test('stats has total_edges', 'total_edges' in stats)
        assert_test('stats has by_type', 'by_type' in stats)
        assert_test('stats has orphan_nodes', 'orphan_nodes' in stats)

        if graph['nodes']:
            n = graph['nodes'][0]
            assert_test('node has id', 'id' in n)
            assert_test('node has title', 'title' in n)
            assert_test('node has type', 'type' in n)
            assert_test('node has group', 'group' in n)

        if graph['edges']:
            e = graph['edges'][0]
            assert_test('edge has source', 'source' in e)
            assert_test('edge has target', 'target' in e)

        print(f'  Nodes: {len(graph["nodes"])}, Edges: {len(graph["edges"])}')
        print(f'  Stats: {json.dumps(stats, indent=2)}')
        print(f'  Elapsed: {elapsed:.3f}s')
    except Exception as e:
        print(f'  ❌ FAILED: {e}')
        failed += 1


# ── Test 8: Consistency check — lint vs graph ─────────────────────
if kb_id:
    print(f'\n=== Test 8: Consistency check (lint vs graph) ===')
    try:
        # Lint uses POST
        req = urllib.request.Request(
            f'{BASE}/api/knowledge/{kb_id}/wiki/lint',
            method='POST',
            headers={'Content-Type': 'application/json'},
            data=b'{}',
        )
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            lint = json.loads(resp.read().decode())

        graph = api_get(f'/api/knowledge/{kb_id}/wiki/graph')

        lint_total = lint['total_pages']
        graph_nodes = graph['stats']['total_nodes']
        # Graph may have extra "missing" nodes for broken links
        assert_test('graph nodes >= lint pages',
                     graph_nodes >= lint_total,
                     f'graph={graph_nodes}, lint={lint_total}')

        # Orphan count should match
        lint_orphans = lint['orphan_pages']
        graph_orphans = graph['stats'].get('orphan_nodes', [])
        lint_orphan_ids = {Path(p).stem for p in lint_orphans}
        graph_orphan_ids = set(graph_orphans)
        assert_test('orphan counts match',
                     lint_orphan_ids == graph_orphan_ids,
                     f'lint={lint_orphan_ids}, graph={graph_orphan_ids}')

        # Broken links in lint should appear as "missing" type nodes in graph
        broken_targets = {bl['target'] for bl in lint['broken_links']}
        missing_nodes = {n['id'] for n in graph['nodes'] if n['type'] == 'missing'}
        assert_test('broken link targets appear as missing nodes',
                     broken_targets.issubset(missing_nodes),
                     f'broken={broken_targets - missing_nodes} not in missing nodes')
    except Exception as e:
        print(f'  ❌ FAILED: {e}')
        failed += 1


# ── Summary ───────────────────────────────────────────────────────
print(f'\n{"=" * 50}')
print(f'Results: ✅ {passed} passed, ❌ {failed} failed')
print(f'{"=" * 50}')
sys.exit(0 if failed == 0 else 1)
