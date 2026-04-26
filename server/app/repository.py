from __future__ import annotations

import uuid
from typing import Any

from app.config import add_worker_ref, get_model_capabilities, get_workers_config, save_worker_config


def _extract_worker_block(worker_cfg: dict[str, Any]) -> dict[str, Any]:
    for key in ('agent', 'team', 'workflow'):
        block = worker_cfg.get(key)
        if isinstance(block, dict):
            return block
    return worker_cfg


def _detect_type(worker_cfg: dict[str, Any]) -> str:
    if 'agent' in worker_cfg:
        return 'Agent'
    if 'team' in worker_cfg:
        return 'Team'
    if 'workflow' in worker_cfg:
        return 'Workflow'
    return 'Agent'


_HISTORY_DEFAULTS = {
    'add_history_to_context': True,
    'num_history_messages': 20,
    'max_tool_calls_from_history': 3,
}


def _merge_history(raw: dict[str, Any]) -> dict[str, Any]:
    history_cfg = raw.get('history') or {}
    merged = dict(_HISTORY_DEFAULTS)
    merged.update({k: v for k, v in history_cfg.items() if v is not None})
    return merged


_LEARNING_DEFAULTS = {
    'user_profile': False,
    'user_memory': False,
    'session_context': False,
    'entity_memory': False,
    'decision_log': False,
}


def _merge_learning(raw: dict[str, Any]) -> dict[str, Any]:
    """Merge learning config from raw worker config with defaults."""
    learning_cfg = raw.get('learning') or {}
    merged = dict(_LEARNING_DEFAULTS)
    merged.update({k: v for k, v in learning_cfg.items() if v is not None})
    return merged


def _serialize_worker(worker_cfg: dict[str, Any]) -> dict[str, Any]:
    block = _extract_worker_block(worker_cfg)
    worker_type = _detect_type(worker_cfg)
    model_ref = worker_cfg.get('model')
    return {
        'id': block.get('id', ''),
        'type': worker_type,
        'name': block.get('name', ''),
        'description': block.get('description', ''),
        'status': block.get('status', ''),
        'recent': block.get('status', ''),
        'config': {
            'model': model_ref,
            'modelCapabilities': get_model_capabilities(model_ref),
            'instructions': block.get('instructions', ''),
            'tools': worker_cfg.get('tools', []),
            'database': worker_cfg.get('database', {}),
            'workspaces': worker_cfg.get('team_workspaces', worker_cfg.get('workspaces', [])),
            'knowledge': worker_cfg.get('team_knowledge', worker_cfg.get('knowledge', [])),
            'members': worker_cfg.get('members', []),
            'nodes': worker_cfg.get('nodes', []),
            'session': worker_cfg.get('session', {}),
            'response': worker_cfg.get('response', {}),
            'skills': worker_cfg.get('skills', []),
            'mcp': worker_cfg.get('mcp', []),
            'history': _merge_history(worker_cfg),
            'learning': _merge_learning(worker_cfg),
        },
        '_ref': worker_cfg.get('_ref', ''),
        '_raw': worker_cfg,
    }


def _read_all_workers() -> list[dict[str, Any]]:
    return get_workers_config()


def list_workers(worker_type: str | None = None) -> list[dict[str, Any]]:
    workers = _read_all_workers()
    result = [_serialize_worker(w) for w in workers]
    if worker_type:
        result = [w for w in result if w['type'] == worker_type]
    return result


def get_worker(worker_id: str) -> dict[str, Any] | None:
    for w in _read_all_workers():
        serialized = _serialize_worker(w)
        if serialized['id'] == worker_id:
            return serialized
    return None


def _get_worker_raw(worker_id: str) -> dict[str, Any] | None:
    for w in _read_all_workers():
        block = _extract_worker_block(w)
        if block.get('id') == worker_id:
            return w
    return None


def create_worker(payload: dict[str, Any]) -> dict[str, Any]:
    worker_type = payload.get('type', 'Agent')
    worker_id = payload.get('id') or f"{worker_type.lower()}-{uuid.uuid4().hex[:8]}"
    ref = payload.get('name', worker_id).lower().replace(' ', '-')
    block_key = {
        'Agent': 'agent',
        'Team': 'team',
        'Workflow': 'workflow',
    }.get(worker_type, 'agent')

    new_cfg: dict[str, Any] = {
        block_key: {
            'id': worker_id,
            'name': payload.get('name', ''),
            'description': payload.get('description', ''),
        },
        'model': payload.get('config', {}).get('model'),
    }

    save_worker_config(ref, new_cfg)
    add_worker_ref(ref)
    new_cfg['_ref'] = ref
    return _serialize_worker(new_cfg)


def update_worker(worker_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    raw = _get_worker_raw(worker_id)
    if raw is None:
        return None

    block = _extract_worker_block(raw)
    block['name'] = payload.get('name', block.get('name', ''))
    block['description'] = payload.get('description', block.get('description', ''))
    if 'status' in payload:
        block['status'] = payload['status']

    config = payload.get('config', {})
    if 'model' in config:
        raw['model'] = config['model']
    if 'workspaces' in config:
        ws_key = 'team_workspaces' if _detect_type(raw) == 'Team' else 'workspaces'
        raw[ws_key] = config['workspaces']
    if 'knowledge' in config:
        raw['knowledge'] = config['knowledge']
    if 'instructions' in config:
        block['instructions'] = config['instructions']
    if 'skills' in config:
        raw['skills'] = config['skills']
    if 'tools' in config:
        raw['tools'] = config['tools']
    if 'members' in config:
        raw['members'] = config['members']
    if 'mcp' in config:
        raw['mcp'] = config['mcp']
    if 'history' in config:
        raw['history'] = config['history']
    if 'learning' in config:
        raw['learning'] = config['learning']

    ref = raw.get('_ref', worker_id)
    save_worker_config(ref, raw)
    return _serialize_worker(raw)


def make_session_id(worker_id: str) -> str:
    return f"{worker_id}:{uuid.uuid4().hex[:8]}"


def extract_worker_id(session_id: str) -> str:
    return session_id.split(':', 1)[0]
