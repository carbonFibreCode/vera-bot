import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from vera.config import Settings
from vera.llm.base import LLMError, SchemaT


def template_settings() -> Settings:
    return Settings(llm_provider="none", team_name="Test Team")


class Seeds:
    def __init__(self, root: Path) -> None:
        self.categories = {
            data["slug"]: data
            for data in (json.loads(f.read_text()) for f in (root / "categories").glob("*.json"))
        }
        self.merchants = _keyed(root / "merchants_seed.json", "merchants", "merchant_id")
        self.customers = _keyed(root / "customers_seed.json", "customers", "customer_id")
        self.triggers = _keyed(root / "triggers_seed.json", "triggers", "id")


def _keyed(path: Path, container: str, key: str) -> dict[str, dict[str, Any]]:
    return {item[key]: item for item in json.loads(path.read_text())[container]}


class FakeLLM:
    def __init__(self, *responses: dict[str, Any] | Exception) -> None:
        self.responses = list(responses)
        self.prompts: list[str] = []

    @property
    def name(self) -> str:
        return "fake-llm"

    async def complete(self, system: str, prompt: str, schema: type[SchemaT]) -> SchemaT:
        self.prompts.append(prompt)
        if not self.responses:
            raise LLMError("no scripted response left")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return schema.model_validate(response)


def push(
    client: TestClient, scope: str, context_id: str, payload: dict[str, Any], version: int = 1
) -> Any:
    return client.post(
        "/v1/context",
        json={"scope": scope, "context_id": context_id, "version": version, "payload": payload},
    )


def push_all(client: TestClient, seeds: Seeds, with_triggers: bool = True) -> None:
    groups: list[tuple[str, dict[str, dict[str, Any]]]] = [
        ("category", seeds.categories),
        ("merchant", seeds.merchants),
        ("customer", seeds.customers),
    ]
    if with_triggers:
        groups.append(("trigger", seeds.triggers))
    for scope, items in groups:
        for context_id, payload in items.items():
            assert push(client, scope, context_id, payload).status_code == 200


def tick(
    client: TestClient, *trigger_ids: str, now: str = "2026-04-26T10:30:00Z"
) -> list[dict[str, Any]]:
    response = client.post("/v1/tick", json={"now": now, "available_triggers": list(trigger_ids)})
    assert response.status_code == 200
    actions: list[dict[str, Any]] = response.json()["actions"]
    return actions


def reply(
    client: TestClient,
    conversation_id: str,
    message: str,
    merchant_id: str = "m_001_drmeera_dentist_delhi",
    **extra: Any,
) -> dict[str, Any]:
    body = {
        "conversation_id": conversation_id,
        "merchant_id": merchant_id,
        "from_role": "merchant",
        "message": message,
        "received_at": "2026-04-26T10:42:00Z",
        "turn_number": 2,
        **extra,
    }
    response = client.post("/v1/reply", json=body)
    assert response.status_code == 200
    result: dict[str, Any] = response.json()
    return result
