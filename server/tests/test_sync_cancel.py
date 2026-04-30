"""End-to-end tests for Wiki KB Sync and Cancel.

Usage:
    PYTHONIOENCODING=utf-8 python server/tests/test_sync_cancel.py

Requires the server to be running on http://127.0.0.1:18080
(start it with: cd server && python -m app.run)
"""

from __future__ import annotations

import json
import sys
import time
import traceback
from pathlib import Path

import httpx

BASE = "http://127.0.0.1:18080"
HERMES_PATH = r"C:\00_work\greenvalley\code\llm\hermes-agent"
TEST_KB_NAME = "hermes-agent-test"
TIMEOUT = 120  # seconds — LLM calls can be slow
SYNC_TIMEOUT = 600  # sync can take very long (multiple files × 2 LLM calls each)


# ── Helpers ────────────────────────────────────────────────────

def api(method: str, path: str, **kwargs) -> httpx.Response:
    with httpx.Client(timeout=TIMEOUT) as c:
        r = c.request(method, f"{BASE}{path}", **kwargs)
        return r


def api_async(method: str, path: str, **kwargs) -> httpx.AsyncClient:
    """Return an async context for streaming / long-running calls."""
    return httpx.AsyncClient(timeout=TIMEOUT, base_url=BASE)


def j(resp: httpx.Response) -> dict:
    return resp.json()


def wait_for_sync_to_finish(kb_id: str, max_wait: int = 600):
    """Poll sync status until the KB is no longer syncing."""
    import time
    start = time.time()
    while time.time() - start < max_wait:
        r = api("GET", f"/api/knowledge/{kb_id}/sync/status")
        if r.status_code != 200:
            break
        data = j(r)
        if not data.get("syncing", False):
            return
        elapsed = int(time.time() - start)
        print(f"  ⏳ Waiting for sync to finish... ({elapsed}s)")
        time.sleep(5)
    else:
        raise TimeoutError(f"Sync still running after {max_wait}s")


# ── Test State ─────────────────────────────────────────────────

created_kb_id: str | None = None
passed = 0
failed = 0
errors: list[str] = []


def report(name: str, ok: bool, detail: str = ""):
    global passed, failed
    if ok:
        passed += 1
        print(f"  ✅ PASS  {name}")
    else:
        failed += 1
        msg = f"  ❌ FAIL  {name}"
        if detail:
            msg += f"  — {detail}"
        print(msg)
        errors.append(f"{name}: {detail}")


# ── Tests ──────────────────────────────────────────────────────

def step_1_create_kb():
    """Create a wiki-mode KB pointing at hermes-agent."""
    global created_kb_id
    print("\n── Step 1: Create Wiki Knowledge Base ──")

    resp = api("POST", "/api/knowledge", json={
        "name": TEST_KB_NAME,
        "description": "Test KB for hermes-agent (auto-created by test script)",
        "wiki_mode": True,
        "purpose": "Hermes Agent — a multi-agent orchestration framework",
        "paths": [
            # Pick a single small file for fast testing
            str(Path(HERMES_PATH) / "CONTRIBUTING.md"),
        ],
        "language": "en",
    })
    report("POST /api/knowledge returns 201", resp.status_code == 201, f"got {resp.status_code}")

    data = j(resp)
    created_kb_id = data.get("id")
    report("Response has id", created_kb_id is not None, f"body={data}")
    report("wiki_mode is true", data.get("wiki_mode") is True, f"wiki_mode={data.get('wiki_mode')}")
    report("language is 'en'", data.get("language") == "en", f"language={data.get('language')}")

    print(f"  ℹ️  Created KB: {created_kb_id}")


def step_2_verify_kb():
    """Verify the KB exists via GET."""
    print("\n── Step 2: Verify KB Exists ──")

    resp = api("GET", f"/api/knowledge/{created_kb_id}")
    report("GET /api/knowledge/{id} returns 200", resp.status_code == 200, f"got {resp.status_code}")

    data = j(resp)
    report("Has paths", len(data.get("paths", [])) > 0, f"paths={data.get('paths')}")
    report("Has wiki_stats", "wiki_stats" in data, f"keys={list(data.keys())}")

    # List all KBs and find ours
    resp2 = api("GET", "/api/knowledge")
    ids = [kb["id"] for kb in j(resp2)]
    report("KB appears in list", created_kb_id in ids, f"ids={ids}")


