from vera.compose.facts import FactSheet
from vera.compose.guardrails import review
from vera.dialogue.language import Language


def sheet(language: Language = Language.ENGLISH) -> FactSheet:
    return FactSheet(
        kind="research_digest",
        salutation="Dr. Meera",
        speaker="Vera",
        language=language,
        voice="peer clinical",
        taboos=("guaranteed", "100% safe", "FDA-approved (use only when actually applicable)"),
        vocabulary=(),
        facts={"sample size": "2,100 patients", "effect": "38% lower recurrence"},
    )


GOOD = "Dr. Meera, a 2,100-patient JIDA trial found 38% lower recurrence. Want the summary?"


def test_grounded_message_passes() -> None:
    assert review(GOOD, sheet()) == []


def test_invented_numbers_are_caught() -> None:
    problems = review("Dr. Meera, 3 out of 7 clinics saw 45% growth. Interested?", sheet())
    assert any("45" in p and "7" in p for p in problems)


def test_urls_taboos_and_jargon_are_caught() -> None:
    problems = review("Guaranteed results, see www.example.com for ctr_below_peer data.", sheet())
    assert any("URL" in p for p in problems)
    assert any("guaranteed" in p for p in problems)
    assert any("internal field" in p for p in problems)


def test_taboo_notes_in_parentheses_are_ignored_when_matching() -> None:
    assert any("FDA-approved" in p for p in review("It is FDA-approved.", sheet()))


def test_repeats_are_caught() -> None:
    assert any("repeats" in p for p in review(GOOD, sheet(), previous=[GOOD.upper()]))


def test_code_mix_is_required_for_hindi_speakers() -> None:
    assert any("code-mix" in p for p in review(GOOD, sheet(Language.HINGLISH)))
    mixed = "Dr. Meera, JIDA ka 2,100-patient trial aapke liye kaafi relevant hai. Summary bhejoon?"
    assert review(mixed, sheet(Language.HINGLISH)) == []


def test_action_mode_forbids_qualifying_questions() -> None:
    body = "Great. Before I start, would you say most patients are diabetic?"
    assert any("qualifying" in p for p in review(body, sheet(), action_mode=True))


def test_invented_clock_times_are_caught() -> None:
    body = "Dr. Meera, a 2,100-patient trial is out. I can call you tomorrow at 10 am. Okay?"
    assert any("times not found" in p for p in review(body, sheet()))


def test_first_message_must_greet_by_name() -> None:
    body = "A 2,100-patient JIDA trial found 38% lower recurrence. Want the summary?"
    assert any("addressing the reader" in p for p in review(body, sheet()))
    assert review(body, sheet(), first_touch=False) == []


def test_vera_speaks_in_the_feminine() -> None:
    body = "Dr. Meera, JIDA ka 2,100-patient trial aapke liye relevant hai. Main summary bhej sakta hoon?"
    assert any("female" in p for p in review(body, sheet(Language.HINGLISH)))


def test_hedged_ctas_are_caught() -> None:
    body = "Dr. Meera, a 2,100-patient trial found 38% lower recurrence. Summary chahiye? (Yes/No)"
    assert any("hedged" in p for p in review(body, sheet()))
