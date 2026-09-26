from typing import Protocol, TypeVar

from pydantic import BaseModel

SchemaT = TypeVar("SchemaT", bound=BaseModel)


class LLMError(Exception):
    pass


class LLMClient(Protocol):
    @property
    def name(self) -> str: ...

    async def complete(self, system: str, prompt: str, schema: type[SchemaT]) -> SchemaT: ...
