from __future__ import annotations

from typing import Any

from langgraph.types import Command

from app.domain.models import (
    ArtifactItem,
    DraftResult,
    ReviewPayload,
    SourceAsset,
    StoryPlan,
    TaskCreateRequest,
    TaskRecord,
    TaskStatus,
)
from app.graph.main_graph import build_graph
from app.llm.story_engine import StoryEngine
from app.storage.task_store import InMemoryTaskStore


class TaskService:
    def __init__(self, store: InMemoryTaskStore, engine: StoryEngine) -> None:
        self.store = store
        self.engine = engine
        self.graph = build_graph(engine)

    def create_task(self, payload: TaskCreateRequest) -> TaskRecord:
        return self.store.create_task(payload)

    def add_source(self, task_id: str, filename: str, media_type: str, content: str) -> TaskRecord:
        source = SourceAsset(filename=filename, media_type=media_type, content=content)
        return self.store.add_source(task_id, source)

    def get_task(self, task_id: str) -> TaskRecord:
        return self.store.get(task_id)

    def run_task(self, task_id: str) -> TaskRecord:
        task = self.store.get(task_id)
        if task.status is not TaskStatus.CREATED:
            raise ValueError("只有新建任务才能开始生成。")
        self.store.append_event(task_id, "running", "开始执行 LangGraph 工作流。")
        result = self.graph.invoke(self._initial_state(task), config=self._config(task_id))
        return self._sync_result(task_id, result)

    def resume_task(self, task_id: str, approved: bool, comment: str) -> TaskRecord:
        task = self.store.get(task_id)
        if task.status is not TaskStatus.WAITING_OUTLINE_REVIEW or task.pending_review is None:
            raise ValueError("当前任务没有待恢复的审核节点。")
        self.store.append_event(task_id, "resume", "收到人工审核结果，继续执行。")
        result = self.graph.invoke(
            Command(resume={"approved": approved, "comment": comment}),
            config=self._config(task_id),
        )
        return self._sync_result(task_id, result, review_comment=comment)

    def list_artifacts(self, task_id: str) -> list[ArtifactItem]:
        return self.store.get(task_id).artifacts

    def list_models(self) -> list[dict[str, Any]]:
        return self.engine.list_models()

    def _initial_state(self, task: TaskRecord) -> dict[str, Any]:
        reference_text = "\n\n".join(source.content for source in task.sources)
        return {
            "task_id": task.id,
            "input_payload": {
                "mode": task.mode.value,
                "prompt": task.input.prompt,
                "genre": task.input.genre,
                "style": task.input.style,
                "target_words": task.input.target_words,
                "audience": task.input.audience,
                "banned": task.input.banned,
                "title_hint": task.input.title_hint,
            },
            "reference_text": reference_text,
        }

    def _config(self, task_id: str) -> dict[str, Any]:
        return {"configurable": {"thread_id": task_id}}

    def _sync_result(
        self,
        task_id: str,
        result: dict[str, Any],
        review_comment: str = "",
    ) -> TaskRecord:
        snapshot = self.graph.get_state(self._config(task_id))
        values = snapshot.values if snapshot and hasattr(snapshot, "values") else {}
        normalized_spec = values.get("normalized_spec")
        if normalized_spec:
            self.store.update_normalized_spec(task_id, normalized_spec)

        if "__interrupt__" in result:
            story_plan_data = values.get("story_plan")
            if not story_plan_data:
                raise RuntimeError("工作流进入审核前未生成可用大纲。")
            review = ReviewPayload.model_validate(result["__interrupt__"][0].value)
            story_plan = StoryPlan.model_validate(story_plan_data)
            return self.store.set_waiting_review(task_id, review, story_plan)

        story_plan_data = values.get("story_plan")
        if not story_plan_data:
            raise RuntimeError("工作流结束后未找到大纲结果。")
        story_plan = StoryPlan.model_validate(story_plan_data)
        if values.get("cancelled"):
            return self.store.set_cancelled(task_id, story_plan, review_comment)

        draft_result_data = values.get("draft_result")
        if not draft_result_data:
            raise RuntimeError("工作流结束后未找到正文结果。")
        draft_result = DraftResult.model_validate(draft_result_data)
        artifacts = self._build_artifacts(story_plan, draft_result)
        return self.store.set_completed(task_id, story_plan, draft_result, artifacts)

    def _build_artifacts(self, story_plan: StoryPlan, draft_result: DraftResult) -> list[ArtifactItem]:
        return [
            ArtifactItem(
                type="story_plan",
                name=f"{story_plan.working_title}-大纲",
                content=story_plan.model_dump_json(indent=2),
            ),
            ArtifactItem(
                type="manuscript",
                name=f"{draft_result.title}-正文",
                content=draft_result.body,
            ),
        ]
