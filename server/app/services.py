from __future__ import annotations

import dataclasses
import json
import logging
from contextlib import contextmanager, nullcontext
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator, Iterator

from fastapi import HTTPException

from app.executor import run_worker, _find_agent_os_worker
from app import repository

logger = logging.getLogger('nowork')


def _resolve_worker_id_from_session(session_id: str, agent_os: Any) -> str | None:
    from agno.db.base import SessionType

    for collection_name, session_type in [('agents', SessionType.AGENT), ('teams', SessionType.TEAM)]:
        items = getattr(agent_os, collection_name, []) or []
        for item in items:
            db = getattr(item, 'db', None)
            if db is None:
                continue
            try:
                session = db.get_session(session_id=session_id, session_type=session_type)
                if session is not None:
                    return str(getattr(session, 'agent_id', '') or getattr(session, 'team_id', '') or getattr(item, 'id', ''))
            except Exception as e:
                logger.debug('db.get_session failed for %s %s: %s', collection_name, getattr(item, 'id', '?'), e)
                continue

    logger.warning('Could not resolve worker_id for session %s', session_id)
    return None


def _resolve_worker_id(session_id: str, agent_os: Any | None) -> str | None:
    if ':' in session_id:
        return session_id.split(':', 1)[0]
    if agent_os is not None:
        return _resolve_worker_id_from_session(session_id, agent_os)
    return None


def _resolve_runtime_agent(worker_id: str, agent_os: Any) -> Any | None:
    worker = repository.get_worker(worker_id)
    if worker is None:
        return None
    return _find_agent_os_worker(agent_os, worker_id, worker['type'])


def _get_runtime_session(runtime: Any, session_id: str) -> Any | None:
    if runtime is None or not hasattr(runtime, 'get_session'):
        return None
    try:
        return runtime.get_session(session_id=session_id)
    except Exception as e:
        logger.debug('runtime.get_session failed for %s: %s', session_id, e)
        return None


def _extract_session_workspaces(session_obj: Any) -> list[str] | None:
    session_data = getattr(session_obj, 'session_data', None)
    if not isinstance(session_data, dict):
        return None
    # New format: workspaces list
    workspaces = session_data.get('workspaces')
    if isinstance(workspaces, list):
        return [w for w in workspaces if isinstance(w, str) and w.strip()] or None
    # Legacy format: single workspace string
    workspace = session_data.get('workspace')
    if isinstance(workspace, str) and workspace.strip():
        return [workspace.strip()]
    return None


@contextmanager
def _bind_runtime_session_workspace(runtime: Any, session_id: str):
    tokens: list[tuple[Any, Any]] = []
    session_obj = _get_runtime_session(runtime, session_id)
    workspaces = _extract_session_workspaces(session_obj)

    tools = list(getattr(runtime, 'tools', None) or [])
    for tool in tools:
        if not all(hasattr(tool, attr) for attr in ('set_current_session', 'register_session_workspace')):
            continue
        try:
            token = tool.set_current_session(session_id)
            tokens.append((tool, token))
            if workspaces:
                tool.register_session_workspace(session_id, workspaces)
        except Exception as e:
            logger.debug('Failed to bind session workspace for %s: %s', session_id, e)

    try:
        yield workspaces
    finally:
        for tool, token in reversed(tokens):
            try:
                tool.reset_current_session(token)
            except Exception:
                pass


def _normalize_tool_call(tc: Any) -> dict[str, Any]:
    if isinstance(tc, dict):
        fn = tc.get('function') or {}
        function_args = fn.get('arguments', {})
        if isinstance(function_args, str):
            try:
                function_args = json.loads(function_args) if function_args else {}
            except Exception:
                function_args = {'raw': function_args}
        return {
            'toolCallId': tc.get('tool_call_id', '') or tc.get('toolCallId', '') or tc.get('id', ''),
            'toolName': tc.get('tool_name', '') or tc.get('toolName', '') or fn.get('name', ''),
            'toolArgs': tc.get('tool_args') or tc.get('toolArgs') or function_args,
            'result': tc.get('result'),
            'error': tc.get('tool_call_error') or tc.get('error'),
        }
    return {
        'toolCallId': getattr(tc, 'tool_call_id', '') or getattr(tc, 'id', ''),
        'toolName': getattr(tc, 'tool_name', '') or (getattr(getattr(tc, 'function', None), 'name', '')),
        'toolArgs': getattr(tc, 'tool_args', {}) or _parse_function_args(tc),
        'result': getattr(tc, 'result', None),
        'error': getattr(tc, 'tool_call_error', None) or getattr(tc, 'error', None),
    }


def _parse_function_args(tc: Any) -> dict:
    fn = getattr(tc, 'function', None)
    if fn is None:
        return {}
    args = getattr(fn, 'arguments', {})
    if isinstance(args, str):
        import json
        try:
            return json.loads(args)
        except Exception:
            return {'raw': args}
    return args if isinstance(args, dict) else {}


def _normalize_runtime_messages(runtime_messages: list[Any], worker_name: str | None = None) -> list[dict[str, Any]]:
    result = []
    for idx, msg in enumerate(runtime_messages):
        role = str(getattr(msg, 'role', 'user'))
        if role == 'assistant':
            role = 'worker'

        raw_tool_calls = getattr(msg, 'tool_calls', None) or []
        normalized_tools = [_normalize_tool_call(tc) for tc in raw_tool_calls]

        reasoning = getattr(msg, 'reasoning_content', '') or getattr(msg, 'reasoning', '') or ''

        metrics = getattr(msg, 'metrics', None)
        token_input = getattr(metrics, 'input_tokens', 0) or 0
        token_output = getattr(metrics, 'output_tokens', 0) or 0

        msg_name = getattr(msg, 'name', None) or None

        content = str(getattr(msg, 'content', ''))
        attachment_lines: list[str] = []
        for kind in ('images', 'videos', 'files'):
            items = getattr(msg, kind, None) or []
            for item in items:
                name = getattr(item, 'filename', None) or getattr(item, 'name', None) or getattr(item, 'filepath', None) or getattr(item, 'url', None) or kind[:-1]
                attachment_lines.append(f"- {kind[:-1]}: {name}")
        if attachment_lines:
            prefix = f"{content}\n\n" if content else ''
            content = prefix + '[Attachments]\n' + '\n'.join(attachment_lines)

        result.append({
            'id': f'runtime-{idx}',
            'role': role,
            'content': content,
            'tokenInput': token_input,
            'tokenOutput': token_output,
            'toolCalls': normalized_tools,
            'reasoning': str(reasoning),
            'senderName': msg_name if role == 'worker' and msg_name else (worker_name if role == 'worker' else None),
        })

    return result


def list_workers(worker_type: str | None = None) -> list[dict[str, Any]]:
    return repository.list_workers(worker_type)


