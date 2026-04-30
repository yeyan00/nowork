"""
测试完整流程:
1. 确认 doc-agent 当前没有关联知识库
2. 通过 API 关联 kb-0bf573ea 知识库
3. 创建 session, 发送与知识库内容(molmo多模态)相关的问题
4. 验证 LLM 是否先调用 search_knowledge 工具从知识库查询信息

用法:
    PYTHONIOENCODING=utf-8 python server/tests/test_knowledge_tool_call.py
"""

import json
import sys
import time
import subprocess
import urllib.request
import urllib.error

BASE_URL = "http://127.0.0.1:18080"
WORKER_ID = "doc-agent-1"
KB_ID = "kb-0bf573ea"


def api(method, path, body=None):
    url = BASE_URL + path
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, method=method,
                                headers={"Content-Type": "application/json"} if data else {})
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            raw = resp.read().decode("utf-8")
            ct = resp.headers.get("content-type", "")
            if "application/json" in ct:
                return resp.status, json.loads(raw)
            return resp.status, raw
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8")
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, raw


def api_stream(path, body):
    url = BASE_URL + path
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method="POST",
                                headers={"Content-Type": "application/json",
                                         "Accept": "text/event-stream"})
    events = []
    with urllib.request.urlopen(req, timeout=180) as resp:
        buf = ""
        for chunk in iter(lambda: resp.read(4096).decode("utf-8"), ""):
            buf += chunk
            while "\n\n" in buf:
                event_str, buf = buf.split("\n\n", 1)
                for line in event_str.split("\n"):
                    if line.startswith("data: "):
                        try:
                            events.append(json.loads(line[6:]))
                        except json.JSONDecodeError:
                            pass
    return events


def start_server():
    print("[start] Starting nowork server...")
    proc = subprocess.Popen(
        [sys.executable, "-m", "app.run"],
        cwd="server", stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    for _ in range(30):
        time.sleep(1)
        try:
            urllib.request.urlopen(BASE_URL + "/health", timeout=2)
            print(f"[start] Server ready (PID {proc.pid})")
            return proc.pid
        except Exception:
            pass
    print("[start] Server failed to start within 30s")
    proc.terminate()
    return None


def stop_server(pid):
    if pid is None:
        return
    print(f"[stop] Stopping server (PID {pid})...")
    subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True)


def run_test():
    server_pid = None

    # Check if server is already running
    try:
        urllib.request.urlopen(BASE_URL + "/health", timeout=2)
        print("[info] Server already running")
    except Exception:
        server_pid = start_server()
        if server_pid is None:
            return False

    try:
        return _do_test()
    finally:
        stop_server(server_pid)


def _do_test():
    # ── Step 1: confirm no knowledge base ──────────────────────
    print("\n" + "=" * 60)
    print("Step 1: Check doc-agent current knowledge config")
    print("=" * 60)
    status, worker = api("GET", f"/api/workers/{WORKER_ID}")
    assert status == 200, f"Failed: {status} {worker}"
    kb_before = worker.get("config", {}).get("knowledge", [])
    print(f"   knowledge before: {kb_before or '(empty)'}")

    # ── Step 2: associate knowledge base via PUT API ───────────
    print("\n" + "=" * 60)
    print("Step 2: Associate kb-0bf573ea to doc-agent via API")
    print("=" * 60)
    status, updated = api("PUT", f"/api/workers/{WORKER_ID}", {
        "config": {"knowledge": [KB_ID]}
    })
    assert status == 200, f"PUT failed: {status} {updated}"
    kb_after = updated.get("config", {}).get("knowledge", [])
    print(f"   knowledge after:  {kb_after}")
    assert KB_ID in kb_after, f"Knowledge base {KB_ID} not found in response"
    print("   OK - knowledge base associated")

    # ── Step 3: create session ─────────────────────────────────
    print("\n" + "=" * 60)
    print("Step 3: Create session")
    print("=" * 60)
    status, session = api("POST", f"/api/workers/{WORKER_ID}/sessions",
                          {"title": "Knowledge test"})
    assert status == 201, f"Session create failed: {status} {session}"
    sid = session["id"]
    print(f"   Session: {sid}")

    # ── Step 4: send question about molmo ──────────────────────
    question = "molmo\u591a\u6a21\u6001\u6a21\u578b\u662f\u4ec0\u4e48\uff1f\u8bf7\u4ece\u77e5\u8bc6\u5e93\u4e2d\u67e5\u627e\u76f8\u5173\u4fe1\u606f\u3002"
    print("\n" + "=" * 60)
    print(f"Step 4: Send question: {question}")
    print("=" * 60)

    events = api_stream(f"/api/sessions/{sid}/messages", {"content": question})

    # ── Step 5: analyze events ─────────────────────────────────
    print("\n" + "=" * 60)
    print("Step 5: Analyze SSE events")
    print("=" * 60)

    tool_started = []
    tool_completed = []
    run_completed = None
    run_error = None

    for evt in events:
        et = evt.get("event", "")
        if et == "ToolCallStarted":
            tool_started.append(evt)
        elif et == "ToolCallCompleted":
            tool_completed.append(evt)
        elif et == "RunCompleted":
            run_completed = evt
        elif et == "RunError":
            run_error = evt

    print(f"\n   ToolCallStarted: {len(tool_started)}")
    for i, tc in enumerate(tool_started):
        for t in tc.get("toolCalls", []):
            name = t.get("toolName", "?")
            args = json.dumps(t.get("toolArgs", {}), ensure_ascii=False)[:200]
            print(f"   [{i+1}] {name}({args}) [{t.get('status','running')}]")

    print(f"\n   ToolCallCompleted: {len(tool_completed)}")
    for i, tc in enumerate(tool_completed):
        for t in tc.get("toolCalls", []):
            name = t.get("toolName", "?")
            result = str(t.get("result", ""))[:200]
            print(f"   [{i+1}] {name} -> {result}...")

    if run_error:
        print(f"\n   RunError: {run_error.get('content', '')}")
        return False

    if run_completed:
        content = run_completed.get("content", "")
        print(f"\n   Response (first 300 chars):\n   {content[:300]}")

    # ── Step 6: verify search_knowledge was called ─────────────
    print("\n" + "=" * 60)
    print("Step 6: Verify search_knowledge tool call")
    print("=" * 60)

    all_tools = []
    search_called = False
    for tc in tool_started:
        for t in tc.get("toolCalls", []):
            name = t.get("toolName", "")
            all_tools.append(name)
            if "search_knowledge" in name:
                search_called = True

    print(f"   All tool calls: {all_tools}")
    print(f"   search_knowledge called: {search_called}")

    if search_called:
        print("\n   PASS - doc-agent called search_knowledge after associating KB via API")
    else:
        print("\n   FAIL - doc-agent did NOT call search_knowledge")
        print("   Possible: LLM decided not to search, or tool not injected")

    return search_called


if __name__ == "__main__":
    ok = run_test()
    sys.exit(0 if ok else 1)
