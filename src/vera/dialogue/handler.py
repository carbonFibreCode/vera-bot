import dataclasses
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from vera.compose import templates
from vera.compose.composer import Composer, MessagePlan
from vera.compose.strategies import CtaType, TriggerRead
from vera.dialogue.classifier import ReplyIntent, classify, classify_with_llm, slot_choice
from vera.dialogue.language import Language, detect_language
from vera.llm.base import LLMClient
from vera.store.contexts import ContextStore
from vera.store.conversations import (
    Conversation,
    ConversationPhase,
    ConversationStore,
    Speaker,
    normalize,
)

AUTO_REPLY_BACKOFF_SECONDS = 86_400
DEFER_SECONDS = 14_400
DEFER_LONG_SECONDS = 86_400
MUTE_DAYS = 30
MAX_BOT_TURNS = 6

_UNKNOWN_THREAD = TriggerRead(
    facts={},
    hook="following up on my last message.",
    deliverable="take care of the next step for you",
)


class ReplyAction(StrEnum):
    SEND = "send"
    WAIT = "wait"
    END = "end"


@dataclass(frozen=True, slots=True)
class InboundReply:
    conversation_id: str
    merchant_id: str | None
    customer_id: str | None
    from_role: str
    message: str
    received_at: datetime


@dataclass(frozen=True, slots=True)
class ReplyDecision:
    action: ReplyAction
    rationale: str
    body: str | None = None
    cta: CtaType | None = None
    wait_seconds: int | None = None


def send(body: str, cta: CtaType, rationale: str) -> ReplyDecision:
    return ReplyDecision(ReplyAction.SEND, rationale, body=body, cta=cta)


def wait(seconds: int, rationale: str) -> ReplyDecision:
    return ReplyDecision(ReplyAction.WAIT, rationale, wait_seconds=seconds)


def end(rationale: str) -> ReplyDecision:
    return ReplyDecision(ReplyAction.END, rationale)


