"""SHA256 缓存管理 — Ingest 去重，检测文件变化。"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger('nowork')


def _sha256_file(path: str | Path) -> str:
    """计算文件的 SHA256 哈希。"""
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            h.update(chunk)
    return h.hexdigest()


class WikiCache:
    """Ingest 缓存管理。存储在 {kb_data_dir}/.cache/ingest-cache.json。"""

    def __init__(self, cache_dir: Path):
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_file = cache_dir / 'ingest-cache.json'
        self._cache: dict[str, dict[str, Any]] = self._load()

    def _load(self) -> dict[str, dict[str, Any]]:
        if self.cache_file.exists():
            try:
                return json.loads(self.cache_file.read_text(encoding='utf-8'))
            except (json.JSONDecodeError, OSError):
                return {}
        return {}

    def _save(self) -> None:
        self.cache_file.write_text(
            json.dumps(self._cache, ensure_ascii=False, indent=2),
            encoding='utf-8',
        )

    def check_cache(self, source_path: str) -> dict[str, Any] | None:
        """检查缓存。如果文件未变化，返回上次的 cached info；否则返回 None。
        
        Returns:
            None if file changed or not cached
            {"hash": ..., "files": [...], "timestamp": ...} if cached and unchanged
        """
        current_hash = _sha256_file(source_path)
        cached = self._cache.get(source_path)
        if cached is None:
            return None
        if cached.get('hash') == current_hash:
            return cached
        return None

    def save_cache(self, source_path: str, wiki_files: list[str]) -> None:
        """保存 Ingest 结果到缓存。"""
        self._cache[source_path] = {
            'hash': _sha256_file(source_path),
            'files': wiki_files,
            'timestamp': _now_iso(),
        }
        self._save()

    def remove_cache(self, source_path: str) -> None:
        """删除指定文件的缓存。"""
        self._cache.pop(source_path, None)
        self._save()

    def scan_changes(self, paths: list[str]) -> list[str]:
        """扫描目录/文件列表，返回有变化的文件路径。
        
        Args:
            paths: 目录或文件路径列表
        Returns:
            发生变化的文件绝对路径列表
        """
        changed: list[str] = []

        for p in paths:
            path = Path(p)
            if path.is_file():
                if self._file_changed(str(path)):
                    changed.append(str(path))
            elif path.is_dir():
                for f in path.rglob('*'):
                    if f.is_file() and _is_supported_file(f):
                        if self._file_changed(str(f)):
                            changed.append(str(f))

        return changed

    def _file_changed(self, file_path: str) -> bool:
        """检查单个文件是否有变化。"""
        cached = self._cache.get(file_path)
        if cached is None:
            return True  # 新文件
        try:
            current_hash = _sha256_file(file_path)
            return current_hash != cached.get('hash', '')
        except OSError:
            return False

    @property
    def all_cached_sources(self) -> list[str]:
        return list(self._cache.keys())


def _is_supported_file(path: Path) -> bool:
    """检查文件扩展名是否支持提取。"""
    supported = {
        '.md', '.txt', '.py', '.js', '.ts', '.json', '.yaml', '.yml',
        '.toml', '.csv', '.xml', '.html', '.css', '.sql', '.sh', '.bat',
        '.pdf', '.docx', '.pptx', '.xlsx',
        '.png', '.jpg', '.jpeg', '.gif', '.webp',
        '.go', '.rs', '.java', '.c', '.cpp', '.h', '.hpp',
        '.rb', '.php', '.swift', '.kt', '.r', '.R',
    }
    return path.suffix.lower() in supported


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
