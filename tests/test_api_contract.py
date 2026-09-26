from fastapi.testclient import TestClient
from support import Seeds, push, reply, tick

REQUIRED_ACTION_FIELDS = {
    "conversation_id",
    "merchant_id",
    "customer_id",
    "send_as",
    "trigger_id",
    "template_name",
    "template_params",
    "body",
    "cta",
    "suppression_key",
    "rationale",
}


def test_healthz_starts_empty(client: TestClient) -> None:
    body = client.get("/v1/healthz").json()
    assert body["status"] == "ok"
    assert body["contexts_loaded"] == {"category": 0, "merchant": 0, "customer": 0, "trigger": 0}


def test_metadata_describes_the_bot(client: TestClient) -> None:
    body = client.get("/v1/metadata").json()
    assert body["team_name"] == "Test Team"
    assert body["model"] == "templates-only"
    assert {"approach", "version", "submitted_at", "contact_email"} <= body.keys()


def test_context_push_is_versioned(client: TestClient, seeds: Seeds) -> None:
    merchant = seeds.merchants["m_001_drmeera_dentist_delhi"]

    first = push(client, "merchant", "m_001_drmeera_dentist_delhi", merchant)
    assert first.status_code == 200
    assert first.json()["ack_id"] == "ack_m_001_drmeera_dentist_delhi_v1"

    replay = push(client, "merchant", "m_001_drmeera_dentist_delhi", merchant)
    assert replay.status_code == 409
    assert replay.json() == {"accepted": False, "reason": "stale_version", "current_version": 1}

    bumped = push(client, "merchant", "m_001_drmeera_dentist_delhi", merchant, version=2)
    assert bumped.status_code == 200


def test_unknown_scope_is_rejected(client: TestClient) -> None:
    response = push(client, "planet", "earth", {})
    assert response.status_code == 400
    assert response.json()["reason"] == "invalid_scope"


def test_healthz_counts_everything_pushed(loaded_client: TestClient, seeds: Seeds) -> None:
    counts = loaded_client.get("/v1/healthz").json()["contexts_loaded"]
    assert counts == {
        "category": len(seeds.categories),
        "merchant": len(seeds.merchants),
        "customer": len(seeds.customers),
        "trigger": len(seeds.triggers),
    }


def test_tick_returns_complete_actions(loaded_client: TestClient) -> None:
    actions = tick(loaded_client, "trg_001_research_digest_dentists")
    assert len(actions) == 1
    action = actions[0]
    assert action.keys() >= REQUIRED_ACTION_FIELDS
    assert action["send_as"] == "vera"
    assert action["suppression_key"] == "research:dentists:2026-W17"
    assert "Dr. Meera" in action["body"]
    assert "http" not in action["body"]


def test_tick_does_not_resend_a_suppressed_trigger(loaded_client: TestClient) -> None:
    assert tick(loaded_client, "trg_001_research_digest_dentists")
    assert tick(loaded_client, "trg_001_research_digest_dentists") == []


def test_tick_with_nothing_to_do_is_empty(loaded_client: TestClient) -> None:
    assert tick(loaded_client) == []
    assert tick(loaded_client, "trg_does_not_exist") == []


def test_tick_sends_one_action_per_merchant(loaded_client: TestClient) -> None:
    actions = tick(
        loaded_client,
        "trg_001_research_digest_dentists",
        "trg_002_compliance_dci_radiograph",
        "trg_004_perf_dip_bharat",
    )
    merchants = [a["merchant_id"] for a in actions]
    assert len(merchants) == len(set(merchants)) == 2
    meera = next(a for a in actions if a["merchant_id"] == "m_001_drmeera_dentist_delhi")
    assert meera["trigger_id"] == "trg_002_compliance_dci_radiograph"


def test_customer_trigger_is_sent_on_behalf_of_merchant(loaded_client: TestClient) -> None:
    action = tick(loaded_client, "trg_003_recall_due_priya")[0]
    assert action["send_as"] == "merchant_on_behalf"
    assert action["customer_id"] == "c_001_priya_for_m001"
    assert action["cta"] == "multi_choice_slot"
    assert "Wed 5 Nov, 6pm" in action["body"]


def test_reply_to_hard_no_ends_conversation(loaded_client: TestClient) -> None:
    result = reply(loaded_client, "conv_x", "Not interested. Stop messaging me.")
    assert result["action"] == "end"
    assert reply(loaded_client, "conv_x", "hello?")["action"] == "end"


def test_reply_to_curveball_stays_on_mission(loaded_client: TestClient) -> None:
    result = reply(
        loaded_client, "conv_y", "Btw can you also help me with my GST filing this month?"
    )
    assert result["action"] == "send"
    assert "outside what I can help with" in result["body"]


def test_malformed_reply_is_rejected(client: TestClient) -> None:
    assert client.post("/v1/reply", json={"message": "hi"}).status_code == 400


def test_teardown_wipes_state(loaded_client: TestClient) -> None:
    assert loaded_client.post("/v1/teardown").json() == {"ok": True}
    counts = loaded_client.get("/v1/healthz").json()["contexts_loaded"]
    assert set(counts.values()) == {0}
