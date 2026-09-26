import asyncio
import dataclasses
import logging
from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass
from datetime import date

from vera.compose import templates
from vera.compose.facts import (
    FactSheet,
    customer_facts,
    customer_salutation,
    merchant_facts,
    merchant_salutation,
)
from vera.compose.guardrails import review
from vera.compose.prompts import SYSTEM_PROMPT, Draft, initial_prompt, reply_prompt
from vera.compose.strategies import (
    FRAMINGS,
    CtaType,
    Framing,
    ReadContext,
    SendAs,
    TriggerFamily,
    TriggerRead,
    read_open_thread,
    strategy_for,
)
from vera.dialogue.language import customer_language, merchant_language
from vera.llm.base import LLMClient, LLMError
from vera.store.contexts import ContextBundle
from vera.store.conversations import Turn

log = logging.getLogger(__name__)

_UNKNOWN_SPECIFICS = {
    "event specifics": "not provided; mention only that it happened, with no names, places, "
    "times or other details about it"
}


@dataclass(frozen=True, slots=True)
class MessagePlan:
    kind: str
    framing: Framing
    read: TriggerRead
    sheet: FactSheet
    cta: CtaType
    suppression_key: str

    @property
    def send_as(self) -> SendAs:
        return self.framing.send_as

    @property
    def template_name(self) -> str:
        prefix = "merchant" if self.sheet.customer_facing else "vera"
        return f"{prefix}_{self.kind}_v1"


@dataclass(frozen=True, slots=True)
class ComposedMessage:
    body: str
    cta: CtaType
    send_as: SendAs
    rationale: str
    template_name: str
    template_params: tuple[str, ...]
    suppression_key: str
    generated_by: str


class Composer:
    def __init__(
        self, llm: LLMClient | None, timeout_seconds: float = 7.0, attempts: int = 2
    ) -> None:
        self._llm = llm
        self._timeout = timeout_seconds
        self._attempts = attempts

    def plan(self, bundle: ContextBundle, today: date) -> MessagePlan:
        trigger = bundle.trigger or {}
        ctx = ReadContext(bundle, today)
        if trigger:
            strategy = strategy_for(str(trigger.get("kind", "")), trigger.get("scope"))
            framing, read = strategy.framing, strategy.read(ctx)
            if (trigger.get("payload") or {}).get("placeholder"):
                read = dataclasses.replace(read, facts={**read.facts, **_UNKNOWN_SPECIFICS})
        else:
            framing, read = FRAMINGS[TriggerFamily.GENERIC], read_open_thread(ctx)
        kind = str(trigger.get("kind", "follow_up"))
        sheet = build_sheet(bundle, framing, read, kind, today)
        suppression_key = str(trigger.get("suppression_key") or f"{kind}:{bundle.merchant_id}")
        return MessagePlan(kind, framing, read, sheet, read.cta or framing.cta, suppression_key)

    async def compose(self, bundle: ContextBundle, today: date) -> ComposedMessage:
        plan = self.plan(bundle, today)
        draft = await self._draft(
            lambda feedback: initial_prompt(
                plan.sheet, plan.framing, plan.read, plan.cta, feedback
            ),
            plan.sheet,
        )
        if draft is None:
            return self.fallback(plan)
        params = tuple(draft.template_params[:3]) or templates.template_params(
            plan.sheet, plan.read, plan.cta
        )
        return ComposedMessage(
            body=draft.body.strip(),
            cta=plan.cta,
            send_as=plan.send_as,
            rationale=draft.rationale.strip(),
            template_name=plan.template_name,
            template_params=params,
            suppression_key=plan.suppression_key,
            generated_by="llm",
        )

    def fallback(self, plan: MessagePlan) -> ComposedMessage:
        return ComposedMessage(
            body=templates.initial_message(plan.sheet, plan.read, plan.cta),
            cta=plan.cta,
            send_as=plan.send_as,
            rationale=(
                f"{plan.framing.family.value.capitalize()} trigger ({plan.kind}): {plan.read.hook} "
                f"Offering to {plan.read.deliverable}. CTA: {plan.cta.value}."
            ),
            template_name=plan.template_name,
            template_params=templates.template_params(plan.sheet, plan.read, plan.cta),
            suppression_key=plan.suppression_key,
            generated_by="template",
        )

    async def write_reply(
        self,
        plan: MessagePlan,
        history: Sequence[Turn],
        intent: str,
        previous: Collection[str],
    ) -> Draft | None:
        return await self._draft(
            lambda feedback: reply_prompt(plan.sheet, plan.read, history, intent, feedback),
            plan.sheet,
            previous=previous,
            action_mode=intent == "commit",
            first_touch=False,
        )

    async def _draft(
        self,
        build_prompt: Callable[[Sequence[str]], str],
        sheet: FactSheet,
        previous: Collection[str] = (),
        action_mode: bool = False,
        first_touch: bool = True,
    ) -> Draft | None:
        if self._llm is None:
            return None
        feedback: list[str] = []
        try:
            async with asyncio.timeout(self._timeout):
                for _ in range(self._attempts):
                    draft = await self._llm.complete(SYSTEM_PROMPT, build_prompt(feedback), Draft)
                    feedback = review(
                        draft.body,
                        sheet,
                        previous=previous,
                        action_mode=action_mode,
                        first_touch=first_touch,
                    )
                    if not feedback:
                        return draft
                    log.info("draft rejected for %s: %s", sheet.kind, feedback)
        except (TimeoutError, LLMError) as error:
            log.warning("llm unavailable for %s: %s", sheet.kind, error)
        return None


def build_sheet(
    bundle: ContextBundle, framing: Framing, read: TriggerRead, kind: str, today: date
) -> FactSheet:
    category, merchant, customer = bundle.category, bundle.merchant, bundle.customer
    voice = category.get("voice", {})
    tone = f"{voice.get('tone', 'friendly')}, {voice.get('register', 'peer')}".replace("_", " ")
    business = str(merchant.get("identity", {}).get("name", "the business"))
    customer_facing = framing.family is TriggerFamily.CUSTOMER and customer is not None

    if customer_facing and customer is not None:
        facts = {
            **read.facts,
            **customer_facts(customer, today),
            "business": business,
            "active offers": merchant_facts(merchant, category)["active offers"],
        }
        return FactSheet(
            kind=kind,
            salutation=customer_salutation(customer),
            speaker=business,
            language=customer_language(customer),
            voice=f"warm and respectful, speaking for {business}; category tone: {tone}",
            taboos=tuple(voice.get("vocab_taboo", [])),
            vocabulary=(),
            facts=_compact(facts),
            customer_facing=True,
            talking_points=_talking_points(read),
        )

    return FactSheet(
        kind=kind,
        salutation=merchant_salutation(merchant, category),
        speaker="Vera",
        language=merchant_language(merchant, category),
        voice=tone,
        taboos=tuple(voice.get("vocab_taboo", [])),
        vocabulary=tuple(voice.get("vocab_allowed", [])),
        facts=_compact({**read.facts, **merchant_facts(merchant, category)}),
        talking_points=_talking_points(read),
    )


def _talking_points(read: TriggerRead) -> tuple[str, ...]:
    return (read.hook, read.proof, read.deliverable, read.closing, *read.options)


def _compact(facts: dict[str, str]) -> dict[str, str]:
    return {label: value for label, value in facts.items() if value and value != "None"}
