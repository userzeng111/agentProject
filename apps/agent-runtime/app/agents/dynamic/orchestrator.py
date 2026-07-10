"""
任务编排执行器

按 DAG 拓扑顺序执行 Agent，支持：
- 同层并行（ThreadPoolExecutor）
- 层间串行（按依赖顺序）
- 综合 Agent 自动汇总下层结果
- 失败重试和错误隔离
"""

from __future__ import annotations

import json
from app.observability import get_logger
from datetime import datetime, timezone
from typing import Any
from concurrent.futures import ThreadPoolExecutor, as_completed

from app.agents.dynamic.factory import AgentFactory
from app.agents.dynamic.master import MasterAgent
from app.agents.dynamic.models import (
    DynamicAgent,
    OrchestrationResult,
    TaskDAG,
    TaskExecutionResult,
)
from app.agents.dynamic.planner import PlannerAgent
from app.agents.dynamic.registry import AgentRegistry
from app.llm.gateway_client import OpenAICompatibleGatewayClient

logger = get_logger(__name__)


class TaskOrchestrator:
    """
    任务编排执行器 — 动态 Agent 系统的核心入口。

    完整流程：
    1. Master Agent 分析任务 → 生成 AgentBlueprint[]
    2. AgentFactory 创建 DynamicAgent 实例
    3. Planner Agent 规划 → 生成 TaskDAG
    4. 按 DAG 执行：同层并行、层间串行
    5. 汇总结果返回 OrchestrationResult
    """

    def __init__(
        self,
        gateway_client: OpenAICompatibleGatewayClient,
        max_workers: int = 4,
    ) -> None:
        self._gateway_client = gateway_client
        self._max_workers = max_workers

        # 初始化子系统
        self._master = MasterAgent(
            gateway_client=gateway_client,
        )
        self._factory = AgentFactory(
            gateway_client=gateway_client,
        )
        self._planner = PlannerAgent(
            gateway_client=gateway_client,
        )
        self._registry = AgentRegistry()

    def execute(
        self,
        task_type: str,
        task_description: str,
        task_context: dict[str, Any] | None = None,
        model: str | None = None,
    ) -> OrchestrationResult:
        """
        执行完整的动态编排流程。

        Args:
            task_type: 任务类型
            task_description: 任务描述
            task_context: 上下文变量（题材、风格、内容等）
            model: 使用的模型

        Returns:
            OrchestrationResult 编排汇总结果
        """
        started_at = datetime.now(timezone.utc)
        use_model = str(model or "").strip()
        if not use_model:
            raise ValueError("动态编排缺少显式模型，调用已拒绝。")
        task_context = task_context or {}

        logger.info("动态编排开始 — 任务类型: %s", task_type)

        try:
            # ── 步骤 1: Master Agent 分析任务，生成蓝图 ──
            logger.debug("[步骤 1/4] Master Agent 分析任务...")
            blueprints = self._master.analyze_task(
                task_type=task_type,
                task_description=task_description,
                context=task_context,
                model=use_model,
            )

            if not blueprints:
                return self._error_result("Master Agent 未能生成任何 Agent 蓝图", started_at)

            logger.info("Master Agent 生成 %d 个 Agent 蓝图", len(blueprints))

            # ── 步骤 2: AgentFactory 创建实例 ──
            logger.debug("[步骤 2/4] AgentFactory 创建 Agent 实例...")
            agents = self._factory.create_batch(blueprints)
            self._registry.register_batch(agents)

            # ── 步骤 3: Planner Agent 规划 DAG ──
            logger.debug("[步骤 3/4] Planner Agent 规划执行 DAG...")
            dag = self._planner.plan(
                blueprints=blueprints,
                task_context=task_context,
                model=use_model,
            )

            # ── 步骤 4: 按 DAG 执行 ──
            logger.debug("[步骤 4/4] 按 DAG 执行 Agent...")
            results = self._execute_dag(agents, dag, task_context, use_model)

            # ── 汇总结果 ──
            completed_at = datetime.now(timezone.utc)
            total_ms = int((completed_at - started_at).total_seconds() * 1000)

            # 分离综合 Agent 和分析 Agent 的结果
            synthesis_result = None
            agent_results: list[TaskExecutionResult] = []
            for r in results:
                if r.execution_kind == "synthesis":
                    synthesis_result = r
                    continue
                agent_results.append(r)

            # 如果没有综合 Agent，取最后执行的结果
            if synthesis_result is None and results:
                synthesis_result = results[-1]

            # 计算整体评分
            overall_score = self._calculate_overall_score(results)
            self._backfill_synthesis_score(synthesis_result, overall_score)

            succeeded = sum(1 for r in results if r.is_success)
            failed = sum(1 for r in results if not r.is_success)

            orchestration_result = OrchestrationResult(
                task_description=task_description,
                agents_created=len(agents),
                agents_succeeded=succeeded,
                agents_failed=failed,
                agent_results=agent_results,
                synthesis_result=synthesis_result,
                overall_score=overall_score,
                dag_snapshot=dag,
                blueprint_snapshot=blueprints,
                total_duration_ms=total_ms,
            )

            logger.info(
                "动态编排完成 — 创建: %d，成功: %d，失败: %d，评分: %.1f，耗时: %dms",
                len(agents), succeeded, failed, overall_score, total_ms,
            )

            return orchestration_result

        except Exception as e:
            logger.error("动态编排异常: %s", e, exc_info=True)
            return self._error_result(f"编排执行异常: {e}", started_at)

    def _execute_dag(
        self,
        agents: list[DynamicAgent],
        dag: TaskDAG,
        context: dict[str, Any],
        model: str,
    ) -> list[TaskExecutionResult]:
        """按 DAG 层级执行 Agent，同层并行、层间串行。"""
        # blueprint.agent_id -> DynamicAgent 映射
        agent_map = {a.blueprint.agent_id: a for a in agents}
        all_results: list[TaskExecutionResult] = []

        # 上下文变量累积（综合 Agent 需要下层结果）
        accumulated_context = dict(context)

        # 兜底：为章节内容提供多个常见变量名，避免 MasterAgent 生成的模板变量名与上下文不匹配
        chapters_text = accumulated_context.get("current_chapters_text")
        if chapters_text:
            for alias in ("chapter_content", "chapters", "content", "text", "chapter_text", "chapter_pair"):
                accumulated_context.setdefault(alias, chapters_text)

        for layer_idx, layer_agent_ids in enumerate(dag.execution_layers):
            logger.info(
                "执行第 %d 层（%d 个 Agent）: %s",
                layer_idx,
                len(layer_agent_ids),
                layer_agent_ids,
            )

            # 获取本层的 DynamicAgent
            layer_agents: list[DynamicAgent] = []
            for agent_id in layer_agent_ids:
                agent = agent_map.get(agent_id)
                if agent is None:
                    logger.warning("DAG 层级引用了不存在的 agent_id: %s，跳过", agent_id)
                    continue
                layer_agents.append(agent)

            if not layer_agents:
                continue

            # 判断是否需要并行
            if len(layer_agents) == 1:
                result = self._execute_single_agent(layer_agents[0], accumulated_context, model)
                all_results.append(result)
            else:
                layer_results = self._execute_parallel(layer_agents, accumulated_context, model)
                all_results.extend(layer_results)

            # 将本层结果注入上下文（供下一层综合 Agent 使用）
            sub_agents_json = json.dumps(
                [
                    {
                        "agent_name": r.agent_name,
                        "role": r.role,
                        "score": r.score,
                        "issues": r.issues,
                        "warnings": r.warnings,
                        "highlights": r.highlights,
                        "reasoning": r.reasoning,
                        "error": r.error,
                    }
                    for r in all_results
                ],
                ensure_ascii=False,
            )
            accumulated_context["sub_agents_json"] = sub_agents_json

        return all_results

    def _execute_single_agent(
        self,
        agent: DynamicAgent,
        context: dict[str, Any],
        model: str,
    ) -> TaskExecutionResult:
        """执行单个 Agent。"""
        bp = agent.blueprint
        variables = dict(context)
        if bp.is_synthesis and "sub_agents_json" not in variables:
            variables["sub_agents_json"] = "暂无子 Agent 结果"
        return self._factory.execute_agent(agent, variables, model)

    def _execute_parallel(
        self,
        agents: list[DynamicAgent],
        context: dict[str, Any],
        model: str,
    ) -> list[TaskExecutionResult]:
        """并行执行多个 Agent（ThreadPoolExecutor）。"""
        max_workers = min(len(agents), self._max_workers)
        results: list[TaskExecutionResult] = []

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_agent = {
                executor.submit(self._execute_single_agent, agent, context, model): agent
                for agent in agents
            }

            for future in as_completed(future_to_agent):
                agent = future_to_agent[future]
                try:
                    result = future.result()
                    results.append(result)
                except Exception as e:
                    logger.error("并行执行 Agent %s 异常: %s", agent.blueprint.agent_name, e)
                    results.append(TaskExecutionResult(
                        agent_id=agent.id,
                        agent_name=agent.blueprint.agent_name,
                        role=agent.blueprint.role,
                        dimension=agent.blueprint.dimension,
                        weight=agent.blueprint.weight,
                        execution_kind=agent.blueprint.execution_kind,
                        created_by=agent.blueprint.created_by,
                        invocation_kind=agent.blueprint.invocation_kind,
                        error=str(e),
                        started_at=datetime.now(timezone.utc),
                        completed_at=datetime.now(timezone.utc),
                    ))

        return results

    @staticmethod
    def _calculate_overall_score(results: list[TaskExecutionResult]) -> float:
        """计算加权平均整体评分。"""
        # 分离分析型 Agent 和综合 Agent
        analysis_results = [r for r in results if r.is_success and r.execution_kind != "synthesis"]
        synthesis_results = [r for r in results if r.is_success and r.execution_kind == "synthesis"]

        # 如果有综合 Agent 的有效评分（>0），直接使用
        if synthesis_results:
            synth_score = max(r.score for r in synthesis_results)
            if synth_score > 0:
                return synth_score
            # 综合 Agent 返回 0 分但子 Agent 有分数时，回退到加权平均
            if analysis_results:
                logger.warning(
                    "综合 Agent 返回 0 分（子 Agent 有正常分数），回退到加权平均: %s",
                    [(r.agent_name, r.score, r.weight) for r in analysis_results],
                )

        # 否则使用加权平均
        if not analysis_results:
            return 0.0

        total_weight = sum(r.weight for r in analysis_results)
        if total_weight == 0:
            return 0.0

        weighted_sum = sum(r.score * r.weight for r in analysis_results)
        return min(100.0, weighted_sum / total_weight)

    @staticmethod
    def _backfill_synthesis_score(
        synthesis_result: TaskExecutionResult | None,
        overall_score: float,
    ) -> None:
        """当综合 Agent 缺少显式评分时，用最终整体评分回填综合结果。"""
        if synthesis_result is None:
            return
        if synthesis_result.score > 0 or overall_score <= 0:
            return

        synthesis_result.score = overall_score
        if isinstance(synthesis_result.raw_response, dict):
            synthesis_result.raw_response.setdefault("score", overall_score)
            synthesis_result.raw_response.setdefault("overall_score", overall_score)

    @staticmethod
    def _error_result(reason: str, started_at: datetime) -> OrchestrationResult:
        """构建错误结果。"""
        completed_at = datetime.now(timezone.utc)
        return OrchestrationResult(
            task_description=reason,
            agents_failed=1,
            overall_score=0.0,
            total_duration_ms=int((completed_at - started_at).total_seconds() * 1000),
        )

    @property
    def registry(self) -> AgentRegistry:
        """获取 Agent 注册表（用于查看已创建的 Agent）。"""
        return self._registry
