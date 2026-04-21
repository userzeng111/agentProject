import unittest
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient
from unittest.mock import patch

from app.agents.dynamic.models import (
    AgentBlueprint,
    OrchestrationResult,
    TaskDAG,
    TaskDAGNode,
    TaskExecutionResult,
)
from app.api.dynamic_routes import build_dynamic_router


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class DynamicRoutesTests(unittest.TestCase):
    def test_dynamic_health_reports_degraded_without_gateway(self) -> None:
        app = FastAPI()
        app.include_router(build_dynamic_router(gateway_client=None, default_model="gpt-5.4"), prefix="/api/v2")
        client = TestClient(app)

        response = client.get("/api/v2/dynamic/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "degraded")

    def test_dynamic_orchestrate_returns_structured_payload(self) -> None:
        orchestrator_result = OrchestrationResult(
            orchestration_id="orch_test_001",
            task_description="审核大纲",
            agents_created=2,
            agents_succeeded=2,
            agents_failed=0,
            overall_score=88.0,
            overall_approved=True,
            total_duration_ms=1200,
            agent_results=[
                TaskExecutionResult(
                    agent_id="agent_1",
                    agent_name="结构分析师",
                    role="structure",
                    dimension="structure",
                    weight=1.0,
                    score=86.0,
                    issues=[{"severity": "warning", "description": "节奏稍慢"}],
                    highlights=["冲突建立清晰"],
                    reasoning="整体结构稳定",
                    started_at=_utc_now(),
                    completed_at=_utc_now(),
                )
            ],
            synthesis_result=TaskExecutionResult(
                agent_id="agent_syn",
                agent_name="综合裁决",
                role="synthesis",
                dimension="overall",
                weight=1.0,
                score=88.0,
                reasoning="可以进入下一阶段",
                raw_response={"final_recommendation": "通过"},
                started_at=_utc_now(),
                completed_at=_utc_now(),
            ),
            dag_snapshot=TaskDAG(
                nodes=[TaskDAGNode(node_id="node_1", agent_id="agent_1", layer=0, label="结构分析")],
                execution_layers=[["node_1"]],
            ),
            blueprint_snapshot=[
                AgentBlueprint(
                    agent_id="bp_1",
                    agent_name="结构分析师",
                    role="structure",
                    dimension="structure",
                    weight=1.0,
                    system_prompt="你是结构分析师",
                    user_prompt_template="请分析结构",
                )
            ],
        )

        class FakeOrchestrator:
            def __init__(self, *args, **kwargs) -> None:
                pass

            def execute(self, task_type, task_description, task_context, model):
                return orchestrator_result

        app = FastAPI()
        with patch("app.api.dynamic_routes.TaskOrchestrator", FakeOrchestrator):
            app.include_router(build_dynamic_router(gateway_client=object(), default_model="gpt-5.4"), prefix="/api/v2")
            client = TestClient(app)

            response = client.post(
                "/api/v2/dynamic/orchestrate",
                json={
                    "task_type": "outline_review",
                    "task_description": "审核大纲",
                    "task_context": {"genre": "悬疑"},
                    "model": "gpt-5.4",
                    "max_workers": 2,
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["success"])
        self.assertEqual(payload["orchestration_id"], "orch_test_001")
        self.assertEqual(payload["agents_created"], 2)
        self.assertEqual(payload["overall_score"], 88.0)
        self.assertTrue(payload["overall_approved"])
        self.assertEqual(payload["agent_results"][0]["agent_name"], "结构分析师")
        self.assertEqual(payload["synthesis_result"]["agent_name"], "综合裁决")

    def test_dynamic_compare_returns_dynamic_summary(self) -> None:
        orchestrator_result = OrchestrationResult(
            orchestration_id="orch_cmp_001",
            task_description="审核大纲",
            agents_created=3,
            agents_succeeded=3,
            agents_failed=0,
            overall_score=91.0,
            overall_approved=True,
            total_duration_ms=980,
            agent_results=[
                TaskExecutionResult(
                    agent_id="agent_1",
                    agent_name="结构分析师",
                    role="structure",
                    dimension="structure",
                    score=90.0,
                    started_at=_utc_now(),
                    completed_at=_utc_now(),
                )
            ],
        )

        class FakeOrchestrator:
            def __init__(self, *args, **kwargs) -> None:
                pass

            def execute(self, task_type, task_description, task_context, model):
                return orchestrator_result

        app = FastAPI()
        with patch("app.api.dynamic_routes.TaskOrchestrator", FakeOrchestrator):
            app.include_router(build_dynamic_router(gateway_client=object(), default_model="gpt-5.4"), prefix="/api/v2")
            client = TestClient(app)

            response = client.post(
                "/api/v2/dynamic/orchestrate/compare",
                json={
                    "task_type": "outline_review",
                    "task_description": "审核大纲",
                    "task_context": {},
                    "model": "gpt-5.4",
                    "max_workers": 2,
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["dynamic"]["orchestration_id"], "orch_cmp_001")
        self.assertEqual(payload["dynamic"]["overall_score"], 91.0)
        self.assertEqual(payload["legacy"]["note"], "旧架构需要通过 /api/tasks 接口触发，此处仅展示动态编排结果")


if __name__ == "__main__":
    unittest.main()
