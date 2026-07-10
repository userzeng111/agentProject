from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from time import monotonic
from typing import Any

from app.observability import get_logger
from app.llm.model_capabilities_config import (
    apply_context_window_config,
    extract_provider_model_limits,
    resolve_generation_max_tokens,
)
from app.settings.config import Settings


logger = get_logger(__name__)

_CAPABILITY_SCHEMA_VERSION = "v1"
_CACHE_TTL_SECONDS = 300.0

_PROFILE_REGISTRY: dict[str, dict[str, Any]] = {
    "gpt-5.4": {
        "display_name": "GPT-5.4",
        "provider": "openai_compatible",
        "capabilities": {
            "context_window": {
                "max_input_tokens": 256000,
                "max_output_tokens": 16000,
                "max_total_tokens": 272000,
                "recommended_prompt_budget": 180000,
                "compression_trigger_tokens": 140000,
            },
            "cache": {
                "runtime_response_cache": True,
                "runtime_context_cache": True,
                "provider_prompt_cache": "unknown",
                "cache_key_strategy": "stage+model+context_hash",
            },
            "compression": {
                "supported": True,
                "may_compress": True,
                "strategy": "reference_truncate+memory_trim",
            },
            "features": {
                "json_mode": True,
                "tool_calling": False,
                "streaming": True,
            },
        },
    },
    "gpt-5.3-codex": {
        "display_name": "GPT-5.3 Codex",
        "provider": "openai_compatible",
        "capabilities": {
            "context_window": {
                "max_input_tokens": 256000,
                "max_output_tokens": 16384,
                "max_total_tokens": 272384,
                "recommended_prompt_budget": 180000,
                "compression_trigger_tokens": 140000,
            },
            "cache": {
                "runtime_response_cache": True,
                "runtime_context_cache": True,
                "provider_prompt_cache": "unknown",
                "cache_key_strategy": "stage+model+context_hash",
            },
            "compression": {
                "supported": True,
                "may_compress": True,
                "strategy": "reference_truncate+memory_trim",
            },
            "features": {
                "json_mode": True,
                "tool_calling": True,
                "streaming": True,
            },
        },
    },
    "gpt-5.2-codex": {
        "display_name": "GPT-5.2 Codex",
        "provider": "openai_compatible",
        "capabilities": {
            "context_window": {
                "max_input_tokens": 256000,
                "max_output_tokens": 16384,
                "max_total_tokens": 272384,
                "recommended_prompt_budget": 180000,
                "compression_trigger_tokens": 140000,
            },
            "cache": {
                "runtime_response_cache": True,
                "runtime_context_cache": True,
                "provider_prompt_cache": "unknown",
                "cache_key_strategy": "stage+model+context_hash",
            },
            "compression": {
                "supported": True,
                "may_compress": True,
                "strategy": "reference_truncate+memory_trim",
            },
            "features": {
                "json_mode": True,
                "tool_calling": True,
                "streaming": True,
            },
        },
    },
    "gpt-5.1-codex-mini": {
        "display_name": "GPT-5.1 Codex Mini",
        "provider": "openai_compatible",
        "capabilities": {
            "context_window": {
                "max_input_tokens": 256000,
                "max_output_tokens": 8192,
                "max_total_tokens": 264192,
                "recommended_prompt_budget": 170000,
                "compression_trigger_tokens": 140000,
            },
            "cache": {
                "runtime_response_cache": True,
                "runtime_context_cache": True,
                "provider_prompt_cache": "unknown",
                "cache_key_strategy": "stage+model+context_hash",
            },
            "compression": {
                "supported": True,
                "may_compress": True,
                "strategy": "reference_truncate+memory_trim",
            },
            "features": {
                "json_mode": True,
                "tool_calling": True,
                "streaming": True,
            },
        },
    },
    "gpt-5.1-codex-max": {
        "display_name": "GPT-5.1 Codex Max",
        "provider": "openai_compatible",
        "capabilities": {
            "context_window": {
                "max_input_tokens": 256000,
                "max_output_tokens": 16384,
                "max_total_tokens": 272384,
                "recommended_prompt_budget": 180000,
                "compression_trigger_tokens": 140000,
            },
            "cache": {
                "runtime_response_cache": True,
                "runtime_context_cache": True,
                "provider_prompt_cache": "unknown",
                "cache_key_strategy": "stage+model+context_hash",
            },
            "compression": {
                "supported": True,
                "may_compress": True,
                "strategy": "reference_truncate+memory_trim",
            },
            "features": {
                "json_mode": True,
                "tool_calling": True,
                "streaming": True,
            },
        },
    },
    "gpt-4.1-mini": {
        "display_name": "GPT-4.1 Mini",
        "provider": "openai_compatible",
        "capabilities": {
            "context_window": {
                "max_input_tokens": None,
                "max_output_tokens": None,
                "max_total_tokens": None,
                "recommended_prompt_budget": None,
                "compression_trigger_tokens": None,
            },
            "cache": {
                "runtime_response_cache": True,
                "runtime_context_cache": True,
                "provider_prompt_cache": "unknown",
                "cache_key_strategy": "stage+model+context_hash",
            },
            "compression": {
                "supported": True,
                "may_compress": True,
                "strategy": "reference_truncate+memory_trim",
            },
            "features": {
                "json_mode": True,
                "tool_calling": False,
                "streaming": True,
            },
        },
    },
    "glm-5": {
        "display_name": "GLM-5",
        "provider": "zhipu",
        "capabilities": {
            "context_window": {
                "max_input_tokens": 200000,
                "max_output_tokens": 8192,
                "max_total_tokens": 208192,
                "recommended_prompt_budget": 150000,
                "compression_trigger_tokens": 120000,
            },
            "cache": {
                "runtime_response_cache": True,
                "runtime_context_cache": True,
                "provider_prompt_cache": "unknown",
                "cache_key_strategy": "stage+model+context_hash",
            },
            "compression": {
                "supported": True,
                "may_compress": True,
                "strategy": "reference_truncate+memory_trim",
            },
            "features": {
                "json_mode": True,
                "tool_calling": True,
                "streaming": True,
            },
        },
    },
    "glm-5.1": {
        "display_name": "GLM-5.1",
        "provider": "zhipu",
        "capabilities": {
            "context_window": {
                "max_input_tokens": 200000,
                "max_output_tokens": 8192,
                "max_total_tokens": 208192,
                "recommended_prompt_budget": 150000,
                "compression_trigger_tokens": 120000,
            },
            "cache": {
                "runtime_response_cache": True,
                "runtime_context_cache": True,
                "provider_prompt_cache": "unknown",
                "cache_key_strategy": "stage+model+context_hash",
            },
            "compression": {
                "supported": True,
                "may_compress": True,
                "strategy": "reference_truncate+memory_trim",
            },
            "features": {
                "json_mode": True,
                "tool_calling": True,
                "streaming": True,
            },
        },
    },
    "claude-haiku-4-5-20251001": {
        "display_name": "Claude Haiku 4.5",
        "provider": "anthropic",
        "capabilities": {
            "context_window": {
                "max_input_tokens": 200000,
                "max_output_tokens": 8192,
                "max_total_tokens": 208192,
                "recommended_prompt_budget": 140000,
                "compression_trigger_tokens": 120000,
            },
            "cache": {
                "runtime_response_cache": True,
                "runtime_context_cache": True,
                "provider_prompt_cache": "unknown",
                "cache_key_strategy": "stage+model+context_hash",
            },
            "compression": {
                "supported": True,
                "may_compress": True,
                "strategy": "reference_truncate+memory_trim",
            },
            "features": {
                "json_mode": True,
                "tool_calling": True,
                "streaming": True,
            },
        },
    },
    "claude-sonnet-4-6": {
        "display_name": "Claude Sonnet 4.6",
        "provider": "anthropic",
        "capabilities": {
            "context_window": {
                "max_input_tokens": 200000,
                "max_output_tokens": 32000,
                "max_total_tokens": 232000,
                "recommended_prompt_budget": 150000,
                "compression_trigger_tokens": 120000,
            },
            "cache": {
                "runtime_response_cache": True,
                "runtime_context_cache": True,
                "provider_prompt_cache": "unknown",
                "cache_key_strategy": "stage+model+context_hash",
            },
            "compression": {
                "supported": True,
                "may_compress": True,
                "strategy": "reference_truncate+memory_trim",
            },
            "features": {
                "json_mode": True,
                "tool_calling": True,
                "streaming": True,
            },
        },
    },
    "claude-opus-4-6": {
        "display_name": "Claude Opus 4.6",
        "provider": "anthropic",
        "capabilities": {
            "context_window": {
                "max_input_tokens": 200000,
                "max_output_tokens": 32000,
                "max_total_tokens": 232000,
                "recommended_prompt_budget": 150000,
                "compression_trigger_tokens": 120000,
            },
            "cache": {
                "runtime_response_cache": True,
                "runtime_context_cache": True,
                "provider_prompt_cache": "unknown",
                "cache_key_strategy": "stage+model+context_hash",
            },
            "compression": {
                "supported": True,
                "may_compress": True,
                "strategy": "reference_truncate+memory_trim",
            },
            "features": {
                "json_mode": True,
                "tool_calling": True,
                "streaming": True,
            },
        },
    },
    "MiniMax-M2.7-highspeed": {
        "display_name": "MiniMax M2.7 Highspeed",
        "provider": "minimax",
        "capabilities": {
            "context_window": {
                "max_input_tokens": 204800,
                "max_output_tokens": 8192,
                "max_total_tokens": 212992,
                "recommended_prompt_budget": 150000,
                "compression_trigger_tokens": 120000,
            },
            "cache": {
                "runtime_response_cache": True,
                "runtime_context_cache": True,
                "provider_prompt_cache": "unknown",
                "cache_key_strategy": "stage+model+context_hash",
            },
            "compression": {
                "supported": True,
                "may_compress": True,
                "strategy": "reference_truncate+memory_trim",
            },
            "features": {
                "json_mode": True,
                "tool_calling": True,
                "streaming": True,
            },
        },
    },
    "mimo-v2.5-pro": {
        "display_name": "Mimo v2.5 Pro",
        "provider": "mimo",
        "capabilities": {
            "context_window": {
                "max_input_tokens": 128000,
                "max_output_tokens": 8192,
                "max_total_tokens": 136192,
                "recommended_prompt_budget": 90000,
                "compression_trigger_tokens": 72000,
            },
            "cache": {
                "runtime_response_cache": True,
                "runtime_context_cache": True,
                "provider_prompt_cache": "unknown",
                "cache_key_strategy": "stage+model+context_hash",
            },
            "compression": {
                "supported": True,
                "may_compress": True,
                "strategy": "reference_truncate+memory_trim",
            },
            "features": {
                "json_mode": True,
                "tool_calling": False,
                "streaming": True,
            },
        },
        "protocol": "openai",
    },
    "K2.6": {
        "display_name": "Kimi K2.6",
        "provider": "moonshot",
        "capabilities": {
            "context_window": {
                "max_input_tokens": 256000,
                "max_output_tokens": 32768,
                "max_total_tokens": 288768,
                "recommended_prompt_budget": 180000,
                "compression_trigger_tokens": 140000,
            },
            "cache": {
                "runtime_response_cache": True,
                "runtime_context_cache": True,
                "provider_prompt_cache": "anthropic_cache_control",
                "cache_key_strategy": "stage+model+context_hash",
            },
            "compression": {
                "supported": True,
                "may_compress": True,
                "strategy": "reference_truncate+memory_trim",
            },
            "features": {
                "json_mode": True,
                "tool_calling": True,
                "streaming": True,
            },
        },
        "protocol": "anthropic",
    },
}


