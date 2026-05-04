"""
File system API for workspace file browsing and preview.

Provides endpoints to:
  - List directory contents
  - Read file content (text)
  - Read file content (binary, for images)
  - Get file/directory metadata (stat)
"""

import logging
import os
import stat as stat_mod
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query

logger = logging.getLogger('nowork')

router = APIRouter(prefix='/api/fs', tags=['filesystem'])

# ── Helpers ──────────────────────────────────────────────────────

MAX_READ_SIZE = 2 * 1024 * 1024  # 2 MB text read limit
MAX_BINARY_SIZE = 10 * 1024 * 1024  # 10 MB binary read limit

# Directories to always skip when listing
SKIP_DIR_NAMES = frozenset({
    'node_modules', '.git', '__pycache__', '.pytest_cache',
    '.mypy_cache', '.ruff_cache', '.tox', '.venv', 'venv',
    'dist', 'build', '.next', '.turbo', '.cache', '.gradle',
    'target', '.idea', '.vscode', '.pi',
})

# File extensions that should be served as binary
BINARY_EXTENSIONS = frozenset({
    '.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg', '.ico',
    '.bmp', '.avif', '.pdf', '.zip', '.tar', '.gz', '.rar',
    '.7z', '.woff', '.woff2', '.ttf', '.eot', '.mp3', '.mp4',
    '.wav', '.avi', '.mov', '.exe', '.dll', '.so', '.dylib',
})

# Text extensions we consider safe to read as utf-8
TEXT_EXTENSIONS = frozenset({
    '.txt', '.md', '.markdown', '.rst', '.adoc',
    '.json', '.jsonc', '.json5', '.yaml', '.yml', '.toml',
    '.py', '.js', '.jsx', '.ts', '.tsx', '.mjs', '.cjs',
    '.html', '.htm', '.css', '.scss', '.sass', '.less',
    '.vue', '.svelte', '.astro',
    '.sh', '.bash', '.zsh', '.fish', '.ps1', '.bat', '.cmd',
    '.sql', '.graphql', '.gql',
    '.java', '.kt', '.kts', '.scala', '.groovy',
    '.c', '.h', '.cpp', '.hpp', '.cc', '.cxx',
    '.go', '.rs', '.rb', '.php', '.swift', '.dart',
    '.lua', '.r', '.R', '.m', '.mm',
    '.xml', '.svg', '.ini', '.cfg', '.conf', '.env',
    '.dockerfile', '.makefile', '.cmake',
    '.gitignore', '.gitattributes', '.editorconfig',
    '.lock', '.log',
})


def _normalize_path(raw: str) -> str:
    """Normalize a file path: expand ~, resolve, strip trailing slashes, forward slashes."""
    # Expand ~ to home directory (works on Windows and Unix)
    expanded = os.path.expanduser(raw)
    p = os.path.normpath(expanded.replace('\\', '/'))
    # On Windows, normpath may produce backslashes — keep forward slashes for consistency
    return p.replace('\\', '/')


def _is_path_within_root(path: str, root: str) -> bool:
    """Check that `path` is within `root` (prevents path traversal)."""
    try:
        resolved = os.path.realpath(path)
        root_resolved = os.path.realpath(root)
        return resolved.startswith(root_resolved + os.sep) or resolved == root_resolved
    except (OSError, ValueError):
        return False


def _is_text_file(path: str) -> bool:
    """Heuristic: decide if a file should be read as utf-8 text."""
    ext = Path(path).suffix.lower()
    if ext in TEXT_EXTENSIONS:
        return True
    if ext in BINARY_EXTENSIONS:
        return False
    # No known extension: try to detect by first 1024 bytes
    try:
        with open(path, 'rb') as f:
            chunk = f.read(1024)
        # Simple heuristic: if no null bytes in first 1024, treat as text
        return b'\x00' not in chunk
    except (OSError, PermissionError):
        return False


