"""Channel API routes for nowork."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from app.channels.schema import SUPPORTED_PLATFORMS

logger = logging.getLogger('nowork.channels')

router = APIRouter(prefix='/api/channels', tags=['channels'])


def _get_manager(request: Request):
    mgr = getattr(request.app.state, 'channel_manager', None)
    if mgr is None:
        raise HTTPException(status_code=503, detail='Channel manager not initialized')
    return mgr


@router.get('')
def api_list_channels(request: Request) -> list[dict[str, Any]]:
    from app.config import load_channels_config
    configs = load_channels_config()
    mgr = _get_manager(request)
    result = []
    for raw in configs:
        cfg_id = raw.get('id', '')
        instance = mgr.get_channel(cfg_id)
        result.append({
            **raw,
            'status': instance.status if instance else 'stopped',
            'detail': instance.detail if instance else '',
        })
    return result


@router.get('/platforms')
def api_list_platforms() -> list[dict[str, Any]]:
    from app.channels.registry import list_platforms as _list_platforms
    platforms = _list_platforms()
    return [
        {'id': p, 'name': _platform_display_name(p), 'available': True}
        for p in SUPPORTED_PLATFORMS
        if p in platforms
    ] + [
        {'id': p, 'name': _platform_display_name(p), 'available': False}
        for p in SUPPORTED_PLATFORMS
        if p not in platforms
    ]


@router.get('/{channel_id}')
def api_get_channel(channel_id: str, request: Request) -> dict[str, Any]:
    from app.config import load_channels_config
    configs = load_channels_config()
    for raw in configs:
        if raw.get('id') == channel_id:
            mgr = _get_manager(request)
            instance = mgr.get_channel(channel_id)
            return {
                **raw,
                'status': instance.status if instance else 'stopped',
                'detail': instance.detail if instance else '',
            }
    raise HTTPException(status_code=404, detail='Channel not found')


# Per-platform key used for business dedup (worker_id + platform app key)
_PLATFORM_UNIQUE_KEYS = {
    'dingtalk': 'client_id',
    'feishu': 'app_id',
    'wecom': 'bot_id',
}


def _check_business_duplicate(
    configs: list[dict], platform: str, worker_id: str, config: dict,
    exclude_id: str | None = None,
) -> str | None:
    """Return an error message if the same worker is already bound to the same
    platform app, or None if no conflict."""
    unique_key = _PLATFORM_UNIQUE_KEYS.get(platform)
    if not unique_key:
        return None
    app_key_value = config.get(unique_key, '').strip()
    if not app_key_value:
        return None  # can't check without the key
    for c in configs:
        if exclude_id and c.get('id') == exclude_id:
            continue
        if (c.get('platform') == platform
                and c.get('worker_id') == worker_id
                and c.get('config', {}).get(unique_key, '') == app_key_value):
            return (
                f'Worker "{worker_id}" already has a {platform} channel '
                f'with {unique_key}="{app_key_value}" (channel: {c.get("id")})'
            )
    return None


@router.post('', status_code=201)
async def api_create_channel(request: Request) -> dict[str, Any]:
    from app.config import load_channels_config, save_channels_config
    body = await request.json()
    channel_id = body.get('id', '').strip()
    platform = body.get('platform', '').strip()
    worker_id = body.get('worker_id', '').strip()
    if not channel_id:
        raise HTTPException(status_code=400, detail='id is required')
    if not worker_id:
        raise HTTPException(status_code=400, detail='worker_id is required')
    if platform not in SUPPORTED_PLATFORMS:
        raise HTTPException(status_code=400, detail=f'Unsupported platform: {platform}')
    configs = load_channels_config()
    existing_ids = {c.get('id') for c in configs}
    if channel_id in existing_ids:
        raise HTTPException(status_code=409, detail=f'Channel id "{channel_id}" already exists')
    # Business dedup: same worker + same platform app key
    dup_msg = _check_business_duplicate(
        configs, platform, worker_id, body.get('config', {}))
    if dup_msg:
        raise HTTPException(status_code=409, detail=dup_msg)
    new_channel = {
        'id': channel_id,
        'platform': platform,
        'name': body.get('name', ''),
        'enabled': body.get('enabled', False),
        'worker_id': worker_id,
        'config': body.get('config', {}),
    }
    configs.append(new_channel)
    save_channels_config(configs)
    if new_channel['enabled']:
        try:
            from app.channels.schema import ChannelConfig
            cfg = ChannelConfig(**new_channel)
            mgr = _get_manager(request)
            await mgr.start_channel(cfg)
        except Exception as e:
            logger.exception('Failed to start channel %s: %s', channel_id, e)
    return new_channel


@router.put('/{channel_id}')
async def api_update_channel(channel_id: str, request: Request) -> dict[str, Any]:
    from app.config import load_channels_config, save_channels_config
    from app.channels.schema import ChannelConfig
    body = await request.json()
    configs = load_channels_config()
    found = None
    for i, raw in enumerate(configs):
        if raw.get('id') == channel_id:
            found = i
            break
    if found is None:
        raise HTTPException(status_code=404, detail='Channel not found')
    existing = configs[found]
    was_enabled = existing.get('enabled', False)
    if 'name' in body:
        existing['name'] = body['name']
    if 'enabled' in body:
        existing['enabled'] = body['enabled']
    if 'worker_id' in body:
        existing['worker_id'] = body['worker_id']
    if 'config' in body:
        existing['config'] = body['config']
    # Business dedup on update
    upd_platform = existing.get('platform', '')
    upd_worker = existing.get('worker_id', '')
    dup_msg = _check_business_duplicate(
        configs, upd_platform, upd_worker, existing.get('config', {}),
        exclude_id=channel_id)
    if dup_msg:
        raise HTTPException(status_code=409, detail=dup_msg)
    configs[found] = existing
    save_channels_config(configs)
    mgr = _get_manager(request)
    is_enabled = existing.get('enabled', False)
    if is_enabled:
        try:
            cfg = ChannelConfig(**existing)
            await mgr.restart_channel(cfg)
        except Exception as e:
            logger.exception('Failed to restart channel %s: %s', channel_id, e)
    elif was_enabled:
        instance = mgr.get_channel(channel_id)
        if instance:
            try:
                await instance.stop()
                instance._status = 'stopped'
            except Exception as e:
                logger.exception('Failed to stop channel %s: %s', channel_id, e)
    return existing


@router.delete('/{channel_id}')
async def api_delete_channel(channel_id: str, request: Request) -> dict[str, Any]:
    from app.config import load_channels_config, save_channels_config
    configs = load_channels_config()
    new_configs = [c for c in configs if c.get('id') != channel_id]
    if len(new_configs) == len(configs):
        raise HTTPException(status_code=404, detail='Channel not found')
    save_channels_config(new_configs)
    mgr = _get_manager(request)
    instance = mgr.get_channel(channel_id)
    if instance:
        try:
            await instance.stop()
        except Exception:
            pass
    return {'ok': True, 'id': channel_id}


@router.post('/{channel_id}/test')
async def api_test_channel(channel_id: str, request: Request) -> dict[str, Any]:
    mgr = _get_manager(request)
    instance = mgr.get_channel(channel_id)
    if instance is None:
        return {'ok': False, 'error': 'Channel not running'}
    try:
        health = await instance.health_check()
        return {'ok': health.get('status') == 'running', **health}
    except Exception as e:
        return {'ok': False, 'error': str(e)}


def _platform_display_name(platform: str) -> str:
    names = {
        'dingtalk': '钉钉',
        'feishu': '飞书',
        'wecom': '企业微信',
    }
    return names.get(platform, platform)
