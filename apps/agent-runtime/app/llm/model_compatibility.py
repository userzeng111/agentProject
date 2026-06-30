from __future__ import annotations

import json
import logging
import os
import secrets
import threading
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


CHECK_IDS = [
    "gateway_visible",
    "streaming",
    "content_output",
    "reasoning_signal",
    "context_echo",
    "json_schema",
    "novel_minimum",
]

CHECK_LABELS = {
    "gateway_visible": "网关可见",
    "streaming": "流式输出",
    "content_output": "内容输出",
    "reasoning_signal": "推理信号",
    "context_echo": "上下文回显",
    "json_schema": "结构化 JSON",
    "novel_minimum": "小说任务最小能力",
}

VALID_REPORT_STATUSES = {"verified", "failed", "unverified"}
VALID_CHECK_STATUSES = {"pending", "running", "passed", "failed", "skipped"}
VALIDATOR_VERSION = "2026-06-30"
LOGGER = logging.getLogger(__name__)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_check(
    check_id: str,
    status: str,
    summary: str,
    evidence: dict[str, Any] | None = None,
    failure_reason: str = "",
) -> dict[str, Any]:
    if check_id not in CHECK_IDS:
        raise ValueError(f"未知验证项：{check_id}")
    if status not in VALID_CHECK_STATUSES:
        raise ValueError(f"未知验证项状态：{status}")
    return {
        "id": check_id,
        "label": CHECK_LABELS[check_id],
        "status": status,
        "summary": summary,
        "failure_reason": failure_reason,
        "evidence": evidence or {},
    }