class ReplyHandler:
    def __init__(
        self,
        contexts: ContextStore,
        conversations: ConversationStore,
        composer: Composer,
        llm: LLMClient | None,
    ) -> None:
        self._contexts = contexts
        self._conversations = conversations
        self._composer = composer
        self._llm = llm

    async def handle(self, reply: InboundReply) -> ReplyDecision:
        conversation = self._conversations.get_or_open(
            reply.conversation_id, reply.merchant_id or "", reply.customer_id
        )
        if conversation.phase is ConversationPhase.ENDED:
            return end("Conversation already closed; not sending anything further.")

        speaker = Speaker.CUSTOMER if reply.from_role == "customer" else Speaker.MERCHANT
        conversation.add(speaker, reply.message)
        signals = self._conversations.signals(conversation.merchant_id)
        repeats = signals.observe(reply.message)
        intent = classify(reply.message, repeats) or await classify_with_llm(
            reply.message, self._llm
        )
        if intent is not ReplyIntent.AUTO_REPLY:
            signals.auto_reply_strikes = 0

        decision = await self._decide(intent, conversation, reply)
        if decision.action is ReplyAction.SEND and decision.body:
            conversation.add(Speaker.BOT, decision.body)
        elif decision.action is ReplyAction.END:
            conversation.phase = ConversationPhase.ENDED
        else:
            conversation.phase = ConversationPhase.WAITING
        return decision

    async def _decide(
        self, intent: ReplyIntent, conversation: Conversation, reply: InboundReply
    ) -> ReplyDecision:
        match intent:
            case ReplyIntent.AUTO_REPLY:
                return self._on_auto_reply(conversation)
            case ReplyIntent.OPT_OUT | ReplyIntent.HOSTILE:
                self._conversations.mute(conversation.merchant_id, reply.received_at, MUTE_DAYS)
                return end(
                    f"Merchant signalled {intent.value.replace('_', '-')}; closing politely and "
                    f"pausing all outreach to them for {MUTE_DAYS} days."
                )
            case ReplyIntent.DEFER:
                long_wait = any(
                    w in reply.message.casefold() for w in ("tomorrow", "kal", "next week")
                )
                seconds = DEFER_LONG_SECONDS if long_wait else DEFER_SECONDS
                return wait(seconds, f"Merchant asked for time; backing off {seconds // 3600}h.")

        if conversation.bot_turn_count >= MAX_BOT_TURNS:
            return end(
                "Conversation has run its course without a new commitment; exiting gracefully."
            )

        plan = self._plan(conversation, reply)
        if intent is ReplyIntent.COMMIT:
            return await self._on_commit(conversation, plan, reply)
        return await self._on_conversation(intent, conversation, plan)

    def _on_auto_reply(self, conversation: Conversation) -> ReplyDecision:
        signals = self._conversations.signals(conversation.merchant_id)
        signals.auto_reply_strikes += 1
        if signals.auto_reply_strikes == 1:
            read = self._read_for(conversation)
            return send(
                templates.owner_nudge(read),
                CtaType.BINARY_YES_NO,
                "Detected a WhatsApp Business auto-reply; one short note so the owner can pick it up.",
            )
        if signals.auto_reply_strikes == 2:
            return wait(
                AUTO_REPLY_BACKOFF_SECONDS,
                "Same canned auto-reply again, so the owner isn't at the phone. Waiting 24h.",
            )
        return end("Auto-reply three times in a row with no human response; closing the thread.")

    async def _on_commit(
        self, conversation: Conversation, plan: MessagePlan | None, reply: InboundReply
    ) -> ReplyDecision:
        read = plan.read if plan else _UNKNOWN_THREAD
        customer_facing = bool(plan and plan.sheet.customer_facing)

        if customer_facing and plan:
            choice = slot_choice(reply.message)
            if choice and choice <= len(plan.read.options):
                conversation.phase = ConversationPhase.ACTING
                return send(
                    templates.slot_booked(plan.read.options[choice - 1]),
                    CtaType.NONE,
                    f"Customer picked slot {choice}; confirming the booking.",
                )
            conversation.phase = ConversationPhase.ACTING
            return send(
                templates.action_reply(read, customer_facing=True),
                CtaType.NONE,
                "Customer said yes; confirming without further questions.",
            )

        if conversation.phase is ConversationPhase.ACTING:
            return self._unique(
                conversation,
                [templates.completion_reply()],
                CtaType.NONE,
                "Merchant confirmed the drafted work; closing the loop with what happens next.",
            )

        conversation.phase = ConversationPhase.ACTING
        body = await self._llm_reply(plan, conversation, "commit")
        return self._unique(
            conversation,
            [body, templates.action_reply(read, customer_facing=False)],
            CtaType.BINARY_CONFIRM_CANCEL,
            "Merchant committed; switching from pitch to action immediately with a concrete next "
            "step and a single CONFIRM.",
        )

    async def _on_conversation(
        self, intent: ReplyIntent, conversation: Conversation, plan: MessagePlan | None
    ) -> ReplyDecision:
        read = plan.read if plan else _UNKNOWN_THREAD
        body = await self._llm_reply(plan, conversation, intent.value)
        if intent is ReplyIntent.OFF_TOPIC:
            return self._unique(
                conversation,
                [body, templates.off_topic_reply(read)],
                CtaType.OPEN_ENDED,
                "Out-of-scope ask declined politely; steering back to the open thread.",
            )
        attempts = conversation.bot_turn_count
        return self._unique(
            conversation,
            [body, *(templates.engaged_reply(read, attempts + i) for i in range(3))],
            CtaType.BINARY_YES_NO,
            "Answered the merchant from known context and moved the thread one step forward.",
        )

    async def _llm_reply(
        self, plan: MessagePlan | None, conversation: Conversation, intent: str
    ) -> str | None:
        if plan is None:
            return None
        draft = await self._composer.write_reply(
            plan,
            conversation.turns,
            intent,
            previous=[t.body for t in conversation.turns if t.speaker is Speaker.BOT],
        )
        return draft.body.strip() if draft else None

    def _unique(
        self, conversation: Conversation, candidates: list[str | None], cta: CtaType, rationale: str
    ) -> ReplyDecision:
        sent = conversation.bot_bodies
        for body in candidates:
            if body and normalize(body) not in sent:
                return send(body, cta, rationale)
        return wait(
            DEFER_SECONDS, "Nothing new worth saying yet; holding back instead of repeating."
        )

    def _plan(self, conversation: Conversation, reply: InboundReply) -> MessagePlan | None:
        bundle = (
            self._contexts.bundle_for_trigger(conversation.trigger_id)
            if conversation.trigger_id
            else None
        ) or self._contexts.bundle_for_merchant(conversation.merchant_id, conversation.customer_id)
        if bundle is None:
            return None
        plan = self._composer.plan(bundle, reply.received_at.date())
        spoken = detect_language(reply.message)
        if spoken is not Language.ENGLISH and spoken is not plan.sheet.language:
            plan = dataclasses.replace(plan, sheet=dataclasses.replace(plan.sheet, language=spoken))
        return plan

    def _read_for(self, conversation: Conversation) -> TriggerRead:
        bundle = self._contexts.bundle_for_trigger(conversation.trigger_id or "")
        if bundle is None:
            return _UNKNOWN_THREAD
        return self._composer.plan(bundle, datetime.now().date()).read
