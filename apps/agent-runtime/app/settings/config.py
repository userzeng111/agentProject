from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


DEFAULT_TASKLOG_ROOT = str(Path(__file__).resolve().parents[4] / "tasklog")
RUNTIME_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    app_env: str = "development"
    app_name: str = "小说 Agent Runtime"
    runtime_origin: str = "http://127.0.0.1:3001"
    tasklog_root: str = DEFAULT_TASKLOG_ROOT
    llm_provider: str = "openai_compatible"
    openai_base_url: str = Field(
        default="https://api.lclaitech.com/v1",
        validation_alias=AliasChoices("LLM_BASE_URL"),
    )
    default_chat_model: str = Field(
        default="glm-5.1",
        validation_alias=AliasChoices("DEFAULT_CHAT_MODEL"),
    )
    openai_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("LLM_API_KEY"),
    )
    # 自动审核配置
    auto_review: bool = Field(
        default=False,
        validation_alias=AliasChoices("AUTO_REVIEW"),
    )
    auto_review_auditor_model: str = Field(
        default="MiniMax-M2.7-highspeed",
        validation_alias=AliasChoices("AUTO_REVIEW_AUDITOR_MODEL"),
    )
    auto_review_synthesis_model: str = Field(
        default="MiniMax-M2.7-highspeed",
        validation_alias=AliasChoices("AUTO_REVIEW_SYNTHESIS_MODEL"),
    )
    # 动态 Agent 审核模式（True=使用动态Agent编排审核，False=使用旧硬编码审核）
    dynamic_agent_review: bool = Field(
        default=False,
        validation_alias=AliasChoices("DYNAMIC_AGENT_REVIEW"),
    )

    model_config = SettingsConfigDict(
        env_file=RUNTIME_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
