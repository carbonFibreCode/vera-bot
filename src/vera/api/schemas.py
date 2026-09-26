from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from vera.compose.strategies import CtaType, SendAs
from vera.dialogue.handler import ReplyAction
from vera.store.contexts import ContextScope


class ContextPush(BaseModel):
    scope: ContextScope
    context_id: str = Field(min_length=1)
    version: int = Field(ge=0)
    payload: dict[str, Any]
    delivered_at: str | None = None


class ContextAck(BaseModel):
    accepted: bool = True
    ack_id: str
    stored_at: str


class ContextRejection(BaseModel):
    accepted: bool = False
    reason: str
    current_version: int | None = None
    details: str | None = None


class TickRequest(BaseModel):
    now: datetime = Field(default_factory=lambda: datetime.now(UTC))
    available_triggers: list[str] = Field(default_factory=list)


class TickAction(BaseModel):
    conversation_id: str
    merchant_id: str
    customer_id: str | None
    send_as: SendAs
    trigger_id: str
    template_name: str
    template_params: list[str]
    body: str
    cta: CtaType
    suppression_key: str
    rationale: str


class TickResponse(BaseModel):
    actions: list[TickAction]


class ReplyRequest(BaseModel):
    conversation_id: str = Field(min_length=1)
    merchant_id: str | None = None
    customer_id: str | None = None
    from_role: str = "merchant"
    message: str
    received_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    turn_number: int = 0


class ReplyResponse(BaseModel):
    action: ReplyAction
    rationale: str
    body: str | None = None
    cta: CtaType | None = None
    wait_seconds: int | None = None


class Health(BaseModel):
    status: str = "ok"
    uptime_seconds: int
    contexts_loaded: dict[str, int]


class Metadata(BaseModel):
    team_name: str
    team_members: list[str]
    model: str
    approach: str
    contact_email: str
    version: str
    submitted_at: str
