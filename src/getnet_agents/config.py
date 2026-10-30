"""Application settings (12-factor: everything comes from environment variables / .env)."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "getnet-multi-agent-support"
    environment: str = "dev"
    log_level: str = "INFO"

    # LLM
    llm_provider: str = "auto"  # auto | anthropic | offline
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-opus-5-5"
    anthropic_router_model: str = "claude-haiku-5-5"
    llm_timeout_s: float = 30.0
    llm_max_retries: int = 2

    # Web search
    web_search_provider: str = "auto"  # auto | tavily | duckduckgo | disabled
    tavily_api_key: str | None = None

    # RAG
    knowledge_dir: str = "data/knowledge"
    rag_top_k: int = 4
    router_confidence_threshold: float = 0.55

    # Support / escalation
    crm_path: str = "data/crm/customers.json"
    handoff_webhook_url: str | None = None

    max_message_chars: int = 4000

    @property
    def effective_llm_provider(self) -> str:
        if self.llm_provider == "auto":
            return "anthropic" if self.anthropic_api_key else "offline"
        return self.llm_provider


@lru_cache
def get_settings() -> Settings:
    return Settings()
