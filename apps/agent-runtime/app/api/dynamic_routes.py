"""
动态 Agent 编排 API（v2 并行路由）

与现有 v1 路由并行运行，用于对比验证。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.agents.dynamic.models import OrchestrationResult
from app.agents.dynamic.orchestrator import TaskOrchestrator
from app.llm.gateway_client import GatewayClientError

logger = logging.getLogger(__name__)


class DynamicOrchestrationRequest(BaseModel):
    """动态编排请求。"""

    task_type: str = Field(..., description="任务类型（如 outline_review, chapter_review, custom）")
    task_description: str = Field(..., description="任务描述")
    task_context: dict[str, Any] = Field(default_factory=dict, description="任务上下文变量")
    model: str | None = Field(default=None, description="使用的模型（默认系统配置）")
    max_workers: int = Field(default=4, description="最大并行 Agent 数")


class DynamicOrchestrationResponse(BaseModel):
    """动态编排响应。"""

    success: bool
    orchestration_id: str = ""
    agents_created: int = 0
    agents_succeeded: int = 0
    agents_failed: int = 0
    overall_score: float = 0.0
    overall_approved: bool = False
    total_duration_ms: int = 0
    agent_results: list[dict[str, Any]] = Field(default_factory=list)
    synthesis_result: dict[str, Any] | None = None
    dag_snapshot: dict[str, Any] | None = None
    blueprint_snapshot: list[dict[str, Any]] = Field(default_factory=list)
    error: str | None = None


def build_dynamic_router(gateway_client=None, default_model: str = "") -> APIRouter:
    """构建动态编排 API 路由。"""
    router = APIRouter(prefix="/dynamic", tags=["动态 Agent 编排"])

    @router.get("/health")
    def dynamic_health() -> dict[str, str]:
        """动态编排模块健康检查。"""
        if gateway_client is None:
            return {"status": "degraded", "message": "模型网关未配置"}
        return {"status": "ok", "module": "dynamic_agent_orchestration"}

    @router.post("/orchestrate", response_model=DynamicOrchestrationResponse)
    async def orchestrate(request: DynamicOrchestrationRequest) -> DynamicOrchestrationResponse:
        """
        执行动态 Agent 编排。

        完整流程：
        1. Master Agent 通过 LLM 分析任务，动态生成 Agent 蓝图
        2. AgentFactory 实例化 Agent
        3. Planner Agent 通过 LLM 规划执行 DAG
        4. TaskOrchestrator 按 DAG 并行/串行执行
        5. 汇总返回结果
        """
        if gateway_client is None:
            raise HTTPException(
                status_code=503,
                detail="模型网关未配置，请检查 .env 中的 LLM_BASE_URL 与 LLM_API_KEY。",
            )

        try:
            orchestrator = TaskOrchestrator(
                gateway_client=gateway_client,
                default_model=default_model,
                max_workers=request.max_workers,
            )

            # 使用 asyncio.to_thread 避免同步编排器阻塞事件循环
            result: OrchestrationResult = await asyncio.to_thread(
                orchestrator.execute,
                task_type=request.task_type,
                task_description=request.task_description,
                task_context=request.task_context,
                model=request.model,
            )

            # 构建响应
            response = DynamicOrchestrationResponse(
                success=True,
                orchestration_id=result.orchestration_id,
                agents_created=result.agents_created,
                agents_succeeded=result.agents_succeeded,
                agents_failed=result.agents_failed,
                overall_score=result.overall_score,
                overall_approved=result.overall_approved,
                total_duration_ms=result.total_duration_ms,
                agent_results=[
                    {
                        "agent_id": r.agent_id,
                        "agent_name": r.agent_name,
                        "role": r.role,
                        "dimension": r.dimension,
                        "weight": r.weight,
                        "score": r.score,
                        "issues": r.issues,
                        "warnings": r.warnings,
                        "highlights": r.highlights,
                        "reasoning": r.reasoning,
                        "error": r.error,
                        "duration_ms": r.duration_ms,
                    }
                    for r in result.agent_results
                ],
                synthesis_result=(
                    {
                        "agent_name": result.synthesis_result.agent_name,
                        "role": result.synthesis_result.role,
                        "score": result.synthesis_result.score,
                        "reasoning": result.synthesis_result.reasoning,
                        "issues": result.synthesis_result.issues,
                        "warnings": result.synthesis_result.warnings,
                        "highlights": result.synthesis_result.highlights,
                        "raw_response": result.synthesis_result.raw_response,
                    }
                    if result.synthesis_result
                    else None
                ),
                dag_snapshot=(
                    result.dag_snapshot.model_dump(mode="json")
                    if result.dag_snapshot
                    else None
                ),
                blueprint_snapshot=[
                    bp.model_dump(mode="json") for bp in result.blueprint_snapshot
                ],
            )

            return response

        except GatewayClientError as exc:
            logger.error("动态编排网关错误: %s", exc)
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        except Exception as exc:
            logger.error("动态编排异常: %s", exc, exc_info=True)
            raise HTTPException(status_code=500, detail=f"编排执行异常: {exc}") from exc

    @router.post("/orchestrate/compare")
    async def orchestrate_compare(request: DynamicOrchestrationRequest) -> dict[str, Any]:
        """
        对比模式：同时运行动态编排和现有硬编码审核，返回对比结果。

        用于验证新架构与旧架构的结果一致性。
        """
        if gateway_client is None:
            raise HTTPException(status_code=503, detail="模型网关未配置。")

        try:
            # 动态编排
            orchestrator = TaskOrchestrator(
                gateway_client=gateway_client,
                default_model=default_model,
                max_workers=request.max_workers,
            )

            dynamic_result = await asyncio.to_thread(
                orchestrator.execute,
                task_type=request.task_type,
                task_description=request.task_description,
                task_context=request.task_context,
                model=request.model,
            )

            return {
                "dynamic": {
                    "orchestration_id": dynamic_result.orchestration_id,
                    "agents_created": dynamic_result.agents_created,
                    "overall_score": dynamic_result.overall_score,
                    "overall_approved": dynamic_result.overall_approved,
                    "agents_succeeded": dynamic_result.agents_succeeded,
                    "agents_failed": dynamic_result.agents_failed,
                    "total_duration_ms": dynamic_result.total_duration_ms,
                    "agent_names": [
                        r.agent_name for r in dynamic_result.agent_results
                    ],
                },
                "legacy": {
                    "note": "旧架构需要通过 /api/tasks 接口触发，此处仅展示动态编排结果",
                },
                "task_type": request.task_type,
            }

        except Exception as exc:
            logger.error("对比编排异常: %s", exc, exc_info=True)
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    return router
