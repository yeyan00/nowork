"""BaseChannel — abstract interface for all channel platforms.

Inspired by QwenPaw BaseChannel (Apache-2.0), simplified for nowork architecture.
"""
from __future__ import annotations

import abc
import logging
from typing import Any, Callable, Optional

from .schema import ChannelConfig, ChannelMessage

logger = logging.getLogger('nowork.channels')

OnMessageCallback = Callable[[ChannelMessage], Any]


class BaseChannel(abc.ABC):
    """Abstract base class for all channel platforms.

    Subclasses must implement:
      - start(): connect to platform, begin receiving messages
      - stop(): disconnect and clean up
      - send(session_id, text, meta): send a reply to the user

    On message received, call self._on_message(msg) which routes through
    the manager to stream_message and then back to send().
    """

    platform: str = ''

    def __init__(self, cfg: ChannelConfig, on_message: OnMessageCallback):
        self.cfg = cfg
        self._on_message = on_message
        self._status = 'stopped'
        self._detail = ''

    @property
    def channel_id(self) -> str:
        return self.cfg.id

    @property
    def worker_id(self) -> str:
        return self.cfg.worker_id

    @property
    def status(self) -> str:
        return self._status

    @property
    def detail(self) -> str:
        return self._detail

    def resolve_session_id(self, sender_id: str, meta: dict[str, Any] | None = None) -> str:
        return f'{self.platform}:{sender_id}'

    @abc.abstractmethod
    async def start(self) -> None:
        raise NotImplementedError

    @abc.abstractmethod
    async def stop(self) -> None:
        raise NotImplementedError

    @abc.abstractmethod
    async def send(self, session_id: str, text: str, meta: dict[str, Any] | None = None) -> None:
        raise NotImplementedError

    async def health_check(self) -> dict[str, Any]:
        return {
            'id': self.channel_id,
            'platform': self.platform,
            'status': self._status,
            'detail': self._detail,
        }
