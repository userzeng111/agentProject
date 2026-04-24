from __future__ import annotations

import json
from app.observability import get_logger
import threading
from pathlib import Path
from typing import Any


from app.domain.models import (
    ChapterDraft,
    ContinueDraftRequest,
    ReviewPayload,
    TaskRecord,
    TaskStatus,
)

logger = get_logger(__name__)

_STAGE_LABELS: dict[str, str] = {
    TaskStatus.WAITING_OUTLINE_REVIEW.value: "待大纲审核",
    TaskStatus.READY_FOR_BATCH.value: "可继续创作",
    TaskStatus.WAITING_CHAPTER_REVIEW.value: "待章节审核",
    TaskStatus.WAITING_VERIFICATION_REVIEW.value: "待验证审核",
    TaskStatus.PLANNING.value: "重新进入规划",
}


class TaskServiceContinuationMixin:

    def continue_task(self, task_id: str, payload: ContinueDraftRequest | dict[str, Any]) -> TaskRecord:
        if not self._enter_active_run(task_id):
            raise ValueError("当前任务正在执行中，请勿重复提交。")
        try:
            request = payload if isinstance(payload, ContinueDraftRequest) else ContinueDraftRequest.model_validate(payload)
            task = self.store.get(task_id)
            action_model_id = self._resolve_action_model_id(task, request.model_id)
            self._ensure_novel_project_seeded(task)

            from app.storage.db_repository import (
                create_batch,
                get_active_batch,
                get_batch_by_request,
                get_novel_project,
                mark_batch_failed,
                upsert_outline_chapter_draft,
                update_project_status,
            )

            existing_batch = get_batch_by_request(task_id, request.continue_request_id)
            if existing_batch is not None:
                return self.store.get(task_id)

            if task.status is not TaskStatus.READY_FOR_BATCH:
                raise ValueError("当前任务尚未进入继续创作阶段。")
            if task.story_plan is None:
                raise ValueError("当前任务缺少大纲，无法继续创作。")

            active_batch = get_active_batch(task_id)
            if active_batch is not None and active_batch.continue_request_id != request.continue_request_id:
                raise ValueError("当前已有活动批次，不能开启新的继续创作请求。")

            project = get_novel_project(task_id)
            if project is None:
                raise ValueError("当前任务缺少小说项目记录。")

            completed_count = int(project.completed_chapter_count or 0)
            remaining = max(int(project.planned_chapter_count or 0) - completed_count, 0)
            effective_count = min(int(request.requested_chapter_count), remaining)
            if effective_count <= 0:
                raise ValueError("当前任务没有可继续创作的剩余章节。")

            batch = create_batch(
                task_id,
                continue_request_id=request.continue_request_id,
                requested_count=int(request.requested_chapter_count),
                effective_count=effective_count,
                actual_start_chapter=completed_count + 1,
            )
            update_project_status(
                task_id,
                status=TaskStatus.DRAFTING.value,
                completed_chapter_count=completed_count,
                next_chapter_number=completed_count + 1,
                active_batch_no=batch.batch_no,
                active_continue_request_id=request.continue_request_id,
                current_generating_chapter_number=completed_count + 1,
            )

            task = self.store.mark_stage(
                task_id,
                status=TaskStatus.DRAFTING,
                stage="drafting",
                progress=max(task.progress, 60),
                message="正在生成章节批次。",
                event_type="draft.generating",
                unit_id=f"chapter-pair-{batch.batch_no}",
            )
            task = self._record_last_action(task_id, model_id=action_model_id, kind="continue")

            completed_chapters = self.get_current_chapters(task_id)[:completed_count]
            draft_seed_map = self._load_draft_seed_map(
                task_id,
                list(range(completed_count + 1, completed_count + effective_count + 1)),
            )
            try:
                chapter_pair = self.engine.generate_chapter_pair(
                    spec=self._with_model_id(
                        task.normalized_spec or self._initial_state(task)["input_payload"],
                        action_model_id,
                    ),
                    story_plan=task.story_plan.model_dump(mode="json"),
                    batch_index=completed_count,
                    completed_chapters=completed_chapters,
                    reference_text="\n\n".join(source.content for source in task.sources),
                    model=action_model_id,
                    requested_batch_size=effective_count,
                    draft_seeds=draft_seed_map,
                )
                chapter_drafts = [ChapterDraft.model_validate(item) for item in chapter_pair]
                for chapter in chapter_drafts:
                    self._write_chapter_file(
                        task_id,
                        chapter_number=chapter.number,
                        title=chapter.title,
                        summary=chapter.summary,
                        content=chapter.content,
                    )
                    upsert_outline_chapter_draft(
                        task_id,
                        chapter_number=chapter.number,
                        title=chapter.title,
                        summary=chapter.summary,
                        batch_no=batch.batch_no,
                        md_ref=f"tasklog/runs/{task_id}/chapters/{chapter.number:02d}.md",
                        json_ref=f"tasklog/runs/{task_id}/chapters/{chapter.number:02d}.json",
                        content=chapter.content,
                    )

                from app.storage.db_repository import mark_batch_waiting_review

                mark_batch_waiting_review(task_id, batch.batch_no, persisted_count=len(chapter_drafts))
                update_project_status(
                    task_id,
                    status=TaskStatus.WAITING_CHAPTER_REVIEW.value,
                    completed_chapter_count=completed_count,
                    next_chapter_number=completed_count + 1,
                    current_generating_chapter_number=None,
                )
                review = ReviewPayload(
                    type="chapter_pair_review",
                    version="v1",
                    summary="请审核当前章节批次。",
                    chapter_pair=chapter_drafts,
                    batch_index=completed_count,
                    completed_count=completed_count,
                    total_chapters=int(project.planned_chapter_count or len(task.story_plan.chapter_plan)),
                )
                snapshot = self.store.set_waiting_chapter_review(task_id, review)
                return self._safe_sync_supervisor_plan(task_id, fallback=snapshot)
            except Exception as exc:
                mark_batch_failed(task_id, batch.batch_no)
                update_project_status(
                    task_id,
                    status=TaskStatus.WAITING_MANUAL_ACTION.value,
                    completed_chapter_count=completed_count,
                    next_chapter_number=completed_count + 1,
                    active_batch_no=None,
                    active_continue_request_id="",
                    blocked_from_status=TaskStatus.READY_FOR_BATCH.value,
                    current_generating_chapter_number=self._current_generating_chapter_number_from_error(task_id, completed_count + 1),
                )
                snapshot = self.store.set_waiting_manual_action(
                    task_id,
                    f"继续创作失败：{exc}",
                    payload={
                        "summary": "继续创作失败，但当前任务仍可恢复后重试。",
                        "display_level": "public",
                        "reason": "draft_batch_generation_failed",
                    },
                )
                return self._safe_sync_supervisor_plan(task_id, fallback=snapshot)
        finally:
            self._leave_active_run(task_id)

    def get_current_chapters(self, task_id: str) -> list[dict[str, Any]]:
        """获取当前任务的章节正文列表（用于工作台预览）。"""
        task = self.store.get(task_id)
        task_dir = self.store._task_dir(task)
        chapters_dir = task_dir / "chapters"
        index_file = chapters_dir / "index.json"
        if not index_file.exists():
            return []
        try:
            index_data = json.loads(index_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, ValueError):
            return []
        chapters: list[dict[str, Any]] = []
        for item in index_data:
            num = item.get("number")
            safe_num = f"{num:02d}" if num else "00"
            chapter_file = chapters_dir / f"{safe_num}.json"
            if chapter_file.exists():
                try:
                    chapters.append(json.loads(chapter_file.read_text(encoding="utf-8")))
                except (json.JSONDecodeError, ValueError):
                    chapters.append(item)
            else:
                chapters.append(item)
        return chapters

    def _write_chapter_file(
        self,
        task_id: str,
        chapter_number: int | None,
        title: str,
        summary: str,
        content: str,
    ) -> None:
        """将章节正文写入磁盘文件。"""
        task = self.store.get(task_id)
        task_dir = self.store._task_dir(task)
        chapters_dir = task_dir / "chapters"
        chapters_dir.mkdir(parents=True, exist_ok=True)
        safe_num = f"{chapter_number:02d}" if chapter_number else "00"
        chapter_md_file = chapters_dir / f"{safe_num}.md"
        chapter_file = chapters_dir / f"{safe_num}.json"
        chapter_data = {
            "number": chapter_number,
            "title": title,
            "summary": summary,
            "content": content,
        }
        chapter_md_file.write_text(f"# {title}\n\n{content}\n", encoding="utf-8")
        chapter_file.write_text(json.dumps(chapter_data, ensure_ascii=False, indent=2), encoding="utf-8")
        # 更新 chapters/index.json（加锁防止读-改-写竞态）
        lock = self._chapter_file_locks.setdefault(task_id, threading.Lock())
        with lock:
            index_file = chapters_dir / "index.json"
            index_data: list[dict[str, Any]] = []
            if index_file.exists():
                try:
                    index_data = json.loads(index_file.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, ValueError):
                    index_data = []
            # 去重后追加
            existing = {item.get("number") for item in index_data}
            if chapter_number not in existing:
                index_data.append({"number": chapter_number, "title": title, "summary": summary})
                index_data.sort(key=lambda x: x.get("number") or 0)
            index_file.write_text(json.dumps(index_data, ensure_ascii=False, indent=2), encoding="utf-8")

    def _extract_chapter_content(self, conversation_history: list[dict[str, Any]]) -> str | None:
        """从对话历史中提取最后一轮 assistant 消息中的章节正文。"""
        for item in reversed(conversation_history):
            if not isinstance(item, dict):
                continue
            if item.get("role") != "assistant":
                continue
            content = str(item.get("content") or "").strip()
            if not content:
                continue
            # 尝试解析 JSON
            try:
                parsed = json.loads(content)
                if isinstance(parsed, dict) and parsed.get("content"):
                    return str(parsed["content"])
            except (json.JSONDecodeError, ValueError):
                pass
        return None

    def _chapter_storage_path(self, task_id: str, chapter_number: int) -> Path:
        task = self.store.get(task_id)
        return self.store._task_dir(task) / "chapters" / f"{chapter_number:02d}.json"

    def _load_chapter_file_payload(self, task_id: str, chapter_number: int) -> dict[str, Any]:
        path = self._chapter_storage_path(task_id, chapter_number)
        return json.loads(path.read_text(encoding="utf-8"))

