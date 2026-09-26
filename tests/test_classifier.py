import pytest

from vera.dialogue.classifier import ReplyIntent, classify, slot_choice
from vera.dialogue.language import Language, detect_language


@pytest.mark.parametrize(
    ("message", "intent"),
    [
        (
            "Thank you for contacting Dr. Meera's Dental Clinic! Our team will respond shortly.",
            ReplyIntent.AUTO_REPLY,
        ),
        (
            "Aapki jaankari ke liye bahut-bahut shukriya. Main yeh team tak pahuncha deti hoon.",
            ReplyIntent.AUTO_REPLY,
        ),
        ("Not interested. Stop messaging me.", ReplyIntent.OPT_OUT),
        ("Why are you bothering me. This is useless.", ReplyIntent.HOSTILE),
        ("Ok lets do it. Whats next?", ReplyIntent.COMMIT),
        ("Yes please send the abstract. Also draft the patient WhatsApp.", ReplyIntent.COMMIT),
        ("Mujhe magicpin judrna hai", ReplyIntent.COMMIT),
        ("Yes!", ReplyIntent.COMMIT),
        ("2", ReplyIntent.COMMIT),
        ("Busy right now, message me later", ReplyIntent.DEFER),
        ("Btw can you also help me with my GST filing this month?", ReplyIntent.OFF_TOPIC),
        ("How long does the verification take?", ReplyIntent.QUESTION),
    ],
)
def test_rules_classify_common_replies(message: str, intent: ReplyIntent) -> None:
    assert classify(message) is intent


def test_ambiguous_replies_are_left_for_the_llm() -> None:
    assert classify("hmm, interesting") is None


def test_verbatim_repeats_become_auto_replies() -> None:
    canned = "We are closed for lunch, please visit again"
    assert classify(canned, repeat_count=1) is None
    assert classify(canned, repeat_count=3) is ReplyIntent.AUTO_REPLY


def test_slot_choice() -> None:
    assert slot_choice(" 2 ") == 2
    assert slot_choice("option 1") == 1
    assert slot_choice("2 pm works") is None


@pytest.mark.parametrize(
    ("text", "language"),
    [
        ("Yes please share the details", Language.ENGLISH),
        ("Haan ji, aap bhej dijiye, main dekh leta hoon", Language.HINGLISH),
        ("हाँ भेज दीजिए", Language.HINDI),
    ],
)
def test_language_detection(text: str, language: Language) -> None:
    assert detect_language(text) is language
