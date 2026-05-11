import dataclasses
import json
import logging
import time
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse

from app.schemas import MessageCreatePayload, SchedulePayload, SessionCreatePayload, SessionUpdatePayload, WorkerCreatePayload, WorkerUpdatePayload
from app.schedules import create_schedule, delete_schedule, get_schedule, list_schedule_runs, list_schedules, schedule_manager, update_schedule
from app.channels.manager import ChannelManager
from app.services import (
    _resolve_worker_id,
    cancel_run,
    check_mcp_status,
    clone_session,
    create_message,
    create_provider,
    create_session,
    create_worker,
    update_session,
    delete_provider,
    delete_skill,
    fetch_remote_models,
    get_skill,
    get_worker,
    install_skill,
    list_messages,
    list_mcp_servers,
    list_models,
    list_sessions,
    list_skill_files,
    list_skills,
    list_tools_catalog,
    list_workers,
    read_skill_file,
    save_mcp_servers,
    set_default_model,
    stream_message,
    test_mcp_connection,
    update_provider,
    update_worker,
    get_user_profile_content,
    get_user_memory_content,
    get_session_context_content,
    get_entity_memory_content,
    get_decision_log_content,
    update_user_memory_content,
    delete_user_memory_content,
    add_user_memory_content,
    read_log_file,
    # Session Compaction
    list_compaction_sessions,
    create_compaction_session,
    get_compaction_session,
    get_session_segments,
    export_session_context,
    get_session_config_info,
    update_session_config_info,
    trigger_manual_compaction,
)

logger = logging.getLogger('nowork')


@asynccontextmanager
async def lifespan(application: FastAPI):
    from app.config import get_workers_config
    from app.runtime import build_agent_os
    from app import session_manager
    try:
        workers = get_workers_config()
        application.state.agent_os = await build_agent_os(workers, base_app=application)
        logger.info('AgentOS initialized with %d worker(s)', len(workers))
    except Exception as e:
        logger.exception('Failed to initialize AgentOS: %s', e)
        application.state.agent_os = None
    # Initialize session compaction DB on startup
    try:
        session_manager.ensure_db()
        logger.info('Session compaction DB initialized')
    except Exception as e:
        logger.warning('Failed to initialize session DB: %s', e)
    # Initialize ChannelManager
    channel_manager = ChannelManager()
    application.state.channel_manager = channel_manager
    try:
        await channel_manager.start_all(application.state.agent_os)
    except Exception as e:
        logger.warning('Failed to start channels: %s', e)
    await schedule_manager.start(getattr(application.state, 'agent_os', None))
    try:
        yield
    finally:
        await channel_manager.stop_all()
        await schedule_manager.stop()


app = FastAPI(title='nowork-server', lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_methods=['*'],
    allow_headers=['*'],
)


def _get_agent_os(request: Request):
    return getattr(request.app.state, 'agent_os', None)


@app.get('/health')
def health() -> dict[str, object]:
    return {
        'status': 'ok',
        'service': 'nowork-server',
        'version': '0.1.0',
    }


@app.get('/api/workers')
def api_list_workers(type: str | None = None, request: Request = None) -> list[dict[str, object]]:
    return list_workers(type, agent_os=_get_agent_os(request))


@app.get('/api/workers/{worker_id}')
def api_get_worker(worker_id: str) -> dict[str, object]:
    result = get_worker(worker_id)
    if result:
        result.pop('_raw', None)
    return result


