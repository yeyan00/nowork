from typing import Any, Optional

from pydantic import BaseModel, Field


class WorkerCreatePayload(BaseModel):
    type: str
    name: str
    description: str = ''
    status: str = 'active'
    config: dict[str, Any] = Field(default_factory=dict)
    clone_from: Optional[str] = None


class WorkerUpdatePayload(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    agentType: Optional[str] = None
    config: dict[str, Any] = Field(default_factory=dict)


class SessionCreatePayload(BaseModel):
    title: str
    workspaces: Optional[list[str]] = None


class SessionUpdatePayload(BaseModel):
    title: Optional[str] = None
    workspaces: Optional[list[str]] = None
    modelOverride: Optional[str] = None
    learningEnabled: Optional[bool] = None


class AttachmentPayload(BaseModel):
    kind: str
    path: str
    mimeType: Optional[str] = None
    name: Optional[str] = None


class MessageCreatePayload(BaseModel):
    content: str
    attachments: list[AttachmentPayload] = Field(default_factory=list)


class SchedulePayload(BaseModel):
    name: str
    enabled: bool = True
    workerId: str
    prompt: str
    sessionTitleTemplate: Optional[str] = None
    workspaces: Optional[list[str]] = None
    triggerType: str
    time: str
    weekdays: Optional[list[int]] = None
    timezone: str = 'UTC'
    misfirePolicy: str = 'run_once'
    createNewSession: bool = True
