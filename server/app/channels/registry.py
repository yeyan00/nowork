"""Channel registry — maps platform names to channel classes."""
from __future__ import annotations

import logging
from typing import Type

from .base import BaseChannel

logger = logging.getLogger('nowork.channels')

_registry: dict[str, Type[BaseChannel]] = {}


def register(platform: str, cls: Type[BaseChannel]) -> None:
    _registry[platform] = cls
    logger.debug('Channel registered: %s -> %s', platform, cls.__name__)


def get(platform: str) -> Type[BaseChannel] | None:
    return _registry.get(platform)


def list_platforms() -> list[str]:
    return list(_registry.keys())


def load_builtin_channels() -> None:
    try:
        from . import dingtalk as _dt  # noqa: F401
    except ImportError:
        logger.debug('dingtalk channel not available (missing dependency)')


load_builtin_channels()
