from __future__ import annotations

import asyncio
import threading
from datetime import timedelta
from pathlib import Path
from typing import Any

from langgraph.types import Command

from app.context.cache_store import FileBackedCacheStore, InMemoryCacheStore, LayeredCacheStore
from app.context.manager import ContextManager
from app.domain.models import (
    AgentRunRecord,
    ArchiveTaskDetailResponse,
    ArchiveTaskListResponse,
    ArtifactItem,
    ChapterDraft,
    DashboardResponse,
    DraftResult,
    ResultResponse,
    ReviewPayload,
    ReviewResponse,
    SourceAsset,
    StoryPlan,
    SubtaskRecord,
    SubtaskStatus,
    TaskCreateRequest,
    TaskMode,
    TaskRecord,
    TaskStatus,
    TaskSummary,
    TaskEvent,
    WorkspaceResponse,
    utc_now,
)
from app.graph.main_graph import (
    _build_references,
    _chapter_pair_instruction,
    _outline_instruction,
    _resolve_model_profile,
    build_graph,
)
from app.graph.supervisor_graph import build_initial_supervisor_plan
from app.llm.model_catalog import ModelCatalogService
from app.llm.story_engine import (
    StoryEngine,
    reset_exchange_callback,
    reset_progress_callback,
    set_exchange_callback,
    set_progress_callback,
)
from app.storage.task_store import TaskLogStore


