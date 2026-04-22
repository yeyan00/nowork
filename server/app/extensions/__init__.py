from __future__ import annotations

import importlib
import logging
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger('nowork')

_EXTENSIONS: dict[str, ExtensionMeta] = {}


@dataclass
class ExtensionMeta:
    id: str
    name: str
    description: str
    category: str
    pip_packages: list[str]
    import_check: str
    install_size: str
    status: str = 'not_installed'
    version: str = ''


def _register(ext: ExtensionMeta) -> None:
    _EXTENSIONS[ext.id] = ext


def _check_installed(ext: ExtensionMeta) -> bool:
    try:
        importlib.import_module(ext.import_check)
        return True
    except ImportError:
        return False


def list_extensions() -> list[dict[str, Any]]:
    results = []
    for ext in _EXTENSIONS.values():
        installed = _check_installed(ext)
        ext_copy = ExtensionMeta(
            id=ext.id,
            name=ext.name,
            description=ext.description,
            category=ext.category,
            pip_packages=ext.pip_packages,
            import_check=ext.import_check,
            install_size=ext.install_size,
            status='installed' if installed else 'not_installed',
            version=_get_version(ext) if installed else '',
        )
        results.append({
            'id': ext_copy.id,
            'name': ext_copy.name,
            'description': ext_copy.description,
            'category': ext_copy.category,
            'pip_packages': ext_copy.pip_packages,
            'install_size': ext_copy.install_size,
            'status': ext_copy.status,
            'version': ext_copy.version,
        })
    return results


def get_extension(ext_id: str) -> dict[str, Any] | None:
    for ext in list_extensions():
        if ext['id'] == ext_id:
            return ext
    return None


def install_extension(ext_id: str) -> dict[str, Any]:
    ext = _EXTENSIONS.get(ext_id)
    if ext is None:
        return {'ok': False, 'error': 'Extension not found'}

    try:
        cmd = [sys.executable, '-m', 'pip', 'install', *ext.pip_packages, '--quiet']
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            return {'ok': False, 'error': result.stderr.strip() or 'pip install failed'}
        installed = _check_installed(ext)
        return {'ok': installed, 'error': '' if installed else 'Install succeeded but import check failed'}
    except subprocess.TimeoutExpired:
        return {'ok': False, 'error': 'Installation timed out'}
    except Exception as e:
        return {'ok': False, 'error': str(e)}


def uninstall_extension(ext_id: str) -> dict[str, Any]:
    ext = _EXTENSIONS.get(ext_id)
    if ext is None:
        return {'ok': False, 'error': 'Extension not found'}

    try:
        cmd = [sys.executable, '-m', 'pip', 'uninstall', '-y', *ext.pip_packages, '--quiet']
        subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        return {'ok': True, 'error': ''}
    except Exception as e:
        return {'ok': False, 'error': str(e)}


def _get_version(ext: ExtensionMeta) -> str:
    try:
        mod = importlib.import_module(ext.import_check)
        return getattr(mod, '__version__', 'unknown')
    except Exception:
        return ''


def is_extension_available(ext_id: str) -> bool:
    ext = _EXTENSIONS.get(ext_id)
    if ext is None:
        return False
    return _check_installed(ext)


_register(ExtensionMeta(
    id='sentence-transformer',
    name='Sentence Transformer (Local Embedding)',
    description='Local embedding model for Knowledge vector DB. Uses all-MiniLM-L6-v2 (~80MB). No API key needed.',
    category='embedding',
    pip_packages=['sentence-transformers'],
    import_check='sentence_transformers',
    install_size='~500MB',
))

_register(ExtensionMeta(
    id='local-vector-db',
    name='Milvus Lite (Local Vector DB)',
    description='Lightweight local vector database (SQLite-based). Required for Knowledge system.',
    category='vector_db',
    pip_packages=['pymilvus'],
    import_check='pymilvus',
    install_size='~50MB',
))
