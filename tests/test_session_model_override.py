import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))

from app import session_manager, services


@pytest.fixture(autouse=True)
def _use_temp_db(tmp_path, monkeypatch):
    db_path = tmp_path / 'test_session_model_override.db'
    session_manager.reset_engine()
    session_manager._engine = None
    session_manager._SessionLocal = None
    monkeypatch.setattr(session_manager, '_get_db_path', lambda: db_path)
    session_manager.ensure_db()
    yield db_path
    session_manager.reset_engine()
    session_manager._engine = None
    session_manager._SessionLocal = None
    services._SESSION_RUNTIME_CACHE.clear()
    services._SESSION_LOCKS.clear()


class TestSessionModelOverrideAPI:
    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        from app.main import app

        @asynccontextmanager
        async def test_lifespan(application):
            application.state.agent_os = None
            yield

        app.router.lifespan_context = test_lifespan
        return TestClient(app)

    def test_create_update_and_list_session_model_override(self, client):
        worker_id = 'code-agent-1'

        create_resp = client.post(f'/api/workers/{worker_id}/sessions', json={'title': 'override test'})
        assert create_resp.status_code == 201
        created = create_resp.json()
        session_id = created['id']
        assert created['modelOverride'] is None

        update_resp = client.put(f'/api/sessions/{session_id}', json={'modelOverride': 'openai/gpt-4.1'})
        assert update_resp.status_code == 200
        updated = update_resp.json()
        assert updated['modelOverride'] == 'openai/gpt-4.1'

        list_resp = client.get(f'/api/workers/{worker_id}/sessions')
        assert list_resp.status_code == 200
        sessions = list_resp.json()
        matched = next(s for s in sessions if s['id'] == session_id)
        assert matched['modelOverride'] == 'openai/gpt-4.1'

        clear_resp = client.put(f'/api/sessions/{session_id}', json={'modelOverride': None})
        assert clear_resp.status_code == 200
        cleared = clear_resp.json()
        assert cleared['modelOverride'] is None


@pytest.mark.asyncio
class TestSessionRuntimeSelection:
    async def test_shared_runtime_used_when_no_override(self, monkeypatch):
        worker = {'id': 'code-agent-1', 'type': 'Agent'}
        shared_runtime = object()
        monkeypatch.setattr(session_manager, 'get_worker_session', lambda _sid: {'id': _sid, 'worker_id': 'code-agent-1', 'model_override': None})
        monkeypatch.setattr(services, '_find_agent_os_worker', lambda _os, _wid, _wt: shared_runtime)

        runtime = await services._resolve_runtime_for_session(worker, 'code-agent-1:abc', agent_os=SimpleNamespace())
        assert runtime is shared_runtime
        assert 'code-agent-1:abc' not in services._SESSION_RUNTIME_CACHE

    async def test_override_runtime_is_cached_by_session(self, monkeypatch):
        worker = {'id': 'code-agent-1', 'type': 'Agent'}
        built = []

        monkeypatch.setattr(session_manager, 'get_worker_session', lambda _sid: {'id': _sid, 'worker_id': 'code-agent-1', 'model_override': 'openai/gpt-4.1'})

        async def fake_build(_worker, model_ref, _agent_os):
            runtime = SimpleNamespace(model_ref=model_ref, marker=len(built) + 1)
            built.append(runtime)
            return runtime

        monkeypatch.setattr(services, '_build_runtime_for_session', fake_build)

        first = await services._resolve_runtime_for_session(worker, 'code-agent-1:abc', agent_os=SimpleNamespace())
        second = await services._resolve_runtime_for_session(worker, 'code-agent-1:abc', agent_os=SimpleNamespace())

        assert first is second
        assert len(built) == 1
        assert services._SESSION_RUNTIME_CACHE['code-agent-1:abc'].model_ref == 'openai/gpt-4.1'

    async def test_update_session_clears_cached_override_runtime(self, monkeypatch):
        ws = session_manager.create_worker_session('code-agent-1', title='cache test')
        session_id = ws['id']
        services._SESSION_RUNTIME_CACHE[session_id] = services.SessionRuntimeEntry(
            worker_id='code-agent-1',
            worker_type='Agent',
            model_ref='openai/gpt-4.1',
            runtime=SimpleNamespace(name='cached'),
            created_at=1.0,
            last_used_at=1.0,
        )

        monkeypatch.setattr(services.repository, 'get_worker', lambda _wid: {'id': 'code-agent-1', 'type': 'Agent', 'name': 'Code Agent'})

        updated = services.update_session(session_id, {'modelOverride': 'qwen/qwen-max'}, agent_os=None)
        assert updated is not None
        assert updated['modelOverride'] == 'qwen/qwen-max'
        assert session_id not in services._SESSION_RUNTIME_CACHE

    async def test_create_message_uses_override_runtime(self, monkeypatch):
        ws = session_manager.create_worker_session('code-agent-1', title='msg test')
        session_id = ws['id']
        worker = {'id': 'code-agent-1', 'type': 'Agent', 'name': 'Code Agent'}
        dedicated_runtime = SimpleNamespace(
            arun=None,
            run=True,
            get_session=lambda session_id=None: SimpleNamespace(session_data={})
        )

        monkeypatch.setattr(services.repository, 'get_worker', lambda _wid: worker)
        monkeypatch.setattr(services, '_resolve_worker_id', lambda _sid, _os: 'code-agent-1')
        monkeypatch.setattr(services, '_resolve_runtime_for_session', lambda _worker, _sid, _os: asyncio.sleep(0, result=dedicated_runtime))
        monkeypatch.setattr(services, '_build_media_kwargs', lambda *_args, **_kwargs: ({}, []))

        async def fake_run_worker(_worker, _message, **kwargs):
            assert kwargs['runtime_worker'] is dedicated_runtime
            return {'content': 'ok', 'tokenInput': 1, 'tokenOutput': 1, 'toolCalls': [], 'reasoning': ''}

        monkeypatch.setattr(services, 'run_worker', fake_run_worker)

        result = await services.create_message(session_id, 'hello', agent_os=SimpleNamespace())
        assert result['workerMessage']['content'] == 'ok'
