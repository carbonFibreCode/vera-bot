import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum


class ConversationPhase(StrEnum):
    PITCHING = "pitching"
    ACTING = "acting"
    WAITING = "waiting"
    ENDED = "ended"


class Speaker(StrEnum):
    BOT = "bot"
    MERCHANT = "merchant"
    CUSTOMER = "customer"


@dataclass(frozen=True, slots=True)
class Turn:
    speaker: Speaker
    body: str


@dataclass(slots=True)
class Conversation:
    conversation_id: str
    merchant_id: str
    customer_id: str | None = None
    trigger_id: str | None = None
    phase: ConversationPhase = ConversationPhase.PITCHING
    turns: list[Turn] = field(default_factory=list)

    def add(self, speaker: Speaker, body: str) -> None:
        self.turns.append(Turn(speaker, body))

    @property
    def bot_bodies(self) -> set[str]:
        return {normalize(t.body) for t in self.turns if t.speaker is Speaker.BOT}

    @property
    def bot_turn_count(self) -> int:
        return sum(t.speaker is Speaker.BOT for t in self.turns)


@dataclass(slots=True)
class MerchantSignals:
    inbound_counts: dict[str, int] = field(default_factory=dict)
    auto_reply_strikes: int = 0
    muted_until: datetime | None = None

    def observe(self, message: str) -> int:
        key = normalize(message)
        self.inbound_counts[key] = self.inbound_counts.get(key, 0) + 1
        return self.inbound_counts[key]

    def is_muted(self, now: datetime) -> bool:
        return self.muted_until is not None and now < self.muted_until


class ConversationStore:
    def __init__(self) -> None:
        self._conversations: dict[str, Conversation] = {}
        self._signals: dict[str, MerchantSignals] = {}
        self._sent_suppression_keys: set[str] = set()

    def get(self, conversation_id: str) -> Conversation | None:
        return self._conversations.get(conversation_id)

    def open(self, conversation: Conversation) -> Conversation:
        self._conversations[conversation.conversation_id] = conversation
        return conversation

    def get_or_open(
        self, conversation_id: str, merchant_id: str, customer_id: str | None
    ) -> Conversation:
        existing = self._conversations.get(conversation_id)
        if existing:
            return existing
        return self.open(Conversation(conversation_id, merchant_id, customer_id))

    def signals(self, merchant_id: str) -> MerchantSignals:
        return self._signals.setdefault(merchant_id, MerchantSignals())

    def mute(self, merchant_id: str, now: datetime, days: int) -> None:
        self.signals(merchant_id).muted_until = now + timedelta(days=days)

    def has_live_conversation(self, merchant_id: str, customer_id: str | None) -> bool:
        return any(
            c.merchant_id == merchant_id
            and c.customer_id == customer_id
            and c.phase in (ConversationPhase.ACTING, ConversationPhase.WAITING)
            for c in self._conversations.values()
        )

    def mark_sent(self, suppression_key: str) -> None:
        if suppression_key:
            self._sent_suppression_keys.add(suppression_key)

    def was_sent(self, suppression_key: str) -> bool:
        return suppression_key in self._sent_suppression_keys

    def clear(self) -> None:
        self._conversations.clear()
        self._signals.clear()
        self._sent_suppression_keys.clear()


def normalize(text: str) -> str:
    return re.sub(r"\W+", " ", text.casefold()).strip()
