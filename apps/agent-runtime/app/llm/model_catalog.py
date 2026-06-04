from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic
from typing import Any

from app.llm.model_capabilities_config import (
    apply_context_window_config,
    resolve_generation_max_tokens,
)
from app.settings.config import Settings


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
    ) -> None:
        self.settings = settings
        self.gateway_client = gateway_client
        self.registry = registry or _PROFILE_REGISTRY
        self.cache_ttl_seconds = cache_ttl_seconds
        self._cached_payload: dict[str, Any] | None = None
        self._cached_at: float = 0.0
        # 运行时默认模型覆盖，持久化到 tasklog/settings.json
        self._runtime_default_model: str | None = None
        self._settings_file = Path(settings.tasklog_root) / "settings.json"
        self._load_runtime_settings()

    def _settings_path(self) -> Path:
        return self._settings_file

    def _load_runtime_settings(self) -> None:
        """从 tasklog/settings.json 加载运行时设置（如默认模型覆盖）。"""
        path = self._settings_path()
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                self._runtime_default_model = data.get("default_model") or None
            except Exception:
                pass

    def _save_runtime_settings(self) -> None:
        """保存运行时设置到 tasklog/settings.json。"""
        path = self._settings_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        data: dict[str, Any] = {}
        if self._runtime_default_model:
            data["default_model"] = self._runtime_default_model
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def _effective_default_model(self) -> str:
        """返回当前生效的默认模型（优先运行时覆盖，其次配置文件）。"""
        return self._runtime_default_model or self.settings.default_chat_model

    def update_default_model(self, model_id: str) -> dict[str, Any]:
        """更新运行时默认模型，持久化到配置文件，返回更新后的摘要。"""
        valid_ids = {item["id"] for item in self.list_models()}
        if model_id not in valid_ids:
            raise ValueError(f"模型 ID 不在可用模型列表中：{model_id}")
        self.ensure_runtime_default_model_supported(model_id)
        self.ensure_novel_generation_model_supported(model_id)
        self._runtime_default_model = model_id
        self._save_runtime_settings()
        # 清除模型列表缓存，使下次 list_models_payload 重新聚合
        self._cached_payload = None
        return {
            "default_model": self._effective_default_model(),
            "supported_models": [item["id"] for item in self.list_models()],
        }

    def ensure_runtime_default_model_supported(self, model_id: str | None) -> dict[str, Any]:
        profile = self.get_model_profile(model_id)
        metadata = profile.get("metadata") if isinstance(profile.get("metadata"), dict) else {}
        source = str(metadata.get("source") or "").strip()
        if source in {"registry", "default+registry"}:
            raise ValueError(
                f"模型 {profile.get('id') or model_id or ''} 当前仅存在本地画像，未接入网关，不能设为默认聊天模型。"
            )
        return profile

    def list_models(self, force_refresh: bool = False) -> list[dict[str, Any]]:
        return self.list_models_payload(force_refresh=force_refresh)["data"]

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
        if self._sync_runtime_default_from_verified_env_default(aggregated):
            aggregated = self._order_default_model_first(aggregated)
        fetched_at = datetime.now(timezone.utc).isoformat()
        payload = {
            "data": aggregated,
            "meta": {
                "default_model": self._effective_default_model(),
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

    def get_model_profile(self, model_id: str | None) -> dict[str, Any]:
        payload = self.list_models_payload()
        candidate = (model_id or "").strip() or self._effective_default_model()
        for item in payload["data"]:
            if item.get("id") == candidate:
                return deepcopy(item)
        return self._build_model_item({"id": candidate}, source="default")

    def ensure_novel_generation_model_supported(self, model_id: str | None) -> dict[str, Any]:
        profile = self.get_model_profile(model_id)
        compatibility = str((profile.get("metadata") or {}).get("compatibility") or "").strip()
        supported = bool(((profile.get("capabilities") or {}).get("features") or {}).get("novel_task_supported"))
        if compatibility == "verified" and supported:
            return profile
        raise ValueError(
            f"模型 {profile.get('id') or model_id or ''} 未完成兼容性验证，暂不支持小说任务流。"
            "请改用已验证模型，例如 gpt-5.4、glm-5.1 或 MiniMax-M2.7-highspeed。"
        )

    def _load_gateway_models(self) -> list[dict[str, Any]]:
        if self.gateway_client is None:
            return []
        try:
            payload = self.gateway_client.list_models()
        except Exception:
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
            source = "gateway+registry" if model_id in self.registry else "gateway"
            items.append(self._build_model_item(raw, source=source))

        # 2. 再补充注册表中有 profile 但网关未返回的模型
        for model_id, profile in self.registry.items():
            if model_id in seen:
                continue
            seen.add(model_id)
            items.append(self._build_model_item({"id": model_id}, source="registry"))

        return self._order_default_model_first(items)

    def _order_default_model_first(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """将当前生效默认模型置顶。"""
        effective_default = self._effective_default_model().strip()
        default_idx = next((i for i, item in enumerate(items) if item["id"] == effective_default), -1)
        if default_idx > 0:
            items.insert(0, items.pop(default_idx))
        return items

    def _sync_runtime_default_from_verified_env_default(self, items: list[dict[str, Any]]) -> bool:
        """刷新模型目录后，将缺失或失效的持久化默认模型同步为已验证的配置默认模型。"""
        env_default = (self.settings.default_chat_model or "").strip()
        if not env_default:
            return False
        env_default_item = self._find_model_item(items, env_default)
        if not self._is_verified_runtime_default_item(env_default_item):
            return False

        runtime_default = (self._runtime_default_model or "").strip()
        if runtime_default:
            runtime_item = self._find_model_item(items, runtime_default)
            if self._is_verified_runtime_default_item(runtime_item):
                return False

        self._runtime_default_model = env_default
        self._save_runtime_settings()
        return True

    @staticmethod
    def _find_model_item(items: list[dict[str, Any]], model_id: str) -> dict[str, Any] | None:
        for item in items:
            if item.get("id") == model_id:
                return item
        return None

    @staticmethod
    def _is_verified_runtime_default_item(item: dict[str, Any] | None) -> bool:
        if not item:
            return False
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        source = str(metadata.get("source") or "").strip()
        if source in {"registry", "default+registry"}:
            return False
        compatibility = str(metadata.get("compatibility") or "").strip()
        features = (item.get("capabilities") or {}).get("features") or {}
        return compatibility == "verified" and bool(features.get("novel_task_supported"))

    def _build_model_item(self, raw: dict[str, Any], source: str) -> dict[str, Any]:
        model_id = str(raw.get("id") or "").strip()
        profile = deepcopy(self.registry.get(model_id, {}))
        capabilities = profile.get("capabilities") or self._unknown_capabilities(model_id)
        capabilities = apply_context_window_config(capabilities, model_id, settings=self.settings)
        provider = profile.get("provider") or self.settings.llm_provider
        display_name = profile.get("display_name") or model_id
        compatibility = "verified" if source in {"gateway+registry", "registry", "default+registry"} else "unverified"
        protocol = profile.get("protocol") or getattr(self.settings, "default_protocol", "openai") or "openai"
        if hasattr(self.settings, "effective_protocol_overrides"):
            protocol = self.settings.effective_protocol_overrides.get(model_id, protocol)
        capabilities.setdefault("features", {})
        if isinstance(capabilities["features"], dict):
            capabilities["features"].setdefault("novel_task_supported", compatibility == "verified")
        return {
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
            },
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
    """查询模型本次生成使用的输出 token 上限。"""
    configured = resolve_generation_max_tokens(model_id, settings=settings)
    if configured is not None:
        return configured
    profile = _PROFILE_REGISTRY.get((model_id or "").strip(), {})
    capabilities = profile.get("capabilities") or {}
    context_window = capabilities.get("context_window") or {}
    return context_window.get("max_output_tokens")