class TaskService:
    _STALE_RUN_AFTER = timedelta(minutes=10)

    def __init__(
        self,
        store: TaskLogStore,
        engine: StoryEngine,
        model_catalog: ModelCatalogService | None = None,
        context_manager: ContextManager | None = None,
        auto_review: bool = False,
        auto_review_policy: dict[str, Any] | None = None,
    ) -> None:
        self.store = store
        self.engine = engine
        self.model_catalog = model_catalog or ModelCatalogService(
            settings=engine.settings,
            gateway_client=engine.gateway_client,
        )
        self.context_manager = context_manager or ContextManager(
            cache_store=LayeredCacheStore(
                [
                    InMemoryCacheStore(ttl_seconds=1800),
                    FileBackedCacheStore(Path(self.store.root_dir) / "cache" / "context", ttl_seconds=86400),
                ]
            )
        )
        self.auto_review = auto_review
        self.auto_review_policy = auto_review_policy or {}
        checkpoint_db_path = str(Path(self.store.root_dir) / "checkpoints.db")
        self.graph = build_graph(
            engine,
            context_manager=self.context_manager,
            model_catalog=self.model_catalog,
            history_loader=self._load_message_history,
            checkpoint_db_path=checkpoint_db_path,
            auto_review=auto_review,
            auto_review_policy=self.auto_review_policy,
        )
        self._active_runs: set[str] = set()
        self._run_lock = threading.Lock()

        # 初始化 SQLite 业务数据库
        from app.storage.database import init_db
        init_db(str(Path(self.store.root_dir) / "data.db"))

        # 启动时同步运行时默认模型到 StoryEngine
        runtime_default = self.model_catalog._effective_default_model()
        if self.model_catalog._runtime_default_model and hasattr(self.engine, "set_runtime_default_model"):
            self.engine.set_runtime_default_model(runtime_default)

    def create_task(self, payload: TaskCreateRequest) -> TaskRecord:
        task = self.store.create_task(payload)
        task.supervisor_plan = build_initial_supervisor_plan(payload)
        if task.auto_review and not task.auto_review_policy:
            task.auto_review_policy = dict(self.auto_review_policy)
        task = self.store.save(task)
        return self._sync_supervisor_plan(task.id)

    def add_source(self, task_id: str, filename: str, media_type: str, content: str) -> TaskRecord:
        source = SourceAsset(filename=filename, media_type=media_type, content=content)
        return self.store.add_source(task_id, source)

    def get_task(self, task_id: str) -> TaskRecord:
        return self.store.get(task_id)

    def cancel_task(self, task_id: str, comment: str = "") -> TaskRecord:
        """取消一个正在运行或等待审核的任务。"""
        # 检查任务是否在活跃运行中，如果是则先移除
        with self._run_lock:
            was_active = task_id in self._active_runs
            if was_active:
                self._active_runs.discard(task_id)
        record = self.store.cancel_task(task_id, comment=comment)
        self._sync_supervisor_plan(task_id)
        return record

    def delete_task(self, task_id: str) -> dict[str, str]:
        """删除一个已取消/已完成/失败的任务（不能删除运行中的任务）。"""
        # 再次确认任务不在活跃运行中
        with self._run_lock:
            if task_id in self._active_runs:
                raise ValueError("任务正在运行中，请先取消后再删除。")
        return self.store.delete_task(task_id)

    def run_task(self, task_id: str) -> TaskRecord:
        task = self.store.get(task_id)
        if task.status not in {TaskStatus.CREATED, TaskStatus.SOURCES_INGESTED}:
            raise ValueError("只有新建任务或已上传素材的任务才能开始生成。")
        snapshot = self.store.mark_stage(
            task_id,
            status=TaskStatus.PLANNING,
            stage="planning",
            progress=max(task.progress, 5),
            message="任务已进入后台执行，正在整理创作要求。",
            event_type="task.queued",
        )
        snapshot = self._sync_supervisor_plan(task_id)
        self._start_background(task_id, self._run_task_sync, task_id)
        return snapshot

    def resume_task(self, task_id: str, approved: bool, comment: str) -> TaskRecord:
        task = self.store.get(task_id)
        valid_statuses = {
            TaskStatus.WAITING_OUTLINE_REVIEW,
            TaskStatus.WAITING_CHAPTER_REVIEW,
            TaskStatus.WAITING_VERIFICATION_REVIEW,
        }
        if task.status not in valid_statuses or task.pending_review is None:
            raise ValueError("当前任务没有待恢复的审核节点。")
        review_type = task.pending_review.type

        if review_type == "chapter_pair_review":
            note = comment.strip() or (
                "人工审核已通过，任务转入后台处理。"
                if approved
                else "人工审核已驳回，正在修订章节。"
            )
            snapshot = self.store.mark_stage(
                task_id,
                status=TaskStatus.DRAFTING,
                stage="drafting",
                progress=max(task.progress, 60),
                message=note,
                event_type="review.submitted",
                unit_id=f"chapter-pair-{task.pending_review.batch_index or 0}",
            )
        elif review_type == "verification_review":
            note = comment.strip() or (
                "人工审核已通过，任务转入后台处理。"
                if approved
                else "人工审核已驳回，正在根据验证意见修复。"
            )
            snapshot = self.store.mark_stage(
                task_id,
                status=TaskStatus.DRAFTING,
                stage="verification",
                progress=max(task.progress, 92),
                message=note,
                event_type="review.submitted",
                unit_id="verification",
            )
        else:
            note = comment.strip() or (
                "人工审核已通过，任务转入后台处理。"
                if approved
                else "人工审核已驳回，正在修订大纲。"
            )
            snapshot = self.store.mark_stage(
                task_id,
                status=TaskStatus.DRAFTING if approved else TaskStatus.PLANNING,
                stage="drafting" if approved else "planning",
                progress=60 if approved else max(task.progress, 56),
                message=note,
                event_type="review.submitted",
                unit_id="outline",
            )
        snapshot = self._sync_supervisor_plan(task_id)
        self._start_background(task_id, self._resume_task_sync, task_id, approved, comment)
        return snapshot

    def list_artifacts(self, task_id: str) -> list[ArtifactItem]:
        return self.store.get(task_id).artifacts

    def list_models(self) -> list[dict[str, Any]]:
        return self.model_catalog.list_models()

    def list_models_payload(self) -> dict[str, Any]:
        return self.model_catalog.list_models_payload()

    def update_default_model(self, model_id: str) -> dict[str, Any]:
        """更新默认模型，同时持久化到配置文件并更新运行时状态。"""
        result = self.model_catalog.update_default_model(model_id)
        # 同步到 StoryEngine，使其立即生效
        self.engine.set_runtime_default_model(model_id)
        return result

    def get_dashboard(self) -> DashboardResponse:
        tasks = sorted(self.store._tasks.values(), key=lambda item: item.updated_at, reverse=True)
        dead_statuses = {
            TaskStatus.WAITING_MANUAL_ACTION,
            TaskStatus.CANCELLED,
            TaskStatus.ASSEMBLING,
        }
        continue_statuses = {
            TaskStatus.CREATED,
            TaskStatus.SOURCES_INGESTED,
            TaskStatus.WAITING_OUTLINE_REVIEW,
            TaskStatus.WAITING_CHAPTER_REVIEW,
            TaskStatus.WAITING_VERIFICATION_REVIEW,
        }
        running_statuses = {
            TaskStatus.PLANNING,
            TaskStatus.DRAFTING,
        }
        running_tasks = [
            self._to_summary(task)
            for task in tasks
            if task.status in running_statuses and not self._is_stale_running_task(task)
        ]
        continue_tasks = [self._to_summary(task) for task in tasks if task.status in continue_statuses]
        failed_tasks = [self._to_summary(task) for task in tasks if task.status is TaskStatus.FAILED]
        failed_tasks.extend(self._to_summary(task) for task in tasks if task.status in dead_statuses)
        failed_tasks.extend(self._to_stale_run_summary(task) for task in tasks if self._is_stale_running_task(task))
        completed_tasks = [
            self._to_summary(task)
            for task in tasks
            if task.status is TaskStatus.COMPLETED and task.storage_state != "archive"
        ]
        return DashboardResponse(
            continue_tasks=continue_tasks,
            running_tasks=running_tasks,
            failed_tasks=failed_tasks,
            completed_tasks=completed_tasks,
            model_summary=self._model_summary(),
            system_summary={
                "active_runs": len(running_tasks),
                "archived_runs": sum(1 for task in tasks if task.storage_state == "archive"),
            },
            continue_total=len(continue_tasks),
            running_total=len(running_tasks),
            failed_total=len(failed_tasks),
            completed_total=len(completed_tasks),
        )

    def get_archive_list(self, page: int = 1, page_size: int = 10) -> ArchiveTaskListResponse:
        paginated_tasks, total = self.store.list_archive_tasks_paginated(page, page_size)
        items = [self._to_summary(task) for task in paginated_tasks]
        total_pages = (total + page_size - 1) // page_size if total > 0 else 0
        return ArchiveTaskListResponse(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
        )

    def get_archive_detail(self, task_id: str) -> ArchiveTaskDetailResponse:
        task = self.store.get(task_id)
        if task.storage_state != "archive":
            raise ValueError("当前任务尚未归档。")
        if task.draft_result is None:
            raise ValueError("归档任务缺少正文结果。")
        return ArchiveTaskDetailResponse(
            meta=self._to_summary(task),
            request_preview=self._request_preview(task),
            sources=task.sources,
            recent_events=task.events[-20:],
            result_summary=task.draft_result.summary,
            result_markdown=self._result_markdown(task.draft_result),
            result_md_ref=self._file_ref(task, "result.md"),
            chapter_index=[
                {
                    "number": chapter.number,
                    "title": chapter.title,
                    "summary": chapter.summary,
                    "md_ref": self._artifact_ref(task, f"chapter-{chapter.number:02d}.md"),
                    "content": chapter.content,
                }
                for chapter in task.draft_result.chapters
            ],
            artifact_index=[self._artifact_index_item(task, artifact) for artifact in task.artifacts],
            history_index=self._review_history(task),
        )

    def get_workspace(self, task_id: str) -> WorkspaceResponse:
        task = self.store.get(task_id)
        recent_events = task.events[-20:]
        return WorkspaceResponse(
            meta=self._to_summary(task),
            recent_events=recent_events,
            active_trace_summary=recent_events[-1].message if recent_events else None,
            available_tabs=self._workspace_tabs(task),
            request_preview=self._request_preview(task),
            context_status=self._load_context_status(task.id),
            response_cache_status=self._load_response_cache_status(task),
            sources=task.sources,
            supervisor_plan=task.supervisor_plan,
            agent_runs=task.agent_runs,
        )

    def get_supervisor_plan(self, task_id: str) -> dict[str, Any]:
        task = self.store.get(task_id)
        if task.supervisor_plan is None:
            raise ValueError("当前任务还没有 supervisor 规划结果。")
        payload = task.supervisor_plan.model_dump(mode="json")
        payload["agent_runs"] = [item.model_dump(mode="json") for item in task.agent_runs]
        return payload

    def get_review(self, task_id: str) -> ReviewResponse:
        task = self.store.get(task_id)
        review = task.pending_review
        auto_review_trace = task.auto_review_trace or []
        if review is None:
            if task.story_plan is None:
                raise ValueError("当前任务还没有可审核的内容。")
            historical_review_type = self._historical_review_type(task)
            outline_ref = self._file_ref(task, "outline.md")
            return ReviewResponse(
                meta=self._to_summary(task),
                review_type=historical_review_type,
                review_version="v1",
                summary="当前任务已有大纲，可查看历史审核结果。",
                risk_flags=[],
                outline_markdown=self._outline_markdown(task.story_plan) if historical_review_type != "verification_review" else None,
                outline_md_ref=outline_ref if historical_review_type != "verification_review" else None,
                revision_count=0,
                review_history=self._review_history(task),
                auto_review_trace=auto_review_trace,
            )

        review_type = review.type
        outline_ref = self._file_ref(task, "outline.md")

        if review_type == "chapter_pair_review":
            chapter_pair_data = review.chapter_pair or []
            chapter_index = [
                {
                    "number": ch.number,
                    "title": ch.title,
                    "summary": ch.summary,
                    "content": ch.content,
                }
                for ch in chapter_pair_data
            ]
            return ReviewResponse(
                meta=self._to_summary(task),
                review_type="chapter_pair_review",
                review_version=review.version,
                summary=review.summary,
                risk_flags=review.risk_flags,
                outline_markdown=self._outline_markdown(task.story_plan) if task.story_plan else None,
                outline_md_ref=outline_ref,
                review_history=self._review_history(task),
                auto_review_trace=auto_review_trace,
                chapter_pair=chapter_index,
                batch_index=review.batch_index,
                completed_count=review.completed_count,
                total_chapters=review.total_chapters,
                chapter_pair_revision_count=review.chapter_pair_revision_count,
            )

        elif review_type == "verification_review":
            return ReviewResponse(
                meta=self._to_summary(task),
                review_type="verification_review",
                review_version=review.version,
                summary=review.summary,
                risk_flags=review.risk_flags,
                outline_markdown=None,
                outline_md_ref=None,
                review_history=self._review_history(task),
                auto_review_trace=auto_review_trace,
                verification_report=review.verification_report,
                verification_revision_count=review.verification_revision_count,
            )

        # 默认：大纲审核
        return ReviewResponse(
            meta=self._to_summary(task),
            review_type="outline_review",
            review_version=review.version,
            summary=review.summary,
            risk_flags=review.risk_flags,
            outline_markdown=self._outline_markdown(task.story_plan) if task.story_plan else None,
            outline_md_ref=outline_ref,
            revision_count=review.revision_count,
            review_history=self._review_history(task),
            auto_review_trace=auto_review_trace,
        )

    def get_result(self, task_id: str) -> ResultResponse:
        task = self.store.get(task_id)
        if task.draft_result is None:
            raise ValueError("当前任务还没有可查看的结果。")
        return ResultResponse(
            meta=self._to_summary(task),
            result_summary=task.draft_result.summary,
            result_markdown=self._result_markdown(task.draft_result),
            result_md_ref=self._file_ref(task, "result.md"),
            chapter_index=[
                {
                    "number": chapter.number,
                    "title": chapter.title,
                    "summary": chapter.summary,
                    "md_ref": self._artifact_ref(task, f"chapter-{chapter.number:02d}.md"),
                    "content": chapter.content,
                }
                for chapter in task.draft_result.chapters
            ],
            artifact_index=[
                self._artifact_index_item(task, artifact)
                for artifact in task.artifacts
            ],
            history_index=self._review_history(task),
        )

    def read_file_text(self, task_id: str, relative_path: str) -> str:
        return self.store.read_text(task_id, relative_path)

    def subscribe_task_events(self, task_id: str) -> asyncio.Queue[dict[str, Any]]:
        self.store.get(task_id)
        return self.store.subscribe(task_id)

    def unsubscribe_task_events(self, task_id: str, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self.store.unsubscribe(task_id, queue)

    def build_sse_snapshot(self, task_id: str) -> dict[str, Any]:
        task = self.store.get(task_id)
        latest_event = task.events[-1].model_dump(mode="json") if task.events else None
        return {
            "task_id": task.id,
            "meta": self._to_summary(task).model_dump(mode="json"),
            "latest_event": latest_event,
        }

    def _initial_state(self, task: TaskRecord) -> dict[str, Any]:
        reference_text = "\n\n".join(source.content for source in task.sources)
        return {
            "task_id": task.id,
            "input_payload": {
                "mode": task.mode.value,
                "model_id": task.model_id,
                "prompt": task.input.prompt,
                "genre": task.input.genre,
                "style": task.input.style,
                "target_words": task.input.target_words,
                "audience": task.input.audience,
                "banned": task.input.banned,
                "title_hint": task.input.title_hint,
            },
            "reference_text": reference_text,
            "source_assets": [source.model_dump(mode="json") for source in task.sources],
            "auto_review": task.auto_review or self.auto_review,
            "auto_review_policy": task.auto_review_policy or dict(self.auto_review_policy),
        }

    def _config(self, task_id: str) -> dict[str, Any]:
        return {"configurable": {"thread_id": task_id}, "recursion_limit": 100}

    def _graph_state_values(self, task_id: str) -> dict[str, Any]:
        try:
            snapshot = self.graph.get_state(self._config(task_id))
        except Exception:
            return {}
        return snapshot.values if snapshot and hasattr(snapshot, "values") and isinstance(snapshot.values, dict) else {}

    def _load_context_snapshot(self, task_id: str, *, stage: str, snapshot_name: str) -> dict[str, Any] | None:
        relative_path = f"context/{stage}/{snapshot_name}.json"
        try:
            return self.store.read_json(task_id, relative_path)
        except Exception:
            return None

    def _load_completed_chapters_for_resume(self, task_id: str, completed_count: int) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for number in range(1, completed_count + 1):
            relative_path = f"context/drafting/chapter-{number:02d}-history.json"
            try:
                history = self.store.read_json(task_id, relative_path)
            except Exception:
                continue
            messages = history.get("messages") if isinstance(history, dict) else []
            if not isinstance(messages, list) or not messages:
                continue
            assistant_content = str(messages[-1].get("content") or "")
            if not assistant_content.strip():
                continue
            try:
                payload = ChapterDraft.model_validate_json(assistant_content)
            except Exception:
                continue
            items.append(payload.model_dump(mode="json"))
        return items

    def _resume_seed_state(self, task: TaskRecord) -> tuple[dict[str, Any], str] | None:
        if task.pending_review is None:
            return None
        seed = self._initial_state(task)
        if task.normalized_spec:
            seed["normalized_spec"] = dict(task.normalized_spec)
        if task.story_plan is not None:
            seed["story_plan"] = task.story_plan.model_dump(mode="json")

        review = task.pending_review
        if review.type == "outline_review":
            outline_snapshot = self._load_context_snapshot(task.id, stage="planning", snapshot_name="outline-context")
            if isinstance(outline_snapshot, dict):
                seed["outline_context_snapshot"] = outline_snapshot
                packet = outline_snapshot.get("packet")
                if isinstance(packet, dict):
                    seed["outline_context_packet"] = packet
            elif task.story_plan is not None:
                state_for_refs = {
                    "reference_text": seed.get("reference_text", ""),
                    "source_assets": seed.get("source_assets", []),
                }
                snapshot = self.context_manager.build_snapshot(
                    task_id=task.id,
                    stage="planning",
                    instruction=_outline_instruction(seed.get("normalized_spec") or {}),
                    model_profile=_resolve_model_profile(self.model_catalog, task.model_id),
                    references=_build_references(state_for_refs),
                    memory_items=[],
                )
                seed["outline_context_packet"] = snapshot.packet.model_dump(mode="json")
                seed["outline_context_snapshot"] = snapshot.model_dump(mode="json")
            seed["outline_revision_count"] = review.revision_count
            return seed, "plan_story"

        if review.type == "chapter_pair_review":
            completed_count = review.completed_count or 0
            completed_chapters = self._load_completed_chapters_for_resume(task.id, completed_count)
            chapter_pair = [item.model_dump(mode="json") for item in (review.chapter_pair or [])]
            seed.update(
                {
                    "batch_index": review.batch_index or 0,
                    "total_chapters": review.total_chapters or (len(task.story_plan.chapter_plan) if task.story_plan else 0),
                    "completed_count": completed_count,
                    "completed_chapters": completed_chapters,
                    "current_chapter_pair": chapter_pair,
                    "chapter_pair_revision_count": review.chapter_pair_revision_count,
                }
            )
            snapshot = self.context_manager.build_snapshot(
                task_id=task.id,
                stage="drafting",
                instruction=_chapter_pair_instruction(seed.get("normalized_spec") or {}, seed.get("story_plan")),
                model_profile=_resolve_model_profile(self.model_catalog, task.model_id),
                references=_build_references(
                    {
                        "reference_text": seed.get("reference_text", ""),
                        "source_assets": seed.get("source_assets", []),
                    }
                ),
                memory_items=[
                    *(f"世界观：{note}" for note in ((seed.get("story_plan") or {}).get("world_notes") or [])),
                    *(f"人物：{note}" for note in ((seed.get("story_plan") or {}).get("character_notes") or [])),
                    *(
                        f"章节计划：第{chapter.get('number')}章 {chapter.get('title')} - {chapter.get('goal')}"
                        for chapter in (((seed.get("story_plan") or {}).get("chapter_plan")) or [])
                        if isinstance(chapter, dict)
                    ),
                ],
            )
            seed["chapter_pair_context_packet"] = snapshot.packet.model_dump(mode="json")
            return seed, "draft_chapter_pair"

        if review.type == "verification_review":
            # 恢复 story_plan：优先从 task.story_plan，否则从 outline-history.json
            if task.story_plan:
                total = len(task.story_plan.chapter_plan)
            else:
                total = 0
                outline_history = self._load_context_snapshot(task.id, stage="planning", snapshot_name="outline-history")
                if isinstance(outline_history, dict):
                    messages = outline_history.get("messages") or []
                    for msg in reversed(messages):
                        if msg.get("role") == "assistant":
                            content = str(msg.get("content", "")).strip()
                            if content:
                                try:
                                    plan_data = StoryPlan.model_validate_json(content)
                                    seed["story_plan"] = plan_data.model_dump(mode="json")
                                    total = len(plan_data.chapter_plan)
                                except Exception:
                                    try:
                                        import json as _json
                                        plan_data = _json.loads(content)
                                        seed["story_plan"] = plan_data
                                        total = len(plan_data.get("chapter_plan", []))
                                    except Exception:
                                        pass
                                break
            seed.update(
                {
                    "completed_chapters": self._load_completed_chapters_for_resume(task.id, total),
                    "verification_report": review.verification_report or {},
                    "verification_revision_count": review.verification_revision_count,
                }
            )
            return seed, "verify_full_story"

        return None

    def _rehydrate_resume_state_if_needed(self, task: TaskRecord) -> None:
        values = self._graph_state_values(task.id)
        if values.get("input_payload"):
            return
        if not hasattr(self.graph, "update_state"):
            return
        seeded = self._resume_seed_state(task)
        if seeded is None:
            return
        seed_values, as_node = seeded
        self.graph.update_state(self._config(task.id), seed_values, as_node=as_node)

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
            self._emit_trace_summary(
                task_id,
                kind="spec",
                title="创作要求已标准化",
                detail="已整理用户诉求、风格、字数和参考材料，开始生成大纲。",
            )

        outline_context_snapshot = values.get("outline_context_snapshot")
        if isinstance(outline_context_snapshot, dict):
            self.store.write_context_snapshot(
                task_id,
                stage="planning",
                snapshot_name="outline-context",
                payload=outline_context_snapshot,
            )
            self._emit_trace_summary(
                task_id,
                kind="context",
                title="大纲上下文已装配",
                detail="已完成 planning 阶段上下文预算、压缩与缓存判定。",
                unit_id="outline-context",
            )

        if "__interrupt__" in result:
            story_plan_data = values.get("story_plan")
            review = ReviewPayload.model_validate(result["__interrupt__"][0].value)
            review_type = review.type
            auto_review_trace = values.get("auto_review_trace") or []

            if review_type == "outline_review":
                if not story_plan_data:
                    raise RuntimeError("工作流进入审核前未生成可用大纲。")
                story_plan = StoryPlan.model_validate(story_plan_data)
                record = self.store.set_waiting_review(task_id, review, story_plan, auto_review_trace)
                record = self._sync_supervisor_plan(task_id)
                self._emit_trace_summary(
                    task_id,
                    kind="outline",
                    title="大纲已生成",
                    detail="已完成故事骨架与章节规划，等待人工审核。",
                    unit_id="outline",
                )
                return record

            elif review_type == "chapter_pair_review":
                current_chapter_pair = values.get("current_chapter_pair") or []
                review.chapter_pair = [ChapterDraft.model_validate(ch) for ch in current_chapter_pair]
                batch_index = values.get("batch_index", 0)
                completed = values.get("completed_chapters") or []
                chapter_plan = (story_plan_data or {}).get("chapter_plan") or []
                review.batch_index = batch_index
                review.completed_count = len(completed)
                review.total_chapters = len(chapter_plan)
                record = self.store.set_waiting_chapter_review(task_id, review, auto_review_trace)
                record = self._sync_supervisor_plan(task_id)
                self._emit_trace_summary(
                    task_id,
                    kind="chapter",
                    title=f"章节对 {batch_index // 2 + 1} 已生成",
                    detail=f"第 {batch_index + 1}-{min(batch_index + 2, len(chapter_plan))} 章已起草，等待审核。",
                    unit_id=f"chapter-pair-{batch_index}",
                )
                return record

            elif review_type == "verification_review":
                verification_report = values.get("verification_report") or {}
                review.verification_report = verification_report
                record = self.store.set_waiting_verification_review(task_id, review, auto_review_trace)
                record = self._sync_supervisor_plan(task_id)
                self._emit_trace_summary(
                    task_id,
                    kind="verification",
                    title="全文验证完成",
                    detail=f"总分 {verification_report.get('overall_score', '?')}，发现 {len(verification_report.get('issues') or [])} 个问题。",
                    unit_id="verification",
                )
                return record

            # 兜底：未知类型按大纲审核处理
            if not story_plan_data:
                raise RuntimeError("工作流进入审核前未生成可用大纲。")
            story_plan = StoryPlan.model_validate(story_plan_data)
            self.store.set_waiting_review(task_id, review, story_plan, auto_review_trace)
            return self._sync_supervisor_plan(task_id)

        # 工作流正常结束
        story_plan_data = values.get("story_plan")
        if not story_plan_data:
            raise RuntimeError("工作流结束后未找到大纲结果。")
        story_plan = StoryPlan.model_validate(story_plan_data)
        if values.get("cancelled"):
            self.store.set_cancelled(task_id, story_plan, review_comment)
            return self._sync_supervisor_plan(task_id)

        draft_result_data = values.get("draft_result")
        if not draft_result_data:
            raise RuntimeError("工作流结束后未找到正文结果。")
        draft_result = DraftResult.model_validate(draft_result_data)
        artifacts = self._build_artifacts(story_plan, draft_result)
        record = self.store.set_completed(task_id, story_plan, draft_result, artifacts)
        record = self._sync_supervisor_plan(task_id)
        self._emit_trace_summary(
            task_id,
            kind="completed",
            title="正文生成完成",
            detail="章节已全部写完，正文与工件已归档。",
        )
        return record

    def _run_task_sync(self, task_id: str) -> TaskRecord:
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
            progress_token = set_progress_callback(self._build_progress_callback(task_id))
            exchange_token = set_exchange_callback(self._build_exchange_callback(task_id))
            try:
                result = self.graph.invoke(self._initial_state(task), config=self._config(task_id))
            finally:
                reset_progress_callback(progress_token)
                reset_exchange_callback(exchange_token)
            return self._sync_result(task_id, result)
        except Exception as exc:
            self.store.set_failed(task_id, f"运行失败：{exc}")
            self._sync_supervisor_plan(task_id)
            raise
        finally:
            self._leave_active_run(task_id)

    def _resume_task_sync(self, task_id: str, approved: bool, comment: str) -> TaskRecord:
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
                self._rehydrate_resume_state_if_needed(task)
                result = self.graph.invoke(
                    Command(resume={"approved": approved, "comment": comment}),
                    config=self._config(task_id),
                )
            finally:
                reset_progress_callback(progress_token)
                reset_exchange_callback(exchange_token)
            return self._sync_result(task_id, result, review_comment=comment)
        except Exception as exc:
            self.store.set_failed(task_id, f"恢复执行失败：{exc}")
            self._sync_supervisor_plan(task_id)
            raise
        finally:
            self._leave_active_run(task_id)

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

    def _to_summary(self, task: TaskRecord) -> TaskSummary:
        title = task.story_plan.working_title if task.story_plan else (task.input.title_hint or task.input.prompt[:24] or task.id)
        summary = task.events[-1].message if task.events else ""
        model_id = task.model_id or self.engine.settings.default_chat_model
        return TaskSummary(
            task_id=task.id,
            title=title,
            mode=task.mode,
            model_id=model_id,
            model_capabilities=self._model_capabilities(model_id),
            status=task.status,
            current_stage=task.current_stage,
            current_unit=task.current_unit,
            progress=task.progress,
            updated_at=task.updated_at,
            summary=summary,
            storage_state=task.storage_state,
            entry_refs={
                "meta_json": f"tasklog/{task.storage_state}/{task.id}/meta.json",
                "events_tail_json": f"tasklog/{task.storage_state}/{task.id}/events.tail.json",
                "result_json": f"tasklog/{task.storage_state}/{task.id}/result.json",
            },
        )

    def _model_summary(self) -> dict[str, Any]:
        models = self.model_catalog.list_models()
        supported_models = [item["id"] for item in models if isinstance(item, dict) and item.get("id")]
        default_model = self.model_catalog._effective_default_model()
        return {
            "default_model": default_model,
            "supported_models": supported_models,
        }

    def _workspace_tabs(self, task: TaskRecord) -> list[str]:
        tabs = ["request", "events"]
        if task.supervisor_plan is not None:
            tabs.append("supervisor")
        if task.story_plan is not None:
            tabs.append("outline")
        review_statuses = {
            TaskStatus.WAITING_OUTLINE_REVIEW,
            TaskStatus.WAITING_CHAPTER_REVIEW,
            TaskStatus.WAITING_VERIFICATION_REVIEW,
            TaskStatus.CANCELLED,
            TaskStatus.COMPLETED,
        }
        if task.pending_review is not None or task.status in review_statuses:
            tabs.append("review")
        if task.draft_result is not None:
            tabs.append("result")
        return tabs

    def _review_history(self, task: TaskRecord) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for event in task.events:
            if event.event_type == "review.waiting":
                items.append(
                    {
                        "version": "v1",
                        "action": "waiting",
                        "comment": event.message,
                        "created_at": event.created_at.isoformat(),
                    }
                )
            elif event.event_type == "review.submitted":
                items.append(
                    {
                        "version": "v1",
                        "action": "submitted",
                        "comment": event.message,
                        "created_at": event.created_at.isoformat(),
                    }
                )
            elif event.event_type == "task.review.rejected":
                items.append(
                    {
                        "version": "v1",
                        "action": "rejected",
                        "comment": event.message,
                        "created_at": event.created_at.isoformat(),
                    }
                )
            elif (
                event.event_type == "context.history.updated"
                and event.stage == "verification"
                and (event.payload or {}).get("exchange_label") == "fix-issues"
            ):
                items.append(
                    {
                        "version": "v1",
                        "action": "repairing",
                        "comment": "已进入验证问题修复阶段。",
                        "created_at": event.created_at.isoformat(),
                    }
                )
            elif event.event_type == "task.cancelled":
                items.append(
                    {
                        "version": "v1",
                        "action": "rejected",
                        "comment": event.message,
                        "created_at": event.created_at.isoformat(),
                    }
                )
            elif event.event_type == "task.completed":
                items.append(
                    {
                        "version": "v1",
                        "action": "approved",
                        "comment": "审核通过，已继续生成正文。",
                        "created_at": event.created_at.isoformat(),
                    }
                )
        return items

    def _outline_markdown(self, story_plan: StoryPlan) -> str:
        lines = [
            f"# {story_plan.working_title}",
            "",
            story_plan.logline,
            "",
            "## 世界观",
            "",
        ]
        lines.extend(f"- {item}" for item in story_plan.world_notes)
        lines.extend(["", "## 人物", ""])
        lines.extend(f"- {item}" for item in story_plan.character_notes)
        lines.extend(["", "## 章节计划", ""])
        for chapter in story_plan.chapter_plan:
            lines.append(f"- 第{chapter.number}章 {chapter.title}：{chapter.goal}")
        return "\n".join(lines) + "\n"

    def _result_markdown(self, draft_result: DraftResult) -> str:
        return f"# {draft_result.title}\n\n{draft_result.summary}\n\n{draft_result.body}\n"

    def _file_ref(self, task: TaskRecord, filename: str) -> str:
        return f"/api/tasks/{task.id}/files/{filename}"

    def _artifact_ref(self, task: TaskRecord, filename: str) -> str:
        return f"/api/tasks/{task.id}/files/artifacts/{filename}"

    def _artifact_index_item(self, task: TaskRecord, artifact: ArtifactItem) -> dict[str, Any]:
        md_ref = None
        json_ref = None
        if artifact.type == "story_plan":
            md_ref = self._file_ref(task, "outline.md")
            json_ref = self._file_ref(task, "outline.json")
        elif artifact.type == "manuscript":
            md_ref = self._file_ref(task, "result.md")
            json_ref = self._file_ref(task, "result.json")
        return {
            "id": artifact.id,
            "type": artifact.type,
            "name": artifact.name,
            "created_at": artifact.created_at.isoformat(),
            "md_ref": md_ref,
            "json_ref": json_ref,
        }

    def _historical_review_type(self, task: TaskRecord) -> str:
        for event in reversed(task.events):
            if event.event_type != "review.waiting":
                continue
            if event.stage == "waiting_verification_review":
                return "verification_review"
            if event.stage == "waiting_chapter_review":
                return "chapter_pair_review"
            if event.stage == "waiting_outline_review":
                return "outline_review"
        return "outline_review"

    def _build_progress_callback(self, task_id: str):
        def callback(event: dict[str, Any]) -> None:
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
                self._emit_trace_summary(
                    task_id,
                    kind="chapter",
                    title=f"开始生成第 {payload.get('chapter_number', '?')} 章",
                    detail=str(payload.get("chapter_title") or message),
                    unit_id=unit_id,
                )

        return callback

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
        chapter_file = chapters_dir / f"{safe_num}.json"
        chapter_data = {
            "number": chapter_number,
            "title": title,
            "summary": summary,
            "content": content,
        }
        chapter_file.write_text(json.dumps(chapter_data, ensure_ascii=False, indent=2), encoding="utf-8")
        # 更新 chapters/index.json
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

    def _sync_supervisor_plan(self, task_id: str) -> TaskRecord:
        task = self.store.get(task_id)
        if task.supervisor_plan is None:
            return task

        status_map = self._derive_supervisor_subtask_status(task)
        next_subtasks = [
            item.model_copy(update={"status": status_map.get(item.kind, item.status)}, deep=True)
            for item in task.supervisor_plan.subtasks
        ]
        task.supervisor_plan = task.supervisor_plan.model_copy(
            update={"subtasks": next_subtasks},
            deep=True,
        )
        return self.store.save(task)

    def _derive_supervisor_subtask_status(self, task: TaskRecord) -> dict[str, SubtaskStatus]:
        status_map = {
            "reference_analysis": SubtaskStatus.BLOCKED,
            "outline_planning": SubtaskStatus.BLOCKED,
            "chapter_writing": SubtaskStatus.BLOCKED,
            "chapter_review": SubtaskStatus.BLOCKED,
            "full_verification": SubtaskStatus.BLOCKED,
            "result_assembly": SubtaskStatus.BLOCKED,
        }

        if task.status in {TaskStatus.CREATED, TaskStatus.SOURCES_INGESTED}:
            status_map["reference_analysis"] = SubtaskStatus.READY
            return status_map

        if task.status is TaskStatus.PLANNING:
            status_map["reference_analysis"] = SubtaskStatus.COMPLETED
            status_map["outline_planning"] = SubtaskStatus.RUNNING
            return status_map

        if task.status is TaskStatus.WAITING_OUTLINE_REVIEW:
            status_map["reference_analysis"] = SubtaskStatus.COMPLETED
            status_map["outline_planning"] = SubtaskStatus.RUNNING
            return status_map

        if task.status is TaskStatus.WAITING_CHAPTER_REVIEW:
            status_map["reference_analysis"] = SubtaskStatus.COMPLETED
            status_map["outline_planning"] = SubtaskStatus.COMPLETED
            status_map["chapter_writing"] = SubtaskStatus.RUNNING
            status_map["chapter_review"] = SubtaskStatus.RUNNING
            return status_map

        if task.status is TaskStatus.WAITING_VERIFICATION_REVIEW:
            status_map["reference_analysis"] = SubtaskStatus.COMPLETED
            status_map["outline_planning"] = SubtaskStatus.COMPLETED
            status_map["chapter_writing"] = SubtaskStatus.COMPLETED
            status_map["chapter_review"] = SubtaskStatus.COMPLETED
            status_map["full_verification"] = SubtaskStatus.RUNNING
            return status_map

        if task.status is TaskStatus.ASSEMBLING:
            status_map["reference_analysis"] = SubtaskStatus.COMPLETED
            status_map["outline_planning"] = SubtaskStatus.COMPLETED
            status_map["chapter_writing"] = SubtaskStatus.COMPLETED
            status_map["chapter_review"] = SubtaskStatus.COMPLETED
            status_map["full_verification"] = SubtaskStatus.COMPLETED
            status_map["result_assembly"] = SubtaskStatus.RUNNING
            return status_map

        if task.status is TaskStatus.COMPLETED:
            return {key: SubtaskStatus.COMPLETED for key in status_map}

        if task.status is TaskStatus.DRAFTING:
            status_map["reference_analysis"] = SubtaskStatus.COMPLETED
            status_map["outline_planning"] = SubtaskStatus.COMPLETED
            if task.current_stage == "verification" or task.current_unit == "verification":
                status_map["chapter_writing"] = SubtaskStatus.COMPLETED
                status_map["chapter_review"] = SubtaskStatus.COMPLETED
                status_map["full_verification"] = SubtaskStatus.RUNNING
                return status_map

            status_map["chapter_writing"] = SubtaskStatus.RUNNING
            if isinstance(task.current_unit, str) and task.current_unit.startswith("chapter-pair-"):
                status_map["chapter_review"] = SubtaskStatus.RUNNING
            return status_map

        if task.status in {TaskStatus.CANCELLED, TaskStatus.FAILED}:
            derived = self._derive_supervisor_subtask_status_for_terminal(task)
            return derived

        return status_map

    def _derive_supervisor_subtask_status_for_terminal(self, task: TaskRecord) -> dict[str, SubtaskStatus]:
        status_map = self._derive_supervisor_subtask_status(
            task.model_copy(update={"status": TaskStatus.DRAFTING}, deep=True)
        )
        if task.current_stage in {"planning", "waiting_outline_review"}:
            status_map["outline_planning"] = SubtaskStatus.FAILED
        elif task.current_stage in {"drafting", "waiting_chapter_review"}:
            if isinstance(task.current_unit, str) and task.current_unit.startswith("chapter-pair-"):
                status_map["chapter_review"] = SubtaskStatus.FAILED
            else:
                status_map["chapter_writing"] = SubtaskStatus.FAILED
        elif task.current_stage in {"verification", "waiting_verification_review"}:
            status_map["full_verification"] = SubtaskStatus.FAILED
        elif task.current_stage == "completed":
            status_map["result_assembly"] = SubtaskStatus.FAILED
        return status_map

    def _enter_active_run(self, task_id: str) -> bool:
        with self._run_lock:
            if task_id in self._active_runs:
                return False
            self._active_runs.add(task_id)
            return True

    def _leave_active_run(self, task_id: str) -> None:
        with self._run_lock:
            self._active_runs.discard(task_id)

    def _start_background(self, task_id: str, target, *args: Any) -> None:
        def runner() -> None:
            try:
                target(*args)
            except Exception as exc:
                # 尝试标记任务为失败，防止永久卡在运行状态
                try:
                    self.store.set_failed(task_id, f"后台任务异常：{exc}")
                    self._sync_supervisor_plan(task_id)
                except Exception:
                    import logging
                    logging.getLogger(__name__).exception("后台任务异常且 set_failed 也失败，task_id=%s", task_id)

        threading.Thread(
            target=runner,
            name=f"task-worker-{task_id}",
            daemon=True,
        ).start()

    def _request_preview(self, task: TaskRecord) -> dict[str, Any]:
        model_id = task.model_id or self.engine.settings.default_chat_model
        return {
            "prompt": task.input.prompt,
            "model_id": model_id,
            "model_capabilities": self._model_capabilities(model_id),
            "genre": task.input.genre,
            "style": task.input.style,
            "target_words": task.input.target_words,
            "audience": task.input.audience,
            "banned": task.input.banned,
            "title_hint": task.input.title_hint,
        }

    def _model_capabilities(self, model_id: str) -> dict[str, Any] | None:
        profile = self.model_catalog.get_model_profile(model_id)
        capabilities = profile.get("capabilities")
        return capabilities if isinstance(capabilities, dict) else None

    def _load_context_status(self, task_id: str) -> dict[str, Any]:
        for relative_path in ("context/drafting/draft-context.json", "context/planning/outline-context.json"):
            try:
                snapshot = self.store.read_json(task_id, relative_path)
            except FileNotFoundError:
                continue
            return self._context_status_from_snapshot(snapshot)
        return {}

    def _load_response_cache_status(self, task: TaskRecord) -> dict[str, Any]:
        cache_event = next(
            (event for event in reversed(task.events) if event.event_type == "cache.hit"),
            None,
        )
        if cache_event is None:
            return {}
        payload = cache_event.payload if isinstance(cache_event.payload, dict) else {}
        status: dict[str, Any] = {
            "stage": cache_event.stage,
            "status": "cached",
            "summary": cache_event.message,
            "cache_hit": True,
            "cache_scope": "response_cache",
        }
        if payload.get("cache_key"):
            status["cache_key"] = payload.get("cache_key")
        if payload.get("model"):
            status["model"] = payload.get("model")
        if isinstance(payload.get("history_count"), int):
            status["history_count"] = payload.get("history_count")
        if payload.get("exchange_label"):
            status["exchange_label"] = payload.get("exchange_label")
        return status

    def _load_message_history(
        self,
        task_id: str,
        stage: str,
        filename: str,
    ) -> list[dict[str, str]]:
        try:
            payload = self.store.read_json(task_id, f"context/{stage}/{filename}.json")
        except FileNotFoundError:
            return []
        messages = payload.get("messages")
        if not isinstance(messages, list):
            return []
        normalized: list[dict[str, str]] = []
        for item in messages:
            if not isinstance(item, dict):
                continue
            role = str(item.get("role") or "user").strip() or "user"
            content = str(item.get("content") or "").strip()
            if not content:
                continue
            normalized.append({"role": role, "content": content})
        return normalized

    def _context_status_from_snapshot(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        budget = snapshot.get("budget") if isinstance(snapshot.get("budget"), dict) else {}
        packet = snapshot.get("packet") if isinstance(snapshot.get("packet"), dict) else {}
        compressed_references = snapshot.get("compressed_references")
        compressed_items = compressed_references if isinstance(compressed_references, list) else []
        original_chars = sum(
            int(item.get("original_chars") or 0)
            for item in compressed_items
            if isinstance(item, dict)
        )
        compressed_chars = sum(
            int(item.get("compressed_chars") or 0)
            for item in compressed_items
            if isinstance(item, dict)
        )
        compression_applied = any(
            bool(item.get("was_compressed"))
            for item in compressed_items
            if isinstance(item, dict)
        )
        ratio = None
        if original_chars > 0:
            ratio = round(max(original_chars - compressed_chars, 0) / original_chars, 4)
        max_input_tokens = budget.get("max_input_tokens")
        input_tokens = packet.get("estimated_input_tokens")
        window_usage_ratio = None
        if isinstance(max_input_tokens, int) and max_input_tokens > 0 and isinstance(input_tokens, int):
            window_usage_ratio = round(input_tokens / max_input_tokens, 4)
        return {
            "stage": snapshot.get("stage"),
            "status": "cached" if snapshot.get("cache_hit") else "fresh",
            "summary": "已完成上下文预算、压缩与装配。",
            "input_tokens": input_tokens,
            "current_tokens": input_tokens,
            "max_input_tokens": max_input_tokens,
            "window_usage_ratio": window_usage_ratio,
            "compression_applied": compression_applied,
            "compression_ratio": ratio,
            "compression_summary": f"已压缩 {sum(1 for item in compressed_items if isinstance(item, dict) and item.get('was_compressed'))} 份素材",
            "cache_hit": bool(snapshot.get("cache_hit")),
            "cache_scope": "runtime_context",
            "cache_key": snapshot.get("cache_key"),
            "cached_segments": len(compressed_items),
        }

    def _emit_trace_summary(
        self,
        task_id: str,
        *,
        kind: str,
        title: str,
        detail: str,
        unit_id: str | None = None,
    ) -> TaskEvent:
        task = self.store.get(task_id)
        return self.store.append_event(
            task_id,
            stage=task.current_stage,
            message=f"{title}：{detail}",
            event_type="trace.summary",
            unit_id=unit_id,
            payload={
                "kind": kind,
                "title": title,
                "detail": detail,
                "display_level": "public",
            },
        ).events[-1]

    def _is_stale_running_task(self, task: TaskRecord) -> bool:
        # 只有自动执行中的状态（planning/drafting/assembling）才可能过期
        # 等待用户操作的状态（waiting_*）不会过期
        if task.storage_state != "runs":
            return False
        if task.status not in {
            TaskStatus.PLANNING,
            TaskStatus.DRAFTING,
            TaskStatus.ASSEMBLING,
        }:
            return False
        if task.id in self._active_runs:
            return False
        return utc_now() - task.updated_at > self._STALE_RUN_AFTER

    def _to_stale_run_summary(self, task: TaskRecord) -> TaskSummary:
        summary = self._to_summary(task)
        summary.summary = f"该任务在 {summary.updated_at.isoformat()} 后未继续更新，已不计入活动运行数。"
        return summary
