from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

from app.config import resolve_config_dir

ENV_CONFIG_FILE = 'env.yaml'


def resolve_env_config_path() -> Path:
    return resolve_config_dir() / ENV_CONFIG_FILE


def _load_raw_env_config() -> dict[str, Any]:
    path = resolve_env_config_path()
    if not path.exists():
        return {}
    with path.open(encoding='utf-8') as f:
        data = yaml.safe_load(f) or {}
    return data if isinstance(data, dict) else {}


def _save_raw_env_config(data: dict[str, Any]) -> None:
    path = resolve_env_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8') as f:
        yaml.safe_dump(data, f, allow_unicode=True, sort_keys=True)


def _mask_value(value: str) -> str:
    if not value:
        return '••••'
    if len(value) <= 4:
        return '••••'
    return f'{value[:2]}••••{value[-2:]}'


def load_environment_variables() -> dict[str, str]:
    raw = _load_raw_env_config()
    variables = raw.get('variables', {})
    if not isinstance(variables, dict):
        return {}
    result: dict[str, str] = {}
    for key, value in variables.items():
        if isinstance(key, str) and key.strip() and isinstance(value, str):
            result[key.strip()] = value
    return result


def list_environment_variables() -> dict[str, Any]:
    variables = load_environment_variables()
    return {
        'variables': [
            {
                'name': name,
                'value': value,
                'hasValue': True,
                'maskedValue': _mask_value(value),
            }
            for name, value in sorted(variables.items())
        ],
    }


def save_environment_variables(changes: list[dict[str, Any]]) -> dict[str, Any]:
    current = load_environment_variables()
    for change in changes:
        if not isinstance(change, dict):
            continue
        name = str(change.get('name') or '').strip()
        if not name:
            continue
        if bool(change.get('remove')) or change.get('value') is None:
            current.pop(name, None)
            continue
        if 'value' in change:
            value = change.get('value')
            if isinstance(value, str) and value:
                current[name] = value
                continue
            if value == '':
                current.pop(name, None)
                continue
        if name not in current:
            continue
    _save_raw_env_config({'variables': current})
    return list_environment_variables()


async def apply_environment_variables(agent_os: Any | None) -> dict[str, Any]:
    from app import services

    variables = load_environment_variables()
    os.environ.update(variables)
    services.clear_all_session_runtime_cache()
    return {
        'applied': True,
        'activeRuns': 0,
        'reloadedWorkers': [],
        'variables': list_environment_variables()['variables'],
    }