@app.post('/api/workers', status_code=201)
async def api_create_worker(payload: WorkerCreatePayload, request: Request) -> dict[str, object]:
    try:
        result = create_worker(payload.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        logger.exception('create_worker failed: %s', e)
        raise HTTPException(status_code=500, detail=f'create_worker error: {type(e).__name__}: {e}')

    logger.info('create_worker returned: id=%s', result.get('id'))

    # Strip internal fields before any further processing
    result.pop('_raw', None)

    agent_os = _get_agent_os(request)
    if agent_os is not None:
        import asyncio
        async def _bg_add():
            try:
                from app.runtime import add_worker_to_os
                await add_worker_to_os(agent_os, result['id'])
                logger.info('Worker %s added to agent_os', result['id'])
            except Exception as e:
                logger.warning('Failed to add worker %s to agent_os: %s', result['id'], e)
        asyncio.create_task(_bg_add())

    logger.info('api_create_worker returning id=%s', result.get('id'))
    return result


@staticmethod


@app.put('/api/workers/{worker_id}')
async def api_update_worker(worker_id: str, payload: WorkerUpdatePayload, request: Request) -> dict[str, object]:
    result = update_worker(worker_id, payload.model_dump())
    result.pop('_raw', None)
    agent_os = _get_agent_os(request)
    if agent_os is not None:
        try:
            from app.runtime import reload_worker
            await reload_worker(agent_os, worker_id, result.get('type', 'Agent'))
            logger.info('Worker %s hot-reloaded in agent_os', worker_id)
        except Exception as e:
            logger.warning('Failed to hot-reload worker %s: %s', worker_id, e)
    return result


@app.get('/api/workers/{worker_id}/sessions')
def api_list_sessions(worker_id: str, request: Request) -> list[dict[str, object]]:
    return list_sessions(worker_id, agent_os=_get_agent_os(request))


@app.post('/api/workers/{worker_id}/sessions', status_code=201)
def api_create_session(worker_id: str, payload: SessionCreatePayload, request: Request) -> dict[str, object]:
    return create_session(worker_id, payload.title, workspaces=payload.workspaces, agent_os=_get_agent_os(request))


@app.put('/api/sessions/{session_id}')
def api_update_session(session_id: str, payload: SessionUpdatePayload, request: Request) -> dict[str, object]:
    result = update_session(session_id, payload.model_dump(exclude_unset=True), agent_os=_get_agent_os(request))
    if result is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail='Session not found')
    return result


@app.post('/api/sessions/{session_id}/clone', status_code=201)
def api_clone_session(session_id: str, request: Request, clone_from_run: int | None = Query(default=None)) -> dict[str, object]:
    """Clone a session. Optionally truncate to a specific run index.

    Query params:
        clone_from_run: Run index to truncate to (inclusive). If not set, clone all runs.
    """
    return clone_session(session_id, clone_from_run=clone_from_run, agent_os=_get_agent_os(request))


@app.get('/api/sessions/{session_id}/messages')
def api_list_messages(session_id: str, limit: int = 20, offset: int = 0, request: Request = None) -> dict[str, object]:
    return list_messages(session_id, limit=limit, offset=offset, agent_os=_get_agent_os(request))


@app.get('/api/debug/session-db')
def api_debug_session_db():
    """Debug: check session_manager engine and DB state."""
    from app.session_manager import _engine, _SessionLocal, get_db_session, WorkerSessionRow, _get_db_path
    
    return {
        'engine': str(_engine),
        'session_factory': str(_SessionLocal),
        'db_path': str(_get_db_path()),
        'can_create': True,
    }


@app.get('/api/sessions/{session_id}/export-context')
def api_export_context(session_id: str, request: Request):
    """Export session's full LLM context as Markdown for debugging."""
    return Response(
        content=export_session_context(session_id, agent_os=_get_agent_os(request)),
        media_type='text/markdown',
        headers={'Content-Disposition': f'attachment; filename="session-{session_id}-context.md"'},
    )


@app.post('/api/sessions/{session_id}/messages', status_code=201)
async def api_create_message(session_id: str, payload: MessageCreatePayload, request: Request):
    agent_os = _get_agent_os(request)
    worker_id = _resolve_worker_id(session_id, agent_os)
    if worker_id is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail='Session not found')
    worker = get_worker(worker_id)

    attachments = [item.model_dump() for item in payload.attachments]

    if worker['type'] in ('Agent', 'Team'):
        return StreamingResponse(
            stream_message(session_id, payload.content, attachments, agent_os),
            media_type='text/event-stream',
            headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'},
        )

    return await create_message(session_id, payload.content, attachments=attachments, agent_os=agent_os)


@app.post('/api/runs/{run_id}/cancel')
async def api_cancel_run(run_id: str):
    cancelled = await cancel_run(run_id)
    return {'ok': cancelled, 'run_id': run_id}


