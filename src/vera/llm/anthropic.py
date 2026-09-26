import anthropic

from vera.llm.base import LLMError, SchemaT


class AnthropicClient:
    def __init__(self, model: str, timeout_seconds: float, api_key: str | None = None) -> None:
        self._model = model
        self._client = anthropic.AsyncAnthropic(
            api_key=api_key, timeout=timeout_seconds, max_retries=1
        )

    @property
    def name(self) -> str:
        return self._model

    async def complete(self, system: str, prompt: str, schema: type[SchemaT]) -> SchemaT:
        try:
            response = await self._client.messages.parse(
                model=self._model,
                max_tokens=1024,
                system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": prompt}],
                thinking={"type": "disabled"},
                output_format=schema,
            )
        except anthropic.APIError as error:
            raise LLMError(str(error)) from error
        if response.stop_reason == "refusal" or response.parsed_output is None:
            raise LLMError(f"no usable output (stop_reason={response.stop_reason})")
        parsed: SchemaT = response.parsed_output
        return parsed
