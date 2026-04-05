"""
Agent 基类

所有具体 Agent 的公共父类，提供 prompt 渲染和 LLM 调用能力。
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any

from app.agents.models import SkillConfig
from app.llm.gateway_client import GatewayClientError, OpenAICompatibleGatewayClient

logger = logging.getLogger(__name__)


class BaseAgent:
    """
    Agent 基类。

    职责：
    - 持有一个 SkillConfig 实例
    - 提供 prompt 渲染能力（将变量注入模板）
    - 提供 LLM 调用能力（委托给 GatewayClient）
    - 提供流式调用、缓存、重试的统一接口
    """

    def __init__(
        self,
        skill_config: SkillConfig,
        gateway_client: OpenAICompatibleGatewayClient | None = None,
        response_cache: Any | None = None,
    ) -> None:
        self.skill_config = skill_config
        self.gateway_client = gateway_client
        self.response_cache = response_cache

    def render_prompt(self, **variables: Any) -> list[dict[str, str]]:
        """
        将变量注入 prompt 模板，返回 [{role, content}] 消息列表。

        校验必填变量是否已提供，缺失时使用默认值或抛出 ValueError。
        """
        messages: list[dict[str, str]] = []

        for role_name in ("system", "human"):
            template = getattr(self.skill_config.prompt, role_name, "")
            if not template:
                continue

            # 校验必填变量
            for var_def in self.skill_config.input_variables:
                if var_def.required and var_def.name not in variables:
                    if var_def.default is not None:
                        variables.setdefault(var_def.name, var_def.default)
                    else:
                        raise ValueError(
                            f"Skill [{self.skill_config.skill_id}]: "
                            f"缺少必填变量 '{var_def.name}'"
                        )

            # 为所有有默认值的变量填充默认值
            for var_def in self.skill_config.input_variables:
                if var_def.name not in variables and var_def.default is not None:
                    variables.setdefault(var_def.name, var_def.default)

            # 安全格式化（忽略未在模板中使用的变量）
            try:
                content = template.format(**variables)
            except KeyError as e:
                # 模板中有变量但未提供值，使用空字符串
                missing_key = str(e).strip("'\"")
                logger.warning(
                    "Skill [%s] 变量 '%s' 未提供，使用空字符串",
                    self.skill_config.skill_id,
                    missing_key,
                )
                patched = dict(variables)
                patched[missing_key] = ""
                content = template.format(**patched)

            messages.append({"role": role_name, "content": content})

        return messages

    def resolve_model(self, override: str | None = None, settings_default: str | None = None) -> str:
        """解析实际使用的模型。优先级：调用时传入 > skill 配置 > settings 默认。"""
        candidate = (override or "").strip()
        if candidate:
            return candidate
        if self.skill_config.model.default:
            return self.skill_config.model.default
        if settings_default:
            return settings_default
        return ""

    def call_stream(
        self,
        variables: dict[str, Any],
        model: str | None = None,
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> str:
        """
        流式调用 LLM，返回完整的文本内容。

        用于写作类 Agent 的流式 JSON 生成。
        """
        if self.gateway_client is None:
            raise RuntimeError(f"Agent [{self.skill_config.skill_id}] 未配置 gateway_client")

        messages = self.render_prompt(**variables)
        resolved_model = self.resolve_model(model)

        full_content = ""
        for chunk in self.gateway_client.complete_stream_sync(messages, model=resolved_model):
            # 透传思考链
            if chunk.reasoning_content and progress_callback:
                progress_callback({
                    "reasoning_chunk": chunk.reasoning_content,
                })
            if chunk.content:
                full_content += chunk.content

        return full_content

    def call_json(
        self,
        variables: dict[str, Any],
        model: str | None = None,
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
        retry_count: int | None = None,
    ) -> dict[str, Any]:
        """
        流式调用 LLM 并解析 JSON 返回。

        支持：流式思考链透传、JSON 解析、重试。
        """
        if self.gateway_client is None:
            raise RuntimeError(f"Agent [{self.skill_config.skill_id}] 未配置 gateway_client")

        attempts = retry_count if retry_count is not None else self.skill_config.runtime.retry_count

        # 首次尝试
        full_content = self.call_stream(variables, model=model, progress_callback=progress_callback)
        result = self._parse_json_response(full_content)
        if result is not None:
            return result

        # 重试
        for i in range(attempts):
            logger.warning(
                "Skill [%s] JSON 解析失败，重试 %d/%d",
                self.skill_config.skill_id,
                i + 1,
                attempts,
            )
            retry_prompt = self.skill_config.runtime.retry_prompt or (
                "上一次返回结果不是可解析的目标 JSON。"
                "请重新输出一个完整、可解析的 JSON 对象。"
                "不要输出 Markdown 代码围栏，不要解释，不要补充说明，只返回最终 JSON 对象。"
            )
            retry_messages = self.render_prompt(**variables)
            retry_messages.append({"role": "assistant", "content": full_content})
            retry_messages.append({"role": "user", "content": retry_prompt})

            resolved_model = self.resolve_model(model)
            retry_content = ""
            for chunk in self.gateway_client.complete_stream_sync(retry_messages, model=resolved_model):
                if chunk.content:
                    retry_content += chunk.content

            result = self._parse_json_response(retry_content)
            if result is not None:
                return result

        raise GatewayClientError(
            f"Skill [{self.skill_config.skill_id}] 重试 {attempts} 次后仍无法解析 JSON。"
            f"最后响应: {full_content[:300]}"
        )

    def _parse_json_response(self, content: str) -> dict[str, Any] | None:
        """解析 LLM 返回的 JSON 内容。"""
        if self.gateway_client is None:
            return None

        cleaned = self.gateway_client._strip_markdown_fences(content)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            extracted = self.gateway_client._extract_first_json_value(cleaned)
            if extracted is not None:
                return extracted
            return None
