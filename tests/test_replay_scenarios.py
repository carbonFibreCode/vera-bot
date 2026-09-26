from fastapi.testclient import TestClient
from support import FakeLLM, Seeds, push, push_all, reply, template_settings, tick

from vera.compose.guardrails import QUALIFYING_PHRASES
from vera.main import create_app

CANNED = "Thank you for contacting us! Our team will respond shortly."
RESEARCH = "trg_001_research_digest_dentists"


def test_auto_reply_hell_nudges_once_then_waits_then_ends(loaded_client: TestClient) -> None:
    actions = [reply(loaded_client, f"conv_auto_{turn}", CANNED)["action"] for turn in range(1, 5)]
    assert actions[:3] == ["send", "wait", "end"]


def test_intent_transition_switches_to_action(loaded_client: TestClient) -> None:
    conversation = tick(loaded_client, "trg_022_cde_webinar_dentists")[0]["conversation_id"]
    reply(loaded_client, conversation, "What topics does it cover?")
    result = reply(loaded_client, conversation, "Ok lets do it. Whats next?", turn_number=3)
    body = result["body"].casefold()
    assert result["action"] == "send"
    assert result["cta"] == "binary_confirm_cancel"
    assert not any(phrase in body for phrase in QUALIFYING_PHRASES)
    assert "next" in body and "confirm" in body


def test_hostile_merchant_is_left_alone(loaded_client: TestClient) -> None:
    result = reply(loaded_client, "conv_hostile", "Stop messaging me. This is useless spam.")
    assert result["action"] == "end"
    assert tick(loaded_client, "trg_001_research_digest_dentists") == []


def test_customer_can_book_a_slot_by_number(loaded_client: TestClient) -> None:
    conversation = tick(loaded_client, "trg_003_recall_due_priya")[0]["conversation_id"]
    result = reply(
        loaded_client, conversation, "2", customer_id="c_001_priya_for_m001", from_role="customer"
    )
    assert result["action"] == "send"
    assert "Thu 6 Nov, 5pm" in result["body"]


def test_bot_never_repeats_itself(loaded_client: TestClient) -> None:
    conversation = tick(loaded_client, "trg_004_perf_dip_bharat")[0]["conversation_id"]
    bodies = [
        reply(loaded_client, conversation, "hmm ok", merchant_id="m_002_bharat_dentist_mumbai").get(
            "body"
        )
        for _ in range(4)
    ]
    sent = [b for b in bodies if b]
    assert len(sent) == len(set(sent))


def test_llm_draft_is_used_when_grounded(seeds: Seeds) -> None:
    draft = {
        "body": "Dr. Meera, JIDA ka naya 2,100-patient trial aapke 124 high-risk patients ke liye "
        "relevant hai. Summary bhej doon?",
        "rationale": "Research digest anchored to her high-risk cohort.",
        "template_params": ["Dr. Meera", "JIDA trial", "Summary bhej doon?"],
    }
    with TestClient(create_app(template_settings(), llm=FakeLLM(draft))) as client:
        push_all(client, seeds, with_triggers=False)
        push(client, "trigger", RESEARCH, seeds.triggers[RESEARCH])
        action = tick(client, RESEARCH)[0]
    assert action["body"] == draft["body"]
    assert action["rationale"] == draft["rationale"]


def test_ungrounded_llm_draft_falls_back_to_template(seeds: Seeds) -> None:
    invented = {
        "body": "Dr. Meera, 11 clinics nearby grew 63% with this. Want in?",
        "rationale": "x",
        "template_params": [],
    }
    llm = FakeLLM(invented, invented)
    with TestClient(create_app(template_settings(), llm=llm)) as client:
        push_all(client, seeds, with_triggers=False)
        push(client, "trigger", RESEARCH, seeds.triggers[RESEARCH])
        action = tick(client, RESEARCH)[0]
    assert "63%" not in action["body"]
    assert "JIDA" in action["body"]
    assert "numbers not found in FACTS" in llm.prompts[-1]


def test_drafts_use_the_judges_clock_not_the_servers(seeds: Seeds) -> None:
    regulation = "trg_002_compliance_dci_radiograph"
    draft = {"body": "unused", "rationale": "unused", "template_params": []}
    llm = FakeLLM(draft)
    with TestClient(create_app(template_settings(), llm=llm)) as client:
        push_all(client, seeds, with_triggers=False)
        push(client, "trigger", regulation, seeds.triggers[regulation])
        assert llm.prompts == []
        tick(client, regulation, now="2026-04-26T10:30:00Z")
    assert "days until deadline: 233" in llm.prompts[0]
