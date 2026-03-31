from __future__ import annotations

from copy import deepcopy
from time import monotonic
from typing import Any

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

    def list_models(self) -> list[dict[str, Any]]:
        return self.list_models_payload()["data"]

    def list_models_payload(self) -> dict[str, Any]:
        if self._cached_payload is not None and (monotonic() - self._cached_at) < self.cache_ttl_seconds:
            return deepcopy(self._cached_payload)

        raw_models = self._load_gateway_models()
        aggregated = self._merge_models(raw_models)
        payload = {
            "data": aggregated,
            "meta": {
                "default_model": self.settings.default_chat_model,
                "capability_schema_version": _CAPABILITY_SCHEMA_VERSION,
            },
        }
        self._cached_payload = deepcopy(payload)
        self._cached_at = monotonic()
        return payload

    def get_model_profile(self, model_id: str | None) -> dict[str, Any]:
        payload = self.list_models_payload()
        candidate = (model_id or "").strip() or self.settings.default_chat_model
        for item in payload["data"]:
            if item.get("id") == candidate:
                return deepcopy(item)
        return self._build_model_item({"id": candidate}, source="default")

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

        for raw in raw_models:
            model_id = str(raw.get("id") or "").strip()
            if not model_id or model_id in seen:
                continue
            seen.add(model_id)
            source = "gateway+registry" if model_id in self.registry else "gateway"
            items.append(self._build_model_item(raw, source=source))

        default_model = self.settings.default_chat_model.strip()
        if default_model and default_model not in seen:
            items.insert(0, self._build_model_item({"id": default_model}, source="default+registry"))

        return items

    def _build_model_item(self, raw: dict[str, Any], source: str) -> dict[str, Any]:
        model_id = str(raw.get("id") or "").strip()
        profile = deepcopy(self.registry.get(model_id, {}))
        capabilities = profile.get("capabilities") or self._unknown_capabilities()
        provider = profile.get("provider") or self.settings.llm_provider
        display_name = profile.get("display_name") or model_id
        return {
            "id": model_id,
            "object": raw.get("object", "model"),
            "owned_by": raw.get("owned_by", "unknown"),
            "display_name": display_name,
            "provider": provider,
            "capabilities": capabilities,
            "metadata": {
                "source": source,
                "profile_version": "2026-03-31",
                "last_refreshed_at": None,
            },
        }

    def _unknown_capabilities(self) -> dict[str, Any]:
        return {
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
        }
