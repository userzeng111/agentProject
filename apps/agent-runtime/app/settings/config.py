from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.llm.model_capabilities_config import DEFAULT_MODEL_CAPABILITIES_PATH


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
        validation_alias=AliasChoices("LLM_BASE_URL", "OPENAI_BASE_URL"),
    )
    anthropic_base_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("ANTHROPIC_BASE_URL"),
    )
    default_chat_model: str = Field(
        default="glm-5.1",
        validation_alias=AliasChoices("DEFAULT_CHAT_MODEL"),
    )
    openai_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("LLM_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_API_KEY"),
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
    auto_review_model_mode: str = Field(
        default="follow_creative",
        validation_alias=AliasChoices("AUTO_REVIEW_MODEL_MODE"),
    )
    auto_review_max_workers: int = Field(
        default=2,
        validation_alias=AliasChoices("AUTO_REVIEW_MAX_WORKERS"),
    )
    provider_prompt_cache: bool = Field(
        default=True,
        validation_alias=AliasChoices("PROVIDER_PROMPT_CACHE"),
    )
    provider_prompt_cache_min_chars: int = Field(
        default=1024,
        validation_alias=AliasChoices("PROVIDER_PROMPT_CACHE_MIN_CHARS"),
    )
    provider_prompt_cache_ttl: str = Field(
        default="",
        validation_alias=AliasChoices("PROVIDER_PROMPT_CACHE_TTL"),
    )
    # 章节批次并行草稿配置。硬上限在 StoryEngine 内再次限制，避免配置过大压满本机或上游网关。
    chapter_parallel_draft_enabled: bool = Field(
        default=True,
        validation_alias=AliasChoices("CHAPTER_PARALLEL_DRAFT_ENABLED"),
    )
    chapter_parallel_max_workers: int = Field(
        default=4,
        validation_alias=AliasChoices("CHAPTER_PARALLEL_MAX_WORKERS"),
    )
    chapter_parallel_min_batch_size: int = Field(
        default=3,
        validation_alias=AliasChoices("CHAPTER_PARALLEL_MIN_BATCH_SIZE"),
    )
    # 动态 Agent 审核模式（True=使用动态Agent编排审核，False=使用旧硬编码审核）
    dynamic_agent_review: bool = Field(
        default=False,
        validation_alias=AliasChoices("DYNAMIC_AGENT_REVIEW"),
    )
    # LLM 协议配置
    default_protocol: str = Field(
        default="openai",
        validation_alias=AliasChoices("DEFAULT_PROTOCOL"),
    )
    anthropic_version: str = Field(
        default="2023-06-01",
        validation_alias=AliasChoices("ANTHROPIC_VERSION"),
    )
    model_protocol_overrides: dict[str, str] = Field(
        default={},
        validation_alias=AliasChoices("MODEL_PROTOCOL_OVERRIDES"),
    )
    model_capabilities_path: str = Field(
        default=str(DEFAULT_MODEL_CAPABILITIES_PATH),
        validation_alias=AliasChoices("MODEL_CAPABILITIES_PATH"),
    )
    # 数据库配置
    database_path: str | None = Field(
        default=None,
        validation_alias=AliasChoices("DATABASE_PATH", "DB_PATH"),
    )
    sqlite_busy_timeout_ms: int = Field(
        default=5000,
        validation_alias=AliasChoices("SQLITE_BUSY_TIMEOUT_MS"),
    )
    sqlite_connect_timeout_seconds: float = Field(
        default=5.0,
        validation_alias=AliasChoices("SQLITE_CONNECT_TIMEOUT_SECONDS"),
    )
    sqlite_journal_mode: str = Field(
        default="WAL",
        validation_alias=AliasChoices("SQLITE_JOURNAL_MODE"),
    )
    sqlite_foreign_keys: bool = Field(
        default=True,
        validation_alias=AliasChoices("SQLITE_FOREIGN_KEYS"),
    )
    sqlite_synchronous: str = Field(
        default="NORMAL",
        validation_alias=AliasChoices("SQLITE_SYNCHRONOUS"),
    )
    db_sql_log_enabled: bool = Field(
        default=False,
        validation_alias=AliasChoices("DB_SQL_LOG_ENABLED"),
    )
    db_slow_query_ms: float = Field(
        default=100.0,
        validation_alias=AliasChoices("DB_SLOW_QUERY_MS"),
    )
    # 上传与模型诊断落盘边界
    upload_max_bytes: int = Field(
        default=2 * 1024 * 1024,
        validation_alias=AliasChoices("UPLOAD_MAX_BYTES"),
    )
    llm_diagnostic_raw_response_enabled: bool = Field(
        default=False,
        validation_alias=AliasChoices("LLM_DIAGNOSTIC_RAW_RESPONSE_ENABLED"),
    )
    llm_diagnostic_raw_response_max_chars: int = Field(
        default=2000,
        validation_alias=AliasChoices("LLM_DIAGNOSTIC_RAW_RESPONSE_MAX_CHARS"),
    )
    llm_diagnostic_include_request_messages: bool = Field(
        default=False,
        validation_alias=AliasChoices("LLM_DIAGNOSTIC_INCLUDE_REQUEST_MESSAGES"),
    )
    # LLM HTTP 超时配置（秒）
    llm_timeout_connect: float = Field(
        default=30.0,
        validation_alias=AliasChoices("LLM_TIMEOUT_CONNECT"),
    )
    llm_timeout_read: float = Field(
        default=240.0,
        validation_alias=AliasChoices("LLM_TIMEOUT_READ"),
    )
    llm_timeout_write: float = Field(
        default=60.0,
        validation_alias=AliasChoices("LLM_TIMEOUT_WRITE"),
    )
    llm_timeout_pool: float = Field(
        default=60.0,
        validation_alias=AliasChoices("LLM_TIMEOUT_POOL"),
    )

    @field_validator("model_protocol_overrides", mode="before")
    @classmethod
    def _parse_protocol_overrides(cls, v):
        if v is None or v == "":
            return {}
        if isinstance(v, dict):
            return v
        import json
        try:
            return json.loads(v)
        except Exception:
            return {}

    @property
    def effective_protocol_overrides(self) -> dict[str, str]:
        from app.settings.runtime_settings import get_model_protocol_overrides
        runtime_overrides = get_model_protocol_overrides()
        env_overrides = self.model_protocol_overrides or {}
        merged = dict(env_overrides)
        merged.update(runtime_overrides)
        return merged

    model_config = SettingsConfigDict(
        env_file=RUNTIME_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
