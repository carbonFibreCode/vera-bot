from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict

from vera.compose.facts import FactSheet
from vera.compose.strategies import CtaType, Framing, TriggerRead
from vera.dialogue.language import Language
from vera.store.conversations import Turn

SYSTEM_PROMPT = """\
You write WhatsApp messages for Vera, magicpin's assistant for Indian local merchants \
(dentists, salons, gyms, restaurants, pharmacies). Sometimes you write as Vera to the merchant; \
sometimes you write as the merchant's business to one of its own customers.

Hard rules:
1. Use only the FACTS given. Never invent numbers, dates, times, prices, names, research, \
competitors, offers, results, schedules, durations, ages or program details. Every number you \
write must appear in FACTS. If a detail is missing, leave it out.
2. Start with the name given in ADDRESS THEM AS, then say why you are writing now, anchored on \
one or two concrete facts the reader can check.
3. Sound like a knowledgeable peer, not an advertiser. Match the category voice. No hype, no \
exclamation-heavy promo copy, no "I hope you're doing well" preambles, no self-introductions \
when writing as Vera. Prefer service-and-price offers; never lead with a percentage discount.
4. Only mention a trend, dip or risk when FACTS show it for this reader.
5. Exactly one call to action as the last sentence: either one direct question or one \
"Reply ..." instruction. Never add "(Yes/No)" or "let me know if".
6. No links or URLs. No internal field names or snake_case words.
7. Language: follow the LANGUAGE line exactly. Hindi is written in Roman script, the way people \
type on WhatsApp. Vera is female, so in Hindi she says "main bhej sakti hoon", "kar dungi".
8. Keep it tight: 2 to 5 short sentences, under 600 characters.

Return JSON with:
- body: the message text
- rationale: one or two sentences on why this message and what it should achieve, true to the body
- template_params: 3 short strings [salutation, why-now line, call to action] for the WhatsApp \
template version of the message"""

_LANGUAGE_RULES = {
    Language.ENGLISH: "English.",
    Language.HINGLISH: "Natural Hindi-English code-mix (roughly half Hindi words), e.g. "
    "'Aapke high-risk patients ke liye yeh kaafi relevant hai'.",
    Language.HINDI: "Mostly Hindi in Roman script; keep prices, dates and product names as-is.",
}

_REPLY_DIRECTIVES = {
    "commit": "The reader just agreed. Switch to action mode now: say what you are doing, give the "
    "concrete draft or next step using FACTS, and end with a single line asking them to reply "
    "CONFIRM. Do not ask any qualifying question. Never use the phrases 'would you', 'do you', "
    "'can you tell', 'what if' or 'how about'.",
    "question": "Answer their message directly using FACTS only. If FACTS do not hold the answer, "
    "say so honestly in a few words. Then give one clear next step.",
    "off_topic": "They asked about something outside what Vera handles. Decline politely in one "
    "short line, then steer back to the open thread with one clear next step.",
    "engaged": "Respond to what they said, move the conversation one step forward, and end with a "
    "single clear next step.",
}


class Draft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    body: str
    rationale: str
    template_params: list[str]


def initial_prompt(
    sheet: FactSheet, framing: Framing, read: TriggerRead, cta: CtaType, feedback: Sequence[str]
) -> str:
    sections = [
        _header(sheet),
        f"TRIGGER: {sheet.kind} ({framing.family.value})",
        f"ANGLE: {framing.angle}",
        f"LEVERS TO USE: {', '.join(framing.levers)}",
        f"WHY NOW: {read.hook}",
        f"SUGGESTED NEXT STEP: {read.closing or 'offer to ' + read.deliverable}",
        f"CTA TYPE: {cta.value}",
        "FACTS:\n" + sheet.render(),
    ]
    if feedback:
        sections.append(
            "YOUR PREVIOUS DRAFT WAS REJECTED. Fix these problems:\n- " + "\n- ".join(feedback)
        )
    sections.append("Write the first message now.")
    return "\n\n".join(sections)


def reply_prompt(
    sheet: FactSheet,
    read: TriggerRead,
    history: Sequence[Turn],
    intent: str,
    feedback: Sequence[str],
) -> str:
    transcript = "\n".join(f"{turn.speaker.value.upper()}: {turn.body}" for turn in history[-8:])
    sections = [
        _header(sheet),
        f"OPEN THREAD: {read.hook} Offer on the table: {read.deliverable}.",
        "FACTS:\n" + sheet.render(),
        "CONVERSATION SO FAR:\n" + transcript,
        f"YOUR TASK: {_REPLY_DIRECTIVES.get(intent, _REPLY_DIRECTIVES['engaged'])}",
        "Do not repeat any earlier BOT message and do not re-introduce yourself.",
    ]
    if feedback:
        sections.append(
            "YOUR PREVIOUS DRAFT WAS REJECTED. Fix these problems:\n- " + "\n- ".join(feedback)
        )
    return "\n\n".join(sections)


def _header(sheet: FactSheet) -> str:
    if sheet.customer_facing:
        audience = f"a customer of {sheet.speaker}; you write as the business itself"
    else:
        audience = "the merchant; you write as Vera"
    vocabulary = ", ".join(sheet.vocabulary[:12]) or "plain words"
    taboos = ", ".join(sheet.taboos) or "none"
    return "\n".join(
        [
            f"READER: {audience}",
            f"ADDRESS THEM AS: {sheet.salutation}",
            f"LANGUAGE: {_LANGUAGE_RULES[sheet.language]}",
            f"VOICE: {sheet.voice}",
            f"VOCABULARY THAT FITS: {vocabulary}",
            f"NEVER SAY: {taboos}",
        ]
    )