@app.post('/api/runs/{run_id}/continue')
async def api_continue_run(run_id: str, request: Request):
    """Continue a paused run after user approval for a write operation outside base_dirs.

    Body: {
        "confirmed": true/false,
        "always_allow_dir": "/path/to/dir" (optional — remember this dir for the session),
        "session_id": "..." (required if always_allow_dir is set),
        "worker_id": "..." (required),
        "updated_tools": [{"toolCallId": "...", "toolName": "...", "toolArgs": {...}, "requiresConfirmation": true}]
    }
    Returns: the continue_run result (for non-streaming response).
    For streaming, use the /api/runs/{run_id}/continue/stream endpoint.
    """
    body = await request.json()
    confirmed = body.get('confirmed', False)
    always_allow_dir = body.get('always_allow_dir')
    session_id = body.get('session_id')

    # If user chose "always allow", record the directory via ApprovalManager
    if confirmed and always_allow_dir and session_id:
        from app.approval import approval_manager
        approval_manager.approve_dir(session_id, always_allow_dir)

    agent_os = getattr(request.app.state, 'agent_os', None)
    if agent_os is None:
        raise HTTPException(status_code=503, detail='Agent OS not available')

    from agno.models.response import ToolExecution
    from app.services import _resolve_runtime_agent, repository

    worker_id = body.get('worker_id')
    if not worker_id:
        raise HTTPException(status_code=400, detail='worker_id is required')

    worker = repository.get_worker(worker_id)
    if worker is None:
        raise HTTPException(status_code=404, detail='Worker not found')

    runtime = _resolve_runtime_agent(worker_id, agent_os)
    if runtime is None:
        raise HTTPException(status_code=404, detail='Runtime not found')

    # Build updated_tools with confirmed flag
    updated_tools_data = body.get('updated_tools', [])
    updated_tools = []
    for ut in updated_tools_data:
        te = ToolExecution(
            tool_call_id=ut.get('toolCallId'),
            tool_name=ut.get('toolName'),
            tool_args=ut.get('toolArgs'),
            confirmed=confirmed if ut.get('requiresConfirmation') else None,
            requires_confirmation=ut.get('requiresConfirmation', False),
        )
        updated_tools.append(te)

    try:
        # Resolve worker_session_id → agno_session_id (same as stream_continue_run)
        agno_session_id = session_id
        if session_id is not None:
            from app.session_manager import resolve_segment
            segment = resolve_segment(session_id)
            if segment is not None:
                agno_session_id = segment['agno_session_id']

        result = await runtime.acontinue_run(
            run_id=run_id,
            session_id=agno_session_id,
            updated_tools=updated_tools if updated_tools else None,
        )
        return {'ok': True, 'run_id': run_id, 'status': getattr(result, 'status', 'unknown')}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'continue_run failed: {str(e)}')


@app.post('/api/runs/{run_id}/continue/stream')
async def api_continue_run_stream(run_id: str, request: Request):
    """Continue a paused run and stream the results via SSE.

    Body: same as /api/runs/{run_id}/continue.
    """
    body = await request.json()
    confirmed = body.get('confirmed', False)
    always_allow_dir = body.get('always_allow_dir')
    session_id = body.get('session_id')

    if confirmed and always_allow_dir and session_id:
        from app.approval import approval_manager
        approval_manager.approve_dir(session_id, always_allow_dir)

    agent_os = getattr(request.app.state, 'agent_os', None)
    if agent_os is None:
        raise HTTPException(status_code=503, detail='Agent OS not available')

    from agno.models.response import ToolExecution
    from app.services import _resolve_runtime_agent, repository

    worker_id = body.get('worker_id')
    if not worker_id:
        raise HTTPException(status_code=400, detail='worker_id is required')

    worker = repository.get_worker(worker_id)
    if worker is None:
        raise HTTPException(status_code=404, detail='Worker not found')

    runtime = _resolve_runtime_agent(worker_id, agent_os)
    if runtime is None:
        raise HTTPException(status_code=404, detail='Runtime not found')

    updated_tools_data = body.get('updated_tools', [])
    updated_tools = []
    for ut in updated_tools_data:
        te = ToolExecution(
            tool_call_id=ut.get('toolCallId'),
            tool_name=ut.get('toolName'),
            tool_args=ut.get('toolArgs'),
            confirmed=confirmed if ut.get('requiresConfirmation') else None,
            requires_confirmation=ut.get('requiresConfirmation', False),
        )
        updated_tools.append(te)

    from app.services import stream_continue_run
    return StreamingResponse(
        stream_continue_run(run_id, runtime, updated_tools, worker, session_id),
        media_type='text/event-stream',
        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'},
    )


@app.get('/api/schedules')
def api_list_schedules() -> list[dict[str, object]]:
    return list_schedules()


@app.post('/api/schedules', status_code=201)
def api_create_schedule(payload: SchedulePayload) -> dict[str, object]:
    return create_schedule(payload.model_dump())


