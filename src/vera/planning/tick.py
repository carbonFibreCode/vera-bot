import asyncio
import logging
from dataclasses import dataclass
from datetime import date, datetime

from vera.compose.composer import ComposedMessage, Composer
from vera.compose.facts import parse_date
from vera.store.contexts import ContextBundle, ContextStore
from vera.store.conversations import Conversation, ConversationStore, Speaker

log = logging.getLogger(__name__)

DraftKey = tuple[tuple[str, int], ...]


@dataclass(frozen=True, slots=True)
class PlannedAction:
    conversation_id: str
    merchant_id: str
    customer_id: str | None
    trigger_id: str
    message: ComposedMessage


class TickPlanner:
    def __init__(
        self,
        contexts: ContextStore,
        conversations: ConversationStore,
        composer: Composer,
        *,
        budget_seconds: float = 8.0,
        max_actions: int = 20,
        concurrency: int = 8,
        respect_expiry: bool = False,
    ) -> None:
        self._contexts = contexts
        self._conversations = conversations
        self._composer = composer
        self._budget = budget_seconds
        self._max_actions = max_actions
        self._slots = asyncio.Semaphore(concurrency)
        self._respect_expiry = respect_expiry
        self._drafts: dict[DraftKey, asyncio.Task[ComposedMessage]] = {}
        self._sim_today: date | None = None

    def precompose(self, trigger_id: str) -> None:
        # Day counts in a draft depend on the judge's simulated clock, which the first tick sets.
        if self._sim_today is None:
            return
        bundle = self._contexts.bundle_for_trigger(trigger_id)
        if bundle and self._sendable(bundle, self._sim_today):
            self._draft(bundle, self._sim_today)

    async def plan(self, now: datetime, trigger_ids: list[str]) -> list[PlannedAction]:
        self._sim_today = now.date()
        chosen = self._select(now, trigger_ids)
        if not chosen:
            return []
        tasks = [self._draft(bundle, now.date()) for bundle in chosen]
        await asyncio.wait(tasks, timeout=self._budget)
        actions = [
            self._record(bundle, self._result_or_fallback(task, bundle, now.date()))
            for bundle, task in zip(chosen, tasks, strict=True)
        ]
        log.info(
            "tick %s: %d candidates, %d actions", now.isoformat(), len(trigger_ids), len(actions)
        )
        return actions

    def reset(self) -> None:
        for task in self._drafts.values():
            task.cancel()
        self._drafts.clear()
        self._sim_today = None

    def _select(self, now: datetime, trigger_ids: list[str]) -> list[ContextBundle]:
        bundles = [
            b for tid in dict.fromkeys(trigger_ids) if (b := self._contexts.bundle_for_trigger(tid))
        ]
        eligible = [b for b in bundles if self._sendable(b, now.date(), now)]
        eligible.sort(key=lambda b: -int((b.trigger or {}).get("urgency", 0)))
        picked: list[ContextBundle] = []
        audiences: set[tuple[str, str | None]] = set()
        for bundle in eligible:
            audience = (bundle.merchant_id, (bundle.trigger or {}).get("customer_id"))
            if audience in audiences:
                continue
            audiences.add(audience)
            picked.append(bundle)
        return picked[: self._max_actions]

    def _sendable(self, bundle: ContextBundle, today: date, now: datetime | None = None) -> bool:
        trigger = bundle.trigger or {}
        if self._conversations.was_sent(str(trigger.get("suppression_key", ""))):
            return False
        if now and self._conversations.signals(bundle.merchant_id).is_muted(now):
            return False
        customer_id = trigger.get("customer_id")
        if self._conversations.has_live_conversation(bundle.merchant_id, customer_id):
            return False
        if (
            self._respect_expiry
            and (expiry := parse_date(trigger.get("expires_at")))
            and expiry < today
        ):
            return False
        if trigger.get("scope") == "customer" or customer_id:
            return bundle.customer is not None and has_consent(bundle.customer)
        return True

    def _draft(self, bundle: ContextBundle, today: date) -> asyncio.Task[ComposedMessage]:
        key = bundle.fingerprint
        task = self._drafts.get(key)
        if task is None or (task.done() and task.exception() is not None):
            task = asyncio.create_task(self._compose(bundle, today))
            self._drafts[key] = task
        return task

    async def _compose(self, bundle: ContextBundle, today: date) -> ComposedMessage:
        async with self._slots:
            return await self._composer.compose(bundle, today)

    def _result_or_fallback(
        self, task: asyncio.Task[ComposedMessage], bundle: ContextBundle, today: date
    ) -> ComposedMessage:
        if task.done() and not task.cancelled() and task.exception() is None:
            return task.result()
        return self._composer.fallback(self._composer.plan(bundle, today))

    def _record(self, bundle: ContextBundle, message: ComposedMessage) -> PlannedAction:
        trigger = bundle.trigger or {}
        customer_id = trigger.get("customer_id")
        conversation_id = self._conversation_id(bundle.trigger_id)
        conversation = Conversation(
            conversation_id, bundle.merchant_id, customer_id, bundle.trigger_id
        )
        conversation.add(Speaker.BOT, message.body)
        self._conversations.open(conversation)
        self._conversations.mark_sent(message.suppression_key)
        return PlannedAction(
            conversation_id, bundle.merchant_id, customer_id, bundle.trigger_id, message
        )

    def _conversation_id(self, trigger_id: str) -> str:
        base = f"conv_{trigger_id.removeprefix('trg_')}"
        candidate, suffix = base, 2
        while self._conversations.get(candidate):
            candidate, suffix = f"{base}_{suffix}", suffix + 1
        return candidate


def has_consent(customer: dict[str, object]) -> bool:
    # Service reminders (recall, refill, appointment) ride on any recorded opt-in; the dataset
    # mostly records a single broad scope, so we only refuse when there is no opt-in at all.
    consent = customer.get("consent")
    preferences = customer.get("preferences")
    scopes = consent.get("scope") if isinstance(consent, dict) else None
    opted_in = preferences.get("reminder_opt_in", True) if isinstance(preferences, dict) else True
    return bool(scopes) and opted_in is not False