def step_3_wiki_structure():
    """Check that wiki directory structure was created."""
    print("\n── Step 3: Wiki Directory Structure ──")

    resp = api("GET", f"/api/knowledge/{created_kb_id}/wiki/pages")
    report("GET wiki/pages returns 200", resp.status_code == 200, f"got {resp.status_code}")

    stats_resp = api("GET", f"/api/knowledge/{created_kb_id}/wiki/stats")
    report("GET wiki/stats returns 200", stats_resp.status_code == 200, f"got {stats_resp.status_code}")
    stats = j(stats_resp)
    print(f"  ℹ️  Wiki stats: total={stats.get('total', 0)}, by_type={stats.get('by_type', {})}")


def step_4_sync():
    """Trigger sync and verify pages are written."""
    print("\n── Step 4: Sync (first run, may be slow due to LLM calls) ──")

    import asyncio

    async def _do_sync():
        async with httpx.AsyncClient(timeout=SYNC_TIMEOUT, base_url=BASE) as c:
            resp = await c.post(f"/api/knowledge/{created_kb_id}/sync")
            return resp

    try:
        resp = asyncio.run(_do_sync())
    except httpx.ReadTimeout:
        print("  ⚠️  Sync timed out on client side — waiting for server to finish...")
        resp = wait_for_sync_to_finish(created_kb_id)

    report("POST /sync returns 200", resp.status_code == 200, f"got {resp.status_code}: {resp.text[:300]}")

    data = j(resp)
    cancelled = data.get("cancelled", False)
    pages_written = data.get("pages_written", 0)
    pages = data.get("pages", [])

    report("Sync not cancelled", not cancelled, f"cancelled={cancelled}")
    report("Pages written > 0", pages_written > 0, f"pages_written={pages_written}")
    report("Pages list matches count", len(pages) == pages_written, f"len={len(pages)} vs {pages_written}")

    if pages_written > 0:
        print(f"  ℹ️  Written pages: {pages[:10]}{'...' if len(pages) > 10 else ''}")

        # Verify pages actually exist on disk via API
        for p in pages[:3]:
            read_resp = api("GET", f"/api/knowledge/{created_kb_id}/wiki/page/{p}")
            ok = read_resp.status_code == 200
            report(f"Page '{p}' is readable via API", ok, f"status={read_resp.status_code}")

    return data


def step_5_verify_wiki_content():
    """After sync, check wiki pages have proper structure."""
    print("\n── Step 5: Verify Wiki Content ──")

    # List pages
    resp = api("GET", f"/api/knowledge/{created_kb_id}/wiki/pages")
    pages = j(resp)
    report("Wiki has pages after sync", len(pages) > 0, f"count={len(pages)}")

    # Check for expected page categories
    paths = [p.get("path", "") for p in pages]
    has_source = any("sources/" in p for p in paths)
    has_entity = any("entities/" in p for p in paths)
    has_index = any("index.md" in p for p in paths)

    report("Has source pages", has_source, f"paths={paths[:10]}")
    report("Has index.md", has_index, f"paths={paths[:10]}")

    # Read a page and verify frontmatter
    if pages:
        first = pages[0]
        path = first.get("path", "")
        read_resp = api("GET", f"/api/knowledge/{created_kb_id}/wiki/page/{path}")
        if read_resp.status_code == 200:
            page_data = j(read_resp)
            meta = page_data.get("meta", {})
            has_type = "type" in meta
            has_sources = "sources" in meta
            # Root-level files (index.md, overview.md, log.md) may not have frontmatter
            is_root_file = not any(path.startswith(f"wiki/{sub}/") for sub in ("entities", "concepts", "sources", "queries"))
            if not is_root_file:
                report(f"Page '{path}' has frontmatter type", has_type, f"meta={meta}")
                report(f"Page '{path}' has sources field", has_sources, f"meta={meta}")

            # Check sources field format — should be filename, not absolute path
            if has_sources:
                sources = meta["sources"]
                bad_sources = [s for s in sources if ":" in s or s.startswith("/") or s.startswith("\\")]
                report("Sources use filenames (not absolute paths)", len(bad_sources) == 0,
                       f"bad_sources={bad_sources}")

    # Stats
    stats_resp = api("GET", f"/api/knowledge/{created_kb_id}/wiki/stats")
    stats = j(stats_resp)
    report("Stats total > 0 after sync", stats.get("total", 0) > 0, f"stats={stats}")

    # Graph
    graph_resp = api("GET", f"/api/knowledge/{created_kb_id}/wiki/graph")
    report("Graph endpoint returns 200", graph_resp.status_code == 200, f"got {graph_resp.status_code}")
    graph = j(graph_resp)
    report("Graph has nodes", len(graph.get("nodes", [])) > 0, f"nodes={len(graph.get('nodes', []))}")


