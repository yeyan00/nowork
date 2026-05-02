"""Feishu (Lark) channel — uses lark-oapi SDK for WebSocket receive + OpenAPI send.

Inspired by QwenPaw FeishuChannel (Apache-2.0), simplified for nowork.

WebSocket mode: no public IP or webhook needed. The SDK connects to Feishu
servers via WebSocket to receive events. Messages are sent via the OpenAPI
im/v1/messages endpoint using tenant_access_token.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import threading
import time
import types
from collections import OrderedDict
from typing import Any, Optional

from ..base import BaseChannel
from ..registry import register as register_channel
from ..schema import ChannelConfig, ChannelMessage

logger = logging.getLogger('nowork.channels.feishu')

# ── pkg_resources shim for setuptools>=82 ──────────────────
# lark-oapi imports pkg_resources.declare_namespace; install a minimal
# shim when pkg_resources is absent (setuptools>=82).
_original_pkg_resources = None
_pkg_resources_shim = None

try:
    import pkg_resources as _  # noqa: F401
except ImportError:
    _pkg_resources_shim = types.ModuleType('pkg_resources')
    _pkg_resources_shim.declare_namespace = lambda _name: None  # type: ignore
    _original_pkg_resources = 'MISSING'
    import sys
    sys.modules['pkg_resources'] = _pkg_resources_shim

# ── EventLoopProxy for lark_oapi.ws.client.loop ────────────
# The SDK stores a module-level loop variable; proxy it to the running loop.
class _EventLoopProxy:
    def __getattr__(self, name: str) -> Any:
        try:
            return getattr(asyncio.get_running_loop(), name)
        except RuntimeError:
            return getattr(asyncio.get_event_loop(), name)


try:
    import lark_oapi as lark  # type: ignore
    from lark_oapi.api.im.v1 import (  # type: ignore
        CreateMessageRequest,
        CreateMessageRequestBody,
        P2ImMessageReceiveV1,
    )
    # Patch the SDK's event loop reference
    import lark_oapi.ws.client as _ws_mod  # type: ignore
    _ws_mod.loop = _EventLoopProxy()
    HAS_FEISHU = True
except ImportError:
    lark = None  # type: ignore
    HAS_FEISHU = False
    logger.debug('lark-oapi not installed, Feishu channel unavailable')

# Cleanup pkg_resources shim
if _pkg_resources_shim is not None:
    import sys
    if _original_pkg_resources == 'MISSING':
        sys.modules.pop('pkg_resources', None)
    del _original_pkg_resources, _pkg_resources_shim

# ── Constants ──────────────────────────────────────────────
_PROCESSED_IDS_MAX = 500
_STALE_MSG_THRESHOLD_MS = 20_000  # 20 seconds
_WS_INITIAL_RETRY_DELAY = 2.0
_WS_MAX_RETRY_DELAY = 120.0
_WS_BACKOFF_FACTOR = 2.0


def _extract_json_key(content_raw: str, *keys: str) -> str:
    """Extract a value from a JSON content string by key(s)."""
    try:
        data = json.loads(content_raw) if isinstance(content_raw, str) else content_raw
    except (json.JSONDecodeError, TypeError):
        return ''
    for key in keys:
        val = data.get(key, '')
        if val:
            return str(val)
    return ''


def _extract_post_text(content_raw: str) -> str:
    """Extract plain text from a Feishu post (rich text) message."""
    try:
        data = json.loads(content_raw) if isinstance(content_raw, str) else content_raw
    except (json.JSONDecodeError, TypeError):
        return ''
    title = data.get('title', '')
    parts: list[str] = []
    if title:
        parts.append(title)
    content = data.get('content', [])
    for paragraph in (content if isinstance(content, list) else []):
        for elem in (paragraph if isinstance(paragraph, list) else []):
            tag = elem.get('tag', '')
            if tag == 'text':
                text = elem.get('text', '').strip()
                if text:
                    parts.append(text)
            elif tag == 'at':
                # @mention — skip bot mentions
                pass
            elif tag == 'a':
                href = elem.get('href', '')
                text = elem.get('text', '')
                if text:
                    parts.append(f'[{text}]({href})' if href else text)
    return '\n'.join(parts)


if HAS_FEISHU:

    class FeishuChannel(BaseChannel):
        """Feishu/Lark channel: WebSocket receive, OpenAPI send.

        Session ID format:
          - P2P: feishu:{open_id}
          - Group: feishu:group:{chat_id}
        """

        platform = 'feishu'

        def __init__(self, cfg: ChannelConfig, on_message):
            super().__init__(cfg, on_message)
            self.app_id = cfg.platform_config('app_id', '')
            self.app_secret = cfg.platform_config('app_secret', '')
            self.encrypt_key = cfg.platform_config('encrypt_key', '')
            self.verification_token = cfg.platform_config('verification_token', '')
            self.domain = cfg.platform_config('domain', 'feishu')
            if self.domain not in ('feishu', 'lark'):
                self.domain = 'feishu'

            if not self.app_id or not self.app_secret:
                raise ValueError('Feishu channel requires app_id and app_secret')

            self._client: Any = None
            self._ws_client: Any = None
            self._ws_thread: Optional[threading.Thread] = None
            self._loop: Optional[asyncio.AbstractEventLoop] = None
            self._ws_loop: Optional[asyncio.AbstractEventLoop] = None
            self._stop_event = threading.Event()
            self._closed = False
            self._clock_offset: int = 0

            # Message dedup
            self._processed_ids: OrderedDict[str, None] = OrderedDict()
            # receive_id store: session_id -> (receive_id_type, receive_id)
            self._receive_id_store: dict[str, tuple[str, str]] = {}

        async def start(self) -> None:
            """Start the Feishu WebSocket client."""
            self._loop = asyncio.get_running_loop()

            # Create lark client for sending messages (builder pattern)
            domain = lark.LARK_DOMAIN if self.domain == 'lark' else lark.FEISHU_DOMAIN
            self._client = (
                lark.Client.builder()
                .app_id(self.app_id)
                .app_secret(self.app_secret)
                .domain(domain)
                .build()
            )

            self._stop_event.clear()
            self._closed = False
            self._ws_thread = threading.Thread(target=self._run_ws_forever, daemon=True)
            self._ws_thread.start()
            logger.info('Feishu channel %s started (app_id=%s)', self.channel_id, self.app_id[:8])

        async def stop(self) -> None:
            """Stop the Feishu WebSocket client."""
            self._closed = True
            self._stop_event.set()
            if self._ws_loop and not self._ws_loop.is_closed():
                try:
                    self._ws_loop.call_soon_threadsafe(self._ws_loop.stop)
                except Exception:
                    pass
            if self._ws_thread:
                self._ws_thread.join(timeout=10)
            self._client = None
            logger.info('Feishu channel %s stopped', self.channel_id)

        def resolve_session_id(self, sender_id: str, meta: dict[str, Any] | None = None) -> str:
            meta = meta or {}
            chat_type = meta.get('feishu_chat_type', 'p2p')
            chat_id = meta.get('feishu_chat_id', '')
            if chat_type == 'group' and chat_id:
                return f'feishu:group:{chat_id}'
            return f'feishu:{sender_id}'

        # ── WebSocket thread ──────────────────────────────

        def _run_ws_forever(self) -> None:
            """Run WebSocket with exponential-backoff reconnection."""
            retry_delay = _WS_INITIAL_RETRY_DELAY

            while not self._stop_event.is_set() and not self._closed:
                self._ws_loop = asyncio.new_event_loop()
                asyncio.set_event_loop(self._ws_loop)
                try:
                    event_handler = (
                        lark.EventDispatcherHandler.builder(
                            self.encrypt_key,
                            self.verification_token,
                        )
                        .register_p2_im_message_receive_v1(
                            self._on_message_sync,
                        )
                        .build()
                    )

                    domain = lark.LARK_DOMAIN if self.domain == 'lark' else lark.FEISHU_DOMAIN
                    self._ws_client = lark.ws.Client(
                        self.app_id,
                        self.app_secret,
                        event_handler=event_handler,
                        log_level=lark.LogLevel.INFO,
                        domain=domain,
                    )

                    async def _drive() -> None:
                        await self._ws_client._connect()
                        self._ws_loop.create_task(self._ws_client._ping_loop())
                        # Keep alive
                        while not self._stop_event.is_set():
                            await asyncio.sleep(3600)

                    logger.info('Feishu WebSocket connecting...')
                    self._ws_loop.run_until_complete(_drive())
                    # Disconnected normally
                    logger.info('Feishu WebSocket disconnected, reconnecting...')
                    retry_delay = _WS_INITIAL_RETRY_DELAY

                except RuntimeError as e:
                    if 'Event loop stopped' in str(e):
                        logger.info('Feishu WebSocket stopped normally')
                        retry_delay = _WS_INITIAL_RETRY_DELAY
                    else:
                        logger.exception('Feishu WebSocket error: %s', e)
                except Exception:
                    logger.exception('Feishu WebSocket connection failed')
                finally:
                    # Cleanup
                    try:
                        if self._ws_loop and not self._ws_loop.is_closed():
                            pending = asyncio.all_tasks(self._ws_loop)
                            for t in pending:
                                t.cancel()
                            self._ws_loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                            self._ws_loop.run_until_complete(asyncio.sleep(0.1))
                            self._ws_loop.close()
                    except Exception:
                        pass
                    self._ws_loop = None

                if not self._stop_event.is_set() and not self._closed:
                    logger.info('Feishu reconnecting in %.1fs...', retry_delay)
                    self._stop_event.wait(timeout=retry_delay)
                    retry_delay = min(retry_delay * _WS_BACKOFF_FACTOR, _WS_MAX_RETRY_DELAY)

        # ── Message receiving ─────────────────────────────

        def _on_message_sync(self, data: 'P2ImMessageReceiveV1') -> None:
            """Sync handler called from WebSocket thread."""
            if self._closed:
                logger.info('Feishu _on_message_sync: channel closed, ignoring')
                return

            logger.info('Feishu _on_message_sync called')

            # Guard against cross-instance dispatch
            header = getattr(data, 'header', None)
            event_app_id = getattr(header, 'app_id', None)
            if event_app_id and event_app_id != self.app_id:
                logger.debug('Feishu: ignoring message from different app_id=%s', event_app_id)
                return

            # Drop stale messages
            create_time = getattr(header, 'create_time', None)
            if create_time:
                now_ms = int(time.time() * 1000) + self._clock_offset
                age_ms = now_ms - int(create_time)
                if age_ms > _STALE_MSG_THRESHOLD_MS:
                    logger.debug('Feishu: drop stale message (age=%.1fs)', age_ms / 1000)
                    return

            if not self._loop or not self._loop.is_running():
                logger.warning('Feishu: main loop not running (loop=%s, running=%s), drop message',
                               self._loop, self._loop.is_running() if self._loop else False)
                return

            future = asyncio.run_coroutine_threadsafe(self._handle_event(data), self._loop)
            logger.info('Feishu: dispatched _handle_event to main loop')

        async def _handle_event(self, data: 'P2ImMessageReceiveV1') -> None:
            """Handle one Feishu event: dedup, parse, build ChannelMessage, route to manager."""
            logger.info('Feishu _handle_event entered')
            if not data or not getattr(data, 'event', None):
                logger.warning('Feishu _handle_event: no data or no event')
                return

            try:
                event = data.event
                message = getattr(event, 'message', None)
                sender = getattr(event, 'sender', None)
                if not message or not sender:
                    logger.warning('Feishu _handle_event: no message or sender')
                    return

                # Dedup
                message_id = str(getattr(message, 'message_id', '') or '').strip()
                if message_id in self._processed_ids:
                    return
                self._processed_ids[message_id] = None
                while len(self._processed_ids) > _PROCESSED_IDS_MAX:
                    self._processed_ids.popitem(last=False)

                # Skip bot messages
                sender_type = getattr(sender, 'sender_type', '') or ''
                if sender_type == 'bot':
                    return

                # Sender info
                sender_id_obj = getattr(sender, 'sender_id', None)
                sender_id = ''
                if sender_id_obj:
                    sender_id = str(getattr(sender_id_obj, 'open_id', '') or '').strip()
                if not sender_id:
                    sender_id = f'unknown_{message_id[:8]}'

                nickname = getattr(sender, 'name', '') or getattr(sender, 'nickname', '') or ''
                if isinstance(nickname, str):
                    nickname = nickname.strip()

                # Chat info
                chat_id = str(getattr(message, 'chat_id', '') or '').strip()
                chat_type = str(getattr(message, 'chat_type', 'p2p') or 'p2p').strip()
                msg_type = str(getattr(message, 'message_type', 'text') or 'text').strip()
                content_raw = str(getattr(message, 'content', '') or '')

                # Parse text
                text = ''
                if msg_type == 'text':
                    text = _extract_json_key(content_raw, 'text')
                elif msg_type == 'post':
                    text = _extract_post_text(content_raw)
                elif msg_type == 'interactive':
                    # Card messages — extract text if possible
                    text = _extract_json_key(content_raw, 'text', 'content')
                else:
                    text = f'[{msg_type}]'

                if not text.strip():
                    logger.debug('Feishu: empty message from %s, skipping', sender_id[:16])
                    return

                # Clean @bot mention in group
                is_group = chat_type == 'group'
                if is_group:
                    # Remove @user mentions from text
                    mentions = getattr(message, 'mentions', None) or []
                    for m in mentions:
                        key = getattr(m, 'key', None)
                        if key:
                            text = text.replace(key, '')
                    text = text.strip()

                if not text:
                    return

                # Build session ID
                if is_group and chat_id:
                    session_key = f'feishu:group:{chat_id}'
                else:
                    session_key = f'feishu:{sender_id}'

                # Store receive_id for sending replies
                receive_id = chat_id if is_group else sender_id
                receive_id_type = 'chat_id' if is_group else 'open_id'
                self._receive_id_store[session_key] = (receive_id_type, receive_id)

                meta = {
                    'feishu_message_id': message_id,
                    'feishu_chat_id': chat_id,
                    'feishu_chat_type': chat_type,
                    'feishu_sender_id': sender_id,
                    'feishu_receive_id': receive_id,
                    'feishu_receive_id_type': receive_id_type,
                    'feishu_sender_nick': nickname,
                    'is_group': is_group,
                }

                msg = ChannelMessage(
                    channel_id=self.channel_id,
                    platform=self.platform,
                    sender_id=sender_id,
                    session_id=session_key,
                    text=text,
                    meta=meta,
                    on_reply_chunk=self._make_chunk_sender(session_key),
                )

                logger.info(
                    'Feishu recv: sender=%s chat=%s type=%s text_len=%d',
                    (nickname or sender_id)[:20], chat_id[:16], msg_type, len(text),
                )

                await self._on_message(msg)

            except Exception:
                logger.exception('Feishu _on_message failed')

        # ── Message sending ───────────────────────────────

        def _make_chunk_sender(self, session_key: str):
            """Create a callback that sends paragraph chunks via Feishu OpenAPI."""
            async def _send_chunk(chunk: str) -> None:
                if not chunk.strip():
                    return
                entry = self._receive_id_store.get(session_key)
                if not entry:
                    logger.warning('Feishu: no receive_id for session %s', session_key)
                    return
                receive_id_type, receive_id = entry
                await self._send_text(receive_id_type, receive_id, chunk)

            return _send_chunk

        async def send(self, session_id: str, text: str, meta: dict[str, Any] | None = None) -> None:
            """Proactive send — look up stored receive_id and send."""
            meta = meta or {}
            receive_id_type = meta.get('feishu_receive_id_type', '')
            receive_id = meta.get('feishu_receive_id', '')

            if not receive_id:
                entry = self._receive_id_store.get(session_id)
                if entry:
                    receive_id_type, receive_id = entry

            if not receive_id:
                logger.warning('Feishu send: no receive_id for session %s', session_id)
                return

            await self._send_text(receive_id_type, receive_id, text)

        async def _send_text(self, receive_id_type: str, receive_id: str, body: str) -> str | None:
            """Send a text/post message via Feishu OpenAPI."""
            if not self._client:
                logger.warning('Feishu _send_text: no client')
                return None

            # Truncate long messages
            if len(body) > 15000:
                body = body[:15000] + '\n...(消息过长已截断)'

            # Send as post (markdown) for better formatting
            post_content = {
                'zh_cn': {
                    'title': '',
                    'content': [[{'tag': 'text', 'text': body}]],
                }
            }
            content = json.dumps(post_content, ensure_ascii=False)

            try:
                req = (
                    CreateMessageRequest.builder()
                    .receive_id_type(receive_id_type)
                    .request_body(
                        CreateMessageRequestBody.builder()
                        .receive_id(receive_id)
                        .msg_type('post')
                        .content(content)
                        .build(),
                    )
                    .build()
                )
                resp = await self._client.im.v1.message.acreate(req)
                if not resp.success():
                    logger.warning(
                        'Feishu send failed: code=%s msg=%s',
                        getattr(resp, 'code', ''),
                        getattr(resp, 'msg', ''),
                    )
                    return None
                msg_id = getattr(resp.data, 'message_id', None) if resp.data else None
                logger.debug('Feishu send OK: msg_id=%s', (msg_id or '')[:20])
                return msg_id
            except Exception:
                logger.exception('Feishu _send_text failed')
                return None

    # Register with the channel registry
    register_channel('feishu', FeishuChannel)

else:
    logger.info('lark-oapi SDK not installed; Feishu channel unavailable. Install with: pip install lark-oapi')