def _entry_stat(entry_path: str) -> dict[str, Any]:
    """Stat a single file/directory entry, returning metadata dict."""
    try:
        st = os.stat(entry_path)
        return {
            'name': os.path.basename(entry_path),
            'path': _normalize_path(entry_path),
            'isDirectory': stat_mod.S_ISDIR(st.st_mode),
            'isFile': stat_mod.S_ISREG(st.st_mode),
            'size': st.st_size,
            'mtimeMs': int(st.st_mtime * 1000),
        }
    except (OSError, PermissionError):
        return {
            'name': os.path.basename(entry_path),
            'path': _normalize_path(entry_path),
            'isDirectory': False,
            'isFile': False,
            'size': 0,
            'mtimeMs': 0,
        }


# ── Endpoints ────────────────────────────────────────────────────

@router.get('/list')
def list_directory(
    path: str = Query(..., description='Directory path to list'),
    respectGitignore: bool = Query(False, description='Skip gitignored entries'),
    showHidden: bool = Query(False, description='Show hidden files/dirs'),
) -> dict[str, Any]:
    """List contents of a directory."""
    normalized = _normalize_path(path)

    if not os.path.isdir(normalized):
        raise HTTPException(status_code=400, detail=f'Not a directory: {normalized}')

    try:
        entries = []
        for name in os.listdir(normalized):
            # Skip hidden
            if not showHidden and name.startswith('.'):
                continue
            # Skip known heavy dirs
            if name in SKIP_DIR_NAMES:
                continue

            entry_path = os.path.join(normalized, name)
            info = _entry_stat(entry_path)
            # Skip symlinks that don't resolve
            if not info['isFile'] and not info['isDirectory']:
                continue
            entries.append(info)

        # Sort: directories first, then files, alphabetical within each group
        entries.sort(key=lambda e: (not e['isDirectory'], e['name'].lower()))

        return {
            'path': _normalize_path(normalized),
            'entries': entries,
        }
    except PermissionError:
        raise HTTPException(status_code=403, detail=f'Permission denied: {normalized}')
    except OSError as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get('/read')
def read_file(
    path: str = Query(..., description='File path to read'),
    encoding: str = Query('utf-8', description='Text encoding'),
) -> dict[str, Any]:
    """Read a text file and return its content."""
    normalized = _normalize_path(path)

    if not os.path.isfile(normalized):
        raise HTTPException(status_code=400, detail=f'Not a file: {normalized}')

    file_size = os.path.getsize(normalized)
    if file_size > MAX_READ_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f'File too large: {file_size} bytes (max {MAX_READ_SIZE})',
        )

    if not _is_text_file(normalized):
        raise HTTPException(
            status_code=400,
            detail='Binary file — use /api/fs/raw endpoint instead',
        )

    try:
        with open(normalized, 'r', encoding=encoding, errors='replace') as f:
            content = f.read()

        return {
            'path': _normalize_path(normalized),
            'content': content,
            'size': file_size,
            'encoding': encoding,
        }
    except PermissionError:
        raise HTTPException(status_code=403, detail=f'Permission denied: {normalized}')
    except OSError as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get('/raw')
def read_raw_file(
    path: str = Query(..., description='File path to read as binary'),
) -> dict[str, Any]:
    """Read a binary file and return base64-encoded content."""
    import base64

    normalized = _normalize_path(path)

    if not os.path.isfile(normalized):
        raise HTTPException(status_code=400, detail=f'Not a file: {normalized}')

    file_size = os.path.getsize(normalized)
    if file_size > MAX_BINARY_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f'File too large: {file_size} bytes (max {MAX_BINARY_SIZE})',
        )

    try:
        with open(normalized, 'rb') as f:
            raw = f.read()

        import mimetypes
        mime_type, _ = mimetypes.guess_type(normalized)

        return {
            'path': _normalize_path(normalized),
            'dataUrl': f'data:{mime_type or "application/octet-stream"};base64,{base64.b64encode(raw).decode("ascii")}',
            'size': file_size,
            'mimeType': mime_type,
        }
    except PermissionError:
        raise HTTPException(status_code=403, detail=f'Permission denied: {normalized}')
    except OSError as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get('/stat')
def stat_file(
    path: str = Query(..., description='File or directory path'),
) -> dict[str, Any]:
    """Get metadata for a file or directory."""
    normalized = _normalize_path(path)

    if not os.path.exists(normalized):
        raise HTTPException(status_code=404, detail=f'Not found: {normalized}')

    return _entry_stat(normalized)
