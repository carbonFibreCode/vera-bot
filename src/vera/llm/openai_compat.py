import json
import time
from typing import Any

import httpx
from pydantic import ValidationError

from vera.llm.base import LLMError, SchemaT

DEFAULT_COOLDOWN_SECONDS = 20.0


class OpenAICompatibleClient:
    def __init__(
        self,
        model: str,
        base_url: str,
        api_key: str,
        timeout_seconds: float,
        *,
        strict_schema: bool = False,
        extra: dict[str, Any] | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._model = model
        self._strict_schema = strict_schema
        self._extra = extra or {}
        self._cooldown_until = 0.0
        self._http = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout_seconds,
            transport=transport,
        )

    @property
    def name(self) -> str:
        return self._model

    async def complete(self, system: str, prompt: str, schema: type[SchemaT]) -> SchemaT:
        if time.monotonic() < self._cooldown_until:
            raise LLMError("rate limited; cooling down")
        payload = {
            "model": self._model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": self._system(system, schema)},
                {"role": "user", "content": prompt},
            ],
            "response_format": self._response_format(schema),
            **self._extra,
        }
        try:
            response = await self._http.post("/chat/completions", json=payload)
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            return schema.model_validate_json(content)
        except httpx.HTTPStatusError as error:
            if error.response.status_code == 429:
                self._cool_down(error.response.headers.get("retry-after"))
            raise LLMError(f"{error.response.status_code}: {error.response.text[:200]}") from error
        except (httpx.HTTPError, KeyError, ValidationError) as error:
            raise LLMError(str(error)) from error

    def _cool_down(self, retry_after: str | None) -> None:
        try:
            seconds = float(retry_after) if retry_after else DEFAULT_COOLDOWN_SECONDS
        except ValueError:
            seconds = DEFAULT_COOLDOWN_SECONDS
        self._cooldown_until = time.monotonic() + seconds

    def _system(self, system: str, schema: type[SchemaT]) -> str:
        if self._strict_schema:
            return system
        return f"{system}\n\nReply with JSON matching: {json.dumps(schema.model_json_schema())}"

    def _response_format(self, schema: type[SchemaT]) -> dict[str, Any]:
        if not self._strict_schema:
            return {"type": "json_object"}
        return {
            "type": "json_schema",
            "json_schema": {
                "name": schema.__name__.lower(),
                "strict": True,
                "schema": schema.model_json_schema(),
            },
        }
