from __future__ import annotations

import asyncio
import json
from app.observability import get_logger
import os
import shutil
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.domain.models import (
    AgentRunRecord,
    ArtifactItem,
    DraftResult,
    ReviewPayload,
    SourceAsset,
    StoryPlan,
    SubtaskRecord,
    TaskCreateRequest,
    TaskEvent,
    TaskRecord,
    TaskStatus,
    utc_now,
)
from app.observability.performance import performance_span


class TaskNotFoundError(Exception):
    pass

logger = get_logger(__name__)


@dataclass(frozen=True)
class _TaskEventSubscriber:
    """保存订阅事件流所在的事件循环，供后台工作线程安全投递。"""

    queue: asyncio.Queue[dict[str, Any]]
    loop: asyncio.AbstractEventLoop | None


class TaskLogStore:
    def __init__(self, root_dir: str = "tasklog", tail_limit: int = 50) -> None:
        self.root_dir = Path(root_dir)
        self.runs_dir = self.root_dir / "runs"
        self.archive_dir = self.root_dir / "archive"
        self.specs_dir = self.root_dir / "specs"
        self.tail_limit = tail_limit
        self._tasks: dict[str, TaskRecord] = {}
        self._subscribers: dict[str, list[_TaskEventSubscriber | asyncio.Queue[dict[str, Any]]]] = {}
        self._lock = threading.Lock()

        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self.archive_dir.mkdir(parents=True, exist_ok=True)
        self.specs_dir.mkdir(parents=True, exist_ok=True)
        self._load_existing_tasks()
        self._write_specs()
        self._write_index()

    def create_task(self, payload: TaskCreateRequest) -> TaskRecord:
        task = TaskRecord(
            mode=payload.mode,
            model_id=(payload.model_id or "").strip(),
            auto_review_model_mode=payload.auto_review_model_mode,
            review_model_id=(payload.review_model_id or "").strip(),
            input=payload,
            auto_review=payload.auto_review,
        )
        with self._lock:
            self._tasks[task.id] = task
        self.append_event(
            task.id,
            stage="created",
            message="任务已创建，等待生成大纲。",
            event_type="task.created",
            payload={"summary": "任务已创建", "display_level": "public"},
            task=task,
        )
        return self.save(task)

    def save(self, task: TaskRecord) -> TaskRecord:
        with performance_span(logger, "task_store_save", task_id=task.id, task_status=task.status.value):
            task.updated_at = utc_now()
            with self._lock:
                self._tasks[task.id] = task
            with performance_span(logger, "task_store_write_task_files", task_id=task.id):
                self._write_task_files(task)
            self._sync_to_db(task)
            with performance_span(logger, "task_store_write_index", task_id=task.id):
                self._write_index()
            return task

    def _sync_to_db(self, task: TaskRecord) -> None:
        """将任务索引元数据同步写入 SQLite。"""
        with performance_span(logger, "task_store_sync_to_db", task_id=task.id):
            try:
                from app.storage.db_repository import upsert_task_index
                upsert_task_index(task)
            except Exception:
                logger.exception("任务 %s 数据库索引同步失败", task.id)

    def get(self, task_id: str) -> TaskRecord:
        with self._lock:
            task = self._tasks.get(task_id)
        if not task:
            raise TaskNotFoundError(task_id)
        return task

    def summaries(self) -> list[dict[str, Any]]:
        with self._lock:
            return [self._summary(task) for task in sorted(self._tasks.values(), key=lambda item: item.updated_at, reverse=True)]

    def counts(self) -> dict[str, int]:
        with self._lock:
            return {
                "active_runs": sum(
                    1
                    for task in self._tasks.values()
                    if task.storage_state == "runs"
                    and task.status in {
                        TaskStatus.PLANNING,
                        TaskStatus.DRAFTING,
                        TaskStatus.ASSEMBLING,
                        TaskStatus.WAITING_MANUAL_ACTION,
                    }
                ),
            "archived_runs": sum(1 for task in self._tasks.values() if task.storage_state == "archive"),
        }

    def list_archive_tasks(self) -> list[TaskRecord]:
        with self._lock:
            return sorted(
                [task for task in self._tasks.values() if task.storage_state == "archive"],
                key=lambda item: item.updated_at,
                reverse=True,
            )

    def list_archive_tasks_paginated(
        self, page: int = 1, page_size: int = 10
    ) -> tuple[list[TaskRecord], int]:
        """返回分页后的归档任务列表及总数。"""
        all_archived = self.list_archive_tasks()
        total = len(all_archived)
        skip = (page - 1) * page_size
        return all_archived[skip : skip + page_size], total

    def list_run_tasks(self) -> list[TaskRecord]:
        with self._lock:
            return sorted(
                [task for task in self._tasks.values() if task.storage_state == "runs"],
                key=lambda item: item.updated_at,
                reverse=True,
            )

    def list_subtasks(self, task_id: str) -> list[SubtaskRecord]:
        task = self.get(task_id)
        if task.supervisor_plan is None:
            return []
        return list(task.supervisor_plan.subtasks)

    def upsert_subtask(self, task_id: str, subtask: SubtaskRecord) -> TaskRecord:
        task = self.get(task_id)
        if task.supervisor_plan is None:
            raise ValueError("当前任务没有 supervisor_plan。")

        next_subtasks: list[SubtaskRecord] = []
        replaced = False
        for current in task.supervisor_plan.subtasks:
            if current.id == subtask.id:
                next_subtasks.append(subtask)
                replaced = True
            else:
                next_subtasks.append(current)
        if not replaced:
            next_subtasks.append(subtask)

        task.supervisor_plan = task.supervisor_plan.model_copy(
            update={"subtasks": next_subtasks},
            deep=True,
        )
        return self.save(task)

    def append_agent_run(self, task_id: str, agent_run: AgentRunRecord) -> TaskRecord:
        task = self.get(task_id)
        task.agent_runs.append(agent_run)
        return self.save(task)

    def add_source(self, task_id: str, source: SourceAsset) -> TaskRecord:
        task = self.get(task_id)
        task.sources.append(source)
        task.status = TaskStatus.SOURCES_INGESTED
        task.progress = max(task.progress, 10)
        task.current_stage = "sources_ingested"
        self.append_event(
            task_id,
            stage="sources_ingested",
            message=f"已接收参考文本：{source.filename}",
            event_type="source.ingested",
            unit_id=source.id,
            payload={"summary": f"已接收素材 {source.filename}", "display_level": "public"},
            task=task,
        )
        return self.save(task)

    def set_waiting_review(self, task_id: str, review: ReviewPayload, story_plan: StoryPlan, auto_review_trace: list[dict[str, Any]] | None = None) -> TaskRecord:
        task = self.get(task_id)
        task.story_plan = story_plan
        task.pending_review = review
        task.status = TaskStatus.WAITING_OUTLINE_REVIEW
        task.current_stage = "waiting_outline_review"
        task.current_unit = "outline"
        task.progress = 55
        task.error_message = ""
        if auto_review_trace is not None:
            task.auto_review_trace = auto_review_trace
        self.append_event(
            task_id,
            stage="waiting_outline_review",
            message="大纲已生成，等待人工审核。",
            event_type="review.waiting",
            md_ref=f"tasklog/{task.storage_state}/{task.id}/outline.md",
            json_ref=f"tasklog/{task.storage_state}/{task.id}/outline.json",
            payload={"summary": "大纲已生成，等待人工审核", "display_level": "public"},
            task=task,
        )
        return self.save(task)

    def set_waiting_chapter_review(
        self,
        task_id: str,
        review: ReviewPayload,
        auto_review_trace: list[dict[str, Any]] | None = None,
        story_plan: StoryPlan | None = None,
    ) -> TaskRecord:
        task = self.get(task_id)
        if story_plan is not None:
            task.story_plan = story_plan
        task.pending_review = review
        task.status = TaskStatus.WAITING_CHAPTER_REVIEW
        task.current_stage = "waiting_chapter_review"
        task.current_unit = f"chapter-pair-{review.batch_index or 0}"
        batch = review.batch_index or 0
        total = review.total_chapters or 0
        completed = review.completed_count or 0
        chapter_items = review.chapter_pair or []
        batch_end = min(batch + len(chapter_items), total) if total > 0 else batch + len(chapter_items)
        task.progress = 55 + int(35 * completed / total) if total > 0 else 60
        task.error_message = ""
        if auto_review_trace is not None:
            task.auto_review_trace = auto_review_trace
        self.append_event(
            task_id,
            stage="waiting_chapter_review",
            message=(
                f"第 {batch + 1} 章已生成（{completed}/{total}），等待审核。"
                if batch_end <= batch + 1
                else f"第 {batch + 1}-{batch_end} 章已生成（{completed}/{total}），等待审核。"
            ),
            event_type="review.waiting",
            payload={"summary": f"章节批次审核等待中 ({completed}/{total})", "display_level": "public"},
            task=task,
        )
        return self.save(task)

    def set_ready_for_batch(self, task_id: str, story_plan: StoryPlan, message: str = "大纲审核通过，等待继续创作。") -> TaskRecord:
        task = self.get(task_id)
        task.story_plan = story_plan
        task.pending_review = None
        task.status = TaskStatus.READY_FOR_BATCH
        task.current_stage = "ready_for_batch"
        task.current_unit = None
        task.progress = max(task.progress, 58)
        task.error_message = ""
        self.append_event(
            task_id,
            stage="ready_for_batch",
            message=message,
            event_type="task.ready_for_batch",
            payload={"summary": message, "display_level": "public"},
            task=task,
        )
        return self.save(task)

    def set_waiting_verification_review(
        self,
        task_id: str,
        review: ReviewPayload,
        auto_review_trace: list[dict[str, Any]] | None = None,
        story_plan: StoryPlan | None = None,
    ) -> TaskRecord:
        task = self.get(task_id)
        if story_plan is not None:
            task.story_plan = story_plan
        task.pending_review = review
        task.status = TaskStatus.WAITING_VERIFICATION_REVIEW
        task.current_stage = "waiting_verification_review"
        task.current_unit = "verification"
        task.progress = 92
        task.error_message = ""
        if auto_review_trace is not None:
            task.auto_review_trace = auto_review_trace
        self.append_event(
            task_id,
            stage="waiting_verification_review",
            message="全文一致性验证完成，等待审核验证报告。",
            event_type="review.waiting",
            payload={"summary": "全文验证报告待审核", "display_level": "public"},
            task=task,
        )
        return self.save(task)

    def set_completed(
        self,
        task_id: str,
        story_plan: StoryPlan,
        draft_result: DraftResult,
        artifacts: list[ArtifactItem],
    ) -> TaskRecord:
        task = self.get(task_id)
        task.story_plan = story_plan
        task.pending_review = None
        task.draft_result = draft_result
        task.artifacts = artifacts
        task.status = TaskStatus.COMPLETED
        task.current_stage = "completed"
        task.current_unit = None
        task.progress = 100
        task.error_message = ""
        self.append_event(
            task_id,
            stage="completed",
            message="正文与工件已生成完成。",
            event_type="task.completed",
            md_ref=f"tasklog/{task.storage_state}/{task.id}/result.md",
            json_ref=f"tasklog/{task.storage_state}/{task.id}/result.json",
            payload={"summary": "正文与工件已生成完成", "display_level": "public"},
            task=task,
        )
        return self.save(task)

    def archive_completed_task(self, task_id: str) -> TaskRecord:
        task = self.get(task_id)
        if task.status is not TaskStatus.COMPLETED:
            raise ValueError("只有已完成任务可以归档。")
        if task.draft_result is None:
            raise ValueError("任务缺少正文结果，无法归档。")
        if task.storage_state == "archive":
            return task
        self.append_event(
            task_id,
            stage="completed",
            message="用户已确认结果，任务已归档。",
            event_type="task.archived",
            payload={"summary": "用户已确认结果，任务已归档", "display_level": "public"},
            task=task,
        )
        self._archive_completed_task(task)
        self._sync_to_db(task)
        self._write_index()
        return task

    def set_cancelled(self, task_id: str, story_plan: StoryPlan, comment: str) -> TaskRecord:
        task = self.get(task_id)
        task.story_plan = story_plan
        task.pending_review = None
        task.status = TaskStatus.CANCELLED
        task.current_stage = "cancelled"
        task.progress = 55
        note = comment or "人工审核未通过，任务已取消。"
        self.append_event(
            task_id,
            stage="cancelled",
            message=note,
            event_type="task.cancelled",
            payload={"summary": note, "display_level": "public"},
            task=task,
        )
        return self.save(task)

    def cancel_task(self, task_id: str, comment: str = "") -> TaskRecord:
        """取消任务 — 仅允许取消处于 planning/drafting/waiting_* 状态的任务。"""
        cancellable_statuses = {
            TaskStatus.PLANNING,
            TaskStatus.DRAFTING,
            TaskStatus.WAITING_OUTLINE_REVIEW,
            TaskStatus.WAITING_CHAPTER_REVIEW,
            TaskStatus.WAITING_VERIFICATION_REVIEW,
            TaskStatus.WAITING_MANUAL_ACTION,
            TaskStatus.ASSEMBLING,
        }
        task = self.get(task_id)
        if task.status not in cancellable_statuses:
            raise ValueError(
                f"当前任务状态为 {task.status.value}，无法取消。"
                f"只能取消 planning/drafting/waiting_* 状态的任务。"
            )
        task.status = TaskStatus.CANCELLED
        task.current_stage = "cancelled"
        task.pending_review = None
        note = comment.strip() or "任务已被用户取消。"
        self.append_event(
            task_id,
            stage="cancelled",
            message=note,
            event_type="task.cancelled",
            payload={"summary": note, "display_level": "public"},
            task=task,
        )
        return self.save(task)

    def delete_task(self, task_id: str) -> dict[str, str]:
        """删除任务 — 不允许删除运行中的任务，仅删除已结束的任务。"""
        running_statuses = {
            TaskStatus.PLANNING,
            TaskStatus.DRAFTING,
            TaskStatus.ASSEMBLING,
            TaskStatus.WAITING_MANUAL_ACTION,
        }
        task = self.get(task_id)
        if task.status in running_statuses:
            raise ValueError(
                f"当前任务状态为 {task.status.value}，无法删除。"
                f"请先取消任务后再删除。"
            )
        # 从内存字典中移除
        with self._lock:
            self._tasks.pop(task_id, None)
        # 从 SQLite 索引中删除
        try:
            from app.storage.db_repository import delete_task_index
            delete_task_index(task_id)
        except Exception:
            logger.warning("任务 %s 数据库索引删除失败", task_id, exc_info=True)
        # 删除 tasklog 目录下的文件
        task_dir = self._task_dir(task)
        if task_dir.exists():
            try:
                shutil.rmtree(task_dir)
            except Exception:
                logger.warning("任务 %s 目录删除失败: %s", task_id, task_dir, exc_info=True)
        # 清理订阅者
        self._subscribers.pop(task_id, None)
        # 刷新索引
        self._write_index()
        return {"task_id": task_id, "message": "任务已删除。"}

    def set_failed(self, task_id: str, message: str) -> TaskRecord:
        task = self.get(task_id)
        task.status = TaskStatus.FAILED
        task.current_stage = "failed"
        task.error_message = message
        self.append_event(
            task_id,
            stage="failed",
            message=message,
            event_type="task.failed",
            payload={"summary": message, "display_level": "public"},
            task=task,
        )
        return self.save(task)

    def set_waiting_manual_action(
        self,
        task_id: str,
        message: str,
        *,
        payload: dict[str, Any] | None = None,
    ) -> TaskRecord:
        task = self.get(task_id)
        task.status = TaskStatus.WAITING_MANUAL_ACTION
        task.current_stage = "waiting_manual_action"
        task.current_unit = None
        task.error_message = message
        self.append_event(
            task_id,
            stage="waiting_manual_action",
            message=message,
            event_type="task.recovery.blocked",
            payload=payload or {"summary": message, "display_level": "public"},
            task=task,
        )
        return self.save(task)

    def update_normalized_spec(self, task_id: str, normalized_spec: dict[str, Any]) -> TaskRecord:
        task = self.get(task_id)
        task.normalized_spec = normalized_spec
        task.status = TaskStatus.PLANNING
        task.current_stage = "planning"
        task.progress = max(task.progress, 20)
        self.append_event(
            task_id,
            stage="planning",
            message="创作要求已标准化，准备生成大纲。",
            event_type="task.stage.changed",
            payload={"summary": "创作要求已标准化", "display_level": "public"},
            task=task,
        )
        return self.save(task)

    def mark_stage(
        self,
        task_id: str,
        *,
        status: TaskStatus | None = None,
        stage: str,
        progress: int | None = None,
        unit_id: str | None = None,
        message: str,
        event_type: str,
        md_ref: str | None = None,
        json_ref: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> TaskRecord:
        task = self.get(task_id)
        task.current_stage = stage
        task.current_unit = unit_id
        if status is not None:
            task.status = status
        if progress is not None:
            task.progress = progress
        self.append_event(
            task_id,
            stage=stage,
            message=message,
            event_type=event_type,
            unit_id=unit_id,
            md_ref=md_ref,
            json_ref=json_ref,
            payload=payload,
            task=task,
        )
        return self.save(task)

    def append_event(
        self,
        task_id: str,
        stage: str,
        message: str,
        event_type: str = "task.updated",
        unit_id: str | None = None,
        md_ref: str | None = None,
        json_ref: str | None = None,
        payload: dict[str, Any] | None = None,
        task: TaskRecord | None = None,
    ) -> TaskRecord:
        with performance_span(logger, "task_store_append_event", task_id=task_id, event_type=event_type):
            target = task or self.get(task_id)
            event = TaskEvent(
                task_id=target.id,
                stage=stage,
                message=message,
                event_type=event_type,
                unit_id=unit_id,
                md_ref=md_ref,
                json_ref=json_ref,
                payload=payload or {},
            )
            target.events.append(event)
            target.updated_at = utc_now()
            with self._lock:
                self._tasks[target.id] = target
            with performance_span(logger, "task_store_broadcast_event", task_id=target.id):
                self._broadcast_event(target.id, event)
            with performance_span(logger, "task_store_write_events", task_id=target.id):
                self._write_events(target)
            with performance_span(logger, "task_store_write_trace", task_id=target.id):
                self._write_trace(target)
            return target

    def broadcast_event(
        self,
        task_id: str,
        *,
        stage: str,
        message: str,
        event_type: str = "task.updated",
        unit_id: str | None = None,
        md_ref: str | None = None,
        json_ref: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        """只向实时订阅者广播事件，不写入任务事件列表或文件。"""
        task = self.get(task_id)
        event = TaskEvent(
            task_id=task.id,
            stage=stage,
            message=message,
            event_type=event_type,
            unit_id=unit_id,
            md_ref=md_ref,
            json_ref=json_ref,
            payload=payload or {},
        )
        with performance_span(logger, "task_store_broadcast_transient_event", task_id=task.id, event_type=event_type):
            self._broadcast_event(task.id, event)

    def subscribe(self, task_id: str) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=256)
        try:
            loop: asyncio.AbstractEventLoop | None = asyncio.get_running_loop()
        except RuntimeError:
            # 仅供同步测试和历史内部调用使用；生产 SSE 订阅始终绑定运行中的事件循环。
            loop = None
        subscriber = _TaskEventSubscriber(queue=queue, loop=loop)
        with self._lock:
            self._subscribers.setdefault(task_id, []).append(subscriber)
        return queue

    def unsubscribe(self, task_id: str, queue: asyncio.Queue[dict[str, Any]]) -> None:
        with self._lock:
            subscribers = self._subscribers.get(task_id, [])
            remaining = [
                subscriber
                for subscriber in subscribers
                if (subscriber.queue if isinstance(subscriber, _TaskEventSubscriber) else subscriber) is not queue
            ]
            if remaining:
                self._subscribers[task_id] = remaining
            else:
                self._subscribers.pop(task_id, None)

    def read_text(self, task_id: str, relative_path: str) -> str:
        return self._resolve_task_path(task_id, relative_path).read_text(encoding="utf-8")

    def read_json(self, task_id: str, relative_path: str) -> dict[str, Any]:
        return json.loads(self.read_text(task_id, relative_path))

    def write_context_snapshot(
        self,
        task_id: str,
        *,
        stage: str,
        snapshot_name: str,
        payload: dict[str, Any],
    ) -> str:
        task = self.get(task_id)
        safe_stage = (stage or "shared").strip().replace("\\", "-").replace("/", "-")
        safe_name = (snapshot_name or "snapshot").strip().replace("\\", "-").replace("/", "-")
        relative_path = f"context/{safe_stage}/{safe_name}.json"
        path = self._task_dir(task) / relative_path
        self._write_json(path, payload)
        return relative_path

    def write_message_history(
        self,
        task_id: str,
        *,
        stage: str,
        history: list[dict[str, Any]],
        filename: str = "message-history",
    ) -> str:
        task = self.get(task_id)
        safe_stage = (stage or "shared").strip().replace("\\", "-").replace("/", "-")
        safe_name = (filename or "message-history").strip().replace("\\", "-").replace("/", "-")
        relative_path = f"context/{safe_stage}/{safe_name}.json"
        path = self._task_dir(task) / relative_path
        self._write_json(
            path,
            {
                "task_id": task_id,
                "stage": safe_stage,
                "messages": history,
            },
        )
        return relative_path

    def _broadcast_event(self, task_id: str, event: TaskEvent) -> None:
        payload = event.model_dump(mode="json")
        with self._lock:
            subscribers = list(self._subscribers.get(task_id, []))

        def deliver(queue: asyncio.Queue[dict[str, Any]]) -> None:
            try:
                queue.put_nowait(payload)
            except asyncio.QueueFull:
                logger.warning(
                    "任务事件广播失败 task_id=%s event_type=%s reason=queue_full",
                    task_id,
                    event.event_type,
                )
                self.unsubscribe(task_id, queue)
            except Exception:
                logger.warning(
                    "任务事件广播失败 task_id=%s event_type=%s",
                    task_id,
                    event.event_type,
                    exc_info=True,
                )
                self.unsubscribe(task_id, queue)

        for subscriber in subscribers:
            if isinstance(subscriber, _TaskEventSubscriber):
                if subscriber.loop is None:
                    deliver(subscriber.queue)
                    continue
                try:
                    subscriber.loop.call_soon_threadsafe(deliver, subscriber.queue)
                except RuntimeError:
                    # 订阅请求已经结束，事件循环无法再接收投递。
                    self.unsubscribe(task_id, subscriber.queue)
                continue
            # 兼容旧测试与历史调用方直接注入的队列。
            deliver(subscriber)

    def _load_existing_tasks(self) -> None:
        loaded: dict[str, TaskRecord] = {}
        for base_dir, storage_state in ((self.runs_dir, "runs"), (self.archive_dir, "archive")):
            for task_dir in sorted(base_dir.glob("task_*")):
                snapshot_path = task_dir / "state" / "task.json"
                if not snapshot_path.exists():
                    snapshot_path = task_dir / "task.json"
                if not snapshot_path.exists():
                    continue
                try:
                    data = json.loads(snapshot_path.read_text(encoding="utf-8"))
                    task = TaskRecord.model_validate(data)
                    task.storage_state = storage_state
                    self._migrate_legacy_model_fields(task_dir, task)
                    loaded[task.id] = task
                except json.JSONDecodeError:
                    logger.warning("跳过损坏的任务快照 %s: JSON 解析失败", snapshot_path)
                except Exception:
                    logger.warning("跳过无法加载的任务 %s", snapshot_path)
        with self._lock:
            self._tasks.update(loaded)

    def _migrate_legacy_model_fields(self, task_dir: Path, task: TaskRecord) -> None:
        legacy_paths = self._legacy_model_field_paths(task_dir)
        if not legacy_paths:
            return
        try:
            self._write_json(task_dir / "task.json", task.model_dump(mode="json"))
            self._write_json(task_dir / "state" / "task.json", task.model_dump(mode="json"))
            self._write_json(task_dir / "meta.json", self._meta_payload(task))
            self._write_json(task_dir / "request.json", self._request_payload(task))
            logger.info(
                "已规范化历史任务模型字段 task_id=%s files=%s",
                task.id,
                ",".join(legacy_paths),
            )
        except OSError:
            logger.warning(
                "规范化历史任务模型字段失败 task_id=%s files=%s",
                task.id,
                ",".join(legacy_paths),
                exc_info=True,
            )

    @staticmethod
    def _legacy_model_field_paths(task_dir: Path) -> list[str]:
        paths: list[str] = []
        for relative_path in ("task.json", "state/task.json", "meta.json", "request.json"):
            path = task_dir / relative_path
            if not path.exists():
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(payload, dict) and "default_model_id" in payload:
                paths.append(relative_path)
        return paths

    def _write_specs(self) -> None:
        specs = {
            "task-status.md": "# task statuses\n\ncreated\nsources_ingested\nplanning\nwaiting_outline_review\ndrafting\nassembling\ncompleted\nfailed\n",
            "event-types.md": "# event types\n\ntask.created\ntask.stage.changed\nsource.ingested\nreview.waiting\nchapter.started\nchapter.saved\ntask.failed\ntask.completed\n",
            "page-mapping.md": "# page mapping\n\n/dashboard -> 首页任务卡片\n/workspace -> 任务工作台\n/review -> 审核页\n/result -> 结果页\n",
        }
        for filename, content in specs.items():
            path = self.specs_dir / filename
            if not path.exists():
                path.write_text(content, encoding="utf-8")

    def _write_task_files(self, task: TaskRecord) -> None:
        task_dir = self._task_dir(task)
        artifacts_dir = task_dir / "artifacts"
        trace_dir = task_dir / "trace"
        state_dir = task_dir / "state"
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        trace_dir.mkdir(parents=True, exist_ok=True)
        state_dir.mkdir(parents=True, exist_ok=True)

        self._write_json(task_dir / "task.json", task.model_dump(mode="json"))
        self._write_json(state_dir / "task.json", task.model_dump(mode="json"))
        self._write_json(task_dir / "meta.json", self._meta_payload(task))
        self._write_json(task_dir / "request.json", self._request_payload(task))
        self._write_md(task_dir / "request.md", self._request_markdown(task))
        self._write_events(task)
        self._write_trace(task)

        if task.story_plan is not None:
            self._write_json(task_dir / "outline.json", task.story_plan.model_dump(mode="json"))
            self._write_md(task_dir / "outline.md", self._outline_markdown(task))

        if task.draft_result is not None:
            self._write_json(task_dir / "result.json", task.draft_result.model_dump(mode="json"))
            self._write_md(task_dir / "result.md", self._result_markdown(task))
            self._write_artifacts(task, artifacts_dir)

    def _write_events(self, task: TaskRecord) -> None:
        task_dir = self._task_dir(task)
        events_md = ["# 事件流", ""]
        for event in task.events:
            refs = []
            if event.md_ref:
                refs.append(f"md={event.md_ref}")
            if event.json_ref:
                refs.append(f"json={event.json_ref}")
            suffix = f" [{' | '.join(refs)}]" if refs else ""
            events_md.append(
                f"- {event.created_at.isoformat()} | {event.event_type} | {event.stage} | {event.message}{suffix}"
            )
        self._write_md(task_dir / "events.md", "\n".join(events_md) + "\n")
        tail = [event.model_dump(mode="json") for event in task.events[-self.tail_limit :]]
        self._write_json(task_dir / "events.tail.json", {"task_id": task.id, "items": tail})

    def _write_trace(self, task: TaskRecord) -> None:
        task_dir = self._task_dir(task)
        latest = task.events[-1] if task.events else None
        current = {
            "task_id": task.id,
            "stage": task.current_stage,
            "current_unit": task.current_unit,
            "status": task.status.value,
            "message": latest.message if latest else "暂无过程信息",
            "updated_at": task.updated_at.isoformat(),
        }
        self._write_json(task_dir / "trace" / "current.json", current)

    def _write_artifacts(self, task: TaskRecord, artifacts_dir: Path) -> None:
        assert task.draft_result is not None
        artifact_index: list[dict[str, Any]] = []
        for chapter in task.draft_result.chapters:
            chapter_name = f"chapter-{chapter.number:02d}"
            chapter_md = artifacts_dir / f"{chapter_name}.md"
            chapter_json = artifacts_dir / f"{chapter_name}.json"
            self._write_md(chapter_md, f"# {chapter.title}\n\n{chapter.content}\n")
            self._write_json(chapter_json, chapter.model_dump(mode="json"))
            artifact_index.append(
                {
                    "id": chapter_name,
                    "type": "chapter",
                    "title": chapter.title,
                    "md_ref": str(chapter_md.relative_to(self.root_dir.parent)),
                    "json_ref": str(chapter_json.relative_to(self.root_dir.parent)),
                }
            )

        final_md = artifacts_dir / "final.md"
        self._write_md(final_md, task.draft_result.body)
        artifact_index.append(
            {
                "id": "final",
                "type": "final",
                "title": task.draft_result.title,
                "md_ref": str(final_md.relative_to(self.root_dir.parent)),
            }
        )
        self._write_json(artifacts_dir / "index.json", artifact_index)

    def _archive_completed_task(self, task: TaskRecord) -> None:
        if task.status is not TaskStatus.COMPLETED or task.storage_state == "archive":
            return
        with performance_span(logger, "task_store_archive_completed", task_id=task.id):
            source_dir = self.runs_dir / task.id
            target_dir = self.archive_dir / task.id
            target_dir.parent.mkdir(parents=True, exist_ok=True)
            if target_dir.exists():
                backup_dir = target_dir.with_suffix(".backup")
                shutil.move(str(target_dir), str(backup_dir))
                try:
                    shutil.rmtree(backup_dir)
                except Exception as exc:
                    logger.warning("清理旧归档备份失败: %s", exc)
            if source_dir.exists():
                # 原子归档：先复制到临时目录，再原子移动到目标
                tmp_target = self.archive_dir / f".{task.id}.tmp"
                shutil.copytree(str(source_dir), str(tmp_target), dirs_exist_ok=True)
                try:
                    shutil.move(str(tmp_target), str(target_dir))
                except Exception:
                    # 移动失败时清理临时目录
                    try:
                        shutil.rmtree(str(tmp_target))
                    except OSError:
                        pass
                    raise
                try:
                    shutil.rmtree(str(source_dir))
                except Exception as exc:
                    logger.warning("归档后清理源目录失败: %s", exc)
            task.storage_state = "archive"
            run_prefix = f"tasklog/runs/{task.id}/"
            archive_prefix = f"tasklog/archive/{task.id}/"
            for event in task.events:
                if event.md_ref and event.md_ref.startswith(run_prefix):
                    event.md_ref = event.md_ref.replace(run_prefix, archive_prefix, 1)
                if event.json_ref and event.json_ref.startswith(run_prefix):
                    event.json_ref = event.json_ref.replace(run_prefix, archive_prefix, 1)
            with self._lock:
                self._tasks[task.id] = task
            self._write_task_files(task)

    def _write_index(self) -> None:
        with self._lock:
            summaries = [self._summary(task) for task in sorted(self._tasks.values(), key=lambda item: item.updated_at, reverse=True)]
        self._write_json(self.root_dir / "index.json", {"items": summaries})
        lines = ["# tasklog index", ""]
        for item in summaries:
            lines.append(
                f"- {item['task_id']} | {item['title']} | {item['status']} | {item['current_stage']} | {item['updated_at']}"
            )
        self._write_md(self.root_dir / "index.md", "\n".join(lines) + "\n")

    def _summary(self, task: TaskRecord) -> dict[str, Any]:
        title = task.story_plan.working_title if task.story_plan else (task.input.title_hint or task.input.prompt[:24] or task.id)
        latest_event = task.events[-1].message if task.events else ""
        return {
            "task_id": task.id,
            "title": title,
            "mode": task.mode.value,
            "creative_mode": task.creative_mode.value if task.creative_mode else "",
            "novel_size": task.novel_size.value if task.novel_size else "",
            "chapter_word_min": int(task.chapter_word_min or task.input.target_words or 1800),
            "model_id": task.model_id,
            "creative_model_id": task.model_id,
            "last_action_model_id": task.last_action_model_id,
            "last_action_kind": task.last_action_kind,
            "status": task.status.value,
            "current_stage": task.current_stage,
            "current_unit": task.current_unit,
            "progress": task.progress,
            "updated_at": task.updated_at.isoformat(),
            "summary": latest_event,
            "storage_state": task.storage_state,
            "entry_refs": {
                "meta_json": f"tasklog/{task.storage_state}/{task.id}/meta.json",
                "events_tail_json": f"tasklog/{task.storage_state}/{task.id}/events.tail.json",
                "result_json": f"tasklog/{task.storage_state}/{task.id}/result.json",
            },
        }

    def _meta_payload(self, task: TaskRecord) -> dict[str, Any]:
        title = task.story_plan.working_title if task.story_plan else (task.input.title_hint or task.input.prompt[:24] or task.id)
        return {
            "task_id": task.id,
            "title": title,
            "mode": task.mode.value,
            "creative_mode": task.creative_mode.value if task.creative_mode else "",
            "novel_size": task.novel_size.value if task.novel_size else "",
            "chapter_word_min": int(task.chapter_word_min or task.input.target_words or 1800),
            "model_id": task.model_id,
            "creative_model_id": task.model_id,
            "last_action_model_id": task.last_action_model_id,
            "last_action_kind": task.last_action_kind,
            "status": task.status.value,
            "current_stage": task.current_stage,
            "current_unit": task.current_unit,
            "progress": task.progress,
            "updated_at": task.updated_at.isoformat(),
            "error_message": task.error_message,
            "storage_state": task.storage_state,
        }

    def _request_payload(self, task: TaskRecord) -> dict[str, Any]:
        return {
            "task_id": task.id,
            "mode": task.mode.value,
            "creative_mode": task.creative_mode.value if task.creative_mode else "",
            "novel_size": task.novel_size.value if task.novel_size else "",
            "chapter_word_min": int(task.chapter_word_min or task.input.target_words or 1800),
            "model_id": task.model_id,
            "creative_model_id": task.model_id,
            "last_action_model_id": task.last_action_model_id,
            "last_action_kind": task.last_action_kind,
            "input": task.input.model_dump(mode="json"),
            "sources": [source.model_dump(mode="json") for source in task.sources],
        }

    def _request_markdown(self, task: TaskRecord) -> str:
        lines = [
            "# 请求",
            "",
            f"- task_id: {task.id}",
            f"- mode: {task.mode.value}",
            f"- creative_mode: {task.creative_mode.value if task.creative_mode else '无'}",
            f"- novel_size: {task.novel_size.value if task.novel_size else '无'}",
            f"- model_id: {task.model_id or '未设置'}",
            f"- prompt: {task.input.prompt}",
            f"- genre: {task.input.genre}",
            f"- style: {task.input.style}",
            f"- style_profile_id: {task.input.style_profile_id or '无'}",
            f"- chapter_word_min: {task.chapter_word_min or task.input.target_words or 1800}",
            "",
            "## 参考材料",
            "",
        ]
        if not task.sources:
            lines.append("- 无")
        else:
            for source in task.sources:
                lines.append(f"- {source.filename}")
                lines.append(f"  摘要：{source.content[:120]}")
        return "\n".join(lines) + "\n"

    def _outline_markdown(self, task: TaskRecord) -> str:
        assert task.story_plan is not None
        lines = [
            f"# {task.story_plan.working_title}",
            "",
            task.story_plan.logline,
            "",
            "## 世界观",
            "",
        ]
        lines.extend(f"- {item}" for item in task.story_plan.world_notes)
        lines.extend(["", "## 人物", ""])
        lines.extend(f"- {item}" for item in task.story_plan.character_notes)
        lines.extend(["", "## 章节计划", ""])
        for chapter in task.story_plan.chapter_plan:
            lines.append(f"- 第{chapter.number}章 {chapter.title}：{chapter.goal}")
        return "\n".join(lines) + "\n"

    def _result_markdown(self, task: TaskRecord) -> str:
        assert task.draft_result is not None
        return f"# {task.draft_result.title}\n\n{task.draft_result.summary}\n\n{task.draft_result.body}\n"

    def _task_dir(self, task: TaskRecord) -> Path:
        base = self.archive_dir if task.storage_state == "archive" else self.runs_dir
        path = base / task.id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _resolve_task_path(self, task_id: str, relative_path: str) -> Path:
        import re
        task = self.get(task_id)
        candidate = Path(relative_path)
        if candidate.is_absolute():
            raise FileNotFoundError("禁止读取绝对路径。")
        if re.search(r"\.\.|\\", relative_path):
            raise FileNotFoundError("非法路径字符。")

        task_dir = self._task_dir(task).resolve()
        if candidate.parts and candidate.parts[0] == "tasklog":
            parts = candidate.parts
            if len(parts) < 4 or parts[2] != task.id:
                raise FileNotFoundError("禁止读取其他任务的文件。")
            absolute = (self.root_dir.parent / candidate).resolve()
        else:
            absolute = (task_dir / candidate).resolve()

        try:
            absolute.relative_to(task_dir)
        except ValueError as exc:
            raise FileNotFoundError("禁止越界读取任务文件。") from exc
        if not str(absolute).startswith(str(self.root_dir.resolve())):
            raise FileNotFoundError("禁止越界读取任务文件。")
        if not absolute.exists() or not absolute.is_file():
            raise FileNotFoundError(relative_path)
        return absolute

    def _atomic_write_text(self, path: Path, content: str) -> None:
        """使用临时文件 + rename 实现原子写入。"""
        content_bytes = len(content.encode("utf-8"))
        with performance_span(
            logger,
            "task_store_write_file",
            path_name=path.name,
            bytes=content_bytes,
        ):
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp_path = tempfile.mkstemp(
                dir=path.parent,
                prefix=f".{path.name}.",
                suffix=".tmp",
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(content)
                    f.flush()
                    os.fsync(fd)
                os.replace(tmp_path, path)
            except Exception:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise

    def _write_json(self, path: Path, payload: Any) -> None:
        data = json.dumps(payload, ensure_ascii=False, indent=2)
        self._atomic_write_text(path, data)

    def _write_md(self, path: Path, content: str) -> None:
        self._atomic_write_text(path, content)
