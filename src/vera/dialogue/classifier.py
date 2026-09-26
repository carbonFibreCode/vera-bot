import re
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from vera.llm.base import LLMClient, LLMError


class ReplyIntent(StrEnum):
    AUTO_REPLY = "auto_reply"
    OPT_OUT = "opt_out"
    HOSTILE = "hostile"
    COMMIT = "commit"
    DEFER = "defer"
    OFF_TOPIC = "off_topic"
    QUESTION = "question"
    ENGAGED = "engaged"


def _patterns(*phrases: str) -> re.Pattern[str]:
    return re.compile("|".join(rf"\b{p}\b" for p in phrases), re.IGNORECASE)


AUTO_REPLY = _patterns(
    r"thank you for (?:contacting|reaching out|your message)",
    r"thanks for (?:contacting|reaching out|your message)",
    r"(?:our|the) team will (?:respond|get back|revert|contact)",
    r"will get back to you (?:shortly|soon)",
    r"automated (?:assistant|message|reply|response)",
    r"auto[- ]?reply",
    r"currently (?:unavailable|away|closed)",
    r"out of (?:the )?office",
    r"business hours",
    r"jaankari ke liye (?:bahut[- ])?(?:bahut )?shukriya",
    r"team tak pahuncha",
)
OPT_OUT = _patterns(
    r"stop(?: messaging| sending| texting)?",
    r"unsubscribe",
    r"not interested",
    r"no interest",
    r"don'?t (?:message|contact|text|disturb)",
    r"leave me alone",
    r"remove (?:me|my number)",
    r"band karo",
    r"mat bhejo",
    r"nahi chahiye",
)
HOSTILE = _patterns(
    r"useless",
    r"spam(?:mer|ming)?",
    r"waste of time",
    r"nonsense",
    r"stupid",
    r"idiot",
    r"shut up",
    r"bothering me",
    r"fraud",
    r"scam",
    r"pagal",
    r"bakwas",
)
COMMIT = _patterns(
    r"let'?s do (?:it|this)",
    r"lets do it",
    r"go ahead",
    r"yes(?:,)? please",
    r"please (?:do|go ahead|proceed|send|draft|share|start)",
    r"do it",
    r"sounds good",
    r"proceed",
    r"confirm(?:ed)?",
    r"book (?:it|me)",
    r"i want to (?:join|start|do|go ahead)",
    r"(?:judna|judrna|jodna|join karna) hai",
    r"what'?s next",
    r"whats next",
    r"send (?:it|me|the)",
    r"haan(?: ji)?",
    r"kar do",
    r"karo",
    r"chalo",
    r"theek hai",
    r"ok(?:ay)?(?:,)? (?:done|sure|go)",
)
SHORT_YES = re.compile(r"^\W*(?:yes|yep|yeah|sure|ok|okay|done|haan|ha|ji)\W*$", re.IGNORECASE)
DEFER = _patterns(
    r"later",
    r"busy",
    r"not now",
    r"call (?:me )?later",
    r"tomorrow",
    r"next week",
    r"baad mein",
    r"kal",
)
OFF_TOPIC = _patterns(
    r"gst",
    r"income tax",
    r"itr",
    r"loan",
    r"insurance",
    r"visa",
    r"passport",
    r"electricity bill",
    r"stock market",
    r"cricket score",
)
_CHOICE = re.compile(r"^\s*(?:option\s*)?([1-9])\s*[.!)]?\s*$", re.IGNORECASE)


def slot_choice(message: str) -> int | None:
    match = _CHOICE.match(message)
    return int(match.group(1)) if match else None


def classify(message: str, repeat_count: int = 1) -> ReplyIntent | None:
    text = message.strip()
    canned_repeat = repeat_count >= 3 and len(text.split()) >= 4
    if canned_repeat or AUTO_REPLY.search(text):
        return ReplyIntent.AUTO_REPLY
    if OPT_OUT.search(text):
        return ReplyIntent.OPT_OUT
    if HOSTILE.search(text):
        return ReplyIntent.HOSTILE
    if OFF_TOPIC.search(text):
        return ReplyIntent.OFF_TOPIC
    if slot_choice(text) or SHORT_YES.match(text) or COMMIT.search(text):
        return ReplyIntent.COMMIT
    if DEFER.search(text):
        return ReplyIntent.DEFER
    if text.endswith("?"):
        return ReplyIntent.QUESTION
    return None


class _Verdict(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent: str = Field(json_schema_extra={"enum": [i.value for i in ReplyIntent]})


_CLASSIFIER_PROMPT = """\
Classify a merchant's WhatsApp reply to Vera, magicpin's assistant, into exactly one intent:
auto_reply (canned WhatsApp Business auto-response), opt_out (wants no more messages),
hostile (angry or abusive), commit (agrees or asks to proceed), defer (asks for later),
off_topic (asks for help unrelated to their listing, marketing or customers),
question (asks something about the offer or topic), engaged (anything else substantive)."""


async def classify_with_llm(message: str, llm: LLMClient | None) -> ReplyIntent:
    if llm is None:
        return ReplyIntent.ENGAGED
    try:
        verdict = await llm.complete(_CLASSIFIER_PROMPT, f"Reply: {message}", _Verdict)
    except LLMError:
        return ReplyIntent.ENGAGED
    return ReplyIntent(verdict.intent) if verdict.intent in ReplyIntent else ReplyIntent.ENGAGED
