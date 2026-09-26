import logging
import os
import time

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from vera.api.routes import Services, router
from vera.compose.composer import Composer
from vera.config import GROQ_BASE_URL, Settings, get_settings
from vera.dialogue.handler import ReplyHandler
from vera.llm.anthropic import AnthropicClient
from vera.llm.base import LLMClient
from vera.llm.openai_compat import OpenAICompatibleClient
from vera.planning.tick import TickPlanner
from vera.store.contexts import ContextStore
from vera.store.conversations import ConversationStore

log = logging.getLogger("vera")


def build_llm(settings: Settings) -> LLMClient | None:
    api_key = settings.llm_api_key.get_secret_value() if settings.llm_api_key else None
    model, timeout = settings.model_name, settings.llm_timeout_seconds
    match settings.llm_provider:
        case "groq" if api_key:
            reasoning = {"reasoning_effort": "low", "include_reasoning": False}
            return OpenAICompatibleClient(
                model,
                settings.llm_base_url or GROQ_BASE_URL,
                api_key,
                timeout,
                strict_schema=model.startswith("openai/gpt-oss"),
                extra=reasoning if model.startswith("openai/gpt-oss") else None,
            )
        case "anthropic" if api_key or os.environ.get("ANTHROPIC_API_KEY"):
            return AnthropicClient(model, timeout, api_key)
        case "openai_compat" if api_key and settings.llm_base_url:
            return OpenAICompatibleClient(model, settings.llm_base_url, api_key, timeout)
    if settings.llm_provider != "none":
        log.warning("no API key for %s; running on templates only", settings.llm_provider)
    return None


def create_app(settings: Settings | None = None, llm: LLMClient | None = None) -> FastAPI:
    settings = settings or get_settings()
    client = llm or build_llm(settings)

    contexts = ContextStore()
    conversations = ConversationStore()
    composer = Composer(client, timeout_seconds=settings.llm_timeout_seconds)
    planner = TickPlanner(
        contexts,
        conversations,
        composer,
        budget_seconds=settings.tick_budget_seconds,
        max_actions=settings.max_actions_per_tick,
        concurrency=settings.compose_concurrency,
        respect_expiry=settings.respect_trigger_expiry,
    )

    app = FastAPI(title="Vera merchant bot", version=settings.version)
    app.state.services = Services(
        settings=settings,
        contexts=contexts,
        conversations=conversations,
        planner=planner,
        replies=ReplyHandler(contexts, conversations, composer, client),
        model_name=client.name if client else "templates-only",
        started_at=time.monotonic(),
    )
    app.include_router(router)
    app.add_exception_handler(RequestValidationError, _reject_malformed)  # type: ignore[arg-type]
    return app


async def _reject_malformed(request: Request, error: RequestValidationError) -> JSONResponse:
    fields = {str(part) for issue in error.errors() for part in issue.get("loc", ())}
    reason = "invalid_scope" if "scope" in fields else "invalid_request"
    return JSONResponse(
        status_code=400,
        content={"accepted": False, "reason": reason, "details": str(error.errors()[:3])},
    )
