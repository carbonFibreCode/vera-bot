import time
from dataclasses import dataclass
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from vera.api.schemas import (
    ContextAck,
    ContextPush,
    ContextRejection,
    Health,
    Metadata,
    ReplyRequest,
    ReplyResponse,
    TickAction,
    TickRequest,
    TickResponse,
)
from vera.config import Settings
from vera.dialogue.handler import InboundReply, ReplyHandler
from vera.planning.tick import TickPlanner
from vera.store.contexts import ContextScope, ContextStore, StaleVersionError
from vera.store.conversations import ConversationStore

APPROACH = (
    "Deterministic fact sheet per (category, merchant, trigger, customer), trigger-family "
    "strategies, LLM writes only from verified facts, guardrails reject ungrounded numbers, "
    "taboos, URLs and repeats, with grounded template fallback; rule-first reply state machine."
)


@dataclass(slots=True)
class Services:
    settings: Settings
    contexts: ContextStore
    conversations: ConversationStore
    planner: TickPlanner
    replies: ReplyHandler
    model_name: str
    started_at: float


def get_services(request: Request) -> Services:
    services: Services = request.app.state.services
    return services


ServicesDep = Annotated[Services, Depends(get_services)]
router = APIRouter(prefix="/v1")


@router.get("/healthz", response_model=Health)
async def healthz(services: ServicesDep) -> Health:
    return Health(
        uptime_seconds=int(time.monotonic() - services.started_at),
        contexts_loaded=services.contexts.counts(),
    )


@router.get("/metadata", response_model=Metadata)
async def metadata(services: ServicesDep) -> Metadata:
    settings = services.settings
    return Metadata(
        team_name=settings.team_name,
        team_members=settings.team_members,
        model=services.model_name,
        approach=APPROACH,
        contact_email=settings.contact_email,
        version=settings.version,
        submitted_at=settings.submitted_at,
    )


@router.post("/context", response_model=ContextAck, responses={409: {"model": ContextRejection}})
async def push_context(push: ContextPush, services: ServicesDep) -> ContextAck | JSONResponse:
    try:
        stored = services.contexts.put(push.scope, push.context_id, push.version, push.payload)
    except StaleVersionError as error:
        rejection = ContextRejection(reason="stale_version", current_version=error.current_version)
        return JSONResponse(status_code=409, content=rejection.model_dump(exclude_none=True))
    if push.scope is ContextScope.TRIGGER:
        services.planner.precompose(push.context_id)
    return ContextAck(
        ack_id=f"ack_{push.context_id}_v{push.version}",
        stored_at=stored.stored_at.isoformat().replace("+00:00", "Z"),
    )


@router.post("/tick", response_model=TickResponse)
async def tick(request: TickRequest, services: ServicesDep) -> TickResponse:
    planned = await services.planner.plan(request.now, request.available_triggers)
    return TickResponse(
        actions=[
            TickAction(
                conversation_id=p.conversation_id,
                merchant_id=p.merchant_id,
                customer_id=p.customer_id,
                send_as=p.message.send_as,
                trigger_id=p.trigger_id,
                template_name=p.message.template_name,
                template_params=list(p.message.template_params),
                body=p.message.body,
                cta=p.message.cta,
                suppression_key=p.message.suppression_key,
                rationale=p.message.rationale,
            )
            for p in planned
        ]
    )


@router.post("/reply", response_model=ReplyResponse, response_model_exclude_none=True)
async def reply(request: ReplyRequest, services: ServicesDep) -> ReplyResponse:
    decision = await services.replies.handle(
        InboundReply(
            conversation_id=request.conversation_id,
            merchant_id=request.merchant_id,
            customer_id=request.customer_id,
            from_role=request.from_role,
            message=request.message,
            received_at=request.received_at,
        )
    )
    return ReplyResponse(
        action=decision.action,
        rationale=decision.rationale,
        body=decision.body,
        cta=decision.cta,
        wait_seconds=decision.wait_seconds,
    )


@router.post("/teardown")
async def teardown(services: ServicesDep) -> dict[str, bool]:
    services.planner.reset()
    services.contexts.clear()
    services.conversations.clear()
    return {"ok": True}
