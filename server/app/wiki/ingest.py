"""Two-step Ingest pipeline — wiki-analyst + wiki-generator Agno Agents."""

from __future__ import annotations

import re
import logging
from pathlib import Path
from typing import Any
from uuid import uuid4

from agno.agent import Agent
from agno.run.cancel import cancel_run as _agno_cancel_run
from agno.exceptions import RunCancelledException as _AgnoCancelled

from app.wiki.repo import WikiRepository
from app.wiki.extract import extract_text
from app.wiki.cache import WikiCache
from app.wiki.prompts import (
    analysis_prompt, generation_prompt,
    ingest_run_message, ingest_generate_message, fallback_source_summary,
)

logger = logging.getLogger('nowork')


# ── Sync Cancellation ───────────────────────────────────────────

_active_run_ids: dict[str, set[str]] = {}
_sync_cancel_flags: dict[str, bool] = {}
_active_sync: set[str] = set()        # kb_ids currently syncing


def request_sync_cancel(kb_id: str) -> None:
    """Cancel a running sync by setting the flag and cancelling active Agno runs."""
    _sync_cancel_flags[kb_id] = True
    # Cancel any active Agno agent runs for this kb
    for run_id in list(_active_run_ids.get(kb_id, [])):
        try:
            _agno_cancel_run(run_id)
            logger.info('Cancelled Agno run %s for kb %s', run_id, kb_id)
        except Exception as e:
            logger.warning('Failed to cancel Agno run %s: %s', run_id, e)


def clear_sync_cancel(kb_id: str) -> None:
    """Clear cancellation flag (called when sync starts or ends)."""
    _sync_cancel_flags.pop(kb_id, None)
    _active_run_ids.pop(kb_id, None)


def _register_active_run(kb_id: str, run_id: str) -> None:
    """Track an active Agno run ID so it can be cancelled."""
    if kb_id not in _active_run_ids:
        _active_run_ids[kb_id] = set()
    _active_run_ids[kb_id].add(run_id)


def _unregister_active_run(kb_id: str, run_id: str) -> None:
    """Remove a completed Agno run ID."""
    if kb_id in _active_run_ids:
        _active_run_ids[kb_id].discard(run_id)


def _is_cancelled(kb_id: str) -> bool:
    return _sync_cancel_flags.get(kb_id, False)


class SyncCancelled(Exception):
    """Raised when a sync is cancelled by the user."""
    def __init__(self, kb_id: str):
        self.kb_id = kb_id
        super().__init__(f'Sync cancelled for {kb_id}')


def _check_cancelled(kb_id: str) -> None:
    """Raise SyncCancelled if the sync was cancelled."""
    if _is_cancelled(kb_id):
        raise SyncCancelled(kb_id)


# ── FILE Block Parsing ──────────────────────────────────────────

FILE_OPENER = re.compile(r'^---\s*FILE:\s*(.+?)\s*---\s*$', re.IGNORECASE)
FILE_CLOSER = re.compile(r'^---\s*END\s+FILE\s*---\s*$', re.IGNORECASE)
REVIEW_OPENER = re.compile(r'^---\s*REVIEW:\s*(.+?)\s*---\s*$', re.IGNORECASE)
REVIEW_CLOSER = re.compile(r'^---\s*END\s+REVIEW\s*---\s*$', re.IGNORECASE)


def parse_file_blocks(llm_output: str) -> list[tuple[str, str]]:
    """Parse ---FILE: path---...---END FILE--- blocks from LLM output.

    Returns: [(path, content), ...]
    """
    blocks: list[tuple[str, str]] = []
    warnings: list[str] = []

    lines = llm_output.split('\n')
    i = 0

    while i < len(lines):
        match = FILE_OPENER.match(lines[i].strip())
        if match:
            path = match.group(1).strip()
            content_lines: list[str] = []
            i += 1

            while i < len(lines):
                if FILE_CLOSER.match(lines[i].strip()):
                    i += 1
                    break
                content_lines.append(lines[i])
                i += 1

            content = '\n'.join(content_lines)

            # Security check
            if not path.startswith('wiki/'):
                warnings.append(f'Rejected path outside wiki/: {path}')
            elif '..' in path.split('/') or '..' in path.split('\\'):
                warnings.append(f'Rejected path with ..: {path}')
            else:
                blocks.append((path, content))
        else:
            i += 1

    if warnings:
        logger.warning('FILE block parse warnings: %s', warnings)

    return blocks


# ── Ingest Pipeline ─────────────────────────────────────────────

