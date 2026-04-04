"""
自动审核模块

包含:
- AutoReviewManager: 审核编排器，根据 review_type 分发到对应 Auditor
- 多 Agent 协作架构（Phase 2）：
  - OutlineAuditor: StructureAgent + ConsistencyAgent + CreativityAgent → SynthesisAgent
  - ChapterAuditor: AlignmentAgent + QualityAgent + CohesionAgent → SynthesisAgent
  - VerifyAuditor: SeverityJudgeAgent + FixPlannerAgent → JudgmentAgent
"""

from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.domain.models import (
    AgentResult,
    AutoReviewPolicy,
    ChapterDraft,
    ReviewDecision,
    ReviewMode,
    ReviewPayload,
    StoryPlan,
    Strictness,
)
from app.llm.gateway_client import GatewayClientError, OpenAICompatibleGatewayClient

# 严格度对应的阈值调整因子
_STRICTNESS_MULTIPLIERS = {
    Strictness.LENIENT: 0.85,
    Strictness.BALANCED: 1.0,
    Strictness.STRICT: 1.15,
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


# ─────────────────────────────────────────────
# 子 Agent 定义
# ─────────────────────────────────────────────


@dataclass
class SubAgentSpec:
    """子 Agent 规格定义"""

    agent_id: str
    agent_name: str  # 显示名称
    role: str  # internal role: structure/consistency/creativity/alignment/quality/cohesion/severity/fix/synthesis
    dimension: str  # 审核维度名称
    weight: float = 1.0  # 权重
    prompt_template: str = ""  # Prompt 模板
    system_role: str = "你是一个中文小说质量审核专家。"


@dataclass
class SubAgentOutput:
    """子 Agent 输出"""

    agent_id: str
    agent_name: str
    role: str
    dimension: str
    score: float = 0.0
    issues: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    highlights: list[str] = field(default_factory=list)
    reasoning: str = ""
    raw_response: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None

    @property
    def duration_ms(self) -> int | None:
        if self.started_at and self.completed_at:
            return int((self.completed_at - self.started_at).total_seconds() * 1000)
        return None

    def to_agent_result(self) -> AgentResult:
        """转换为 AgentResult 用于追踪"""
        return AgentResult(
            agent_name=self.agent_name,
            role=self.role,
            status="failed" if self.error else "completed",
            score=self.score if not self.error else None,
            issues=self.issues + self.warnings,
            highlights=self.highlights,
            reasoning=self.reasoning,
            error=self.error,
            started_at=self.started_at,
            completed_at=self.completed_at,
        )


# ─────────────────────────────────────────────
# Prompt 模板 — 大纲审核子 Agent
# ─────────────────────────────────────────────


_STRUCTURE_AGENT_PROMPT = """你是一个中文小说大纲结构审核专家，专注于分析故事结构。

【你的职责】
分析大纲的章节结构是否合理，包括：
- 起承转合是否完整
- 章节数量与目标字数是否匹配
- 节奏安排是否得当
- 冲突和高潮设置是否合理

【评分标准】（0-100）
- 90-100：结构优秀，节奏完美
- 70-89：结构良好，有小瑕疵
- 50-69：结构一般，需调整
- 50以下：结构混乱，需重建

【输出要求】
严格返回 JSON：
{{
  "score": int,
  "issues": [{{"severity": "critical", "dimension": "structure", "description": str, "suggestion": str}}],
  "warnings": [{{"severity": "warning", "dimension": "structure", "description": str, "suggestion": str}}],
  "highlights": [str],
  "reasoning": str
}}

【特殊审查规则】
- 模式：{mode}
- 用户目标字数：{requested_target_words}
- 最低成稿字数：{target_words}
- 如果模式为 `short_story`：
  - 必须按短篇标准审查，不得套用中长篇标准；
  - 允许 3 到 5 章的短篇反转结构；
  - 只要能够在 `最低成稿字数` 以上完成完整起承转合和结尾反转，就不能仅因章节少而判定结构不合格；
  - 严禁动辄要求扩展到 `8-12章`、`8000字以上` 这一类中长篇方案。

【待审核大纲】
工作标题：{working_title}
一句话梗概：{logline}
章节计划：{chapter_plan}
目标字数：{target_words}
题材：{genre}
风格：{style}
"""


_CONSISTENCY_AGENT_PROMPT = """你是一个中文小说一致性审核专家，专注于检查逻辑自洽。

【你的职责】
分析大纲中的人物设定和世界观是否一致，包括：
- 人物设定是否清晰、是否有前后矛盾
- 世界观设定是否自洽
- 人物关系是否合理
- 时间线和逻辑是否连贯

【评分标准】（0-100）
- 90-100：一致性优秀，无逻辑漏洞
- 70-89：一致性良好，有微小不一致
- 50-69：存在明显不一致
- 50以下：逻辑混乱，矛盾严重

【输出要求】
严格返回 JSON：
{{
  "score": int,
  "issues": [{{"severity": "critical", "dimension": "consistency", "description": str, "suggestion": str}}],
  "warnings": [{{"severity": "warning", "dimension": "consistency", "description": str, "suggestion": str}}],
  "highlights": [str],
  "reasoning": str
}}

【待审核大纲】
世界观笔记：{world_notes}
人物笔记：{character_notes}
章节计划：{chapter_plan}
"""


_CREATIVITY_AGENT_PROMPT = """你是一个中文小说创意审核专家，专注于评估故事价值。

【你的职责】
评估大纲的创意价值和吸引力，包括：
- 是否有独特的创意亮点
- 故事钩子是否吸引人
- 与同类作品相比是否有差异化
- 题材和风格是否有新意

【评分标准】（0-100）
- 90-100：创意出色，独具匠心
- 70-89：创意良好，有亮点
- 50-69：创意一般，平淡无奇
- 50以下：创意匮乏，缺乏吸引力

【输出要求】
严格返回 JSON：
{{
  "score": int,
  "issues": [{{"severity": "critical", "dimension": "creativity", "description": str, "suggestion": str}}],
  "warnings": [{{"severity": "warning", "dimension": "creativity", "description": str, "suggestion": str}}],
  "highlights": [str],
  "reasoning": str
}}

【待审核大纲】
工作标题：{working_title}
一句话梗概：{logline}
题材：{genre}
风格：{style}
用户要求：{user_prompt}
"""


# ─────────────────────────────────────────────
# Prompt 模板 — 章节审核子 Agent
# ─────────────────────────────────────────────


_ALIGNMENT_AGENT_PROMPT = """你是一个中文小说章节对齐审核专家，检查章节是否符合大纲。

【你的职责】
检查章节是否遵循章节计划的目标，包括：
- 章节是否完成了计划中的目标
- 情节走向是否与大纲一致
- 人物行动是否与大岗设定相符

【评分标准】（0-100）
- 90-100：完美对齐，完全符合大纲
- 70-89：良好对齐，有微小偏差
- 50-69：偏差明显
- 50以下：严重偏离大纲

【输出要求】
严格返回 JSON：
{{
  "score": int,
  "issues": [{{"severity": "critical", "chapter": int, "dimension": "alignment", "description": str, "suggestion": str}}],
  "warnings": [{{"severity": "warning", "chapter": int, "dimension": "alignment", "description": str, "suggestion": str}}],
  "highlights": [str],
  "reasoning": str
}}

【待审核章节】
{current_chapters_text}
【章节计划】
{chapter_plan}
【已完成章节摘要】
{completed_summaries}
"""


_QUALITY_AGENT_PROMPT = """你是一个中文小说章节质量审核专家，评估写作水平。

【你的职责】
评估章节的写作质量，包括：
- 叙事是否流畅
- 语言是否精准
- 情感是否真实
- 文风是否冷静克制

【评分标准】（0-100）
- 90-100：质量优秀，文学性强
- 70-89：质量良好
- 50-69：质量一般
- 50以下：质量较差

【输出要求】
严格返回 JSON：
{{
  "score": int,
  "issues": [{{"severity": "critical", "chapter": int, "dimension": "quality", "description": str, "suggestion": str}}],
  "warnings": [{{"severity": "warning", "chapter": int, "dimension": "quality", "description": str, "suggestion": str}}],
  "highlights": [str],
  "reasoning": str
}}

【待审核章节】
{current_chapters_text}
【字数要求】
每章 250-450 字
"""


_COHESION_AGENT_PROMPT = """你是一个中文小说章节连贯性审核专家，检查章节衔接。

【你的职责】
评估章节之间的衔接是否自然，包括：
- 章节之间的过渡是否流畅
- 情节发展是否连贯
- 人物状态变化是否有逻辑

【评分标准】（0-100）
- 90-100：连贯性优秀，衔接自然
- 70-89：连贯性良好
- 50-69：连贯性一般
- 50以下：衔接生硬

【输出要求】
严格返回 JSON：
{{
  "score": int,
  "issues": [{{"severity": "critical", "chapter": int, "dimension": "cohesion", "description": str, "suggestion": str}}],
  "warnings": [{{"severity": "warning", "chapter": int, "dimension": "cohesion", "description": str, "suggestion": str}}],
  "highlights": [str],
  "reasoning": str
}}

【待审核章节】
{current_chapters_text}
【已完成章节摘要】
{completed_summaries}
"""


# ─────────────────────────────────────────────
# Prompt 模板 — 验证审核子 Agent
# ─────────────────────────────────────────────


_SEVERITY_JUDGE_PROMPT = """你是一个中文小说问题严重度判断专家。

【你的职责】
分析全文一致性验证报告中的问题，判断每个问题的严重程度，并评估整体风险。

【评分标准】（0-100）
- 90-100：无问题或轻微问题
- 70-89：有少量可忽略的问题
- 50-69：存在需要修复的问题
- 50以下：存在严重影响阅读的问题

【输出要求】
严格返回 JSON：
{{
  "score": int,
  "critical_issues": [{{"severity": "critical", "location": str, "description": str, "suggestion": str}}],
  "warnings": [{{"severity": "warning", "description": str, "suggestion": str}}],
  "reasoning": str
}}

【验证报告】
{verification_report}
"""


_FIX_PLANNER_PROMPT = """你是一个中文小说修复规划专家。

【你的职责】
根据验证报告中的问题，规划修复范围和优先级。

【输出要求】
严格返回 JSON：
{{
  "revision_scope": str | null,
  "revision_priority": [{{"chapter": int | null, "issue_type": str, "priority": str}}],
  "reasoning": str
}}

【验证报告】
{verification_report}
"""


# ─────────────────────────────────────────────
# Prompt 模板 — 综合决策 Agent
# ─────────────────────────────────────────────


_OUTLINE_SYNTHESIS_PROMPT = """你是一个小说审核综合决策专家。

【任务】
综合多个专家的审核意见，得出最终审核决策。

【子 Agent 审核结果】
{sub_agents_json}

【审核策略】
- 模式：{mode}
- 阈值：{threshold}
- 严格度：{strictness}

【决策规则】
1. 如果任一子 Agent 发现 critical 问题 → 整体不通过
2. 加权平均分 >= 阈值 → 通过
3. 有 critical 问题时 → 升级人工
4. 评分低于阈值 70% → 升级人工

【输出要求】
严格返回 JSON：
{{
  "overall_score": float,
  "approved": bool,
  "auto_escalated": bool,
  "critical_issues": [{{"severity": "critical", "dimension": str, "description": str, "suggestion": str}}],
  "warnings": [{{"severity": "warning", "dimension": str, "description": str, "suggestion": str}}],
  "highlights": [str],
  "comment": str,
  "reasoning": str
}}
"""


_CHAPTER_SYNTHESIS_PROMPT = """你是一个小说章节审核综合决策专家。

【任务】
综合多个专家的审核意见，得出最终审核决策。

【子 Agent 审核结果】
{sub_agents_json}

【审核策略】
- 模式：{mode}
- 阈值：{threshold}
- 严格度：{strictness}

【决策规则】
1. 任一章节有 critical 问题 → 整体不通过
2. 加权平均分 >= 阈值 → 通过
3. 有 critical 问题时 → 升级人工
4. 评分低于阈值 70% → 升级人工

【输出要求】
严格返回 JSON：
{{
  "overall_score": float,
  "approved": bool,
  "auto_escalated": bool,
  "critical_issues": [{{"severity": "critical", "chapter": int, "dimension": str, "description": str, "suggestion": str}}],
  "warnings": [{{"severity": "warning", "chapter": int, "dimension": str, "description": str, "suggestion": str}}],
  "highlights": [str],
  "comment": str,
  "reasoning": str,
  "revision_scope": str | null
}}
"""


_VERIFICATION_SYNTHESIS_PROMPT = """你是一个小说验证审核综合决策专家。

【任务】
综合多个专家的审核意见，得出最终审核决策。

【子 Agent 审核结果】
{sub_agents_json}

【审核策略】
- 模式：{mode}
- 阈值：{threshold}
- 严格度：{strictness}

【决策规则】
1. 有 critical 问题 → 整体不通过，必须修复
2. 评分 >= 80 且无 critical → 通过
3. 有 critical 问题 → 升级人工
4. 评分 < 60 → 升级人工

【输出要求】
严格返回 JSON：
{{
  "overall_score": float,
  "approved": bool,
  "auto_escalated": bool,
  "critical_issues": [{{"severity": "critical", "location": str, "description": str, "suggestion": str}}],
  "warnings": [{{"severity": "warning", "description": str, "suggestion": str}}],
  "comment": str,
  "reasoning": str,
  "revision_scope": str | null
}}
"""


# ─────────────────────────────────────────────
# 子 Agent 规格注册表
# ─────────────────────────────────────────────


def _get_outline_sub_agents() -> list[SubAgentSpec]:
    return [
        SubAgentSpec(
            agent_id="outline-structure",
            agent_name="结构分析师",
            role="structure",
            dimension="结构完整性",
            weight=0.35,
            prompt_template=_STRUCTURE_AGENT_PROMPT,
        ),
        SubAgentSpec(
            agent_id="outline-consistency",
            agent_name="一致性分析师",
            role="consistency",
            dimension="人物与世界观一致性",
            weight=0.35,
            prompt_template=_CONSISTENCY_AGENT_PROMPT,
        ),
        SubAgentSpec(
            agent_id="outline-creativity",
            agent_name="创意评估师",
            role="creativity",
            dimension="创意与价值",
            weight=0.30,
            prompt_template=_CREATIVITY_AGENT_PROMPT,
        ),
    ]


def _get_chapter_sub_agents() -> list[SubAgentSpec]:
    return [
        SubAgentSpec(
            agent_id="chapter-alignment",
            agent_name="大纲对齐审核师",
            role="alignment",
            dimension="大纲对齐度",
            weight=0.40,
            prompt_template=_ALIGNMENT_AGENT_PROMPT,
        ),
        SubAgentSpec(
            agent_id="chapter-quality",
            agent_name="写作质量审核师",
            role="quality",
            dimension="内容质量",
            weight=0.30,
            prompt_template=_QUALITY_AGENT_PROMPT,
        ),
        SubAgentSpec(
            agent_id="chapter-cohesion",
            agent_name="章节连贯性审核师",
            role="cohesion",
            dimension="章节衔接",
            weight=0.30,
            prompt_template=_COHESION_AGENT_PROMPT,
        ),
    ]


def _get_verification_sub_agents() -> list[SubAgentSpec]:
    return [
        SubAgentSpec(
            agent_id="verify-severity",
            agent_name="严重度评判师",
            role="severity",
            dimension="问题严重度",
            weight=0.60,
            prompt_template=_SEVERITY_JUDGE_PROMPT,
        ),
        SubAgentSpec(
            agent_id="verify-fix-planner",
            agent_name="修复规划师",
            role="fix",
            dimension="修复规划",
            weight=0.40,
            prompt_template=_FIX_PLANNER_PROMPT,
        ),
    ]


# ─────────────────────────────────────────────
# AutoReviewManager
# ─────────────────────────────────────────────


class AutoReviewManager:
    """
    自动审核编排器

    职责：
    - 根据 review_type 分发到对应的审核 Auditor
    - 管理多子 Agent 并行执行
    - 调用 SynthesisAgent 综合决策
    - 支持升级机制
    """

    def __init__(
        self,
        gateway_client: OpenAICompatibleGatewayClient | None = None,
        default_model: str = "MiniMax-M2.7-highspeed",
        max_workers: int = 3,
    ) -> None:
        self.gateway_client = gateway_client
        self.default_model = default_model
        self.max_workers = max_workers
        self._lock = threading.Lock()

    def review(self, payload: ReviewPayload, policy: AutoReviewPolicy) -> ReviewDecision:
        """
        执行自动审核，返回审核决策。
        """
        review_type = payload.type

        try:
            if review_type == "outline_review":
                return self._review_outline_multi(payload, policy)
            elif review_type == "chapter_pair_review":
                return self._review_chapter_pair_multi(payload, policy)
            elif review_type == "verification_review":
                return self._review_verification_multi(payload, policy)
            else:
                return self._fallback_decision(f"未知审核类型: {review_type}")
        except GatewayClientError:
            # gateway_client 未配置时的降级处理
            return self._fallback_decision("自动审核服务未配置 gateway_client")
        except Exception as e:
            return self._fallback_decision(f"自动审核执行异常: {e}")

    def _run_sub_agent(
        self,
        spec: SubAgentSpec,
        prompt_text: str,
        model: str,
    ) -> SubAgentOutput:
        """执行单个子 Agent"""
        started_at = _utc_now()
        try:
            result_json = self._call_llm(prompt_text, model)
            parsed = json.loads(result_json)
            return SubAgentOutput(
                agent_id=spec.agent_id,
                agent_name=spec.agent_name,
                role=spec.role,
                dimension=spec.dimension,
                score=float(parsed.get("score", 0)),
                issues=parsed.get("issues") or [],
                warnings=parsed.get("warnings") or [],
                highlights=parsed.get("highlights") or [],
                reasoning=parsed.get("reasoning") or "",
                raw_response=parsed,
                started_at=started_at,
                completed_at=_utc_now(),
            )
        except Exception as e:
            return SubAgentOutput(
                agent_id=spec.agent_id,
                agent_name=spec.agent_name,
                role=spec.role,
                dimension=spec.dimension,
                error=str(e),
                started_at=started_at,
                completed_at=_utc_now(),
            )

    def _run_sub_agents_parallel(
        self,
        specs: list[SubAgentSpec],
        prompt_factory: callable,
        model: str,
    ) -> list[SubAgentOutput]:
        """并行执行多个子 Agent（使用线程池）"""
        if not specs:
            return []

        max_workers = min(len(specs), self.max_workers)
        outputs: list[SubAgentOutput] = []
        output_lock = threading.Lock()

        def _worker(spec: SubAgentSpec) -> SubAgentOutput:
            prompt_text = prompt_factory(spec)
            return self._run_sub_agent(spec, prompt_text, model)

        # 使用线程池并行执行所有子 Agent
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # 提交所有任务
            future_to_spec = {executor.submit(_worker, spec): spec for spec in specs}
            # 按提交顺序收集结果
            results: list[SubAgentOutput] = []
            for future in as_completed(future_to_spec):
                try:
                    result = future.result()
                    results.append(result)
                except Exception as e:
                    spec = future_to_spec[future]
                    results.append(
                        SubAgentOutput(
                            agent_id=spec.agent_id,
                            agent_name=spec.agent_name,
                            role=spec.role,
                            dimension=spec.dimension,
                            error=f"并行执行异常: {e}",
                        )
                    )

        # 按原始顺序排列结果
        spec_ids = [spec.agent_id for spec in specs]
        output_map = {r.agent_id: r for r in results}
        outputs = [output_map[sid] for sid in spec_ids if sid in output_map]
        return outputs

    def _review_outline_multi(
        self, payload: ReviewPayload, policy: AutoReviewPolicy
    ) -> ReviewDecision:
        """大纲多 Agent 审核"""
        story_plan = payload.story_plan
        if story_plan is None:
            return self._fallback_decision("大纲数据为空")

        specs = _get_outline_sub_agents()

        def build_prompt(spec: SubAgentSpec) -> str:
            return spec.prompt_template.format(
                mode=getattr(payload, "_mode", ""),
                working_title=story_plan.working_title,
                logline=story_plan.logline,
                world_notes="\n".join(story_plan.world_notes) if story_plan.world_notes else "无",
                character_notes="\n".join(story_plan.character_notes) if story_plan.character_notes else "无",
                chapter_plan="\n".join(
                    f"第{ch.number}章: {ch.title} - 目标: {ch.goal}"
                    for ch in (story_plan.chapter_plan or [])
                ),
                requested_target_words=getattr(payload, "_requested_target_words", getattr(payload, "_target_words", "")),
                user_prompt=getattr(payload, "_user_prompt", ""),
                genre=getattr(payload, "_genre", ""),
                style=getattr(payload, "_style", ""),
                target_words=getattr(payload, "_target_words", ""),
            )

        outputs = self._run_sub_agents_parallel(specs, build_prompt, policy.auditor_model)

        # 合成子 Agent 结果
        sub_agents_json = json.dumps(
            [
                {
                    "agent_name": o.agent_name,
                    "role": o.role,
                    "score": o.score,
                    "issues": o.issues,
                    "warnings": o.warnings,
                    "highlights": o.highlights,
                    "reasoning": o.reasoning,
                    "error": o.error,
                }
                for o in outputs
            ],
            ensure_ascii=False,
        )

        # 调用综合 Agent
        threshold = policy.get_pass_threshold("outline_review")
        synthesis_prompt = _OUTLINE_SYNTHESIS_PROMPT.format(
            sub_agents_json=sub_agents_json,
            mode=policy.mode.value,
            threshold=threshold,
            strictness=policy.strictness.value,
        )
        synthesis_result = self._call_llm(synthesis_prompt, policy.synthesis_model)

        try:
            parsed = json.loads(synthesis_result)
        except json.JSONDecodeError:
            return self._fallback_decision(f"综合 Agent 返回格式错误: {synthesis_result[:200]}")

        return self._build_decision(
            parsed=parsed,
            outputs=outputs,
            review_type="outline_review",
            policy=policy,
            pass_threshold=threshold,
        )

    def _review_chapter_pair_multi(
        self, payload: ReviewPayload, policy: AutoReviewPolicy
    ) -> ReviewDecision:
        """章节对多 Agent 审核"""
        chapters = payload.chapter_pair or []
        story_plan = payload.story_plan

        if not chapters:
            return self._fallback_decision("章节数据为空")

        current_chapters_text = "\n\n".join(
            f"=== 第{ch.get('number', 0) if isinstance(ch, dict) else ch.number}章: "
            f"{ch.get('title', '') if isinstance(ch, dict) else ch.title} ===\n"
            f"{ch.get('content', '') if isinstance(ch, dict) else ch.content}"
            for ch in chapters
        )

        chapter_plan = []
        if story_plan:
            chapter_plan = [
                f"第{ch.number}章: {ch.title} - 目标: {ch.goal}"
                for ch in (story_plan.chapter_plan or [])
            ]

        completed_summaries = getattr(payload, "_completed_summaries", [])

        specs = _get_chapter_sub_agents()

        def build_prompt(spec: SubAgentSpec) -> str:
            return spec.prompt_template.format(
                current_chapters_text=current_chapters_text,
                chapter_plan="\n".join(chapter_plan) if chapter_plan else "无",
                completed_summaries="\n".join(completed_summaries) if completed_summaries else "无",
            )

        outputs = self._run_sub_agents_parallel(specs, build_prompt, policy.auditor_model)

        sub_agents_json = json.dumps(
            [
                {
                    "agent_name": o.agent_name,
                    "role": o.role,
                    "score": o.score,
                    "issues": o.issues,
                    "warnings": o.warnings,
                    "highlights": o.highlights,
                    "reasoning": o.reasoning,
                    "error": o.error,
                }
                for o in outputs
            ],
            ensure_ascii=False,
        )

        threshold = policy.get_pass_threshold("chapter_pair_review")
        synthesis_prompt = _CHAPTER_SYNTHESIS_PROMPT.format(
            sub_agents_json=sub_agents_json,
            mode=policy.mode.value,
            threshold=threshold,
            strictness=policy.strictness.value,
        )
        synthesis_result = self._call_llm(synthesis_prompt, policy.synthesis_model)

        try:
            parsed = json.loads(synthesis_result)
        except json.JSONDecodeError:
            return self._fallback_decision(f"综合 Agent 返回格式错误: {synthesis_result[:200]}")

        return self._build_decision(
            parsed=parsed,
            outputs=outputs,
            review_type="chapter_pair_review",
            policy=policy,
            pass_threshold=threshold,
        )

    def _review_verification_multi(
        self, payload: ReviewPayload, policy: AutoReviewPolicy
    ) -> ReviewDecision:
        """验证多 Agent 审核"""
        report = payload.verification_report or {}
        report_text = json.dumps(report, ensure_ascii=False, indent=2)[:4000]

        specs = _get_verification_sub_agents()

        def build_prompt(spec: SubAgentSpec) -> str:
            return spec.prompt_template.format(verification_report=report_text)

        outputs = self._run_sub_agents_parallel(specs, build_prompt, policy.auditor_model)

        sub_agents_json = json.dumps(
            [
                {
                    "agent_name": o.agent_name,
                    "role": o.role,
                    "score": o.score,
                    "issues": o.issues,
                    "warnings": o.warnings,
                    "highlights": o.highlights,
                    "reasoning": o.reasoning,
                    "error": o.error,
                }
                for o in outputs
            ],
            ensure_ascii=False,
        )

        threshold = policy.get_pass_threshold("verification_review")
        synthesis_prompt = _VERIFICATION_SYNTHESIS_PROMPT.format(
            sub_agents_json=sub_agents_json,
            mode=policy.mode.value,
            threshold=threshold,
            strictness=policy.strictness.value,
        )
        synthesis_result = self._call_llm(synthesis_prompt, policy.synthesis_model)

        try:
            parsed = json.loads(synthesis_result)
        except json.JSONDecodeError:
            return self._fallback_decision(f"综合 Agent 返回格式错误: {synthesis_result[:200]}")

        return self._build_decision(
            parsed=parsed,
            outputs=outputs,
            review_type="verification_review",
            policy=policy,
            pass_threshold=threshold,
        )

    def _build_decision(
        self,
        parsed: dict[str, Any],
        outputs: list[SubAgentOutput],
        review_type: str,
        policy: AutoReviewPolicy,
        pass_threshold: float,
    ) -> ReviewDecision:
        """构建最终审核决策"""
        base_score = float(parsed.get("overall_score", 60))
        multiplier = _STRICTNESS_MULTIPLIERS.get(policy.strictness, 1.0)
        adjusted_score = min(100, base_score * multiplier)

        approved = bool(parsed.get("approved", adjusted_score >= pass_threshold))
        auto_escalated = bool(parsed.get("auto_escalated", False))

        critical_issues = parsed.get("critical_issues") or []
        warnings = parsed.get("warnings") or []
        highlights = parsed.get("highlights") or []
        comment = parsed.get("comment") or ""
        reasoning = parsed.get("reasoning") or ""
        revision_scope = parsed.get("revision_scope")

        # 升级判断
        if policy.should_auto_escalate_on_critical(review_type) and len(critical_issues) > 0:
            auto_escalated = True
        if policy.auto_escalate_on_low_score and adjusted_score < pass_threshold * 0.7:
            auto_escalated = True

        # 放宽章节审核：当章节评分已过线，且该阶段不要求因 critical 直接升级时，继续正文生成。
        if (
            review_type in {"outline_review", "chapter_pair_review"}
            and not policy.should_auto_escalate_on_critical(review_type)
            and adjusted_score >= pass_threshold
        ):
            approved = True
            auto_escalated = False

        # 构建审核意见
        if not approved and not comment:
            comment = self._build_revision_comment(
                comment=comment,
                critical_issues=critical_issues,
                warnings=warnings,
                score=adjusted_score,
            )

        # 构建 Agent 结果追踪
        agent_trace = [o.to_agent_result() for o in outputs]

        return ReviewDecision(
            approved=approved,
            comment=comment,
            reasoning=reasoning
            or f"多 Agent 审核评分 {adjusted_score:.1f}（阈值 {pass_threshold:.1f}），"
            + (f"发现 {len(critical_issues)} 个严重问题" if critical_issues else "无严重问题"),
            agent_trace=agent_trace,
            auto_escalated=auto_escalated,
            overall_score=adjusted_score,
            critical_issues=critical_issues,
            warnings=warnings,
            suggestions=highlights,
            revision_needed=not approved,
            revision_scope=revision_scope if not approved else None,
        )

    def _call_llm(self, prompt: str, model: str | None) -> str:
        """调用 LLM（流式），同时支持思考链透传。"""
        if self.gateway_client is None:
            raise GatewayClientError(
                "AutoReviewManager 需要有效的 gateway_client 才能执行自动审核。"
            )
        messages = [
            {"role": "system", "content": "你是一个中文小说质量审核专家，请严格返回 JSON 格式的审核结果，不要输出额外解释。"},
            {"role": "user", "content": prompt},
        ]
        attempt_messages = messages
        for attempt in range(2):
            try:
                # 流式调用，累积 content 后解析 JSON
                full_content = ""
                for chunk in self.gateway_client.complete_stream_sync(
                    attempt_messages,
                    model=model or self.default_model,
                ):
                    if chunk.content:
                        full_content += chunk.content
                # 解析 JSON
                cleaned = self.gateway_client._strip_markdown_fences(full_content)
                try:
                    response = json.loads(cleaned)
                except json.JSONDecodeError:
                    extracted = self.gateway_client._extract_first_json_value(cleaned)
                    if extracted is not None:
                        response = extracted
                    else:
                        raise GatewayClientError(f"自动审核返回的 JSON 无法解析：{full_content[:240]}")
                return json.dumps(response, ensure_ascii=False)
            except GatewayClientError:
                if attempt == 1:
                    raise
                attempt_messages = [dict(item) for item in messages] + [
                    {
                        "role": "user",
                        "content": (
                            "上一次返回结果不是可解析的目标 JSON。"
                            "请重新输出一个完整、可解析的 JSON 对象。"
                            "不要输出 Markdown 代码围栏，不要解释，不要补充说明，只返回最终 JSON 对象。"
                        ),
                    }
                ]
        raise GatewayClientError("自动审核调用失败：重试后仍未拿到有效 JSON。")

    def _build_revision_comment(
        self,
        comment: str,
        critical_issues: list[dict[str, Any]],
        warnings: list[dict[str, Any]],
        score: float,
    ) -> str:
        """构建修订意见"""
        parts = []
        if comment:
            parts.append(comment)
        if critical_issues:
            parts.append(f"\n【严重问题】（共 {len(critical_issues)} 项）：")
            for issue in critical_issues:
                parts.append(
                    f"- [{issue.get('dimension', 'unknown')}] {issue.get('description', '')} "
                    f"→ 建议：{issue.get('suggestion', '请修订')}"
                )
        if warnings:
            parts.append(f"\n【警告项】（共 {len(warnings)} 项）：")
            for warning in warnings[:5]:
                parts.append(
                    f"- {warning.get('description', '')} "
                    f"→ 建议：{warning.get('suggestion', '建议改进')}"
                )
        parts.append(f"\n当前评分：{score:.1f} 分，请根据以上意见进行修订。")
        return "\n".join(parts)

    def _fallback_decision(self, reason: str) -> ReviewDecision:
        """降级决策"""
        agent_result = AgentResult(
            agent_name="Fallback",
            role="error",
            status="failed",
            error=reason,
            started_at=_utc_now(),
            completed_at=_utc_now(),
        )
        return ReviewDecision(
            approved=False,
            comment=f"自动审核失败：{reason}。请人工介入审核。",
            reasoning=reason,
            agent_trace=[agent_result],
            auto_escalated=True,
            overall_score=0.0,
        )
