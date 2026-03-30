from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path
from typing import Any

from app.domain.models import (
    ArtifactItem,
    DraftResult,
    ReviewPayload,
    SourceAsset,
    StoryPlan,
    TaskCreateRequest,
    TaskEvent,
    TaskRecord,
    TaskStatus,
    utc_now,
)


class TaskNotFoundError(Exception):
    pass


class TaskLogStore:
    def __init__(self, root_dir: str = "tasklog", tail_limit: int = 50) -> None:
        self.root_dir = Path(root_dir)
        self.runs_dir = self.root_dir / "runs"
        self.archive_dir = self.root_dir / "archive"
        self.specs_dir = self.root_dir / "specs"
        self.tail_limit = tail_limit
        self._tasks: dict[str, TaskRecord] = {}
        self._subscribers: dict[str, list[asyncio.Queue[dict[str, Any]]]] = {}

        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self.archive_dir.mkdir(parents=True, exist_ok=True)
        self.specs_dir.mkdir(parents=True, exist_ok=True)
        self._load_existing_tasks()
        self._write_specs()
        self._write_index()

    def create_task(self, payload: TaskCreateRequest) -> TaskRecord:
        task = TaskRecord(mode=payload.mode, input=payload)
        self._tasks[task.id] = task
        self.append_event(
            task.id,
            stage="created",
            message="任务已创建，等待生成大纲。",
            event_type="task.created",
            task=task,
        )
        return self.save(task)

    def save(self, task: TaskRecord) -> TaskRecord:
        task.updated_at = utc_now()
        self._tasks[task.id] = task
        self._write_task_files(task)
        self._archive_completed_task(task)
        self._write_index()
        return task

    def get(self, task_id: str) -> TaskRecord:
        task = self._tasks.get(task_id)
        if not task:
            raise TaskNotFoundError(task_id)
        return task

    def summaries(self) -> list[dict[str, Any]]:
        return [self._summary(task) for task in sorted(self._tasks.values(), key=lambda item: item.updated_at, reverse=True)]

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
            task=task,
        )
        return self.save(task)

    def set_waiting_review(self, task_id: str, review: ReviewPayload, story_plan: StoryPlan) -> TaskRecord:
        task = self.get(task_id)
        task.story_plan = story_plan
        task.pending_review = review
        task.status = TaskStatus.WAITING_OUTLINE_REVIEW
        task.current_stage = "waiting_outline_review"
        task.current_unit = "outline"
        task.progress = 55
        self.append_event(
            task_id,
            stage="waiting_outline_review",
            message="大纲已生成，等待人工审核。",
            event_type="review.waiting",
            md_ref=f"tasklog/{task.storage_state}/{task.id}/outline.md",
            json_ref=f"tasklog/{task.storage_state}/{task.id}/outline.json",
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
        self.append_event(
            task_id,
            stage="completed",
            message="正文与工件已生成完成。",
            event_type="task.completed",
            md_ref=f"tasklog/{task.storage_state}/{task.id}/result.md",
            json_ref=f"tasklog/{task.storage_state}/{task.id}/result.json",
            task=task,
        )
        return self.save(task)

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
            task=task,
        )
        return self.save(task)

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
        target = task or self.get(task_id)
        event = TaskEvent(
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
        self._tasks[target.id] = target
        self._broadcast_event(target.id, event)
        self._write_events(target)
        self._write_trace(target)
        return target

    def subscribe(self, task_id: str) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._subscribers.setdefault(task_id, []).append(queue)
        return queue

    def unsubscribe(self, task_id: str, queue: asyncio.Queue[dict[str, Any]]) -> None:
        queues = self._subscribers.get(task_id, [])
        if queue in queues:
            queues.remove(queue)

    def _broadcast_event(self, task_id: str, event: TaskEvent) -> None:
        payload = event.model_dump(mode="json")
        for queue in self._subscribers.get(task_id, []):
            queue.put_nowait(payload)

    def _load_existing_tasks(self) -> None:
        for base_dir, storage_state in ((self.runs_dir, "runs"), (self.archive_dir, "archive")):
            for task_dir in sorted(base_dir.glob("task_*")):
                snapshot_path = task_dir / "task.json"
                if not snapshot_path.exists():
                    continue
                data = json.loads(snapshot_path.read_text(encoding="utf-8"))
                task = TaskRecord.model_validate(data)
                task.storage_state = storage_state
                self._tasks[task.id] = task

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
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        trace_dir.mkdir(parents=True, exist_ok=True)

        self._write_json(task_dir / "task.json", task.model_dump(mode="json"))
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
            events_md.append(f"- {event.at.isoformat()} | {event.event_type} | {event.stage} | {event.message}{suffix}")
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
        source_dir = self.runs_dir / task.id
        target_dir = self.archive_dir / task.id
        target_dir.parent.mkdir(parents=True, exist_ok=True)
        if target_dir.exists():
            shutil.rmtree(target_dir)
        if source_dir.exists():
            shutil.move(str(source_dir), str(target_dir))
        task.storage_state = "archive"
        self._tasks[task.id] = task
        self._write_json(target_dir / "task.json", task.model_dump(mode="json"))
        self._write_json(target_dir / "meta.json", self._meta_payload(task))

    def _write_index(self) -> None:
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
            "status": task.status.value,
            "current_stage": task.current_stage,
            "current_unit": task.current_unit,
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
            "input": task.input.model_dump(mode="json"),
            "sources": [source.model_dump(mode="json") for source in task.sources],
        }

    def _request_markdown(self, task: TaskRecord) -> str:
        lines = [
            "# 请求",
            "",
            f"- task_id: {task.id}",
            f"- mode: {task.mode.value}",
            f"- prompt: {task.input.prompt}",
            f"- genre: {task.input.genre}",
            f"- style: {task.input.style}",
            f"- target_words: {task.input.target_words}",
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

    def _write_json(self, path: Path, payload: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _write_md(self, path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
