from typing import Any


def _find_agent_os_worker(agent_os: Any, worker_id: str, worker_type: str) -> Any | None:
    collection_name = {
        'Agent': 'agents',
        'Team': 'teams',
        'Workflow': 'workflows',
    }.get(worker_type)

    if not collection_name:
        return None

    collection = getattr(agent_os, collection_name, None) or []
    for item in collection:
        if getattr(item, 'id', None) == worker_id:
            return item

    return None


def _extract_response_content(result: Any) -> str:
    if result is None:
        return ''

    if isinstance(result, str):
        return result

    for field_name in ('content', 'response', 'message'):
        value = getattr(result, field_name, None)
        if isinstance(value, str) and value:
            return value

    return str(result)


def _extract_tool_calls(result: Any) -> list[dict[str, Any]]:
    tools = getattr(result, 'tools', None) or []
    extracted = []
    for t in tools:
        extracted.append({
            'toolCallId': getattr(t, 'tool_call_id', ''),
            'toolName': getattr(t, 'tool_name', ''),
            'toolArgs': getattr(t, 'tool_args', {}),
            'result': getattr(t, 'result', None),
            'error': getattr(t, 'tool_call_error', None),
        })
    return extracted


def _extract_reasoning(result: Any) -> str:
    rc = getattr(result, 'reasoning_content', None)
    if rc and isinstance(rc, str):
        return rc
    return ''


async def run_worker(worker: dict[str, object], message: str, session_id: str | None = None, agent_os: Any | None = None, media_kwargs: dict[str, object] | None = None, runtime_worker: Any | None = None) -> dict[str, object]:
    worker_type = str(worker['type'])

    if runtime_worker is None and agent_os is not None:
        runtime_worker = _find_agent_os_worker(agent_os, str(worker['id']), worker_type)

    if runtime_worker is not None and hasattr(runtime_worker, 'arun'):
        run_kwargs: dict[str, object] = {}
        if session_id:
            run_kwargs['session_id'] = session_id
        if media_kwargs:
            run_kwargs.update(media_kwargs)

        result = await runtime_worker.arun(message, **run_kwargs)
        content = _extract_response_content(result)
        return {
            'content': content or f"{worker['name']} processed the request",
            'tokenInput': len(message.split()),
            'tokenOutput': max(len((content or '').split()), 1),
            'toolCalls': _extract_tool_calls(result),
            'reasoning': _extract_reasoning(result),
        }

    if worker_type in {'Team', 'Workflow'}:
        return {
            'content': f'{worker_type} execution is not enabled in phase 1',
            'tokenInput': len(message.split()),
            'tokenOutput': 7,
            'toolCalls': [],
            'reasoning': '',
        }

    return {
        'content': f"{worker['name']} received: {message}",
        'tokenInput': len(message.split()),
        'tokenOutput': len(message.split()) + 3,
        'toolCalls': [],
        'reasoning': '',
    }