@app.get('/api/schedules/{schedule_id}')
def api_get_schedule(schedule_id: str) -> dict[str, object]:
    result = get_schedule(schedule_id)
    if result is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail='Schedule not found')
    return result


@app.put('/api/schedules/{schedule_id}')
def api_update_schedule(schedule_id: str, payload: SchedulePayload) -> dict[str, object]:
    result = update_schedule(schedule_id, payload.model_dump())
    if result is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail='Schedule not found')
    return result


@app.delete('/api/schedules/{schedule_id}')
def api_delete_schedule(schedule_id: str) -> dict[str, object]:
    deleted = delete_schedule(schedule_id)
    if not deleted:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail='Schedule not found')
    return {'ok': True, 'id': schedule_id}


@app.post('/api/schedules/{schedule_id}/run')
async def api_run_schedule(schedule_id: str) -> dict[str, object]:
    return await schedule_manager.run_schedule(schedule_id)


@app.get('/api/schedules/{schedule_id}/runs')
def api_list_schedule_runs(schedule_id: str, limit: int = 20) -> list[dict[str, object]]:
    return list_schedule_runs(schedule_id, limit=limit)


@app.get('/api/skills')
def api_list_skills() -> list[dict[str, object]]:
    return list_skills()


@app.get('/api/models')
def api_list_models() -> dict[str, object]:
    return list_models()


@app.post('/api/providers', status_code=201)
async def api_create_provider(request: Request):
    body = await request.json()
    try:
        return create_provider(body)
    except ValueError as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=str(e))


@app.put('/api/providers/{provider_id}')
async def api_update_provider(provider_id: str, request: Request):
    body = await request.json()
    result = update_provider(provider_id, body)
    if result is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail='Provider not found')
    return result


@app.delete('/api/providers/{provider_id}')
def api_delete_provider(provider_id: str):
    return delete_provider(provider_id)


@app.put('/api/default-model')
async def api_set_default_model(request: Request):
    body = await request.json()
    model_id = body.get('model', '')
    if not model_id:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail='model is required')
    return set_default_model(model_id)


@app.get('/api/logs')
def api_read_logs(lines: int = 200, offset: int = 0, file: str | None = None):
    return read_log_file(lines=lines, offset=offset, file_name=file)


@app.post('/api/providers/fetch-models')
async def api_fetch_remote_models(request: Request):
    body = await request.json()
    base_url = body.get('baseUrl', '').rstrip('/')
    api_key = body.get('apiKey')
    if not base_url:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail='baseUrl is required')
    models = fetch_remote_models(base_url, api_key)
    return {'models': models}


@app.get('/api/tools-catalog')
def api_list_tools_catalog() -> list[dict[str, object]]:
    return list_tools_catalog()


@app.get('/api/mcp')
async def api_list_mcp_servers() -> list[dict[str, object]]:
    servers = list_mcp_servers()
    return await check_mcp_status(servers)


@app.put('/api/mcp')
async def api_save_mcp_servers(request: Request):
    body = await request.json()
    servers = body.get('servers', [])
    return save_mcp_servers(servers)


@app.post('/api/mcp/test')
async def api_test_mcp_connection(request: Request):
    body = await request.json()
    return await test_mcp_connection(body)


@app.get('/api/skills/{skill_name}')
def api_get_skill(skill_name: str) -> dict[str, object]:
    skill = get_skill(skill_name)
    if skill is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail='Skill not found')
    return skill


@app.get('/api/skills/{skill_name}/files/{file_path:path}')
def api_read_skill_file(skill_name: str, file_path: str):
    content = read_skill_file(skill_name, file_path)
    if content is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail='File not found')
    return {'content': content}


@app.get('/api/skills/{skill_name}/tree')
def api_list_skill_files(skill_name: str):
    files = list_skill_files(skill_name)
    if files is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail='Skill not found')
    return files


@app.post('/api/skills/install')
async def api_install_skill(request: Request):
    body = await request.json()
    source = body.get('source', '')
    overwrite = body.get('overwrite', False)
    if not source:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail='source is required')
    return install_skill(source.strip(), overwrite=overwrite)


@app.delete('/api/skills/{skill_name}')
def api_delete_skill(skill_name: str):
    result = delete_skill(skill_name)
    if not result['ok']:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=result.get('error', 'Skill not found'))
    return result


# =============================================================================
# Learning Content APIs
# =============================================================================


