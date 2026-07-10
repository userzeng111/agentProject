from __future__ import annotations

import json
from app.observability import get_logger
import os
import tempfile
import threading
from pathlib import Path
from typing import Any


from app.domain.models import (
    AutoReviewPolicy,
    ChapterDraft,
    ContinueDraftRequest,
    ReviewDecision,
    ReviewPayload,
    TaskRecord,
    TaskStatus,
)
from app.llm.story_engine import (
    reset_exchange_callback,
    reset_progress_callback,
    set_exchange_callback,
    set_progress_callback,
)

logger = get_logger(__name__)


class TaskServiceContinuationMixin:

    def queue_continue_task(self, task_id: str, payload: ContinueDraftRequest | dict[str, Any]) -> TaskRecord:
        """将继续创作请求放入后台执行，避免 HTTP 请求长时间阻塞。"""
        if not self._enter_active_run(task_id):
            raise ValueError("当前任务正在执行中，请勿重复提交。")
        started_background = False
        try:
            request = payload if isinstance(payload, ContinueDraftRequest) else ContinueDraftRequest.model_validate(payload)
            task = self.store.get(task_id)
            action_model_id = self._resolve_action_model_id(task, request.model_id)
            self._ensure_novel_project_seeded(task)

            from app.storage.db_repository import (
                get_active_batch,
                get_batch_by_request,
                get_novel_project,
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

            with self._run_lock:
                self._queued_continue_runs.add(task_id)
            snapshot = self.store.mark_stage(
                task_id,
                status=TaskStatus.READY_FOR_BATCH,
                stage="ready_for_batch",
                progress=max(task.progress, 58),
                message="继续创作已进入后台执行。",
                event_type="task.queued",
                unit_id=f"chapter-{completed_count + 1:02d}",
                payload={
                    "summary": "继续创作已进入后台执行",
                    "display_level": "public",
                    "continue_request_id": request.continue_request_id,
                    "requested_chapter_count": int(request.requested_chapter_count),
                    "effective_chapter_count": effective_count,
                    "next_chapter_number": completed_count + 1,
                },
            )
            snapshot = self._record_last_action(task_id, model_id=action_model_id, kind="continue")
            snapshot = self._sync_supervisor_plan(task_id)
            self._start_background(task_id, self.continue_task, task_id, request)
            started_background = True
            return snapshot
        finally:
            if not started_background:
                with self._run_lock:
                    self._queued_continue_runs.discard(task_id)
                self._leave_active_run(task_id)

    def continue_task(self, task_id: str, payload: ContinueDraftRequest | dict[str, Any]) -> TaskRecord:
        with self._run_lock:
            queued_run = task_id in self._queued_continue_runs
            if queued_run:
                self._queued_continue_runs.discard(task_id)
        if not queued_run and not self._enter_active_run(task_id):
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
                progress_callback = self._build_progress_callback(task_id, update_completed_on_saved=False)
                exchange_callback = self._build_exchange_callback(task_id)
                progress_token = set_progress_callback(progress_callback)
                exchange_token = set_exchange_callback(exchange_callback)
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
                        progress_callback=progress_callback,
                        requested_batch_size=effective_count,
                        draft_seeds=draft_seed_map,
                    )
                finally:
                    reset_progress_callback(progress_token)
                    reset_exchange_callback(exchange_token)
                if self._is_stop_requested(task_id) or self.store.get(task_id).status is TaskStatus.CANCELLED:
                    return self.store.get(task_id)
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
                # 自动审核：若开启则在入库前生成 Agent 评分与建议
                auto_review_trace: list[dict[str, Any]] | None = None
                if self._resolve_task_auto_review(task):
                    try:
                        from datetime import datetime, timezone
                        from app.llm.auto_reviewer import AutoReviewManager
                        from app.settings.config import get_settings

                        gateway_client = getattr(self.engine, "gateway_client", None)
                        policy = AutoReviewPolicy.model_validate(
                            self._resolve_auto_review_policy(task, action_model_id)
                        )
                        decision: ReviewDecision | None = None
                        _settings = get_settings()
                        if (
                            getattr(_settings, "dynamic_agent_review", False)
                            and gateway_client is not None
                            and hasattr(gateway_client, "complete_stream_sync")
                        ):
                            from app.agents.dynamic.bridge import DynamicReviewBridge
                            bridge = DynamicReviewBridge(
                                gateway_client=gateway_client,
                                max_workers=getattr(_settings, "auto_review_max_workers", 6),
                            )
                            decision = bridge.review(review, policy)
                        else:
                            manager = AutoReviewManager(
                                gateway_client=gateway_client,
                                max_workers=getattr(_settings, "auto_review_max_workers", 6),
                            )
                            decision = manager.review(review, policy)

                        if decision is not None:
                            summary_entry = {
                                "__summary__": True,
                                "trace_round": 1,
                                "review_type": "chapter_pair_review",
                                "revision_count": 0,
                                "batch_index": completed_count,
                                "created_at": datetime.now(timezone.utc).isoformat(),
                                "overall_score": decision.overall_score,
                                "approved": decision.approved,
                                "auto_escalated": decision.auto_escalated,
                                "comment": decision.comment,
                                "reasoning": decision.reasoning,
                                "critical_issues": decision.critical_issues,
                                "warnings": decision.warnings,
                            }
                            agent_items = [a.model_dump(mode="json") for a in decision.agent_trace]
                            auto_review_trace = [summary_entry, *agent_items]
                    except Exception as e:
                        logger.warning("章节自动审核失败，继续进入人工审核: %s", e)
                snapshot = self.store.set_waiting_chapter_review(task_id, review, auto_review_trace)
                return self._safe_sync_supervisor_plan(task_id, fallback=snapshot)
            except Exception as exc:
                if self._is_stop_requested(task_id) or self.store.get(task_id).status is TaskStatus.CANCELLED:
                    return self.store.get(task_id)
                # 扫描实际已写入的章节，避免 completed_chapter_count 与文件不一致
                actual_completed = len([c for c in self.get_current_chapters(task_id) if c.get("content")])
                mark_batch_failed(task_id, batch.batch_no)
                update_project_status(
                    task_id,
                    status=TaskStatus.WAITING_MANUAL_ACTION.value,
                    completed_chapter_count=actual_completed,
                    next_chapter_number=actual_completed + 1,
                    active_batch_no=None,
                    active_continue_request_id="",
                    blocked_from_status=TaskStatus.READY_FOR_BATCH.value,
                    current_generating_chapter_number=self._current_generating_chapter_number_from_error(task_id, actual_completed + 1),
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
        except (OSError, json.JSONDecodeError, ValueError):
            logger.warning("读取章节索引失败 task_id=%s path=%s", task_id, index_file, exc_info=True)
            return []
        if not isinstance(index_data, list):
            logger.warning("章节索引格式不正确 task_id=%s path=%s", task_id, index_file)
            return []
        chapters: list[dict[str, Any]] = []
        for item in index_data:
            if not isinstance(item, dict):
                logger.warning("章节索引条目格式不正确 task_id=%s path=%s", task_id, index_file)
                continue
            num = item.get("number")
            if not isinstance(num, int) or isinstance(num, bool) or num <= 0:
                logger.warning("章节索引条目格式不正确 task_id=%s path=%s", task_id, index_file)
                continue
            safe_num = f"{num:02d}"
            chapter_file = chapters_dir / f"{safe_num}.json"
            if chapter_file.exists():
                try:
                    chapters.append(json.loads(chapter_file.read_text(encoding="utf-8")))
                except (OSError, json.JSONDecodeError, ValueError):
                    logger.warning("读取章节文件失败 task_id=%s path=%s", task_id, chapter_file, exc_info=True)
                    chapters.append(item)
            else:
                chapters.append(item)
        return chapters

    def _atomic_write_text(self, path: Path, content: str) -> None:
        """使用临时文件 + rename 实现原子写入。"""
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

    def _rebuild_chapter_index_from_files(self, task_id: str, chapters_dir: Path) -> list[dict[str, Any]]:
        """从章节 JSON 文件重建轻量索引。"""
        rebuilt_by_number: dict[int, dict[str, Any]] = {}
        for chapter_file in sorted(chapters_dir.glob("*.json")):
            if chapter_file.name == "index.json":
                continue
            try:
                chapter_data = json.loads(chapter_file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError, ValueError):
                logger.warning("读取章节文件失败 task_id=%s path=%s", task_id, chapter_file, exc_info=True)
                continue
            if not isinstance(chapter_data, dict):
                logger.warning("章节文件格式不正确 task_id=%s path=%s", task_id, chapter_file)
                continue
            number = chapter_data.get("number")
            if not isinstance(number, int) or isinstance(number, bool) or number <= 0:
                logger.warning("章节文件格式不正确 task_id=%s path=%s", task_id, chapter_file)
                continue
            rebuilt_by_number[number] = {
                "number": number,
                "title": str(chapter_data.get("title") or f"第{number}章"),
                "summary": str(chapter_data.get("summary") or ""),
            }
        return sorted(rebuilt_by_number.values(), key=lambda item: item["number"])

    def _write_chapter_file(
        self,
        task_id: str,
        chapter_number: int | None,
        title: str,
        summary: str,
        content: str,
    ) -> None:
        """将章节正文原子写入磁盘文件。"""
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
        self._atomic_write_text(chapter_md_file, f"# {title}\n\n{content}\n")
        self._atomic_write_text(chapter_file, json.dumps(chapter_data, ensure_ascii=False, indent=2))
        # 更新 chapters/index.json（加锁防止读-改-写竞态）
        lock = self._chapter_file_locks.setdefault(task_id, threading.Lock())
        with lock:
            index_file = chapters_dir / "index.json"
            index_data: list[dict[str, Any]] = []
            rebuild_from_files = False
            if index_file.exists():
                try:
                    raw_index_data = json.loads(index_file.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError, ValueError):
                    logger.warning("读取章节索引失败 task_id=%s path=%s", task_id, index_file, exc_info=True)
                    raw_index_data = []
                    rebuild_from_files = True
                if isinstance(raw_index_data, list):
                    for item in raw_index_data:
                        if not isinstance(item, dict):
                            logger.warning("章节索引条目格式不正确 task_id=%s path=%s", task_id, index_file)
                            continue
                        num = item.get("number")
                        if not isinstance(num, int) or isinstance(num, bool) or num <= 0:
                            logger.warning("章节索引条目格式不正确 task_id=%s path=%s", task_id, index_file)
                            continue
                        index_data.append(item)
                else:
                    logger.warning("章节索引格式不正确 task_id=%s path=%s", task_id, index_file)
                    rebuild_from_files = True
            if rebuild_from_files:
                index_data = self._rebuild_chapter_index_from_files(task_id, chapters_dir)
            # 去重后追加
            if isinstance(chapter_number, int) and not isinstance(chapter_number, bool) and chapter_number > 0:
                by_number = {item["number"]: item for item in index_data}
                by_number[chapter_number] = {"number": chapter_number, "title": title, "summary": summary}
                index_data = sorted(by_number.values(), key=lambda item: item["number"])
            self._atomic_write_text(index_file, json.dumps(index_data, ensure_ascii=False, indent=2))

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
