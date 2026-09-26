from vera.compose.facts import FactSheet
from vera.compose.strategies import CtaType, TriggerRead
from vera.dialogue.language import Language


def opener(sheet: FactSheet) -> str:
    if not sheet.customer_facing:
        return f"{sheet.salutation},"
    if sheet.salutation == "Namaste":
        return f"Namaste, {sheet.speaker} here."
    greeting = "Namaste" if sheet.language is Language.HINDI else "Hi"
    return f"{greeting} {sheet.salutation}, {sheet.speaker} here."


def closing_line(sheet: FactSheet, read: TriggerRead, cta: CtaType) -> str:
    code_mixed = sheet.language is not Language.ENGLISH
    if read.closing:
        if sheet.customer_facing:
            return read.closing + _SIGNOFFS.get(sheet.language, "")
        return read.closing + (" Aap bataiye." if code_mixed else "")
    ask = f"Want me to {read.deliverable}?"
    if cta is CtaType.OPEN_ENDED:
        return ask + (" Aap bataiye." if code_mixed else "")
    if code_mixed:
        return f"{ask} Bas YES reply karein, baaki main sambhal loongi."
    return f"{ask} Reply YES and I'll get it started."


_SIGNOFFS = {Language.HINGLISH: " Aapka intezaar rahega!", Language.HINDI: " Dhanyavaad!"}


def initial_message(sheet: FactSheet, read: TriggerRead, cta: CtaType) -> str:
    hook = read.hook[:1].upper() + read.hook[1:] if sheet.customer_facing else read.hook
    parts = [opener(sheet), hook, read.proof, closing_line(sheet, read, cta)]
    return " ".join(part.strip() for part in parts if part.strip())


def template_params(sheet: FactSheet, read: TriggerRead, cta: CtaType) -> tuple[str, ...]:
    return (sheet.salutation, read.hook, closing_line(sheet, read, cta))


def owner_nudge(read: TriggerRead) -> str:
    return (
        "Looks like an auto-reply 🙂 Whenever the owner sees this, just reply YES and "
        f"I'll {read.deliverable}."
    )


def action_reply(read: TriggerRead, customer_facing: bool) -> str:
    if customer_facing:
        return "Done ✅ We've noted it and will send a confirmation shortly. See you soon!"
    return (
        f"On it. I'm starting now: I'll {read.deliverable} and share the draft here within "
        "10 minutes. Next step: reply CONFIRM once you've checked it and I'll publish."
    )


def slot_booked(option: str) -> str:
    return (
        f"Done ✅ {option} is booked for you. We'll send a reminder the day before. See you then!"
    )


def completion_reply() -> str:
    return "Confirmed, it's going live now. I'll share how it performs in a few days."


def off_topic_reply(read: TriggerRead) -> str:
    return (
        "That one is outside what I can help with, so it's best left to the right expert. "
        f"Coming back to our thread: want me to {read.deliverable}?"
    )


def engaged_reply(read: TriggerRead, attempt: int) -> str:
    variants = (
        f"Got it. The easiest next step is for me to {read.deliverable} right away. "
        "Reply YES to go ahead.",
        f"Thanks for the reply. I can {read.deliverable} today, no effort needed on your side. "
        "Just reply YES.",
        "Noted, thank you. I'll keep this ready for whenever you want it. Reply YES any time.",
    )
    return variants[min(attempt, len(variants) - 1)]


def goodbye_reply() -> str:
    return "Understood, I won't message again about this. If you ever need help, just say 'Hi Vera'. 🙏"