@app.get('/api/workers/{worker_id}/learning/user-profile')
def api_get_user_profile(worker_id: str, user_id: str, request: Request) -> dict[str, object]:
    return get_user_profile_content(worker_id, user_id, agent_os=_get_agent_os(request))


@app.get('/api/workers/{worker_id}/learning/user-memory')
def api_get_user_memory(worker_id: str, user_id: str, request: Request) -> dict[str, object]:
    return get_user_memory_content(worker_id, user_id, agent_os=_get_agent_os(request))


@app.post('/api/workers/{worker_id}/learning/user-memory')
async def api_add_user_memory(worker_id: str, user_id: str, request: Request) -> dict[str, object]:
    body = await request.json()
    memory_content = body.get('memory', '')
    if not memory_content:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail='memory content is required')
    return add_user_memory_content(worker_id, user_id, memory_content, agent_os=_get_agent_os(request))


@app.put('/api/workers/{worker_id}/learning/user-memory/{memory_id}')
async def api_update_user_memory(worker_id: str, memory_id: str, request: Request) -> dict[str, object]:
    body = await request.json()
    content = body.get('memory', '')
    if not content:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail='memory content is required')
    return update_user_memory_content(worker_id, memory_id, content, agent_os=_get_agent_os(request))


@app.delete('/api/workers/{worker_id}/learning/user-memory/{memory_id}')
def api_delete_user_memory(worker_id: str, memory_id: str, request: Request, user_id: str | None = None) -> dict[str, object]:
    return delete_user_memory_content(worker_id, memory_id, user_id, agent_os=_get_agent_os(request))


@app.get('/api/workers/{worker_id}/learning/session-context')
def api_get_session_context(worker_id: str, session_id: str, request: Request) -> dict[str, object]:
    return get_session_context_content(worker_id, session_id, agent_os=_get_agent_os(request))


@app.get('/api/workers/{worker_id}/learning/entity-memory')
def api_get_entity_memory(worker_id: str, request: Request, entity_id: str | None = None, entity_type: str | None = None) -> dict[str, object]:
    return get_entity_memory_content(worker_id, entity_id, entity_type, agent_os=_get_agent_os(request))


@app.get('/api/workers/{worker_id}/learning/decision-log')
def api_get_decision_log(worker_id: str, request: Request, session_id: str | None = None) -> dict[str, object]:
    return get_decision_log_content(worker_id, session_id, agent_os=_get_agent_os(request))


from app.knowledge_repo import (
    list_knowledge_bases as _list_kb,
    get_knowledge_base as _get_kb,
    create_knowledge as _create_kb,
    update_knowledge as _update_kb,
    delete_knowledge as _delete_kb,
)


def _get_kb_language(kb_id: str) -> str | None:
    """Read the 'language' field from the knowledge base's raw config."""
    kb = _get_kb(kb_id)
    if kb is None:
        return None
    raw = kb.get('_raw', kb)
    return raw.get('language') or None


@app.get('/api/knowledge')
def api_list_knowledge() -> list[dict[str, object]]:
    return _list_kb()


@app.get('/api/knowledge/{knowledge_id}')
def api_get_knowledge(knowledge_id: str) -> dict[str, object] | None:
    kb = _get_kb(knowledge_id)
    if kb is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail='Knowledge base not found')
    return kb


@app.post('/api/knowledge', status_code=201)
async def api_create_knowledge(request: Request) -> dict[str, object]:
    body = await request.json()
    result = _create_kb(body)
    logger.info('Knowledge %s created', result['id'])
    return result


@app.put('/api/knowledge/{knowledge_id}')
async def api_update_knowledge(knowledge_id: str, request: Request) -> dict[str, object]:
    body = await request.json()
    result = _update_kb(knowledge_id, body)
    if result is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail='Knowledge base not found')
    return result


@app.delete('/api/knowledge/{knowledge_id}')
def api_delete_knowledge(knowledge_id: str) -> dict[str, object]:
    ok = _delete_kb(knowledge_id)
    if not ok:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail='Knowledge base not found')
    return {'ok': True, 'id': knowledge_id}


@app.post('/api/knowledge/{knowledge_id}/reload')
async def api_reload_knowledge(knowledge_id: str, request: Request) -> dict[str, object]:
    from app.knowledge_repo import get_knowledge_base
    kb = get_knowledge_base(knowledge_id)
    if kb is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail='Knowledge base not found')

    raw = kb.get('_raw', kb)
    try:
        from app.runtime import _build_single_knowledge
        _build_single_knowledge(raw)
        return {'ok': True, 'id': knowledge_id}
    except Exception as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# Wiki Knowledge APIs