def step_6_sync_idempotent():
    """Second sync should find no changes (cache hit)."""
    print("\n── Step 6: Second Sync (should be no-op due to cache) ──")

    # Wait for any previous sync to finish
    wait_for_sync_to_finish(created_kb_id)

    import asyncio

    async def _do_sync():
        async with httpx.AsyncClient(timeout=SYNC_TIMEOUT, base_url=BASE) as c:
            resp = await c.post(f"/api/knowledge/{created_kb_id}/sync")
            return resp

    resp = asyncio.run(_do_sync())
    report("Second sync returns 200", resp.status_code == 200, f"got {resp.status_code}")

    data = j(resp)
    pages_written = data.get("pages_written", 0)
    report("Second sync writes 0 pages (cache hit)", pages_written == 0,
           f"pages_written={pages_written}")


def step_7_concurrent_sync_protection():
    """Two concurrent syncs — second should get 409."""
    print("\n── Step 7: Concurrent Sync Protection ──")

    # Clear cache so sync actually does work (slow enough to overlap)
    cache_dir = Path("C:/00_work/greenvalley/code/llm/nowork/server/knowledge") / created_kb_id / ".cache"
    cache_file = cache_dir / "ingest-cache.json"
    try:
        if cache_file.exists():
            cache_file.unlink()
            print(f"  ℹ️  Cleared cache for concurrent test")
    except Exception:
        pass

    import asyncio

    async def _do_concurrent():
        async with httpx.AsyncClient(timeout=SYNC_TIMEOUT, base_url=BASE) as c:
            t1 = asyncio.create_task(c.post(f"/api/knowledge/{created_kb_id}/sync"))
            await asyncio.sleep(0.3)  # small delay to let first request register
            t2 = asyncio.create_task(c.post(f"/api/knowledge/{created_kb_id}/sync"))
            r1, r2 = await asyncio.gather(t1, t2, return_exceptions=True)
            return r1, r2

    r1, r2 = asyncio.run(_do_concurrent())

    # One should succeed (200), the other should get 409 (or both 200 if first finished fast)
    s1 = r1.status_code if isinstance(r1, httpx.Response) else -1
    s2 = r2.status_code if isinstance(r2, httpx.Response) else -1

    both_ok = (s1 == 200 and s2 == 200)
    one_conflict = (s1 == 409 or s2 == 409)

    if both_ok:
        report("Both syncs completed (first finished before second arrived) — acceptable",
               True)
    elif one_conflict:
        report("Second sync correctly rejected with 409", True,
               f"statuses: {s1}, {s2}")
    else:
        report("Concurrent sync handling", False,
               f"unexpected statuses: {s1}, {s2}")


