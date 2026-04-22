from __future__ import annotations

import uuid
from typing import Any

from app.config import (
    get_all_knowledge_configs,
    load_knowledge_config,
    save_knowledge_config,
    add_knowledge_ref,
    remove_knowledge_ref,
    delete_knowledge_config as delete_kconfig_file,
)


def _serialize_knowledge(k_cfg: dict[str, Any]) -> dict[str, Any]:
    return {
        'id': k_cfg.get('id', ''),
        'name': k_cfg.get('name', ''),
        'description': k_cfg.get('description', ''),
        'paths': k_cfg.get('paths', []),
        'embedder': k_cfg.get('embedder', {}),
        'vector_db': k_cfg.get('vector_db', {}),
        '_ref': k_cfg.get('_ref', ''),
        '_raw': k_cfg,
    }


def list_knowledge_bases() -> list[dict[str, Any]]:
    configs = get_all_knowledge_configs()
    return [_serialize_knowledge(c) for c in configs]


def get_knowledge_base(knowledge_id: str) -> dict[str, Any] | None:
    for cfg in get_all_knowledge_configs():
        if cfg.get('id') == knowledge_id:
            return _serialize_knowledge(cfg)
    return None


def create_knowledge(payload: dict[str, Any]) -> dict[str, Any]:
    kb_id = payload.get('id') or f"kb-{uuid.uuid4().hex[:8]}"
    ref = payload.get('name', kb_id).lower().replace(' ', '-')

    new_cfg: dict[str, Any] = {
        'id': kb_id,
        'name': payload.get('name', ''),
        'description': payload.get('description', ''),
        'paths': payload.get('paths', []),
        'embedder': payload.get('embedder', {}),
        'vector_db': payload.get('vector_db', {}),
    }

    save_knowledge_config(ref, new_cfg)
    add_knowledge_ref(ref)
    new_cfg['_ref'] = ref
    return _serialize_knowledge(new_cfg)


def update_knowledge(knowledge_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    target = None
    for cfg in get_all_knowledge_configs():
        if cfg.get('id') == knowledge_id:
            target = cfg
            break
    if target is None:
        return None

    target['name'] = payload.get('name', target.get('name', ''))
    target['description'] = payload.get('description', target.get('description', ''))

    config = payload.get('config', {})
    if 'paths' in config:
        target['paths'] = config['paths']
    if 'embedder' in config:
        target['embedder'] = config['embedder']
    if 'vector_db' in config:
        target['vector_db'] = config['vector_db']

    ref = target.get('_ref', knowledge_id)
    save_knowledge_config(ref, target)
    return _serialize_knowledge(target)


def delete_knowledge(knowledge_id: str) -> bool:
    target = None
    for cfg in get_all_knowledge_configs():
        if cfg.get('id') == knowledge_id:
            target = cfg
            break
    if target is None:
        return False

    ref = target.get('_ref', knowledge_id)
    remove_knowledge_ref(ref)
    delete_kconfig_file(ref)
    return True