# =============================================================================

from app.wiki.repo import WikiRepository as _WikiRepo
from app.wiki.search import tokenized_search as _tokenized_search
from app.wiki.lint import lint_knowledge_base as _lint_kb
from app.wiki.graph import build_graph as _build_graph


def _get_wiki_repo(knowledge_id: str) -> _WikiRepo:
    """获取 Wiki 仓库，验证知识库存在。"""
    kb = _get_kb(knowledge_id)
    if kb is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail='Knowledge base not found')
    if not kb.get('wiki_mode', False):
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail='Knowledge base is not in wiki mode')
    repo = _WikiRepo(knowledge_id)
    repo.ensure_structure()
    return repo


@app.post('/api/knowledge/{knowledge_id}/sync')
async def api_sync_knowledge(knowledge_id: str, request: Request):
    """同步知识库的所有关联目录。"""
    kb = _get_kb(knowledge_id)
    if kb is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail='Knowledge base not found')

    from app.config import get_default_model_id
    from app.runtime import _build_model

    try:
        model_ref = kb.get('_raw', kb).get('model')
        if not model_ref:
            try:
                model_ref = get_default_model_id()
            except ValueError:
                from fastapi import HTTPException
                raise HTTPException(status_code=400, detail='No default model configured')
        model = _build_model(model_ref)
        if model is None:
            from fastapi import HTTPException
            raise HTTPException(status_code=400, detail='Failed to build model')
    except Exception as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=f'Model error: {e}')

    from app.wiki.ingest import sync_knowledge_base, SyncCancelled
    try:
        written = await sync_knowledge_base(knowledge_id, model)
    except SyncCancelled:
        # Pages already ingested are kept on disk — just report cancellation.
        # Frontend will reload wiki data to reflect the partial results.
        return {'ok': True, 'id': knowledge_id, 'cancelled': True}
    except ValueError as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=409, detail=str(e))
    return {'ok': True, 'id': knowledge_id, 'pages_written': len(written), 'pages': written}


@app.get('/api/knowledge/{knowledge_id}/sync/status')
async def api_sync_status(knowledge_id: str):
    """Check whether a sync is currently in progress."""
    from app.wiki.ingest import _active_sync
    return {'syncing': knowledge_id in _active_sync, 'id': knowledge_id}


@app.post('/api/knowledge/{knowledge_id}/sync/cancel')
async def api_cancel_sync(knowledge_id: str):
    """Cancel a running sync."""
    from app.wiki.ingest import request_sync_cancel
    request_sync_cancel(knowledge_id)
    return {'ok': True, 'id': knowledge_id}


@app.post('/api/knowledge/{knowledge_id}/ingest')
async def api_ingest_knowledge(knowledge_id: str, request: Request):
    """手动 Ingest 指定文件列表。"""
    body = await request.json()
    files = body.get('files', [])
    force = body.get('force', False)

    if not files:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail='files list is required')

    from app.config import get_default_model_id
    from app.runtime import _build_model
    from app.wiki.ingest import ingest_file

    try:
        model_ref = None
        try:
            model_ref = get_default_model_id()
        except ValueError:
            pass
        model = _build_model(model_ref) if model_ref else None
        if model is None:
            from fastapi import HTTPException
            raise HTTPException(status_code=400, detail='No model available for ingest')
    except Exception as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=f'Model error: {e}')

    all_written: list[str] = []
    for f in files:
        written = await ingest_file(knowledge_id, f, model, force=force, locale=_get_kb_language(knowledge_id))
        all_written.extend(written)

    return {'ok': True, 'id': knowledge_id, 'pages_written': len(all_written), 'pages': all_written}


@app.get('/api/knowledge/{knowledge_id}/wiki/pages')
def api_list_wiki_pages(knowledge_id: str, type: str = '', search: str = ''):
    repo = _get_wiki_repo(knowledge_id)
    pages = repo.list_pages(category=type, search=search)
    return pages


@app.get('/api/knowledge/{knowledge_id}/wiki/page/{page_path:path}')
def api_read_wiki_page(knowledge_id: str, page_path: str):
    repo = _get_wiki_repo(knowledge_id)
    page = repo.read_page(f'wiki/{page_path}' if not page_path.startswith('wiki/') else page_path)
    if page is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail='Page not found')
    return page