async def ingest_file(kb_id: str, source_path: str, model: Any,
                      force: bool = False, locale: str | None = None) -> list[str]:
    """Ingest a single file into the Wiki.

    Args:
        kb_id: Knowledge base ID.
        source_path: Absolute path to the source file.
        model: Agno Model instance.
        force: Force re-ingest (ignore cache).
        locale: Language code for prompts (e.g. "zh", "en").

    Returns:
        List of written Wiki page paths.

    Raises:
        SyncCancelled: If the sync was cancelled by the user.
    """
    _check_cancelled(kb_id)

    repo = WikiRepository(kb_id)
    cache = WikiCache(repo.cache_dir)

    # 1. Cache check
    if not force:
        cached = cache.check_cache(source_path)
        if cached is not None:
            logger.info('Cache hit for %s, skipping', source_path)
            return cached.get('files', [])

    _check_cancelled(kb_id)

    # 2. Extract text
    text = extract_text(source_path)
    if not text:
        logger.warning('No text extracted from %s', source_path)
        return []

    # Truncate overly long content
    if len(text) > 50000:
        text = text[:50000] + '\n\n[...truncated...]'

    # 3. Read context
    purpose = repo.read_purpose()
    index = repo.read_index()
    schema = repo.read_schema()
    overview = repo.read_overview()
    file_name = Path(source_path).name

    _check_cancelled(kb_id)

    # 4. Step 1: Analysis (expensive LLM call)
    #    Pre-generate run_id so we can cancel mid-flight via Agno's cancellation system
    analysis_run_id = str(uuid4())
    _register_active_run(kb_id, analysis_run_id)

    try:
        analyst = Agent(
            name='wiki-analyst',
            model=model,
            instructions=analysis_prompt(locale, purpose, index),
        )
        analysis = await analyst.arun(
            ingest_run_message(locale, file_name) + text,
            run_id=analysis_run_id,
        )
    except _AgnoCancelled:
        raise SyncCancelled(kb_id)
    finally:
        _unregister_active_run(kb_id, analysis_run_id)

    _check_cancelled(kb_id)

    # 5. Step 2: Generation (expensive LLM call)
    generation_run_id = str(uuid4())
    _register_active_run(kb_id, generation_run_id)

    analysis_text = getattr(analysis, 'content', None) or ''

    try:
        generator = Agent(
            name='wiki-generator',
            model=model,
            instructions=generation_prompt(
                locale, schema, purpose, index, file_name, overview,
            ),
        )
        generation = await generator.arun(
            ingest_generate_message(locale, file_name, analysis_text, text),
            run_id=generation_run_id,
        )
    except _AgnoCancelled:
        raise SyncCancelled(kb_id)
    finally:
        _unregister_active_run(kb_id, generation_run_id)

    _check_cancelled(kb_id)

    # 6. Parse and write
    gen_text = getattr(generation, 'content', None) or ''
    blocks = parse_file_blocks(gen_text)
    written: list[str] = []
    for path, content in blocks:
        if repo.write_page(path, content):
            written.append(path)

    # Fallback: create a basic source summary if none was generated
    source_base = Path(source_path).stem
    if not any('sources/' in p for p in written):
        fb = fallback_source_summary(locale, file_name, file_name)
        repo.write_page(f'wiki/sources/{source_base}.md', fb)
        written.append(f'wiki/sources/{source_base}.md')

    # 7. Append to log
    repo.append_log(file_name)

    # 8. Update cache
    cache.save_cache(source_path, written)

    # 9. Bump graph version
    repo.bump_version()

    logger.info('Ingested %s -> %d wiki pages', file_name, len(written))
    return written


async def sync_knowledge_base(kb_id: str, model: Any,
                              force: bool = False) -> list[str]:
    """Sync all associated directories of a knowledge base.

    Args:
        kb_id: Knowledge base ID.
        model: Agno Model instance.
        force: Force re-ingest.

    Returns:
        List of all written Wiki page paths.

    Raises:
        SyncCancelled: If the sync was cancelled by the user.
    """
    # Prevent concurrent syncs for the same KB
    if kb_id in _active_sync:
        raise ValueError(f'Sync already in progress for {kb_id}')
    _active_sync.add(kb_id)

    # Clear any stale cancel flag from a previous run
    clear_sync_cancel(kb_id)

    try:
        return await _sync_knowledge_base_inner(kb_id, model, force)
    finally:
        _active_sync.discard(kb_id)


async def _sync_knowledge_base_inner(kb_id: str, model: Any,
                                     force: bool = False) -> list[str]:
    """Inner implementation of sync_knowledge_base (called under lock)."""
    # Find the knowledge base config
    kb_cfg = None
    for cfg_raw in _get_all_kb_configs():
        if cfg_raw.get('id') == kb_id:
            kb_cfg = cfg_raw
            break
    if not kb_cfg:
        return []

    paths = kb_cfg.get('paths', [])
    locale = kb_cfg.get('language', None)  # e.g. "zh", "en"
    if not paths:
        return []

    repo = WikiRepository(kb_id)
    cache = WikiCache(repo.cache_dir)

    # Scan for changed files
    changed = cache.scan_changes(paths) if not force else _list_all_files(paths)

    if not changed:
        logger.info('No changes detected for kb %s', kb_id)
        return []

    logger.info('Found %d changed files for kb %s', len(changed), kb_id)

    # Serial ingest — check cancellation between each file
    all_written: list[str] = []
    try:
        for file_path in changed:
            _check_cancelled(kb_id)
            try:
                written = await ingest_file(
                    kb_id, file_path, model, force=force, locale=locale,
                )
                all_written.extend(written)
            except SyncCancelled:
                raise
            except Exception as e:
                logger.error('Failed to ingest %s: %s', file_path, e)
    except SyncCancelled:
        # Only clear the cancel flag — active run IDs are already cleaned up
        # by each ingest_file's finally block. Do NOT clear _active_run_ids
        # here because a new sync could have already started registering IDs.
        _sync_cancel_flags.pop(kb_id, None)
        raise

    return all_written


def _get_all_kb_configs() -> list[dict]:
    from app.config import get_all_knowledge_configs
    return get_all_knowledge_configs()


def _list_all_files(paths: list[str]) -> list[str]:
    """List all supported files under the given paths."""
    from app.wiki.cache import _is_supported_file
    files: list[str] = []
    for p in paths:
        path = Path(p)
        if path.is_file():
            files.append(str(path))
        elif path.is_dir():
            for f in path.rglob('*'):
                if f.is_file() and _is_supported_file(f):
                    files.append(str(f))
    return files
