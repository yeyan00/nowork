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


class PendingApprovalInfo:
    """Info about a pending tool approval request."""

    def __init__(self, run_id: str, approvals: list[dict], session_id: str, worker_id: str, msg: ChannelMessage):
        self.run_id = run_id
        self.approvals = approvals
        self.session_id = session_id
        self.worker_id = worker_id
        self.msg = msg  # Original channel message (has on_reply_chunk)


class ChannelManager:
    """Manages channel instances: create, start, stop, route messages."""

    def __init__(self):
        self._channels: dict[str, BaseChannel] = {}
        self._agent_os: Any = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._session_map: dict[str, str] = {}  # channel_session_id -> nowork_session_id
        self._pending_approvals: dict[str, PendingApprovalInfo] = {}  # channel_session_id -> PendingApprovalInfo

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
        """Route an incoming message to the bound worker via stream_message.

        Platform-specific streaming:
          - Feishu: incremental send + edit (best UX, one message)
          - DingTalk: accumulate and send once at completion (clean single message)

        Returns the final full reply.
        """
        from app.services import stream_message, create_session

        if self._agent_os is None:
            logger.error('AgentOS not available for channel message')
            return 'Error: server not ready'

        # ── Check for approval response (y/n) ──
        map_key = msg.session_id
        pending = self._pending_approvals.get(map_key)
        if pending:
            text_lower = msg.text.strip().lower()
            if text_lower in ('y', 'yes', '批准', '同意', 'approve'):
                return await self._handle_approval_response(pending, approved=True)
            elif text_lower in ('n', 'no', '拒绝', '不同意', 'reject'):
                return await self._handle_approval_response(pending, approved=False)
            # Not an approval response, clear pending and treat as new message
            logger.info('Clearing pending approval for %s (user sent: %s)', map_key, msg.text[:20])
            self._pending_approvals.pop(map_key, None)

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
        nowork_session_id = self._session_map.get(map_key)

        if not nowork_session_id:
            try:
                from app.session_manager import list_worker_sessions
                existing = list_worker_sessions(worker_id)
                for ws in existing:
                    # Match by title: title is set to msg.session_id on creation
                    title = ws.get('title', '')
                    if title == map_key:
                        nowork_session_id = ws['id']
                        break
            except Exception:
                pass

        if not nowork_session_id:
            new_session = create_session(
                worker_id,
                title=map_key,
                agent_os=self._agent_os,
            )
            nowork_session_id = new_session['id']
            logger.info('Created session %s for channel %s sender %s', nowork_session_id, msg.channel_id, msg.sender_id)

        self._session_map[map_key] = nowork_session_id

        # ── Platform-specific streaming logic ──
        # Both Feishu and DingTalk: accumulate and send once at completion
        # (Feishu edit API has validation issues, use single message for stability)
        return await self._stream_accumulate(msg, nowork_session_id, worker_id)

    async def _stream_feishu(self, msg: ChannelMessage, nowork_session_id: str) -> str:
        """Feishu streaming: send first chunk, then edit with accumulated content.
        User sees one message that gradually fills in.
        """
        from app.services import stream_message
        import json

        full_reply = ''
        message_id: str | None = None
        accumulated = ''

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

                if event_type == 'RunContent':
                    content = event_data.get('content', '')
                    if content:
                        accumulated += content
                        if message_id and msg.on_edit_message:
                            # Edit existing message with accumulated content
                            await msg.on_edit_message(message_id, accumulated)
                        elif msg.on_reply_chunk and not message_id:
                            # First chunk: send new message
                            message_id = await msg.on_reply_chunk(accumulated)

                elif event_type == 'RunCompleted':
                    full_reply = event_data.get('content', '')
                    # Final edit with complete content
                    if message_id and msg.on_edit_message and full_reply:
                        await msg.on_edit_message(message_id, full_reply)

                elif event_type == 'RunError':
                    full_reply = f'Error: {event_data.get("content", "unknown error")}'
                    if message_id and msg.on_edit_message:
                        await msg.on_edit_message(message_id, full_reply)
                    elif msg.on_reply_chunk:
                        await msg.on_reply_chunk(full_reply)

        except Exception as e:
            logger.exception('Error streaming message for channel %s: %s', msg.channel_id, e)
            full_reply = f'Error: {e}'
            if message_id and msg.on_edit_message:
                await msg.on_edit_message(message_id, full_reply)
            elif msg.on_reply_chunk:
                await msg.on_reply_chunk(full_reply)

        return full_reply or 'Sorry, I could not generate a response.'

    async def _stream_accumulate(self, msg: ChannelMessage, nowork_session_id: str, worker_id: str) -> str:
        """DingTalk / others: accumulate all content and send once at completion.
        Clean single message, but user waits longer for any response.

        Also handles ToolApprovalRequest events by prompting the user for y/n response.
        """
        from app.services import stream_message
        import json

        full_reply = ''
        accumulated = ''

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

                if event_type == 'RunContent':
                    content = event_data.get('content', '')
                    if content:
                        accumulated += content

                elif event_type == 'RunCompleted':
                    full_reply = event_data.get('content', '')
                    # Send complete message once
                    if msg.on_reply_chunk and full_reply:
                        await msg.on_reply_chunk(full_reply)

                elif event_type == 'RunError':
                    full_reply = f'Error: {event_data.get("content", "unknown error")}'
                    if msg.on_reply_chunk:
                        await msg.on_reply_chunk(full_reply)

                elif event_type == 'ToolApprovalRequest':
                    # Agent needs user approval for write operation
                    run_id = event_data.get('run_id', '')
                    approvals = event_data.get('approvals', [])
                    await self._handle_tool_approval_request(
                        msg, nowork_session_id, run_id, approvals, worker_id
                    )
                    # The run is paused waiting for approval response
                    # User will send y/n message later, which triggers _handle_approval_response
                    return ''

        except Exception as e:
            logger.exception('Error streaming message for channel %s: %s', msg.channel_id, e)
            full_reply = f'Error: {e}'
            if msg.on_reply_chunk:
                await msg.on_reply_chunk(full_reply)

        return full_reply or 'Sorry, I could not generate a response.'

    async def _handle_tool_approval_request(
        self, msg: ChannelMessage, session_id: str, run_id: str, approvals: list[dict], worker_id: str
    ) -> None:
        """Send approval prompt to user and store pending approval info."""
        # Build prompt message
        paths = []
        for a in approvals:
            desc = a.get('description', '')
            path = a.get('toolArgs', {}).get('file_path', '') or a.get('toolArgs', {}).get('path', '')
            if desc:
                paths.append(desc)
            elif path:
                paths.append(path)
        
        if not paths:
            paths = ['unknown path']
        
        prompt = (
            f'⚠️ 需批准写入操作\n'
            f'路径: {", ".join(paths)}\n'
            f'回复 "y" 批准，"n" 拒绝'
        )

        # Send prompt to user
        if msg.on_reply_chunk:
            await msg.on_reply_chunk(prompt)

        # Store pending approval info
        map_key = msg.session_id
        self._pending_approvals[map_key] = PendingApprovalInfo(
            run_id=run_id,
            approvals=approvals,
            session_id=session_id,
            worker_id=worker_id,
            msg=msg,
        )
        logger.info('Tool approval request sent to %s, run_id=%s', map_key, run_id)

    async def _handle_approval_response(self, pending: PendingApprovalInfo, approved: bool) -> str:
        """Handle user's y/n response to a pending approval request."""
        from app.services import stream_continue_run, _resolve_runtime_agent
        from app import repository
        from agno.models.response import ToolExecution
        import json

        # Clear pending approval
        map_key = pending.msg.session_id
        self._pending_approvals.pop(map_key, None)

        # Get runtime and worker
        if self._agent_os is None:
            return 'Error: agent_os not available'
        
        runtime = _resolve_runtime_agent(pending.worker_id, self._agent_os)
        if runtime is None:
            return 'Error: runtime not found'
        
        worker = repository.get_worker(pending.worker_id)
        if worker is None:
            return 'Error: worker not found'

        # Build updated_tools for continue_run
        updated_tools = []
        for a in pending.approvals:
            te = ToolExecution(
                tool_call_id=a.get('toolCallId', ''),
                tool_name=a.get('toolName', ''),
                tool_args=a.get('toolArgs', {}),
                confirmed=approved,
                requires_confirmation=True,
            )
            updated_tools.append(te)

        # Send confirmation message
        status_text = '已批准' if approved else '已拒绝'
        if pending.msg.on_reply_chunk:
            await pending.msg.on_reply_chunk(f'✅ {status_text}，继续执行...')

        # Continue the paused run
        full_reply = ''
        try:
            async for sse_line in stream_continue_run(
                pending.run_id,
                runtime,
                updated_tools,
                worker,
                pending.session_id,
            ):
                if not sse_line.startswith('data: '):
                    continue
                try:
                    event_data = json.loads(sse_line[6:])
                except (json.JSONDecodeError, IndexError):
                    continue

                event_type = event_data.get('event', '')

                if event_type == 'RunContent':
                    content = event_data.get('content', '')
                    if content:
                        full_reply += content

                elif event_type == 'RunCompleted':
                    full_reply = event_data.get('content', '') or full_reply
                    if pending.msg.on_reply_chunk and full_reply:
                        await pending.msg.on_reply_chunk(full_reply)

                elif event_type == 'RunError':
                    full_reply = f'Error: {event_data.get("content", "unknown error")}'
                    if pending.msg.on_reply_chunk:
                        await pending.msg.on_reply_chunk(full_reply)

                elif event_type == 'ToolApprovalRequest':
                    # Nested approval request - handle recursively
                    run_id = event_data.get('run_id', '')
                    approvals = event_data.get('approvals', [])
                    await self._handle_tool_approval_request(
                        pending.msg, pending.session_id, run_id, approvals, pending.worker_id
                    )
                    return ''

        except Exception as e:
            logger.exception('Error continuing run after approval: %s', e)
            full_reply = f'Error: {e}'
            if pending.msg.on_reply_chunk:
                await pending.msg.on_reply_chunk(full_reply)

        return full_reply or 'Done.'