@app.put('/api/knowledge/{knowledge_id}/wiki/page/{page_path:path}')
async def api_write_wiki_page(knowledge_id: str, page_path: str, request: Request):
    repo = _get_wiki_repo(knowledge_id)
    body = await request.json()
    content = body.get('content', '')

    full_path = f'wiki/{page_path}' if not page_path.startswith('wiki/') else page_path
    ok = repo.write_page(full_path, content)
    if not ok:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail='Failed to write page (invalid path?)')
    repo.bump_version()
    return {'ok': True, 'path': full_path}


@app.delete('/api/knowledge/{knowledge_id}/wiki/page/{page_path:path}')
def api_delete_wiki_page(knowledge_id: str, page_path: str):
    repo = _get_wiki_repo(knowledge_id)
    full_path = f'wiki/{page_path}' if not page_path.startswith('wiki/') else page_path
    ok = repo.delete_page(full_path)
    if not ok:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail='Page not found')
    repo.bump_version()
    return {'ok': True, 'path': full_path}


@app.post('/api/knowledge/{knowledge_id}/wiki/search')
async def api_search_wiki(knowledge_id: str, request: Request):
    body = {}
    try:
        body = await request.json() if request.headers.get('content-type', '').startswith('application/json') else {}
    except Exception:
        pass

    query = body.get('query', '') if isinstance(body, dict) else ''
    max_results = body.get('max_results', 20) if isinstance(body, dict) else 20

    if not query:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail='query is required')

    _get_wiki_repo(knowledge_id)  # 验证 kb 存在
    results = _tokenized_search(knowledge_id, query, max_results)
    return results


@app.get('/api/knowledge/{knowledge_id}/wiki/stats')
def api_wiki_stats(knowledge_id: str):
    repo = _get_wiki_repo(knowledge_id)
    return repo.get_stats()


@app.post('/api/knowledge/{knowledge_id}/wiki/lint')
def api_lint_wiki(knowledge_id: str):
    _get_wiki_repo(knowledge_id)
    result = _lint_kb(knowledge_id)
    return result.to_dict()


@app.get('/api/knowledge/{knowledge_id}/wiki/graph')
def api_wiki_graph(knowledge_id: str):
    _get_wiki_repo(knowledge_id)
    return _build_graph(knowledge_id)


from app.extensions import list_extensions as _list_ext, get_extension as _get_ext, install_extension as _install_ext, uninstall_extension as _uninstall_ext


@app.get('/api/extensions')
def api_list_extensions() -> list[dict[str, object]]:
    return _list_ext()


@app.get('/api/extensions/{ext_id}')
def api_get_extension(ext_id: str) -> dict[str, object]:
    ext = _get_ext(ext_id)
    if ext is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail='Extension not found')
    return ext


@app.post('/api/extensions/{ext_id}/install')
async def api_install_extension(ext_id: str) -> dict[str, object]:
    import asyncio
    result = await asyncio.get_event_loop().run_in_executor(None, _install_ext, ext_id)
    if not result['ok']:
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail=result['error'])
    return result


@app.post('/api/extensions/{ext_id}/uninstall')
async def api_uninstall_extension(ext_id: str) -> dict[str, object]:
    import asyncio
    result = await asyncio.get_event_loop().run_in_executor(None, _uninstall_ext, ext_id)
    if not result['ok']:
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail=result['error'])
    return result


# =============================================================================
# Agent Types & Prerequisites
# =============================================================================

@app.get('/api/agent-types')
def api_list_agent_types() -> list[dict[str, object]]:
    from app.agent_types import get_agent_types
    return get_agent_types()


@app.get('/api/prerequisites/{agent_type}')
def api_check_prerequisites(agent_type: str) -> dict[str, object]:
    from app.prerequisites import check_prerequisites
    result = check_prerequisites(agent_type)
    return result


@app.post('/api/prerequisites/install')
async def api_install_prerequisite(payload: dict[str, object]):
    from app.prerequisites import stream_install
    command = payload.get('command', '')
    if not command or not isinstance(command, str):
        raise HTTPException(status_code=400, detail='command is required')

    # Allowlist: only npm install, winget install, brew install
    allowed_prefixes = ('npm install', 'winget install', 'brew install', 'curl ')
    if not any(command.strip().startswith(p) for p in allowed_prefixes):
        raise HTTPException(status_code=400, detail='Command not allowed')

    return StreamingResponse(
        stream_install(command),
        media_type='text/event-stream',
        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'},
    )


