import dataclasses
import json
import logging
import time
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from app.schemas import MessageCreatePayload, SchedulePayload, SessionCreatePayload, SessionUpdatePayload, WorkerCreatePayload, WorkerUpdatePayload
from app.schedules import create_schedule, delete_schedule, get_schedule, list_schedule_runs, list_schedules, schedule_manager, update_schedule
from app.services import (
    _resolve_worker_id,
    cancel_run,
    check_mcp_status,
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
)

logger = logging.getLogger('nowork')


@asynccontextmanager
async def lifespan(application: FastAPI):
    from app.config import get_workers_config
    from app.runtime import build_agent_os
    try:
        workers = get_workers_config()
        application.state.agent_os = await build_agent_os(workers, base_app=application)
        logger.info('AgentOS initialized with %d worker(s)', len(workers))
    except Exception as e:
        logger.exception('Failed to initialize AgentOS: %s', e)
        application.state.agent_os = None
    await schedule_manager.start(getattr(application.state, 'agent_os', None))
    try:
        yield
    finally:
        await schedule_manager.stop()


app = FastAPI(title='nowork-server', lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=['http://localhost:5173'],
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
def api_list_workers(type: str | None = None) -> list[dict[str, object]]:
    return list_workers(type)


@app.get('/api/workers/{worker_id}')
def api_get_worker(worker_id: str) -> dict[str, object]:
    return get_worker(worker_id)


@app.post('/api/workers', status_code=201)
async def api_create_worker(payload: WorkerCreatePayload, request: Request) -> dict[str, object]:
    result = create_worker(payload.model_dump())
    agent_os = _get_agent_os(request)
    if agent_os is not None:
        try:
            from app.runtime import add_worker_to_os
            await add_worker_to_os(agent_os, result['id'])
            logger.info('Worker %s added to agent_os', result['id'])
        except Exception as e:
            logger.warning('Failed to add worker %s to agent_os: %s', result['id'], e)
    return result


@app.put('/api/workers/{worker_id}')
async def api_update_worker(worker_id: str, payload: WorkerUpdatePayload, request: Request) -> dict[str, object]:
    result = update_worker(worker_id, payload.model_dump())
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


@app.get('/api/sessions/{session_id}/messages')
def api_list_messages(session_id: str, limit: int = 20, offset: int = 0, request: Request = None) -> dict[str, object]:
    return list_messages(session_id, limit=limit, offset=offset, agent_os=_get_agent_os(request))


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


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception('Unhandled exception on %s %s: %s', request.method, request.url.path, exc)
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=500, content={'detail': 'Internal server error'})


@app.middleware('http')
async def log_requests(request: Request, call_next):
    start = time.time()
    try:
        response = await call_next(request)
    except Exception as e:
        logger.exception('Request failed %s %s: %s', request.method, request.url.path, e)
        raise
    elapsed = (time.time() - start) * 1000
    if request.url.path.startswith('/api/'):
        logger.info('%s %s %d %.0fms', request.method, request.url.path, response.status_code, elapsed)
    return response