class ModelCompatibilityService:
    def __init__(
        self,
        tasklog_root: str,
        gateway_client: Any | None,
        model_catalog_resolver: Any | None = None,
        model_catalog_invalidator: Any | None = None,
    ) -> None:
        self.tasklog_root = Path(tasklog_root)
        self.gateway_client = gateway_client
        self.model_catalog_resolver = model_catalog_resolver
        self.model_catalog_invalidator = model_catalog_invalidator
        self.path = self.tasklog_root / "model_compatibility.json"
        self._store_lock = threading.RLock()
        self._store_cache: dict[str, Any] | None = None
        self._store_cache_fingerprint: tuple[int, int] | None = None
        self._store_warning_fingerprint: tuple[int, int] | None = None

    def _store_fingerprint(self) -> tuple[int, int] | None:
        try:
            stat = self.path.stat()
        except FileNotFoundError:
            return None
        return (stat.st_mtime_ns, stat.st_size)

    def _cache_store(self, data: dict[str, Any], fingerprint: tuple[int, int] | None) -> dict[str, Any]:
        self._store_cache = deepcopy(data)
        self._store_cache_fingerprint = fingerprint
        return deepcopy(data)

    def _load_store(self) -> dict[str, Any]:
        fingerprint = self._store_fingerprint()
        if self._store_cache is not None and self._store_cache_fingerprint == fingerprint:
            return deepcopy(self._store_cache)
        if not self.path.exists():
            return self._cache_store({"version": 1, "models": {}}, fingerprint)
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception as exc:
            if self._store_warning_fingerprint != fingerprint:
                LOGGER.warning("读取模型兼容性报告失败，已忽略损坏文件 %s：%s", self.path, exc)
                self._store_warning_fingerprint = fingerprint
            return self._cache_store({"version": 1, "models": {}}, fingerprint)
        if not isinstance(data, dict):
            return self._cache_store({"version": 1, "models": {}}, fingerprint)
        models = data.get("models")
        if not isinstance(models, dict):
            models = {}
        return self._cache_store({"version": 1, "models": models}, fingerprint)

    def _save_store(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_name(f"{self.path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp")
        tmp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_path.replace(self.path)
        self._store_warning_fingerprint = None
        self._cache_store(data, self._store_fingerprint())

    def _invalidate_model_catalog_cache(self) -> None:
        if self.model_catalog_invalidator is None:
            return
        try:
            self.model_catalog_invalidator()
        except Exception as exc:
            LOGGER.warning("刷新模型目录缓存失败，已继续: error=%s", exc)
            return

    def build_report(
        self,
        model_id: str,
        status: str,
        summary: str,
        checks: list[dict[str, Any]],
        evidence: dict[str, Any] | None = None,
        failure_reason: str = "",
    ) -> dict[str, Any]:
        if status not in VALID_REPORT_STATUSES:
            raise ValueError(f"未知验证状态：{status}")
        return {
            "model_id": model_id,
            "status": status,
            "validated_at": utc_now_iso() if status != "unverified" else "",
            "validator_version": VALIDATOR_VERSION,
            "summary": summary,
            "failure_reason": failure_reason,
            "checks": checks,
            "evidence": evidence or {},
        }

    def get_report(self, model_id: str) -> dict[str, Any]:
        candidate = (model_id or "").strip()
        with self._store_lock:
            data = self._load_store()
        report = data["models"].get(candidate)
        if isinstance(report, dict):
            return {"model_id": candidate, **report}
        return self.build_report(candidate, "unverified", "尚未验证", [])

    def save_report(self, report: dict[str, Any]) -> dict[str, Any]:
        model_id = str(report.get("model_id") or "").strip()
        if not model_id:
            raise ValueError("model_id 不能为空")
        with self._store_lock:
            data = self._load_store()
            payload = {k: v for k, v in report.items() if k != "model_id"}
            data["models"][model_id] = payload
            self._save_store(data)
        self._invalidate_model_catalog_cache()
        return report

    def clear_report(self, model_id: str) -> dict[str, Any]:
        candidate = (model_id or "").strip()
        with self._store_lock:
            data = self._load_store()
            data["models"].pop(candidate, None)
            self._save_store(data)
        self._invalidate_model_catalog_cache()
        return self.get_report(candidate)

    async def run_validation_stream(self, model_id: str, context_marker: str | None = None):
        candidate = (model_id or "").strip()
        if not candidate:
            raise ValueError("model_id 不能为空")
        marker = (context_marker or "").strip() or f"CTX-{secrets.token_hex(4)}"
        check_states = {check_id: build_check(check_id, "pending", "等待验证") for check_id in CHECK_IDS}
        evidence: dict[str, Any] = {
            "chunk_count": 0,
            "reasoning_chars": 0,
            "reasoning_event_count": 0,
            "content_chars": 0,
            "context_marker_seen": False,
            "usage": {},
        }

        yield {
            "event": "validation.started",
            "data": {
                "model_id": candidate,
                "context_marker": marker,
                "checks": self._ordered_checks(check_states),
                "validator_version": VALIDATOR_VERSION,
            },
        }

        def mark_check(check_id: str, status: str, summary: str, failure_reason: str = "") -> dict[str, Any]:
            check = build_check(check_id, status, summary, dict(evidence), failure_reason)
            check_states[check_id] = check
            return check

        gateway_check = mark_check("gateway_visible", "running", "正在确认模型是否来自网关")
        yield self._check_event(candidate, gateway_check)
        if not self._gateway_visible(candidate):
            message = "模型未出现在网关返回列表中，请检查 LLM_BASE_URL、LLM_API_KEY 或供应商模型权限。"
            failed = mark_check("gateway_visible", "failed", message, message)
            yield self._check_event(candidate, failed)
            report = self._save_failed_report(candidate, check_states, evidence, failed)
            yield self._error_event(candidate, "gateway_visible", message, report)
            return
        passed = mark_check("gateway_visible", "passed", "模型来自网关")
        yield self._check_event(candidate, passed)

        messages = self._build_validation_messages(candidate, marker)
        streaming_running = mark_check("streaming", "running", "正在请求模型流式输出")
        yield self._check_event(candidate, streaming_running)
        content_parts: list[str] = []
        try:
            stream = self.gateway_client.complete_stream(
                messages,
                model=candidate,
                temperature=0,
                max_tokens=800,
                _obs_stage="model_validation",
                _obs_exchange_label="compatibility",
            )
            if not hasattr(stream, "__aiter__"):
                stream = await stream
            async for chunk in stream:
                content = str(getattr(chunk, "content", "") or "")
                reasoning_content = str(getattr(chunk, "reasoning_content", "") or "")
                usage = getattr(chunk, "usage", None) or {}
                if usage:
                    evidence["usage"] = usage
                if content or reasoning_content or usage:
                    evidence["chunk_count"] += 1
                if reasoning_content:
                    evidence["reasoning_chars"] += len(reasoning_content)
                    evidence["reasoning_event_count"] += 1
                if content:
                    content_parts.append(content)
                if content or reasoning_content:
                    yield {
                        "event": "validation.chat_chunk",
                        "data": {
                            "model_id": candidate,
                            "content": content,
                            "reasoning_signal": bool(reasoning_content),
                            "reasoning_chars_delta": len(reasoning_content),
                        },
                    }
        except Exception as exc:
            message = f"流式响应中断：{exc}"
            failed = mark_check("streaming", "failed", message, message)
            yield self._check_event(candidate, failed)
            report = self._save_failed_report(candidate, check_states, evidence, failed)
            yield self._error_event(candidate, "streaming", message, report)
            return

        if evidence["chunk_count"] <= 0:
            message = "未收到流式 chunk，模型可能不支持当前协议的流式响应。"
            failed = mark_check("streaming", "failed", message, message)
            yield self._check_event(candidate, failed)
            report = self._save_failed_report(candidate, check_states, evidence, failed)
            yield self._error_event(candidate, "streaming", message, report)
            return
        passed = mark_check("streaming", "passed", f"收到 {evidence['chunk_count']} 个 chunk")
        yield self._check_event(candidate, passed)

        content = "".join(content_parts).strip()
        evidence["content_chars"] = len(content)
        if not content:
            message = "模型返回内容为空。"
            failed = mark_check("content_output", "failed", message, message)
            yield self._check_event(candidate, failed)
            report = self._save_failed_report(candidate, check_states, evidence, failed)
            yield self._error_event(candidate, "content_output", message, report)
            return
        passed = mark_check("content_output", "passed", "收到非空正文")
        yield self._check_event(candidate, passed)

        reasoning_failed_check: dict[str, Any] | None = None
        if int(evidence["reasoning_chars"]) <= 0:
            message = "未收到 reasoning_content 或可识别推理事件。该模型可聊天，但不满足当前小说任务流的推理信号要求。"
            reasoning_failed_check = mark_check("reasoning_signal", "failed", message, message)
            yield self._check_event(candidate, reasoning_failed_check)
        else:
            passed = mark_check("reasoning_signal", "passed", "收到推理信号元数据")
            yield self._check_event(candidate, passed)

        evidence["context_marker_seen"] = marker in content
        if not evidence["context_marker_seen"]:
            message = "模型有输出，但未回显上下文哨兵，可能没有正确接收系统上下文。"
            failed = mark_check("context_echo", "failed", message, message)
            yield self._check_event(candidate, failed)
            report = self._save_failed_report(candidate, check_states, evidence, failed)
            yield self._error_event(candidate, "context_echo", message, report)
            return
        passed = mark_check("context_echo", "passed", "已回显上下文哨兵")
        yield self._check_event(candidate, passed)

        try:
            parsed = self._parse_json_object(content)
        except ValueError as exc:
            message = str(exc)
            failed = mark_check("json_schema", "failed", message, message)
            yield self._check_event(candidate, failed)
            report = self._save_failed_report(candidate, check_states, evidence, failed)
            yield self._error_event(candidate, "json_schema", message, report)
            return
        schema_error = self._json_schema_error(parsed, marker)
        if schema_error:
            failed = mark_check("json_schema", "failed", schema_error, schema_error)
            yield self._check_event(candidate, failed)
            report = self._save_failed_report(candidate, check_states, evidence, failed)
            yield self._error_event(candidate, "json_schema", schema_error, report)
            return
        passed = mark_check("json_schema", "passed", "JSON 可解析")
        yield self._check_event(candidate, passed)

        if not self._has_novel_minimum(parsed, content):
            message = "模型输出不符合中文小说任务最小格式。"
            failed = mark_check("novel_minimum", "failed", message, message)
            yield self._check_event(candidate, failed)
            report = self._save_failed_report(candidate, check_states, evidence, failed)
            yield self._error_event(candidate, "novel_minimum", message, report)
            return
        passed = mark_check("novel_minimum", "passed", "中文小说片段非空")
        yield self._check_event(candidate, passed)

        if reasoning_failed_check is not None:
            message = reasoning_failed_check.get("failure_reason") or reasoning_failed_check.get("summary") or "未收到推理信号。"
            report = self._save_failed_report(candidate, check_states, evidence, reasoning_failed_check)
            yield self._error_event(candidate, "reasoning_signal", message, report)
            return

        report = self.build_report(
            model_id=candidate,
            status="verified",
            summary="流式、上下文、推理信号、JSON 与小说最小能力均通过",
            checks=self._ordered_checks(check_states),
            evidence=evidence,
        )
        self.save_report(report)
        yield {
            "event": "validation.done",
            "data": {
                "model_id": candidate,
                "status": "verified",
                "report": report,
            },
        }

    def _gateway_visible(self, model_id: str) -> bool:
        if self.model_catalog_resolver is None:
            return False
        try:
            payload = self.model_catalog_resolver()
        except Exception as exc:
            LOGGER.warning("读取模型目录失败，模型兼容性验证将按不可见处理: model=%s error=%s", model_id, exc)
            return False
        items = payload.get("data", []) if isinstance(payload, dict) else payload
        if not isinstance(items, list):
            return False
        for item in items:
            if not isinstance(item, dict) or item.get("id") != model_id:
                continue
            metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
            return "gateway" in str(metadata.get("source") or "")
        return False

    def _build_validation_messages(self, model_id: str, context_marker: str) -> list[dict[str, str]]:
        system = (
            "你正在执行模型兼容性验证，只验证协议、上下文接收、流式输出和结构化输出能力，"
            "不做文学质量评分。请严格遵守用户要求，只返回一个 JSON 对象。"
        )
        user = (
            f"待验证模型：{model_id}\n"
            f"上下文哨兵 context_marker：{context_marker}\n"
            "请完成一个中文小说任务要求：为一篇雨夜悬疑短篇小说生成最小章节大纲。\n"
            "必须返回严格 JSON，不能添加 Markdown、解释或额外文本。\n"
            "JSON 字段必须包含：\n"
            f'- "context_marker": "{context_marker}"，必须原样回显上下文哨兵；\n'
            '- "outline": 至少 1 个对象，每个对象包含 "title" 和 "goal"，内容使用中文小说表达；\n'
            '- "risk_flags": 数组，可为空数组。\n'
            "示例结构："
            '{"context_marker":"'
            f'{context_marker}'
            '","outline":[{"title":"雨夜","goal":"发现线索"}],"risk_flags":[]}'
        )
        return [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]

    @staticmethod
    def _parse_json_object(content: str) -> dict[str, Any]:
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as direct_exc:
            start = content.find("{")
            end = content.rfind("}")
            if start < 0 or end <= start:
                raise ValueError("模型输出不是合法 JSON。") from direct_exc
            try:
                parsed = json.loads(content[start : end + 1])
            except json.JSONDecodeError as exc:
                raise ValueError("模型输出不是合法 JSON。") from exc
        if not isinstance(parsed, dict):
            raise ValueError("模型输出不是 JSON 对象。")
        return parsed

    @staticmethod
    def _json_schema_error(parsed: dict[str, Any], context_marker: str) -> str:
        if parsed.get("context_marker") != context_marker:
            return "JSON 缺少 context_marker 字段或上下文哨兵不匹配。"
        outline = parsed.get("outline")
        if not isinstance(outline, list):
            return "JSON 缺少 outline 字段。"
        risk_flags = parsed.get("risk_flags")
        if risk_flags is None or not isinstance(risk_flags, list):
            return "JSON 缺少 risk_flags 字段。"
        for item in outline:
            if not isinstance(item, dict):
                return "outline 项必须是对象。"
            if not str(item.get("title") or "").strip() or not str(item.get("goal") or "").strip():
                return "outline 项缺少 title 或 goal 字段。"
        return ""

    @staticmethod
    def _has_novel_minimum(parsed: dict[str, Any], content: str) -> bool:
        outline = parsed.get("outline")
        if not isinstance(outline, list) or not outline:
            return False
        combined = content + "\n" + "\n".join(
            f"{item.get('title', '')}{item.get('goal', '')}"
            for item in outline
            if isinstance(item, dict)
        )
        chinese_chars = sum(1 for char in combined if "\u4e00" <= char <= "\u9fff")
        return chinese_chars >= 4

    @staticmethod
    def _ordered_checks(check_states: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
        return [check_states[check_id] for check_id in CHECK_IDS]

    @staticmethod
    def _check_event(model_id: str, check: dict[str, Any]) -> dict[str, Any]:
        return {
            "event": "validation.check",
            "data": {
                "model_id": model_id,
                "check": check,
            },
        }

    def _save_failed_report(
        self,
        model_id: str,
        check_states: dict[str, dict[str, Any]],
        evidence: dict[str, Any],
        failed_check: dict[str, Any],
    ) -> dict[str, Any]:
        failed_id = failed_check["id"]
        failed_index = CHECK_IDS.index(failed_id)
        for check_id in CHECK_IDS[failed_index + 1 :]:
            current = check_states[check_id]
            if current["status"] in {"pending", "running"}:
                check_states[check_id] = build_check(check_id, "skipped", "前置验证失败，已跳过")
        report = self.build_report(
            model_id=model_id,
            status="failed",
            summary="模型兼容性验证失败",
            checks=self._ordered_checks(check_states),
            evidence=evidence,
            failure_reason=failed_check.get("failure_reason") or failed_check.get("summary") or "",
        )
        self.save_report(report)
        return report

    @staticmethod
    def _error_event(model_id: str, check_id: str, message: str, report: dict[str, Any]) -> dict[str, Any]:
        return {
            "event": "validation.error",
            "data": {
                "model_id": model_id,
                "status": "failed",
                "check_id": check_id,
                "message": message,
                "report": report,
            },
        }
