"""
Agent 基类

所有具体 Agent 的公共父类，提供完整的 Agent 通用能力：
- Skill YAML 加载与管理
- gateway_client 守卫
- 流式 LLM 调用（支持思考链透传）
- JSON 解析与清理
- LLM 调用 + JSON 解析 + 重试
- 子类按需扩展业务方法
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.agents.loader import SkillLoader
from app.llm.gateway_client import GatewayClientError, OpenAICompatibleGatewayClient

logger = logging.getLogger(__name__)

# JSON 重试提示词（全局共享）
_RETRY_JSON_PROMPT = (
    "上一次返回结果不是可解析的目标 JSON。"
    "请重新输出一个完整、可解析的 JSON 对象。"
    "不要输出 Markdown 代码围栏，不要解释，不要补充说明，只返回最终 JSON 对象。"
)


class BaseAgent:
    """
    Agent 基类。

    提供所有 Agent 共享的核心能力：
    - Skill YAML 加载（通过 _skill_subdir 指定子目录）
    - gateway_client 守卫
    - 流式 LLM 调用（含思考链透传）
    - JSON 解析与清理
    - LLM 调用 + JSON 解析 + 自动重试

    子类只需设置 _skill_subdir 并按需扩展业务方法。
    """

    _skill_subdir: str  # 子类必须设置：story_engine / auto_reviewer

    def __init__(
        self,
        gateway_client: OpenAICompatibleGatewayClient | None = None,
    ) -> None:
        self.gateway_client = gateway_client
        self._skill_loader: SkillLoader | None = None
        self._skills_loaded: bool = False

    # ── Skill 加载 ──────────────────────────────

    def _load_skills(self) -> None:
        """加载 _skill_subdir 目录下的 Skill YAML，失败时静默 fallback。"""
        try:
            skills_root = Path(__file__).parent / "skills" / self._skill_subdir
            self._skill_loader = SkillLoader(skills_root)
            registry = self._skill_loader.load_all()
            if registry:
                self._skills_loaded = True
                logger.info(
                    "%s 已加载 %d 个 Skill: %s",
                    self.__class__.__name__,
                    len(registry),
                    list(registry.keys()),
                )
        except Exception as exc:
            logger.warning("Skill YAML 加载失败，使用内置 prompt fallback: %s", exc)
            self._skills_loaded = False

    # ── Gateway 守卫 ────────────────────────────

    def _require_gateway_client(self) -> OpenAICompatibleGatewayClient:
        """返回 gateway_client，未配置时抛出 GatewayClientError。"""
        if self.gateway_client is None:
            raise GatewayClientError(
                "当前没有可用的模型网关，请检查 apps/agent-runtime/.env 中的 LLM_BASE_URL 与 LLM_API_KEY 配置。"
            )
        return self.gateway_client

    # ── 流式 LLM 调用 ────────────────────────────

    def _call_llm_stream(
        self,
        messages: list[dict[str, str]],
        model: str,
        *,
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
        stage: str = "",
        unit_id: str = "",
    ) -> str:
        """
        流式调用 LLM，返回完整文本内容。

        可选通过 progress_callback 透传思考链事件。
        """
        gc = self._require_gateway_client()
        full_content = ""
        full_reasoning = ""
        for chunk in gc.complete_stream_sync(messages, model=model):
            if chunk.reasoning_content and progress_callback:
                full_reasoning += chunk.reasoning_content
                progress_callback({
                    "event_type": "model.thinking",
                    "stage": stage,
                    "unit_id": unit_id,
                    "message": "模型思考中...",
                    "payload": {
                        "reasoning_chunk": chunk.reasoning_content,
                        "accumulated_length": len(full_reasoning),
                    },
                })
            if chunk.content:
                full_content += chunk.content
        return full_content

    # ── JSON 解析 ──────────────────────────────

    def _strip_and_parse_json(self, raw: str) -> dict[str, Any]:
        """清理 Markdown 围栏并解析 JSON，失败时尝试提取首个 JSON 值。"""
        gc = self._require_gateway_client()
        cleaned = gc._strip_markdown_fences(raw)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            extracted = gc._extract_first_json_value(cleaned)
            if extracted is not None:
                return extracted
            raise GatewayClientError(f"模型返回的 JSON 无法解析：{raw[:240]}")

    # ── LLM 调用 + JSON 解析 + 重试 ────────────

    def _call_llm_json(
        self,
        messages: list[dict[str, str]],
        model: str,
        *,
        max_retries: int = 1,
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
        stage: str = "",
        unit_id: str = "",
    ) -> dict[str, Any]:
        """
        流式调用 LLM 并解析 JSON，解析失败时自动重试。

        重试时在原始消息后追加重试提示词。
        """
        attempt_messages = list(messages)
        for attempt in range(max_retries + 1):
            full_content = self._call_llm_stream(
                attempt_messages,
                model,
                progress_callback=progress_callback,
                stage=stage,
                unit_id=unit_id,
            )
            try:
                return self._strip_and_parse_json(full_content)
            except (GatewayClientError, json.JSONDecodeError):
                if attempt >= max_retries:
                    raise
                # 在当前尝试的消息基础上追加重试提示
                attempt_messages = [dict(item) for item in attempt_messages] + [
                    {"role": "user", "content": _RETRY_JSON_PROMPT}
                ]
        # 理论上不可达
        raise GatewayClientError("LLM 调用重试后仍无法解析 JSON。")