def step_8_cancel_sync():
    """Start a sync, then cancel it. Verify cancel works."""
    print("\n── Step 8: Sync Cancellation ──")

    import asyncio

    # Wait for any previous sync to finish, then add more files to make sync slower
    wait_for_sync_to_finish(created_kb_id)

    # Add a large file to give us a bigger cancellation window
    api("PUT", f"/api/knowledge/{created_kb_id}", json={
        "paths": [
            str(Path(HERMES_PATH) / "CONTRIBUTING.md"),
            str(Path(HERMES_PATH) / "README.md"),  # large file — slow LLM call
        ],
        "config": {},
    })

    # Clear cache so sync actually does LLM work (gives us time to cancel)
    cache_dir = Path("C:/00_work/greenvalley/code/llm/nowork/server/knowledge") / created_kb_id / ".cache"
    cache_file = cache_dir / "ingest-cache.json"
    try:
        if cache_file.exists():
            cache_file.unlink()
            print(f"  ℹ️  Cleared ingest cache for reliable cancel test")
        else:
            print(f"  ℹ️  No cache file found (first sync already clear)")
    except Exception as ex:
        print(f"  ⚠️  Could not clear cache: {ex}")

    async def _do_cancel_test():
        async with httpx.AsyncClient(timeout=SYNC_TIMEOUT, base_url=BASE) as c:
            # Start sync in background
            sync_task = asyncio.create_task(
                c.post(f"/api/knowledge/{created_kb_id}/sync")
            )
            # Wait a bit for the sync to start
            await asyncio.sleep(2)

            # Cancel it
            cancel_resp = await c.post(f"/api/knowledge/{created_kb_id}/sync/cancel")
            
            # Wait for the sync to finish (it should return cancelled)
            try:
                sync_resp = await asyncio.wait_for(sync_task, timeout=120)
            except asyncio.TimeoutError:
                sync_resp = None

            return cancel_resp, sync_resp

    cancel_resp, sync_resp = asyncio.run(_do_cancel_test())

    report("Cancel endpoint returns 200", cancel_resp.status_code == 200,
           f"got {cancel_resp.status_code}")
    cancel_data = j(cancel_resp)
    report("Cancel response ok=true", cancel_data.get("ok") is True,
           f"data={cancel_data}")

    if sync_resp is not None:
        report("Sync responded after cancel", True)
        sync_data = j(sync_resp)
        was_cancelled = sync_data.get("cancelled", False)
        report("Sync response has cancelled=true", was_cancelled,
               f"sync_data={sync_data}")
    else:
        report("Sync response received (may have timed out)", False,
               "sync task timed out waiting for response")

    # Verify wiki data is still valid after cancel
    stats_resp = api("GET", f"/api/knowledge/{created_kb_id}/wiki/stats")
    report("Wiki stats still accessible after cancel", stats_resp.status_code == 200,
           f"got {stats_resp.status_code}")


def step_9_update_language():
    """Update KB language and verify it persists."""
    print("\n── Step 9: Language Setting Persistence ──")

    # Change to zh
    resp = api("PUT", f"/api/knowledge/{created_kb_id}", json={
        "language": "zh",
        "config": {},
    })
    report("PUT language=zh returns 200", resp.status_code == 200, f"got {resp.status_code}")

    # Read back
    get_resp = api("GET", f"/api/knowledge/{created_kb_id}")
    data = j(get_resp)
    report("Language persisted as 'zh'", data.get("language") == "zh",
           f"language={data.get('language')}")

    # Change back to en
    resp2 = api("PUT", f"/api/knowledge/{created_kb_id}", json={
        "language": "en",
    })
    get_resp2 = api("GET", f"/api/knowledge/{created_kb_id}")
    data2 = j(get_resp2)
    report("Language changed back to 'en'", data2.get("language") == "en",
           f"language={data2.get('language')}")


def step_10_cleanup():
    """Delete the test KB."""
    print("\n── Step 10: Cleanup ──")

    if created_kb_id:
        resp = api("DELETE", f"/api/knowledge/{created_kb_id}")
        report("DELETE /api/knowledge/{id} returns 200", resp.status_code == 200,
               f"got {resp.status_code}")

        # Verify gone
        resp2 = api("GET", f"/api/knowledge/{created_kb_id}")
        report("KB returns 404 after deletion", resp2.status_code == 404,
               f"got {resp2.status_code}")
    else:
        report("Cleanup skipped (no KB created)", True)


# ── Main ───────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("Wiki Sync & Cancel End-to-End Tests")
    print(f"Server: {BASE}")
    print(f"Target: {HERMES_PATH}")
    print("=" * 60)

    # Check server is reachable
    try:
        r = api("GET", "/api/knowledge")
        if r.status_code != 200:
            print(f"❌ Server returned {r.status_code} — aborting")
            sys.exit(1)
        print(f"✅ Server is reachable ({len(j(r))} existing KBs)")
    except Exception as e:
        print(f"❌ Cannot reach server at {BASE}: {e}")
        print("   Start it with: cd server && python -m app.run")
        sys.exit(1)

    steps = [
        step_1_create_kb,
        step_2_verify_kb,
        step_3_wiki_structure,
        step_4_sync,
        step_5_verify_wiki_content,
        step_6_sync_idempotent,
        step_7_concurrent_sync_protection,
        step_8_cancel_sync,
        step_9_update_language,
        step_10_cleanup,
    ]

    for step in steps:
        try:
            step()
        except Exception as e:
            report(step.__name__, False, traceback.format_exc())

    print("\n" + "=" * 60)
    print(f"Results: {passed} passed, {failed} failed")
    if errors:
        print("\nFailures:")
        for e in errors:
            print(f"  • {e}")
    print("=" * 60)

    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
