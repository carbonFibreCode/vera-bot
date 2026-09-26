import re
from collections.abc import Collection

from vera.compose.facts import FactSheet, numbers_in
from vera.dialogue.language import Language, has_hindi_flavour
from vera.store.conversations import normalize

MAX_BODY_CHARS = 700
SAFE_NUMBERS = frozenset({1.0, 2.0})

QUALIFYING_PHRASES = ("would you", "do you", "can you tell", "what if", "how about")
PREAMBLES = (
    "i hope you",
    "hope you are doing",
    "i am reaching out",
    "i'm reaching out",
    "my name is",
)

HEDGED_CTAS = ("(yes/no)", "reply yes/no", "let me know if")

_CLOCK = re.compile(r"\b\d{1,2}(?::\d{2})?\s?(?:am|pm)\b", re.IGNORECASE)
_MASCULINE = re.compile(r"\b(?:sakta|raha) (?:hoon|hu)\b|\b(?:karunga|dunga|bhejunga|dekhunga)\b")
_URL = re.compile(r"https?://|www\.|\b[\w-]+\.(?:com|in|org|net|io|ly)\b", re.IGNORECASE)
_SNAKE_CASE = re.compile(r"\b[a-z]+_[a-z_]+\b")


def review(
    body: str,
    sheet: FactSheet,
    *,
    previous: Collection[str] = (),
    action_mode: bool = False,
    first_touch: bool = True,
) -> list[str]:
    text = body.strip()
    if not text:
        return ["body is empty"]
    lowered = text.casefold()
    problems: list[str] = []

    if _URL.search(text):
        problems.append("contains a URL; remove it")
    if len(text) > MAX_BODY_CHARS:
        problems.append(f"too long ({len(text)} chars); keep it under {MAX_BODY_CHARS}")
    if normalize(text) in {normalize(p) for p in previous}:
        problems.append("repeats a message already sent in this conversation")
    if snake := _SNAKE_CASE.findall(text):
        problems.append(f"exposes internal field names {snake}; use plain words")
    problems += [f"uses banned phrase '{t}'" for t in sheet.taboos if _mentions(lowered, t)]
    problems += [f"opens with a preamble ('{p}')" for p in PREAMBLES if p in lowered[:80]]
    problems += [f"hedged call to action ('{h}')" for h in HEDGED_CTAS if h in lowered]
    if first_touch and sheet.salutation.casefold() not in lowered[:60]:
        problems.append(f"must open by addressing the reader as '{sheet.salutation}'")

    allowed = sheet.allowed_numbers() | SAFE_NUMBERS
    unsupported = sorted({n for n in numbers_in(text) if n not in allowed})
    if unsupported:
        shown = ", ".join(f"{n:g}" for n in unsupported)
        problems.append(f"numbers not found in FACTS: {shown}; use only numbers from FACTS")

    grounding = _squash(sheet.grounding_text)
    invented_times = [t for t in _CLOCK.findall(text) if _squash(t) not in grounding]
    if invented_times:
        problems.append(f"times not found in FACTS: {invented_times}; do not invent timings")
    if not sheet.customer_facing and _MASCULINE.search(lowered):
        problems.append("Vera is female; use 'sakti hoon', 'dungi', 'karungi'")

    if sheet.language is not Language.ENGLISH and not has_hindi_flavour(text):
        problems.append("should be written in natural Hindi-English code-mix")
    if action_mode:
        problems += [
            f"asks a qualifying question ('{p}')" for p in QUALIFYING_PHRASES if p in lowered
        ]
    return problems


def _squash(text: str) -> str:
    return re.sub(r"\s+", "", text.casefold())


def _mentions(text: str, phrase: str) -> bool:
    core = re.sub(r"\s*\(.*\)", "", phrase).casefold().strip()
    return bool(core) and re.search(rf"\b{re.escape(core)}\b", text) is not None
