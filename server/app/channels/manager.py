"""ChannelManager — orchestrates channel lifecycle and message routing.

Inspired by QwenPaw ChannelManager (Apache-2.0), simplified for nowork.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Optional

from . import registry
from .base import BaseChannel
from .schema import ChannelConfig, ChannelMessage, ChannelStatus

logger = logging.getLogger('nowork.channels')


class ChannelManager:
    """Manages channel instances: create, start, stop, route messages."""

    def __init__(self):
        self._channels: dict[str, BaseChannel] = {}
        self._agent_os: Any = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._session_map: dict[str, str] = {}  # channel_session_id -> nowork_session_id

    def set_agent_os(self, agent_os: Any) -> None:
        self._agent_os = agent_os

    def load_configs(self) -> list[ChannelConfig]:
        from app.config import load_channels_config
        raw_list = load_channels_config()
        return [ChannelConfig(**raw) for raw in raw_list]

    async def start_all(self, agent_os: Any) -> None:
        self.set_agent_os(agent_os)
        self._loop = asyncio.get_running_loop()

        configs = self.load_configs()
        started = 0
        for cfg in configs:
            if not cfg.enabled:
                logger.info('Channel %s (%s) is disabled, skipping', cfg.id, cfg.platform)
                continue
            try:
                await self.start_channel(cfg)
                started += 1
            except Exception as e:
                logger.exception('Failed to start channel %s (%s): %s', cfg.id, cfg.platform, e)
        logger.info('ChannelManager: %d/%d channels started', started, len(configs))

    async def start_channel(self, cfg: ChannelConfig) -> BaseChannel:
        cls = registry.get(cfg.platform)
        if cls is None:
            raise ValueError(f'Unknown platform: {cfg.platform}. Available: {registry.list_platforms()}')

        if not cfg.worker_id:
            raise ValueError(f'Channel {cfg.id} has no worker_id configured')

        channel = cls(cfg=cfg, on_message=self._on_message)
        self._channels[cfg.id] = channel
        channel._status = 'starting'
        try:
            await channel.start()
            channel._status = 'running'
            logger.info('Channel %s (%s) started, worker=%s', cfg.id, cfg.platform, cfg.worker_id)
        except Exception as e:
            channel._status = 'error'
            channel._detail = str(e)
            raise
        return channel

    async def stop_all(self) -> None:
        for cid, channel in list(self._channels.items()):
            try:
                await channel.stop()
                channel._status = 'stopped'
                logger.info('Channel %s stopped', cid)
            except Exception as e:
                logger.exception('Error stopping channel %s: %s', cid, e)
        self._channels.clear()

    async def restart_channel(self, cfg: ChannelConfig) -> BaseChannel:
        existing = self._channels.get(cfg.id)
        if existing:
            try:
                await existing.stop()
            except Exception as e:
                logger.warning('Error stopping channel %s for restart: %s', cfg.id, e)
            self._channels.pop(cfg.id, None)
        return await self.start_channel(cfg)

    def get_channel(self, channel_id: str) -> BaseChannel | None:
        return self._channels.get(channel_id)

    def list_channels(self) -> list[ChannelStatus]:
        configs = self.load_configs()
        result = []
        for cfg in configs:
            instance = self._channels.get(cfg.id)
            result.append(ChannelStatus(
                id=cfg.id,
                platform=cfg.platform,
                name=cfg.name,
                enabled=cfg.enabled,
                worker_id=cfg.worker_id,
                status=instance.status if instance else 'stopped',
                detail=instance.detail if instance else '',
            ))
        return result

    async def _on_message(self, msg: ChannelMessage) -> str:
        """Route an incoming message to the bound worker via stream_message."""
        from app.services import stream_message, create_session

        if self._agent_os is None:
            logger.error('AgentOS not available for channel message')
            return 'Error: server not ready'

        # Find the worker bound to this channel
        worker_id = None
        for cfg in self.load_configs():
            if cfg.id == msg.channel_id:
                worker_id = cfg.worker_id
                break

        if not worker_id:
            logger.error('No worker bound for channel %s', msg.channel_id)
            return 'Error: no worker configured'

        # Map channel session (e.g. "dingtalk:sender123") → nowork session ID
        # We keep a simple in-memory mapping so repeated messages from the same
        # user reuse the same nowork session.
        map_key = msg.session_id
        nowork_session_id = self._session_map.get(map_key)

        if not nowork_session_id:
            # Check if worker has any existing session for this channel sender
            # by searching session titles
            try:
                from app.session_manager import list_worker_sessions
                existing = list_worker_sessions(worker_id)
                for ws in existing:
                    title = ws.get('title', '')
                    if title == map_key or title == f'{msg.platform}:{msg.sender_id}':
                        nowork_session_id = ws['id']
                        break
            except Exception:
                pass

        if not nowork_session_id:
            new_session = create_session(
                worker_id,
                title=f'{msg.platform}:{msg.sender_id}',
                agent_os=self._agent_os,
            )
            nowork_session_id = new_session['id']
            logger.info('Created session %s for channel %s sender %s', nowork_session_id, msg.channel_id, msg.sender_id)

        self._session_map[map_key] = nowork_session_id

        # Collect the full reply from the stream
        full_reply = ''
        try:
            async for sse_line in stream_message(
                nowork_session_id, msg.text, attachments=[], agent_os=self._agent_os
            ):
                if not sse_line.startswith('data: '):
                    continue
                try:
                    event_data = json.loads(sse_line[6:])
                except (json.JSONDecodeError, IndexError):
                    continue

                event_type = event_data.get('event', '')
                if event_type == 'RunCompleted':
                    full_reply = event_data.get('content', full_reply)
                elif event_type == 'RunError':
                    full_reply = f'Error: {event_data.get("content", "unknown error")}'
                elif event_type == 'RunContent':
                    content = event_data.get('content', '')
                    if content:
                        full_reply = content

        except Exception as e:
            logger.exception('Error streaming message for channel %s: %s', msg.channel_id, e)
            full_reply = f'Error: {e}'

        return full_reply or 'Sorry, I could not generate a response.'
