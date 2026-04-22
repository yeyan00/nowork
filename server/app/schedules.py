from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import HTTPException

from app.config import SERVER_RUNTIME_DIR
from app import repository

logger = logging.getLogger('nowork')

SCHEDULES_FILE = SERVER_RUNTIME_DIR / 'schedules.json'
MISFIRE_GRACE_SECONDS = 300


@dataclass
class ScheduleStore:
    schedules: list[dict[str, Any]]
    runs: list[dict[str, Any]]


def _ensure_store_dir() -> None:
    SERVER_RUNTIME_DIR.mkdir(parents=True, exist_ok=True)


def _load_store() -> ScheduleStore:
    _ensure_store_dir()
    if not SCHEDULES_FILE.exists():
        return ScheduleStore(schedules=[], runs=[])
    try:
        data = json.loads(SCHEDULES_FILE.read_text(encoding='utf-8'))
    except Exception:
        return ScheduleStore(schedules=[], runs=[])
    schedules = data.get('schedules', []) if isinstance(data, dict) else []
    runs = data.get('runs', []) if isinstance(data, dict) else []
    return ScheduleStore(
        schedules=[item for item in schedules if isinstance(item, dict)],
        runs=[item for item in runs if isinstance(item, dict)],
    )


def _save_store(store: ScheduleStore) -> None:
    _ensure_store_dir()
    SCHEDULES_FILE.write_text(
        json.dumps({'schedules': store.schedules, 'runs': store.runs}, ensure_ascii=False, indent=2),
        encoding='utf-8',
    )


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_zone(name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(name or 'UTC')
    except Exception:
        return ZoneInfo('UTC')


def _parse_hhmm(value: str) -> tuple[int, int]:
    try:
        hour_str, minute_str = value.split(':', 1)
        hour = int(hour_str)
        minute = int(minute_str)
    except Exception as exc:
        raise HTTPException(status_code=400, detail='time must be HH:mm') from exc
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        raise HTTPException(status_code=400, detail='time must be HH:mm')
    return hour, minute


def _normalize_weekdays(values: list[int] | None) -> list[int]:
    if not values:
        return []
    normalized = sorted({int(v) for v in values if 0 <= int(v) <= 6})
    return normalized


def _compute_next_run(schedule: dict[str, Any], from_dt: datetime | None = None) -> str | None:
    trigger_type = str(schedule.get('triggerType') or 'daily')
    hhmm = str(schedule.get('time') or '09:00')
    tz_name = str(schedule.get('timezone') or 'UTC')
    zone = _parse_zone(tz_name)
    base = (from_dt or datetime.now(timezone.utc)).astimezone(zone)
    hour, minute = _parse_hhmm(hhmm)
    target_t = time(hour=hour, minute=minute)

    if trigger_type == 'daily':
        candidate = datetime.combine(base.date(), target_t, tzinfo=zone)
        if candidate <= base:
            candidate += timedelta(days=1)
        return candidate.astimezone(timezone.utc).isoformat()

    if trigger_type == 'weekly':
        weekdays = _normalize_weekdays(schedule.get('weekdays'))
        if not weekdays:
            raise HTTPException(status_code=400, detail='weekdays is required for weekly schedule')
        for offset in range(0, 8):
            candidate_date = base.date() + timedelta(days=offset)
            candidate = datetime.combine(candidate_date, target_t, tzinfo=zone)
            if candidate.weekday() in weekdays and candidate > base:
                return candidate.astimezone(timezone.utc).isoformat()
        fallback = datetime.combine(base.date() + timedelta(days=7), target_t, tzinfo=zone)
        return fallback.astimezone(timezone.utc).isoformat()

    raise HTTPException(status_code=400, detail='triggerType must be daily or weekly')


def _render_session_title(schedule: dict[str, Any], when: datetime | None = None) -> str:
    current = when or datetime.now()
    template = str(schedule.get('sessionTitleTemplate') or '').strip()
    if not template:
        return f"{schedule.get('name', 'Schedule')} - {current.strftime('%Y-%m-%d %H:%M')}"

    replacements = {
        '{name}': str(schedule.get('name', 'Schedule')),
        '{date}': current.strftime('%Y-%m-%d'),
        '{time}': current.strftime('%H:%M'),
        '{datetime}': current.strftime('%Y-%m-%d %H:%M'),
        '{yyyy}': current.strftime('%Y'),
        '{MM}': current.strftime('%m'),
        '{dd}': current.strftime('%d'),
        '{HH}': current.strftime('%H'),
        '{mm}': current.strftime('%M'),
    }
    result = template
    for key, value in replacements.items():
        result = result.replace(key, value)
    return result.strip() or f"{schedule.get('name', 'Schedule')} - {current.strftime('%Y-%m-%d %H:%M')}"


def _sanitize_schedule(payload: dict[str, Any], existing: dict[str, Any] | None = None) -> dict[str, Any]:
    now = _now_iso()
    source = dict(existing or {})
    source.update(payload)

    worker_id = str(source.get('workerId') or '').strip()
    if not worker_id:
        raise HTTPException(status_code=400, detail='workerId is required')
    worker = repository.get_worker(worker_id)
    if worker is None:
        raise HTTPException(status_code=400, detail='worker not found')

    prompt = str(source.get('prompt') or '').strip()
    if not prompt:
        raise HTTPException(status_code=400, detail='prompt is required')

    trigger_type = str(source.get('triggerType') or 'daily')
    if trigger_type not in {'daily', 'weekly'}:
        raise HTTPException(status_code=400, detail='triggerType must be daily or weekly')

    hhmm = str(source.get('time') or '').strip()
    _parse_hhmm(hhmm)

    weekdays = _normalize_weekdays(source.get('weekdays'))
    if trigger_type == 'weekly' and not weekdays:
        raise HTTPException(status_code=400, detail='weekly schedule requires weekdays')

    workspaces = source.get('workspaces')
    if isinstance(workspaces, list):
        workspaces = [str(item).strip() for item in workspaces if str(item).strip()]
    else:
        workspaces = None

    session_title_template = str(source.get('sessionTitleTemplate') or '').strip() or None

    schedule = {
        'id': source.get('id') or f'sch-{uuid.uuid4().hex[:10]}',
        'name': str(source.get('name') or 'Untitled schedule').strip() or 'Untitled schedule',
        'enabled': bool(source.get('enabled', True)),
        'workerId': worker_id,
        'prompt': prompt,
        'sessionTitleTemplate': session_title_template,
        'workspaces': workspaces,
        'triggerType': trigger_type,
        'time': hhmm,
        'weekdays': weekdays,
        'timezone': str(source.get('timezone') or 'UTC'),
        'misfirePolicy': 'skip' if str(source.get('misfirePolicy') or 'run_once') == 'skip' else 'run_once',
        'createNewSession': bool(source.get('createNewSession', True)),
        'lastRunAt': source.get('lastRunAt'),
        'nextRunAt': source.get('nextRunAt'),
        'lastStatus': str(source.get('lastStatus') or 'idle'),
        'lastError': source.get('lastError'),
        'createdAt': source.get('createdAt') or now,
        'updatedAt': now,
    }
    schedule['nextRunAt'] = _compute_next_run(schedule) if schedule['enabled'] else None
    return schedule


def list_schedules() -> list[dict[str, Any]]:
    store = _load_store()
    schedules = sorted(store.schedules, key=lambda item: item.get('updatedAt', ''), reverse=True)
    for schedule in schedules:
        worker = repository.get_worker(str(schedule.get('workerId', '')))
        schedule['workerName'] = worker.get('name') if worker else None
    return schedules


def get_schedule(schedule_id: str) -> dict[str, Any] | None:
    for item in _load_store().schedules:
        if item.get('id') == schedule_id:
            worker = repository.get_worker(str(item.get('workerId', '')))
            result = dict(item)
            result['workerName'] = worker.get('name') if worker else None
            return result
    return None


def create_schedule(payload: dict[str, Any]) -> dict[str, Any]:
    store = _load_store()
    schedule = _sanitize_schedule(payload)
    store.schedules.append(schedule)
    _save_store(store)
    return get_schedule(schedule['id']) or schedule


def update_schedule(schedule_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    store = _load_store()
    for index, existing in enumerate(store.schedules):
        if existing.get('id') != schedule_id:
            continue
        merged = _sanitize_schedule({'id': schedule_id, **payload}, existing=existing)
        store.schedules[index] = merged
        _save_store(store)
        return get_schedule(schedule_id)
    return None


def delete_schedule(schedule_id: str) -> bool:
    store = _load_store()
    before = len(store.schedules)
    store.schedules = [item for item in store.schedules if item.get('id') != schedule_id]
    store.runs = [item for item in store.runs if item.get('scheduleId') != schedule_id]
    changed = len(store.schedules) != before
    if changed:
        _save_store(store)
    return changed


def list_schedule_runs(schedule_id: str, limit: int = 20) -> list[dict[str, Any]]:
    store = _load_store()
    runs = [item for item in store.runs if item.get('scheduleId') == schedule_id]
    runs.sort(key=lambda item: item.get('plannedAt', ''), reverse=True)
    return runs[:limit]


def _append_run(schedule_id: str, worker_id: str, planned_at: str, status: str, session_id: str | None = None, error: str | None = None, output_preview: str | None = None) -> dict[str, Any]:
    store = _load_store()
    run = {
        'id': f'run-{uuid.uuid4().hex[:10]}',
        'scheduleId': schedule_id,
        'workerId': worker_id,
        'sessionId': session_id,
        'plannedAt': planned_at,
        'startedAt': _now_iso(),
        'finishedAt': _now_iso() if status in {'success', 'failed', 'skipped'} else None,
        'status': status,
        'error': error,
        'outputPreview': output_preview,
    }
    store.runs.append(run)
    _save_store(store)
    return run


def _finish_run(run_id: str, status: str, session_id: str | None = None, error: str | None = None, output_preview: str | None = None) -> None:
    store = _load_store()
    for item in store.runs:
        if item.get('id') != run_id:
            continue
        item['status'] = status
        item['sessionId'] = session_id
        item['error'] = error
        item['outputPreview'] = output_preview
        item['finishedAt'] = _now_iso()
        break
    _save_store(store)


def _mark_schedule_result(schedule_id: str, status: str, error: str | None = None, last_run_at: str | None = None, next_run_at: str | None = None) -> None:
    store = _load_store()
    for item in store.schedules:
        if item.get('id') != schedule_id:
            continue
        item['lastStatus'] = status
        item['lastError'] = error
        item['lastRunAt'] = last_run_at
        item['nextRunAt'] = next_run_at
        item['updatedAt'] = _now_iso()
        break
    _save_store(store)


class ScheduleManager:
    def __init__(self) -> None:
        self._task: asyncio.Task[None] | None = None
        self._stopped = asyncio.Event()
        self._running_ids: set[str] = set()
        self._agent_os: Any | None = None

    async def start(self, agent_os: Any | None) -> None:
        self._agent_os = agent_os
        self._stopped.clear()
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        self._stopped.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _loop(self) -> None:
        while not self._stopped.is_set():
            try:
                await self.tick()
            except Exception as exc:
                logger.warning('scheduler tick failed: %s', exc)
            await asyncio.sleep(15)

    async def tick(self) -> None:
        now = datetime.now(timezone.utc)
        for schedule in list_schedules():
            if not schedule.get('enabled'):
                continue
            schedule_id = str(schedule.get('id'))
            if schedule_id in self._running_ids:
                continue
            next_run = schedule.get('nextRunAt')
            if not next_run:
                continue
            try:
                due_at = datetime.fromisoformat(str(next_run))
            except Exception:
                continue
            if due_at.tzinfo is None:
                due_at = due_at.replace(tzinfo=timezone.utc)
            if due_at > now:
                continue
            delay = (now - due_at).total_seconds()
            if delay > MISFIRE_GRACE_SECONDS and schedule.get('misfirePolicy') == 'skip':
                _append_run(schedule_id, str(schedule.get('workerId')), planned_at=next_run, status='skipped', error='Skipped due to missed schedule window')
                _mark_schedule_result(schedule_id, 'idle', error='Skipped due to missed schedule window', next_run_at=_compute_next_run(schedule, now + timedelta(seconds=1)))
                continue
            await self.run_schedule(schedule_id, planned_at=next_run)

    async def run_schedule(self, schedule_id: str, planned_at: str | None = None) -> dict[str, Any]:
        if schedule_id in self._running_ids:
            raise HTTPException(status_code=409, detail='Schedule is already running')
        schedule = get_schedule(schedule_id)
        if schedule is None:
            raise HTTPException(status_code=404, detail='Schedule not found')
        worker_id = str(schedule.get('workerId'))
        self._running_ids.add(schedule_id)
        run = _append_run(schedule_id, worker_id, planned_at=planned_at or _now_iso(), status='running')
        _mark_schedule_result(schedule_id, 'running', error=None)
        try:
            from app.services import create_message, create_session, get_session

            session = None
            if not bool(schedule.get('createNewSession', True)):
                previous_runs = list_schedule_runs(schedule_id, limit=20)
                reusable_session_id = next((item.get('sessionId') for item in previous_runs if item.get('sessionId')), None)
                if reusable_session_id:
                    existing_session = get_session(str(reusable_session_id), agent_os=self._agent_os)
                    if existing_session is not None:
                        session = existing_session
            if session is None:
                title = _render_session_title(schedule, datetime.now())
                session = create_session(worker_id, title, workspaces=schedule.get('workspaces'), agent_os=self._agent_os)
            result = await create_message(session['id'], str(schedule.get('prompt', '')), attachments=None, agent_os=self._agent_os)
            preview = str(result.get('workerMessage', {}).get('content', ''))[:400]
            next_run = _compute_next_run(schedule, datetime.now(timezone.utc) + timedelta(seconds=1)) if schedule.get('enabled') else None
            _finish_run(run['id'], 'success', session_id=session['id'], output_preview=preview)
            _mark_schedule_result(schedule_id, 'success', error=None, last_run_at=_now_iso(), next_run_at=next_run)
            return {'ok': True, 'run': get_schedule(schedule_id), 'sessionId': session['id']}
        except Exception as exc:
            next_run = _compute_next_run(schedule, datetime.now(timezone.utc) + timedelta(seconds=1)) if schedule.get('enabled') else None
            _finish_run(run['id'], 'failed', error=str(exc))
            _mark_schedule_result(schedule_id, 'failed', error=str(exc), last_run_at=_now_iso(), next_run_at=next_run)
            raise
        finally:
            self._running_ids.discard(schedule_id)


schedule_manager = ScheduleManager()