def get_worker(worker_id: str) -> dict[str, Any]:
    worker = repository.get_worker(worker_id)
    if worker is None:
        raise HTTPException(status_code=404, detail='Worker not found')
    return worker


def create_worker(payload: dict[str, Any]) -> dict[str, Any]:
    return repository.create_worker(payload)


def update_worker(worker_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    worker = repository.update_worker(worker_id, payload)
    if worker is None:
        raise HTTPException(status_code=404, detail='Worker not found')
    return worker


def list_sessions(worker_id: str, agent_os: Any | None = None) -> list[dict[str, Any]]:
    get_worker(worker_id)

    if agent_os is not None:
        runtime = _resolve_runtime_agent(worker_id, agent_os)
        if runtime is not None:
            db = getattr(runtime, 'db', None)
            if db is not None and hasattr(db, 'get_sessions'):
                from agno.db.base import SessionType
                worker = repository.get_worker(worker_id)
                session_type = SessionType.TEAM if worker['type'] == 'Team' else SessionType.AGENT
                try:
                    sessions = db.get_sessions(
                        session_type=session_type,
                        component_id=worker_id,
                    )
                except Exception:
                    return []
                sessions = sorted(
                    sessions,
                    key=lambda s: getattr(s, 'updated_at', None) or getattr(s, 'created_at', None) or 0,
                    reverse=True,
                )
                return [
                    {
                        'id': str(getattr(s, 'session_id', '')),
                        'workerId': worker_id,
                        'title': getattr(s, 'session_data', {}).get('title', 'Untitled') if isinstance(getattr(s, 'session_data', None), dict) else 'Untitled',
                        'workspaces': _extract_session_workspaces(s),
                        'createdAt': str(getattr(s, 'created_at', '')),
                        'updatedAt': str(getattr(s, 'updated_at', '') or getattr(s, 'created_at', '')),
                    }
                    for s in sessions
                ]

    return []


def create_session(worker_id: str, title: str, workspaces: list[str] | None = None, agent_os: Any | None = None) -> dict[str, Any]:
    get_worker(worker_id)
    session_id = repository.make_session_id(worker_id)
    now = datetime.now(timezone.utc).isoformat()
    session_data: dict[str, Any] = {'title': title}
    if workspaces:
        session_data['workspaces'] = workspaces

    if agent_os is not None:
        runtime = _resolve_runtime_agent(worker_id, agent_os)
        if runtime is not None:
            db = getattr(runtime, 'db', None)
            if db is not None and hasattr(db, 'upsert_session'):
                try:
                    worker = repository.get_worker(worker_id)
                    if worker['type'] == 'Team':
                        from agno.session import TeamSession
                        session_obj = TeamSession(
                            session_id=session_id,
                            team_id=worker_id,
                            session_data=session_data,
                        )
                    else:
                        from agno.session import AgentSession
                        session_obj = AgentSession(
                            session_id=session_id,
                            agent_id=worker_id,
                            session_data=session_data,
                        )
                    db.upsert_session(session_obj)
                except Exception:
                    pass

    return {
        'id': session_id,
        'workerId': worker_id,
        'title': title,
        'workspaces': workspaces,
        'createdAt': now,
    }


def get_session(session_id: str, agent_os: Any | None = None) -> dict[str, Any] | None:
    worker_id = repository.extract_worker_id(session_id)
    worker = repository.get_worker(worker_id)
    if worker is None:
        return None

    if agent_os is not None:
        runtime = _resolve_runtime_agent(worker_id, agent_os)
        if runtime is not None:
            try:
                agent_session = runtime.get_session(session_id=session_id)
                if agent_session is not None:
                    return {
                        'id': session_id,
                        'workerId': worker_id,
                        'title': getattr(agent_session, 'session_data', {}).get('title', 'Untitled') if isinstance(getattr(agent_session, 'session_data', None), dict) else 'Untitled',
                        'workspaces': _extract_session_workspaces(agent_session),
                        'createdAt': str(getattr(agent_session, 'created_at', '')),
                    }
            except Exception:
                pass

    return {
        'id': session_id,
        'workerId': worker_id,
        'title': 'Untitled',
        'workspaces': None,
        'createdAt': '',
    }


def update_session(session_id: str, payload: dict[str, Any], agent_os: Any | None = None) -> dict[str, Any] | None:
    worker_id = repository.extract_worker_id(session_id)
    worker = repository.get_worker(worker_id)
    if worker is None:
        return None
    if agent_os is None:
        return get_session(session_id, agent_os=agent_os)

    runtime = _resolve_runtime_agent(worker_id, agent_os)
    if runtime is None:
        return None
    db = getattr(runtime, 'db', None)
    if db is None or not hasattr(db, 'upsert_session'):
        return None

    session_obj = _get_runtime_session(runtime, session_id)
    if session_obj is None:
        return None

    session_data = getattr(session_obj, 'session_data', None)
    if not isinstance(session_data, dict):
        session_data = {}
    else:
        session_data = dict(session_data)

    if 'title' in payload and payload.get('title') is not None:
        session_data['title'] = str(payload['title'])

    if 'workspaces' in payload:
        workspaces = payload.get('workspaces')
        if isinstance(workspaces, list) and len(workspaces) > 0:
            session_data['workspaces'] = [str(w).strip() for w in workspaces if str(w).strip()]
        else:
            session_data.pop('workspaces', None)
        # Also clean up legacy single-workspace key
        session_data.pop('workspace', None)

    setattr(session_obj, 'session_data', session_data)

    try:
        db.upsert_session(session_obj)
    except Exception as e:
        logger.warning('Failed to update session %s: %s', session_id, e)
        return None

    return {
        'id': session_id,
        'workerId': worker_id,
        'title': session_data.get('title', 'Untitled'),
        'workspaces': session_data.get('workspaces'),
        'createdAt': str(getattr(session_obj, 'created_at', '')),
        'updatedAt': str(getattr(session_obj, 'updated_at', '') or getattr(session_obj, 'created_at', '')),
    }


def list_messages(session_id: str, limit: int = 20, offset: int = 0, agent_os: Any | None = None) -> dict[str, Any]:
    worker_id = _resolve_worker_id(session_id, agent_os)
    if worker_id is None:
        raise HTTPException(status_code=404, detail='Session not found')
    worker = repository.get_worker(worker_id)
    if worker is None:
        raise HTTPException(status_code=404, detail='Session not found')

    if agent_os is not None:
        runtime = _resolve_runtime_agent(worker_id, agent_os)
        if runtime is not None and hasattr(runtime, 'get_chat_history'):
            history = runtime.get_chat_history(session_id=session_id)
            if history is not None:
                normalized = _normalize_runtime_messages(history, worker_name=worker.get('name'))
                total = len(normalized)
                start = max(0, total - offset - limit)
                end = total - offset
                return {
                    'messages': normalized[start:end],
                    'total': total,
                    'has_more': start > 0,
                }

    return {'messages': [], 'total': 0, 'has_more': False}


def _get_worker_model_capabilities(worker: dict[str, Any]) -> dict[str, bool]:
    raw_caps = worker.get('config', {}).get('modelCapabilities', {}) if isinstance(worker.get('config'), dict) else {}
    if not isinstance(raw_caps, dict):
        raw_caps = {}
    return {
        'image': bool(raw_caps.get('image', False)),
        'video': bool(raw_caps.get('video', False)),
        'file': bool(raw_caps.get('file', True)),
    }


def _get_allowed_attachment_roots(worker: dict[str, Any], session_obj: Any | None) -> list[Path]:
    selected_workspaces = _extract_session_workspaces(session_obj)
    roots_raw = selected_workspaces
    if not roots_raw:
        config = worker.get('config', {}) if isinstance(worker.get('config'), dict) else {}
        workspaces_cfg = config.get('workspaces', []) if isinstance(config, dict) else []
        roots_raw = [str(ws.get('path', '')).strip() for ws in workspaces_cfg if isinstance(ws, dict) and ws.get('path')]

    roots: list[Path] = []
    for root in roots_raw or []:
        try:
            resolved = Path(root).resolve()
            if resolved.exists() and resolved.is_dir():
                roots.append(resolved)
        except Exception:
            continue
    return roots


def _is_path_within_roots(path: Path, roots: list[Path]) -> bool:
    for root in roots:
        try:
            path.relative_to(root)
            return True
        except ValueError:
            continue
    return False


def _build_media_kwargs(session_id: str, worker: dict[str, Any], runtime: Any | None, attachments: list[dict[str, Any]] | None) -> tuple[dict[str, Any], list[dict[str, str]]]:
    if not attachments:
        return {}, []

    from agno.media import File, Image, Video

    session_obj = _get_runtime_session(runtime, session_id) if runtime is not None else None
    allowed_roots = _get_allowed_attachment_roots(worker, session_obj)
    if not allowed_roots:
        raise HTTPException(status_code=400, detail='No workspace available for attachments')

    caps = _get_worker_model_capabilities(worker)
    images: list[Any] = []
    videos: list[Any] = []
    files: list[Any] = []
    normalized: list[dict[str, str]] = []

    for item in attachments:
        if not isinstance(item, dict):
            continue
        kind = str(item.get('kind', '')).strip().lower()
        raw_path = str(item.get('path', '')).strip()
        if not kind or not raw_path:
            continue

        resolved = Path(raw_path).resolve()
        if not resolved.exists() or not resolved.is_file():
            raise HTTPException(status_code=400, detail=f'Attachment not found: {raw_path}')
        if not _is_path_within_roots(resolved, allowed_roots):
            raise HTTPException(status_code=400, detail=f'Attachment path is outside session workspaces: {raw_path}')

        name = str(item.get('name') or resolved.name)
        mime_type = item.get('mimeType')
        if kind == 'image':
            if not caps['image']:
                raise HTTPException(status_code=400, detail='Current model does not support image attachments')
            images.append(Image(filepath=str(resolved), mime_type=mime_type))
        elif kind == 'video':
            if not caps['video']:
                raise HTTPException(status_code=400, detail='Current model does not support video attachments')
            suffix = resolved.suffix.lower().lstrip('.') or None
            videos.append(Video(filepath=str(resolved), mime_type=mime_type, format=suffix))
        elif kind == 'file':
            if not caps['file']:
                raise HTTPException(status_code=400, detail='Current model does not support file attachments')
            suffix = resolved.suffix.lower().lstrip('.') or None
            files.append(File(filepath=str(resolved), mime_type=mime_type, filename=name, format=suffix, name=name))
        else:
            raise HTTPException(status_code=400, detail=f'Unsupported attachment kind: {kind}')

        normalized.append({'kind': kind, 'path': str(resolved), 'name': name})

    kwargs: dict[str, Any] = {}
    if images:
        kwargs['images'] = images
    if videos:
        kwargs['videos'] = videos
    if files:
        kwargs['files'] = files
    return kwargs, normalized


def _format_user_message_content(content: str, attachments: list[dict[str, str]] | None = None) -> str:
    if not attachments:
        return content
    lines = [content] if content else []
    lines.append('')
    lines.append('[Attachments]')
    for item in attachments:
        lines.append(f"- {item.get('kind', 'file')}: {item.get('name', item.get('path', ''))}")
    return '\n'.join(lines).strip()


async def create_message(session_id: str, content: str, attachments: list[dict[str, Any]] | None = None, agent_os: Any | None = None) -> dict[str, Any]:
    worker_id = _resolve_worker_id(session_id, agent_os)
    if worker_id is None:
        raise HTTPException(status_code=404, detail='Session not found')
    worker = repository.get_worker(worker_id)
    if worker is None:
        raise HTTPException(status_code=404, detail='Session not found')

    runtime_worker = _resolve_runtime_agent(worker['id'], agent_os) if agent_os is not None else None
    media_kwargs, normalized_attachments = _build_media_kwargs(session_id, worker, runtime_worker, attachments)
    display_content = _format_user_message_content(content, normalized_attachments)

    if agent_os is not None and worker['type'] == 'Agent':
        runtime_agent = _find_agent_os_worker(agent_os, worker['id'], 'Agent')
        if runtime_agent is not None and hasattr(runtime_agent, 'run'):
            with _bind_runtime_session_workspace(runtime_agent, session_id):
                result = await run_worker(worker, content, session_id=session_id, agent_os=agent_os, media_kwargs=media_kwargs)
            user_message = {
                'id': f'runtime-user-{session_id}',
                'role': 'user',
                'content': display_content,
                'meta': '',
                'tokenInput': 0,
                'tokenOutput': 0,
                'toolCalls': [],
                'reasoning': '',
            }
            worker_message = {
                'id': f'runtime-worker-{session_id}',
                'role': 'worker',
                'content': str(result['content']),
                'meta': '',
                'tokenInput': int(result['tokenInput']),
                'tokenOutput': int(result['tokenOutput']),
                'toolCalls': result.get('toolCalls', []),
                'reasoning': result.get('reasoning', ''),
            }
            return {
                'userMessage': user_message,
                'workerMessage': worker_message,
                'tokenUsage': {
                    'input': int(result['tokenInput']),
                    'output': int(result['tokenOutput']),
                    'total': int(result['tokenInput']) + int(result['tokenOutput']),
                },
            }

    if worker['type'] in {'Team', 'Workflow'}:
        runtime_worker = _find_agent_os_worker(agent_os, worker['id'], worker['type']) if agent_os is not None else None
        with (_bind_runtime_session_workspace(runtime_worker, session_id) if runtime_worker is not None else nullcontext()):
            result = await run_worker(worker, content, session_id=session_id, agent_os=agent_os, media_kwargs=media_kwargs)
        return {
            'userMessage': {
                'id': f'placeholder-user-{session_id}',
                'role': 'user',
                'content': display_content,
                'meta': '',
                'tokenInput': 0,
                'tokenOutput': 0,
                'toolCalls': [],
                'reasoning': '',
            },
            'workerMessage': {
                'id': f'placeholder-worker-{session_id}',
                'role': 'worker',
                'content': str(result['content']),
                'meta': '',
                'tokenInput': int(result['tokenInput']),
                'tokenOutput': int(result['tokenOutput']),
                'toolCalls': result.get('toolCalls', []),
                'reasoning': result.get('reasoning', ''),
            },
            'tokenUsage': {
                'input': int(result['tokenInput']),
                'output': int(result['tokenOutput']),
                'total': int(result['tokenInput']) + int(result['tokenOutput']),
            },
        }

    with (_bind_runtime_session_workspace(runtime_worker, session_id) if runtime_worker is not None else nullcontext()):
        result = await run_worker(worker, content, session_id=session_id, agent_os=agent_os, media_kwargs=media_kwargs)
    return {
        'userMessage': {
            'id': f'user-{session_id}',
            'role': 'user',
            'content': display_content,
            'meta': '',
            'tokenInput': 0,
            'tokenOutput': 0,
            'toolCalls': [],
            'reasoning': '',
        },
        'workerMessage': {
            'id': f'worker-{session_id}',
            'role': 'worker',
            'content': str(result['content']),
            'meta': '',
            'tokenInput': int(result['tokenInput']),
            'tokenOutput': int(result['tokenOutput']),
            'toolCalls': result.get('toolCalls', []),
            'reasoning': result.get('reasoning', ''),
        },
        'tokenUsage': {
            'input': int(result['tokenInput']),
            'output': int(result['tokenOutput']),
            'total': int(result['tokenInput']) + int(result['tokenOutput']),
        },
    }


def _get_event_type(event: Any) -> str:
    raw = getattr(event, 'event', '')
    if hasattr(raw, 'value'):
        return raw.value
    return str(raw)


_TEAM_EVENT_MAP = {
    'TeamRunStarted': 'RunStarted',
    'TeamRunContent': 'RunContent',
    'TeamRunContentCompleted': 'RunContentCompleted',
    'TeamRunCompleted': 'RunCompleted',
    'TeamRunError': 'RunError',
    'TeamRunCancelled': 'RunCancelled',
    'TeamRunPaused': 'RunPaused',
    'TeamRunContinued': 'RunContinued',
    'TeamToolCallStarted': 'ToolCallStarted',
    'TeamToolCallCompleted': 'ToolCallCompleted',
    'TeamToolCallError': 'ToolCallError',
    'TeamReasoningStarted': 'ReasoningStarted',
    'TeamReasoningStep': 'ReasoningStep',
    'TeamReasoningContentDelta': 'ReasoningContentDelta',
    'TeamReasoningCompleted': 'ReasoningCompleted',
    'TeamModelRequestCompleted': 'ModelRequestCompleted',
    'TeamModelRequestStarted': 'ModelRequestStarted',
}


def _normalize_event_type(event_type: str) -> str:
    return _TEAM_EVENT_MAP.get(event_type, event_type)


def _normalize_tool_execution(tc: Any) -> dict[str, Any]:
    return {
        'toolCallId': getattr(tc, 'tool_call_id', '') or '',
        'toolName': getattr(tc, 'tool_name', '') or '',
        'toolArgs': getattr(tc, 'tool_args', None) or {},
        'result': getattr(tc, 'result', None),
        'error': getattr(tc, 'tool_call_error', None),
    }


def _serialize_event(event: Any) -> dict[str, Any]:
    result: dict[str, Any] = {'event': _get_event_type(event)}
    for field in dataclasses.fields(event):
        name = field.name
        value = getattr(event, name)
        if value is None:
            continue
        if isinstance(value, str | int | float | bool):
            result[name] = value
        elif dataclasses.is_dataclass(value):
            result[name] = _serialize_event(value)
        elif isinstance(value, list):
            result[name] = [
                _normalize_tool_execution(item) if type(item).__name__ == 'ToolExecution'
                else _serialize_event(item) if dataclasses.is_dataclass(item)
                else item
                for item in value
            ]
        elif isinstance(value, dict):
            result[name] = value
        else:
            result[name] = str(value)
    return result


async def stream_message(session_id: str, content: str, attachments: list[dict[str, Any]] | None, agent_os: Any) -> AsyncIterator[str]:
    worker_id = _resolve_worker_id(session_id, agent_os)
    if worker_id is None:
        logger.warning('stream_message: session not found %s', session_id)
        yield f"data: {json.dumps({'event': 'RunError', 'content': 'Session not found'})}\n\n"
        return
    worker = repository.get_worker(worker_id)
    if worker is None:
        logger.warning('stream_message: worker not found %s', worker_id)
        yield f"data: {json.dumps({'event': 'RunError', 'content': 'Session not found'})}\n\n"
        return

    worker_type = worker.get('type', 'Agent')
    runtime = _find_agent_os_worker(agent_os, worker['id'], worker_type)
    if runtime is None or not hasattr(runtime, 'run'):
        logger.error('stream_message: runtime not available for worker %s type %s', worker['id'], worker_type)
        yield f"data: {json.dumps({'event': 'RunError', 'content': f'{worker_type} runtime not available'})}\n\n"
        return

    logger.info('stream_message: session=%s worker=%s type=%s content_len=%d', session_id, worker_id, worker_type, len(content))

    media_kwargs, _normalized_attachments = _build_media_kwargs(session_id, worker, runtime, attachments)

    accumulated_content = ''
    accumulated_reasoning = ''
    current_tools: list[dict[str, Any]] = []

    try:
        with _bind_runtime_session_workspace(runtime, session_id):
            async for event in runtime.arun(content, session_id=session_id, stream=True, stream_events=True, **media_kwargs):
                event_data = _serialize_event(event)
                raw_event_type = _get_event_type(event)
                event_type = _normalize_event_type(raw_event_type)

                event_data['event'] = event_type

                new_content = getattr(event, 'content', None)
                if new_content and isinstance(new_content, str):
                    accumulated_content = new_content

                new_reasoning = getattr(event, 'reasoning_content', None)
                if new_reasoning and isinstance(new_reasoning, str):
                    accumulated_reasoning = new_reasoning

                if event_type == 'ToolCallStarted':
                    tool = getattr(event, 'tool', None)
                    if tool:
                        current_tools.append(_normalize_tool_execution(tool))
                    event_data['toolCalls'] = current_tools

                if event_type == 'ToolCallCompleted':
                    tool = getattr(event, 'tool', None)
                    if tool:
                        tc_id = getattr(tool, 'tool_call_id', '')
                        for t in current_tools:
                            if t['toolCallId'] == tc_id:
                                t['result'] = getattr(tool, 'result', None)
                                t['status'] = 'completed'
                                break
                    event_data['toolCalls'] = current_tools

                if event_type == 'ToolCallError':
                    tool = getattr(event, 'tool', None)
                    if tool:
                        tc_id = getattr(tool, 'tool_call_id', '')
                        for t in current_tools:
                            if t['toolCallId'] == tc_id:
                                t['error'] = getattr(tool, 'tool_call_error', None) or getattr(tool, 'error', None)
                                t['status'] = 'error'
                                break
                    event_data['toolCalls'] = current_tools

                if event_type == 'ModelRequestCompleted':
                    # Forward per-request token metrics for live display
                    event_data['metrics'] = {
                        'input_tokens': getattr(event, 'input_tokens', 0) or 0,
                        'output_tokens': getattr(event, 'output_tokens', 0) or 0,
                        'total_tokens': getattr(event, 'total_tokens', 0) or 0,
                    }

                if event_type == 'RunCompleted':
                    metrics = getattr(event, 'metrics', None)
                    event_data['content'] = accumulated_content
                    event_data['reasoning'] = accumulated_reasoning
                    event_data['toolCalls'] = current_tools
                    if metrics:
                        event_data['metrics'] = {
                            'input_tokens': getattr(metrics, 'input_tokens', 0),
                            'output_tokens': getattr(metrics, 'output_tokens', 0),
                            'total_tokens': getattr(metrics, 'total_tokens', 0),
                            'duration': getattr(metrics, 'duration', 0),
                        }

                yield f"data: {json.dumps(event_data)}\n\n"

    except Exception as exc:
        logger.exception('stream_message error: session=%s %s', session_id, exc)
        yield f"data: {json.dumps({'event': 'RunError', 'content': str(exc)})}\n\n"


async def cancel_run(run_id: str) -> bool:
    from agno.run.cancel import acancel_run
    return await acancel_run(run_id)


_skills_cache: list[dict[str, Any]] | None = None


def _get_skills_dir() -> Path:
    return Path(__file__).resolve().parents[1] / 'skills'


def _load_skills_metadata() -> list[dict[str, Any]]:
    """Load skill metadata using SkillToolkit's frontmatter parser.

    Returns a list of dicts suitable for the web API, without depending
    on the old agno.skills.agent_skills / LocalSkills loader.
    """
    from agno.tools.skill_toolkit import _discover_skills

    skills_dir = _get_skills_dir()
    if not skills_dir.exists():
        return []

    skills = _discover_skills(skills_dir)
    result = []
    for s in skills:
        # Build file listing from skill_dir
        skill_dir = Path(s.skill_dir)
        files: list[dict[str, Any]] = []
        for fpath in sorted(skill_dir.rglob('*')):
            if not fpath.is_file() or fpath.name.startswith('.'):
                continue
            rel = fpath.relative_to(skill_dir)
            files.append({'name': str(rel).replace('\\', '/'), 'size': fpath.stat().st_size})

        result.append({
            'name': s.name,
            'description': s.description,
            'sourcePath': s.skill_dir,
            'scripts': [],
            'references': [],
            'instructions': '',  # Progressive disclosure: not pre-loaded
            '_files': files,
        })
    return result


def list_skills() -> list[dict[str, Any]]:
    global _skills_cache
    if _skills_cache is not None:
        return _skills_cache

    try:
        _skills_cache = _load_skills_metadata()
    except Exception as e:
        logger.warning('Failed to load skills: %s', e)
        _skills_cache = []
    return _skills_cache


def get_skill(skill_name: str) -> dict[str, Any] | None:
    for s in list_skills():
        if s['name'] == skill_name:
            return s
    return None


def read_skill_file(skill_name: str, file_path: str) -> str | None:
    skill = get_skill(skill_name)
    if skill is None:
        return None

    skill_dir = Path(skill['sourcePath'])

    # Resolve the requested file within skill_dir
    target = (skill_dir / file_path).resolve()

    # Security: prevent path traversal outside skill_dir
    if not str(target).startswith(str(skill_dir.resolve())):
        return None

    if not target.exists() or not target.is_file():
        return None

    try:
        return target.read_text(encoding='utf-8')
    except Exception:
        return None


def list_skill_files(skill_name: str) -> list[dict[str, Any]] | None:
    skill = get_skill(skill_name)
    if skill is None:
        return None
    # Use cached file listing from _load_skills_metadata if available
    cached = skill.get('_files')
    if cached is not None:
        return cached
    # Fallback: scan on demand
    skill_dir = Path(skill['sourcePath'])
    result: list[dict[str, Any]] = []
    for fpath in sorted(skill_dir.rglob('*')):
        if not fpath.is_file():
            continue
        if fpath.name.startswith('.'):
            continue
        rel = fpath.relative_to(skill_dir)
        result.append({
            'name': str(rel).replace('\\', '/'),
            'size': fpath.stat().st_size,
        })
    return result


def install_skill(source: str, overwrite: bool = False) -> dict[str, Any]:
    global _skills_cache
    import re
    import shutil
    import tempfile

    skills_dir = _get_skills_dir()
    skills_dir.mkdir(parents=True, exist_ok=True)

    tmp_dir: Path | None = None
    try:
        if source.startswith(('http://', 'https://')):
            import urllib.request
            import zipfile
            suffix = '.zip'
            if source.endswith('.tar.gz'):
                suffix = '.tar.gz'
            tmp_dir = Path(tempfile.mkdtemp())
            archive_path = tmp_dir / f'archive{suffix}'
            urllib.request.urlretrieve(source, str(archive_path))
            if suffix == '.zip':
                with zipfile.ZipFile(archive_path, 'r') as zf:
                    zf.extractall(tmp_dir)
            else:
                import tarfile
                with tarfile.open(archive_path, 'r:*') as tf:
                    tf.extractall(tmp_dir)
            source_dir = _find_skill_root(tmp_dir)
        else:
            source_path = Path(source).resolve()
            if not source_path.exists():
                return {'ok': False, 'error': f'Source path not found: {source}'}
            source_dir = source_path

        if source_dir is None:
            return {'ok': False, 'error': 'No SKILL.md found in source'}

        skill_md = source_dir / 'SKILL.md'
        if not skill_md.exists():
            return {'ok': False, 'error': 'SKILL.md not found in source directory'}

        content = skill_md.read_text(encoding='utf-8')
        fm_match = re.match(r'^---\s*\n(.*?)\n---', content, re.DOTALL)
        skill_name = source_dir.name
        if fm_match:
            for line in fm_match.group(1).split('\n'):
                if line.strip().startswith('name:'):
                    skill_name = line.split(':', 1)[1].strip().strip('"\'')
                    break

        target = skills_dir / skill_name
        if target.exists() and not overwrite:
            return {'ok': False, 'duplicate': True, 'name': skill_name, 'error': f'Skill "{skill_name}" already exists. Overwrite?'}

        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(source_dir, target)

        _skills_cache = None
        return {'ok': True, 'name': skill_name, 'path': str(target)}

    except Exception as e:
        return {'ok': False, 'error': str(e)}
    finally:
        if tmp_dir:
            shutil.rmtree(tmp_dir, ignore_errors=True)


def _find_skill_root(base: Path) -> Path | None:
    if (base / 'SKILL.md').exists():
        return base
    for child in base.iterdir():
        if child.is_dir() and (child / 'SKILL.md').exists():
            return child
    for child in base.iterdir():
        if child.is_dir():
            result = _find_skill_root(child)
            if result:
                return result
    return None


def delete_skill(skill_name: str) -> dict[str, Any]:
    global _skills_cache
    skill = get_skill(skill_name)
    if skill is None:
        return {'ok': False, 'error': f'Skill "{skill_name}" not found'}

    import shutil
    skill_dir = Path(skill['sourcePath'])
    if not skill_dir.exists():
        return {'ok': False, 'error': 'Skill directory not found'}

    shutil.rmtree(skill_dir)
    _skills_cache = None
    return {'ok': True, 'name': skill_name}


def list_models() -> dict[str, Any]:
    from app.config import get_all_providers, load_config
    providers = get_all_providers()
    cfg = load_config()
    default_model = cfg.get('default_model', '') or ''
    return {'providers': providers, 'default_model': default_model}


def create_provider(payload: dict[str, Any]) -> dict[str, Any]:
    from app.config import add_provider_ref, save_provider_config
    provider_id = payload.get('id', '')
    if not provider_id:
        raise ValueError('Provider id is required')
    provider_cfg = {
        'provider': payload.get('provider', provider_id),
        'name': payload.get('name', provider_id),
        'type': payload.get('type', 'openai_compatible'),
        'base_url': payload.get('baseUrl', ''),
        'api_key': payload.get('apiKey', ''),
        'models': {},
    }
    save_provider_config(provider_id, provider_cfg)
    add_provider_ref(provider_id)
    from app.config import load_provider_config, _serialize_provider
    cfg = load_provider_config(provider_id)
    return _serialize_provider(provider_id, cfg)


def update_provider(provider_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    from app.config import load_provider_config, save_provider_config, _serialize_provider, load_config, set_default_model_id
    cfg = load_provider_config(provider_id)
    if not cfg:
        return None
    if 'name' in payload:
        cfg['name'] = payload['name']
    if 'type' in payload:
        cfg['type'] = payload['type']
    if 'provider' in payload:
        cfg['provider'] = payload['provider']
    if 'baseUrl' in payload:
        cfg['base_url'] = payload['baseUrl']
    if 'apiKey' in payload:
        cfg['api_key'] = payload['apiKey']
    if 'models' in payload:
        models_cfg = {}
        for m in payload['models']:
            local_id = m.get('localId', m.get('id', '').split('/')[-1])
            legacy_vision = m.get('vision', False)
            models_cfg[local_id] = {
                'name': m.get('name', local_id),
                'image': m.get('image', legacy_vision),
                'video': m.get('video', legacy_vision),
            }
        cfg['models'] = models_cfg
    save_provider_config(provider_id, cfg)
    # Auto-set default_model if currently empty and this provider has models
    if 'models' in payload:
        try:
            global_cfg = load_config()
            if not global_cfg.get('default_model'):
                saved_models = cfg.get('models', {})
                if isinstance(saved_models, dict) and saved_models:
                    first_model_id = f"{provider_id}/{next(iter(saved_models))}"
                    set_default_model_id(first_model_id)
        except Exception:
            pass
    reloaded = load_provider_config(provider_id)
    return _serialize_provider(provider_id, reloaded)


def delete_provider(provider_id: str) -> dict[str, Any]:
    from app.config import delete_provider_config, remove_provider_ref
    remove_provider_ref(provider_id)
    deleted = delete_provider_config(provider_id)
    return {'ok': deleted, 'id': provider_id}


def set_default_model(model_id: str) -> dict[str, Any]:
    from app.config import set_default_model_id
    set_default_model_id(model_id)
    return {'ok': True, 'default_model': model_id}


def read_log_file(lines: int = 200, offset: int = 0, file_name: str | None = None) -> dict[str, Any]:
    from app.config import get_log_dir
    log_dir = get_log_dir()
    if not log_dir.exists():
        return {'lines': [], 'total': 0, 'offset': 0, 'has_more': False, 'files': []}

    # List available log files
    all_files = sorted(
        [f.name for f in log_dir.iterdir() if f.is_file() and f.suffix == '.log'],
        reverse=True,
    )
    if not all_files:
        return {'lines': [], 'total': 0, 'offset': 0, 'has_more': False, 'files': []}

    target = file_name if file_name else all_files[0]
    log_path = log_dir / target
    if not log_path.exists():
        return {'lines': [], 'total': 0, 'offset': 0, 'has_more': False, 'files': all_files}

    # Read file, count total lines
    with open(log_path, encoding='utf-8', errors='replace') as f:
        all_lines = f.readlines()
    total = len(all_lines)

    # offset=0 means latest N lines; offset=200 means 200 lines before that
    end = total - offset
    start = max(0, end - lines)
    has_more = start > 0
    selected = all_lines[start:end]

    return {
        'lines': [line.rstrip('\n\r') for line in selected],
        'total': total,
        'offset': offset + len(selected),
        'has_more': has_more,
        'files': all_files,
    }


def fetch_remote_models(base_url: str, api_key: str | None = None) -> list[dict[str, Any]]:
    import httpx
    headers = {}
    if api_key:
        headers['Authorization'] = f'Bearer {api_key}'
    try:
        resp = httpx.get(f'{base_url}/models', headers=headers, timeout=10.0)
        if resp.status_code != 200:
            return []
        data = resp.json()
        model_list = data.get('data', []) if isinstance(data, dict) else data
        return [
            {'id': m.get('id', ''), 'name': m.get('id', '')}
            for m in model_list
            if isinstance(m, dict) and m.get('id')
        ]
    except Exception:
        return []


TOOLS_CATALOG = [
    {
        'id': 'coding-tools',
        'name': 'CodingTools',
        'module': 'app.tools.codingTools',
        'description': 'File operations, shell execution, code search',
        'tools': [
            {'id': 'read_file', 'name': 'Read File', 'default': True},
            {'id': 'edit_file', 'name': 'Edit File', 'default': True},
            {'id': 'write_file', 'name': 'Write File', 'default': True},
            {'id': 'run_shell', 'name': 'Shell', 'default': True},
            {'id': 'grep', 'name': 'Grep', 'default': False},
            {'id': 'find', 'name': 'Find', 'default': False},
            {'id': 'ls', 'name': 'List Dir', 'default': False},
        ],
    },
]


def list_tools_catalog() -> list[dict[str, Any]]:
    return TOOLS_CATALOG


def list_mcp_servers() -> list[dict[str, Any]]:
    from app.config import load_mcp_config
    return load_mcp_config()


def _check_url_reachable(url: str, timeout: float = 3.0) -> bool:
    from urllib.parse import urlparse
    import socket
    try:
        parsed = urlparse(url)
        host = parsed.hostname or 'localhost'
        port = parsed.port
        if port is None:
            port = 443 if parsed.scheme == 'https' else 80
        sock = socket.create_connection((host, port), timeout=timeout)
        sock.close()
        return True
    except Exception:
        return False


async def check_mcp_status(servers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for s in servers:
        entry = dict(s)
        if s.get('url'):
            import asyncio
            entry['verified'] = await asyncio.get_event_loop().run_in_executor(
                None, _check_url_reachable, s['url'],
            )
        elif s.get('command'):
            entry['verified'] = True
        else:
            entry['verified'] = False
        result.append(entry)
    return result


def save_mcp_servers(servers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    from app.config import save_mcp_config
    seen: set[str] = set()
    clean = []
    for s in servers:
        name = s.get('name', '').strip()
        if not name or name in seen:
            continue
        seen.add(name)
        entry: dict[str, Any] = {'name': name}
        transport = s.get('transport', 'stdio')
        entry['transport'] = transport
        if transport == 'stdio':
            entry['command'] = s.get('command', '')
        else:
            entry['url'] = s.get('url', '')
        if s.get('env'):
            entry['env'] = s['env']
        if s.get('timeout_seconds'):
            entry['timeout_seconds'] = s['timeout_seconds']
        if s.get('tools'):
            tools_raw = s['tools']
            all_names = [t['name'] for t in tools_raw if isinstance(t, dict) and t.get('name')]
            enabled = [t['name'] for t in tools_raw if isinstance(t, dict) and t.get('enabled', True)]
            disabled = [n for n in all_names if n not in enabled]
            if len(disabled) == 0:
                entry['tools'] = all_names
            elif len(disabled) < len(enabled):
                entry['exclude_tools'] = disabled
                entry['tools'] = all_names
            else:
                entry['include_tools'] = enabled
                entry['tools'] = all_names
        clean.append(entry)
    save_mcp_config(clean)
    return clean


async def test_mcp_connection(payload: dict[str, Any]) -> dict[str, Any]:
    import asyncio
    from agno.tools.mcp import MCPTools

    transport = payload.get('transport', 'stdio')
    kwargs: dict[str, Any] = {'transport': transport}
    if transport == 'stdio':
        kwargs['command'] = payload.get('command', '')
    else:
        kwargs['url'] = payload.get('url', '')
    if payload.get('env'):
        kwargs['env'] = payload['env']
    timeout = payload.get('timeout_seconds', 10)
    kwargs['timeout_seconds'] = timeout

    try:
        mcp = MCPTools(**kwargs)
        await asyncio.wait_for(mcp.connect(), timeout=timeout + 5)
        if not mcp.initialized or mcp.session is None:
            await mcp.close()
            return {'ok': False, 'error': 'Connection initialized but session is None'}

        tools_result = await asyncio.wait_for(mcp.session.list_tools(), timeout=timeout)
        tools = [
            {'name': t.name, 'description': t.description or ''}
            for t in tools_result.tools
        ]
        await mcp.close()
        return {'ok': True, 'tools': tools}
    except asyncio.TimeoutError:
        return {'ok': False, 'error': 'Connection timed out'}
    except Exception as e:
        return {'ok': False, 'error': str(e)}


# =============================================================================
# Learning Content Services
# =============================================================================


def _get_worker_db(worker_id: str, agent_os: Any | None) -> Any | None:
    """Get the database instance for a worker from AgentOS."""
    if agent_os is None:
        return None
    from app.executor import _find_agent_os_worker
    worker = _find_agent_os_worker(agent_os, worker_id, 'Agent')
    if worker is None:
        worker = _find_agent_os_worker(agent_os, worker_id, 'Team')
    if worker is None:
        return None
    return getattr(worker, 'db', None)


def _get_runtime_worker(worker_id: str, agent_os: Any | None) -> Any | None:
    if agent_os is None:
        return None
    from app.executor import _find_agent_os_worker
    worker = _find_agent_os_worker(agent_os, worker_id, 'Agent')
    if worker is None:
        worker = _find_agent_os_worker(agent_os, worker_id, 'Team')
    return worker


def get_user_profile_content(worker_id: str, user_id: str, agent_os: Any | None) -> dict[str, Any]:
    runtime = _get_runtime_worker(worker_id, agent_os)
    if runtime is None:
        raise HTTPException(status_code=404, detail='Worker not found in runtime')

    lm = getattr(runtime, 'learning_machine', None)
    if lm is None or getattr(lm, 'user_profile_store', None) is None:
        return {'worker_id': worker_id, 'user_id': user_id, 'profile': None}

    profile = lm.user_profile_store.recall(user_id=user_id)
    if profile is None:
        return {'worker_id': worker_id, 'user_id': user_id, 'profile': None}

    profile_data = dataclasses.asdict(profile) if dataclasses.is_dataclass(profile) else (profile if isinstance(profile, dict) else {'raw': str(profile)})
    return {'worker_id': worker_id, 'user_id': user_id, 'profile': profile_data}


def get_user_memory_content(worker_id: str, user_id: str, agent_os: Any | None) -> dict[str, Any]:
    runtime = _get_runtime_worker(worker_id, agent_os)
    if runtime is None:
        raise HTTPException(status_code=404, detail='Worker not found in runtime')

    lm = getattr(runtime, 'learning_machine', None)
    if lm is None or getattr(lm, 'user_memory_store', None) is None:
        return {'worker_id': worker_id, 'user_id': user_id, 'memories': [], 'total': 0}

    memories = lm.user_memory_store.recall(user_id=user_id)
    if memories is None:
        return {'worker_id': worker_id, 'user_id': user_id, 'memories': [], 'total': 0}

    if isinstance(memories, list):
        items = []
        for m in memories:
            items.append(dataclasses.asdict(m) if dataclasses.is_dataclass(m) else (m if isinstance(m, dict) else str(m)))
        return {'worker_id': worker_id, 'user_id': user_id, 'memories': items, 'total': len(items)}

    mem_data = dataclasses.asdict(memories) if dataclasses.is_dataclass(memories) else (memories if isinstance(memories, dict) else str(memories))
    return {'worker_id': worker_id, 'user_id': user_id, 'memories': [mem_data], 'total': 1}


def get_session_context_content(worker_id: str, session_id: str, agent_os: Any | None) -> dict[str, Any]:
    """Get session context learning content from the worker's database."""
    db = _get_worker_db(worker_id, agent_os)
    if db is None:
        raise HTTPException(status_code=404, detail='Worker or database not found')

    from agno.db.base import SessionType
    session_type = SessionType.AGENT

    session = db.get_session(session_id=session_id, session_type=session_type)
    if session is None:
        session = db.get_session(session_id=session_id, session_type=SessionType.TEAM)

    if session is None:
        return {
            'worker_id': worker_id,
            'session_id': session_id,
            'context': None,
            'summary': None,
        }

    session_dict = {}
    if hasattr(session, 'to_dict'):
        session_dict = session.to_dict()
    elif dataclasses.is_dataclass(session):
        session_dict = dataclasses.asdict(session)
    else:
        session_dict = dict(session) if isinstance(session, dict) else {}

    return {
        'worker_id': worker_id,
        'session_id': session_id,
        'context': session_dict.get('session_context') or session_dict.get('context'),
        'summary': session_dict.get('session_summary') or session_dict.get('summary'),
        'messages_count': len(session_dict.get('messages', [])),
    }


def get_entity_memory_content(worker_id: str, entity_id: str | None, entity_type: str | None, agent_os: Any | None) -> dict[str, Any]:
    """Get entity memory learning content from the worker's database.

    Note: Entity memory is stored in knowledge table with entity_id prefix.
    """
    db = _get_worker_db(worker_id, agent_os)
    if db is None:
        raise HTTPException(status_code=404, detail='Worker or database not found')

    # Entity memory uses knowledge storage with entity namespace
    knowledge_rows, total = db.get_knowledge_contents(limit=100)

    entities = []
    for row in knowledge_rows:
        row_dict = {}
        if hasattr(row, 'to_dict'):
            row_dict = row.to_dict()
        elif dataclasses.is_dataclass(row):
            row_dict = dataclasses.asdict(row)
        else:
            row_dict = dict(row) if isinstance(row, dict) else {}

        # Filter by entity_id/entity_type if provided
        name = row_dict.get('name', '')
        if entity_id and entity_id not in name:
            continue
        if entity_type and entity_type not in name:
            continue

        entities.append({
            'id': row_dict.get('id'),
            'name': name,
            'content': row_dict.get('content'),
            'meta_data': row_dict.get('meta_data'),
        })

    return {
        'worker_id': worker_id,
        'entities': entities,
        'total': len(entities),
    }


def get_decision_log_content(worker_id: str, session_id: str | None, agent_os: Any | None) -> dict[str, Any]:
    """Get decision log learning content from the worker's database.

    Note: Decision logs are stored as session metadata.
    """
    db = _get_worker_db(worker_id, agent_os)
    if db is None:
        raise HTTPException(status_code=404, detail='Worker or database not found')

    if session_id:
        from agno.db.base import SessionType
        session = db.get_session(session_id=session_id, session_type=SessionType.AGENT)
        if session is None:
            session = db.get_session(session_id=session_id, session_type=SessionType.TEAM)

        if session is None:
            return {
                'worker_id': worker_id,
                'session_id': session_id,
                'decisions': [],
            }

        session_dict = {}
        if hasattr(session, 'to_dict'):
            session_dict = session.to_dict()
        elif dataclasses.is_dataclass(session):
            session_dict = dataclasses.asdict(session)
        else:
            session_dict = dict(session) if isinstance(session, dict) else {}

        decisions = session_dict.get('session_metadata', {}).get('decisions', [])
        return {
            'worker_id': worker_id,
            'session_id': session_id,
            'decisions': decisions,
        }

    # Get all sessions and aggregate decisions
    sessions, _ = db.get_sessions(limit=50)
    all_decisions = []
    for s in sessions:
        s_dict = {}
        if hasattr(s, 'to_dict'):
            s_dict = s.to_dict()
        elif dataclasses.is_dataclass(s):
            s_dict = dataclasses.asdict(s)
        else:
            s_dict = dict(s) if isinstance(s, dict) else {}

        decisions = s_dict.get('session_metadata', {}).get('decisions', [])
        if decisions:
            all_decisions.extend(decisions)

    return {
        'worker_id': worker_id,
        'decisions': all_decisions,
        'total': len(all_decisions),
    }


def update_user_memory_content(worker_id: str, memory_id: str, content: str, agent_os: Any | None) -> dict[str, Any]:
    """Update a specific user memory entry."""
    db = _get_worker_db(worker_id, agent_os)
    if db is None:
        raise HTTPException(status_code=404, detail='Worker or database not found')

    from agno.db.schemas.memory import UserMemory

    existing = db.get_user_memory(memory_id=memory_id, deserialize=True)
    if existing is None:
        raise HTTPException(status_code=404, detail='Memory not found')

    # Update the memory content
    existing.memory = content

    updated = db.upsert_user_memory(memory=existing, deserialize=True)

    return {
        'ok': True,
        'memory_id': memory_id,
        'updated': updated.to_dict() if hasattr(updated, 'to_dict') else updated,
    }


def delete_user_memory_content(worker_id: str, memory_id: str, user_id: str | None, agent_os: Any | None) -> dict[str, Any]:
    """Delete a specific user memory entry."""
    db = _get_worker_db(worker_id, agent_os)
    if db is None:
        raise HTTPException(status_code=404, detail='Worker or database not found')

    db.delete_user_memory(memory_id=memory_id, user_id=user_id)

    return {
        'ok': True,
        'memory_id': memory_id,
    }


def add_user_memory_content(worker_id: str, user_id: str, memory_content: str, agent_os: Any | None) -> dict[str, Any]:
    """Add a new user memory entry."""
    db = _get_worker_db(worker_id, agent_os)
    if db is None:
        raise HTTPException(status_code=404, detail='Worker or database not found')

    from agno.db.schemas.memory import UserMemory
    import uuid

    new_memory = UserMemory(
        memory_id=str(uuid.uuid4()),
        memory=memory_content,
        user_id=user_id,
    )

    created = db.upsert_user_memory(memory=new_memory, deserialize=True)

    return {
        'ok': True,
        'memory_id': new_memory.memory_id,
        'created': created.to_dict() if hasattr(created, 'to_dict') else created,
    }