class ModelCatalogService:
    def __init__(
        self,
        settings: Settings,
        gateway_client: Any | None = None,
        registry: dict[str, dict[str, Any]] | None = None,
        cache_ttl_seconds: float = _CACHE_TTL_SECONDS,
        compatibility_provider: Any | None = None,
    ) -> None:
        self.settings = settings
        self.gateway_client = gateway_client
        self.registry = registry or _PROFILE_REGISTRY
        self.cache_ttl_seconds = cache_ttl_seconds
        self.compatibility_provider = compatibility_provider
        self._cached_payload: dict[str, Any] | None = None
        self._cached_at: float = 0.0
    def list_models(self, force_refresh: bool = False) -> list[dict[str, Any]]:
        return self.list_models_payload(force_refresh=force_refresh)["data"]

    def invalidate_cache(self) -> None:
        self._cached_payload = None
        self._cached_at = 0.0

    def list_models_payload(self, force_refresh: bool = False) -> dict[str, Any]:
        cache_age_seconds = monotonic() - self._cached_at
        if (
            not force_refresh
            and self._cached_payload is not None
            and cache_age_seconds < self.cache_ttl_seconds
        ):
            payload = deepcopy(self._cached_payload)
            meta = payload.setdefault("meta", {})
            meta["cache_ttl_seconds"] = self.cache_ttl_seconds
            meta["cache_age_seconds"] = round(cache_age_seconds, 2)
            meta["cached"] = True
            return payload

        raw_models = self._load_gateway_models()
        aggregated = self._merge_models(raw_models)
        fetched_at = datetime.now(timezone.utc).isoformat()
        payload = {
            "data": aggregated,
            "meta": {
                "capability_schema_version": _CAPABILITY_SCHEMA_VERSION,
                "cache_ttl_seconds": self.cache_ttl_seconds,
                "cache_age_seconds": 0.0,
                "cached": False,
                "fetched_at": fetched_at,
            },
        }
        self._cached_payload = deepcopy(payload)
        self._cached_at = monotonic()
        return payload

    def get_model_profile(self, model_id: str | None, *, force_refresh: bool = False) -> dict[str, Any]:
        payload = self.list_models_payload(force_refresh=force_refresh)
        candidate = (model_id or "").strip()
        for item in payload["data"]:
            if item.get("id") == candidate:
                return deepcopy(item)
        return self._build_model_item({"id": candidate}, source="missing")

    def ensure_novel_generation_model_supported(self, model_id: str | None) -> dict[str, Any]:
        candidate = (model_id or "").strip()
        if not candidate:
            raise ValueError("请显式选择当前供应商返回的模型后再创建或执行任务。")
        profile = self.get_model_profile(model_id, force_refresh=True)
        source = str((profile.get("metadata") or {}).get("source") or "")
        if "gateway" not in source:
            raise ValueError(f"模型 {candidate} 不在当前供应商模型目录中，请刷新模型列表后重新选择。")
        compatibility = str((profile.get("metadata") or {}).get("compatibility") or "").strip()
        supported = bool(((profile.get("capabilities") or {}).get("features") or {}).get("novel_task_supported"))
        if compatibility == "verified" and supported:
            return profile
        raise ValueError(
            f"模型 {profile.get('id') or candidate} 未完成兼容性验证，暂不支持小说任务流。"
            "请在 AI 对话页完成当前在线模型的兼容性验证后重试。"
        )

    def _load_gateway_models(self) -> list[dict[str, Any]]:
        if self.gateway_client is None:
            return []
        try:
            payload = self.gateway_client.list_models()
        except Exception as exc:
            logger.warning("读取网关模型列表失败，不使用本地模型画像作为候选项: error=%s", exc)
            return []
        if not isinstance(payload, list):
            return []
        return [item for item in payload if isinstance(item, dict) and str(item.get("id") or "").strip()]

    def _merge_models(self, raw_models: list[dict[str, Any]]) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        seen: set[str] = set()

        # 1. 先添加网关返回的模型
        for raw in raw_models:
            model_id = str(raw.get("id") or "").strip()
            if not model_id or model_id in seen:
                continue
            seen.add(model_id)
            items.append(self._build_model_item(raw, source="gateway"))

        return items

    def _build_model_item(self, raw: dict[str, Any], source: str) -> dict[str, Any]:
        model_id = str(raw.get("id") or "").strip()
        profile = deepcopy(self.registry.get(model_id, {}))
        profile_capabilities = profile.get("capabilities")
        capabilities = deepcopy(profile_capabilities) if isinstance(profile_capabilities, dict) else self._unknown_capabilities(model_id)
        # 型号注册表只允许补充非限额元数据；上下文窗口必须来自当前供应商目录或通用默认配置。
        capabilities["context_window"] = {}
        provider_limits, provider_limit_sources = extract_provider_model_limits(raw)
        capabilities = apply_context_window_config(
            capabilities,
            model_id,
            settings=self.settings,
            provider_context_window=provider_limits,
        )
        provider = profile.get("provider") or self.settings.llm_provider
        display_name = profile.get("display_name") or model_id
        compatibility = "unverified"
        protocol = profile.get("protocol") or getattr(self.settings, "default_protocol", "openai") or "openai"
        if hasattr(self.settings, "effective_protocol_overrides"):
            protocol = self.settings.effective_protocol_overrides.get(model_id, protocol)
        capabilities.setdefault("features", {})
        if isinstance(capabilities["features"], dict):
            capabilities["features"]["novel_task_supported"] = False
        item = {
            "id": model_id,
            "object": raw.get("object", "model"),
            "owned_by": raw.get("owned_by", "unknown"),
            "display_name": display_name,
            "provider": provider,
            "capabilities": capabilities,
            "metadata": {
                "source": source,
                "compatibility": compatibility,
                "protocol": protocol,
                "profile_version": "2026-03-31",
                "last_refreshed_at": None,
                "context_limit_source": provider_limit_sources.get("max_total_tokens", ""),
                "input_limit_source": provider_limit_sources.get("max_input_tokens", ""),
                "output_limit_source": provider_limit_sources.get("max_output_tokens", ""),
                "limits_known": bool(provider_limits),
            },
        }
        return self._apply_compatibility_override(item, source)

    def _apply_compatibility_override(self, item: dict[str, Any], source: str) -> dict[str, Any]:
        if self.compatibility_provider is None:
            return item
        model_id = str(item.get("id") or "").strip()
        if not model_id:
            return item
        try:
            report = self.compatibility_provider.get_report(model_id)
        except Exception as exc:
            logger.warning("读取模型兼容性覆盖失败: model=%s error=%s", model_id, exc)
            return item
        if not isinstance(report, dict):
            return item
        status = str(report.get("status") or "").strip()
        if status not in {"verified", "failed"}:
            return item

        metadata = item.setdefault("metadata", {})
        features = item.setdefault("capabilities", {}).setdefault("features", {})
        metadata["validation"] = self._validation_summary(report)
        source_value = str(metadata.get("source") or source or "")
        if status == "verified" and "gateway" in source_value:
            metadata["compatibility"] = "verified"
            features["novel_task_supported"] = True
        elif status == "failed":
            metadata["compatibility"] = "unverified"
            features["novel_task_supported"] = False
        return item

    @staticmethod
    def _validation_summary(report: dict[str, Any]) -> dict[str, Any]:
        return {
            "status": str(report.get("status") or "unverified"),
            "validated_at": str(report.get("validated_at") or ""),
            "validator_version": str(report.get("validator_version") or ""),
            "summary": str(report.get("summary") or ""),
            "last_error": str(report.get("failure_reason") or ""),
            "checks": report.get("checks") if isinstance(report.get("checks"), list) else [],
            "evidence": report.get("evidence") if isinstance(report.get("evidence"), dict) else {},
        }

    def _unknown_capabilities(self, model_id: str | None = None) -> dict[str, Any]:
        return {
            "context_window": apply_context_window_config(
                {
                    "context_window": {},
                },
                model_id,
                settings=self.settings,
            )["context_window"],
            "cache": {
                "runtime_response_cache": True,
                "runtime_context_cache": True,
                "provider_prompt_cache": "unknown",
                "cache_key_strategy": "stage+model+context_hash",
            },
            "compression": {
                "supported": True,
                "may_compress": True,
                "strategy": "reference_truncate+memory_trim",
            },
            "features": {
                "json_mode": False,
                "tool_calling": False,
                "streaming": True,
                "novel_task_supported": False,
            },
        }


def get_model_max_output_tokens(model_id: str | None, settings: Settings | None = None) -> int | None:
    """返回供应商未提供限额时使用的通用输出 token 默认值。"""
    return resolve_generation_max_tokens(None, settings=settings)
