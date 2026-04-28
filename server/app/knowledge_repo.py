from __future__ import annotations

import logging
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

logger = logging.getLogger('nowork')


def _serialize_knowledge(k_cfg: dict[str, Any]) -> dict[str, Any]:
    wiki_mode = k_cfg.get('wiki_mode', False)

    result = {
        'id': k_cfg.get('id', ''),
        'name': k_cfg.get('name', ''),
        'description': k_cfg.get('description', ''),
        'paths': k_cfg.get('paths', []),
        'embedder': k_cfg.get('embedder', {}),
        'vector_db': k_cfg.get('vector_db', {}),
        'wiki_mode': wiki_mode,
        'purpose': k_cfg.get('purpose', ''),
        'auto_sync': k_cfg.get('auto_sync', False),
        'language': k_cfg.get('language', ''),
        '_ref': k_cfg.get('_ref', ''),
        '_raw': k_cfg,
    }

    # 为 Wiki 模式附加统计数据
    if wiki_mode:
        try:
            from app.wiki.repo import WikiRepository
            repo = WikiRepository(k_cfg.get('id', ''))
            result['wiki_stats'] = repo.get_stats()
        except Exception:
            result['wiki_stats'] = {'total': 0, 'by_type': {}, 'last_updated': ''}

    return result


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
        'wiki_mode': payload.get('wiki_mode', False),
        'purpose': payload.get('purpose', ''),
        'auto_sync': payload.get('auto_sync', False),
        'language': payload.get('language', ''),
    }

    save_knowledge_config(ref, new_cfg)
    add_knowledge_ref(ref)
    new_cfg['_ref'] = ref

    # 如果是 Wiki 模式，初始化目录结构
    if new_cfg.get('wiki_mode', False):
        try:
            from app.wiki.repo import WikiRepository
            repo = WikiRepository(kb_id)
            repo.ensure_structure()
            # 写入 purpose
            purpose = new_cfg.get('purpose', '')
            if purpose:
                repo.write_purpose(purpose)
            logger.info('Wiki directory initialized for kb %s', kb_id)
        except Exception as e:
            logger.warning('Failed to initialize wiki directory for kb %s: %s', kb_id, e)

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

    # Wiki 模式字段
    if 'wiki_mode' in payload:
        target['wiki_mode'] = payload['wiki_mode']
    elif 'config' in payload and 'wiki_mode' in payload['config']:
        target['wiki_mode'] = payload['config']['wiki_mode']
    if 'purpose' in payload:
        target['purpose'] = payload['purpose']
    elif 'config' in payload and 'purpose' in payload['config']:
        target['purpose'] = payload['config']['purpose']
    if 'auto_sync' in payload:
        target['auto_sync'] = payload['auto_sync']
    elif 'config' in payload and 'auto_sync' in payload['config']:
        target['auto_sync'] = payload['config']['auto_sync']
    if 'language' in payload:
        target['language'] = payload['language']
    elif 'config' in payload and 'language' in payload['config']:
        target['language'] = payload['config']['language']

    # 初始化 Wiki 目录（首次开启 wiki_mode）
    if target.get('wiki_mode', False):
        try:
            from app.wiki.repo import WikiRepository
            repo = WikiRepository(knowledge_id)
            repo.ensure_structure()
            purpose = target.get('purpose', '')
            if purpose:
                repo.write_purpose(purpose)
        except Exception as e:
            logger.warning('Failed to ensure wiki structure for kb %s: %s', knowledge_id, e)

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

    # 清理 Wiki 数据目录
    if target.get('wiki_mode', False):
        try:
            from app.wiki.repo import WikiRepository
            repo = WikiRepository(knowledge_id)
            repo.destroy()
            logger.info('Wiki data destroyed for kb %s', knowledge_id)
        except Exception as e:
            logger.warning('Failed to destroy wiki data for kb %s: %s', knowledge_id, e)

    ref = target.get('_ref', knowledge_id)
    remove_knowledge_ref(ref)
    delete_kconfig_file(ref)
    return True
