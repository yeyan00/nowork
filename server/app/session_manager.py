"""
Session Compaction Manager

Implements logical session → physical session mapping.
A WorkerSession (logical) has multiple SessionSegments (physical agno sessions).
When token usage exceeds threshold, compaction is triggered:
1. LLM summarizes the old segment's runs
2. A new agno session + segment is created
3. Summary is injected as a prefix in subsequent user messages
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import Column, DateTime, Integer, String, Text, create_engine, Index, text
from sqlalchemy.orm import declarative_base, sessionmaker

from app.config import get_compaction_config, get_session_config, resolve_server_root, load_config

logger = logging.getLogger('nowork')

Base = declarative_base()


# =============================================================================
# SQLAlchemy Models
# =============================================================================

class WorkerSessionRow(Base):
    __tablename__ = 'worker_sessions'

    id = Column(String, primary_key=True)
    title = Column(String, default='')
    worker_id = Column(String, nullable=False, index=True)
    status = Column(String, default='active')  # active / archived
    model_override = Column(String, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))


class SessionSegmentRow(Base):
    __tablename__ = 'session_segments'

    id = Column(String, primary_key=True)
    worker_session_id = Column(String, nullable=False, index=True)
    agno_session_id = Column(String, nullable=False)
    segment_order = Column(Integer, default=0)
    run_count = Column(Integer, default=0)
    compaction_summary = Column(Text, nullable=True)
    compaction_meta = Column(Text, nullable=True)  # JSON
    status = Column(String, default='active')  # active → compacted → archived
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    compacted_at = Column(DateTime, nullable=True)

    __table_args__ = (
        Index('ix_segment_ws_order', 'worker_session_id', 'segment_order'),
    )


# =============================================================================
# Database Setup
# =============================================================================

_engine = None
_SessionLocal = None


def _get_db_path() -> Path:
    cfg = load_config()
    session_cfg = get_session_config(cfg)
    db_file = session_cfg.get('db_file', 'db/nowork_sessions.db')
    db_path = Path(db_file)
    if not db_path.is_absolute():
        db_path = resolve_server_root() / db_path
    return db_path


def _migrate_schema(engine) -> None:
    """Apply lightweight schema migrations for the session DB."""
    try:
        with engine.begin() as conn:
            cols = [row[1] for row in conn.execute(text('PRAGMA table_info(worker_sessions)')).fetchall()]
            if 'model_override' not in cols:
                conn.execute(text('ALTER TABLE worker_sessions ADD COLUMN model_override VARCHAR'))
    except Exception as e:
        logger.warning('Session DB schema migration skipped/failed: %s', e)



def _get_engine():
    global _engine
    if _engine is None:
        db_path = _get_db_path()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        _engine = create_engine(f'sqlite:///{db_path}', echo=False)
        Base.metadata.create_all(_engine)
        _migrate_schema(_engine)
    return _engine


def _get_session_factory():
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=_get_engine(), expire_on_commit=False)
    return _SessionLocal


def get_db_session():
    """Get a SQLAlchemy session for the session compaction database."""
    factory = _get_session_factory()
    return factory()


def reset_engine():
    """Reset the engine (useful for testing)."""
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()


def ensure_db():
    """Initialize the session compaction DB and create tables.

    Safe to call multiple times — no-op if already initialized.
    Called at server startup to guarantee the DB file exists.
    """
    _get_engine()


def migrate_legacy_session(session_id: str, title: str = '') -> dict[str, Any] | None:
    """Create a WorkerSession + Segment for a pre-existing agno session.

    For sessions created before session_manager was integrated, this
    creates the corresponding records in nowork_sessions.db so that
    compaction can work on them.

    Args:
        session_id: The existing agno/session id (format: worker_id:xxxx)
        title: Optional title for the session

    Returns:
        The created WorkerSession dict, or None if already exists.
    """
    # Check if already migrated
    existing = get_worker_session(session_id)
    if existing is not None:
        return None

    worker_id = session_id.split(':', 1)[0] if ':' in session_id else ''
    if not worker_id:
        return None

    now = datetime.now(timezone.utc)
    db = get_db_session()
    try:
        ws = WorkerSessionRow(
            id=session_id,
            title=title,
            worker_id=worker_id,
            status='active',
            model_override=None,
            created_at=now,
            updated_at=now,
        )
        db.add(ws)

        seg = SessionSegmentRow(
            id=str(uuid.uuid4()),
            worker_session_id=session_id,
            agno_session_id=session_id,  # same ID — the agno session already exists
            segment_order=0,
            run_count=0,
            status='active',
            created_at=now,
        )
        db.add(seg)
        db.commit()
        logger.info('Migrated legacy session %s → segment agno_session_id=%s', session_id, session_id)
        return _serialize_worker_session(ws)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


# =============================================================================
# WorkerSession CRUD
# =============================================================================

def create_worker_session(worker_id: str, title: str = '') -> dict[str, Any]:
    """Create a new WorkerSession and its first segment."""
    ws_id = f'{worker_id}:{uuid.uuid4().hex[:8]}'
    now = datetime.now(timezone.utc)

    db = get_db_session()
    try:
        ws = WorkerSessionRow(
            id=ws_id,
            title=title,
            worker_id=worker_id,
            status='active',
            model_override=None,
            created_at=now,
            updated_at=now,
        )
        db.add(ws)

        # Create first segment with a new agno session ID
        agno_session_id = f'{worker_id}:{uuid.uuid4().hex[:8]}'
        seg = SessionSegmentRow(
            id=str(uuid.uuid4()),
            worker_session_id=ws_id,
            agno_session_id=agno_session_id,
            segment_order=0,
            run_count=0,
            status='active',
            created_at=now,
        )
        db.add(seg)
        db.commit()

        return {
            'id': ws_id,
            'worker_id': worker_id,
            'title': title,
            'status': 'active',
            'model_override': None,
            'agno_session_id': agno_session_id,
            'segment_id': seg.id,
            'created_at': now.isoformat(),
        }
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def get_worker_session(ws_id: str) -> dict[str, Any] | None:
    """Get a WorkerSession by ID."""
    db = get_db_session()
    try:
        ws = db.query(WorkerSessionRow).filter(WorkerSessionRow.id == ws_id).first()
        if ws is None:
            return None
        return _serialize_worker_session(ws)
    finally:
        db.close()


def resolve_segment(session_id: str) -> dict[str, Any] | None:
    """Find the active segment for a session_id.

    Tries two lookups:
    1. session_id as WorkerSession.id (new sessions)
    2. session_id as Segment.agno_session_id (legacy sessions)
    """
    # Try as WorkerSession ID first
    seg = get_active_segment(session_id)
    if seg is not None:
        return seg

    # Fallback: look for a segment whose agno_session_id matches
    db = get_db_session()
    try:
        seg_row = (db.query(SessionSegmentRow)
                   .filter(SessionSegmentRow.agno_session_id == session_id,
                           SessionSegmentRow.status == 'active')
                   .order_by(SessionSegmentRow.segment_order.desc())
                   .first())
        if seg_row is not None:
            return _serialize_segment(seg_row)
        return None
    finally:
        db.close()


def list_worker_sessions(worker_id: str) -> list[dict[str, Any]]:
    """List all WorkerSessions for a worker."""
    db = get_db_session()
    try:
        rows = (db.query(WorkerSessionRow)
                .filter(WorkerSessionRow.worker_id == worker_id)
                .order_by(WorkerSessionRow.updated_at.desc())
                .all())
        return [_serialize_worker_session(ws) for ws in rows]
    finally:
        db.close()


def update_worker_session(ws_id: str, **kwargs) -> dict[str, Any] | None:
    """Update a WorkerSession."""
    db = get_db_session()
    try:
        ws = db.query(WorkerSessionRow).filter(WorkerSessionRow.id == ws_id).first()
        if ws is None:
            return None
        for key, value in kwargs.items():
            if hasattr(ws, key):
                setattr(ws, key, value)
        ws.updated_at = datetime.now(timezone.utc)
        db.commit()
        return _serialize_worker_session(ws)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _serialize_worker_session(ws: WorkerSessionRow) -> dict[str, Any]:
    return {
        'id': ws.id,
        'worker_id': ws.worker_id,
        'title': ws.title or '',
        'status': ws.status,
        'model_override': ws.model_override,
        'created_at': ws.created_at.isoformat() if ws.created_at else '',
        'updated_at': ws.updated_at.isoformat() if ws.updated_at else '',
    }


# =============================================================================
# SessionSegment CRUD
# =============================================================================

def get_active_segment(ws_id: str) -> dict[str, Any] | None:
    """Get the currently active segment for a WorkerSession."""
    db = get_db_session()
    try:
        seg = (db.query(SessionSegmentRow)
               .filter(SessionSegmentRow.worker_session_id == ws_id,
                       SessionSegmentRow.status == 'active')
               .order_by(SessionSegmentRow.segment_order.desc())
               .first())
        if seg is None:
            return None
        return _serialize_segment(seg)
    finally:
        db.close()


def get_compacted_segments(ws_id: str, limit: int | None = None) -> list[dict[str, Any]]:
    """Get compacted segments for summary injection, ordered by segment_order."""
    db = get_db_session()
    try:
        q = (db.query(SessionSegmentRow)
             .filter(SessionSegmentRow.worker_session_id == ws_id,
                     SessionSegmentRow.status == 'compacted')
             .order_by(SessionSegmentRow.segment_order.asc()))
        if limit:
            q = q.limit(limit)
        return [_serialize_segment(seg) for seg in q.all()]
    finally:
        db.close()


def get_all_segments(ws_id: str) -> list[dict[str, Any]]:
    """Get all segments for a WorkerSession, ordered by segment_order."""
    db = get_db_session()
    try:
        segs = (db.query(SessionSegmentRow)
                .filter(SessionSegmentRow.worker_session_id == ws_id)
                .order_by(SessionSegmentRow.segment_order.asc())
                .all())
        return [_serialize_segment(seg) for seg in segs]
    finally:
        db.close()


def increment_segment_run_count(seg_id: str) -> int:
    """Atomically increment the run_count of a segment. Returns new count."""
    db = get_db_session()
    try:
        seg = db.query(SessionSegmentRow).filter(SessionSegmentRow.id == seg_id).first()
        if seg is None:
            return 0
        seg.run_count += 1
        db.commit()
        return seg.run_count
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _serialize_segment(seg: SessionSegmentRow) -> dict[str, Any]:
    meta = None
    if seg.compaction_meta:
        try:
            meta = json.loads(seg.compaction_meta)
        except (json.JSONDecodeError, TypeError):
            meta = None
    return {
        'id': seg.id,
        'worker_session_id': seg.worker_session_id,
        'agno_session_id': seg.agno_session_id,
        'segment_order': seg.segment_order,
        'run_count': seg.run_count,
        'compaction_summary': seg.compaction_summary,
        'compaction_meta': meta,
        'status': seg.status,
        'created_at': seg.created_at.isoformat() if seg.created_at else '',
        'compacted_at': seg.compacted_at.isoformat() if seg.compacted_at else None,
    }


# =============================================================================
# Token Estimation
# =============================================================================

def estimate_segment_tokens_from_runs(runs: list[Any]) -> int:
    """Estimate total tokens from agno run objects.

    Uses metrics if available, falls back to word-count heuristic.
    """
    total = 0
    for run in runs:
        metrics = getattr(run, 'metrics', None)
        if metrics:
            total += getattr(metrics, 'input_tokens', 0) or 0
            total += getattr(metrics, 'output_tokens', 0) or 0
        else:
            # Fallback: rough char-to-token estimate (~4 chars per token)
            content = str(getattr(run, 'content', ''))
            total += max(len(content) // 4, 1)
    return total


def estimate_segment_tokens_by_count(run_count: int, avg_tokens_per_run: int = 500) -> int:
    """Quick estimate based on run count and average token usage."""
    return run_count * avg_tokens_per_run


# =============================================================================
# Compaction Threshold Check
# =============================================================================

def should_compact(segment: dict[str, Any], model: Any = None) -> bool:
    """Check if a segment should be compacted based on token threshold.

    Args:
        segment: Segment dict from get_active_segment()
        model: The agno model instance (for context_window info)

    Returns:
        True if compaction should be triggered
    """
    cfg = get_compaction_config()
    if not cfg.get('enabled', True):
        return False

    context_window = None
    if model is not None:
        context_window = getattr(model, 'context_window', None)
        # Also try to get from model config
        if context_window is None:
            context_window = getattr(model, '_context_window', None)

    threshold = cfg.get('context_usage_threshold', 0.75)
    reserve = cfg.get('context_reserve_tokens', 4000)

    if not context_window:
        context_window = 128000  # default context window if not specified

    token_limit = int(context_window * threshold - reserve)  # default 128K context window

    estimated_tokens = estimate_segment_tokens_by_count(
        segment.get('run_count', 0)
    )

    return estimated_tokens >= token_limit


# =============================================================================
# Compaction Execution
# =============================================================================

async def generate_compaction_summary(runs: list[Any], model: Any = None, is_team: bool = False) -> dict[str, Any]:
    """Generate a structured summary from runs using LLM.

    Returns:
        {
            'text': 'Human-readable summary',
            'structured': {
                'key_decisions': [...],
                'user_preferences': [...],
                'pending_tasks': [...],
                'context_points': [...]
            }
        }
    """
    cfg = get_compaction_config()
    summary_style = cfg.get('summary_style', 'structured')

    # Format runs for summarization
    conversation_text = _format_runs_for_summary(runs, is_team=is_team)

    if model is None:
        # Try to build a model from config
        from app.runtime import _build_model
        summary_model_ref = cfg.get('summary_model')
        model = _build_model(summary_model_ref)

    if model is None or not conversation_text:
        # Final fallback: simple truncation summary
        return _generate_simple_summary(runs, conversation_text)

    prompt = f"""You are a conversation summarizer. Your job is to produce a HIGHLY CONCISE summary that preserves KEY INFORMATION the assistant will need in future turns.

