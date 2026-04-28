"""Two-step Ingest pipeline — wiki-analyst + wiki-generator Agno Agents."""

from __future__ import annotations

import re
import logging
from datetime import date
from pathlib import Path
from typing import Any

from app.wiki.repo import WikiRepository
from app.wiki.extract import extract_text
from app.wiki.cache import WikiCache
from app.wiki.prompts import (
    analysis_prompt, generation_prompt,
    ingest_run_message, ingest_generate_message, fallback_source_summary,
)

logger = logging.getLogger('nowork')


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
    """
    from agno.agent import Agent

    repo = WikiRepository(kb_id)
    cache = WikiCache(repo.cache_dir)

    # 1. Cache check
    if not force:
        cached = cache.check_cache(source_path)
        if cached is not None:
            logger.info('Cache hit for %s, skipping', source_path)
            return cached.get('files', [])

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

    # 4. Step 1: Analysis
    analyst = Agent(
        name='wiki-analyst',
        model=model,
        instructions=analysis_prompt(locale, purpose, index),
    )
    analysis = await analyst.arun(
        ingest_run_message(locale, file_name) + text,
    )

    # 5. Step 2: Generation
    generator = Agent(
        name='wiki-generator',
        model=model,
        instructions=generation_prompt(
            locale, schema, purpose, index, file_name, overview,
        ),
    )
    generation = await generator.arun(
        ingest_generate_message(locale, file_name, analysis.content, text),
    )

    # 6. Parse and write
    blocks = parse_file_blocks(generation.content)
    written: list[str] = []
    for path, content in blocks:
        if repo.write_page(path, content):
            written.append(path)

    # Fallback: create a basic source summary if none was generated
    source_base = Path(source_path).stem
    if not any('sources/' in p for p in written):
        fb = fallback_source_summary(locale, file_name, source_path)
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
    """
    from app.config import load_knowledge_config, list_knowledge_refs

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

    # Serial ingest
    all_written: list[str] = []
    for file_path in changed:
        try:
            written = await ingest_file(
                kb_id, file_path, model, force=force, locale=locale,
            )
            all_written.extend(written)
        except Exception as e:
            logger.error('Failed to ingest %s: %s', file_path, e)

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
