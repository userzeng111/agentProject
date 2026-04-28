"""
动态审核桥接层

将 TaskOrchestrator 包装为与 AutoReviewManager.review() 兼容的接口：
- 输入：ReviewPayload + AutoReviewPolicy
- 输出：ReviewDecision
- 下游（main_graph、task_service）完全不需要改动
"""

from __future__ import annotations

import json
from app.observability import get_logger
from typing import Any

from app.agents.dynamic.models import (
    OrchestrationResult,
    TaskExecutionResult,
)
from app.agents.dynamic.orchestrator import TaskOrchestrator
from app.domain.models import (
    AgentResult as DomainAgentResult,
    AutoReviewPolicy,
    ReviewDecision,
    ReviewPayload,
)
from app.llm.gateway_client import OpenAICompatibleGatewayClient

logger = get_logger(__name__)

MAIN_REVIEW_AGENT_ID = "dynamic-review-main"


class DynamicReviewBridge:
    """
    动态审核桥接层。

    职责：
    - 将 ReviewPayload 转换为 TaskOrchestrator 所需的 task_context
    - 调用 TaskOrchestrator.execute()
    - 将 OrchestrationResult 转换为 ReviewDecision
    """

    def __init__(
        self,
        gateway_client: OpenAICompatibleGatewayClient,
        default_model: str = "MiniMax-M2.7-highspeed",
        max_workers: int = 4,
    ) -> None:
        self._gateway_client = gateway_client
        self._default_model = default_model
        self._max_workers = max_workers

    def review(self, payload: ReviewPayload, policy: AutoReviewPolicy) -> ReviewDecision:
        """
        执行动态审核，返回 ReviewDecision。

        接口签名与 AutoReviewManager.review() 完全一致。
        """
        review_type = payload.type
        logger.info("动态审核开始: review_type=%s, model=%s", review_type, policy.auditor_model or self._default_model)
        task_description = self._build_task_description(payload)
        task_context = self._build_task_context(payload, policy)

        # 根据审核类型选择模型
        model = policy.auditor_model or self._default_model

        try:
            orchestrator = TaskOrchestrator(
                gateway_client=self._gateway_client,
                default_model=model,
                max_workers=self._max_workers,
            )

            result = orchestrator.execute(
                task_type=review_type,
                task_description=task_description,
                task_context=task_context,
                model=model,
            )

            decision = self._convert_to_review_decision(result, policy, review_type)
            logger.info("动态审核结束: review_type=%s, score=%s, approved=%s, agent_trace_count=%s", review_type, decision.overall_score, decision.approved, len(decision.agent_trace))
            return decision

        except Exception as e:
            logger.error("动态审核桥接异常: %s", e, exc_info=True)
            return ReviewDecision(
                approved=False,
                comment=f"动态审核执行异常: {e}，请人工介入。",
                reasoning=str(e),
                auto_escalated=True,
                overall_score=0.0,
            )

    def _build_task_description(self, payload: ReviewPayload) -> str:
        """根据审核类型构建任务描述。"""
        review_type = payload.type

        if review_type == "outline_review":
            sp = payload.story_plan
            title = sp.working_title if sp else "未知"
            return f"审核小说大纲「{title}」的结构完整性、逻辑一致性和创意价值"

        elif review_type == "chapter_pair_review":
            chapters = payload.chapter_pair or []
            chapter_nums = ", ".join(str(ch.number if hasattr(ch, "number") else ch.get("number", "?")) for ch in chapters)
            return f"审核第 {chapter_nums} 章是否符合理大纲要求"

        elif review_type == "verification_review":
            return "审核全文一致性验证报告，判断问题严重度和修复范围"

        return f"执行 {review_type} 类型审核"

    def _build_task_context(self, payload: ReviewPayload, policy: AutoReviewPolicy) -> dict[str, Any]:
        """将 ReviewPayload 转换为 TaskOrchestrator 所需的 task_context。"""
        context: dict[str, Any] = {}

        # 通用上下文
        spec = getattr(payload, "_normalized_spec", {})
        context["mode"] = getattr(payload, "_mode", spec.get("mode", ""))
        context["genre"] = getattr(payload, "_genre", spec.get("genre", ""))
        context["style"] = getattr(payload, "_style", spec.get("style", ""))
        context["target_words"] = getattr(payload, "_target_words", spec.get("target_words", ""))
        context["user_prompt"] = getattr(payload, "_user_prompt", spec.get("prompt", ""))

        # 大纲信息
        sp = payload.story_plan
        if sp:
            context["working_title"] = sp.working_title
            context["logline"] = sp.logline
            context["world_notes"] = "\n".join(sp.world_notes) if sp.world_notes else "无"
            context["character_notes"] = "\n".join(sp.character_notes) if sp.character_notes else "无"
            context["chapter_plan"] = "\n".join(
                f"第{ch.number}章: {ch.title} - 目标: {ch.goal}"
                for ch in (sp.chapter_plan or [])
            )

        # 章节对审核的额外上下文
        if payload.type == "chapter_pair_review":
            chapters = payload.chapter_pair or []
            context["current_chapters_text"] = "\n\n".join(
                f"=== 第{ch.number if hasattr(ch, 'number') else ch.get('number', '?')}章: "
                f"{ch.title if hasattr(ch, 'title') else ch.get('title', '')} ===\n"
                f"{ch.content if hasattr(ch, 'content') else ch.get('content', '')}"
                for ch in chapters
            )
            completed_summaries = getattr(payload, "_completed_summaries", [])
            context["completed_summaries"] = "\n".join(completed_summaries) if completed_summaries else "无"

        # 验证审核的额外上下文
        if payload.type == "verification_review":
            report = payload.verification_report or {}
            context["verification_report"] = json.dumps(report, ensure_ascii=False, indent=2)[:4000]

        # 审核策略上下文
        context["strictness"] = policy.strictness.value
        context["review_mode"] = policy.mode.value

        return context

    def _convert_to_review_decision(
        self,
        result: OrchestrationResult,
        policy: AutoReviewPolicy,
        review_type: str,
    ) -> ReviewDecision:
        """将 OrchestrationResult 转换为 ReviewDecision。"""
        # 提取综合 Agent 结果
        synthesis = result.synthesis_result
        overall_score = result.overall_score

        # 评分阈值
        pass_threshold = policy.get_pass_threshold(review_type)

        # 通过判断
        approved = overall_score >= pass_threshold

        # 自动升级判断
        auto_escalated = False
        if policy.auto_escalate_on_low_score and overall_score < pass_threshold * 0.7:
            auto_escalated = True

        # 提取综合 Agent 的详细信息
        comment = ""
        reasoning = ""
        critical_issues: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []
        highlights: list[str] = []
        revision_scope = None

        if synthesis:
            raw = synthesis.raw_response
            comment = raw.get("final_recommendation", "") or raw.get("verdict", "") or raw.get("comment", "")
            reasoning = raw.get("reasoning", "") or raw.get("summary", "")

            # 从综合 Agent 提取 issues
            key_issues = raw.get("key_issues") or raw.get("critical_issues") or []
            for issue in key_issues:
                if isinstance(issue, dict):
                    critical_issues.append(issue)
                elif isinstance(issue, str):
                    critical_issues.append({"severity": "critical", "description": issue})

            # 提取 warnings
            warnings_list = raw.get("warnings") or raw.get("weaknesses") or []
            for w in warnings_list:
                if isinstance(w, dict):
                    warnings.append(w)
                elif isinstance(w, str):
                    warnings.append({"severity": "warning", "description": w})

            # 提取 highlights
            highlights = (
                raw.get("highlights")
                or raw.get("key_strengths")
                or raw.get("strengths")
                or []
            )
            if isinstance(highlights, list):
                highlights = [str(h) for h in highlights]

            # 提取修改建议
            suggestions = raw.get("final_suggestions") or raw.get("priority_suggestions") or []
            if suggestions and not comment:
                comment = "；".join(str(s) for s in suggestions[:3])

            revision_scope = raw.get("revision_scope")

        # 如果没有通过，构建审核意见
        if not approved and not comment:
            comment = self._build_fallback_comment(result.agent_results, overall_score, pass_threshold)

        # 构建 agent_trace（兼容 AgentResult 格式）
        agent_trace: list[DomainAgentResult] = [
            DomainAgentResult(
                agent_id=MAIN_REVIEW_AGENT_ID,
                agent_name="主审核编排 Agent",
                role="orchestrator",
                execution_kind="main_agent",
                created_by="system",
                invocation_kind="orchestrate",
                status="completed",
                score=overall_score,
                reasoning=reasoning or f"主 Agent 完成 {review_type} 审核编排",
            )
        ]
        for r in result.agent_results:
            agent_trace.append(DomainAgentResult(
                agent_id=r.agent_id,
                agent_name=r.agent_name,
                role=r.role,
                execution_kind=r.execution_kind or "subagent",
                parent_agent_id=r.parent_agent_id or MAIN_REVIEW_AGENT_ID,
                created_by=r.created_by or "main_agent",
                invocation_kind=r.invocation_kind or "function_call",
                status="completed" if r.is_success else "failed",
                score=r.score,
                issues=r.issues if all(isinstance(i, dict) for i in r.issues) else [],
                warnings=r.warnings if all(isinstance(i, dict) for i in r.warnings) else [],
                highlights=r.highlights,
                reasoning=r.reasoning,
                raw_response=r.raw_response,
                error=r.error,
                started_at=r.started_at,
                completed_at=r.completed_at,
            ))
        # 加入综合 Agent
        if synthesis:
            agent_trace.append(DomainAgentResult(
                agent_id=synthesis.agent_id,
                agent_name=synthesis.agent_name,
                role=synthesis.role,
                execution_kind="synthesis",
                parent_agent_id=synthesis.parent_agent_id or MAIN_REVIEW_AGENT_ID,
                created_by=synthesis.created_by or "main_agent",
                invocation_kind=synthesis.invocation_kind or "function_call",
                status="completed" if synthesis.is_success else "failed",
                score=synthesis.score,
                reasoning=synthesis.reasoning,
                started_at=synthesis.started_at,
                completed_at=synthesis.completed_at,
            ))

        return ReviewDecision(
            approved=approved,
            comment=comment,
            reasoning=reasoning or f"动态 Agent 审核评分 {overall_score:.1f}（阈值 {pass_threshold:.1f}）",
            agent_trace=agent_trace,
            auto_escalated=auto_escalated,
            overall_score=overall_score,
            critical_issues=critical_issues,
            warnings=warnings,
            suggestions=highlights,
            revision_needed=not approved,
            revision_scope=revision_scope if not approved else None,
        )

    @staticmethod
    def _build_fallback_comment(
        agent_results: list[TaskExecutionResult],
        overall_score: float,
        pass_threshold: float,
    ) -> str:
        """构建降级审核意见。"""
        parts = [f"动态 Agent 审核评分 {overall_score:.1f}（阈值 {pass_threshold:.1f}）"]
        for r in agent_results:
            if r.issues:
                for issue in r.issues[:3]:
                    if isinstance(issue, dict):
                        parts.append(f"- [{r.agent_name}] {issue.get('description', '')}")
                    elif isinstance(issue, str):
                        parts.append(f"- [{r.agent_name}] {issue}")
        return "\n".join(parts)