# =============================================================================
# Session Compaction APIs
# =============================================================================


@app.post('/api/translate')
async def api_translate(payload: dict[str, object]):
    """Translate text using the configured LLM."""
    text = payload.get('text', '')
    target_lang = payload.get('target_lang', 'zh-CN')
    if not text or not isinstance(text, str):
        raise HTTPException(status_code=400, detail='text is required')

    lang_map = {'zh-CN': 'Chinese', 'en': 'English', 'ja': 'Japanese', 'ko': 'Korean'}
    target_name = lang_map.get(target_lang, target_lang)

    try:
        from agno.models.openai import OpenAIChat
        from app.config import get_full_model_config

        model_cfg = get_full_model_config()
        model = OpenAIChat(
            id=model_cfg.get('model_id', 'gpt-4o-mini'),
            api_key=model_cfg.get('api_key', ''),
            base_url=model_cfg.get('base_url'),
        )

        prompt = (
            f'Translate the following text to {target_name}. '
            f'Output ONLY the translation, no explanations, no quotes.\n\n{text}'
        )

        response = await model.ainvoke(prompt)
        translated = response.strip() if response else text
        return {'translated': translated}
    except Exception as e:
        logger.warning('Translation failed: %s', e)
        raise HTTPException(status_code=500, detail=f'Translation failed: {e}')


# =============================================================================
# Session Compaction APIs
# =============================================================================


@app.get('/api/session-config')
def api_get_session_config() -> dict[str, object]:
    return get_session_config_info()


@app.put('/api/session-config')
def api_update_session_config(payload: dict[str, object]) -> dict[str, object]:
    return update_session_config_info(payload)


@app.get('/api/workers/{worker_id}/compaction-sessions')
def api_list_compaction_sessions(worker_id: str) -> list[dict[str, object]]:
    return list_compaction_sessions(worker_id)


@app.post('/api/workers/{worker_id}/compaction-sessions', status_code=201)
async def api_create_compaction_session(worker_id: str, request: Request) -> dict[str, object]:
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    title = body.get('title', '') if isinstance(body, dict) else ''
    return create_compaction_session(worker_id, title)


@app.get('/api/compaction-sessions/{ws_id}')
def api_get_compaction_session(ws_id: str) -> dict[str, object]:
    result = get_compaction_session(ws_id)
    if result is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail='WorkerSession not found')
    return result


@app.get('/api/compaction-sessions/{ws_id}/segments')
def api_get_session_segments(ws_id: str) -> list[dict[str, object]]:
    return get_session_segments(ws_id)


@app.post('/api/compaction-sessions/{ws_id}/compact')
async def api_trigger_compaction(ws_id: str, request: Request) -> dict[str, object]:
    return await trigger_manual_compaction(ws_id, agent_os=_get_agent_os(request))


from app.channels_api import router as channels_router
app.include_router(channels_router)

from app.fs_api import router as fs_router
app.include_router(fs_router)


class LogRequestsMiddleware:
    """Pure ASGI middleware for request logging and exception handling.

    Replaces the previous @app.middleware('http') + @app.exception_handler approach,
    which caused Starlette's BaseHTTPMiddleware to raise RuntimeError('No response returned.')
    whenever the exception_handler caught an error — because BaseHTTPMiddleware.call_next()
    cannot see responses produced by exception handlers.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] not in ('http', 'websocket'):
            await self.app(scope, receive, send)
            return

        start = time.time()
        path = scope.get('path', '')
        method = scope.get('method', '')
        status_holder = {'status': 0}

        async def send_wrapper(message):
            if message['type'] == 'http.response.start':
                status_holder['status'] = message.get('status', 0)
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception as exc:
            status_holder['status'] = 500
            logger.exception('Unhandled exception on %s %s: %s', method, path, exc)
            body = json.dumps({'detail': 'Internal server error'}).encode('utf-8')
            await send({'type': 'http.response.start', 'status': 500,
                        'headers': [[b'content-type', b'application/json'],
                                    [b'content-length', str(len(body)).encode()]]})
            await send({'type': 'http.response.body', 'body': body})

        elapsed = (time.time() - start) * 1000
        if path.startswith('/api/'):
            logger.info('%s %s %d %.0fms', method, path, status_holder['status'], elapsed)


app.add_middleware(LogRequestsMiddleware)