RULES:
- summary: 2-3 sentences max, covering the main topics and progress
- key_decisions: max 3 items, each under 50 characters
- user_preferences: max 3 items, each under 50 characters
- pending_tasks: max 3 items, each under 50 characters
- context_points: max 5 items, each under 100 characters. These are the MOST IMPORTANT facts, data, or conclusions that MUST be preserved. Do NOT copy raw text — ABSTRACT and CONDENSE.

Output strictly in this JSON format:
{{
  "summary": "...",
  "key_decisions": ["..."],
  "user_preferences": ["..."],
  "pending_tasks": ["..."],
  "context_points": ["..."]
}}

Conversation history:
{conversation_text}

Output JSON only, no other text."""

    try:
        from agno.models.message import Message
        user_msg = Message(role='user', content=prompt)
        assistant_msg = Message(role='assistant', content='')
        response = await model.ainvoke(
            messages=[user_msg],
            assistant_message=assistant_msg,
        )

        # Extract response text from ModelResponse
        content = ''
        if response and hasattr(response, 'content') and response.content:
            content = str(response.content)

        # Try to parse JSON from response
        content = content.strip()
        # Remove markdown code fences if present
        if content.startswith('```'):
            lines = content.split('\n')
            content = '\n'.join(lines[1:])
            if content.endswith('```'):
                content = content[:-3]
            content = content.strip()

        parsed = json.loads(content)
        return {
            'text': parsed.get('summary', content),
            'structured': {
                'key_decisions': parsed.get('key_decisions', []),
                'user_preferences': parsed.get('user_preferences', []),
                'pending_tasks': parsed.get('pending_tasks', []),
                'context_points': parsed.get('context_points', []),
            },
        }
    except Exception as e:
        logger.warning('LLM compaction summary failed, falling back to simple: %s', e)
        return _generate_simple_summary(runs, conversation_text)


def _format_runs_for_summary(runs: list[Any], max_total_chars: int = 20000, is_team: bool = False) -> str:
    """Format agno run objects into a readable conversation text.

    Captures ALL messages with smart truncation:
    - Recent messages (last 30%): keep up to 1200 chars each
    - Older messages (first 70%): keep up to 300 chars each
    - Total output capped at max_total_chars

    Args:
        runs: List of agno run/message objects
        max_total_chars: Maximum total characters for the formatted text
        is_team: If True, only include team-level runs (skip member runs)
    """
    if not runs:
        return ''

    # First pass: extract all messages from runs, flattening Run→messages
    raw_lines: list[tuple[int, str, str]] = []  # (idx, content, role)
    msg_idx = 0
    skip_roles = {'system', 'tool'}
    for run in runs:
        # For Team sessions, skip member runs — only summarize team-level conversation
        if is_team:
            agent_id = getattr(run, 'agent_id', None) or (run.get('agent_id') if isinstance(run, dict) else None)
            if agent_id:
                continue

        run_messages = getattr(run, 'messages', None)
        if run_messages is None:
            # Not a Run object — treat as a single message (legacy agent runs)
            role = getattr(run, 'role', 'unknown')
            content = str(getattr(run, 'content', ''))
            reasoning = str(getattr(run, 'reasoning_content', '') or '')
            parts = []
            if content:
                parts.append(content)
            if reasoning and len(reasoning) < 500:
                parts.append(f'(reasoning: {reasoning[:200]})')
            line_content = ' | '.join(parts)
            raw_lines.append((msg_idx, line_content, role))
            msg_idx += 1
        else:
            # Run object — flatten its messages
            for msg in run_messages:
                role = getattr(msg, 'role', 'unknown')
                if role in skip_roles:
                    continue
                content = str(getattr(msg, 'content', ''))
                reasoning = str(getattr(msg, 'reasoning_content', '') or '')

                parts = []
                if content:
                    parts.append(content)
                if reasoning and len(reasoning) < 500:
                    parts.append(f'(reasoning: {reasoning[:200]})')

                line_content = ' | '.join(parts)
                raw_lines.append((msg_idx, line_content, role))
                msg_idx += 1

    total_runs = len(raw_lines)
    split_point = int(total_runs * 0.7)  # Older = first 70%, recent = last 30%

    # Second pass: apply per-line truncation based on position
    lines: list[str] = []
    total_chars = 0
    for idx, line_content, role in raw_lines:
        if idx < split_point:
            per_line_limit = 300
        else:
            per_line_limit = 1200

        if len(line_content) > per_line_limit:
            line_content = line_content[:per_line_limit] + '...'

        formatted = f'[{role}]: {line_content}'
        lines.append(formatted)
        total_chars += len(formatted)

    # Third pass: if still over budget, proportionally trim older lines
    if total_chars > max_total_chars:
        result = '\n'.join(lines)
        # Keep the head (first few) and tail (most recent), trim middle
        if len(result) > max_total_chars:
            # Aggressive trim: keep first 10% and last 50% of budget
            head_budget = int(max_total_chars * 0.1)
            tail_budget = int(max_total_chars * 0.85)

            head_lines: list[str] = []
            tail_lines: list[str] = []
            head_used = 0
            tail_used = 0

            for line in lines:
                if head_used < head_budget:
                    head_lines.append(line)
                    head_used += len(line) + 1
                else:
                    tail_lines.append(line)

            # Take from tail
            tail_chars = '\n'.join(tail_lines)
            if len(tail_chars) > tail_budget:
                tail_chars = tail_chars[-tail_budget:]

            result = '\n'.join(head_lines) + '\n...\n' + tail_chars
            return result
        return result

    return '\n'.join(lines)


def _generate_simple_summary(runs: list[Any], conversation_text: str) -> dict[str, Any]:
    """Simple fallback summary without LLM."""
    # Count messages across all runs (runs may contain sub-messages)
    user_msgs = 0
    assistant_msgs = 0
    for run in runs:
        run_messages = getattr(run, 'messages', None)
        if run_messages is None:
            # Legacy single-message run
            role = getattr(run, 'role', '')
            if role == 'user':
                user_msgs += 1
            elif role == 'assistant':
                assistant_msgs += 1
        else:
            for msg in run_messages:
                role = getattr(msg, 'role', '')
                if role == 'user':
                    user_msgs += 1
                elif role == 'assistant':
                    assistant_msgs += 1

    # Take last 1500 chars as key context, but extract key lines
    tail = conversation_text[-1500:] if len(conversation_text) > 1500 else conversation_text
    # Only keep non-trivial lines
    key_lines = [l for l in tail.split('\n') if len(l.strip()) > 20][:10]

    return {
        'text': f'Conversation: {user_msgs} user msgs, {assistant_msgs} assistant msgs. Recent: {tail[-300:]}',
        'structured': {
            'key_decisions': [],
            'user_preferences': [],
            'pending_tasks': [],
            'context_points': key_lines[:5],
        },
    }


async def compact_segment(ws_id: str, old_segment: dict[str, Any],
                          runs: list[Any] = None, model: Any = None,
                          is_team: bool = False) -> dict[str, Any]:
    """Execute compaction: summarize old segment, create new segment.

    Args:
        ws_id: WorkerSession ID
        old_segment: The active segment to compact
        runs: Optional pre-loaded runs (if None, will try to load from agno)
        model: Optional model for summary generation
        is_team: If True, only summarize team-level runs (skip member runs)

    Returns:
        New segment dict
    """
    # Generate summary
    summary = await generate_compaction_summary(runs or [], model, is_team=is_team)

    now = datetime.now(timezone.utc)
    db = get_db_session()
    try:
        # Mark old segment as compacted
        old_seg = db.query(SessionSegmentRow).filter(
            SessionSegmentRow.id == old_segment['id']
        ).first()
        if old_seg is None:
            raise ValueError(f'Segment {old_segment["id"]} not found')

        old_seg.status = 'compacted'
        old_seg.compaction_summary = summary['text']
        old_seg.compaction_meta = json.dumps(summary['structured'], ensure_ascii=False)
        old_seg.compacted_at = now

        # Extract worker_id from ws_id for new agno session
        worker_id = ws_id.split(':', 1)[0] if ':' in ws_id else ws_id
        new_agno_session_id = f'{worker_id}:{uuid.uuid4().hex[:8]}'

        # Create new segment (use old_segment dict for values since it's already loaded)
        new_seg = SessionSegmentRow(
            id=str(uuid.uuid4()),
            worker_session_id=ws_id,
            agno_session_id=new_agno_session_id,
            segment_order=old_segment['segment_order'] + 1,
            run_count=0,
            status='active',
            created_at=now,
        )
        db.add(new_seg)

        # Update worker session timestamp
        ws = db.query(WorkerSessionRow).filter(WorkerSessionRow.id == ws_id).first()
        if ws:
            ws.updated_at = now

        db.commit()

        logger.info('Compacted segment %s → new segment %s (agno: %s)',
                     old_segment['id'], new_seg.id, new_agno_session_id)

        return _serialize_segment(new_seg)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


# =============================================================================
# Summary Injection
# =============================================================================

def get_compaction_summaries(ws_id: str) -> list[dict[str, Any]]:
    """Get compaction summaries for injection, limited by max_summaries_injected."""
    cfg = get_compaction_config()
    max_summaries = cfg.get('max_summaries_injected', 3)
    return get_compacted_segments(ws_id, limit=max_summaries)


def wrap_with_compaction(user_message: str, summaries: list[dict[str, Any]]) -> str:
    """Wrap user message with compaction summaries as prefix."""
    if not summaries:
        return user_message

    compaction_text = build_compaction_text(summaries)
    return (
        f"[System Injection - Prior Conversation Summary]\n"
        f"{compaction_text}\n"
        f"---\n"
        f"{user_message}"
    )


def unwrap_compaction_injection(content: str) -> str:
    """Remove [System Injection - Prior Conversation Summary] prefix from a user message.

    When compaction injects a summary prefix, agno stores the full wrapped message.
    When displaying to the user, we strip the injection to show only the original input.
    """
    if not content or not content.startswith('[System Injection - Prior Conversation Summary]'):
        return content
    # Find the separator line "---" and take everything after it
    idx = content.find('\n---\n')
    if idx >= 0:
        return content[idx + 5:].strip()
    return content


def build_compaction_text(summaries: list[dict[str, Any]]) -> str:
    """Build compact compaction text from summaries."""
    parts = []
    for seg in summaries:
        meta = seg.get('compaction_meta') or {}
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except Exception:
                meta = {}

        lines = [f"## Segment {seg.get('segment_order', 0) + 1}"]
        summary = seg.get('compaction_summary', '')
        if summary:
            lines.append(f"Summary: {summary[:300]}")
        for key, label in [('key_decisions', 'Decisions'), ('pending_tasks', 'Pending'), ('context_points', 'Key Info')]:
            items = meta.get(key, [])
            if items:
                lines.append(f"{label}: {'; '.join(str(i)[:100] for i in items[:5])}")
        parts.append('\n'.join(lines))
    return '\n\n'.join(parts)


# =============================================================================
# Full Chat Flow Integration
# =============================================================================

# =============================================================================
# Multi-segment message merging (for list_messages)
# =============================================================================

def list_messages_across_segments(ws_id: str, agno_db: Any, limit: int = 20, offset: int = 0) -> dict[str, Any]:
    """Load messages from all segments, merged in chronological order.

    Args:,
        ws_id: WorkerSession ID
        agno_db: The agno database instance for loading runs
        limit: Max messages to return
        offset: Offset from the end (latest messages)
    """
    segments = get_all_segments(ws_id)
    if not segments:
        return {'messages': [], 'total': 0, 'has_more': False}

    all_messages = []
    for seg in segments:
        runs = _load_runs_from_agno(agno_db, seg['agno_session_id'])
        all_messages.extend(runs)

    total = len(all_messages)
    start = max(0, total - offset - limit)
    end = total - offset
    has_more = start > 0

    return {
        'messages': all_messages[start:end],
        'total': total,
        'has_more': has_more,
    }


def _load_runs_from_agno(agno_db: Any, agno_session_id: str) -> list[Any]:
    """Load runs from agno database for a given session ID."""
    if agno_db is None or not hasattr(agno_db, 'get_session'):
        return []
    try:
        from agno.db.base import SessionType
        for session_type in (SessionType.AGENT, SessionType.TEAM):
            session_obj = agno_db.get_session(
                session_id=agno_session_id,
                session_type=session_type,
            )
            if session_obj is not None and hasattr(session_obj, 'runs'):
                return session_obj.runs or []
    except Exception as e:
        logger.debug('Failed to load runs for %s: %s', agno_session_id, e)
    return []
