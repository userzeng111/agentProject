from __future__ import annotations

from app.observability import get_logger
from typing import Any

from langgraph.types import Command

from app.domain.models import (
    TaskRecord,
    TaskStatus,
)
from app.graph.main_graph import (
    build_normalized_spec,
)
from app.llm.story_engine import (
    reset_exchange_callback,
    reset_progress_callback,
    set_exchange_callback,
    set_progress_callback,
)

logger = get_logger(__name__)

_STAGE_LABELS: dict[str, str] = {
    TaskStatus.WAITING_OUTLINE_REVIEW.value: "待大纲审核",
    TaskStatus.READY_FOR_BATCH.value: "可继续创作",
    TaskStatus.WAITING_CHAPTER_REVIEW.value: "待章节审核",
    TaskStatus.WAITING_VERIFICATION_REVIEW.value: "待验证审核",
    TaskStatus.PLANNING.value: "重新进入规划",
}


class TaskServiceRunnerMixin:

    def _run_task_sync(self, task_id: str, action_model_id: str | None = None) -> TaskRecord:
        if not self._enter_active_run(task_id):
            return self.store.get(task_id)
        task = self.store.get(task_id)
        if task.status not in {TaskStatus.CREATED, TaskStatus.SOURCES_INGESTED, TaskStatus.PLANNING}:
            raise ValueError("只有新建任务或已上传素材的任务才能开始生成。")
        try:
            self.store.mark_stage(
                task_id,
                status=TaskStatus.PLANNING,
                stage="planning",
                progress=max(task.progress, 20),
                message="开始执行 LangGraph 工作流，正在生成大纲。",
                event_type="outline.generating",
            )
            self._emit_trace_summary(
                task_id,
                kind="outline",
                title="开始生成大纲",
                detail="正在结合提示词、风格和参考文本收敛故事骨架。",
            )
            initial_state = self._initial_state(task, action_model_id)
            initial_payload = initial_state["input_payload"]
            normalized_spec = build_normalized_spec(
                initial_payload,
                novel_skill_service=self.novel_skill_service,
                style_profile_service=self.style_profile_service,
            )
            self.store.update_normalized_spec(task_id, self._persistable_normalized_spec(task, normalized_spec))
            self._emit_trace_summary(
                task_id,
                kind="spec",
                title="创作要求已标准化",
                detail="已整理用户诉求、方法论、风格、字数和参考材料，开始生成大纲。",
            )
            progress_token = set_progress_callback(self._build_progress_callback(task_id))
            exchange_token = set_exchange_callback(self._build_exchange_callback(task_id))
            try:
                result = self.workflow_engine.start(initial_state, config=self._config(task_id))
            finally:
                reset_progress_callback(progress_token)
                reset_exchange_callback(exchange_token)
            return self._sync_result(task_id, result)
        except Exception as exc:
            self._mark_failed_unless_stable(task_id, f"运行失败：{exc}")
            raise
        finally:
            self._leave_active_run(task_id)

    def _resume_task_sync(self, task_id: str, approved: bool, comment: str, action_model_id: str | None = None) -> TaskRecord:
        if not self._enter_active_run(task_id):
            return self.store.get(task_id)
        task = self.store.get(task_id)
        valid_statuses = {
            TaskStatus.WAITING_OUTLINE_REVIEW,
            TaskStatus.WAITING_MANUAL_ACTION,
            TaskStatus.WAITING_CHAPTER_REVIEW,
            TaskStatus.WAITING_VERIFICATION_REVIEW,
            TaskStatus.PLANNING,
            TaskStatus.DRAFTING,
        }
        if task.pending_review is None or task.status not in valid_statuses:
            raise ValueError("当前任务没有待恢复的审核节点。")
        try:
            if approved:
                self.store.mark_stage(
                    task_id,
                    status=TaskStatus.DRAFTING,
                    stage="drafting",
                    progress=max(task.progress, 60),
                    message="收到人工审核结果，继续执行工作流。",
                    event_type="draft.generating",
                    unit_id=task.current_unit,
                )
            else:
                self.store.append_event(
                    task_id,
                    stage="review_decision",
                    message="收到人工审核结果（驳回），准备修订。",
                    event_type="task.review.rejected",
                )
            progress_token = set_progress_callback(self._build_progress_callback(task_id))
            exchange_token = set_exchange_callback(self._build_exchange_callback(task_id))
            try:
                self._rehydrate_resume_state_if_needed(task, action_model_id)
                # 若已有 checkpoint 但未停留在审核中断节点，强制校准 as_node，
                # 确保 Command(resume=...) 被正确的审核中断节点消费，避免误入旧生成节点
                values = self._graph_state_values(task_id)
                if values:
                    review_type = task.pending_review.type if task.pending_review else None
                    as_node_map = {
                        "outline_review": "review_outline",
                        "chapter_pair_review": "review_chapter_pair",
                        "verification_review": "review_verification",
                    }
                    as_node = as_node_map.get(review_type)
                    if as_node and hasattr(self.workflow_engine, "update_state"):
                        self.workflow_engine.update_state(self._config(task_id), {}, as_node=as_node)
                result = self.workflow_engine.resume(
                    Command(resume={"approved": approved, "comment": comment}),
                    config=self._config(task_id),
                )
            finally:
                reset_progress_callback(progress_token)
                reset_exchange_callback(exchange_token)
            return self._sync_result(task_id, result, review_comment=comment)
        except Exception as exc:
            self._mark_failed_unless_stable(task_id, f"恢复执行失败：{exc}")
            raise
        finally:
            self._leave_active_run(task_id)

    def _build_progress_callback(self, task_id: str):
        def callback(event: dict[str, Any]) -> None:
            from app.storage.db_repository import update_project_status

            stage = str(event.get("stage") or "drafting")
            event_type = str(event.get("event_type") or "task.updated")
            unit_id = event.get("unit_id")
            message = str(event.get("message") or "任务进度已更新。")
            payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
            progress = self._progress_value(task_id, event_type, payload)
            status = TaskStatus.DRAFTING if stage == "drafting" else None
            self.store.mark_stage(
                task_id,
                status=status,
                stage=stage,
                progress=progress,
                unit_id=unit_id,
                message=message,
                event_type=event_type,
                payload=payload,
            )
            self._sync_supervisor_plan(task_id)
            # 章节正文持久化（从 conversation_history 中提取）
            if event_type == "chapter.saved":
                chapter_number = payload.get("chapter_number")
                chapter_title = payload.get("chapter_title")
                chapter_summary = payload.get("chapter_summary")
                conversation_history = event.get("conversation_history") or []
                # 从对话历史中提取章节 JSON
                chapter_content = self._extract_chapter_content(conversation_history)
                if chapter_content:
                    self._write_chapter_file(
                        task_id,
                        chapter_number=chapter_number,
                        title=chapter_title or f"第{chapter_number}章",
                        summary=chapter_summary or "",
                        content=chapter_content,
                    )
                self._emit_trace_summary(
                    task_id,
                    kind="chapter",
                    title=f"第 {payload.get('chapter_number', '?')} 章已完成",
                    detail=str(payload.get("chapter_summary") or payload.get("chapter_title") or message),
                    unit_id=unit_id,
                )
            elif event_type == "chapter.started":
                chapter_number = payload.get("chapter_number")
                if isinstance(chapter_number, int) and chapter_number > 0:
                    update_project_status(
                        task_id,
                        status=TaskStatus.DRAFTING.value,
                        current_generating_chapter_number=chapter_number,
                    )
                self._emit_trace_summary(
                    task_id,
                    kind="chapter",
                    title=f"开始生成第 {payload.get('chapter_number', '?')} 章",
                    detail=str(payload.get("chapter_title") or message),
                    unit_id=unit_id,
                )

        return callback

    def _build_exchange_callback(self, task_id: str):
        def callback(event: dict[str, Any]) -> None:
            stage = str(event.get("stage") or "unknown")
            exchange_label = str(event.get("exchange_label") or "exchange")
            history = event.get("conversation_history")
            if not isinstance(history, list):
                return
            history_path = self.store.write_message_history(
                task_id,
                stage=stage,
                history=history,
                filename=f"{exchange_label}-history",
            )
            cache_hit = bool(event.get("cache_hit"))
            cache_key = event.get("cache_key")
            model_name = str(event.get("model") or self.engine.settings.default_chat_model)
            message = (
                f"{stage} 阶段已命中模型响应缓存：{exchange_label}"
                if cache_hit
                else f"{stage} 阶段已记录模型上下文链：{exchange_label}"
            )
            self.store.append_event(
                task_id,
                stage=stage,
                message=message,
                event_type="cache.hit" if cache_hit else "context.history.updated",
                unit_id=exchange_label,
                json_ref=f"tasklog/{self.store.get(task_id).storage_state}/{task_id}/{history_path}",
                payload={
                    "summary": message,
                    "display_level": "public",
                    "cache_hit": cache_hit,
                    "cache_key": cache_key,
                    "model": model_name,
                    "history_count": len(history),
                    "exchange_label": exchange_label,
                },
            )

        return callback

    def _progress_value(self, task_id: str, event_type: str, payload: dict[str, Any]) -> int | None:
        task = self.store.get(task_id)
        total = len(task.story_plan.chapter_plan) if task.story_plan is not None else 0
        chapter_number = payload.get("chapter_number")
        if not isinstance(chapter_number, int) or total <= 0:
            return max(task.progress, 60) if event_type.startswith("chapter.") else None
        base_progress = 55
        span = 35
        offset = chapter_number - 1 if event_type == "chapter.started" else chapter_number
        return min(90, max(task.progress, base_progress + int(offset / total * span)))

