"""Channel data schemas."""
from __future__ import annotations

from typing import Any, Callable, Optional
from pydantic import BaseModel, ConfigDict


SUPPORTED_PLATFORMS = ('dingtalk', 'feishu', 'wecom')


class ChannelConfig(BaseModel):
    id: str
    platform: str
    name: str = ''
    enabled: bool = False
    worker_id: str = ''
    config: dict[str, Any] = {}

    def platform_config(self, key: str, default: Any = None) -> Any:
        return self.config.get(key, default)


class ChannelMessage(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    channel_id: str
    platform: str
    sender_id: str
    session_id: str
    text: str = ''
    meta: dict[str, Any] = {}
    # Callback for streaming reply chunks.  Not serialized.
    # Signature: async (chunk_text: str) -> None
    # Returns: None (钉钉) or message_id (飞书，用于后续编辑)
    on_reply_chunk: Optional[Callable[[str], Any]] = None
    # Callback for editing an existing message (飞书 only).  Not serialized.
    # Signature: async (message_id: str, chunk_text: str) -> None
    on_edit_message: Optional[Callable[[str, str], Any]] = None


class ChannelStatus(BaseModel):
    id: str
    platform: str
    name: str
    enabled: bool
    worker_id: str
    status: str = 'stopped'
    detail: str = ''
