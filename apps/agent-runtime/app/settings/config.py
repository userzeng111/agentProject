from functools import lru_cache

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "development"
    app_name: str = "小说 Agent Runtime"
    runtime_origin: str = "http://127.0.0.1:3000"
    llm_provider: str = "openai_compatible"
    openai_base_url: str = Field(
        default="https://api.lclaitech.com/v1",
        validation_alias=AliasChoices("LLM_BASE_URL", "OPENAI_BASE_URL"),
    )
    chat_model: str = Field(
        default="gpt-5.4",
        validation_alias=AliasChoices("LLM_MODEL", "CHAT_MODEL"),
    )
    openai_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("LLM_API_KEY", "OPENAI_API_KEY"),
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
