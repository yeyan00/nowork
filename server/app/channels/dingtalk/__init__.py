"""DingTalk channel — uses dingtalk-stream SDK for Stream mode.

Inspired by QwenPaw DingTalkChannel (Apache-2.0), simplified for nowork.

Stream mode: no public IP or webhook needed. The SDK connects to DingTalk
servers via WebSocket to receive messages and uses sessionWebhook to reply.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import threading
from typing import Any, Optional

from ..base import BaseChannel
from ..registry import register as register_channel
from ..schema import ChannelConfig, ChannelMessage

logger = logging.getLogger('nowork.channels.dingtalk')

try:
    import dingtalk_stream  # type: ignore
    from dingtalk_stream import ChatbotMessage  # type: ignore
    from dingtalk_stream.chatbot import ChatbotHandler  # type: ignore
    HAS_DINGTALK = True
except ImportError:
    HAS_DINGTALK = False
    logger.debug('dingtalk-stream not installed, DingTalk channel unavailable')


if HAS_DINGTALK:

    class _DingTalkHandler(ChatbotHandler):
        """Internal handler that receives DingTalk messages and routes to our channel."""

        def __init__(self, channel: 'DingTalkChannel', main_loop: asyncio.AbstractEventLoop):
            super().__init__()
            self._channel = channel
            self._main_loop = main_loop

        async def process(self, callback: 'dingtalk_stream.CallbackMessage'):
            """Called by dingtalk_stream when a message arrives.

            callback is a CallbackMessage; we parse ChatbotMessage from callback.data.
            """
            try:
                incoming = ChatbotMessage.from_dict(callback.data)
                await self._channel._handle_message(incoming)
            except Exception as e:
                logger.exception('Error handling DingTalk message: %s', e)
            from dingtalk_stream import AckMessage
            return AckMessage.STATUS_OK, 'OK'

    class DingTalkChannel(BaseChannel):
        """DingTalk channel using Stream mode (dingtalk-stream SDK)."""

        platform = 'dingtalk'

        def __init__(self, cfg: ChannelConfig, on_message):
            super().__init__(cfg, on_message)
            self.client_id = cfg.platform_config('client_id', '')
            self.client_secret = cfg.platform_config('client_secret', '')
            self.robot_code = cfg.platform_config('robot_code', '') or self.client_id
            self.message_type = cfg.platform_config('message_type', 'markdown')

            if not self.client_id or not self.client_secret:
                raise ValueError('DingTalk channel requires client_id and client_secret')

            self._client: Optional[Any] = None
            self._stop_event = threading.Event()
            self._stream_thread: Optional[threading.Thread] = None
            self._loop: Optional[asyncio.AbstractEventLoop] = None
            self._webhooks: dict[str, str] = {}

        async def start(self) -> None:
            """Start the DingTalk Stream client."""
            self._loop = asyncio.get_running_loop()

            credential = dingtalk_stream.Credential(self.client_id, self.client_secret)
            self._client = dingtalk_stream.DingTalkStreamClient(credential)

            handler = _DingTalkHandler(self, self._loop)
            self._client.register_callback_handler(ChatbotMessage.TOPIC, handler)

            self._stop_event.clear()
            self._stream_thread = threading.Thread(target=self._run_stream, daemon=True)
            self._stream_thread.start()
            logger.info('DingTalk channel %s started (client_id=%s)', self.channel_id, self.client_id[:8])

        async def stop(self) -> None:
            """Stop the DingTalk Stream client."""
            self._stop_event.set()
            if self._stream_thread:
                self._stream_thread.join(timeout=5)
            self._client = None
            logger.info('DingTalk channel %s stopped', self.channel_id)

        async def _handle_message(self, incoming: ChatbotMessage) -> None:
            """Process an incoming DingTalk message (ChatbotMessage parsed from CallbackMessage.data)."""
            text = ''
            conversation_id = incoming.conversation_id or ''
            sender_id = incoming.sender_staff_id or incoming.sender_id or ''
            sender_nick = incoming.sender_nick or ''
            conversation_type = incoming.conversation_type or ''
            session_webhook = incoming.session_webhook or ''
            is_group = conversation_type == '2'

            # Extract text content
            if incoming.message_type == 'text' and incoming.text:
                text = incoming.text.content or ''
            elif incoming.message_type == 'richText' and incoming.rich_text_content:
                parts = []
                for item in (incoming.rich_text_content.rich_text_list or []):
                    if isinstance(item, dict) and 'text' in item:
                        parts.append(item['text'])
                text = ''.join(parts)
            elif incoming.message_type == 'markdown' and incoming.text:
                text = incoming.text.content or ''

            if not text.strip():
                logger.debug('DingTalk: empty message from %s, skipping', sender_id)
                return

            # Clean @bot mention prefix in group chat
            if is_group:
                text = re.sub(r'^@\S+\s*', '', text).strip()

            if not text:
                return

            # Store webhook for replying
            if session_webhook and sender_id:
                self._webhooks[sender_id] = session_webhook

            # Build session ID
            if is_group and conversation_id:
                session_key = f'dingtalk:group:{conversation_id}'
            else:
                session_key = f'dingtalk:{sender_id}'

            msg = ChannelMessage(
                channel_id=self.channel_id,
                platform=self.platform,
                sender_id=sender_id,
                session_id=session_key,
                text=text,
                meta={
                    'session_webhook': session_webhook,
                    'conversation_id': conversation_id,
                    'conversation_type': conversation_type,
                    'sender_nick': sender_nick,
                    'is_group': is_group,
                },
                on_reply_chunk=self._make_chunk_sender(session_webhook, is_group, sender_id),
            )

            # Route to manager which calls stream_message and returns reply
            # Streaming chunks are sent via on_reply_chunk callback.
            # If no chunks were streamed (e.g. error path), send the final reply.
            await self._on_message(msg)

        def _make_chunk_sender(self, webhook_url: str, is_group: bool, sender_staff_id: str):
            """Create a callback that sends message via sessionWebhook.
            Called once at completion with full reply content.
            """
            async def _send_chunk(chunk: str) -> None:
                if not webhook_url or not chunk.strip():
                    return
                await self._send_via_webhook(
                    webhook_url, chunk,
                    is_group=is_group, sender_staff_id=sender_staff_id,
                )

            return _send_chunk

        async def send(self, session_id: str, text: str, meta: dict[str, Any] | None = None) -> None:
            """Proactive send — look up stored webhook and send."""
            meta = meta or {}
            webhook = meta.get('session_webhook', '')
            if not webhook:
                sender_id = session_id.replace('dingtalk:', '', 1)
                webhook = self._webhooks.get(sender_id, '')

            if not webhook:
                logger.warning('DingTalk send: no webhook for session %s', session_id)
                return

            is_group = meta.get('is_group', False)
            sender_staff_id = meta.get('sender_staff_id', '')
            await self._send_via_webhook(webhook, text, is_group=is_group, sender_staff_id=sender_staff_id)

        async def _send_via_webhook(self, webhook_url: str, text: str,
                                     is_group: bool = False, sender_staff_id: str = '') -> None:
            """Send a reply via DingTalk sessionWebhook."""
            import aiohttp

            bot_prefix = self.cfg.platform_config('bot_prefix', '')
            if bot_prefix and text:
                text = bot_prefix + ' ' + text

            # Truncate long messages
            if len(text) > 15000:
                text = text[:15000] + '\n...(消息过长已截断)'

            if self.message_type == 'markdown':
                payload = {
                    'msgtype': 'markdown',
                    'markdown': {
                        'title': '回复',
                        'text': text,
                    },
                }
            else:
                payload = {
                    'msgtype': 'text',
                    'text': {
                        'content': text,
                    },
                }

            # @mention the sender in group chat
            if is_group and sender_staff_id:
                payload['at'] = {
                    'atUserIds': [sender_staff_id],
                }

            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(webhook_url, json=payload, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                        if resp.status != 200:
                            body = await resp.text()
                            logger.warning('DingTalk webhook send failed: status=%s body=%s', resp.status, body[:200])
                        else:
                            logger.debug('DingTalk reply sent via webhook')
            except Exception as e:
                logger.exception('DingTalk webhook send error: %s', e)

        def _run_stream(self) -> None:
            """Run the dingtalk_stream client in a background thread."""
            logger.info('DingTalk stream thread started (client_id=%s)', self.client_id[:8])
            try:
                if self._client:
                    asyncio.run(self._stream_loop())
            except Exception:
                logger.exception('DingTalk stream thread failed')
            finally:
                self._stop_event.set()
                logger.info('DingTalk stream thread stopped')

        async def _stream_loop(self) -> None:
            """Drive the dingtalk_stream client start/stop."""
            client = self._client
            if not client:
                return

            main_task = asyncio.create_task(client.start())

            async def stop_watcher():
                while not self._stop_event.is_set():
                    await asyncio.sleep(0.5)
                ws = getattr(client, 'websocket', None)
                if ws is not None:
                    try:
                        await ws.close()
                    except Exception:
                        pass
                while not main_task.done():
                    main_task.cancel()
                    await asyncio.sleep(0.1)

            watcher = asyncio.create_task(stop_watcher())
            try:
                await main_task
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.exception('DingTalk stream start() failed')
            watcher.cancel()

    # Register with the channel registry
    register_channel('dingtalk', DingTalkChannel)

else:
    logger.info('dingtalk-stream SDK not installed; DingTalk channel unavailable. Install with: pip install dingtalk-stream')
