from functools import lru_cache
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

LLMProviderName = Literal["groq", "anthropic", "openai_compat", "none"]

DEFAULT_MODELS = {"groq": "openai/gpt-oss-120b", "anthropic": "claude-sonnet-5"}
GROQ_BASE_URL = "https://api.groq.com/openai/v1"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="VERA_", env_file=".env", extra="ignore")

    llm_provider: LLMProviderName = "groq"
    llm_model: str | None = None
    llm_api_key: SecretStr | None = None
    llm_base_url: str | None = None
    llm_timeout_seconds: float = 7.0

    tick_budget_seconds: float = 8.0
    compose_concurrency: int = 8
    max_actions_per_tick: int = 20
    # The judge lists only triggers it considers active, and the local simulator stamps ticks
    # with wall-clock time, so enforcing expires_at would silently drop valid work.
    respect_trigger_expiry: bool = False

    team_name: str = "Team Vera"
    team_members: list[str] = []
    contact_email: str = ""
    version: str = "1.0.0"
    submitted_at: str = "2026-09-26T00:00:00Z"

    @property
    def model_name(self) -> str:
        return self.llm_model or DEFAULT_MODELS.get(self.llm_provider, "")


@lru_cache
def get_settings() -> Settings:
    return Settings()
